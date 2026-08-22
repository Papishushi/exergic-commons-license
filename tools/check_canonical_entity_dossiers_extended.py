#!/usr/bin/env python3
"""Run canonical dossier coverage with the shared supported non-State policy."""
from markdown_it import MarkdownIt

import canonical_dossier_contract as contract
import check_canonical_entity_dossiers as checker

_RAW_IMAGE_TARGETS = checker.image_targets


def image_targets(text: str) -> list[str]:
    """Use CommonMark-rendered image destinations, preserving raw HTML/resource guards."""
    targets: list[str] = []
    for token in MarkdownIt("commonmark").parse(text):
        if token.type != "inline":
            continue
        for child in token.children or []:
            if child.type != "image":
                continue
            target = (child.attrGet("src") or "").strip()
            if target and target not in targets:
                targets.append(target)

    # Keep the legacy raw-HTML/srcset discovery surface. Markdown images already
    # discovered above are deduplicated, so escaping cannot hide them from the
    # local provenance allowlist while HTML media remains fail-closed.
    for target in _RAW_IMAGE_TARGETS(text):
        if target and target not in targets:
            targets.append(target)
    return targets


checker.TYPE_DIR = dict(contract.TYPE_DIR)
checker.ENTITY_SUFFIXES = set(contract.ENTITY_SUFFIXES)
checker.IMAGE_EXTENSIONS = set(contract.RASTER_FACSIMILE_EXTENSIONS)
checker.image_targets = image_targets

if __name__ == "__main__":
    raise SystemExit(checker.main())
