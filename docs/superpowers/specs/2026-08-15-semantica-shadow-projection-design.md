# Semantica Shadow Projection V1 — Design

Status: APPROVED DESIGN / NOT IMPLEMENTED  
Decision: D1:A  
Baseline: upstream `semantica-agi/semantica@5579851208ae5adbc813c787be8c8581d8bd2aed`  
Target: deterministic, read-first semantic/provenance projection proof

## Objective

Prove that Semantica can add semantic graph, provenance, temporal context, decision intelligence, and deterministic reasoning without becoming an uncontrolled competing source of truth.

The V1 proof must ingest a fixed evidence corpus, assign deterministic canonical identities, preserve source provenance, project assertions into Semantica, survive restart, validate graph structure, and produce identical canonical results on replay.

## Non-goals

V1 does not:

- make Semantica the sole authoritative datastore;
- expose unrestricted native MCP writes;
- auto-promote inferred or agent-generated facts to canonical truth;
- certify every graph/vector backend;
- implement production multi-store erasure;
- deploy Explorer publicly;
- follow Semantica `main` automatically.

## Architectural rule

Semantica is a semantic/provenance projection and reasoning substrate. Authority remains explicit and external to the projection until a separate promotion policy authorizes canonicalization.

```text
Authoritative sources
        |
        v
Canonical identity + source envelope
        |
        v
Normalize -> Deduplicate -> Detect conflicts
        |
        v
Semantica projection
  - provenance
  - temporal assertions
  - decisions
  - causal relationships
  - semantic relationships
        |
        v
Validation gate
        |
   +----+----+
   |         |
 invalid    valid
   |         |
quarantine  v
       durable projection
             |
             v
     read/reason/explain
```

## Semantic model

The projection keeps the following concepts distinct:

- **Observation** — something measured, inspected, or retrieved.
- **Assertion** — a source states a predicate/value about a subject.
- **Inference** — a deterministic reasoning result derived from assertions.
- **Decision** — an actor or system chose an outcome for stated reasons.
- **CanonicalFact** — an accepted current project truth created only by an explicit promotion rule.

A Decision is evidence that a decision occurred; it is not itself authorization to mutate an external system or promote a CanonicalFact.

## Canonical identity

Identity is assigned before Semantica ingestion. Labels, free text, embeddings, and entity extraction may help correlate records but cannot create canonical identity by themselves.

Canonical resources use stable HTTPS identifiers when practical:

```text
https://id.example.invalid/project/<id>
https://id.example.invalid/resource/<id>
https://id.example.invalid/decision/<id>
https://id.example.invalid/evidence/sha256/<digest>
```

The example host is intentionally non-routable for V1 tests. A production namespace is a later deployment decision.

Every projected record carries at minimum:

```text
canonical_uri
record_type
source_uri
source_id
source_version
content_digest
observed_at
valid_from
valid_until
authority_class
```

`authority_class` is explicit and must not be inferred from confidence score.

## Assertion model

Competing source claims are preserved as assertions rather than silently overwriting a property on a resource.

Conceptually:

```text
Source --asserted--> Assertion --about--> Resource
```

An Assertion records:

```text
predicate
value
source_uri
evidence_uri
observed_at
valid_from
valid_until
confidence
authority_class
```

A canonical projection may select a value only after an explicit source-authority or conflict-resolution rule succeeds.

## Provenance

Provenance begins at ingestion, before normalization or extraction.

Processing order:

```text
receive source
-> calculate SHA-256 digest
-> assign source/evidence URI
-> persist provenance
-> normalize
-> resolve identity
-> emit assertions
-> validate
-> project
```

V1 uses explicit persistent provenance storage. Implicit in-memory provenance is not acceptable for the proof.

Every canonicalized assertion must trace to at least one evidence object and source version.

## Temporal semantics

The design keeps two time dimensions separate:

- `observed_at`: when the system received or observed the assertion;
- `valid_from` / `valid_until`: when the assertion is claimed to be true in the modeled domain.

Retraction closes semantic validity without deleting historical explainability.

Purge is not part of V1 acceptance because graph deletion alone does not prove erasure from memory/vector copies.

## Pipeline ordering

The deterministic projection pipeline is:

```text
source capture
-> provenance
-> normalization
-> identity resolution
-> deduplication
-> conflict detection
-> resolution or preservation of competing assertions
-> graph validation
-> projection
-> verification receipt
```

Handlers should be deterministic for fixed input/configuration and should not depend on mutable process-global state.

## Validation

V1 requires an admission validator before data is accepted into the durable projection.

The validation contract must enforce at least:

- canonical URI present;
- record type belongs to the V1 semantic vocabulary;
- Assertion has subject, predicate, value, and evidence reference;
- Decision has decision maker, scenario, reasoning, and outcome;
- temporal interval is coherent when both endpoints exist;
- CanonicalFact cannot be created without promotion evidence.

