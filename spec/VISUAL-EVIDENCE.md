# Visual Evidence and Dossier Rendering

Status: normative repository curation specification.

## Purpose

ECL dossiers may contain visual material to make provenance, scope, evidence gaps and governance context easier to audit. Visuals are subordinate to the cited record: they do not create facts, Claims, relations, Material Participation, or governance outcomes.

## Evidence classes

### 1. Source facsimile

A screenshot, scan, photograph, map, chart or figure copied from an external evidentiary source.

A source facsimile may be committed only when repository storage/reuse is permitted and the asset has a sidecar metadata record containing at least `sourceUrl`, `capturedAt`, `contentSha256`, a reuse basis, supported propositions/sections and any transformation. Cropping or redaction must never change evidentiary meaning.

Canonical dossier Markdown must not embed remote resources through Markdown images/reference definitions, HTML image/media/embed/object elements, inline SVG, CSS `url(...)`/`@import`, protocol-relative URLs, `data:` URIs, or equivalent indirection. Identity-only migrated dossiers forbid raw HTML completely.

Source facsimiles under `dossiers/evidence-images/` are raster-only: PNG, JPEG or WebP. CI verifies the sidecar/hash and performs an actual Pillow decoder verification plus pixel decode; an extension or forged magic bytes are not evidence of a valid image. SVG is excluded because wrapper-byte hashing does not fix externally referenced rendered pixels.

### 2. Derived evidence diagram

A repository-generated diagram that visualizes already-curated dossier content, for example:

`source surface -> curated proposition -> entity identity -> attribution boundary`

Derived diagrams MUST say that they are derived, preserve a textual equivalent, identify source granularity, never manufacture a Claim/EvidenceItem, and never imply participation/control/supply/command/membership/culpability by adjacency.

### 3. Derived chart

A chart generated from versioned repository data. It MUST identify its data source and generation method, and visual magnitude must never be an undocumented proxy for culpability or severity.

## State-context palette and migration snapshots

The canonical palette is `../knowledge/generated/dossier-visual-palette-v1.json`. `R/S/U/N` colors are rendering vocabulary, not a culpability scale. Color MUST NOT be the sole signal; state letter and human-readable label accompany it.

For a non-State migration, manifest `stateContext` is historical provenance. The status card is a separate **live derived view**: each render reads the current referenced State dossier and displays its current `provisional_outcome` under **STATE DOSSIER CONTEXT**, together with the no-inheritance warning. A State outcome change updates the deterministic status card without rewriting the historical migration manifest.

A State outcome is never copied into a non-State dossier's `provisional_outcome`.

## Accessibility

Committed SVG evidence visuals include `<title>`, `<desc>`, meaningful Markdown alt text and a textual equivalent. Interpretation remains possible without color.

## Layout bounds and text overflow

Dynamic SVG text MUST remain inside every visual region that owns it. The renderer combines conservative deterministic wrapping with hard `clipPath` bounds.

SVG clipping is cumulative: a child clip does not replace an ancestor clip. Static validation therefore resolves sequential `x`/`y` plus `dx`/`dy` positioning and requires every text anchor to remain inside the viewBox and **every active ancestor/self clip**. A token hidden by any active clip cannot satisfy normative semantics.

`tools/check_dossier_visual_layout.py`, `tools/canonical_dossier_contract.py` and `tools/check_visual_evidence_semantics.py` independently validate layout/visibility. Static-safety validation covers every file under `dossiers/assets/generated/*.svg`, including the palette legend.

## Static SVG contract

Generated SVGs are static documents. Scripts, event handlers, SMIL/animation, `<image>`, `<use>`, external href/url resources, foreign namespaces, XML stylesheet/entity/DOCTYPE indirection, masks/filters and noncanonical clip coordinate systems fail closed.

## AI-generated and decorative imagery

AI-generated, reconstructed or decorative imagery is not evidence and MUST NOT be placed in an evidence section or stored under a path that implies evidentiary status.

## Deterministic generation

`tools/render_dossier_visuals.py` renders the canonical SVGs from versioned manifests and the palette. CI regenerates and compares byte-for-byte, validates layout again, and performs a second independent regeneration.

## Canonical dossier boundary

A State dossier may be provenance for an Agency, Institution, Organization, Person, Project or Deployment, but it is not that entity's canonical per-entity dossier. Coverage applies to `.json` and `.jsonld` entity records under `knowledge/entities/`, with the JSON-LD/identity/lifecycle rules defined in `CANONICAL-DOSSIER-MIGRATION.md`.
