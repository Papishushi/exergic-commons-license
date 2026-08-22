#!/usr/bin/env python3
"""Round-eight regressions for pre-ledger CommonMark resource enforcement."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import canonical_dossier_contract as contract  # noqa: E402


class CanonicalRoundEightTests(unittest.TestCase):
    @staticmethod
    def _write_preledger_fixture(root: Path, markdown: str) -> tuple[str, Path]:
        entity_id = "ORG-PRELEDGER"
        entity_dir = root / "knowledge/entities"
        dossier_dir = root / "dossiers/organizations"
        entity_dir.mkdir(parents=True, exist_ok=True)
        dossier_dir.mkdir(parents=True, exist_ok=True)

        entity = {
            "@context": "../../ontology/ecl-context.jsonld",
            "iri": f"ecl:{entity_id}",
            "id": entity_id,
            "type": "Organization",
            "name": "Pre-ledger Organization",
            "dossier": f"../../dossiers/organizations/{entity_id}.md",
        }
        (entity_dir / f"{entity_id}.json").write_text(
            json.dumps(entity),
            encoding="utf-8",
        )
        dossier = dossier_dir / f"{entity_id}.md"
        dossier.write_text(markdown, encoding="utf-8")
        return entity_id, dossier

    @staticmethod
    def _markdown(resource: str) -> str:
        return rf"""---
id: ECL-ORG-PRELEDGER
entity: Pre-ledger Organization
entity_type: organization
---
# Pre-ledger Organization

![x\]y]({resource})
"""

    def test_preledger_dossier_cannot_hide_remote_image_with_escaped_alt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = "https://example.invalid/preledger.png"
            markdown = self._markdown(remote)
            self._write_preledger_fixture(root, markdown)

            # This fixture deliberately has no migration manifest: it represents the
            # dedicated baseline that predates the canonical dossier ledger.
            self.assertFalse((root / "knowledge/generated").exists())
            self.assertIn(remote, contract.commonmark_image_targets(markdown))

            errors = contract.validate_universe(root)
            self.assertTrue(
                any(remote in error and "non-local embedded resource" in error for error in errors),
                errors,
            )

    def test_preledger_local_resources_require_shared_provenance_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            rogue = "../../rogue.png"
            markdown = self._markdown(rogue)
            _, dossier = self._write_preledger_fixture(root, markdown)
            (root / "rogue.png").write_bytes(b"not-a-controlled-facsimile")
            self.assertIn(rogue, contract.commonmark_image_targets(markdown))

            errors = contract.validate_universe(root)
            self.assertTrue(
                any("uncontrolled asset" in error and "rogue.png" in error for error in errors),
                errors,
            )

            traversal = "../../../outside.png"
            markdown = self._markdown(traversal)
            dossier.write_text(markdown, encoding="utf-8")
            self.assertIn(traversal, contract.commonmark_image_targets(markdown))
            errors = contract.validate_universe(root)
            self.assertTrue(
                any("escapes the repository" in error and traversal in error for error in errors),
                errors,
            )

            allowed = "../assets/generated/ORG-PRELEDGER-status.svg"
            generated = root / "dossiers/assets/generated/ORG-PRELEDGER-status.svg"
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            markdown = self._markdown(allowed)
            dossier.write_text(markdown, encoding="utf-8")
            self.assertIn(allowed, contract.commonmark_image_targets(markdown))
            self.assertEqual([], contract.validate_universe(root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
