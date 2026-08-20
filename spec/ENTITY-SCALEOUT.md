# State dossier entity/project scale-out

## Purpose

ECL's canonical State dossiers contain materially relevant institutions, companies, persons, projects, systems and deployments that are not yet uniformly represented as first-class ABox identities. This scale-out closes that representation gap without converting prose association into attribution or governance.

The target property is **representational completeness**, not accusation density.

## Non-inference rules

1. A textual mention is not identity proof.
2. An identity record is not a Claim that the entity performed, controlled, operated, supplied or participated in anything.
3. `partOf`, `tracks`, `operates`, `controls`, `participatesIn`, `deploys`, supplier/customer relations and other graph edges never propagate an ECL governance outcome.
4. A company, agency, person, project or deployment may be materialized as identity-only even when its governance status is unknown or not applicable.
5. R/S/U/N remains a governance determination supported by its own record; this work never derives it from mention frequency, graph centrality, association, sanctions, source prominence, or the discovery audit's review priority.
6. Candidate extraction is discovery only. False positives are expected and must not enter `knowledge/entities/` without a stable, disambiguated referent.
7. A Project/Deployment boundary must be objectively knowable enough to distinguish the object from a policy family, entire technology class, State apparatus, vendor product line, or speculative future deployment.
8. Proposition-specific edges require proposition-specific evidence. Identity evidence is insufficient for conduct attribution.
9. Counter-institutions, remediation projects and excluded actors are eligible for neutral identity materialization on the same terms as potentially restrictive actors/projects.
10. A named victim, defendant, journalist, activist, lawyer or other case subject may be a `Person` identity without being a culpable actor or Restricted Party.

## Canonical State universe

A State dossier is canonical only when three independent values agree:

- filename `<ISO3>.md`;
- frontmatter `iso3: <ISO3>`;
- frontmatter `id: ECL-STATE-<ISO3>`.

`tools/check_state_dossier_identity_sets.py` requires exact set equality between these dossiers and `STATE-<ISO3>` ABox identities. This excludes `_TEMPLATE.md` even though its example frontmatter uses `XXX`.

## Coverage classes

The dossier discovery audit distinguishes:

- **materialized** — a dossier mention resolves by canonical name/alias to an existing ABox identity;
- **review-candidate** — a deterministic extractor found a plausible named actor/institution/project/deployment that does not resolve to an existing identity;
- **curated-identity** — a reviewed candidate with a stable, disambiguated referent that has been promoted to an identity-only ABox record;
- **deferred** — plausible referent, but the current record does not support an exact enough identity or Project/Deployment boundary;
- **rejected** — extraction noise, generic class, legal/policy phrase, geographic label, or other non-identity.

Only `materialized`/`curated-identity` correspond to represented identities. `review-candidate`, `deferred`, and `rejected` have no ontology or governance effect.

A raw `review-candidate` count is **not a count of missing entities**. It intentionally contains extraction noise, ambiguous labels, international bodies, legislation/acronyms, plural/functional classes and true domestic identity candidates. Only curation may move a candidate to `curated-identity`, `deferred` or `rejected`.

## State dossier audit contract

`tools/audit_state_dossier_entities.py` scans all canonical `dossiers/states/*.md`, compares detected names against `knowledge/entities/*.json`, and emits:

- deterministic State-scoped candidate groups;
- every dossier/line/section occurrence;
- whether a name already resolves to a canonical identity;
- a review-priority value used only to order curation work;
- State/outcome context so R/S dossiers can be reviewed first without treating the outcome as an actor/project attribution.

Unresolved names remain State-scoped. The same text in two States is not evidence that it denotes the same individual.

The audit must remain reproducible from repository contents and must not call an LLM, external NER service, search engine, or mutable external API.

## Reviewed prose-candidate overlay

The broad discovery audit intentionally stays noisy. Human-reviewed curation is therefore stored separately in `knowledge/generated/state-dossier-prose-dispositions-v*.json` and applied by `tools/review_state_dossier_candidates.py`.

Each disposition is keyed by the exact State-scoped pair `(state, normalized)` and may be only:

- **curated-identity** — the mention is bound to one or more already materialized ABox identities;
- **deferred** — the text does not yet establish a sufficiently exact legal/organizational/project boundary;
- **rejected** — the extractor produced a generic class, legislation/acronym, malformed fragment, geographic/population label or other non-individual at the current ontology granularity.

A disposition must carry a repository provenance path and a reason. `curated-identity` must resolve to existing stable IDs. The overlay never edits the raw audit, so discovery behavior remains inspectable independently from human review decisions.

