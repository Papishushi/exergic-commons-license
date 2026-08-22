#!/usr/bin/env python3
"""Adversarial tests for canonical policy alignment and embed/visibility boundaries."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import canonical_dossier_contract as contract  # noqa: E402
import check_canonical_entity_dossiers_extended as dossiers_extended  # noqa: E402
import check_canonical_entity_migration_preservation_extended as preservation_extended  # noqa: E402
import check_evidence_image_metadata as evidence_metadata  # noqa: E402
import check_visual_evidence_semantics as semantics  # noqa: E402


class CanonicalPolicyHardeningTests(unittest.TestCase):
    def test_schema_type_enum_must_match_canonical_type_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema = root / "schemas/entity.schema.json"
            schema.parent.mkdir(parents=True)
            schema.write_text(
                json.dumps({
                    "type": "object",
                    "properties": {
                        "type": {
                            "enum": ["State", *contract.TYPE_DIR.keys(), "FutureType"]
                        }
                    }
                }),
                encoding="utf-8",
            )
            errors = contract.validate_schema_type_alignment(root)
            self.assertTrue(any("FutureType" in error for error in errors))

    def test_extended_wrappers_share_the_single_type_and_raster_policy(self) -> None:
        self.assertEqual(dossiers_extended.checker.TYPE_DIR, contract.TYPE_DIR)
        self.assertEqual(
            dossiers_extended.checker.IMAGE_EXTENSIONS,
            contract.RASTER_FACSIMILE_EXTENSIONS,
        )
        self.assertEqual(preservation_extended.checker.TYPE_DIR, contract.TYPE_DIR)
        self.assertEqual(evidence_metadata.IMAGE_EXTENSIONS, contract.RASTER_FACSIMILE_EXTENSIONS)
        self.assertNotIn(".svg", contract.RASTER_FACSIMILE_EXTENSIONS)

    def test_entity_and_entity_type_frontmatter_are_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema = root / "schemas/entity.schema.json"
            schema.parent.mkdir(parents=True)
            schema.write_text(
                json.dumps({
                    "properties": {"type": {"enum": ["State", *contract.TYPE_DIR.keys()]}}
                }),
                encoding="utf-8",
            )
            entity = root / "knowledge/entities/ORG-X.json"
            entity.parent.mkdir(parents=True)
            entity.write_text(
                json.dumps({
                    "id": "ORG-X",
                    "type": "Organization",
                    "name": "Example Organization",
                    "dossier": "../../dossiers/organizations/ORG-X.md",
                }),
                encoding="utf-8",
            )
            dossier = root / "dossiers/organizations/ORG-X.md"
            dossier.parent.mkdir(parents=True)
            dossier.write_text("---\nid: ECL-ORG-X\n---\n# Example\n", encoding="utf-8")
            errors = contract.validate_universe(root)
            self.assertTrue(any("frontmatter entity None" in error for error in errors))
            self.assertTrue(any("frontmatter entity_type None" in error for error in errors))

    def test_inline_svg_html_and_css_remote_resources_are_rejected(self) -> None:
        rel = Path("dossiers/organizations/ORG-X.md")
        samples = (
            '<svg><image href="https://example.invalid/a.png"/></svg>',
            '<object data="https://example.invalid/b.png"></object>',
            '<embed src="https://example.invalid/c.png">',
            '<div style="background-image:url(https://example.invalid/d.png)"></div>',
            '<style>@import "https://example.invalid/e.css";</style>',
        )
        for sample in samples:
            with self.subTest(sample=sample):
                errors = contract.validate_dossier_embedded_resources(sample, rel)
                self.assertTrue(errors)

    def test_dy_shifted_semantic_text_outside_clip_is_not_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "dossiers/assets/generated"
            generated.mkdir(parents=True)
            path = generated / "X-status.svg"
            path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<defs><clipPath id="box"><rect x="0" y="0" width="100" height="40"/></clipPath></defs>'
                '<text x="10" y="10" clip-path="url(#box)">'
                '<tspan x="10" y="10">SAFE</tspan>'
                '<tspan x="10" dy="100">REQUIRED</tspan>'
                '</text></svg>',
                encoding="utf-8",
            )
            clipping_errors = contract.validate_generated_svg_clipping(root)
            self.assertTrue(any("outside clipPath" in error for error in clipping_errors))
            visible = semantics.visible_svg_text(path) or ""
            self.assertIn("SAFE", visible)
            self.assertNotIn("REQUIRED", visible)


if __name__ == "__main__":
    unittest.main(verbosity=2)
