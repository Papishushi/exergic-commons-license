#!/usr/bin/env python3
# Validate canonical per-entity dossier coverage and visual-evidence invariants.

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENTITY_DIR = ROOT / "knowledge/entities"
DEFAULT_MANIFEST_DIR = ROOT / "knowledge/generated"
DEFAULT_PALETTE = ROOT / "knowledge/generated/dossier-visual-palette-v1.json"
EVIDENCE_IMAGE_DIR = ROOT / "dossiers/evidence-images"
TYPE_DIR = {"Agency":"agencies","Institution":"institutions","Organization":"organizations","Person":"persons","Project":"projects"}
EXPECTED_PALETTE = {"R":"#B42318","S":"#E67E22","U":"#D4A017","N":"#2E7D32","UNKNOWN":"#667085"}
VALID_ENTITY_STATE_CONTEXTS = {"R", "S", "U", "N"}
REQUIRED_SECTIONS = ("## Identity scope","## State governance context","## Evidence record","## Attribution and exclusions","## Visual evidence","## Evidence gaps","## Sources","## Governance boundary")
ENTITY_SUFFIXES = {".json", ".jsonld"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

INLINE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))", flags=re.I)
REFERENCE_DEF_RE = re.compile(r"(?m)^[ \t]{0,3}\[([^\]]+)\]:[ \t]*(?:<([^>\n]+)>|([^\s\n]+))")
REFERENCE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
SHORTCUT_IMAGE_RE = re.compile(r"!\[([^\]]+)\](?!\s*[\[(])")
HTML_IMAGE_RE = re.compile(
    r"<(?:img|source)\b[^>]*\b(?:src|srcset)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
    flags=re.I | re.S,
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_paths(manifest_dir: Path) -> list[Path]:
    paths = list(manifest_dir.glob("canonical-entity-dossier-migration-v*.json"))
    paths.sort(key=lambda p: int(p.stem.rsplit("v", 1)[1]))
    return paths


def entity_paths(entity_dir: Path = ENTITY_DIR) -> list[Path]:
    """Return the canonical entity-source universe accepted by the ABox builder."""
    return sorted(
        path for path in entity_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in ENTITY_SUFFIXES
    )


def repo_path_from_entity_ref(entity_file: Path, dossier_ref: str, root: Path = ROOT) -> Path:
    absolute = (entity_file.parent / dossier_ref).resolve()
    try:
        return absolute.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"dossier path escapes repository: {entity_file}: {dossier_ref}") from exc


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def is_dedicated(entity: dict, entity_file: Path, root: Path = ROOT) -> tuple[bool, Path | None]:
    expected_dir = TYPE_DIR.get(entity.get("type"))
    dossier_ref = entity.get("dossier")
    if not expected_dir or not isinstance(dossier_ref, str) or not dossier_ref:
        return False, None
    try:
        rel = repo_path_from_entity_ref(entity_file, dossier_ref, root)
    except ValueError:
        return False, None
    parts = rel.parts
    good = (
        len(parts) >= 3
        and parts[0] == "dossiers"
        and parts[1] == expected_dir
        and rel.suffix == ".md"
        and (root / rel).is_file()
    )
    return good, rel


