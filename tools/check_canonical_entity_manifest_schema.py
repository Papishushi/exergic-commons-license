#!/usr/bin/env python3
"""Validate strict canonical migration filenames and JSON Schema payloads."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

import canonical_dossier_contract as contract

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/canonical-entity-dossier-migration.schema.json"


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    schema = json.loads((root / "schemas/canonical-entity-dossier-migration.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    paths, naming_errors = contract.strict_manifest_paths(root)
    errors.extend(naming_errors)
    if not paths:
        errors.append("no strictly named canonical migration manifests found")
        return errors
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.relative_to(root)}: invalid JSON: {exc}")
            continue
        match = contract.MANIFEST_NAME_RE.fullmatch(path.name)
        filename_version = int(match.group(1)) if match else None
        if type(payload.get("version")) is not int:
            errors.append(f"{path.relative_to(root)}: version must be a JSON integer, not bool/float/string")
        elif payload.get("version") != filename_version:
            errors.append(
                f"{path.relative_to(root)}: internal version {payload.get('version')!r} != filename version {filename_version}"
            )
        if type(payload.get("maxMissingDedicatedDossiers")) is not int:
            errors.append(
                f"{path.relative_to(root)}: maxMissingDedicatedDossiers must be a JSON integer, not bool/float/string"
            )
        for violation in sorted(validator.iter_errors(payload), key=lambda err: list(err.path)):
            location = ".".join(str(part) for part in violation.path) or "<root>"
            errors.append(f"{path.relative_to(root)}: schema violation at {location}: {violation.message}")
    return errors


def main() -> int:
    errors = validate(ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    paths, _ = contract.strict_manifest_paths(ROOT)
    print(f"canonical migration manifest schema: OK ({len(paths)} strictly named manifests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
