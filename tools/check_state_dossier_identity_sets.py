#!/usr/bin/env python3
"""Require exact set equality between canonical State dossiers and State identities."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOSSIERS = ROOT / "dossiers" / "states"
ENTITIES = ROOT / "knowledge" / "entities"
FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
DOSSIER_ID = re.compile(r"^ECL-STATE-([A-Z]{3})$")
ENTITY_ID = re.compile(r"^STATE-([A-Z]{3})$")


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONT.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def main() -> int:
    dossier_by_iso: dict[str, str] = {}
    for path in sorted(DOSSIERS.glob("*.md")):
        data = frontmatter(path)
        match = DOSSIER_ID.fullmatch(data.get("id", ""))
        if not match or data.get("iso3") != match.group(1):
            continue
        iso = match.group(1)
        # A canonical State dossier has three independent agreement points:
        # filename, iso3, and ECL-STATE-<ISO3>. This intentionally excludes
        # `_TEMPLATE.md` even though its example frontmatter uses XXX.
        if path.stem != iso:
            continue
        if iso in dossier_by_iso:
            print(f"duplicate canonical dossier for {iso}: {dossier_by_iso[iso]} and {path}")
            return 2
        dossier_by_iso[iso] = str(path.relative_to(ROOT))

    identity_by_iso: dict[str, str] = {}
    for path in sorted(ENTITIES.glob("STATE-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") != "State":
            continue
        match = ENTITY_ID.fullmatch(data.get("id", ""))
        if not match:
            print(f"malformed State identity id in {path.relative_to(ROOT)}: {data.get('id')!r}")
            return 3
        iso = match.group(1)
        if path.stem != data.get("id"):
            print(f"State identity filename/id mismatch: {path.relative_to(ROOT)} -> {data.get('id')!r}")
            return 4
        if iso in identity_by_iso:
            print(f"duplicate State identity for {iso}: {identity_by_iso[iso]} and {path}")
            return 5
        identity_by_iso[iso] = str(path.relative_to(ROOT))

    dossier_set = set(dossier_by_iso)
    identity_set = set(identity_by_iso)
    missing_identity = sorted(dossier_set - identity_set)
    missing_dossier = sorted(identity_set - dossier_set)
    report = {
        "canonical_state_dossiers": len(dossier_set),
        "state_identities": len(identity_set),
        "dossiers_without_state_identity": [
            {"iso3": iso, "dossier": dossier_by_iso[iso]} for iso in missing_identity
        ],
        "state_identities_without_dossier": [
            {"iso3": iso, "entity": identity_by_iso[iso]} for iso in missing_dossier
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if missing_identity or missing_dossier else 0


if __name__ == "__main__":
    sys.exit(main())
