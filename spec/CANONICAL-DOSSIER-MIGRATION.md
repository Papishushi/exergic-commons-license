# Canonical Dossier Migration Contract

Status: normative repository curation specification.

## Supported non-State universe

Canonical per-entity dossier coverage applies to `Agency`, `Institution`, `Organization`, `Person`, `Project`, and `Deployment` ABox records stored as lowercase `.json` or `.jsonld` under `knowledge/entities/`. `Deployment` uses the `dossiers/projects/` surface.

`knowledge/**` remains the broader Git-native ABox surface. Builder-loadable ABox records use one canonical compact JSON-LD dialect: `@context` MUST be a local relative reference resolving to `ontology/ecl-context.jsonld`; the compact `iri` and `type` aliases MUST be used instead of direct `@id`/`@type` or alternate context aliases. Remote, inline or alternate JSON-LD contexts are forbidden. This makes raw repository classification and RDF meaning the same fail-closed surface.

Any ABox record whose canonical `type` is an entity type from `schemas/entity.schema.json` MUST live under `knowledge/entities/`. Entity records are schema-validated recursively. Case-variant extensions such as `.JSON`/`.JSONLD` are rejected so discovery is identical to the RDF builder.

For every entity, `iri` MUST equal `ecl:<id>`. `id`, `iri`, and `type` form the immutable identity core after adoption. A name, alias, review clock or review reason may evolve without changing that stable core.

`schemas/entity.schema.json` and the canonical dossier contract MUST expose the same non-State type universe. A type added to the ABox schema without a dossier mapping is a CI error.

Every supported non-State identity must point to an existing type-appropriate dossier whose frontmatter contains:

- `id: ECL-<entity-id>`
- `entity: <exact ABox name>`
- `entity_type: <lowercase ABox type>`

## Identity lifecycle

A supported identity MUST NOT disappear or change its stable `id`/`iri`/`type` merely to reduce the dossier denominator or rewrite history. Lifecycle changes use the entity fields `identityLifecycle` (`active`, `retired`, `superseded`) and, for `superseded`, mandatory `supersededBy`.

Omission of `identityLifecycle` means active for existing records. `supersededBy` is legal only when `identityLifecycle` is `superseded`. Retirement/supersession preserves the original canonical record and its immutable identity core.

## Identity-only frontmatter and rendered Markdown

Dossiers introduced by the canonical migration ledger are identity/evidence-boundary records, not standalone governance determinations. Their frontmatter uses restricted flat `key: value` syntax with unquoted canonical keys. Duplicate keys, merge keys, nested/indented YAML and multiline YAML values fail closed.

Identity-only migrated dossiers MUST NOT carry governance shortcut keys such as `provisional_outcome`, `outcome`, `status`, `tier`, `governanceStatus`, `restrictionStatus` or `currentGovernance`.

Positive completeness requirements are evaluated against a deterministic CommonMark-compatible surface. HTML comments, fenced/indented code and single- or multi-line code spans cannot satisfy headings, textual-equivalent sections or required image references. Raw HTML is forbidden on identity-only canonical dossiers; this removes browser-specific raw-HTML parsing from the positive contract. Raw source remains scanned for forbidden embedded resources, including multiline reference definitions.

## Append-only ledger

Migration manifests are named exactly `canonical-entity-dossier-migration-v<N>.json`, where `N` is a positive decimal integer with no sign, decimal point, leading-zero alias or alternate spelling. Payloads conform to `schemas/canonical-entity-dossier-migration.schema.json`.

The historical v1-v49 prefix is immutable. Later manifests append contiguously. A new supported non-State identity added after closure must arrive atomically with its dedicated dossier and a new manifest row.

A post-v49 atomic registration is strictly **identity-only**. It may contain canonical identity, aliases/provenance, dossier mapping and review-clock metadata, but MUST NOT introduce graph relationships (`partOf`, `controls`, `participatesIn`, `operates`, `deploys`, `materiallyBenefits`, `targetsOrAffects`, `remediates`, `reviews`, tracked-object relations, or any future non-identity field). Relationship curation is a separate reviewed change after the identity exists. A new atomic identity starts active and cannot arrive already retired/superseded.

