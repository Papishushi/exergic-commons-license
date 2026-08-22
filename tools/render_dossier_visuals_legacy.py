#!/usr/bin/env python3
# Render deterministic SVG visual evidence for canonical entity dossiers.

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_DIR = ROOT / "knowledge/generated"
DEFAULT_PALETTE = ROOT / "knowledge/generated/dossier-visual-palette-v1.json"
DEFAULT_OUT = ROOT / "dossiers/assets/generated"

# Deliberately smaller than the physical clip rectangles. These are layout
# budgets, not clip widths: wrapped text must leave a substantial gutter before
# arrows / neighbouring columns even when browser font metrics differ.
EVIDENCE_TEXT_BUDGETS = {
    "source": 220,
    "proposition": 220,
    "identity": 240,
}


def esc(value: str) -> str:
    return html.escape(str(value), quote=True)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_entities(manifest_dir: Path) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    manifests = sorted(
        manifest_dir.glob("canonical-entity-dossier-migration-v*.json"),
        key=lambda p: int(p.stem.rsplit("v", 1)[1]),
    )
    if not manifests:
        raise SystemExit("no canonical entity dossier migration manifests found")
    for path in manifests:
        manifest = load_json(path)
        for row in manifest["entities"]:
            entity_id = row["id"]
            if entity_id in seen:
                raise SystemExit(f"duplicate migrated entity across manifests: {entity_id}")
            seen.add(entity_id)
            rows.append(row)
    return rows


def glyph_width(ch: str, font_size: int) -> float:
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


def measured_width(text: str, font_size: int) -> float:
    return sum(glyph_width(ch, font_size) for ch in text)


