#!/usr/bin/env python3
"""Audit ABox coverage of already-curated State Schedule-freeze references.

This is an identity-coverage gate, not an attribution engine. Every actor/project
reference in the curated freeze corpus must either resolve to one or more exact ABox
identities or carry an explicit reviewed deferral. Domestic heuristic resolution is
State-scoped; explicit reviewed dispositions may intentionally bind cross-State referents.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import yaml

from entity_identity_resolution import build_name_index, eligible_in_state

ROOT = Path(__file__).resolve().parents[1]
FREEZE_DIR = ROOT / "registry" / "schedule-state-s-freezes"
ENTITY_DIR = ROOT / "knowledge" / "entities"
DISPOSITION_GLOB = "schedule-reference-dispositions-v*.json"

ACTOR_FIELDS = (
    "candidate_parties", "candidate_party", "identified_operators", "identified_operator",
    "identified_parties", "identified_party",
)
PROJECT_FIELDS = (
    "candidate_projects", "candidate_project", "identified_projects", "identified_project",
)
SCOPE_FIELDS = (
    "schedule_identity", "project_boundary", "identified_incident", "identified_measure",
    "identified_location", "binding_remediation",
)
CAPACITY_SPLITS = (", only ", ", including ", " only when ", " only in ", " only where ")
VALID_DISPOSITIONS = {"bound", "deferred", "partial-deferred"}


def norm(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_entities():
    rows: list[dict] = []
    by_id: dict[str, dict] = {}
    state_codes: set[str] = set()
    raw_non_state: list[dict] = []
    for path in sorted(ENTITY_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") == "State":
            state_id = data.get("id", "")
            if isinstance(state_id, str) and state_id.startswith("STATE-") and len(state_id) == 9:
                state_codes.add(state_id[6:])
            continue
        names = [data.get("name"), *(data.get("aliases") or [])]
        aliases = sorted({norm(x) for x in names if isinstance(x, str) and norm(x)}, key=len, reverse=True)
        row = {"id": data["id"], "type": data["type"], "aliases": aliases, "name": data.get("name")}
        rows.append(row)
        by_id[data["id"]] = row
        raw_non_state.append(data)
    index = build_name_index(raw_non_state, state_codes=state_codes, normalizer=norm)
    return rows, by_id, index


def load_dispositions() -> list[dict]:
    rows: list[dict] = []
    for path in sorted((ROOT / "knowledge" / "generated").glob(DISPOSITION_GLOB)):
        data = json.loads(path.read_text(encoding="utf-8"))
        for index, row in enumerate(data.get("entries", [])):
            if row.get("disposition") not in VALID_DISPOSITIONS:
                raise ValueError(f"invalid disposition in {path}:{index}: {row.get('disposition')!r}")
            required = {"source", "state", "field", "match_prefix", "disposition", "resolved_ids", "reason"}
            missing = required - set(row)
            if missing:
                raise ValueError(f"missing disposition fields in {path}:{index}: {sorted(missing)}")
            copy = dict(row)
            copy["manifest"] = str(path.relative_to(ROOT))
            rows.append(copy)
    return rows


def records_from_document(data: object) -> list[dict]:
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
        if isinstance(data.get("state"), str):
            return [data]
    return []


def list_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def identity_head(raw: str) -> str:
    head = raw.strip()
    lower = head.lower()
    positions = [lower.find(token) for token in CAPACITY_SPLITS if lower.find(token) >= 0]
    if positions:
        head = head[: min(positions)]
    return head.strip(" .;:")


def heuristic_resolve(raw: str, entities: list[dict], identity_index, expected: str, state: str | None) -> list[str]:
    raw_norm = norm(raw)
    head_norm = norm(identity_head(raw))
    matches: list[tuple[int, str]] = []
    for entity in entities:
        if not eligible_in_state(identity_index, entity["id"], state):
            continue
        is_project = entity["type"] in {"Project", "Deployment"}
        if expected == "actor" and is_project:
            continue
        if expected == "project" and not is_project:
            continue
        for alias in entity["aliases"]:
            if not alias:
                continue
            exact = alias == head_norm or alias == raw_norm
            prefix = len(alias) >= 6 and (head_norm.startswith(alias + " ") or raw_norm.startswith(alias + " "))
            contained = len(alias) >= 12 and f" {alias} " in f" {raw_norm} "
            if exact or prefix or contained:
                matches.append((len(alias), entity["id"]))
                break
    if not matches:
        return []
    best = max(score for score, _ in matches)
    return sorted({entity_id for score, entity_id in matches if score == best})


def matching_disposition(
    source: str, state: str | None, field: str, raw: str, dispositions: list[dict]
) -> dict | None:
    matches = [
        row for row in dispositions
        if row["source"] == source
        and row["state"] == state
        and row["field"] == field
        and raw.startswith(row["match_prefix"])
    ]
    if len(matches) > 1:
        raise ValueError(f"multiple Schedule dispositions match {source} {state} {field}: {raw}")
    return matches[0] if matches else None


def validate_disposition_targets(row: dict, by_id: dict[str, dict], expected: str) -> None:
    for entity_id in row["resolved_ids"]:
        if entity_id not in by_id:
            raise ValueError(f"disposition target does not resolve: {entity_id}")
        is_project = by_id[entity_id]["type"] in {"Project", "Deployment"}
        if expected == "actor" and is_project:
            raise ValueError(f"actor reference bound to Project/Deployment: {entity_id}")
        if expected == "project" and not is_project:
            raise ValueError(f"project reference bound to Actor: {entity_id}")
    if row["disposition"] == "bound" and not row["resolved_ids"]:
        raise ValueError(f"bound disposition has no target: {row}")
    if row["disposition"] == "deferred" and row["resolved_ids"]:
        raise ValueError(f"deferred disposition must not contain target ids: {row}")
    if row["disposition"] == "partial-deferred" and not row["resolved_ids"]:
        raise ValueError(f"partial-deferred disposition needs at least one exact target: {row}")


def reference_row(
    *, kind: str, expected: str, state: str | None, outcome: str | None, field: str, raw: str,
    source: str, record_index: int, entities: list[dict], by_id: dict[str, dict], identity_index,
    dispositions: list[dict]
) -> dict:
    disposition = matching_disposition(source, state, field, raw, dispositions)
    if disposition:
        validate_disposition_targets(disposition, by_id, expected)
        status = {
            "bound": "resolved", "deferred": "deferred", "partial-deferred": "partial-deferred",
        }[disposition["disposition"]]
        matches = list(disposition["resolved_ids"])
        source_kind = "reviewed-disposition"
        reason = disposition["reason"]
        disposition_manifest = disposition["manifest"]
    else:
        matches = heuristic_resolve(raw, entities, identity_index, expected, state)
        status = "resolved" if len(matches) == 1 else ("ambiguous" if matches else "unresolved")
        source_kind = "jurisdiction-safe-canonical-name-or-alias" if matches else None
        reason = None
        disposition_manifest = None
    return {
        "kind": kind, "state": state, "outcome": outcome, "field": field, "raw": raw,
        "identity_head": identity_head(raw), "resolved_ids": matches, "status": status,
        "resolution_source": source_kind, "disposition_reason": reason,
        "disposition_manifest": disposition_manifest, "source": source, "record_index": record_index,
    }


def audit() -> dict:
    entities, by_id, identity_index = load_entities()
    dispositions = load_dispositions()
    references: list[dict] = []
    files = sorted(FREEZE_DIR.glob("*.yml")) + sorted(FREEZE_DIR.glob("*.yaml"))
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        source = str(path.relative_to(ROOT))
        for record_index, record in enumerate(records_from_document(data)):
            state = record.get("state")
            outcome = record.get("outcome")
            for field in ACTOR_FIELDS:
                for raw in list_values(record.get(field)):
                    references.append(reference_row(
                        kind="actor-reference", expected="actor", state=state, outcome=outcome,
                        field=field, raw=raw, source=source, record_index=record_index,
                        entities=entities, by_id=by_id, identity_index=identity_index, dispositions=dispositions,
                    ))
            for field in PROJECT_FIELDS:
                for raw in list_values(record.get(field)):
                    references.append(reference_row(
                        kind="project-reference", expected="project", state=state, outcome=outcome,
                        field=field, raw=raw, source=source, record_index=record_index,
                        entities=entities, by_id=by_id, identity_index=identity_index, dispositions=dispositions,
                    ))
            for field in SCOPE_FIELDS:
                for raw in list_values(record.get(field)):
                    references.append({
                        "kind": "scope-reference", "state": state, "outcome": outcome, "field": field,
                        "raw": raw, "identity_head": None, "resolved_ids": [], "status": "context-only",
                        "resolution_source": None, "disposition_reason": None, "disposition_manifest": None,
                        "source": source, "record_index": record_index,
                    })

    counted = [row for row in references if row["kind"] != "scope-reference"]
    statuses = Counter(row["status"] for row in counted)
    kinds = Counter(row["kind"] for row in counted)
    states = {row["state"] for row in counted if isinstance(row["state"], str)}
    return {
        "schema_version": 3,
        "semantics": {
            "purpose": "coverage audit of already-curated Schedule-preparation actor/project references",
            "completeness_rule": "Every curated actor/project reference must be resolved, deferred or partial-deferred; ambiguous/unresolved is a CI failure.",
            "identity_resolution": "heuristic domestic identity matching is State-scoped; reviewed dispositions may explicitly bind cross-State referents",
            "non_inference": [
                "reference matching is not attribution",
                "identity resolution does not inherit the State outcome",
                "cross-State domestic matching requires an explicit reviewed disposition",
                "scope-reference fields are context only and are never coerced into an Actor or Project identity",
                "deferred and partial-deferred are explicit representation states, not evidence or governance judgments",
            ],
        },
        "counts": {
            "freeze_files": len(files), "states_with_actor_or_project_references": len(states),
            "actor_references": kinds["actor-reference"], "project_references": kinds["project-reference"],
            "resolved": statuses["resolved"], "partial_deferred": statuses["partial-deferred"],
            "deferred": statuses["deferred"], "ambiguous": statuses["ambiguous"],
            "unresolved": statuses["unresolved"],
            "scope_context_references": sum(row["kind"] == "scope-reference" for row in references),
        },
        "references": references,
    }


def write_markdown(report: dict, path: Path) -> None:
    counts = report["counts"]
    rows = [
        "# Schedule freeze reference coverage", "",
        "> Identity-coverage audit only. Resolution has no governance or attribution effect.", "",
        f"- Freeze files: **{counts['freeze_files']}**",
        f"- States with actor/project references: **{counts['states_with_actor_or_project_references']}**",
        f"- Actor references: **{counts['actor_references']}**",
        f"- Project references: **{counts['project_references']}**",
        f"- Resolved: **{counts['resolved']}**",
        f"- Partial/deferred: **{counts['partial_deferred']}**",
        f"- Deferred: **{counts['deferred']}**",
        f"- Ambiguous: **{counts['ambiguous']}**",
        f"- Unresolved: **{counts['unresolved']}**", "",
        "## Non-resolved curated references", "",
        "| State | Kind | Field | Identity head | Status | Reason | Source |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["references"]:
        if row["status"] not in {"deferred", "partial-deferred", "unresolved", "ambiguous"}:
            continue
        head = (row["identity_head"] or row["raw"]).replace("|", "\\|")
        reason = (row["disposition_reason"] or "").replace("|", "\\|")
        rows.append(
            f"| {row['state'] or ''} | {row['kind']} | {row['field']} | {head} | {row['status']} | {reason} | {row['source']} |"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def self_test() -> None:
    assert identity_head("Zambia Police Service, only in qualifying cases") == "Zambia Police Service"
    assert identity_head("NISA only where evidence exists") == "NISA"
    sample = [{
        "source": "x.yml", "state": "ABC", "field": "candidate_parties",
        "match_prefix": "Named Agency", "disposition": "deferred", "resolved_ids": [],
        "reason": "test", "manifest": "m.json"
    }]
    assert matching_disposition("x.yml", "ABC", "candidate_parties", "Named Agency, only here", sample)
    synthetic = [
        {"id": "AGENCY-AAA-NATIONAL-POLICE", "type": "Agency", "aliases": ["national police"]},
        {"id": "AGENCY-BBB-NATIONAL-POLICE", "type": "Agency", "aliases": ["national police"]},
        {"id": "ORG-GLOBAL", "type": "Organization", "aliases": ["global source"]},
    ]
    raw = [
        {"id": "AGENCY-AAA-NATIONAL-POLICE", "type": "Agency", "name": "National Police", "aliases": []},
        {"id": "AGENCY-BBB-NATIONAL-POLICE", "type": "Agency", "name": "National Police", "aliases": []},
        {"id": "ORG-GLOBAL", "type": "Organization", "name": "Global Source", "aliases": []},
    ]
    idx = build_name_index(raw, state_codes={"AAA", "BBB"}, normalizer=norm)
    assert heuristic_resolve("National Police", synthetic, idx, "actor", "AAA") == ["AGENCY-AAA-NATIONAL-POLICE"]
    assert heuristic_resolve("National Police", synthetic, idx, "actor", "CCC") == []
    assert heuristic_resolve("Global Source", synthetic, idx, "actor", "AAA") == ["ORG-GLOBAL"]
    print("Schedule reference audit self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--fail-on-unresolved-curated", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    report = audit()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(report, args.markdown)
    print(json.dumps(report["counts"], sort_keys=True))
    if args.fail_on_unresolved_curated and (report["counts"]["unresolved"] or report["counts"]["ambiguous"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