def validate_svg(path: Path, required_text: list[str] | None = None, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        xml_root = ET.parse(path).getroot()
    except Exception as exc:
        return [f"{path.relative_to(root)}: invalid SVG/XML: {exc}"]
    ns = "{http://www.w3.org/2000/svg}"
    if xml_root.find(f"{ns}title") is None:
        errors.append(f"{path.relative_to(root)}: missing <title>")
    if xml_root.find(f"{ns}desc") is None:
        errors.append(f"{path.relative_to(root)}: missing <desc>")
    text = path.read_text(encoding="utf-8")
    for token in required_text or []:
        if token not in text:
            errors.append(f"{path.relative_to(root)}: missing required token {token!r}")
    return errors


def _definition_targets(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in REFERENCE_DEF_RE.finditer(text):
        label = " ".join(match.group(1).split()).casefold()
        target = match.group(2) or match.group(3) or ""
        if label:
            result[label] = target
    return result


def image_targets(text: str) -> list[str]:
    """Extract Markdown and raw-HTML image destinations, including references."""
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

    for match in HTML_IMAGE_RE.finditer(text):
        raw = match.group(1) or match.group(2) or match.group(3) or ""
        # srcset may contain comma-separated URL + density/width descriptors.
        for candidate in raw.split(","):
            candidate = candidate.strip()
            if candidate:
                targets.append(candidate.split()[0])
    return targets


def nonlocal_image_target(target: str) -> bool:
    target = target.strip()
    if target.startswith("//"):
        return True
    parsed = urlsplit(target)
    return bool(parsed.scheme or parsed.netloc)


def _local_image_repo_path(target: str, dossier_path: Path, root: Path) -> Path | None:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    raw_path = unquote(parsed.path).strip()
    if not raw_path or raw_path.startswith("#"):
        return None
    absolute = (dossier_path.parent / raw_path).resolve()
    try:
        return absolute.relative_to(root.resolve())
    except ValueError:
        return Path("..") / absolute.name


def validate_dossier_images(
    text: str,
    dossier_path: Path,
    allowed_visuals: set[str],
    root: Path = ROOT,
    evidence_image_dir: Path = EVIDENCE_IMAGE_DIR,
) -> list[str]:
    """Reject remote/embedded and provenance-uncontrolled dossier images."""
    errors: list[str] = []
    evidence_rel = evidence_image_dir.resolve().relative_to(root.resolve())
    for target in image_targets(text):
        if nonlocal_image_target(target):
            errors.append(
                f"{dossier_path.relative_to(root)}: non-local image reference {target!r} is forbidden; "
                "curate a provenance-safe local asset"
            )
            continue
        rel = _local_image_repo_path(target, dossier_path, root)
        if rel is None:
            continue
        rel_posix = rel.as_posix()
        if rel_posix in allowed_visuals:
            continue
        try:
            rel.relative_to(evidence_rel)
            if not (root / rel).is_file():
                errors.append(
                    f"{dossier_path.relative_to(root)}: referenced evidence image does not exist: {rel_posix!r}"
                )
            continue
        except ValueError:
            pass
        errors.append(
            f"{dossier_path.relative_to(root)}: local image {target!r} resolves to uncontrolled asset "
            f"{rel_posix!r}; use a manifest-declared generated visual or dossiers/evidence-images"
        )
    return errors


def validate_source_images(root: Path = ROOT, evidence_image_dir: Path = EVIDENCE_IMAGE_DIR) -> list[str]:
    errors: list[str] = []
    if not evidence_image_dir.exists():
        return errors
    for asset in sorted(
        p for p in evidence_image_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ):
        sidecar = asset.with_suffix(".json")
        if not sidecar.is_file():
            errors.append(f"{asset.relative_to(root)}: missing source-image metadata sidecar {sidecar.name}")
            continue
        meta = load_json(sidecar)
        required = ("version","asset","sourceUrl","capturedAt","contentSha256","licenseBasis","propositions","transformation")
        for key in required:
            if key not in meta:
                errors.append(f"{sidecar.relative_to(root)}: missing metadata field {key}")
        if meta.get("version") != 1:
            errors.append(f"{sidecar.relative_to(root)}: version must be 1")
        if meta.get("asset") != asset.name:
            errors.append(f"{sidecar.relative_to(root)}: asset must equal {asset.name!r}")
        if not str(meta.get("sourceUrl", "")).startswith("https://"):
            errors.append(f"{sidecar.relative_to(root)}: sourceUrl must be https")
        if meta.get("contentSha256") != hashlib.sha256(asset.read_bytes()).hexdigest():
            errors.append(f"{sidecar.relative_to(root)}: contentSha256 mismatch")
        propositions = meta.get("propositions")
        if not isinstance(propositions, list) or not propositions or not all(isinstance(x, str) and x.strip() for x in propositions):
            errors.append(f"{sidecar.relative_to(root)}: propositions must be a non-empty string array")
        if not str(meta.get("licenseBasis", "")).strip():
            errors.append(f"{sidecar.relative_to(root)}: licenseBasis must be non-empty")
        if not str(meta.get("transformation", "")).strip():
            errors.append(f"{sidecar.relative_to(root)}: transformation must be non-empty")
    for sidecar in sorted(evidence_image_dir.rglob("*.json")):
        meta = load_json(sidecar)
        asset_name = meta.get("asset")
        if asset_name and not (sidecar.parent / asset_name).is_file():
            errors.append(f"{sidecar.relative_to(root)}: referenced asset does not exist: {asset_name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--palette", type=Path, default=DEFAULT_PALETTE)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    errors = validate_source_images()
    palette = load_json(args.palette)
    for key, expected in EXPECTED_PALETTE.items():
        got = palette.get("states", {}).get(key, {}).get("hex")
        if got != expected:
            errors.append(f"palette {key}: expected {expected}, got {got}")
    paths = manifest_paths(args.manifest_dir)
    manifests = [load_json(path) for path in paths]
    if not paths:
        errors.append("no canonical entity dossier migration manifests found")
    ratchets: list[int] = []
    previous = None
    for path, manifest in zip(paths, manifests):
        value = int(manifest["maxMissingDedicatedDossiers"])
        ratchets.append(value)
        if previous is not None and value > previous:
            errors.append(f"{path.relative_to(ROOT)}: maxMissingDedicatedDossiers regressed {previous} -> {value}")
        previous = value
    max_missing = ratchets[-1] if ratchets else 10**9
    entities: dict[str, tuple[dict, Path]] = {}
    non_state = dedicated = 0
    missing: list[str] = []
    by_type: dict[str, dict[str, int]] = {}
    for entity_file in entity_paths():
        entity = load_json(entity_file)
        entity_id, entity_type = entity.get("id"), entity.get("type")
        if not entity_id or not entity_type:
            continue
        if entity_id in entities:
            errors.append(
                f"duplicate canonical entity id {entity_id}: "
                f"{entities[entity_id][1].relative_to(ROOT)} and {entity_file.relative_to(ROOT)}"
            )
            continue
        entities[entity_id] = (entity, entity_file)
        if entity_type == "State" or entity_type not in TYPE_DIR:
            continue
        non_state += 1
        stats = by_type.setdefault(entity_type, {"total":0,"dedicated":0,"missing":0})
        stats["total"] += 1
        good, _ = is_dedicated(entity, entity_file)
        if good:
            dedicated += 1
            stats["dedicated"] += 1
        else:
            missing.append(entity_id)
            stats["missing"] += 1
    if len(missing) > max_missing:
        errors.append(f"dedicated-dossier ratchet regressed: {len(missing)} missing > allowed {max_missing}")
    migrated_ids: set[str] = set()
    for path, manifest in zip(paths, manifests):
        rows = manifest.get("entities")
        if not isinstance(rows, list):
            errors.append(f"{path.relative_to(ROOT)}: entities payload must be a list")
            continue
        for row in rows:
            entity_id = row["id"]
            if entity_id in migrated_ids:
                errors.append(f"{path.relative_to(ROOT)}: duplicate migrated entity across manifests: {entity_id}")
                continue
            migrated_ids.add(entity_id)
            if entity_id not in entities:
                errors.append(f"{path.relative_to(ROOT)}: manifest entity missing: {entity_id}")
                continue
            entity, entity_file = entities[entity_id]
            if entity.get("type") != row["type"]:
                errors.append(f"{entity_id}: type mismatch")
            if entity.get("name") != row["name"]:
                errors.append(f"{entity_id}: name mismatch")
            good, rel = is_dedicated(entity, entity_file)
            expected_rel = Path(row["dossier"])
            if not good:
                errors.append(f"{entity_id}: does not point to an existing dedicated dossier")
                continue
            if rel != expected_rel:
                errors.append(f"{entity_id}: dossier path {rel} != manifest {expected_rel}")
            dossier_path = ROOT / expected_rel
            text = dossier_path.read_text(encoding="utf-8")
            fm = frontmatter(text)
            if fm.get("id") != f"ECL-{entity_id}": errors.append(f"{expected_rel}: frontmatter id mismatch")
            if fm.get("entity") != row["name"]: errors.append(f"{expected_rel}: frontmatter entity mismatch")
            if fm.get("entity_type") != row["type"].lower(): errors.append(f"{expected_rel}: frontmatter entity_type mismatch")
            if "provisional_outcome" in fm: errors.append(f"{expected_rel}: non-State canonical dossier must not inherit provisional_outcome")
            for section in REQUIRED_SECTIONS:
                if section not in text: errors.append(f"{expected_rel}: missing section {section}")

            visuals = row.get("visuals", [])
            allowed_visuals = {item for item in visuals if isinstance(item, str)}
            errors.extend(validate_dossier_images(text, dossier_path, allowed_visuals))
            if len(visuals) < 2:
                errors.append(f"{entity_id}: requires at least status + evidence visuals")
            state = row.get("stateContext")
            if state not in VALID_ENTITY_STATE_CONTEXTS:
                errors.append(f"{entity_id}: invalid stateContext {state!r}")
                continue
            color = EXPECTED_PALETTE[state]
            for rel_visual in visuals:
                visual_path = ROOT / rel_visual
                if not visual_path.is_file():
                    errors.append(f"{entity_id}: missing visual {rel_visual}")
                    continue
                required = []
                if rel_visual.endswith("-status.svg"): required += [color, f">{state} ·", "no entity-level governance inheritance"]
                if rel_visual.endswith("-evidence.svg"): required += ["DERIVED EVIDENCE DIAGRAM", "Identity ≠ participation / culpability"]
                errors.extend(validate_svg(visual_path, required))
    report = {"nonStateEntities":non_state,"dedicatedDossiers":dedicated,"missingDedicatedDossiers":len(missing),"maxMissingDedicatedDossiers":max_missing,"migratedAcrossManifests":len(migrated_ids),"byType":by_type,"errors":errors}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
