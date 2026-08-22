#!/usr/bin/env python3
"""Public round-six hardening wrapper with compatibility and adversarial guards."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

import check_canonical_entity_contract_round6_impl as _impl

_original_commonmark_validation = _impl.validate_commonmark_identity_dossiers
_original_abox_validation = _impl.validate_abox_dialect
_original_encoded_resource_validation = _impl.validate_encoded_resources


_CANONICAL_JSONLD_CONTEXT_SHA256 = "ad85086227a65f2da2cfe1e26261fbbc74cef4a3607b96063172fafbe00ffe9c"


def _sources_has_rendered_content(path: Path) -> bool:
    """Repository paths rendered as code are valid structured source entries."""
    source = path.read_text(encoding="utf-8")
    tokens = MarkdownIt("commonmark").parse(_impl._body_without_frontmatter(source))
    in_sources = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open" and token.tag == "h2" and i + 1 < len(tokens):
            heading = " ".join(tokens[i + 1].content.split())
            in_sources = heading == "Sources"
            i += 3
            continue
        if in_sources and token.type == "inline":
            for child in token.children or []:
                if child.type in {"text", "code_inline", "image"} and child.content.strip():
                    return True
        i += 1
    return False


def validate_commonmark_identity_dossiers(root: Path) -> list[str]:
    errors = _original_commonmark_validation(root)
    filtered: list[str] = []
    marker = "CommonMark section ## Sources has no positive rendered prose"
    for error in errors:
        if marker not in error:
            filtered.append(error)
            continue
        dossier_rel = error.split(":", 1)[0]
        dossier = root / dossier_rel
        if not dossier.is_file() or not _sources_has_rendered_content(dossier):
            filtered.append(error)
    return filtered


def _canonical_entity_records(root: Path) -> dict[str, tuple[Path, dict]]:
    """Load canonical entity identities keyed by their compact IRI."""
    entity_root = root / "knowledge/entities"
    records: dict[str, tuple[Path, dict]] = {}
    if not entity_root.is_dir():
        return records
    paths = sorted(set(entity_root.rglob("*.json")) | set(entity_root.rglob("*.jsonld")))
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        entity_id = value.get("id")
        iri = value.get("iri")
        if isinstance(entity_id, str) and isinstance(iri, str) and iri == f"ecl:{entity_id}":
            records.setdefault(iri, (path, value))
    return records


def validate_identity_supersession(root: Path) -> list[str]:
    """Require supersession to resolve to another identity and remain acyclic."""
    records = _canonical_entity_records(root)
    errors: list[str] = []
    edges: dict[str, str] = {}

    for iri, (path, record) in sorted(records.items()):
        target = record.get("supersededBy")
        if not isinstance(target, str):
            continue
        rel = path.relative_to(root)
        if target == iri:
            errors.append(f"{rel}: identity {iri} cannot supersede itself")
            continue
        if target not in records:
            errors.append(
                f"{rel}: supersededBy target {target!r} does not resolve to a canonical entity identity"
            )
            continue
        edges[iri] = target

    state: dict[str, int] = {}
    stack: list[str] = []
    reported_cycles: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        target = edges.get(node)
        if target in edges:
            target_state = state.get(target, 0)
            if target_state == 0:
                visit(target)
            elif target_state == 1:
                start = stack.index(target)
                cycle = stack[start:] + [target]
                core = cycle[:-1]
                rotations = [tuple(core[i:] + core[:i]) for i in range(len(core))]
                key = min(rotations) if rotations else tuple()
                if key not in reported_cycles:
                    reported_cycles.add(key)
                    errors.append("supersession cycle is forbidden: " + " -> ".join(cycle))
        stack.pop()
        state[node] = 2

    for node in sorted(edges):
        if state.get(node, 0) == 0:
            visit(node)
    return errors


def validate_canonical_context_semantics(root: Path) -> list[str]:
    """Freeze the canonical JSON-LD context as a semantic contract, not only a path."""
    path = root / "ontology/ecl-context.jsonld"
    rel = Path("ontology/ecl-context.jsonld")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{rel}: cannot load canonical JSON-LD context: {exc}"]
    if not isinstance(document, dict) or set(document) != {"@context"}:
        return [f"{rel}: canonical JSON-LD document must contain exactly one top-level @context object"]
    if not isinstance(document.get("@context"), dict):
        return [f"{rel}: canonical @context must be an object"]

    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    if digest == _CANONICAL_JSONLD_CONTEXT_SHA256:
        return []
    return [
        f"{rel}: canonical JSON-LD semantic fingerprint {digest} does not match pinned "
        f"{_CANONICAL_JSONLD_CONTEXT_SHA256}; any dialect change must update the guard and RDF equivalence tests"
    ]


def validate_abox_dialect(root: Path) -> list[str]:
    errors = validate_canonical_context_semantics(root)
    errors.extend(_original_abox_validation(root))
    errors.extend(validate_identity_supersession(root))
    return errors


def _commonmark_image_targets(source: str) -> list[str]:
    """Return image destinations exactly as CommonMark renders them."""
    tokens = MarkdownIt("commonmark").parse(_impl._body_without_frontmatter(source))
    targets: list[str] = []
    for token in tokens:
        if token.type != "inline":
            continue
        for child in token.children or []:
            if child.type == "image":
                target = (child.attrGet("src") or "").strip()
                if target:
                    targets.append(target)
    return targets


def _nonlocal_rendered_target(target: str) -> tuple[bool, str]:
    decoded = html.unescape(target.strip())
    if "\\" in decoded or decoded.startswith("//"):
        return True, decoded
    parsed = urlsplit(decoded)
    return bool(parsed.scheme or parsed.netloc), decoded


def validate_encoded_resources(root: Path) -> list[str]:
    """Preserve raw guards and additionally inspect parser-rendered image URLs."""
    errors = _original_encoded_resource_validation(root)
    seen = set(errors)
    for _version, _manifest_path, row in _impl.prior._manifest_rows(root):
        dossier_rel = row.get("dossier")
        entity_id = row.get("id", "<missing-id>")
        if not isinstance(dossier_rel, str):
            continue
        dossier = root / dossier_rel
        if not dossier.is_file():
            continue
        source = dossier.read_text(encoding="utf-8")
        for target in _commonmark_image_targets(source):
            forbidden, decoded = _nonlocal_rendered_target(target)
            if not forbidden:
                continue
            error = (
                f"{dossier_rel}: {entity_id}: non-local CommonMark image resource "
                f"{target!r} resolves to {decoded!r}"
            )
            if error not in seen:
                seen.add(error)
                errors.append(error)
    return errors


# Patch the implementation module so validate()/main() use the hardened rules.
_impl.validate_commonmark_identity_dossiers = validate_commonmark_identity_dossiers
_impl.validate_abox_dialect = validate_abox_dialect
_impl.validate_encoded_resources = validate_encoded_resources

for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

# Ensure patched public functions/helpers are not overwritten by the export loop.
globals()["validate_commonmark_identity_dossiers"] = validate_commonmark_identity_dossiers
globals()["validate_canonical_context_semantics"] = validate_canonical_context_semantics
globals()["validate_identity_supersession"] = validate_identity_supersession
globals()["validate_abox_dialect"] = validate_abox_dialect
globals()["_commonmark_image_targets"] = _commonmark_image_targets
globals()["validate_encoded_resources"] = validate_encoded_resources


if __name__ == "__main__":
    raise SystemExit(_impl.main())
