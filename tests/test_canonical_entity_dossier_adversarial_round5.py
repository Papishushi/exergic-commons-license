#!/usr/bin/env python3
"""Adversarial round-five regressions for parser, discovery, preservation and static-media boundaries."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import canonical_dossier_contract as contract  # noqa: E402
import check_canonical_entity_contract as hardened  # noqa: E402
import check_canonical_entity_migration_preservation_extended as preservation  # noqa: E402


def write_schema(root: Path) -> None:
    path = root / "schemas/entity.schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": [
                    "@context",
                    "iri",
                    "id",
                    "type",
                    "name",
                    "dossier",
                    "lastSubstantiveReview",
                    "reviewClass",
                ],
                "properties": {
                    "@context": {"type": "string"},
                    "iri": {"type": "string"},
                    "id": {"type": "string"},
                    "type": {"enum": ["State", *contract.TYPE_DIR.keys()]},
                    "name": {"type": "string"},
                    "dossier": {"type": "string"},
                    "lastSubstantiveReview": {"type": "string"},
                    "reviewClass": {"type": "string"},
                },
            }
        ),
        encoding="utf-8",
    )


def entity_record(entity_id: str = "ORG-X", entity_type: str = "Organization") -> dict:
    return {
        "@context": "../../ontology/ecl-context.jsonld",
        "iri": f"ecl:{entity_id}",
        "id": entity_id,
        "type": entity_type,
        "name": "Example",
        "dossier": "../../dossiers/organizations/X.md",
        "lastSubstantiveReview": "2026-08-20",
        "reviewClass": "manual",
    }


def write_manifest(
    root: Path,
    *,
    model: dict | None = None,
    visual: str = "dossiers/assets/generated/ORG-X-status.svg",
) -> Path:
    path = root / "knowledge/generated/canonical-entity-dossier-migration-v40.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "ORG-X",
        "name": "Example",
        "type": "Organization",
        "state": "USA",
        "stateContext": "N",
        "dossier": "dossiers/organizations/X.md",
        "sourceDossier": "dossiers/states/USA.md",
        "sourceGranularity": "partial",
        "visualModel": model
        or {
            "source": "USA State dossier + existing ABox identity/review record",
            "proposition": "Dedicated dossier migration preserves Example as an identity-only non-State record",
            "boundary": hardened.CANONICAL_BOUNDARY,
        },
        "visuals": [visual, "dossiers/assets/generated/ORG-X-evidence.svg"],
    }
    path.write_text(json.dumps({"version": 40, "entities": [row]}), encoding="utf-8")
    return path


class CanonicalRoundFiveTests(unittest.TestCase):
    def test_entity_type_abox_record_outside_entities_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_schema(root)
            path = root / "knowledge/claims/ORG-X.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(entity_record()), encoding="utf-8")
            errors = hardened.validate_abox_entity_surface(root)
            self.assertTrue(any("outside knowledge/entities" in error for error in errors))

    def test_recursive_entity_schema_validation_cannot_be_bypassed_by_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_schema(root)
            path = root / "knowledge/entities/nested/ORG-X.json"
            path.parent.mkdir(parents=True)
            record = entity_record()
            del record["name"]
            path.write_text(json.dumps(record), encoding="utf-8")
            errors = hardened.validate_abox_entity_surface(root)
            self.assertTrue(any("entity schema violation" in error and "name" in error for error in errors))

    def test_case_variant_json_suffix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_schema(root)
            path = root / "knowledge/entities/ORG-X.JSON"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(entity_record()), encoding="utf-8")
            errors = hardened.validate_abox_entity_surface(root)
            self.assertTrue(any("suffix must be lowercase" in error for error in errors))

    def test_quoted_or_merged_yaml_frontmatter_cannot_hide_governance_keys(self) -> None:
        quoted = '---\nid: ECL-ORG-X\n"provisional_outcome": R\n---\n'
        _fm, errors = hardened.strict_frontmatter(quoted)
        self.assertTrue(any("unquoted canonical key" in error for error in errors))

        merged = "---\nid: ECL-ORG-X\n<<: *governance\n---\n"
        _fm, errors = hardened.strict_frontmatter(merged)
        self.assertTrue(any("unquoted canonical key" in error for error in errors))

    def test_comments_fences_and_indented_code_cannot_satisfy_positive_markdown(self) -> None:
        source = """<!--
## Evidence record
![State dossier context for Example](../assets/generated/ORG-X-status.svg)
-->
```markdown
## Evidence gaps
![Derived evidence diagram for Example](../assets/generated/ORG-X-evidence.svg)
```
    ## Sources
"""
        visible = hardened.renderable_markdown(source)
        self.assertNotIn("## Evidence record", visible)
        self.assertNotIn("## Evidence gaps", visible)
        self.assertNotIn("## Sources", visible)
        self.assertFalse(hardened.IMAGE_RE.findall(visible))

    def test_html_entity_encoded_remote_resource_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            dossier = root / "dossiers/organizations/X.md"
            dossier.parent.mkdir(parents=True)
            dossier.write_text('<img src="https&#58;//example.invalid/evidence.png">', encoding="utf-8")
            errors = hardened.validate_encoded_resource_indirection(root)
            self.assertTrue(any("encoded/non-local embedded resource" in error for error in errors))

    def test_active_or_external_svg_constructs_are_rejected(self) -> None:
        samples = {
            "script": '<script>alert(1)</script>',
            "animate": '<set attributeName="visibility" to="hidden"/>',
            "href": '<a href="https://example.invalid/"><text x="1" y="1">X</text></a>',
            "clip-units": '<defs><clipPath id="c" clipPathUnits="objectBoundingBox"><rect x="0" y="0" width="1" height="1"/></clipPath></defs>',
        }
        for label, body in samples.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_manifest(root)
                generated = root / "dossiers/assets/generated"
                generated.mkdir(parents=True)
                (generated / "ORG-X-status.svg").write_text(
                    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{body}</svg>',
                    encoding="utf-8",
                )
                errors = hardened.validate_static_svg_surface(root)
                self.assertTrue(errors)

    def test_fake_raster_bytes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "dossiers/evidence-images/fake.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"not actually a png")
            errors = hardened.validate_raster_bytes(root)
            self.assertTrue(any("bytes do not match" in error for error in errors))

    def test_v40_visual_model_is_bound_to_safe_identity_only_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(
                root,
                model={
                    "source": "USA State dossier + existing ABox identity/review record",
                    "proposition": "Example is culpable",
                    "boundary": hardened.CANONICAL_BOUNDARY,
                },
            )
            errors = hardened.validate_safe_visual_models(root)
            self.assertTrue(
                any("canonical identity-only migration/atomic-addition template" in error for error in errors)
            )

    def test_base_supported_identity_deletion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
            path = root / "knowledge/entities/ORG-X.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(entity_record()), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            path.unlink()
            errors = preservation.validate_baseline_identity_preservation(base, root)
            self.assertTrue(any("was deleted" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