SHACL is the preferred graph-level validation mechanism where the V1 representation is RDF-compatible. Flat ingress envelopes may additionally use Pydantic or JSON Schema.

Generated ontology/shapes may assist discovery but are not normative. Normative constraints are version-controlled.

## Persistence boundary

`ContextGraph` is a working/query graph, not the sole durable system of record.

V1 persistence is split into:

1. **source/evidence corpus** — immutable test inputs plus digests;
2. **provenance store** — persistent lineage/integrity records;
3. **durable semantic projection** — one certified backend or deterministic serialized representation;
4. **ContextGraph working set** — loaded/reconstructed for query, reasoning, and temporal operations.

Backend portability is not assumed. V1 certifies exactly the backend/representation used by the proof.

## Interface boundary

V1 is read-first.

Allowed external capabilities:

```text
READ
- entity.get
- relationship.query
- assertion.query
- provenance.trace
- decision.trace
- explain
- graph.summary
```

Deferred capabilities:

```text
PROPOSE
- assertion.propose
- relationship.propose
- decision.propose

MUTATE
- promote
- retract
- resolve_conflict
- purge
```

If MCP is used for V1, only the read surface is exposed through the integration boundary. Native Semantica write tools are not considered authorization-safe merely because they are available.

## Version and supply-chain policy

The proof starts from exact Semantica commit:

`5579851208ae5adbc813c787be8c8581d8bd2aed`

Runtime/package installation must be pinned to an approved release/artifact or commit and recorded in the verification receipt. Automatic tracking of upstream `main` is prohibited.

Every future Semantica upgrade is treated as a compatibility migration and must rerun the V1 acceptance suite.

## Acceptance gates

V1 is VERIFIED only when all gates pass through observable postconditions.

### G1 — Identity

The same source record produces the same canonical URI on repeated runs.

### G2 — Replay convergence

The fixed corpus ingested twice yields the same canonical graph/projection. No unexplained duplicate entities, assertions, or relationships are created.

### G3 — Provenance completeness

Every accepted Assertion and CanonicalFact traces to at least one persisted source/evidence record.

### G4 — Integrity

Stored provenance integrity/checksum verification passes after restart.

### G5 — Temporal behavior

A retracted assertion is absent from the current active view while remaining present in a historical view that predates retraction.

### G6 — Conflict preservation

Contradictory claims from two sources do not silently overwrite one another. The result is either multiple preserved assertions or an explicit, auditable resolution.

### G7 — Validation

A deliberately malformed graph/record fails admission and cannot enter the accepted projection.

### G8 — Persistence

After process restart, the durable state can be reconstructed and yields the same accepted projection digest.

### G9 — Backend contract

For the selected persistence path, tests assert write-then-read postconditions through public interfaces. Return-value-only success is insufficient.

### G10 — Authority separation

Read/query callers cannot create CanonicalFact, promote assertions, retract data, or invoke provider mutations.

### G11 — Security boundary

Negative authorization tests prove mutation interfaces are unavailable to the V1 read surface. No anonymous public Explorer deployment is part of the proof.

### G12 — Recovery

A pre-change snapshot/digest and post-change snapshot/digest can be compared, and the accepted state can be deterministically reconstructed from source evidence.

## Verification receipt

A successful proof emits a machine-readable receipt containing at least:

```text
semantica_version_or_sha
projection_contract_version
source_corpus_digest
canonical_projection_digest
provenance_integrity_status
validation_status
replay_run_1_digest
replay_run_2_digest
backend_identifier
acceptance_gates
created_at
```

The receipt reports partial or failed gates explicitly. It must never translate unsupported, skipped, or unexecuted checks into PASS.

## Implementation slices

1. **Contract fixtures** — fixed corpus, deterministic identity function, semantic envelope, normative validation rules.
2. **Projection adapter** — source -> provenance -> assertion/decision -> ContextGraph/durable projection.
3. **Persistence/restart proof** — durable provenance + one persistence path.
4. **Acceptance suite** — G1-G12 with observable postconditions.
5. **Read gateway** — minimal query/explain interface; optional read-only MCP wrapper.
6. **Receipt** — canonical machine-readable verification output.

No later slice may weaken an earlier acceptance gate.

## Stop conditions

Stop and report BLOCKED rather than improvising if:

- canonical identity cannot be made deterministic;
- provenance persistence fails or silently falls back to memory;
- the selected persistence backend cannot satisfy required read-after-write semantics;
- replay creates unexplained duplicates;
- validation cannot prevent malformed data from entering the accepted projection;
- a proposed interface would expose mutation authority through the V1 read surface.

## Completion definition

V1 is COMPLETE only when all G1-G12 gates are executed and pass on the pinned Semantica baseline, and the verification receipt is reproducible from the committed corpus and configuration.

Until then, Semantica remains a shadow projection and cannot be described as authoritative project truth.