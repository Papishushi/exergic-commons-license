#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from entity_identity_resolution import canonicalize_id, load_id_supersessions

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = sorted((ROOT / "knowledge" / "generated").glob("state-dossier-entity-scaleout-v*.json"))
FORBIDDEN_GOVERNANCE = {
    "provisional_outcome", "outcome", "tier", "derived_outcome", "score_outcome",
    "governanceStatus", "governanceOutcome", "restrictionStatus"
}
FORBIDDEN_RELATIONS = {
    "controls", "controlledBy", "partOf", "operates", "participatesIn", "deploys",
    "materiallyBenefits", "tracks", "remediates", "reviews"
}
ALLOWED_TYPES = {"Agency", "Organization", "Institution", "Person", "Project", "Deployment"}


def main() -> int:
    assert MANIFESTS, "no entity scale-out manifests"
    supersessions = load_id_supersessions()
    all_historical_ids: list[str] = []
    promotion_count = 0
    superseded_count = 0
    for manifest_path in MANIFESTS:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = manifest["identities"]
        assert manifest["relationClaims"] == []
        assert manifest["formalAssessments"] == []
        assert manifest["governanceChanges"] == []
        for row in rows:
            promotion_count += 1
            historical_id = row["id"]
            all_historical_ids.append(historical_id)
            entity_id = canonicalize_id(historical_id, supersessions)
            if entity_id != historical_id:
                superseded_count += 1
                old_path = ROOT / "knowledge" / "entities" / f"{historical_id}.json"
                assert not old_path.exists(), f"superseded identity source still materialized: {old_path}"
            path = ROOT / "knowledge" / "entities" / f"{entity_id}.json"
            assert path.exists(), f"missing promoted/canonical identity: {path} (historical {historical_id})"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["id"] == entity_id
            assert data["iri"] == f"ecl:{entity_id}"
            assert data["type"] == row["type"] in ALLOWED_TYPES
            assert isinstance(data.get("name"), str) and data["name"].strip()
            assert not (FORBIDDEN_GOVERNANCE & set(data)), (entity_id, FORBIDDEN_GOVERNANCE & set(data))
            assert not (FORBIDDEN_RELATIONS & set(data)), (entity_id, FORBIDDEN_RELATIONS & set(data))
            dossier = (path.parent / data["dossier"]).resolve()
            assert dossier.exists(), (entity_id, dossier)
            source = ROOT / row["source"]
            assert source.exists(), (historical_id, source)
    assert len(all_historical_ids) == len(set(all_historical_ids)), "duplicate promoted stable id across historical manifests"
    print(
        f"identity scale-out tests: OK ({promotion_count} historical promotions across "
        f"{len(MANIFESTS)} manifests; {superseded_count} canonicalized IDs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
