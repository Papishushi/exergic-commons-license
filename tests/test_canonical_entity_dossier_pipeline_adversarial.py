#!/usr/bin/env python3
"""Pipeline-level adversarial tests for the canonical dossier contract."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import canonical_dossier_contract as contract  # noqa: E402
import check_canonical_entity_manifest_schema as manifest_schema  # noqa: E402
import check_canonical_entity_migration_preservation as preservation  # noqa: E402
import check_canonical_entity_provenance_snapshot as provenance  # noqa: E402

preservation.TYPE_DIR.clear()
preservation.TYPE_DIR.update(contract.TYPE_DIR)
preservation.ENTITY_SUFFIXES = set(contract.ENTITY_SUFFIXES)


class CanonicalPipelineAdversarialTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
        return proc.stdout.strip()

    def init_repo(self, root: Path) -> str:
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "tests@example.invalid")
        self.git(root, "config", "user.name", "Guard Tests")
        (root / "README").write_text("base\n", encoding="utf-8")
        self.git(root, "add", "README")
        self.git(root, "commit", "-q", "-m", "base")
        return self.git(root, "rev-parse", "HEAD")

    def write_schema(self, root: Path) -> None:
        schema_dir = root / "schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            REPO_ROOT / "schemas/canonical-entity-dossier-migration.schema.json",
            schema_dir / "canonical-entity-dossier-migration.schema.json",
        )
        shutil.copyfile(
            REPO_ROOT / "schemas/entity.schema.json",
            schema_dir / "entity.schema.json",
        )

    @staticmethod
    def write_state(root: Path, outcome: str) -> None:
        path = root / "dossiers/states/AAA.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\niso3: AAA\nprovisional_outcome: {outcome}\n---\n# Example State\n",
            encoding="utf-8",
        )

    @staticmethod
    def write_entity(root: Path, *, entity_id: str = "DEPLOYMENT-X", dossier_id: str | None = None) -> None:
        dossier_id = dossier_id or entity_id
        path = root / "knowledge/entities" / f"{entity_id}.jsonld"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "@context": "../../ontology/ecl-context.jsonld",
            "iri": f"ecl:{entity_id}",
            "id": entity_id,
            "type": "Deployment",
            "name": "Example Deployment",
            "dossier": f"../../dossiers/projects/{dossier_id}.md",
            "lastSubstantiveReview": "2026-08-20",
            "reviewClass": "manual"
        }, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def write_dossier(root: Path, dossier_id: str = "DEPLOYMENT-X", entity_id: str = "DEPLOYMENT-X") -> None:
        path = root / "dossiers/projects" / f"{dossier_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"id: ECL-{entity_id}\n"
            "entity: \"Example Deployment\"\n"
            "entity_type: deployment\n"
            "---\n# Example Deployment\n",
            encoding="utf-8",
        )

    @staticmethod
    def write_visuals(root: Path, entity_id: str = "DEPLOYMENT-X") -> None:
        directory = root / "dossiers/assets/generated"
        directory.mkdir(parents=True, exist_ok=True)
        for suffix in ("status", "evidence"):
            (directory / f"{entity_id}-{suffix}.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                f'<title>{entity_id} title</title><desc>Example Deployment {suffix}</desc>'
                '<text x="10" y="20">visible</text></svg>',
                encoding="utf-8",
            )

    @staticmethod
    def write_manifest(root: Path, *, version: int = 50, state_context: str = "S", visuals: list[str] | None = None) -> Path:
        entity_id = "DEPLOYMENT-X"
        visuals = visuals or list(contract.canonical_visuals(entity_id))
        payload = {
            "version": version,
            "date": "2026-08-20",
            "purpose": "Atomic post-v49 canonical dossier addition.",
            "migrationRule": "Identity arrives atomically with dedicated dossier; no governance inference.",
            "visualRule": "Derived visuals are deterministic migration-snapshot context only.",
            "maxMissingDedicatedDossiers": 0,
            "entities": [{
                "id": entity_id,
                "name": "Example Deployment",
                "type": "Deployment",
                "state": "AAA",
                "stateContext": state_context,
                "dossier": "dossiers/projects/DEPLOYMENT-X.md",
                "sourceDossier": "dossiers/states/AAA.md",
                "sourceGranularity": "direct",
                "visualModel": {
                    "source": "AAA State dossier + ABox identity",
                    "proposition": "Identity-only deployment dossier",
                    "boundary": "No governance inference"
                },
                "visuals": visuals
            }]
        }
        path = root / "knowledge/generated" / f"canonical-entity-dossier-migration-v{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def make_valid_atomic_v50(self, root: Path) -> str:
        self.init_repo(root)
        self.write_state(root, "S")
        self.git(root, "add", "dossiers/states/AAA.md")
        self.git(root, "commit", "-q", "-m", "state base")
        base = self.git(root, "rev-parse", "HEAD")
        self.write_schema(root)
        self.write_entity(root)
        self.write_dossier(root)
        self.write_visuals(root)
        self.write_manifest(root)
        return base

    def test_complete_atomic_v50_deployment_crosses_contract_preservation_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.make_valid_atomic_v50(root)
            self.assertEqual(contract.validate(root), [])
            self.assertEqual(manifest_schema.validate(root), [])
            errors, stats = preservation.validate(base, root)
            self.assertEqual(errors, [])
            self.assertEqual(stats["atomicNew"], 1)
            self.assertEqual(provenance.validate(base, root), [])

    def test_wrong_baseline_identity_to_dossier_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_entity(root, entity_id="DEPLOYMENT-A", dossier_id="DEPLOYMENT-B")
            self.write_dossier(root, dossier_id="DEPLOYMENT-B", entity_id="DEPLOYMENT-B")
            errors = contract.validate_universe(root)
            self.assertTrue(any("frontmatter id" in error for error in errors))

    def test_deployment_is_part_of_supported_canonical_universe(self) -> None:
        self.assertEqual(contract.TYPE_DIR["Deployment"], "projects")
        self.assertEqual(preservation.TYPE_DIR["Deployment"], "projects")

    def test_noncanonical_visual_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_manifest(root, visuals=[
                "dossiers/manual/DEPLOYMENT-X-status.svg",
                "dossiers/manual/DEPLOYMENT-X-evidence.svg",
            ])
            errors = contract.validate_manifest_visual_paths(root)
            self.assertTrue(any("visuals must be exactly" in error for error in errors))

    def test_malformed_manifest_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "knowledge/generated"
            directory.mkdir(parents=True)
            (directory / "canonical-entity-dossier-migration-v+50.json").write_text("{}\n", encoding="utf-8")
            _paths, errors = contract.strict_manifest_paths(root)
            self.assertTrue(any("invalid canonical migration manifest filename" in error for error in errors))

    def test_bool_manifest_version_is_rejected_as_non_integer_contract_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_schema(root)
            path = self.write_manifest(root)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["version"] = True
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            errors = manifest_schema.validate(root)
            self.assertTrue(any("version must be a JSON integer" in error for error in errors))

    def test_historical_state_context_snapshot_survives_living_outcome_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_repo(root)
            self.write_state(root, "S")
            self.write_visuals(root)
            self.write_manifest(root)
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "snapshot S")
            base = self.git(root, "rev-parse", "HEAD")
            self.write_state(root, "R")
            self.assertEqual(provenance.validate(base, root), [])

    def test_new_state_context_snapshot_must_match_current_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_repo(root)
            self.write_state(root, "R")
            self.git(root, "add", "dossiers/states/AAA.md")
            self.git(root, "commit", "-q", "-m", "R state")
            base = self.git(root, "rev-parse", "HEAD")
            self.write_visuals(root)
            self.write_manifest(root, state_context="S")
            errors = provenance.validate(base, root)
            self.assertTrue(any("newly appended stateContext snapshot" in error for error in errors))

    def test_unknown_or_svg_facsimile_formats_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "dossiers/evidence-images"
            directory.mkdir(parents=True)
            (directory / "photo.gif").write_bytes(b"gif")
            (directory / "wrapper.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.invalid/x.png"/></svg>',
                encoding="utf-8",
            )
            errors = contract.validate_evidence_image_surface(root)
            self.assertEqual(sum("unsupported source-facsimile file type" in e for e in errors), 2)

    def test_text_clipped_out_of_its_owning_region_cannot_count_as_visible_contract_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "dossiers/assets/generated"
            directory.mkdir(parents=True)
            (directory / "X-status.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<defs><clipPath id="box"><rect x="50" y="50" width="40" height="40"/></clipPath></defs>'
                '<text x="10" y="20" clip-path="url(#box)">REQUIRED</text></svg>',
                encoding="utf-8",
            )
            errors = contract.validate_generated_svg_clipping(root)
            self.assertTrue(any("outside clipPath" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
