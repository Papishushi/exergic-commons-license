#!/usr/bin/env python3
"""Overlay reviewed dispositions on the broad State-dossier discovery audit.

The raw audit intentionally over-generates candidates. This tool records human-reviewed
State-scoped decisions without mutating the raw discovery output or treating a disposition
as attribution/governance. `curated-identity` only binds a mention to existing ABox IDs;
`deferred` preserves insufficient precision; `rejected` classifies extractor noise or a
non-individual at the current ontology granularity.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from entity_identity_resolution import canonicalize_id, load_id_supersessions

ROOT = Path(__file__).resolve().parents[1]
ENTITY_DIR = ROOT / "knowledge" / "entities"
GENERATED_DIR = ROOT / "knowledge" / "generated"
DISPOSITION_GLOB = "state-dossier-prose-dispositions-v*.json"
ALLOWED_STATUSES = {"curated-identity", "deferred", "rejected"}
STATE_RE = re.compile(r"^[A-Z]{3}$")


def load_entity_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted(ENTITY_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entity_id = data.get("id")
        if isinstance(entity_id, str):
            ids.add(entity_id)
    return ids


def load_dispositions() -> tuple[dict[tuple[str, str], dict], list[str]]:
    entity_ids = load_entity_ids()
    supersessions = load_id_supersessions()
    by_key: dict[tuple[str, str], dict] = {}
    manifests: list[str] = []
    for path in sorted(GENERATED_DIR.glob(DISPOSITION_GLOB)):
        manifests.append(str(path.relative_to(ROOT)))
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("dispositions", []):
            state = row.get("state")
            normalized = row.get("normalized")
            status = row.get("status")
            reason = row.get("reason")
            source = row.get("source")
            assert isinstance(state, str) and STATE_RE.fullmatch(state), (path, row)
            assert isinstance(normalized, str) and normalized.strip() == normalized and normalized, (path, row)
            assert status in ALLOWED_STATUSES, (path, row)
            assert isinstance(reason, str) and reason.strip(), (path, row)
            assert isinstance(source, str) and (ROOT / source).exists(), (path, row)
            key = (state, normalized)
            assert key not in by_key, f"duplicate prose disposition key: {key}"
            resolved_ids = row.get("resolved_ids", [])
            reviewed = dict(row)
            if status == "curated-identity":
                assert isinstance(resolved_ids, list) and resolved_ids, (path, row)
                canonical_ids = [canonicalize_id(item, supersessions) for item in resolved_ids]
                assert all(isinstance(item, str) and item in entity_ids for item in canonical_ids), (path, row, canonical_ids)
                reviewed["resolved_ids"] = canonical_ids
                if canonical_ids != resolved_ids:
                    reviewed["historical_resolved_ids"] = list(resolved_ids)
            else:
                assert resolved_ids in ([], None), (path, row)
            by_key[key] = reviewed
    return by_key, manifests


def load_ratchet(path: Path) -> tuple[int, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    threshold = data.get("min_review_priority")
    assert isinstance(threshold, int) and threshold >= 0, (path, threshold)
    assert isinstance(data.get("version"), int) and data["version"] >= 1, path
    assert isinstance(data.get("reason"), str) and data["reason"].strip(), path
    return threshold, data


def review(audit: dict, dispositions: dict[tuple[str, str], dict], priority_threshold: int | None = None) -> dict:
    raw = [item for item in audit["candidates"] if item["resolution"] == "review-candidate"]
    occurrence_keys: set[tuple[str, str]] = set()
    for candidate in audit["candidates"]:
        for occurrence in candidate.get("occurrences", []):
            state = occurrence.get("state")
            normalized = occurrence.get("normalized")
            if isinstance(state, str) and isinstance(normalized, str):
                occurrence_keys.add((state, normalized))

    raw_keys: set[tuple[str, str]] = set()
    rows: list[dict] = []
    status_counts: Counter = Counter()
    for candidate in raw:
        assert len(candidate["states"]) == 1, candidate
        state = candidate["states"][0]
        key = (state, candidate["normalized"])
        raw_keys.add(key)
        disposition = dispositions.get(key)
        review_status = disposition["status"] if disposition else "unreviewed"
        status_counts[review_status] += 1
        rows.append({
            "state": state,
            "candidate": candidate["candidate"],
            "normalized": candidate["normalized"],
            "review_priority": candidate["review_priority"],
            "raw_kinds": candidate["kinds"],
            "review_status": review_status,
            "resolved_ids": (disposition or {}).get("resolved_ids", []),
            "reason": (disposition or {}).get("reason"),
            "source": (disposition or {}).get("source"),
        })

    stale = []
    for key, disposition in sorted(dispositions.items()):
        if key in raw_keys:
            continue
        if disposition["status"] == "curated-identity" and key in occurrence_keys:
            continue
        stale.append({"state": key[0], "normalized": key[1], "status": disposition["status"]})

    rows.sort(key=lambda item: (
        item["review_status"] != "unreviewed",
        -item["review_priority"],
        item["state"],
        item["candidate"].lower(),
    ))
    threshold = priority_threshold
    high_unreviewed = [
        row for row in rows
        if row["review_status"] == "unreviewed"
        and threshold is not None
        and row["review_priority"] >= threshold
    ]
    reviewed_total = sum(status_counts[state] for state in ALLOWED_STATUSES)
    return {
        "schema_version": 1,
        "semantics": {
            "purpose": "review overlay for broad State-dossier discovery candidates",
            "raw_audit_remains_authoritative_for_discovery": True,
            "non_inference": [
                "curated-identity is identity resolution only",
                "deferred is insufficient precision, not adverse evidence",
                "rejected classifies the extractor candidate, not the underlying subject",
                "no review status changes Claims, Formal Exergism or governance",
            ],
        },
        "counts": {
            "raw_review_candidates": len(raw),
            "reviewed_total": reviewed_total,
            "curated_identity": status_counts["curated-identity"],
            "deferred": status_counts["deferred"],
            "rejected": status_counts["rejected"],
            "unreviewed": status_counts["unreviewed"],
            "stale_dispositions": len(stale),
            "priority_threshold": threshold,
            "unreviewed_at_or_above_threshold": len(high_unreviewed),
        },
        "stale_dispositions": stale,
        "unreviewed_at_or_above_threshold": high_unreviewed,
        "candidates": rows,
    }


def write_markdown(report: dict, path: Path) -> None:
    counts = report["counts"]
    lines = [
        "# Reviewed State-dossier candidate overlay",
        "",
        "> Curation metadata only. No row is a Claim, attribution, Formal Exergism assessment or governance decision.",
        "",
        f"- Raw review candidates: **{counts['raw_review_candidates']}**",
        f"- Reviewed: **{counts['reviewed_total']}**",
        f"  - curated identity: **{counts['curated_identity']}**",
        f"  - deferred: **{counts['deferred']}**",
        f"  - rejected extractor candidate: **{counts['rejected']}**",
        f"- Unreviewed: **{counts['unreviewed']}**",
        f"- Stale dispositions: **{counts['stale_dispositions']}**",
    ]
    if counts["priority_threshold"] is not None:
        lines.append(
            f"- Unreviewed with priority >= {counts['priority_threshold']}: "
            f"**{counts['unreviewed_at_or_above_threshold']}**"
        )
    lines += [
        "", "## Highest-priority unreviewed candidates", "",
        "| State | Candidate | Kind | Priority |", "|---|---|---|---:|",
    ]
    for row in report["candidates"]:
        if row["review_status"] != "unreviewed":
            continue
        candidate = row["candidate"].replace("|", "\\|")
        kinds = ", ".join(row["raw_kinds"]).replace("|", "\\|")
        lines.append(f"| {row['state']} | {candidate} | {kinds} | {row['review_priority']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def self_test() -> None:
    fake = {"candidates": [
        {"candidate":"The Court","normalized":"the court","resolution":"review-candidate","states":["AAA"],"review_priority":50,"kinds":["actor-or-institution"],"occurrences":[{"state":"AAA","normalized":"the court"}]},
        {"candidate":"Noise","normalized":"noise","resolution":"review-candidate","states":["BBB"],"review_priority":10,"kinds":["acronym-review"],"occurrences":[{"state":"BBB","normalized":"noise"}]},
    ]}
    dispositions = {("AAA", "the court"): {"state":"AAA","normalized":"the court","status":"deferred","reason":"not exact","source":"x"}}
    report = review(fake, dispositions, 42)
    assert report["counts"]["deferred"] == 1
    assert report["counts"]["unreviewed"] == 1
    assert report["counts"]["unreviewed_at_or_above_threshold"] == 0
    assert report["unreviewed_at_or_above_threshold"] == []
    assert canonicalize_id("AGENCY-PHL-PNP", {"AGENCY-PHL-PNP": "AGENCY-PHL-PHILIPPINE-NATIONAL-POLICE"}) == "AGENCY-PHL-PHILIPPINE-NATIONAL-POLICE"
    print("State dossier candidate review self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--fail-on-unreviewed-priority", type=int)
    parser.add_argument("--ratchet-config", type=Path)
    parser.add_argument("--fail-on-stale-disposition", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.audit is None:
        parser.error("--audit is required unless --self-test is used")
    if args.fail_on_unreviewed_priority is not None and args.ratchet_config is not None:
        parser.error("use either --fail-on-unreviewed-priority or --ratchet-config, not both")

    threshold = args.fail_on_unreviewed_priority
    ratchet = None
    if args.ratchet_config is not None:
        threshold, ratchet = load_ratchet(args.ratchet_config)

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    dispositions, manifests = load_dispositions()
    report = review(audit, dispositions, threshold)
    report["disposition_manifests"] = manifests
    if ratchet is not None:
        report["ratchet"] = {
            "config": str(args.ratchet_config), "version": ratchet["version"],
            "min_review_priority": threshold, "reason": ratchet["reason"],
        }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(report, args.markdown)
    print(json.dumps(report["counts"], sort_keys=True))
    if args.fail_on_stale_disposition and report["counts"]["stale_dispositions"]:
        print("STALE_DISPOSITIONS=" + json.dumps(report["stale_dispositions"], ensure_ascii=False, sort_keys=True))
        return 4
    if threshold is not None and report["counts"]["unreviewed_at_or_above_threshold"]:
        print("UNREVIEWED_RATCHET_DRIFT=" + json.dumps(report["unreviewed_at_or_above_threshold"], ensure_ascii=False, sort_keys=True))
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
