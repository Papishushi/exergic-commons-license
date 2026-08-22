#!/usr/bin/env python3
"""Round-seven regressions for CommonMark resource and supersession attacks."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import check_canonical_entity_contract_round6 as hardened  # noqa: E402
import check_canonical_entity_dossiers_extended as coverage  # noqa: E402


def copy_schema_and_context(root: Path) -> None:
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    (root / "ontology").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "schemas/entity.schema.json", root / "schemas/entity.schema.json")
    shutil.copy2(REPO_ROOT / "ontology/ecl-context.jsonld", root / "ontology/ecl-context.jsonld")


def entity_record(entity_id: str) -> dict:
    return {
        "@context": "../../ontology/ecl-context.jsonld",
        "iri": f"ecl:{entity_id}",
        "id": entity_id,
        "type": "Organization",
        "name": entity_id,
        "dossier": f"../../dossiers/organizations/{entity_id}.md",
        "lastSubstantiveReview": "2026-08-20",
        "reviewClass": "manual",
    }


def write_entity(root: Path, record: dict) -> None:
    path = root / f"knowledge/entities/{record['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def write_manifest_dossier(root: Path, markdown: str) -> None:
    manifest = root / "knowledge/generated/canonical-entity-dossier-migration-v50.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 50,
                "entities": [
                    {
                        "id": "ORG-X",
                        "dossier": "dossiers/organizations/ORG-X.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    dossier = root / "dossiers/organizations/ORG-X.md"
    dossier.parent.mkdir(parents=True, exist_ok=True)
    dossier.write_text(markdown, encoding="utf-8")


class CanonicalRoundSevenTests(unittest.TestCase):
    def test_commonmark_escaped_alt_cannot_hide_remote_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = r"![x\]y](https://example.invalid/evidence.png)"
            write_manifest_dossier(root, source)
            self.assertIn(
                "https://example.invalid/evidence.png",
                hardened._commonmark_image_targets(source),
            )
            errors = hardened.validate_encoded_resources(root)
            self.assertTrue(
                any("non-local CommonMark image resource" in error for error in errors),
                errors,
            )

    def test_commonmark_escaped_alt_cannot_hide_local_allowlist_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dossier = root / "dossiers/organizations/ORG-X.md"
            dossier.parent.mkdir(parents=True, exist_ok=True)
            evidence_dir = root / "dossiers/evidence-images"
            evidence_dir.mkdir(parents=True, exist_ok=True)

            rogue = r"![x\]y](rogue.png)"
            self.assertIn("rogue.png", coverage.image_targets(rogue))
            errors = coverage.checker.validate_dossier_images(
                rogue,
                dossier,
                set(),
                root=root,
                evidence_image_dir=evidence_dir,
            )
            self.assertTrue(any("uncontrolled asset" in error for error in errors), errors)

            traversal = r"![x\]y](../../../rogue.png)"
            errors = coverage.checker.validate_dossier_images(
                traversal,
                dossier,
                set(),
                root=root,
                evidence_image_dir=evidence_dir,
            )
            self.assertTrue(any("uncontrolled asset" in error for error in errors), errors)

            allowed = "dossiers/assets/generated/ORG-X-status.svg"
            permitted = r"![x\]y](../assets/generated/ORG-X-status.svg)"
            errors = coverage.checker.validate_dossier_images(
                permitted,
                dossier,
                {allowed},
                root=root,
                evidence_image_dir=evidence_dir,
            )
            self.assertEqual(errors, [])

    def test_canonical_context_semantics_are_pinned(self) -> None:
        mutations = {
            "class-remap": ("Organization", "ecl:Person"),
            "relation-remap": (
                "partOf",
                {"@id": "ecl:controls", "@type": "@id", "@container": "@set"},
            ),
            "reverse-loss": ("supersededBy", {"@id": "ecl:supersedes", "@type": "@id"}),
        }
        for label, (term, replacement) in mutations.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                copy_schema_and_context(root)
                self.assertEqual(hardened.validate_canonical_context_semantics(root), [])
                path = root / "ontology/ecl-context.jsonld"
                document = json.loads(path.read_text(encoding="utf-8"))
                document["@context"][term] = replacement
                path.write_text(json.dumps(document), encoding="utf-8")
                errors = hardened.validate_canonical_context_semantics(root)
                self.assertTrue(
                    any("semantic fingerprint" in error for error in errors),
                    errors,
                )

    def test_supersession_rejects_self_dangling_and_cycles(self) -> None:
        with self.subTest("self-supersession"), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_schema_and_context(root)
            record = entity_record("ORG-A")
            record.update(identityLifecycle="superseded", supersededBy="ecl:ORG-A")
            write_entity(root, record)
            errors = hardened.validate_abox_dialect(root)
            self.assertTrue(any("cannot supersede itself" in error for error in errors), errors)

        with self.subTest("dangling-target"), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_schema_and_context(root)
            record = entity_record("ORG-A")
            record.update(identityLifecycle="superseded", supersededBy="ecl:ORG-MISSING")
            write_entity(root, record)
            errors = hardened.validate_abox_dialect(root)
            self.assertTrue(any("does not resolve" in error for error in errors), errors)

        with self.subTest("cycle"), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_schema_and_context(root)
            first = entity_record("ORG-A")
            first.update(identityLifecycle="superseded", supersededBy="ecl:ORG-B")
            second = entity_record("ORG-B")
            second.update(identityLifecycle="superseded", supersededBy="ecl:ORG-A")
            write_entity(root, first)
            write_entity(root, second)
            errors = hardened.validate_abox_dialect(root)
            self.assertTrue(any("supersession cycle is forbidden" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
