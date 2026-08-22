#!/usr/bin/env python3
"""Fail closed when canonical dossier visuals lack meaningful Markdown alt text."""
from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "knowledge/generated"
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
GENERIC_ALT_TEXT = {
    "state context",
    "state dossier context",
    "evidence boundary",
    "derived evidence diagram",
    "image",
    "visual",
    "diagram",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_relative_visual(dossier: str, visual: str) -> str:
    dossier_dir = posixpath.dirname(dossier)
    return posixpath.relpath(visual, dossier_dir)


def meaningful_alt_error(alt: str, visual: str) -> str | None:
    normalized = " ".join(alt.casefold().split())
    if not normalized:
        return "empty alt text"
    if normalized in GENERIC_ALT_TEXT:
        return f"generic alt text {alt!r}"
    if len(normalized) < 12:
        return f"alt text is too terse to be meaningful: {alt!r}"
    if visual.endswith("-status.svg"):
        if "state" not in normalized or "context" not in normalized:
            return f"status alt text must identify State context: {alt!r}"
    elif visual.endswith("-evidence.svg"):
        if "evidence" not in normalized or "diagram" not in normalized:
            return f"evidence alt text must identify the evidence diagram: {alt!r}"
    return None


def main() -> int:
    errors: list[str] = []
    checked = 0
    manifests = sorted(
        MANIFEST_DIR.glob("canonical-entity-dossier-migration-v*.json"),
        key=lambda path: int(path.stem.rsplit("v", 1)[1]),
    )

    for manifest_path in manifests:
        manifest = load_json(manifest_path)
        for row in manifest.get("entities", []):
            entity_id = row.get("id", "<missing-id>")
            dossier = row.get("dossier")
            visuals = row.get("visuals")
            if not isinstance(dossier, str) or not dossier:
                errors.append(f"{manifest_path.relative_to(ROOT)}: {entity_id}: missing dossier")
                continue
            if not isinstance(visuals, list) or not visuals:
                errors.append(f"{manifest_path.relative_to(ROOT)}: {entity_id}: missing visuals")
                continue

            dossier_path = ROOT / dossier
            if not dossier_path.is_file():
                errors.append(f"{dossier}: dossier does not exist")
                continue
            text = dossier_path.read_text(encoding="utf-8")
            images = [(alt.strip(), target.strip()) for alt, target in IMAGE_RE.findall(text)]

            for visual in visuals:
                if not isinstance(visual, str) or not visual:
                    errors.append(f"{dossier}: {entity_id}: invalid visual path {visual!r}")
                    continue
                expected_target = expected_relative_visual(dossier, visual)
                matches = [(alt, target) for alt, target in images if target == expected_target]
                if len(matches) != 1:
                    errors.append(
                        f"{dossier}: {entity_id}: expected exactly one Markdown image for "
                        f"{expected_target!r}, found {len(matches)}"
                    )
                    continue
                alt = matches[0][0]
                checked += 1
                problem = meaningful_alt_error(alt, visual)
                if problem:
                    errors.append(f"{dossier}: {entity_id}: {problem} for {expected_target}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(
        "canonical dossier accessibility: OK "
        f"({checked} visual references with meaningful Markdown alt text)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
