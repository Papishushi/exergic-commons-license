#!/usr/bin/env python3
"""Fail closed on canonical migration State-provenance and SVG-metadata mismatches."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "knowledge/generated"
VALID_STATE_CONTEXTS = {"R", "S", "U", "N"}
VALID_SOURCE_GRANULARITY = {"direct", "partial"}
SVG_NS = "{http://www.w3.org/2000/svg}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def frontmatter(text: str) -> dict[str, str]:
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


def svg_metadata(path: Path) -> str | None:
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    title = root.find(f"{SVG_NS}title")
    desc = root.find(f"{SVG_NS}desc")
    if title is None or desc is None:
        return None
    return " ".join(("".join(title.itertext()), "".join(desc.itertext())))


def main() -> int:
    errors: list[str] = []
    manifests = sorted(
        MANIFEST_DIR.glob("canonical-entity-dossier-migration-v*.json"),
        key=lambda path: int(path.stem.rsplit("v", 1)[1]),
    )
    if not manifests:
        errors.append("no canonical entity dossier migration manifests found")

    for path in manifests:
        manifest = load_json(path)
        for row in manifest.get("entities", []):
            entity_id = row.get("id", "<missing-id>")
            entity_name = row.get("name")
            state = row.get("state")
            source = row.get("sourceDossier")
            state_context = row.get("stateContext")
            source_granularity = row.get("sourceGranularity")

            if not isinstance(state, str) or not state:
                errors.append(f"{path.relative_to(ROOT)}: {entity_id}: missing state")
                continue
            expected = Path("dossiers/states") / f"{state}.md"
            if source != expected.as_posix():
                errors.append(
                    f"{path.relative_to(ROOT)}: {entity_id}: sourceDossier {source!r} "
                    f"!= State provenance {expected.as_posix()!r}"
                )
                continue
            source_path = ROOT / expected
            if not source_path.is_file():
                errors.append(f"{path.relative_to(ROOT)}: {entity_id}: missing sourceDossier {expected}")
                continue
            fm = frontmatter(source_path.read_text(encoding="utf-8"))
            if fm.get("iso3") != state:
                errors.append(
                    f"{path.relative_to(ROOT)}: {entity_id}: source dossier iso3 "
                    f"{fm.get('iso3')!r} != manifest state {state!r}"
                )

            if state_context not in VALID_STATE_CONTEXTS:
                errors.append(
                    f"{path.relative_to(ROOT)}: {entity_id}: invalid stateContext {state_context!r}"
                )
            elif fm.get("provisional_outcome") != state_context:
                errors.append(
                    f"{path.relative_to(ROOT)}: {entity_id}: stateContext {state_context!r} "
                    f"!= source dossier provisional_outcome {fm.get('provisional_outcome')!r}"
                )

            if source_granularity not in VALID_SOURCE_GRANULARITY:
                errors.append(
                    f"{path.relative_to(ROOT)}: {entity_id}: invalid sourceGranularity {source_granularity!r}"
                )

            if not isinstance(entity_name, str) or not entity_name:
                errors.append(f"{path.relative_to(ROOT)}: {entity_id}: missing name")
                continue
            for visual in row.get("visuals", []):
                visual_path = ROOT / visual
                if not visual_path.is_file():
                    continue
                metadata = svg_metadata(visual_path)
                if metadata is None:
                    errors.append(f"{path.relative_to(ROOT)}: {entity_id}: invalid SVG metadata in {visual}")
                elif entity_name not in metadata:
                    errors.append(
                        f"{path.relative_to(ROOT)}: {entity_id}: SVG metadata in {visual} "
                        "does not preserve the canonical entity name"
                    )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"canonical entity provenance: OK ({len(manifests)} manifests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
