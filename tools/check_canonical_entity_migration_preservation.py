#!/usr/bin/env python3
"""Verify base-relative ABox preservation and future canonical-ledger completeness.

Historical migrations (v1-v49) may only migrate identities that already existed
at the comparison base, from a non-dedicated dossier pointer to a dedicated one,
changing no ABox field except ``dossier``. Post-closure manifests (v50+) may also
introduce a new non-State identity atomically, but every such new identity must
appear in a newly appended manifest and already point at its dedicated dossier.
For an existing identity, ``sourceDossier`` must equal the dossier pointer at the
comparison base so State provenance cannot be silently substituted.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL_DIR = Path("knowledge/generated")
ENTITY_REL_DIR = Path("knowledge/entities")
ALLOWED_CHANGED_FIELDS = {"dossier"}
MANIFEST_RE = re.compile(r"^knowledge/generated/canonical-entity-dossier-migration-v(\d+)\.json$")
FROZEN_FINAL_VERSION = 49
TYPE_DIR = {
    "Agency": "agencies",
    "Institution": "institutions",
    "Organization": "organizations",
    "Person": "persons",
    "Project": "projects",
}
ENTITY_SUFFIXES = {".json", ".jsonld"}
_MISSING = object()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def git_show(ref: str, rel: str, root: Path = ROOT) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def git_paths(ref: str, rel_dir: str, root: Path = ROOT) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", rel_dir],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cannot list {rel_dir} at {ref}: {proc.stderr.strip()}")
    return proc.stdout.splitlines()


def base_migrated_ids(ref: str, root: Path = ROOT) -> set[str]:
    ids: set[str] = set()
    for rel in git_paths(ref, MANIFEST_REL_DIR.as_posix(), root):
        match = MANIFEST_RE.match(rel)
        if not match:
            continue
        content = git_show(ref, rel, root)
        if content is None:
            raise RuntimeError(f"cannot read historical migration manifest {rel} at {ref}")
        manifest = json.loads(content)
        rows = manifest.get("entities")
        if not isinstance(rows, list):
            raise RuntimeError(f"historical migration manifest {rel} has invalid entities payload")
        for row in rows:
            entity_id = row.get("id") if isinstance(row, dict) else None
            if not isinstance(entity_id, str) or not entity_id:
                raise RuntimeError(f"historical migration manifest {rel} contains a row without id")
            ids.add(entity_id)
    return ids


def current_entity_index(root: Path = ROOT) -> dict[str, tuple[dict, str]]:
    entity_dir = root / ENTITY_REL_DIR
    paths = sorted(
        path for path in entity_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in ENTITY_SUFFIXES
    )
    result: dict[str, tuple[dict, str]] = {}
    for path in paths:
        record = load_json(path)
        entity_id = record.get("id") if isinstance(record, dict) else None
        if not isinstance(entity_id, str) or not entity_id:
            continue
        rel = path.relative_to(root).as_posix()
        if entity_id in result:
            raise RuntimeError(f"duplicate current ABox entity id {entity_id}: {result[entity_id][1]} and {rel}")
        result[entity_id] = (record, rel)
    return result


def base_entity_index(ref: str, root: Path = ROOT) -> dict[str, tuple[dict, str]]:
    result: dict[str, tuple[dict, str]] = {}
    for rel in git_paths(ref, ENTITY_REL_DIR.as_posix(), root):
        if Path(rel).suffix.lower() not in ENTITY_SUFFIXES:
            continue
        content = git_show(ref, rel, root)
        if content is None:
            raise RuntimeError(f"cannot read ABox entity {rel} at {ref}")
        record = json.loads(content)
        entity_id = record.get("id") if isinstance(record, dict) else None
        if not isinstance(entity_id, str) or not entity_id:
            continue
        if entity_id in result:
            raise RuntimeError(f"duplicate base ABox entity id {entity_id}: {result[entity_id][1]} and {rel}")
        result[entity_id] = (record, rel)
    return result


def field_value(record: dict, key: str) -> object:
    return record[key] if key in record else _MISSING


def display_value(record: dict, key: str) -> str:
    return repr(record[key]) if key in record else "<absent>"


def changed_fields(before: dict, after: dict) -> list[str]:
    return sorted(
        key for key in set(before) | set(after)
        if field_value(before, key) != field_value(after, key)
    )


def dossier_repo_path(entity_rel: str, dossier_ref: object) -> str | None:
    if not isinstance(dossier_ref, str) or not dossier_ref:
        return None
    normalized = posixpath.normpath(
        posixpath.join(posixpath.dirname(entity_rel), dossier_ref.replace("\\", "/"))
    )
    if normalized == ".." or normalized.startswith("../"):
        return None
    return normalized


def dedicated_pointer(record: dict, entity_rel: str) -> bool:
    expected_dir = TYPE_DIR.get(record.get("type"))
    rel = dossier_repo_path(entity_rel, record.get("dossier"))
    return (
        expected_dir is not None
        and rel is not None
        and rel.startswith(f"dossiers/{expected_dir}/")
        and rel.endswith(".md")
    )


def manifest_version(path: Path) -> int:
    return int(path.stem.rsplit("v", 1)[1])


def validate(base_ref: str, root: Path = ROOT) -> tuple[list[str], dict[str, int]]:
    manifest_dir = root / MANIFEST_REL_DIR
    manifests = sorted(
        manifest_dir.glob("canonical-entity-dossier-migration-v*.json"),
        key=manifest_version,
    )
    errors: list[str] = []
    seen: set[str] = set()
    newly_migrated: set[str] = set()
    atomic_new: set[str] = set()

    try:
        historical_ids = base_migrated_ids(base_ref, root)
        current_entities = current_entity_index(root)
        base_entities = base_entity_index(base_ref, root)
    except (RuntimeError, json.JSONDecodeError) as exc:
        return [str(exc)], {"newlyMigrated": 0, "atomicNew": 0, "manifestlessNew": 0}

    for manifest_path in manifests:
        version = manifest_version(manifest_path)
        manifest = load_json(manifest_path)
        rows = manifest.get("entities", [])
        if not isinstance(rows, list):
            errors.append(f"{manifest_path.relative_to(root)}: entities payload must be a list")
            continue
        for row in rows:
            entity_id = row.get("id") if isinstance(row, dict) else None
            if not isinstance(entity_id, str) or not entity_id:
                errors.append(f"{manifest_path.relative_to(root)}: missing entity id")
                continue
            if entity_id in seen:
                errors.append(
                    f"{manifest_path.relative_to(root)}: duplicate migrated entity across manifests: {entity_id}"
                )
                continue
            seen.add(entity_id)

            # Rows already recorded at the comparison base are immutable at the
            # manifest layer and are deliberately not used to freeze later ABox
            # review-metadata updates.
            if entity_id in historical_ids:
                continue

            newly_migrated.add(entity_id)
            current_entry = current_entities.get(entity_id)
            if current_entry is None:
                errors.append(f"{entity_id}: current ABox entity file is missing (.json/.jsonld)")
                continue
            after, after_rel = current_entry
            before_entry = base_entities.get(entity_id)

            if before_entry is None:
                if version <= FROZEN_FINAL_VERSION:
                    errors.append(
                        f"{entity_id}: entity did not exist at comparison base {base_ref}; "
                        f"frozen v1-v{FROZEN_FINAL_VERSION} migrations must not create ABox identities"
                    )
                    continue
                atomic_new.add(entity_id)
                if after.get("type") not in TYPE_DIR:
                    errors.append(f"{entity_id}: post-closure atomic identity is not a supported non-State type")
                if not dedicated_pointer(after, after_rel):
                    errors.append(
                        f"{entity_id}: post-closure atomic identity must arrive with a type-appropriate dedicated dossier"
                    )
                continue

            before, before_rel = before_entry
            if dedicated_pointer(before, before_rel):
                errors.append(
                    f"{entity_id}: comparison base already pointed to a type-appropriate dedicated dossier; "
                    "this is not a new dossier migration"
                )
            if not dedicated_pointer(after, after_rel):
                errors.append(
                    f"{entity_id}: newly introduced migration does not end at a type-appropriate dedicated dossier"
                )

            expected_source = dossier_repo_path(before_rel, before.get("dossier"))
            source = row.get("sourceDossier")
            if expected_source is None:
                errors.append(f"{entity_id}: comparison-base dossier pointer is missing or escapes the repository")
            elif source != expected_source:
                errors.append(
                    f"{entity_id}: sourceDossier {source!r} does not match comparison-base dossier "
                    f"provenance {expected_source!r}"
                )

            changed = changed_fields(before, after)
            illegal = [field for field in changed if field not in ALLOWED_CHANGED_FIELDS]
            if illegal:
                details = ", ".join(
                    f"{field}: {display_value(before, field)} -> {display_value(after, field)}"
                    for field in illegal
                )
                errors.append(f"{entity_id}: non-dossier ABox mutation: {details}")
            if "dossier" not in changed:
                errors.append(f"{entity_id}: newly introduced migration row does not change the dossier pointer")

    # Once v49 closes the backlog, every new supported non-State identity must
    # be entered into the append-only migration ledger in the same change. This
    # prevents a dedicated dossier from bypassing State/source/visual guards.
    new_non_state = {
        entity_id
        for entity_id, (record, _rel) in current_entities.items()
        if record.get("type") in TYPE_DIR
        and (
            entity_id not in base_entities
            or base_entities[entity_id][0].get("type") not in TYPE_DIR
        )
    }
    manifestless_new = sorted(new_non_state - newly_migrated)
    for entity_id in manifestless_new:
        errors.append(
            f"{entity_id}: new non-State ABox identity is not represented in a newly appended canonical migration manifest"
        )

    stats = {
        "newlyMigrated": len(newly_migrated),
        "atomicNew": len(atomic_new),
        "manifestlessNew": len(manifestless_new),
    }
    return errors, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", required=True)
    args = parser.parse_args()

    errors, stats = validate(args.base_ref, ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"canonical migration preservation: FAILED ({len(errors)} error(s))")
        return 1

    print(
        "canonical migration preservation: OK "
        f"({stats['newlyMigrated']} new ledger row(s); {stats['atomicNew']} atomic post-v49 identity addition(s); "
        "existing identities are non-dedicated -> dedicated, preserve base sourceDossier, and change only dossier; "
        "all new non-State identities are ledgered)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
