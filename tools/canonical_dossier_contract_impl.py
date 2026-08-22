#!/usr/bin/env python3
"""Shared fail-closed contract helpers for canonical non-State dossiers."""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

TYPE_DIR = {
    "Agency": "agencies",
    "Institution": "institutions",
    "Organization": "organizations",
    "Person": "persons",
    "Project": "projects",
    "Deployment": "projects",
}
ENTITY_SUFFIXES = {".json", ".jsonld"}
MANIFEST_NAME_RE = re.compile(r"^canonical-entity-dossier-migration-v([1-9][0-9]*)\.json$")
MANIFEST_PREFIX = "canonical-entity-dossier-migration-v"
RASTER_FACSIMILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SVG_NS = "{http://www.w3.org/2000/svg}"

INLINE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))", flags=re.I)
REFERENCE_DEF_RE = re.compile(
    r"(?m)^[ \t]{0,3}\[([^\]]+)\]:[ \t]*(?:\n[ \t]{0,3})?(?:<([^>\n]+)>|([^\s\n]+))"
)
REFERENCE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
SHORTCUT_IMAGE_RE = re.compile(r"!\[([^\]]+)\](?!\s*[\[(])")
HTML_RESOURCE_RE = re.compile(
    r"<(?:img|source|image|embed|video|audio|iframe|track|input)\b[^>]*\b"
    r"(?:src|srcset|href|xlink:href|poster)\s*=\s*"
    r"(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
    flags=re.I | re.S,
)
HTML_OBJECT_RE = re.compile(
    r"<object\b[^>]*\bdata\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
    flags=re.I | re.S,
)
CSS_URL_RE = re.compile(
    r"url\(\s*(?:\"([^\"]+)\"|'([^']+)'|([^)\s]+))\s*\)",
    flags=re.I,
)
CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?(?:\"([^\"]+)\"|'([^']+)'|([^\s;)]+))",
    flags=re.I,
)
INLINE_SVG_RE = re.compile(r"<\s*svg\b", flags=re.I)


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def frontmatter(text: str) -> dict[str, str]:
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


def entity_paths(root: Path) -> list[Path]:
    entity_dir = root / "knowledge/entities"
    return sorted(
        path for path in entity_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in ENTITY_SUFFIXES
    )


def strict_manifest_paths(root: Path) -> tuple[list[Path], list[str]]:
    directory = root / "knowledge/generated"
    errors: list[str] = []
    accepted: list[tuple[int, Path]] = []
    if not directory.exists():
        return [], ["knowledge/generated: missing manifest directory"]
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not path.name.startswith(MANIFEST_PREFIX):
            continue
        if not path.name.endswith(".json"):
            errors.append(f"{path.relative_to(root)}: canonical migration manifest must end in .json")
            continue
        match = MANIFEST_NAME_RE.fullmatch(path.name)
        if match is None:
            errors.append(
                f"{path.relative_to(root)}: invalid canonical migration manifest filename; "
                "expected canonical-entity-dossier-migration-v<N>.json with N >= 1"
            )
            continue
        accepted.append((int(match.group(1)), path))
    accepted.sort(key=lambda item: item[0])
    return [path for _, path in accepted], errors


def resolve_repo_ref(root: Path, owner_file: Path, ref: object) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    absolute = (owner_file.parent / ref).resolve()
    try:
        return absolute.relative_to(root.resolve())
    except ValueError:
        return None


def canonical_visuals(entity_id: str) -> tuple[str, str]:
    base = "dossiers/assets/generated"
    return (f"{base}/{entity_id}-status.svg", f"{base}/{entity_id}-evidence.svg")


def _schema_non_state_types(root: Path) -> set[str] | None:
    path = root / "schemas/entity.schema.json"
    try:
        schema = load_json(path)
        enum = schema["properties"]["type"]["enum"]
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(enum, list) or not all(isinstance(item, str) for item in enum):
        return None
    return set(enum) - {"State"}


def validate_schema_type_alignment(root: Path) -> list[str]:
    schema_types = _schema_non_state_types(root)
    if schema_types is None:
        return ["schemas/entity.schema.json: cannot resolve the canonical entity type enum"]
    contract_types = set(TYPE_DIR)
    if schema_types == contract_types:
        return []
    return [
        "canonical non-State type universe is out of sync with entity.schema.json: "
        f"schema-only={sorted(schema_types - contract_types)}, contract-only={sorted(contract_types - schema_types)}"
    ]


