#!/usr/bin/env python3
"""Adversarial regression tests for canonical dossier fail-closed guards."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import check_canonical_entity_dossiers as dossiers  # noqa: E402
import check_canonical_entity_migration_preservation as preservation  # noqa: E402
import check_visual_evidence_semantics as semantics  # noqa: E402


class DossierCoverageAdversarialTests(unittest.TestCase):
    def test_entity_universe_includes_json_and_jsonld(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A.json").write_text("{}", encoding="utf-8")
            (root / "B.jsonld").write_text("{}", encoding="utf-8")
            (root / "ignore.txt").write_text("x", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "C.jsonld").write_text("{}", encoding="utf-8")
            self.assertEqual(
                {path.name for path in dossiers.entity_paths(root)},
                {"A.json", "B.jsonld", "C.jsonld"},
            )

    def test_remote_and_embedded_image_syntaxes_are_detected(self) -> None:
        text = """
![inline](https://example.invalid/a.png)
![reference][img]
[img]: http://example.invalid/b.png
<img src="https://example.invalid/c.png" alt="x">
<source srcset='https://example.invalid/d.png 1x, https://example.invalid/e.png 2x'>
![embedded](data:image/png;base64,AAAA)
"""
        targets = dossiers.image_targets(text)
        for expected in (
            "https://example.invalid/a.png",
            "http://example.invalid/b.png",
            "https://example.invalid/c.png",
            "https://example.invalid/d.png",
            "https://example.invalid/e.png",
        ):
            self.assertIn(expected, targets)
            self.assertTrue(dossiers.nonlocal_image_target(expected))
        self.assertTrue(any(target.startswith("data:") for target in targets))

    def test_uncontrolled_local_image_is_rejected_but_declared_and_facsimile_paths_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dossier_dir = root / "dossiers/organizations"
            dossier_dir.mkdir(parents=True)
            dossier_path = dossier_dir / "ORG-X.md"
            evidence_dir = root / "dossiers/evidence-images"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "photo.png").write_bytes(b"fixture")
            allowed = {"dossiers/assets/generated/ORG-X-status.svg"}
            text = """
![generated](../assets/generated/ORG-X-status.svg)
![facsimile](../evidence-images/photo.png)
![rogue](rogue.png)
"""
            errors = dossiers.validate_dossier_images(
                text,
                dossier_path,
                allowed,
                root=root,
                evidence_image_dir=evidence_dir,
            )
            self.assertEqual(len(errors), 1)
            self.assertIn("uncontrolled asset", errors[0])

    def test_reference_style_remote_image_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dossier_dir = root / "dossiers/projects"
            dossier_dir.mkdir(parents=True)
            dossier_path = dossier_dir / "PROJECT-X.md"
            evidence_dir = root / "dossiers/evidence-images"
            evidence_dir.mkdir(parents=True)
            errors = dossiers.validate_dossier_images(
                "![remote][evidence]\n\n[evidence]: https://example.invalid/e.png\n",
                dossier_path,
                set(),
                root=root,
                evidence_image_dir=evidence_dir,
            )
            self.assertTrue(any("non-local image reference" in error for error in errors))


class VisibleSvgAdversarialTests(unittest.TestCase):
    def _visible(self, body: str) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.svg"
            path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                + body
                + "</svg>",
                encoding="utf-8",
            )
            return semantics.visible_svg_text(path)

    def test_normal_text_is_visible(self) -> None:
        self.assertIn("REQUIRED", self._visible('<text x="10" y="20">REQUIRED</text>') or "")

    def test_display_none_text_is_not_visible(self) -> None:
        self.assertNotIn("REQUIRED", self._visible('<text x="10" y="20" display="none">REQUIRED</text>') or "")

    def test_hidden_parent_and_zero_opacity_are_not_visible(self) -> None:
        hidden_parent = self._visible('<g visibility="hidden"><text x="10" y="20">REQUIRED</text></g>') or ""
        zero_opacity = self._visible('<text x="10" y="20" style="opacity: 0">REQUIRED</text>') or ""
        self.assertNotIn("REQUIRED", hidden_parent)
        self.assertNotIn("REQUIRED", zero_opacity)

    def test_off_canvas_text_is_not_visible(self) -> None:
        self.assertNotIn("REQUIRED", self._visible('<text x="10000" y="10000">REQUIRED</text>') or "")

    def test_css_or_transform_indirection_fails_closed(self) -> None:
        self.assertIsNone(self._visible('<style>.x{display:none}</style><text class="x" x="10" y="20">REQUIRED</text>'))
        self.assertIsNone(self._visible('<g transform="translate(-9999 0)"><text x="10" y="20">REQUIRED</text></g>'))


class PreservationAdversarialTests(unittest.TestCase):
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

    @staticmethod
    def write_entity(root: Path, entity_id: str, dossier: str, *, suffix: str = ".jsonld", name: str = "Example") -> None:
        path = root / "knowledge/entities" / f"{entity_id}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "@context": "https://example.invalid/context",
                "iri": f"urn:test:{entity_id}",
                "id": entity_id,
                "name": name,
                "type": "Organization",
                "dossier": dossier,
            }, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def write_manifest(root: Path, version: int, entity_id: str, source: str) -> None:
        path = root / "knowledge/generated" / f"canonical-entity-dossier-migration-v{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "version": version,
                "maxMissingDedicatedDossiers": 0,
                "entities": [{"id": entity_id, "sourceDossier": source}],
            }, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_v50_allows_atomic_new_jsonld_identity_with_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.init_repo(root)
            self.write_entity(root, "ORG-NEW", "../../dossiers/organizations/ORG-NEW.md")
            self.write_manifest(root, 50, "ORG-NEW", "dossiers/states/AAA.md")
            errors, stats = preservation.validate(base, root)
            self.assertEqual(errors, [])
            self.assertEqual(stats["atomicNew"], 1)

    def test_frozen_v49_cannot_create_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.init_repo(root)
            self.write_entity(root, "ORG-NEW", "../../dossiers/organizations/ORG-NEW.md")
            self.write_manifest(root, 49, "ORG-NEW", "dossiers/states/AAA.md")
            errors, _ = preservation.validate(base, root)
            self.assertTrue(any("frozen v1-v49 migrations must not create" in error for error in errors))

    def test_manifestless_new_jsonld_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.init_repo(root)
            self.write_entity(root, "ORG-BYPASS", "../../dossiers/organizations/ORG-BYPASS.md")
            errors, stats = preservation.validate(base, root)
            self.assertTrue(any("not represented in a newly appended" in error for error in errors))
            self.assertEqual(stats["manifestlessNew"], 1)

    def test_existing_identity_source_dossier_must_match_base_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.git(root, "config", "user.email", "tests@example.invalid")
            self.git(root, "config", "user.name", "Guard Tests")
            self.write_entity(root, "ORG-OLD", "../../dossiers/states/AAA.md", suffix=".json")
            self.git(root, "add", "knowledge/entities/ORG-OLD.json")
            self.git(root, "commit", "-q", "-m", "base")
            base = self.git(root, "rev-parse", "HEAD")

            self.write_entity(root, "ORG-OLD", "../../dossiers/organizations/ORG-OLD.md", suffix=".json")
            self.write_manifest(root, 50, "ORG-OLD", "dossiers/states/BBB.md")
            errors, _ = preservation.validate(base, root)
            self.assertTrue(any("does not match comparison-base dossier provenance" in error for error in errors))

    def test_existing_identity_valid_migration_preserves_source_and_only_dossier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.git(root, "config", "user.email", "tests@example.invalid")
            self.git(root, "config", "user.name", "Guard Tests")
            self.write_entity(root, "ORG-OLD", "../../dossiers/states/AAA.md", suffix=".json")
            self.git(root, "add", "knowledge/entities/ORG-OLD.json")
            self.git(root, "commit", "-q", "-m", "base")
            base = self.git(root, "rev-parse", "HEAD")

            self.write_entity(root, "ORG-OLD", "../../dossiers/organizations/ORG-OLD.md", suffix=".json")
            self.write_manifest(root, 50, "ORG-OLD", "dossiers/states/AAA.md")
            errors, _ = preservation.validate(base, root)
            self.assertEqual(errors, [])

    def test_existing_identity_non_dossier_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.git(root, "config", "user.email", "tests@example.invalid")
            self.git(root, "config", "user.name", "Guard Tests")
            self.write_entity(root, "ORG-OLD", "../../dossiers/states/AAA.md", suffix=".json", name="Before")
            self.git(root, "add", "knowledge/entities/ORG-OLD.json")
            self.git(root, "commit", "-q", "-m", "base")
            base = self.git(root, "rev-parse", "HEAD")

            self.write_entity(root, "ORG-OLD", "../../dossiers/organizations/ORG-OLD.md", suffix=".json", name="After")
            self.write_manifest(root, 50, "ORG-OLD", "dossiers/states/AAA.md")
            errors, _ = preservation.validate(base, root)
            self.assertTrue(any("non-dossier ABox mutation" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