The CI threshold is a **ratchet, not ontology doctrine**. Its current value is stored in `knowledge/generated/state-dossier-review-ratchet.json`; CI reads that versioned file rather than hardcoding the threshold in workflow YAML. Lowering `min_review_priority` is a monotonic curation step and is allowed only after every candidate newly brought into scope has a reviewed disposition or resolves directly to a canonical identity. Priority only orders review work; it never changes the substantive meaning of a candidate or creates governance.

Stale dispositions are rejected by CI unless a `curated-identity` became directly resolvable by the raw audit after the corresponding identity was materialized. This prevents review metadata from silently drifting away from the corpus.

## Curated Schedule-reference gate

State dossiers contain noisy prose, while `registry/schedule-state-s-freezes/` already contains a narrower set of reviewed actor/project references used in Schedule preparation. `tools/audit_schedule_reference_coverage.py` therefore provides a stronger second layer.

For every curated `candidate_parties`/`identified_party`/`identified_operators` and `candidate_projects`/`identified_projects` reference, exactly one of the following representation states must be explainable:

- **resolved** — canonical name/alias or a reviewed binding resolves the reference to one or more exact ABox identities;
- **partial-deferred** — an exact component is resolved but the source also contains unspecified/composite components that must not be invented;
- **deferred** — the source deliberately describes a plural, functional, conditional or otherwise non-enumerated class rather than one sufficiently exact identity;
- **ambiguous / unresolved** — forbidden by the CI gate.

Reviewed exceptions live in `knowledge/generated/schedule-reference-dispositions-v*.json`. A disposition is identity-resolution metadata only. A multi-identity binding does not assert `partOf`, control, participation, operation or any other relation. A deferral is not evidence against the entity and is not a governance judgment.

CI runs the Schedule audit with `--fail-on-unresolved-curated`, so adding or changing a curated actor/project reference cannot silently create new identity debt.

`scope` fields such as `schedule_identity`, `project_boundary`, identified incidents/locations and remediation text are retained as context and are not automatically coerced into ontology individuals.

## High-precision private-organization gate

The general prose audit is deliberately broad and therefore unsuitable as a company completeness gate. `tools/audit_private_org_mentions.py` is a separate high-precision pass over all 195 canonical State dossiers. It recognizes only:

- explicit corporate-form names; or
- a proper name directly tied to a supplier/vendor/private-company action involving a product, technology, software, spyware, platform, tool or service.

Unnamed phrases such as `private contractors` are not converted into invented companies. Product brands are not converted into organizations merely because they are products. International `Working Group` names are filtered rather than misclassified as companies.

CI runs this pass with `--fail-on-unresolved-private`. Therefore a newly named high-confidence private organization/vendor must either resolve to an ABox identity or make the audit fail until reviewed. The gate has no supply, participation, control or governance semantics.

A supplier can also be counter/remediation evidence. For example, an identity may be materialized precisely so that product withdrawal or remediation remains queryable without treating the supplier as a Restricted Party.

## Promotion rule

A candidate may be promoted only when the repository contains enough information to establish:

- canonical name;
- stable identity type (`Agency`, `Organization`, `Institution`, `Person`, `Project`, or `Deployment` as applicable);
- an unambiguous dossier/evidence provenance path;
- aliases needed to resolve the dossier wording;
- a review clock/reason consistent with the existing knowledge model.

Promotion does **not** require a governance outcome.

For `Project`/`Deployment`, the reviewer must additionally record why the object boundary is exact enough to be tracked independently. A historical/remediated project may remain first-class even when it is excluded from current governance scope; this preserves positive and negative evidence symmetrically.

## Relation rule

After identity promotion, relation curation is a separate pass. A relation is created only as an auditable Claim with supporting EvidenceItem(s). The existence of two identities in the same dossier, freeze or project record is never enough.

## Intended workflow

1. Prove exact State dossier/identity parity.
2. Run the deterministic full-corpus State-dossier discovery audit.
3. Apply the reviewed prose-candidate overlay and lower the versioned review ratchet in bounded tranches.
4. Run the stronger curated Schedule-reference audit and require zero ambiguous/unresolved references.
5. Run the high-precision private-organization audit and require zero unresolved high-confidence company/vendor names.
6. Review unresolved prose candidates using dossier context and existing internal registry/review records.
7. Mark each reviewed candidate `curated-identity`, `deferred`, or `rejected` rather than manufacturing certainty.
8. Materialize reviewed identity-only records in bounded tranches.
9. Add relation Claims only where proposition-specific evidence exists.
10. Re-run all audits until unexplained high-confidence State-dossier debt is eliminated.
11. Re-run Formal Exergism coverage after the actor/object universe stabilizes.

This ordering prevents Formal Exergism completeness from being measured against an artificially sparse ABox.
