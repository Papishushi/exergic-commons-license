from __future__ import annotations

import ast
import fnmatch
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

WORKFLOW_ENTRYPOINTS = {
    ".github/workflows/canonical-entity-dossiers.yml": (
        "tools/canonical_dossier_contract.py",
        "tools/check_canonical_entity_contract_round6.py",
    ),
    ".github/workflows/living-update-integrity.yml": (
        "tools/check_canonical_entity_contract_round6.py",
    ),
}


def _local_tool_dependencies(entrypoints: tuple[str, ...]) -> set[str]:
    """Return the recursive tools/*.py import closure for normative entrypoints."""
    pending = [ROOT / path for path in entrypoints]
    seen: set[Path] = set()

    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                module_names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_names.add(node.module.split(".", 1)[0])

        for module_name in module_names:
            candidate = TOOLS / f"{module_name}.py"
            if candidate.is_file() and candidate not in seen:
                pending.append(candidate)

    return {path.relative_to(ROOT).as_posix() for path in seen}


def _event_paths(workflow_text: str, event: str) -> set[str]:
    """Extract one top-level Actions event's paths list without a YAML dependency."""
    lines = workflow_text.splitlines()
    event_marker = f"  {event}:"
    try:
        start = lines.index(event_marker) + 1
    except ValueError as exc:
        raise AssertionError(f"workflow is missing {event_marker.strip()!r}") from exc

    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
            end = index
            break

    block = lines[start:end]
    try:
        paths_index = block.index("    paths:") + 1
    except ValueError as exc:
        raise AssertionError(f"workflow event {event!r} is missing paths") from exc

    paths: set[str] = set()
    for line in block[paths_index:]:
        if not line.startswith("      - "):
            if line.strip():
                break
            continue
        value = line[len("      - ") :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        paths.add(value)
    return paths


def _covered(path: str, patterns: set[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


class CanonicalWorkflowGateTests(unittest.TestCase):
    def test_normative_local_python_imports_are_ci_path_covered(self) -> None:
        for workflow_rel, entrypoints in WORKFLOW_ENTRYPOINTS.items():
            with self.subTest(workflow=workflow_rel):
                workflow_text = (ROOT / workflow_rel).read_text(encoding="utf-8")
                dependencies = _local_tool_dependencies(entrypoints)
                self.assertTrue(dependencies, workflow_rel)

                for event in ("push", "pull_request"):
                    patterns = _event_paths(workflow_text, event)
                    missing = sorted(path for path in dependencies if not _covered(path, patterns))
                    self.assertEqual(
                        [],
                        missing,
                        f"{workflow_rel} {event}.paths does not cover normative local imports: {missing}",
                    )


if __name__ == "__main__":
    unittest.main()
