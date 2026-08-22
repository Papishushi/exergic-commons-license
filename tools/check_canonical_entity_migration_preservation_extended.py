#!/usr/bin/env python3
"""Run base-relative migration preservation plus immutable identity-core guards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import canonical_dossier_contract as contract
import check_canonical_entity_migration_preservation as checker

checker.TYPE_DIR = dict(contract.TYPE_DIR)
checker.ENTITY_SUFFIXES = set(contract.ENTITY_SUFFIXES)

ROOT = Path(__file__).resolve().parents[1]
ENTITY_REL_DIR = Path("knowledge/entities")
IMMUTABLE_IDENTITY_FIELDS = ("id", "iri", "type")
ATOMIC_IDENTITY_ALLOWED_FIELDS = {
    "@context", "iri", "id", "type", "name", "aliases", "dossier", "provenance",
    "lastSubstantiveReview", "reviewDue", "reviewClass", "reviewReason", "identityLifecycle",
}


def _supported_base_records(base_ref: str, root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for rel in checker.git_paths(base_ref, ENTITY_REL_DIR.as_posix(), root):
        if Path(rel).suffix not in contract.ENTITY_SUFFIXES:
            continue
        content = checker.git_show(base_ref, rel, root)
        if content is None:
            raise RuntimeError(f"cannot read base entity {rel} at {base_ref}")
        record = json.loads(content)
        entity_id = record.get("id") if isinstance(record, dict) else None
        if record.get("type") in contract.TYPE_DIR and isinstance(entity_id, str) and entity_id:
            result[entity_id] = record
    return result


def validate_baseline_identity_preservation(base_ref: str, root: Path = ROOT) -> list[str]:
    """Stable ID/IRI/type survive review-metadata and lifecycle evolution."""
    try:
        base_records = _supported_base_records(base_ref, root)
        current = checker.current_entity_index(root)
    except (RuntimeError, json.JSONDecodeError) as exc:
        return [str(exc)]

    errors: list[str] = []
    for entity_id, before in sorted(base_records.items()):
        current_entry = current.get(entity_id)
        if current_entry is None:
            errors.append(
                f"{entity_id}: supported non-State identity existed at comparison base {base_ref} "
                "but was deleted; use identityLifecycle/supersededBy rather than shrinking the coverage denominator"
            )
            continue
        after, _rel = current_entry
        for field in IMMUTABLE_IDENTITY_FIELDS:
            if before.get(field) != after.get(field):
                errors.append(
                    f"{entity_id}: immutable identity core field {field!r} changed "
                    f"{before.get(field)!r} -> {after.get(field)!r}; supersede/retire the identity instead"
                )
    return errors


def validate_atomic_identity_only_additions(base_ref: str, root: Path = ROOT) -> list[str]:
    """A v50+ atomic identity may not smuggle curated graph relationships."""
    try:
        base = checker.base_entity_index(base_ref, root)
        current = checker.current_entity_index(root)
    except (RuntimeError, json.JSONDecodeError) as exc:
        return [str(exc)]

    errors: list[str] = []
    for entity_id, (record, _rel) in sorted(current.items()):
        if entity_id in base or record.get("type") not in contract.TYPE_DIR:
            continue
        extra = sorted(set(record) - ATOMIC_IDENTITY_ALLOWED_FIELDS)
        if extra:
            errors.append(
                f"{entity_id}: post-v49 atomic identity-only addition contains non-identity fields {extra}; "
                "curate graph relationships in a separate reviewed change after identity registration"
            )
        lifecycle = record.get("identityLifecycle", "active")
        if lifecycle != "active":
            errors.append(
                f"{entity_id}: new atomic identity must begin active (or omit identityLifecycle), got {lifecycle!r}"
            )
        if "supersededBy" in record:
            errors.append(f"{entity_id}: a newly registered atomic identity cannot arrive already superseded")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", required=True)
    args = parser.parse_args()

    migration_errors, stats = checker.validate(args.base_ref, ROOT)
    identity_errors = validate_baseline_identity_preservation(args.base_ref, ROOT)
    atomic_errors = validate_atomic_identity_only_additions(args.base_ref, ROOT)
    errors = migration_errors + identity_errors + atomic_errors
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"canonical migration preservation: FAILED ({len(errors)} error(s))")
        return 1

    print(
        "canonical migration preservation: OK "
        f"({stats['newlyMigrated']} new ledger row(s); {stats['atomicNew']} atomic post-v49 identity addition(s); "
        "existing migrations preserve source/dossier-only changes; immutable id/iri/type core is preserved; "
        "atomic new identities are relationship-free; all new non-State identities are ledgered)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
