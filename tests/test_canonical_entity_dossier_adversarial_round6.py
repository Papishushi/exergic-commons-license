#!/usr/bin/env python3
"""Round-six adversarial regressions for identity, CommonMark, lifecycle and media guards."""
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
import check_canonical_entity_contract_round6 as hardened  # noqa: E402
import check_canonical_entity_migration_preservation_extended as preservation  # noqa: E402
import render_dossier_visuals as renderer  # noqa: E402


def copy_schema_and_context(root: Path) -> None:
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    (root / "ontology").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "schemas/entity.schema.json", root / "schemas/entity.schema.json")
    shutil.copy2(REPO_ROOT / "ontology/ecl-context.jsonld", root / "ontology/ecl-context.jsonld")


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


def init_repo(root: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
    marker = root / "README.md"
    marker.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def write_manifest(root: Path, dossier: str = "dossiers/organizations/X.md") -> None:
    path = root / "knowledge/generated/canonical-entity-dossier-migration-v40.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 40,
                "entities": [
                    {
                        "id": "ORG-X",
                        "name": "Example",
                        "type": "Organization",
                        "state": "USA",
                        "stateContext": "N",
                        "dossier": dossier,
                        "sourceDossier": "dossiers/states/USA.md",
                        "sourceGranularity": "direct",
                        "visualModel": {
                            "source": "USA State dossier + existing ABox identity/review record",
                            "proposition": "Dedicated dossier migration preserves Example as an identity-only non-State record",
                            "boundary": "Identity and State-context adjacency do not establish participation, control, culpability or governance",
                        },
                        "visuals": [
                            "dossiers/assets/generated/ORG-X-status.svg",
                            "dossiers/assets/generated/ORG-X-evidence.svg",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class CanonicalRoundSixTests(unittest.TestCase):
    def test_remote_or_inline_context_cannot_redefine_entity_semantics(self) -> None:
        for context in ("https://example.invalid/context.jsonld", {"kind": "@type"}):
            with self.subTest(context=context), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                copy_schema_and_context(root)
                path = root / "knowledge/claims/X.json"
                path.parent.mkdir(parents=True)
                record = entity_record()
                record["@context"] = context
                path.write_text(json.dumps(record), encoding="utf-8")
                errors = hardened.validate_abox_dialect(root)
                self.assertTrue(any("@context" in error for error in errors), errors)

    def test_direct_jsonld_id_or_type_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_schema_and_context(root)
            path = root / "knowledge/claims/X.jsonld"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "@context": "../../ontology/ecl-context.jsonld",
                        "@id": "ecl:ORG-X",
                        "@type": "Organization",
                        "id": "ORG-X",
                    }
                ),
                encoding="utf-8",
            )
            errors = hardened.validate_abox_dialect(root)
            self.assertTrue(any("direct @id/@type is forbidden" in error for error in errors), errors)

    def test_entity_iri_must_equal_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_schema_and_context(root)
            path = root / "knowledge/entities/ORG-X.json"
            path.parent.mkdir(parents=True)
            record = entity_record()
            record["iri"] = "ecl:ORG-Y"
            path.write_text(json.dumps(record), encoding="utf-8")
            errors = hardened.validate_abox_dialect(root)
            self.assertTrue(any("must equal stable identity 'ecl:ORG-X'" in error for error in errors), errors)

    def test_superseded_lifecycle_requires_replacement_and_uses_existing_supersedes_relation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_schema_and_context(root)
            path = root / "knowledge/entities/ORG-X.json"
            path.parent.mkdir(parents=True)
            record = entity_record()
            record["identityLifecycle"] = "superseded"
            path.write_text(json.dumps(record), encoding="utf-8")
            errors = hardened.validate_abox_dialect(root)
            self.assertTrue(any("supersededBy" in error and "required" in error for error in errors), errors)

        context = json.loads((REPO_ROOT / "ontology/ecl-context.jsonld").read_text(encoding="utf-8"))["@context"]
        self.assertEqual(context["supersededBy"].get("@reverse"), "ecl:supersedes")

    def test_existing_identity_type_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "knowledge/entities/ORG-X.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(entity_record()), encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
            subprocess.run(["git", "add", "knowledge/entities/ORG-X.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            changed = entity_record(entity_type="Project")
            path.write_text(json.dumps(changed), encoding="utf-8")
            errors = preservation.validate_baseline_identity_preservation(base, root)
            self.assertTrue(any("immutable identity core field 'type' changed" in error for error in errors), errors)

    def test_atomic_v50_identity_cannot_smuggle_graph_relations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            path = root / "knowledge/entities/ORG-X.json"
            path.parent.mkdir(parents=True)
            record = entity_record()
            record["participatesIn"] = ["ecl:PROJECT-Y"]
            path.write_text(json.dumps(record), encoding="utf-8")
            errors = preservation.validate_atomic_identity_only_additions(base, root)
            self.assertTrue(any("non-identity fields" in error and "participatesIn" in error for error in errors), errors)

    def test_multiline_commonmark_code_span_cannot_satisfy_section_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            dossier = root / "dossiers/organizations/X.md"
            dossier.parent.mkdir(parents=True)
            dossier.write_text(
                """---\nid: ECL-ORG-X\nentity: Example\nentity_type: organization\n---\n# Example\n\n## Identity scope\nVisible identity text.\n\n## State governance context\nVisible State text.\n![State dossier context for Example](../assets/generated/ORG-X-status.svg)\n\n## Evidence record\n`only code\nacross lines`\n\n## Attribution and exclusions\nVisible exclusion text.\n\n## Visual evidence\nVisible diagram text.\n![Derived evidence diagram for Example](../assets/generated/ORG-X-evidence.svg)\n\n## Evidence gaps\nVisible gap text.\n\n## Sources\n- Visible source text.\n\n## Governance boundary\nVisible boundary text.\n""",
                encoding="utf-8",
            )
            errors = hardened.validate_commonmark_identity_dossiers(root)
            self.assertTrue(any("Evidence record has no positive rendered prose" in error for error in errors), errors)

    def test_raw_html_is_forbidden_on_identity_only_dossier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            dossier = root / "dossiers/organizations/X.md"
            dossier.parent.mkdir(parents=True)
            dossier.write_text(
                """---\nid: ECL-ORG-X\nentity: Example\nentity_type: organization\n---\n<pre>raw browser surface</pre>\n""",
                encoding="utf-8",
            )
            errors = hardened.validate_commonmark_identity_dossiers(root)
            self.assertTrue(any("raw HTML is forbidden" in error for error in errors), errors)

    def test_multiline_reference_definition_exposes_remote_target(self) -> None:
        source = "![evidence][remote]\n[remote]:\n  https://example.invalid/evidence.png\n"
        targets = contract.embedded_resource_targets(source)
        self.assertIn("https://example.invalid/evidence.png", targets)

    def test_all_generated_svgs_include_legend_in_static_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "dossiers/assets/generated"
            generated.mkdir(parents=True)
            (generated / "state-outcome-legend.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                encoding="utf-8",
            )
            errors = hardened.validate_all_generated_svg_static(root)
            self.assertTrue(any("state-outcome-legend.svg" in error and "<script>" in error for error in errors), errors)

    def test_nested_svg_clips_are_intersected_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "dossiers/assets/generated"
            generated.mkdir(parents=True)
            (generated / "ORG-X-status.svg").write_text(
                '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<defs>
  <clipPath id="outer"><rect x="0" y="0" width="10" height="10"/></clipPath>
  <clipPath id="inner"><rect x="0" y="0" width="100" height="100"/></clipPath>
</defs>
<g clip-path="url(#outer)"><text x="50" y="50" clip-path="url(#inner)">TOKEN</text></g>
</svg>''',
                encoding="utf-8",
            )
            errors = contract.validate_generated_svg_clipping(root)
            self.assertTrue(any("outside active clipPath outer" in error for error in errors), errors)

    def test_forged_png_magic_bytes_fail_real_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "dossiers/evidence-images/fake.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40)
            errors = hardened.validate_decoded_rasters(root)
            self.assertTrue(any("cannot decode/verify" in error for error in errors), errors)

    def test_status_renderer_uses_live_state_dossier_not_historical_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "dossiers/states/USA.md"
            state.parent.mkdir(parents=True)
            state.write_text("---\niso3: USA\nprovisional_outcome: N\n---\n", encoding="utf-8")
            old_root = renderer.ROOT
            renderer.ROOT = root
            try:
                svg = renderer.status_svg(
                    {
                        "id": "ORG-X",
                        "name": "Example",
                        "state": "USA",
                        "stateContext": "R",
                        "_normalized_visual_v40": True,
                    },
                    {
                        "states": {
                            "R": {"label": "Restricted", "hex": "#000000"},
                            "N": {"label": "No restriction", "hex": "#ffffff"},
                        }
                    },
                )
            finally:
                renderer.ROOT = old_root
            self.assertIn("N · No restriction", svg)
            self.assertNotIn("R · Restricted", svg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