Existing identities may be migrated only from a non-dedicated pointer to a type-appropriate dedicated dossier, preserving the comparison-base source dossier and changing no ABox field except `dossier`. After adoption, base-relative preservation separately freezes the identity core `id`/`iri`/`type` while allowing ordinary review metadata to evolve.

## State-context snapshot semantics

`stateContext` is an immutable migration-time snapshot of the referenced State dossier's `provisional_outcome` when a manifest row is appended. It is provenance metadata, not a live alias for the State dossier.

A newly appended row MUST match the referenced State dossier outcome at append time. Later living-governance changes MUST NOT rewrite the historical manifest snapshot.

Status SVGs do **not** render the immutable manifest snapshot as current truth. At render time they read the current referenced State dossier and display that live `provisional_outcome` as **STATE DOSSIER CONTEXT**. A later State governance change therefore causes deterministic status-card regeneration without rewriting the historical manifest. Evidence visuals and manifest provenance remain tied to the migration snapshot.

## Canonical generated visuals

For every migration row `<ID>`, `visuals` is exactly:

- `dossiers/assets/generated/<ID>-status.svg`
- `dossiers/assets/generated/<ID>-evidence.svg`

No alternate path can satisfy the contract. Generated SVG semantics must be statically demonstrable. Text hidden by clipping, masks, filters, off-canvas positioning, unsupported indirection, or cumulative `dx`/`dy` movement cannot satisfy required tokens.

SVG clips compose by intersection. CI therefore evaluates every clip inherited from a text element and all of its ancestors; a token must lie inside **all** active clips. The static-safety guard scans every generated SVG, including `state-outcome-legend.svg`, not only files listed in manifests.

Active/dynamic or externally resolved SVG constructs are forbidden, including scripts, event handlers, animation/SMIL, hyperlinks/hrefs, external `url(...)`, XML stylesheet/entity/DOCTYPE indirection and non-`userSpaceOnUse` clip coordinates.

For v40+ rows, `visualModel` is constrained to canonical identity-only templates and cannot carry a stronger proposition than the renderer displays.

## Embedded resource boundary

Canonical dossier Markdown MUST NOT hot-link remote or embedded image/media resources. This includes Markdown images and reference definitions, HTML image/media/embed/object surfaces, inline SVG, CSS `url(...)`/`@import`, protocol-relative URLs, `data:` or other URI schemes, and equivalent HTML-entity/CSS/backslash indirection.

Identity-only dossiers additionally forbid raw HTML altogether.

## Source facsimiles

`dossiers/evidence-images/` is reserved for provenance-controlled raster source facsimiles: PNG, JPEG and WebP. Each asset requires its sibling JSON metadata sidecar and must satisfy the metadata schema, confinement/symlink rules, content SHA-256 and HTTPS-source rules.

The extension and magic bytes are not sufficient. CI opens the asset with Pillow, verifies the declared decoder format, validates dimensions/structure and forces a pixel decode. Truncated or forged containers fail closed.

SVG remains excluded because wrapper-byte hashing does not fix externally referenced rendered pixels.

## Adversarial testing

Canonical CI exercises the valid corpus and negative mutations covering at least:

- canonical local JSON-LD context, compact `iri`/`type` dialect and `id == iri` identity binding;
- entity placement, recursive schema and case-sensitive suffixes;
- immutable identity core and explicit retirement/supersession lifecycle;
- relationship-free post-v49 atomic identity registration;
- strict frontmatter and governance-key smuggling;
- comments, fences, indented code, multiline code spans, raw HTML and multiline reference definitions;
- malformed manifests and noncanonical visual paths;
- State snapshot mismatch plus live status-card derivation from the current State dossier;
- remote/embedded resource indirection;
- fully decoded raster facsimiles;
- static SVG safety for all generated SVGs;
- nested/intersecting clips and off-canvas/`dx`/`dy` semantic text;
- safe v40+ `visualModel`; and
- a complete post-v49 atomic-addition fixture covering the same workflow surface as CI.