def _definition_targets(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in REFERENCE_DEF_RE.finditer(text):
        label = " ".join(match.group(1).split()).casefold()
        target = match.group(2) or match.group(3) or ""
        if label:
            result[label] = target
    return result


def embedded_resource_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in INLINE_IMAGE_RE.finditer(text):
        targets.append(match.group(1) or match.group(2) or "")
    definitions = _definition_targets(text)
    for match in REFERENCE_IMAGE_RE.finditer(text):
        alt, label = match.groups()
        key = " ".join((label or alt).split()).casefold()
        if key in definitions:
            targets.append(definitions[key])
    for match in SHORTCUT_IMAGE_RE.finditer(text):
        key = " ".join(match.group(1).split()).casefold()
        if key in definitions:
            targets.append(definitions[key])
    for regex in (HTML_RESOURCE_RE, HTML_OBJECT_RE, CSS_URL_RE, CSS_IMPORT_RE):
        for match in regex.finditer(text):
            raw = next((group for group in match.groups() if group is not None), "")
            if regex is HTML_RESOURCE_RE and "," in raw:
                for candidate in raw.split(","):
                    candidate = candidate.strip()
                    if candidate:
                        targets.append(candidate.split()[0])
            else:
                targets.append(raw.strip())
    return targets


def nonlocal_resource_target(target: str) -> bool:
    target = target.strip()
    if target.startswith("//"):
        return True
    parsed = urlsplit(target)
    return bool(parsed.scheme or parsed.netloc)


def validate_dossier_embedded_resources(text: str, dossier_rel: Path) -> list[str]:
    errors: list[str] = []
    if INLINE_SVG_RE.search(text):
        errors.append(
            f"{dossier_rel}: inline <svg> is forbidden in canonical dossier Markdown; "
            "reference a deterministic generated SVG or provenance-controlled raster facsimile"
        )
    for target in embedded_resource_targets(text):
        if nonlocal_resource_target(target):
            errors.append(
                f"{dossier_rel}: non-local embedded resource {target!r} is forbidden; "
                "curate a provenance-safe local asset instead"
            )
    return errors


def validate_universe(root: Path) -> list[str]:
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for path in entity_paths(root):
        try:
            record = load_json(path)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            continue
        entity_id = record.get("id")
        entity_type = record.get("type")
        if not isinstance(entity_id, str) or not entity_id:
            errors.append(f"{path.relative_to(root)}: entity id is required")
            continue
        if entity_id in seen:
            errors.append(
                f"duplicate canonical entity id {entity_id}: "
                f"{seen[entity_id].relative_to(root)} and {path.relative_to(root)}"
            )
            continue
        seen[entity_id] = path
        if record.get("iri") != f"ecl:{entity_id}":
            errors.append(
                f"{path.relative_to(root)}: canonical entity iri {record.get('iri')!r} must equal 'ecl:{entity_id}'"
            )
        if entity_type not in TYPE_DIR:
            continue
        rel = resolve_repo_ref(root, path, record.get("dossier"))
        expected_dir = TYPE_DIR[entity_type]
        if rel is None or len(rel.parts) < 3 or rel.parts[:2] != ("dossiers", expected_dir) or rel.suffix != ".md":
            errors.append(f"{entity_id}: dossier must resolve under dossiers/{expected_dir}/ as Markdown")
            continue
        dossier = root / rel
        if not dossier.is_file():
            errors.append(f"{entity_id}: dedicated dossier does not exist: {rel.as_posix()}")
            continue
        text = dossier.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm.get("id") != f"ECL-{entity_id}":
            errors.append(f"{entity_id}: dossier {rel.as_posix()} frontmatter id {fm.get('id')!r} != {f'ECL-{entity_id}'!r}")
        name = record.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{entity_id}: ABox name is required")
        elif fm.get("entity") != name:
            errors.append(f"{entity_id}: dossier {rel.as_posix()} frontmatter entity {fm.get('entity')!r} != ABox name {name!r}")
        expected_type = str(entity_type).lower()
        if fm.get("entity_type") != expected_type:
            errors.append(f"{entity_id}: dossier {rel.as_posix()} frontmatter entity_type {fm.get('entity_type')!r} != {expected_type!r}")
        errors.extend(validate_dossier_embedded_resources(text, rel))
    return errors


def validate_manifest_visual_paths(root: Path) -> list[str]:
    errors: list[str] = []
    paths, naming_errors = strict_manifest_paths(root)
    errors.extend(naming_errors)
    for manifest_path in paths:
        try:
            manifest = load_json(manifest_path)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            continue
        for row in manifest.get("entities", []):
            if not isinstance(row, dict):
                continue
            entity_id = row.get("id")
            visuals = row.get("visuals")
            if not isinstance(entity_id, str) or not entity_id:
                continue
            expected = list(canonical_visuals(entity_id))
            if visuals != expected:
                errors.append(f"{manifest_path.relative_to(root)}: {entity_id}: visuals must be exactly {expected!r}, got {visuals!r}")
    return errors


def validate_evidence_image_surface(root: Path) -> list[str]:
    errors: list[str] = []
    directory = root / "dossiers/evidence-images"
    if not directory.exists():
        return errors
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if path.name == "README.md" or path.suffix.lower() == ".json":
            continue
        if path.suffix.lower() not in RASTER_FACSIMILE_EXTENSIONS:
            errors.append(f"{rel}: unsupported source-facsimile file type; only PNG/JPEG/WebP raster assets are allowed")
            continue
        sidecar = path.with_suffix(".json")
        if not sidecar.is_file():
            errors.append(f"{rel}: missing provenance sidecar {sidecar.name}")
    return errors


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _clip_rects(svg_root: ET.Element) -> dict[str, tuple[float, float, float, float]]:
    result: dict[str, tuple[float, float, float, float]] = {}
    for clip in svg_root.findall(f".//{SVG_NS}clipPath"):
        clip_id = clip.get("id")
        rect = clip.find(f"{SVG_NS}rect")
        if not clip_id or rect is None:
            continue
        x, y, w, h = (_float(rect.get(k)) for k in ("x", "y", "width", "height"))
        if None not in (x, y, w, h) and w is not None and h is not None and w >= 0 and h >= 0:
            result[clip_id] = (x or 0.0, y or 0.0, (x or 0.0) + w, (y or 0.0) + h)
    return result


def _clip_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"url\(#([A-Za-z0-9_.:-]+)\)", value.strip())
    return match.group(1) if match else None


