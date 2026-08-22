#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

import canonical_dossier_contract as contract

ROOT = Path(__file__).resolve().parents[1]
SVG_NS = "{http://www.w3.org/2000/svg}"
ENTITY_SUFFIXES_EXACT = {".json", ".jsonld"}
IDENTITY_ONLY_FORBIDDEN_FRONTMATTER = {
    "currentGovernance", "governanceStatus", "restrictionStatus", "tier",
    "outcome", "provisional_outcome", "status",
}
REQUIRED_SECTIONS = (
    "## Identity scope", "## State governance context", "## Evidence record",
    "## Attribution and exclusions", "## Visual evidence", "## Evidence gaps",
    "## Sources", "## Governance boundary",
)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
GENERIC_ALT_TEXT = {
    "state context", "state dossier context", "evidence boundary",
    "derived evidence diagram", "image", "visual", "diagram",
}
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", flags=re.S)
INLINE_CODE_RE = re.compile(r"(`+)([^\n]*?)\1")
KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
ACTIVE_SVG_TAGS = {
    "a", "animate", "animateMotion", "animateTransform", "discard",
    "foreignObject", "image", "script", "set", "style", "textPath", "use",
}
CANONICAL_BOUNDARY = (
    "Identity and State-context adjacency do not establish participation, "
    "control, culpability or governance"
)


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _entity_schema(root: Path) -> tuple[dict, set[str]]:
    schema = _load_json(root / "schemas/entity.schema.json")
    enum = schema["properties"]["type"]["enum"]
    if not isinstance(enum, list) or not all(isinstance(item, str) for item in enum):
        raise ValueError("schemas/entity.schema.json: invalid entity type enum")
    return schema, set(enum)


def _builder_abox_paths(root: Path) -> list[Path]:
    knowledge = root / "knowledge"
    return sorted(set(knowledge.rglob("*.json")) | set(knowledge.rglob("*.jsonld")))


def _is_abox_candidate(value: object) -> bool:
    return isinstance(value, dict) and "@context" in value and ("iri" in value or "@id" in value)


def validate_abox_entity_surface(root: Path) -> list[str]:
    """Make builder discovery, entity placement and entity-schema scope agree."""
    errors: list[str] = []
    try:
        schema, entity_types = _entity_schema(root)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [str(exc)]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    knowledge = root / "knowledge"
    entity_root = root / "knowledge/entities"

    for path in sorted(knowledge.rglob("*")):
        if path.is_file() and path.suffix.lower() in ENTITY_SUFFIXES_EXACT and path.suffix not in ENTITY_SUFFIXES_EXACT:
            errors.append(
                f"{path.relative_to(root)}: JSON-LD/ABox suffix must be lowercase '.json' or '.jsonld' "
                "so discovery matches the RDF builder"
            )

    entity_paths = sorted(set(entity_root.rglob("*.json")) | set(entity_root.rglob("*.jsonld")))
    for path in entity_paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.relative_to(root)}: invalid entity JSON: {exc}")
            continue
        for violation in sorted(validator.iter_errors(value), key=lambda err: list(err.absolute_path)):
            location = ".".join(str(part) for part in violation.absolute_path) or "<root>"
            errors.append(f"{path.relative_to(root)}: entity schema violation at {location}: {violation.message}")

    for path in _builder_abox_paths(root):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _is_abox_candidate(value):
            continue
        record_type = value.get("type")
        if record_type not in entity_types:
            continue
        try:
            path.relative_to(entity_root)
        except ValueError:
            errors.append(
                f"{path.relative_to(root)}: ABox record has entity type {record_type!r} but is outside "
                "knowledge/entities; entity identities must live on the schema-governed entity surface"
            )
    return errors


