#!/usr/bin/env python3
"""Render dossier visuals while preserving manifest snapshots and live State status truth.

`stateContext` in a migration manifest is immutable provenance. Status cards are
*live derived context*: at render time they read the current State dossier so a
later governance change cannot leave a present-tense status card stale. Evidence
visuals remain bound to the immutable migration row.
"""
from __future__ import annotations

from pathlib import Path

import render_dossier_visuals_legacy as legacy

ROOT = Path(__file__).resolve().parents[1]
_GENERIC_NAME = "Canonical non-State identity"
_GENERIC_MODEL = {
    "source": "Linked State dossier + ABox identity record",
    "proposition": "Dedicated dossier migration preserves an identity-only non-State record",
    "boundary": "No entity-level governance inference",
}
_VALID_STATE_CONTEXTS = {"R", "S", "U", "N"}

_original_load_entities = legacy.load_entities
_original_status_svg = legacy.status_svg
_original_evidence_svg = legacy.evidence_svg


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
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


def _current_state_context(entity: dict) -> str:
    state = entity.get("state")
    if not isinstance(state, str) or not state:
        raise SystemExit(f"{entity.get('id', '<missing-id>')}: manifest row has no State provenance code")
    dossier = ROOT / "dossiers/states" / f"{state}.md"
    if not dossier.is_file():
        raise SystemExit(f"{entity.get('id', '<missing-id>')}: missing current State dossier {dossier}")
    outcome = _frontmatter(dossier).get("provisional_outcome")
    if outcome not in _VALID_STATE_CONTEXTS:
        raise SystemExit(
            f"{entity.get('id', '<missing-id>')}: current {state} State dossier has invalid provisional_outcome {outcome!r}"
        )
    return outcome


def load_entities(manifest_dir: Path) -> list[dict]:
    rows = _original_load_entities(manifest_dir)
    normalized_ids: set[str] = set()
    for path in manifest_dir.glob("canonical-entity-dossier-migration-v*.json"):
        version = int(path.stem.rsplit("v", 1)[1])
        if version < 40:
            continue
        manifest = legacy.load_json(path)
        normalized_ids.update(row["id"] for row in manifest["entities"])
    for row in rows:
        if row["id"] in normalized_ids:
            row["_normalized_visual_v40"] = True
    return rows


def normalized(entity: dict) -> dict:
    if not entity.get("_normalized_visual_v40"):
        return entity
    rendered = dict(entity)
    rendered["name"] = _GENERIC_NAME
    rendered["visualModel"] = dict(_GENERIC_MODEL)
    return rendered


def _restore_metadata_name(svg: str, entity: dict) -> str:
    generic = legacy.esc(_GENERIC_NAME)
    actual = legacy.esc(entity["name"])
    svg = svg.replace(f'<title id="title">{generic} —', f'<title id="title">{actual} —', 1)
    svg = svg.replace(f'not inherited by {generic}.</desc>', f'not inherited by {actual}.</desc>', 1)
    return svg


def status_svg(entity: dict, palette: dict) -> str:
    live = dict(entity)
    live["stateContext"] = _current_state_context(entity)
    if not entity.get("_normalized_visual_v40"):
        return _original_status_svg(live, palette)
    return _restore_metadata_name(_original_status_svg(normalized(live), palette), entity)


def evidence_svg(entity: dict) -> str:
    if not entity.get("_normalized_visual_v40"):
        return _original_evidence_svg(entity)
    return _restore_metadata_name(_original_evidence_svg(normalized(entity)), entity)


legacy.load_entities = load_entities
legacy.status_svg = status_svg
legacy.evidence_svg = evidence_svg


if __name__ == "__main__":
    raise SystemExit(legacy.main())