def _inside(rect: tuple[float, float, float, float], x: float, y: float) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _apply_svg_position(element: ET.Element, current_x: float | None, current_y: float | None) -> tuple[float | None, float | None, bool]:
    x = _float(element.get("x")) if element.get("x") is not None else current_x
    y = _float(element.get("y")) if element.get("y") is not None else current_y
    if element.get("x") is not None and x is None:
        return None, None, False
    if element.get("y") is not None and y is None:
        return None, None, False
    if element.get("dx") is not None:
        dx = _float(element.get("dx"))
        if dx is None or x is None:
            return None, None, False
        x += dx
    if element.get("dy") is not None:
        dy = _float(element.get("dy"))
        if dy is None or y is None:
            return None, None, False
        y += dy
    return x, y, True


def _text_anchor_positions(text: ET.Element) -> tuple[list[tuple[float, float]], bool]:
    positions: list[tuple[float, float]] = []
    x, y, ok = _apply_svg_position(text, None, None)
    if not ok:
        return [], False
    if x is not None and y is not None:
        positions.append((x, y))
    def walk(parent: ET.Element, cursor_x: float | None, cursor_y: float | None) -> tuple[float | None, float | None, bool]:
        for child in parent:
            if child.tag != f"{SVG_NS}tspan":
                continue
            cursor_x, cursor_y, child_ok = _apply_svg_position(child, cursor_x, cursor_y)
            if not child_ok or cursor_x is None or cursor_y is None:
                return cursor_x, cursor_y, False
            positions.append((cursor_x, cursor_y))
            cursor_x, cursor_y, child_ok = walk(child, cursor_x, cursor_y)
            if not child_ok:
                return cursor_x, cursor_y, False
        return cursor_x, cursor_y, True
    _, _, ok = walk(text, x, y)
    return positions, ok


def validate_generated_svg_clipping(root: Path) -> list[str]:
    errors: list[str] = []
    directory = root / "dossiers/assets/generated"
    if not directory.exists():
        return ["dossiers/assets/generated: missing generated visual directory"]
    for path in sorted(directory.glob("*.svg")):
        try:
            svg = ET.parse(path).getroot()
        except Exception as exc:
            errors.append(f"{path.relative_to(root)}: invalid SVG: {exc}")
            continue
        for element in svg.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag in {"foreignObject", "textPath", "use"}:
                errors.append(f"{path.relative_to(root)}: unsupported SVG indirection element <{tag}>")
            if any(name in element.attrib for name in ("mask", "filter")):
                errors.append(f"{path.relative_to(root)}: unsupported SVG visibility indirection on <{tag}>")
        clips = _clip_rects(svg)
        parent_map = {child: parent for parent in svg.iter() for child in parent}
        for text in svg.findall(f".//{SVG_NS}text"):
            active_clips: list[str] = []
            node: ET.Element | None = text
            malformed = False
            while node is not None:
                raw_clip = node.get("clip-path")
                if raw_clip is not None:
                    clip = _clip_id(raw_clip)
                    if clip is None:
                        errors.append(f"{path.relative_to(root)}: unsupported clip-path syntax {raw_clip!r}")
                        malformed = True
                        break
                    active_clips.append(clip)
                node = parent_map.get(node)
            if malformed or not active_clips:
                continue
            positions, verifiable = _text_anchor_positions(text)
            if not verifiable or not positions:
                errors.append(f"{path.relative_to(root)}: clipped text has no statically verifiable x/y/dx/dy anchor sequence")
                continue
            for clip in active_clips:
                rect = clips.get(clip)
                if rect is None:
                    errors.append(f"{path.relative_to(root)}: text references unknown/non-rectangular clipPath {clip!r}")
                    continue
                for px, py in positions:
                    if not _inside(rect, px, py):
                        errors.append(f"{path.relative_to(root)}: clipped text anchor ({px:g}, {py:g}) is outside active clipPath {clip}")
    return errors


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_schema_type_alignment(root))
    errors.extend(validate_universe(root))
    errors.extend(validate_manifest_visual_paths(root))
    errors.extend(validate_evidence_image_surface(root))
    errors.extend(validate_generated_svg_clipping(root))
    return errors