def _split_token(token: str, max_width: int, font_size: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for ch in token:
        if current and measured_width(current + ch, font_size) > max_width:
            chunks.append(current)
            current = ch
        else:
            current += ch
    if current:
        chunks.append(current)
    return chunks


def wrap_lines(text: str, max_width: int, font_size: int, max_lines: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    index = 0
    while index < len(words) and len(lines) < max_lines:
        word = words[index]
        candidate = word if not current else f"{current} {word}"
        if measured_width(candidate, font_size) <= max_width:
            current = candidate
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
            continue
        chunks = _split_token(word, max_width, font_size)
        for chunk in chunks:
            if len(lines) == max_lines:
                break
            lines.append(chunk)
        index += 1
    if current and len(lines) < max_lines:
        lines.append(current)
    complete = " ".join(words)
    rendered = " ".join(lines)
    if rendered != complete and lines:
        ellipsis = "…"
        last = lines[-1]
        while last and measured_width(last + ellipsis, font_size) > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + ellipsis
    return lines


def text_block(text: str, *, x: int, y: int, max_width: int, font_size: int,
               max_lines: int, line_height: int, clip_id: str,
               weight: str = "700", fill: str = "#101828") -> str:
    lines = wrap_lines(text, max_width, font_size, max_lines)
    tspans: list[str] = []
    for idx, line in enumerate(lines):
        attrs = f'x="{x}" y="{y}"' if idx == 0 else f'x="{x}" dy="{line_height}"'
        tspans.append(f'    <tspan {attrs}>{esc(line)}</tspan>')
    return (
        f'  <text font-family="Arial, Helvetica, sans-serif" font-size="{font_size}" '
        f'font-weight="{weight}" fill="{fill}" clip-path="url(#{clip_id})">\n'
        + "\n".join(tspans)
        + "\n  </text>"
    )


def status_svg(entity: dict, palette: dict) -> str:
    state = entity["stateContext"]
    swatch = palette["states"][state]
    name = entity["name"]
    state_code = entity["state"]
    label = swatch["label"]
    color = swatch["hex"]

    name_block = text_block(name, x=54, y=88, max_width=780, font_size=26,
        max_lines=2, line_height=30, clip_id="status-name-clip")
    badge_block = text_block(f"{state} · {label}", x=76, y=177, max_width=250,
        font_size=18, max_lines=2, line_height=21, clip_id="status-badge-clip",
        fill="#FFFFFF")
    context_title = text_block(f"{state_code} State dossier", x=382, y=177,
        max_width=500, font_size=18, max_lines=1, line_height=20,
        clip_id="status-context-clip", fill="#344054")
    context_note = text_block("Context only — no entity-level governance inheritance",
        x=382, y=205, max_width=500, font_size=16, max_lines=1, line_height=20,
        clip_id="status-context-clip", weight="400", fill="#475467")
    footer = text_block(
        "Color is never the sole signal: the state letter and label are always rendered.",
        x=54, y=275, max_width=830, font_size=15, max_lines=1, line_height=18,
        clip_id="status-footer-clip", weight="400", fill="#667085")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="300" viewBox="0 0 960 300" role="img" aria-labelledby="title desc">
  <title id="title">{esc(name)} — State dossier context {esc(state)}</title>
  <desc id="desc">Derived status card. The {esc(state_code)} State dossier is {esc(state)} — {esc(label)}. This status is context only and is not inherited by {esc(name)}.</desc>
  <defs>
    <clipPath id="status-name-clip"><rect x="54" y="64" width="800" height="66"/></clipPath>
    <clipPath id="status-badge-clip"><rect x="54" y="150" width="300" height="66" rx="12"/></clipPath>
    <clipPath id="status-context-clip"><rect x="382" y="150" width="524" height="66"/></clipPath>
    <clipPath id="status-footer-clip"><rect x="54" y="258" width="852" height="24"/></clipPath>
  </defs>
  <rect width="960" height="300" rx="18" fill="#FFFFFF" stroke="#D0D5DD"/>
  <rect width="18" height="300" rx="9" fill="{esc(color)}"/>
  <text x="54" y="48" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#344054">STATE DOSSIER CONTEXT</text>
{name_block}
  <rect x="54" y="150" width="300" height="66" rx="12" fill="{esc(color)}"/>
{badge_block}
{context_title}
{context_note}
  <line x1="54" y1="246" x2="906" y2="246" stroke="#EAECF0"/>
{footer}
</svg>
'''


def evidence_svg(entity: dict) -> str:
    name = entity["name"]
    source = entity["visualModel"]["source"]
    proposition = entity["visualModel"]["proposition"]
    boundary = entity["visualModel"]["boundary"]
    granularity_label = ("direct locator" if entity["sourceGranularity"] == "direct"
                         else "partial locator / explicit gap")

    source_block = text_block(source, x=62, y=180,
        max_width=EVIDENCE_TEXT_BUDGETS["source"], font_size=14,
        max_lines=3, line_height=19, clip_id="source-box-clip")
    proposition_block = text_block(proposition, x=412, y=180,
        max_width=EVIDENCE_TEXT_BUDGETS["proposition"], font_size=14,
        max_lines=3, line_height=19, clip_id="proposition-box-clip")
    identity_block = text_block(name, x=762, y=180,
        max_width=EVIDENCE_TEXT_BUDGETS["identity"], font_size=14,
        max_lines=3, line_height=19, clip_id="identity-box-clip")
    source_footer = text_block(granularity_label, x=62, y=252, max_width=240,
        font_size=14, max_lines=1, line_height=16, clip_id="source-footer-clip",
        weight="400", fill="#667085")
    proposition_footer = text_block(
        "Prose evidence; no Claim/EvidenceItem invented",
        x=412, y=244, max_width=240, font_size=13, max_lines=2, line_height=16,
        clip_id="proposition-footer-clip", weight="400", fill="#667085")
    identity_footer = text_block("Identity ≠ participation / culpability",
        x=762, y=252, max_width=276, font_size=14, max_lines=1, line_height=16,
        clip_id="identity-footer-clip", weight="400", fill="#667085")
    boundary_block = text_block(
        f"{boundary} · no partOf/control/operation/participation/supplier inference",
        x=172, y=326, max_width=828, font_size=15, max_lines=2, line_height=20,
        clip_id="boundary-box-clip", weight="400", fill="#475467")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="390" viewBox="0 0 1100 390" role="img" aria-labelledby="title desc">
  <title id="title">{esc(name)} — derived evidence diagram</title>
  <desc id="desc">Derived evidence diagram linking the curated source surface to the dossier proposition and then to the entity identity, while preserving a no-governance-inheritance boundary.</desc>
  <defs>
    <clipPath id="source-column-clip"><rect x="40" y="118" width="300" height="156" rx="14"/></clipPath>
    <clipPath id="proposition-column-clip"><rect x="390" y="118" width="300" height="156" rx="14"/></clipPath>
    <clipPath id="identity-column-clip"><rect x="740" y="118" width="320" height="156" rx="14"/></clipPath>
    <clipPath id="source-box-clip"><rect x="52" y="158" width="276" height="70"/></clipPath>
    <clipPath id="proposition-box-clip"><rect x="402" y="158" width="276" height="70"/></clipPath>
    <clipPath id="identity-box-clip"><rect x="752" y="158" width="296" height="70"/></clipPath>
    <clipPath id="source-footer-clip"><rect x="52" y="234" width="276" height="30"/></clipPath>
    <clipPath id="proposition-footer-clip"><rect x="402" y="232" width="276" height="34"/></clipPath>
    <clipPath id="identity-footer-clip"><rect x="752" y="234" width="296" height="30"/></clipPath>
    <clipPath id="boundary-box-clip"><rect x="172" y="304" width="828" height="48"/></clipPath>
  </defs>
  <rect width="1100" height="390" rx="18" fill="#FFFFFF" stroke="#D0D5DD"/>
  <text x="40" y="48" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700" fill="#101828">DERIVED EVIDENCE DIAGRAM</text>
  <text x="40" y="76" font-family="Arial, Helvetica, sans-serif" font-size="15" fill="#667085">Not a source facsimile · textual equivalent is preserved in the dossier</text>

  <rect x="40" y="118" width="300" height="156" rx="14" fill="#F9FAFB" stroke="#98A2B3"/>
  <g clip-path="url(#source-column-clip)">
  <text x="62" y="148" font-family="Arial, Helvetica, sans-serif" font-size="15" font-weight="700" fill="#344054">SOURCE SURFACE</text>
{source_block}
{source_footer}
  </g>

  <line x1="340" y1="196" x2="388" y2="196" stroke="#667085" stroke-width="2"/>
  <polygon points="388,196 376,189 376,203" fill="#667085"/>

  <rect x="390" y="118" width="300" height="156" rx="14" fill="#F9FAFB" stroke="#98A2B3"/>
  <g clip-path="url(#proposition-column-clip)">
  <text x="412" y="148" font-family="Arial, Helvetica, sans-serif" font-size="15" font-weight="700" fill="#344054">CURATED PROPOSITION</text>
{proposition_block}
{proposition_footer}
  </g>

  <line x1="690" y1="196" x2="738" y2="196" stroke="#667085" stroke-width="2"/>
  <polygon points="738,196 726,189 726,203" fill="#667085"/>

  <rect x="740" y="118" width="320" height="156" rx="14" fill="#F9FAFB" stroke="#98A2B3"/>
  <g clip-path="url(#identity-column-clip)">
  <text x="762" y="148" font-family="Arial, Helvetica, sans-serif" font-size="15" font-weight="700" fill="#344054">IDENTITY BOUNDARY</text>
{identity_block}
{identity_footer}
  </g>

  <rect x="40" y="304" width="1020" height="58" rx="10" fill="#F2F4F7"/>
  <text x="60" y="326" font-family="Arial, Helvetica, sans-serif" font-size="16" font-weight="700" fill="#344054">BOUNDARY:</text>
{boundary_block}
</svg>
'''


def legend_svg(palette: dict) -> str:
    order = ["R", "S", "U", "N", "UNKNOWN"]
    x = 40
    clip_defs: list[str] = []
    blocks: list[str] = []
    for idx, key in enumerate(order):
        item = palette["states"][key]
        clip_id = f"legend-{idx}-clip"
        clip_defs.append(
            f'    <clipPath id="{clip_id}"><rect x="{x+12}" y="126" width="144" height="42"/></clipPath>'
        )
        label_block = text_block(item["label"], x=x + 18, y=146, max_width=132,
            font_size=12, max_lines=2, line_height=16, clip_id=clip_id,
            weight="400", fill="#FFFFFF")
        blocks.append(
            f'  <rect x="{x}" y="92" width="168" height="88" rx="12" fill="{esc(item["hex"])}"/>\n'
            f'  <text x="{x+18}" y="121" font-family="Arial, Helvetica, sans-serif" font-size="21" font-weight="700" fill="#FFFFFF">{esc(key)}</text>\n'
            f'{label_block}'
        )
        x += 184

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="245" viewBox="0 0 1000 245" role="img" aria-labelledby="title desc">
  <title id="title">ECL dossier state-context palette</title>
  <desc id="desc">Canonical R, S, U, N and unknown colors. Letters and labels accompany every swatch; colors are never entity culpability scores.</desc>
  <defs>
{chr(10).join(clip_defs)}
  </defs>
  <rect width="1000" height="245" rx="18" fill="#FFFFFF" stroke="#D0D5DD"/>
  <text x="40" y="47" font-family="Arial, Helvetica, sans-serif" font-size="22" font-weight="700" fill="#101828">ECL STATE-CONTEXT PALETTE</text>
  <text x="40" y="73" font-family="Arial, Helvetica, sans-serif" font-size="15" fill="#667085">Rendering vocabulary only · not a severity scale · no governance inheritance</text>
{chr(10).join(blocks)}
  <text x="40" y="222" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#667085">Always render letter + text label together with color.</text>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--palette", type=Path, default=DEFAULT_PALETTE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    rows = load_entities(args.manifest_dir)
    palette = load_json(args.palette)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "state-outcome-legend.svg").write_text(legend_svg(palette), encoding="utf-8")
    for entity in rows:
        (args.out / f'{entity["id"]}-status.svg').write_text(status_svg(entity, palette), encoding="utf-8")
        (args.out / f'{entity["id"]}-evidence.svg').write_text(evidence_svg(entity), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())