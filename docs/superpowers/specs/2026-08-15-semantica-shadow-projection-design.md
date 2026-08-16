# Semantica Shadow Projection V1 — Design

Status: APPROVED DESIGN / NOT IMPLEMENTED  
Decision: D1:A  
Runtime baseline: Semantica `v0.6.5` commit `5b319560fb0b8403644b70bc592864418cdcc740`  
Target: deterministic, read-first semantic/provenance projection proof

## Objective

Prove that Semantica can add semantic graph, provenance, temporal context, decision intelligence, and deterministic reasoning without becoming an uncontrolled competing source of truth.

The V1 proof must ingest a fixed evidence corpus, assign deterministic canonical identities, preserve source provenance, project assertions into Semantica, survive restart, validate graph structure, and produce identical canonical results on replay.

## Non-goals

V1 does not:

- make Semantica the sole authoritative datastore;
- expose unrestricted native MCP writes;
- auto-promote inferred or agent-generated facts to canonical truth;
- certify external graph/vector backends;
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
SHACL validation gate
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

The example host is intentionally non-routable for V1 tests. A production namespace is a later deployment decision and is not needed to verify determinism.

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

V1 uses Semantica `ProvenanceManager` with an explicitly configured SQLite path. Implicit in-memory provenance is a test failure.

Every accepted Assertion must trace to at least one evidence object and source version. Any CanonicalFact fixture used solely for negative admission tests must also require promotion evidence.

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
-> SHACL validation
-> projection
-> verification receipt
```

Handlers are deterministic for fixed input/configuration and must not depend on mutable process-global state.

## Validation

V1 uses two explicit validation layers:

1. **Ingress envelope validation** using Pydantic models for source records, assertions, decisions, and projection receipts.
2. **Graph-level validation** using version-controlled SHACL Turtle shapes and Semantica's SHACL support.

The validation contract enforces at least:

- canonical URI present;
- record type belongs to the V1 semantic vocabulary;
- Assertion has subject, predicate, value, and evidence reference;
- Decision has decision maker, scenario, reasoning, and outcome;
- temporal interval is coherent when both endpoints exist;
- CanonicalFact cannot be created without promotion evidence.

Generated ontology/shapes may assist discovery but are not normative. V1 normative SHACL shapes are committed source artifacts.

## Concrete V1 persistence

V1 deliberately avoids an external graph database so backend portability is not confused with proof correctness.

The proof uses:

1. **Immutable evidence corpus** — committed JSON fixtures with SHA-256 corpus digest.
2. **Persistent provenance store** — SQLite via explicit `ProvenanceManager(storage_path=...)`.
3. **Durable semantic projection** — canonical JSON written atomically with deterministic key/order normalization before hashing.
4. **ContextGraph working set** — reconstructed from the durable projection for query, temporal behavior, decision relationships, and reasoning.
5. **Version snapshots** — SQLite-backed `TemporalVersionManager` for pre/post state comparison where required by the recovery gate.

A future phase may certify Apache AGE, Neo4j, or another backend using the same public postcondition tests. External backend certification is not required for V1 completion.

## Read interface boundary

V1 provides a small application-owned read facade. It does not expose native Semantica write tools.

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

The read facade contains no mutation methods. Negative tests assert that promotion/retraction/purge operations are not addressable through it.

A read-only MCP wrapper may be added after the V1 proof passes; MCP is not required to prove the core projection contract.

## Version and supply-chain policy

The proof runtime starts from Semantica release `v0.6.5`, annotated tag target commit:

`5b319560fb0b8403644b70bc592864418cdcc740`

The implementation branch must derive from that exact commit. Package/environment receipts must also record the resolved Semantica version and commit. Automatic tracking of upstream `main` is prohibited.

Every future Semantica upgrade is treated as a compatibility migration and must rerun the complete V1 acceptance suite before promotion.

## Acceptance gates

V1 is VERIFIED only when all gates pass through observable postconditions.

### G1 — Identity

The same source record produces the same canonical URI on repeated runs.

### G2 — Replay convergence

The fixed corpus ingested twice yields the same canonical projection digest. No unexplained duplicate entities, assertions, or relationships are created.

### G3 — Provenance completeness

Every accepted Assertion traces to at least one persisted source/evidence record.

### G4 — Integrity

Stored provenance integrity/checksum verification passes after restart.

### G5 — Temporal behavior

A retracted assertion is absent from the current active view while remaining present in a historical view that predates retraction.

### G6 — Conflict preservation

Contradictory claims from two sources do not silently overwrite one another. The result is either multiple preserved assertions or an explicit, auditable resolution.

### G7 — Validation

A deliberately malformed ingress record and a deliberately SHACL-invalid graph both fail admission and cannot enter the accepted projection.

### G8 — Persistence

After process restart, state reconstructed from the durable projection yields the same canonical projection digest and provenance remains queryable.

### G9 — Persistence contract

Tests assert write-then-read postconditions for the canonical JSON projection, SQLite provenance store, and version snapshot store. A truthy return value alone is insufficient proof.

### G10 — Authority separation

Read-facade callers cannot create CanonicalFact, promote assertions, retract data, purge data, or invoke provider mutations.

### G11 — Security boundary

Negative interface tests prove mutation operations are unavailable through the V1 read surface. No anonymous public Explorer deployment is part of the proof.

### G12 — Recovery

A pre-change snapshot/digest and post-change snapshot/digest can be compared, and the accepted state can be deterministically reconstructed from committed source evidence.

## Verification receipt

A proof run emits a machine-readable receipt containing at least:

```text
semantica_version
semantica_commit
projection_contract_version
source_corpus_digest
canonical_projection_digest
provenance_integrity_status
validation_status
replay_run_1_digest
replay_run_2_digest
persistence_profile
acceptance_gates
created_at
```

The receipt reports partial or failed gates explicitly. Unsupported, skipped, or unexecuted checks cannot be translated into PASS.

## Implementation slices

1. **Contract fixtures** — fixed corpus, deterministic identity function, Pydantic semantic envelope, normative SHACL shapes.
2. **Projection adapter** — source -> provenance -> assertion/decision -> ContextGraph/canonical JSON projection.
3. **Persistence/restart proof** — SQLite provenance + deterministic JSON projection + version snapshots.
4. **Acceptance suite** — G1-G12 with observable postconditions.
5. **Read facade** — minimal query/explain interface with no mutation methods.
6. **Receipt** — canonical machine-readable verification output.

No later slice may weaken an earlier acceptance gate.

## Stop conditions

Stop and report BLOCKED rather than improvising if:

- canonical identity cannot be made deterministic;
- provenance persistence fails or silently falls back to memory;
- deterministic serialization cannot reproduce the same projection digest;
- replay creates unexplained duplicates;
- ingress or SHACL validation cannot prevent malformed data from entering the accepted projection;
- a proposed interface would expose mutation authority through the V1 read surface.

## Completion definition

V1 is COMPLETE only when all G1-G12 gates are executed and pass on Semantica `v0.6.5` commit `5b319560fb0b8403644b70bc592864418cdcc740`, and the verification receipt is reproducible from the committed corpus and configuration.

Until then, Semantica remains a shadow projection and cannot be described as authoritative project truth.