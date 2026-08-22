#!/usr/bin/env python3
# Fail closed when generated dossier text can paint outside its owning visual region.

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.w3.org/2000/svg}"

# clip_id -> (x, y, width, height, max_lines_per_text, expected_text_nodes)
EXPECTED = {
    "evidence": {
        "source-box-clip": (52.0, 158.0, 276.0, 70.0, 3, 1),
        "proposition-box-clip": (402.0, 158.0, 276.0, 70.0, 3, 1),
        "identity-box-clip": (752.0, 158.0, 296.0, 70.0, 3, 1),
        "source-footer-clip": (52.0, 234.0, 276.0, 30.0, 1, 1),
        "proposition-footer-clip": (402.0, 232.0, 276.0, 34.0, 2, 1),
        "identity-footer-clip": (752.0, 234.0, 296.0, 30.0, 1, 1),
        "boundary-box-clip": (172.0, 304.0, 828.0, 48.0, 2, 1),
    },
    "status": {
        "status-name-clip": (54.0, 64.0, 800.0, 66.0, 2, 1),
        "status-badge-clip": (54.0, 150.0, 300.0, 66.0, 2, 1),
        "status-context-clip": (382.0, 150.0, 524.0, 66.0, 1, 2),
        "status-footer-clip": (54.0, 258.0, 852.0, 24.0, 1, 1),
    },
}

# A clip is the final paint boundary. These smaller budgets are the readability
# boundary: body text must wrap well before the clip edge / next arrow or box.
TEXT_BUDGETS = {
    "source-box-clip": 220.0,
    "proposition-box-clip": 220.0,
    "identity-box-clip": 240.0,
}

COLUMN_GUARDS = {
    "source-column-clip": (40.0, 118.0, 300.0, 156.0),
    "proposition-column-clip": (390.0, 118.0, 300.0, 156.0),
    "identity-column-clip": (740.0, 118.0, 320.0, 156.0),
}


def number(value: str | None) -> float:
    if value is None:
        raise ValueError("missing numeric SVG attribute")
    return float(value)


def glyph_width(ch: str, font_size: float) -> float:
    if ch in " il.,'`|!:;":
        factor = 0.32
    elif ch in "mwMW@#%&":
        factor = 0.90
    elif ch.isupper():
        factor = 0.72
    elif ch.isdigit():
        factor = 0.62
    else:
        factor = 0.60
    return font_size * factor


def measured_width(text: str, font_size: float) -> float:
    return sum(glyph_width(ch, font_size) for ch in text)


def clip_map(root: ET.Element) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    for clip in root.findall(f".//{NS}clipPath"):
        clip_id = clip.get("id")
        rect = clip.find(f"{NS}rect")
        if clip_id and rect is not None:
            result[clip_id] = rect
    return result


def clipped_text(root: ET.Element, clip_id: str) -> list[ET.Element]:
    token = f"url(#{clip_id})"
    return [node for node in root.findall(f".//{NS}text") if node.get("clip-path") == token]


def clipped_groups(root: ET.Element, clip_id: str) -> list[ET.Element]:
    token = f"url(#{clip_id})"
    return [node for node in root.findall(f".//{NS}g") if node.get("clip-path") == token]


def validate_wrapped_text(path: Path, clip_id: str, texts: list[ET.Element], text_budget: float, max_lines: int) -> list[str]:
    errors: list[str] = []
    for text in texts:
        lines = text.findall(f"{NS}tspan")
        if not lines:
            errors.append(f"{path}: {clip_id} text must use wrapped tspans")
            continue
        if len(lines) > max_lines:
            errors.append(f"{path}: {clip_id} uses {len(lines)} lines > allowed {max_lines}")
        font_size = number(text.get("font-size"))
        for line in lines:
            line_text = "".join(line.itertext())
            estimate = measured_width(line_text, font_size)
            if estimate > text_budget:
                errors.append(
                    f"{path}: {clip_id} estimated line width {estimate:.1f} > safe text budget {text_budget:.1f}: {line_text!r}"
                )
    return errors


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        return [f"{path}: invalid SVG/XML: {exc}"]

    name = path.name
    if name == "state-outcome-legend.svg":
        clips = clip_map(root)
        for idx in range(5):
            clip_id = f"legend-{idx}-clip"
            rect = clips.get(clip_id)
            if rect is None:
                errors.append(f"{path}: missing {clip_id}")
                continue
            texts = clipped_text(root, clip_id)
            if len(texts) != 1:
                errors.append(f"{path}: {clip_id} must bound exactly one label text")
                continue
            errors.extend(validate_wrapped_text(path, clip_id, texts, number(rect.get("width")), 2))
        return errors

    kind = "evidence" if name.endswith("-evidence.svg") else "status" if name.endswith("-status.svg") else None
    if kind is None:
        return errors

    clips = clip_map(root)
    for clip_id, (x, y, width, height, max_lines, expected_text_nodes) in EXPECTED[kind].items():
        rect = clips.get(clip_id)
        if rect is None:
            errors.append(f"{path}: missing hard overflow guard {clip_id}")
            continue
        actual = (number(rect.get("x")), number(rect.get("y")), number(rect.get("width")), number(rect.get("height")))
        expected = (x, y, width, height)
        if actual != expected:
            errors.append(f"{path}: {clip_id} geometry {actual} != expected {expected}")
        texts = clipped_text(root, clip_id)
        if len(texts) != expected_text_nodes:
            errors.append(
                f"{path}: {clip_id} must bound {expected_text_nodes} text block(s), found {len(texts)}"
            )
            continue
        budget = TEXT_BUDGETS.get(clip_id, width)
        if budget > width:
            errors.append(f"{path}: {clip_id} safe text budget {budget} exceeds clip width {width}")
            continue
        errors.extend(validate_wrapped_text(path, clip_id, texts, budget, max_lines))

    if kind == "evidence":
        for clip_id, expected in COLUMN_GUARDS.items():
            rect = clips.get(clip_id)
            if rect is None:
                errors.append(f"{path}: missing whole-column overflow guard {clip_id}")
                continue
            actual = (number(rect.get("x")), number(rect.get("y")), number(rect.get("width")), number(rect.get("height")))
            if actual != expected:
                errors.append(f"{path}: {clip_id} geometry {actual} != expected {expected}")
            groups = clipped_groups(root, clip_id)
            if len(groups) != 1:
                errors.append(f"{path}: {clip_id} must clip exactly one whole column group")
                continue
            if len(groups[0].findall(f".//{NS}text")) < 3:
                errors.append(f"{path}: {clip_id} must contain header, body and footer text")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path, nargs="?", default=Path("dossiers/assets/generated"))
    args = parser.parse_args()

    errors: list[str] = []
    files = sorted(args.directory.glob("*.svg"))
    if not files:
        errors.append(f"{args.directory}: no SVG files found")
    for path in files:
        errors.extend(validate_file(path))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"dossier visual layout: OK ({len(files)} SVGs; conservative wrap budgets + hard column clipping)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())