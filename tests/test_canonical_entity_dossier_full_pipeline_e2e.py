#!/usr/bin/env python3
"""Full pipeline regression proving a real atomic post-v49 addition can pass every canonical guard."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class CanonicalV50FullPipelineTests(unittest.TestCase):
    maxDiff = None

    def run_python(self, root: Path, *args: str) -> str:
        proc = subprocess.run(
            [sys.executable, *args],
            cwd=root,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            self.fail(
                f"command failed ({proc.returncode}): {sys.executable} {' '.join(args)}\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        return proc.stdout

    def git(self, root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            self.fail(
                f"git failed ({proc.returncode}): git {' '.join(args)}\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        return proc.stdout.strip()

    @staticmethod
    def parse_frontmatter(path: Path) -> dict[str, str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}
        end = text.find("\n---\n", 4)
        if end < 0:
            return {}
        result: dict[str, str] = {}
        for line in text[4:end].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
        return result

    def choose_state(self, root: Path) -> tuple[str, str]:
        for path in sorted((root / "dossiers/states").glob("*.md")):
            fm = self.parse_frontmatter(path)
            iso3 = fm.get("iso3")
            outcome = fm.get("provisional_outcome")
            if iso3 and outcome in {"R", "S", "U", "N"}:
                return iso3, outcome
        self.fail("no State dossier with a canonical R/S/U/N outcome found")

    @staticmethod
    def assert_dir_bytes_equal(test: unittest.TestCase, left: Path, right: Path) -> None:
        left_files = {
            path.relative_to(left).as_posix(): path
            for path in left.rglob("*")
            if path.is_file()
        }
        right_files = {
            path.relative_to(right).as_posix(): path
            for path in right.rglob("*")
            if path.is_file()
        }
        test.assertEqual(set(left_files), set(right_files))
        for rel in sorted(left_files):
            test.assertEqual(
                left_files[rel].read_bytes(),
                right_files[rel].read_bytes(),
                f"byte mismatch for {rel}",
            )

    def test_atomic_v50_deployment_passes_the_entire_canonical_workflow_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(
                REPO_ROOT,
                root,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "build",
                    "__pycache__",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".venv",
                    "venv",
                ),
            )

            self.git(root, "init", "-q")
            self.git(root, "config", "user.email", "tests@example.invalid")
            self.git(root, "config", "user.name", "Canonical E2E")
            self.git(root, "add", "knowledge/entities", "knowledge/generated", "dossiers/states")
            self.git(root, "commit", "-q", "-m", "v49 base")
            base = self.git(root, "rev-parse", "HEAD")

            state, state_context = self.choose_state(root)
            entity_id = "DEPLOYMENT-E2E-V50"
            name = "Canonical E2E Deployment"

            entity_path = root / "knowledge/entities" / f"{entity_id}.jsonld"
            entity_path.write_text(
                json.dumps(
                    {
                        "@context": "../../ontology/ecl-context.jsonld",
                        "iri": f"ecl:{entity_id}",
                        "id": entity_id,
                        "type": "Deployment",
                        "name": name,
                        "dossier": f"../../dossiers/projects/{entity_id}.md",
                        "lastSubstantiveReview": "2026-08-20",
                        "reviewClass": "manual",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            dossier = root / "dossiers/projects" / f"{entity_id}.md"
            dossier.write_text(
                f'''---
id: ECL-{entity_id}
entity: "{name}"
entity_type: deployment
jurisdiction: {state}
evidence_cutoff: 2026-08-20
last_reviewed: 2026-08-20
review_stage: canonical-entity-dossier-v50-e2e
operative: false
---
# {name}

> **Canonical per-entity evidence/provenance record.** This dossier has no licensing effect by itself and carries no standalone `provisional_outcome`.

## Identity scope

Synthetic deployment identity used only by the adversarial pipeline fixture.

## State governance context

The `{state}` State dossier is recorded as migration-time **{state_context}** context only. That State outcome is not inherited by this Deployment.

![State dossier context for {name}](../assets/generated/{entity_id}-status.svg)

## Evidence record

This fixture proves that a post-v49 identity can arrive atomically with a dedicated dossier, ledger row and deterministic visual evidence without creating a governance inference.

## Attribution and exclusions

Identity existence does not imply participation, control, supply, command, culpability or Material Participation.

## Visual evidence

![Derived evidence diagram for {name}](../assets/generated/{entity_id}-evidence.svg)

The generated diagram is derived from the versioned fixture data and has a textual equivalent in this dossier.

## Evidence gaps

This is a synthetic CI fixture and carries no real-world evidentiary proposition.

## Sources

- [Canonical {state} State dossier](../states/{state}.md)

## Governance boundary

The fixture is identity-only. State context is provenance and must not be inherited as entity governance.
''',
                encoding="utf-8",
            )

            manifest = {
                "version": 50,
                "date": "2026-08-20",
                "purpose": "Full-pipeline atomic post-v49 Deployment regression fixture.",
                "migrationRule": "Identity arrives atomically with its dedicated dossier; no governance inference.",
                "visualRule": "Derived visuals are deterministic migration-snapshot context only.",
                "maxMissingDedicatedDossiers": 0,
                "entities": [
                    {
                        "id": entity_id,
                        "name": name,
                        "type": "Deployment",
                        "state": state,
                        "stateContext": state_context,
                        "dossier": f"dossiers/projects/{entity_id}.md",
                        "sourceDossier": f"dossiers/states/{state}.md",
                        "sourceGranularity": "direct",
                        "visualModel": {
                            "source": f"{state} State dossier + ABox identity",
                            "proposition": "Atomic identity-only Deployment dossier",
                            "boundary": "No governance inheritance",
                        },
                        "visuals": [
                            f"dossiers/assets/generated/{entity_id}-status.svg",
                            f"dossiers/assets/generated/{entity_id}-evidence.svg",
                        ],
                    }
                ],
            }
            manifest_path = (
                root
                / "knowledge/generated"
                / "canonical-entity-dossier-migration-v50.json"
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            staged = root / "build/e2e-staged"
            self.run_python(root, "tools/render_dossier_visuals.py", "--out", str(staged))
            generated = root / "dossiers/assets/generated"
            for suffix in ("status", "evidence"):
                shutil.copy2(
                    staged / f"{entity_id}-{suffix}.svg",
                    generated / f"{entity_id}-{suffix}.svg",
                )

            commands = [
                ("tools/check_canonical_entity_manifest_schema.py",),
                (
                    "tools/check_canonical_entity_provenance_snapshot.py",
                    "--base-ref",
                    base,
                ),
                (
                    "tools/check_canonical_entity_manifest_history.py",
                    "--base-ref",
                    base,
                ),
                ("tools/check_evidence_image_metadata.py",),
                ("tools/check_canonical_entity_contract.py",),
                (
                    "tools/check_canonical_entity_dossiers_extended.py",
                    "--json",
                    "build/e2e-coverage.json",
                ),
                ("tools/check_canonical_dossier_accessibility.py",),
                ("tools/check_visual_evidence_semantics.py",),
                (
                    "tools/check_canonical_entity_migration_preservation_extended.py",
                    "--base-ref",
                    base,
                ),
                (
                    "tools/check_dossier_visual_layout.py",
                    "dossiers/assets/generated",
                ),
            ]
            for command in commands:
                self.run_python(root, *command)

            regenerated_one = root / "build/e2e-regenerated-one"
            regenerated_two = root / "build/e2e-regenerated-two"
            self.run_python(
                root,
                "tools/render_dossier_visuals.py",
                "--out",
                str(regenerated_one),
            )
            self.assert_dir_bytes_equal(self, generated, regenerated_one)

            self.run_python(
                root,
                "tools/check_dossier_visual_layout.py",
                str(regenerated_one),
            )
            self.run_python(
                root,
                "tools/render_dossier_visuals.py",
                "--out",
                str(regenerated_two),
            )
            self.assert_dir_bytes_equal(self, regenerated_one, regenerated_two)


if __name__ == "__main__":
    unittest.main(verbosity=2)
