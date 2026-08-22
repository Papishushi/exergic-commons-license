#!/usr/bin/env python3
"""Validate State provenance while treating stateContext as an immutable migration snapshot.

Rows already present at the comparison base retain their historical stateContext even
if the living State dossier later changes outcome. Newly appended manifests must
capture the current State dossier outcome at append time.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "knowledge/generated"
MANIFEST_RE = re.compile(r"^knowledge/generated/canonical-entity-dossier-migration-v([1-9][0-9]*)\.json$")
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


def base_manifest_paths(ref: str, root: Path = ROOT) -> set[str]:
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", "knowledge/generated"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cannot list migration manifests at {ref}: {proc.stderr.strip()}")
    return {line for line in proc.stdout.splitlines() if MANIFEST_RE.fullmatch(line)}


def validate(base_ref: str | None = None, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        historical = base_manifest_paths(base_ref, root) if base_ref else set()
    except RuntimeError as exc:
        return [str(exc)]
    manifests = sorted(
        (root / "knowledge/generated").glob("canonical-entity-dossier-migration-v*.json"),
        key=lambda path: int(path.stem.rsplit("v", 1)[1]),
    )
    if not manifests:
        return ["no canonical entity dossier migration manifests found"]

    for path in manifests:
        rel = path.relative_to(root).as_posix()
        is_new_manifest = bool(base_ref) and rel not in historical
        manifest = load_json(path)
        for row in manifest.get("entities", []):
            if not isinstance(row, dict):
                errors.append(f"{rel}: non-object migration row")
                continue
            entity_id = row.get("id", "<missing-id>")
            entity_name = row.get("name")
            state = row.get("state")
            source = row.get("sourceDossier")
            state_context = row.get("stateContext")
            source_granularity = row.get("sourceGranularity")

            if not isinstance(state, str) or not state:
                errors.append(f"{rel}: {entity_id}: missing state")
                continue
            expected = Path("dossiers/states") / f"{state}.md"
            if source != expected.as_posix():
                errors.append(f"{rel}: {entity_id}: sourceDossier {source!r} != State provenance {expected.as_posix()!r}")
                continue
            source_path = root / expected
            if not source_path.is_file():
                errors.append(f"{rel}: {entity_id}: missing sourceDossier {expected}")
                continue
            fm = frontmatter(source_path.read_text(encoding="utf-8"))
            if fm.get("iso3") != state:
                errors.append(f"{rel}: {entity_id}: source dossier iso3 {fm.get('iso3')!r} != manifest state {state!r}")

            if state_context not in VALID_STATE_CONTEXTS:
                errors.append(f"{rel}: {entity_id}: invalid stateContext {state_context!r}")
            elif is_new_manifest and fm.get("provisional_outcome") != state_context:
                errors.append(
                    f"{rel}: {entity_id}: newly appended stateContext snapshot {state_context!r} "
                    f"!= current source dossier provisional_outcome {fm.get('provisional_outcome')!r}"
                )

            if source_granularity not in VALID_SOURCE_GRANULARITY:
                errors.append(f"{rel}: {entity_id}: invalid sourceGranularity {source_granularity!r}")

            if not isinstance(entity_name, str) or not entity_name:
                errors.append(f"{rel}: {entity_id}: missing name")
                continue
            for visual in row.get("visuals", []):
                if not isinstance(visual, str):
                    continue
                visual_path = root / visual
                if not visual_path.is_file():
                    continue
                metadata = svg_metadata(visual_path)
                if metadata is None:
                    errors.append(f"{rel}: {entity_id}: invalid SVG metadata in {visual}")
                elif entity_name not in metadata:
                    errors.append(f"{rel}: {entity_id}: SVG metadata in {visual} does not preserve the canonical entity name")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref")
    args = parser.parse_args()
    errors = validate(args.base_ref, ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    mode = f"; new rows checked against current State outcomes relative to {args.base_ref}" if args.base_ref else "; structural snapshot validation"
    print(f"canonical entity provenance snapshots: OK{mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