def strict_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse the deliberately restricted flat frontmatter used by identity-only dossiers."""
    if not text.startswith("---\n"):
        return {}, ["missing opening frontmatter delimiter"]
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, ["missing closing frontmatter delimiter"]
    data: dict[str, str] = {}
    errors: list[str] = []
    for lineno, line in enumerate(text[4:end].splitlines(), start=2):
        if not line.strip():
            continue
        if line[:1].isspace():
            errors.append(f"frontmatter line {lineno}: nested/indented YAML is forbidden on identity-only dossiers")
            continue
        if ":" not in line:
            errors.append(f"frontmatter line {lineno}: expected flat key: value syntax")
            continue
        raw_key, raw_value = line.split(":", 1)
        key = raw_key.strip()
        if KEY_RE.fullmatch(key) is None:
            errors.append(f"frontmatter line {lineno}: key {key!r} is not an unquoted canonical key")
            continue
        if key in data:
            errors.append(f"frontmatter line {lineno}: duplicate key {key!r}")
            continue
        value = raw_value.strip()
        if value.startswith((">", "|")):
            errors.append(f"frontmatter line {lineno}: multiline YAML scalars are forbidden on identity-only dossiers")
            continue
        data[key] = value.strip('"').strip("'")
    return data, errors


def renderable_markdown(text: str) -> str:
    """Return the Markdown surface eligible to satisfy positive dossier requirements."""
    text = HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    output: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in text.splitlines(keepends=True):
        match = FENCE_RE.match(line)
        if fence_char is None and match:
            token = match.group(1)
            fence_char, fence_len = token[0], len(token)
            output.append("\n" if line.endswith("\n") else "")
            continue
        if fence_char is not None:
            stripped = line.lstrip()
            if stripped.startswith(fence_char * fence_len):
                token = stripped.split(maxsplit=1)[0]
                if token and set(token) == {fence_char} and len(token) >= fence_len:
                    fence_char = None
                    fence_len = 0
            output.append("\n" if line.endswith("\n") else "")
            continue
        if line.startswith("    ") or line.startswith("\t"):
            output.append("\n" if line.endswith("\n") else "")
            continue
        output.append(line)
    return INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), "".join(output))


def _section_body(text: str, heading: str) -> str | None:
    match = re.search(rf"(?ms)^{re.escape(heading)}[ \t]*\n(.*?)(?=^##[ \t]+|\Z)", text)
    return match.group(1).strip() if match else None


def _expected_relative_visual(dossier: str, visual: str) -> str:
    return posixpath.relpath(visual, posixpath.dirname(dossier))


def _meaningful_alt_error(alt: str, visual: str) -> str | None:
    normalized = " ".join(alt.casefold().split())
    if not normalized:
        return "empty alt text"
    if normalized in GENERIC_ALT_TEXT:
        return f"generic alt text {alt!r}"
    if len(normalized) < 12:
        return f"alt text is too terse to be meaningful: {alt!r}"
    if visual.endswith("-status.svg") and ("state" not in normalized or "context" not in normalized):
        return f"status alt text must identify State context: {alt!r}"
    if visual.endswith("-evidence.svg") and ("evidence" not in normalized or "diagram" not in normalized):
        return f"evidence alt text must identify the evidence diagram: {alt!r}"
    return None


def _manifest_rows(root: Path) -> list[tuple[int, Path, dict]]:
    paths, _ = contract.strict_manifest_paths(root)
    result: list[tuple[int, Path, dict]] = []
    for path in paths:
        match = contract.MANIFEST_NAME_RE.fullmatch(path.name)
        if match is None:
            continue
        manifest = _load_json(path)
        for row in manifest.get("entities", []):
            if isinstance(row, dict):
                result.append((int(match.group(1)), path, row))
    return result


def validate_identity_only_dossiers(root: Path) -> list[str]:
    errors: list[str] = []
    for _version, _manifest_path, row in _manifest_rows(root):
        dossier_rel = row.get("dossier")
        entity_id = row.get("id", "<missing-id>")
        if not isinstance(dossier_rel, str):
            continue
        dossier = root / dossier_rel
        if not dossier.is_file():
            continue
        text = dossier.read_text(encoding="utf-8")
        fm, fm_errors = strict_frontmatter(text)
        errors.extend(f"{dossier_rel}: {entity_id}: {problem}" for problem in fm_errors)
        for key in sorted(IDENTITY_ONLY_FORBIDDEN_FRONTMATTER & set(fm)):
            errors.append(f"{dossier_rel}: {entity_id}: identity-only migrated dossier must not carry governance frontmatter key {key!r}")

        visible = renderable_markdown(text)
        for heading in REQUIRED_SECTIONS:
            body = _section_body(visible, heading)
            if body is None:
                errors.append(f"{dossier_rel}: {entity_id}: rendered Markdown is missing required section {heading}")
            elif not body:
                errors.append(f"{dossier_rel}: {entity_id}: rendered Markdown has empty required section {heading}")

        images = [(alt.strip(), target.strip()) for alt, target in IMAGE_RE.findall(visible)]
        visuals = row.get("visuals")
        if not isinstance(visuals, list):
            continue
        for visual in visuals:
            if not isinstance(visual, str):
                continue
            expected = _expected_relative_visual(dossier_rel, visual)
            matches = [(alt, target) for alt, target in images if target == expected]
            if len(matches) != 1:
                errors.append(f"{dossier_rel}: {entity_id}: rendered Markdown must contain exactly one image reference for {expected!r}; found {len(matches)}")
                continue
            problem = _meaningful_alt_error(matches[0][0], visual)
            if problem:
                errors.append(f"{dossier_rel}: {entity_id}: {problem}")
    return errors


def validate_encoded_resource_indirection(root: Path) -> list[str]:
    errors: list[str] = []
    for _version, _manifest_path, row in _manifest_rows(root):
        dossier_rel = row.get("dossier")
        entity_id = row.get("id", "<missing-id>")
        if not isinstance(dossier_rel, str):
            continue
        dossier = root / dossier_rel
        if not dossier.is_file():
            continue
        for target in contract.embedded_resource_targets(dossier.read_text(encoding="utf-8")):
            decoded = html.unescape(target.strip())
            if "\\" in decoded:
                errors.append(f"{dossier_rel}: {entity_id}: escaped/backslash resource target {target!r} is forbidden because browser/CSS resolution is not statically auditable")
                continue
            if decoded.startswith("//"):
                errors.append(f"{dossier_rel}: {entity_id}: protocol-relative embedded resource {target!r} is forbidden")
                continue
            parsed = urlsplit(decoded)
            if parsed.scheme or parsed.netloc:
                errors.append(f"{dossier_rel}: {entity_id}: encoded/non-local embedded resource {target!r} resolves to {decoded!r}")
    return errors


def validate_static_svg_surface(root: Path) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for _version, _manifest_path, row in _manifest_rows(root):
        visuals = row.get("visuals")
        if not isinstance(visuals, list):
            continue
        for visual in visuals:
            if not isinstance(visual, str) or visual in seen:
                continue
            seen.add(visual)
            path = root / visual
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8")
            lowered = raw.lower()
            for marker in ("<!doctype", "<!entity", "<?xml-stylesheet"):
                if marker in lowered:
                    errors.append(f"{visual}: active/external XML construct {marker!r} is forbidden")
            try:
                svg = ET.fromstring(raw)
            except ET.ParseError:
                continue
            for element in svg.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                namespace = element.tag[: element.tag.rfind("}") + 1] if "}" in element.tag else ""
                if namespace not in {"", SVG_NS}:
                    errors.append(f"{visual}: foreign XML namespace element {element.tag!r} is forbidden")
                if tag in ACTIVE_SVG_TAGS:
                    errors.append(f"{visual}: active/indirect SVG element <{tag}> is forbidden")
                if tag == "clipPath":
                    units = element.get("clipPathUnits")
                    if units not in {None, "userSpaceOnUse"}:
                        errors.append(f"{visual}: clipPathUnits must be userSpaceOnUse/absent, got {units!r}")
                for raw_name, value in element.attrib.items():
                    name = raw_name.rsplit("}", 1)[-1].lower()
                    if name.startswith("on"):
                        errors.append(f"{visual}: SVG event-handler attribute {name!r} is forbidden")
                    if name == "href":
                        errors.append(f"{visual}: SVG href/xlink:href indirection is forbidden")
                    if "url(" in value.lower():
                        allowed_clip = name == "clip-path" and re.fullmatch(r"url\(#[-A-Za-z0-9_.:]+\)", value.strip())
                        if not allowed_clip:
                            errors.append(f"{visual}: external/indirect SVG url() reference in {name!r} is forbidden")
    return errors


def _valid_raster_bytes(path: Path) -> bool:
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".png":
        return len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR"
    if suffix in {".jpg", ".jpeg"}:
        return len(data) >= 4 and data[:3] == b"\xff\xd8\xff" and b"\xff\xd9" in data[-32:]
    if suffix == ".webp":
        return len(data) >= 16 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def validate_raster_bytes(root: Path) -> list[str]:
    errors: list[str] = []
    directory = root / "dossiers/evidence-images"
    if not directory.exists():
        return errors
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in contract.RASTER_FACSIMILE_EXTENSIONS and not _valid_raster_bytes(path):
            errors.append(f"{path.relative_to(root)}: file extension declares a raster facsimile but the bytes do not match the declared PNG/JPEG/WebP format")
    return errors


def validate_safe_visual_models(root: Path) -> list[str]:
    errors: list[str] = []
    for version, manifest_path, row in _manifest_rows(root):
        if version < 40:
            continue
        entity_id = row.get("id", "<missing-id>")
        historical_template = {
            "source": f"{row.get('state')} State dossier + existing ABox identity/review record",
            "proposition": f"Dedicated dossier migration preserves {row.get('name')} as an identity-only non-State record",
            "boundary": CANONICAL_BOUNDARY,
        }
        atomic_template = {
            "source": f"{row.get('state')} State dossier + ABox identity",
            "proposition": f"Atomic identity-only {row.get('type')} dossier",
            "boundary": "No governance inheritance",
        }
        if row.get("visualModel") not in (historical_template, atomic_template):
            errors.append(f"{manifest_path.relative_to(root)}: {entity_id}: v40+ visualModel must equal a canonical identity-only migration/atomic-addition template")
    return errors


def validate_hardening(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_abox_entity_surface(root))
    errors.extend(validate_identity_only_dossiers(root))
    errors.extend(validate_encoded_resource_indirection(root))
    errors.extend(validate_static_svg_surface(root))
    errors.extend(validate_raster_bytes(root))
    errors.extend(validate_safe_visual_models(root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abox-only", action="store_true", help="validate only the builder/entity-schema placement contract")
    args = parser.parse_args()
    errors = validate_abox_entity_surface(ROOT) if args.abox_only else contract.validate(ROOT) + validate_hardening(ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"canonical dossier contract: FAILED ({len(errors)} error(s))")
        return 1
    if args.abox_only:
        print("canonical ABox entity surface: OK (builder discovery and recursive entity schema agree)")
    else:
        print("canonical dossier contract: OK (schema/type alignment, ABox placement/schema, strict identity frontmatter, rendered-Markdown requirements, encoded-resource boundary, canonical visual paths, static SVG safety, raster facsimile bytes, safe visualModel, cumulative SVG clipping)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
