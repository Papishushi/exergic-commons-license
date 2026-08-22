#!/usr/bin/env python3
"""Public canonical dossier contract with backward-compatible clipping diagnostics."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

import canonical_dossier_contract_impl as _impl

for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

_original_validate_generated_svg_clipping = _impl.validate_generated_svg_clipping
_original_embedded_resource_targets = _impl.embedded_resource_targets
_original_validate_universe = _impl.validate_universe


def commonmark_image_targets(text: str) -> list[str]:
    """Return every image destination that CommonMark actually renders."""
    targets: list[str] = []
    for token in MarkdownIt("commonmark").parse(text):
        if token.type != "inline":
            continue
        for child in token.children or []:
            if child.type != "image":
                continue
            target = (child.attrGet("src") or "").strip()
            if target:
                targets.append(target)
    return targets


def embedded_resource_targets(text: str) -> list[str]:
    """Union legacy raw-syntax discovery with rendered CommonMark image destinations."""
    targets = list(_original_embedded_resource_targets(text))
    targets.extend(commonmark_image_targets(text))
    return list(dict.fromkeys(targets))


# Functions defined in the implementation module resolve this global at call time.
# Patch the implementation namespace as well as the public wrapper so every caller,
# including validate_universe(), receives the rendered CommonMark surface.
_impl.embedded_resource_targets = embedded_resource_targets


def _local_resource_repo_path(root: Path, dossier_rel: Path, target: str) -> tuple[Path | None, bool]:
    """Resolve a local embedded resource and report repository escape attempts."""
    parsed = urlsplit(target.strip())
    if parsed.scheme or parsed.netloc:
        return None, False
    raw_path = unquote(parsed.path).strip()
    if not raw_path:
        return None, False
    absolute = ((root / dossier_rel).parent / raw_path).resolve()
    try:
        return absolute.relative_to(root.resolve()), False
    except ValueError:
        return None, True


def validate_dossier_local_resources(
    text: str,
    dossier_rel: Path,
    entity_id: str,
    root: Path,
) -> list[str]:
    """Require every local embedded resource to use a canonical provenance surface."""
    errors: list[str] = []
    allowed_generated = set(_impl.canonical_visuals(entity_id))
    evidence_rel = Path("dossiers/evidence-images")

    for target in embedded_resource_targets(text):
        if _impl.nonlocal_resource_target(target):
            continue
        rel, escaped = _local_resource_repo_path(root, dossier_rel, target)
        if escaped:
            errors.append(
                f"{dossier_rel}: local embedded resource {target!r} escapes the repository; "
                "use a canonical generated visual or provenance-controlled raster facsimile"
            )
            continue
        if rel is None:
            continue

        rel_posix = rel.as_posix()
        if rel_posix in allowed_generated:
            if not (root / rel).is_file():
                errors.append(
                    f"{dossier_rel}: referenced canonical generated visual does not exist: {rel_posix!r}"
                )
            continue

        try:
            rel.relative_to(evidence_rel)
        except ValueError:
            errors.append(
                f"{dossier_rel}: local embedded resource {target!r} resolves to uncontrolled asset "
                f"{rel_posix!r}; use a canonical generated visual or dossiers/evidence-images"
            )
            continue

        if not (root / rel).is_file():
            errors.append(
                f"{dossier_rel}: referenced evidence image does not exist: {rel_posix!r}"
            )

    return errors


def validate_universe(root: Path) -> list[str]:
    """Validate canonical identity bindings plus local/remote resource provenance for every dossier."""
    errors = list(_original_validate_universe(root))
    for path in _impl.entity_paths(root):
        try:
            record = _impl.load_json(path)
        except (OSError, ValueError):
            continue
        entity_id = record.get("id")
        entity_type = record.get("type")
        if not isinstance(entity_id, str) or not entity_id or entity_type not in _impl.TYPE_DIR:
            continue
        rel = _impl.resolve_repo_ref(root, path, record.get("dossier"))
        expected_dir = _impl.TYPE_DIR[entity_type]
        if rel is None or len(rel.parts) < 3 or rel.parts[:2] != ("dossiers", expected_dir) or rel.suffix != ".md":
            continue
        dossier = root / rel
        if not dossier.is_file():
            continue
        try:
            text = dossier.read_text(encoding="utf-8")
        except OSError:
            continue
        errors.extend(validate_dossier_local_resources(text, rel, entity_id, root))
    return errors


# The implementation's top-level validate() resolves validate_universe dynamically.
_impl.validate_universe = validate_universe


def validate_generated_svg_clipping(root):
    return [
        error.replace(
            "outside active clipPath",
            "outside clipPath; outside active clipPath",
        )
        for error in _original_validate_generated_svg_clipping(root)
    ]
