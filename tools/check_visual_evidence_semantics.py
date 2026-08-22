#!/usr/bin/env python3
"""Validate normative *visibly rendered* semantics of canonical dossier SVG evidence."""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "knowledge/generated"
PALETTE_PATH = ROOT / "knowledge/generated/dossier-visual-palette-v1.json"
SVG_NS = "{http://www.w3.org/2000/svg}"
TEXTUAL_EQUIVALENT_SECTIONS = ("## Evidence record", "## Evidence gaps", "## Sources")
GRANULARITY_LABELS = {
    "direct": "direct locator",
    "partial": "partial locator / explicit gap",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized(value: str) -> str:
    return " ".join(value.split())


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"[ \t]*([-+]?(?:\d+(?:\.\d*)?|\.\d+))[ \t]*", value)
    if not match:
        return None
    result = float(match.group(1))
    return result if math.isfinite(result) else None


def _style_map(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for declaration in (value or "").split(";"):
        if ":" not in declaration:
            continue
        key, val = declaration.split(":", 1)
        result[key.strip().lower()] = val.strip().lower()
    return result


def _zero(value: str | None) -> bool:
    if value is None:
        return False
    value = value.strip().lower()
    if value.endswith("%"):
        try:
            return float(value[:-1]) <= 0
        except ValueError:
            return False
    try:
        return float(value) <= 0
    except ValueError:
        return False


def _element_hidden(element: ET.Element) -> bool:
    style = _style_map(element.get("style"))
    display = (element.get("display") or style.get("display") or "").strip().lower()
    visibility = (element.get("visibility") or style.get("visibility") or "").strip().lower()
    opacity = element.get("opacity") or style.get("opacity")
    font_size = element.get("font-size") or style.get("font-size")
    fill = (element.get("fill") or style.get("fill") or "").strip().lower()
    fill_opacity = element.get("fill-opacity") or style.get("fill-opacity")
    stroke = (element.get("stroke") or style.get("stroke") or "").strip().lower()
    return (
        display == "none"
        or visibility in {"hidden", "collapse"}
        or _zero(opacity)
        or _zero(font_size)
        or ((fill == "none" or _zero(fill_opacity)) and stroke in {"", "none"})
    )


def _viewbox(root: ET.Element) -> tuple[float, float, float, float] | None:
    raw = root.get("viewBox")
    if not raw:
        return None
    parts = re.split(r"[ ,]+", raw.strip())
    if len(parts) != 4:
        return None
    try:
        x, y, width, height = map(float, parts)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, x + width, y + height


def _inside(bounds: tuple[float, float, float, float] | None, x: float | None, y: float | None) -> bool:
    if bounds is None:
        return True
    if x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
        return False
    x0, y0, x1, y1 = bounds
    return x0 <= x <= x1 and y0 <= y <= y1


def _clip_rects(root: ET.Element) -> dict[str, tuple[float, float, float, float]]:
    result: dict[str, tuple[float, float, float, float]] = {}
    for clip in root.findall(f".//{SVG_NS}clipPath"):
        clip_id = clip.get("id")
        rect = clip.find(f"{SVG_NS}rect")
        if not clip_id or rect is None:
            continue
        vals = [_number(rect.get(attr)) for attr in ("x", "y", "width", "height")]
        if any(value is None for value in vals):
            continue
        x, y, width, height = vals
        assert x is not None and y is not None and width is not None and height is not None
        if width < 0 or height < 0:
            continue
        result[clip_id] = (x, y, x + width, y + height)
    return result


def _clip_id(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.fullmatch(r"url\(#([A-Za-z0-9_.:-]+)\)", raw.strip())
    return match.group(1) if match else None


def _apply_position(
    element: ET.Element,
    current_x: float | None,
    current_y: float | None,
) -> tuple[float | None, float | None] | None:
    x = current_x
    y = current_y
    if element.get("x") is not None:
        x = _number(element.get("x"))
        if x is None:
            return None
    if element.get("y") is not None:
        y = _number(element.get("y"))
        if y is None:
            return None
    if element.get("dx") is not None:
        dx = _number(element.get("dx"))
        if dx is None or x is None:
            return None
        x += dx
    if element.get("dy") is not None:
        dy = _number(element.get("dy"))
        if dy is None or y is None:
            return None
        y += dy
    return x, y


def visible_svg_text(path: Path) -> str | None:
    """Return text that is statically demonstrable as visible.

    Generated canonical SVGs intentionally avoid CSS classes/transforms and
    unsupported visibility indirection. Text coordinates, including sequential
    tspan dx/dy offsets, are resolved statically against both the viewBox and
    the active clipPath rectangle.
    """
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    if root.tag != f"{SVG_NS}svg":
        return None
    if root.find(f".//{SVG_NS}style") is not None:
        return None
    if any("class" in element.attrib or "transform" in element.attrib for element in root.iter()):
        return None
    if any(
        element.tag.rsplit("}", 1)[-1] in {"foreignObject", "textPath", "use"}
        or "mask" in element.attrib
        or "filter" in element.attrib
        for element in root.iter()
    ):
        return None

    bounds = _viewbox(root)
    clips = _clip_rects(root)
    chunks: list[str] = []
    invalid = False

    def walk(
        element: ET.Element,
        hidden: bool,
        inherited_x: float | None,
        inherited_y: float | None,
        inherited_clip: str | None,
    ) -> tuple[float | None, float | None]:
        nonlocal invalid
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"defs", "title", "desc", "metadata"}:
            return inherited_x, inherited_y

        hidden = hidden or _element_hidden(element)
        position = _apply_position(element, inherited_x, inherited_y)
        if position is None:
            invalid = True
            return inherited_x, inherited_y
        x, y = position

        own_clip_raw = element.get("clip-path")
        if own_clip_raw is not None:
            own_clip = _clip_id(own_clip_raw)
            if own_clip is None or own_clip not in clips:
                invalid = True
                return x, y
            clip = own_clip
        else:
            clip = inherited_clip

        semantic_text_node = tag in {"text", "tspan"}
        visible = not hidden and _inside(bounds, x, y)
        if clip is not None:
            visible = visible and _inside(clips.get(clip), x, y)

        if semantic_text_node and visible and element.text:
            chunks.append(element.text)

        cursor_x, cursor_y = x, y
        for child in element:
            child_x, child_y = walk(child, hidden, cursor_x, cursor_y, clip)
            if semantic_text_node:
                cursor_x, cursor_y = child_x, child_y
            if semantic_text_node and visible and child.tail:
                chunks.append(child.tail)

        return cursor_x, cursor_y

    walk(root, False, None, None, None)
    if invalid:
        return None
    return normalized(" ".join(chunks))


def section_body(text: str, heading: str) -> str | None:
    match = re.search(
        rf"(?ms)^{re.escape(heading)}[ \t]*\n(.*?)(?=^##[ \t]+|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def one_visual(row: dict, suffix: str) -> str | None:
    visuals = row.get("visuals")
    if not isinstance(visuals, list):
        return None
    matches = [item for item in visuals if isinstance(item, str) and item.endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def main() -> int:
    errors: list[str] = []
    checked = 0
    palette = load_json(PALETTE_PATH)
    manifests = sorted(
        MANIFEST_DIR.glob("canonical-entity-dossier-migration-v*.json"),
        key=lambda path: int(path.stem.rsplit("v", 1)[1]),
    )

    for manifest_path in manifests:
        manifest = load_json(manifest_path)
        for row in manifest.get("entities", []):
            if not isinstance(row, dict):
                errors.append(f"{manifest_path.relative_to(ROOT)}: non-object migration row")
                continue
            entity_id = row.get("id", "<missing-id>")
            dossier = row.get("dossier")
            state = row.get("state")
            state_context = row.get("stateContext")
            source_granularity = row.get("sourceGranularity")

            if not isinstance(dossier, str) or not dossier:
                errors.append(f"{manifest_path.relative_to(ROOT)}: {entity_id}: missing dossier")
                continue
            dossier_path = ROOT / dossier
            if not dossier_path.is_file():
                errors.append(f"{dossier}: dossier does not exist")
                continue
            dossier_text = dossier_path.read_text(encoding="utf-8")
            for heading in TEXTUAL_EQUIVALENT_SECTIONS:
                body = section_body(dossier_text, heading)
                if body is None:
                    errors.append(f"{dossier}: {entity_id}: missing textual-equivalent section {heading}")
                elif not body:
                    errors.append(f"{dossier}: {entity_id}: empty textual-equivalent section {heading}")

            status_rel = one_visual(row, "-status.svg")
            evidence_rel = one_visual(row, "-evidence.svg")
            if status_rel is None:
                errors.append(f"{manifest_path.relative_to(ROOT)}: {entity_id}: requires exactly one status SVG")
            if evidence_rel is None:
                errors.append(f"{manifest_path.relative_to(ROOT)}: {entity_id}: requires exactly one evidence SVG")

            if status_rel is not None:
                status_path = ROOT / status_rel
                status_text = visible_svg_text(status_path) if status_path.is_file() else None
                if status_text is None:
                    errors.append(f"{entity_id}: invalid/unverifiably-visible status SVG {status_rel}")
                elif state_context not in palette.get("states", {}):
                    errors.append(f"{entity_id}: unknown stateContext {state_context!r} for status semantics")
                else:
                    label = palette["states"][state_context].get("label")
                    expected_badge = normalized(f"{state_context} · {label}")
                    for required in (
                        "STATE DOSSIER CONTEXT",
                        expected_badge,
                        f"{state} State dossier",
                        "no entity-level governance inheritance",
                    ):
                        if required not in status_text:
                            errors.append(
                                f"{status_rel}: {entity_id}: visible status semantics missing {required!r}"
                            )
                    checked += 1

            if evidence_rel is not None:
                evidence_path = ROOT / evidence_rel
                evidence_text = visible_svg_text(evidence_path) if evidence_path.is_file() else None
                granularity_label = GRANULARITY_LABELS.get(source_granularity)
                if evidence_text is None:
                    errors.append(f"{entity_id}: invalid/unverifiably-visible evidence SVG {evidence_rel}")
                elif granularity_label is None:
                    errors.append(
                        f"{entity_id}: unsupported sourceGranularity {source_granularity!r} for evidence semantics"
                    )
                else:
                    for required in (
                        "DERIVED EVIDENCE DIAGRAM",
                        "textual equivalent is preserved in the dossier",
                        granularity_label,
                        "Identity ≠ participation / culpability",
                    ):
                        if required not in evidence_text:
                            errors.append(
                                f"{evidence_rel}: {entity_id}: visible evidence semantics missing {required!r}"
                            )
                    checked += 1

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"visual evidence semantics: FAILED ({len(errors)} error(s))")
        return 1

    print(f"visual evidence semantics: OK ({checked} status/evidence SVGs checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
