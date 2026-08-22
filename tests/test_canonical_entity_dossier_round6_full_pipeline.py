#!/usr/bin/env python3
"""Run the existing v50 full-pipeline fixture through the round-six guards as well."""
from __future__ import annotations

import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from test_canonical_entity_dossier_full_pipeline_e2e import CanonicalV50FullPipelineTests  # noqa: E402


class CanonicalRoundSixV50FullPipelineTests(CanonicalV50FullPipelineTests):
    """Reuse the canonical synthetic v50 repo and splice in the new guards."""

    def run_python(self, root: Path, *args: str) -> str:
        output = super().run_python(root, *args)
        if args and args[0] == "tools/check_canonical_entity_contract.py":
            super().run_python(root, "tools/check_canonical_entity_contract_round6.py")
        if args and args[0] == "tools/check_visual_evidence_semantics.py":
            super().run_python(root, "tools/check_visual_evidence_semantics_live.py")
        return output


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
