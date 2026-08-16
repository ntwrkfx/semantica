# Semantica Shadow Projection V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-first Semantica shadow projection that preserves provenance, conflicting assertions, temporal validity, validation, restart reproducibility, and explicit authority separation on the pinned Semantica v0.6.5 baseline.

**Architecture:** Implement the proof as an isolated integration package under `integrations/shadow_projection_v1/`, leaving Semantica core behavior unchanged. Raw source bytes are hashed first, source provenance is persisted through `ProvenanceManager(storage_path=...)`, strict source models produce deterministic assertion identities, the accepted projection is stored as canonical JSON, normative SHACL validates a staged graph before commit, `ContextGraph` is reconstructed only as a working/query view, and a G1-G12 verifier emits a machine-readable receipt.

**Tech Stack:** Python >=3.8, Semantica v0.6.5, Pydantic v2, `rdflib`, `pyshacl` through the existing `shacl` optional extra, SQLite-backed `ProvenanceManager`, SQLite-backed `TemporalVersionManager`, pytest.

## Global Constraints

- Execution code MUST branch from Semantica v0.6.5 commit `5b319560fb0b8403644b70bc592864418cdcc740`.
- Do NOT use `design/semantica-shadow-projection-v1` as the code baseline; that branch contains the approved documents but has newer upstream ancestry.
- Implementation branch: `feat/semantica-shadow-projection-v1`.
- Before code changes, copy the approved design and this plan into the implementation branch so the execution branch is self-contained.
- Do not modify fork `main` during implementation.
- Do not modify Semantica core modules. If a G1-G12 gate cannot be satisfied through public v0.6.5 APIs, stop BLOCKED and report the exact missing capability.
- `ContextGraph` is a working/query graph, not durable authority.
- Native `ContextGraph.retract_node()` / `retract_edge()` are not available in v0.6.5; V1 retraction closes `valid_until` in the durable projection and reconstructs the working graph.
- V1 persistence is: canonical JSON projection + SQLite provenance + SQLite version snapshots.
- No external graph/vector database, public Explorer deployment, MCP server, provider mutation, or unrestricted write tool is part of V1.
- Normative graph constraints are committed SHACL. Generated ontology/shapes are not normative.
- `CanonicalFact` has no V1 creation API. Therefore V1 cannot silently promote an assertion to canonical authority.
- Every persistence/mutation test MUST verify a public read-after-write postcondition; truthy return values are insufficient.
- Test environment: `python -m pip install -e ".[dev,shacl]"`.

---

## File Structure

```text
integrations/shadow_projection_v1/
├── __init__.py
├── identity.py
├── models.py
├── provenance.py
├── store.py
├── validation.py
├── projector.py
├── gateway.py
├── verification.py
└── shapes.ttl

tests/integrations/shadow_projection_v1/
├── __init__.py
├── fixtures/
│   ├── source_a.json
│   ├── source_b_conflict.json
│   └── malformed_source.json
├── test_identity_models.py
├── test_provenance.py
├── test_store_projection.py
├── test_validation.py
├── test_projector_restart.py
├── test_gateway_authority.py
└── test_acceptance.py
```

V1 deliberately omits MCP. G10/G11 are proven against the explicit `ReadGateway`; an MCP wrapper may later delegate only to that gateway.

---

### Task 1: Deterministic identity, strict models, and fixed corpus

**Files:**
- Create: `integrations/shadow_projection_v1/__init__.py`
- Create: `integrations/shadow_projection_v1/identity.py`
- Create: `integrations/shadow_projection_v1/models.py`
- Create: `tests/integrations/shadow_projection_v1/__init__.py`
- Create: `tests/integrations/shadow_projection_v1/fixtures/source_a.json`
- Create: `tests/integrations/shadow_projection_v1/fixtures/source_b_conflict.json`
- Create: `tests/integrations/shadow_projection_v1/fixtures/malformed_source.json`
- Create: `tests/integrations/shadow_projection_v1/test_identity_models.py`

**Interfaces:**
- Produces: `canonical_json_bytes(value: Any) -> bytes`
- Produces: `sha256_hex(value: Any) -> str`
- Produces: `stable_uri(kind: str, stable_key: str, namespace: str = DEFAULT_NAMESPACE) -> str`
- Produces: `evidence_uri_from_digest(content_digest: str, namespace: str = DEFAULT_NAMESPACE) -> str`
- Produces models: `SourceEnvelope`, `SourceRecord`, `RawAssertion`, `EvidenceRecord`, `AssertionRecord`, `DecisionRecord`, `ProjectionReceipt`

- [ ] **Step 1: Add the fixed source corpus**

`source_a.json`:

```json
{
  "source_id": "ops-state-a",
  "source_version": "commit-a1",
  "observed_at": "2026-08-15T20:00:00Z",
  "records": [
    {
      "canonical_key": "workstream:ws-1",
      "resource_type": "Workstream",
      "assertions": [
        {
          "predicate": "status",
          "value": "COMPLETE",
          "confidence": 1.0,
          "authority_class": "authoritative_source",
          "valid_from": "2026-08-15T20:00:00Z",
          "valid_until": null
        }
      ]
    }
  ]
}
```

`source_b_conflict.json`:

```json
{
  "source_id": "provider-observation-b",
  "source_version": "snapshot-b1",
  "observed_at": "2026-08-15T20:05:00Z",
  "records": [
    {
      "canonical_key": "workstream:ws-1",
      "resource_type": "Workstream",
      "assertions": [
        {
          "predicate": "status",
          "value": "BLOCKED",
          "confidence": 0.95,
          "authority_class": "provider_observation",
          "valid_from": "2026-08-15T20:05:00Z",
          "valid_until": null
        }
      ]
    }
  ]
}
```

`malformed_source.json`:

```json
{
  "source_id": "bad-source",
  "source_version": "bad-1",
  "observed_at": "2026-08-15T20:10:00Z",
  "records": [
    {
      "canonical_key": "workstream:ws-bad",
      "resource_type": "Workstream",
      "assertions": [
        {
          "value": "COMPLETE",
          "confidence": 1.0,
          "authority_class": "authoritative_source"
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Write failing identity/model tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from integrations.shadow_projection_v1.identity import (
    evidence_uri_from_digest,
    sha256_hex,
    stable_uri,
)
from integrations.shadow_projection_v1.models import SourceEnvelope

FIXTURES = Path(__file__).parent / "fixtures"


def test_stable_uri_is_deterministic():
    first = stable_uri("resource", "workstream:ws-1")
    second = stable_uri("resource", "workstream:ws-1")
    assert first == second
    assert first == "https://id.example.invalid/resource/workstream%3Aws-1"


def test_evidence_uri_has_digest_path_segment():
    assert evidence_uri_from_digest("abc123") == (
        "https://id.example.invalid/evidence/sha256/abc123"
    )


def test_sha256_hex_is_order_independent_for_mapping_keys():
    assert sha256_hex({"b": 2, "a": 1}) == sha256_hex({"a": 1, "b": 2})


def test_source_envelope_rejects_missing_assertion_predicate():
    payload = (FIXTURES / "malformed_source.json").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        SourceEnvelope.model_validate_json(payload)
```

- [ ] **Step 3: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_identity_models.py -v
```

Expected: import/collection failure because the integration package does not exist.

- [ ] **Step 4: Implement deterministic identity functions**

```python
# integrations/shadow_projection_v1/identity.py
import hashlib
import json
from typing import Any
from urllib.parse import quote

DEFAULT_NAMESPACE = "https://id.example.invalid"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def stable_uri(kind: str, stable_key: str, namespace: str = DEFAULT_NAMESPACE) -> str:
    if not kind or not stable_key:
        raise ValueError("kind and stable_key are required")
    return "%s/%s/%s" % (
        namespace.rstrip("/"),
        quote(kind, safe=""),
        quote(stable_key, safe=""),
    )


def evidence_uri_from_digest(
    content_digest: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    if not content_digest:
        raise ValueError("content_digest is required")
    return "%s/evidence/sha256/%s" % (
        namespace.rstrip("/"),
        quote(content_digest, safe=""),
    )
```

- [ ] **Step 5: Implement all strict Pydantic models**

```python
# integrations/shadow_projection_v1/models.py
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthorityClass(str, Enum):
    AUTHORITATIVE_SOURCE = "authoritative_source"
    PROVIDER_OBSERVATION = "provider_observation"
    DERIVED = "derived"
    PROPOSED = "proposed"


class RawAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: str = Field(min_length=1)
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    authority_class: AuthorityClass
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_interval(self):
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until cannot precede valid_from")
        return self


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_key: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    assertions: List[RawAssertion] = Field(min_length=1)


class SourceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    observed_at: datetime
    records: List[SourceRecord] = Field(min_length=1)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_uri: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    content_digest: str = Field(min_length=1)
    observed_at: datetime


class AssertionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_type: Literal["Assertion"] = "Assertion"
    assertion_uri: str = Field(min_length=1)
    canonical_uri: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: Any
    evidence_uri: str = Field(min_length=1)
    observed_at: datetime
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    confidence: float = Field(ge=0.0, le=1.0)
    authority_class: AuthorityClass

    @model_validator(mode="after")
    def validate_interval(self):
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until cannot precede valid_from")
        return self


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_type: Literal["Decision"] = "Decision"
    decision_uri: str = Field(min_length=1)
    decision_maker: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    observed_at: datetime


class ProjectionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantica_version_or_sha: str
    projection_contract_version: str
    source_corpus_digest: str
    canonical_projection_digest: str
    provenance_integrity_status: str
    validation_status: str
    replay_run_1_digest: str
    replay_run_2_digest: str
    backend_identifier: str
    acceptance_gates: Dict[str, str]
    created_at: datetime
```

- [ ] **Step 6: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_identity_models.py -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add integrations/shadow_projection_v1 tests/integrations/shadow_projection_v1
git commit -m "feat: add deterministic shadow projection contracts"
```

---

### Task 2: Persistent provenance with idempotent evidence/assertion recording

**Files:**
- Create: `integrations/shadow_projection_v1/provenance.py`
- Create: `tests/integrations/shadow_projection_v1/test_provenance.py`

**Interfaces:**
- Consumes: `EvidenceRecord`, `AssertionRecord`
- Produces: `PersistentProvenance(path: Path)`
- Produces: `record_evidence(evidence: EvidenceRecord) -> None`
- Produces: `record_assertion(assertion: AssertionRecord) -> None`
- Produces: `lineage(entity_uri: str) -> Dict[str, Any]`
- Produces: `verify() -> Dict[str, Any]`

- [ ] **Step 1: Write failing restart/idempotency tests**

```python
from pathlib import Path

from integrations.shadow_projection_v1.models import EvidenceRecord
from integrations.shadow_projection_v1.provenance import PersistentProvenance


def _evidence() -> EvidenceRecord:
    return EvidenceRecord(
        evidence_uri="https://id.example.invalid/evidence/sha256/abc123",
        source_uri="https://id.example.invalid/source/ops-state-a",
        source_id="ops-state-a",
        source_version="commit-a1",
        content_digest="abc123",
        observed_at="2026-08-15T20:00:00Z",
    )


def test_provenance_survives_restart(tmp_path: Path):
    db = tmp_path / "provenance.db"
    first = PersistentProvenance(db)
    first.record_evidence(_evidence())
    assert first.verify()["valid"] is True

    second = PersistentProvenance(db)
    lineage = second.lineage(_evidence().evidence_uri)
    assert lineage["entity_id"] == _evidence().evidence_uri
    assert lineage["integrity_verified"] is True
    assert second.verify()["valid"] is True


def test_replaying_same_evidence_does_not_append_version(tmp_path: Path):
    db = tmp_path / "provenance.db"
    prov = PersistentProvenance(db)
    prov.record_evidence(_evidence())
    before = prov.verify()["total_entries"]
    prov.record_evidence(_evidence())
    after = prov.verify()["total_entries"]
    assert after == before
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_provenance.py -v
```

Expected: import failure for `PersistentProvenance`.

- [ ] **Step 3: Implement the public-API provenance wrapper**

```python
# integrations/shadow_projection_v1/provenance.py
from pathlib import Path
from typing import Any, Dict

from semantica.provenance import ProvenanceManager

from .models import AssertionRecord, EvidenceRecord


class PersistentProvenance:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.manager = ProvenanceManager(storage_path=str(self.path))

    def lineage(self, entity_uri: str) -> Dict[str, Any]:
        return self.manager.get_lineage(entity_uri)

    def record_evidence(self, evidence: EvidenceRecord) -> None:
        if self.lineage(evidence.evidence_uri):
            return
        entry = self.manager.track_entity(
            entity_id=evidence.evidence_uri,
            source=evidence.source_uri,
            entity_type="Evidence",
            activity_id="shadow_projection_source_capture",
            agent_id="shadow_projection_v1",
            metadata={
                "source_id": evidence.source_id,
                "source_version": evidence.source_version,
                "content_digest": evidence.content_digest,
                "observed_at": evidence.observed_at.isoformat(),
            },
        )
        if entry is None:
            raise RuntimeError("persistent evidence provenance write failed")

    def record_assertion(self, assertion: AssertionRecord) -> None:
        if self.lineage(assertion.assertion_uri):
            return
        entry = self.manager.track_entity(
            entity_id=assertion.assertion_uri,
            source=assertion.evidence_uri,
            entity_type="Assertion",
            activity_id="shadow_projection_assertion_projection",
            agent_id="shadow_projection_v1",
            parent_entity_id=assertion.evidence_uri,
            valid_from=(
                assertion.valid_from.isoformat() if assertion.valid_from else None
            ),
            valid_until=(
                assertion.valid_until.isoformat() if assertion.valid_until else None
            ),
            metadata=assertion.model_dump(mode="json"),
        )
        if entry is None:
            raise RuntimeError("persistent assertion provenance write failed")

    def verify(self) -> Dict[str, Any]:
        return self.manager.verify_chain()
```

- [ ] **Step 4: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_provenance.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/shadow_projection_v1/provenance.py tests/integrations/shadow_projection_v1/test_provenance.py
git commit -m "feat: persist shadow projection provenance"
```

---

### Task 3: Deterministic durable projection, conflicts, staging, and temporal filtering

**Files:**
- Create: `integrations/shadow_projection_v1/store.py`
- Create: `tests/integrations/shadow_projection_v1/test_store_projection.py`

**Interfaces:**
- Produces: `ProjectionStore(path: Optional[Path] = None)`
- Produces: `clone() -> ProjectionStore` (in-memory deep copy)
- Produces: `commit_from(staged: ProjectionStore) -> None`
- Produces: `upsert_resource(canonical_uri: str, resource_type: str) -> None`
- Produces: `add_assertion(assertion: AssertionRecord) -> None`
- Produces: `retract_assertion(assertion_uri: str, valid_until: datetime) -> None`
- Produces: `active_assertions(at_time: datetime) -> List[AssertionRecord]`
- Produces: `conflicts() -> List[Dict[str, Any]]`
- Produces: `graph_dict(at_time: Optional[datetime] = None) -> Dict[str, Any]`
- Produces: `digest() -> str`

**Semantics:** `graph_dict()` with `at_time=None` returns the full accepted historical projection. Supplying `at_time` returns only assertions active at that explicit instant. `digest()` always hashes the full accepted historical projection and therefore never depends on wall-clock time.

- [ ] **Step 1: Write failing deterministic/conflict/temporal tests**

```python
from datetime import datetime, timezone
from pathlib import Path

from integrations.shadow_projection_v1.models import AssertionRecord
from integrations.shadow_projection_v1.store import ProjectionStore

RESOURCE = "https://id.example.invalid/resource/workstream%3Aws-1"


def _assertion(uri: str, value: str, evidence: str, valid_from: str) -> AssertionRecord:
    return AssertionRecord(
        assertion_uri=uri,
        canonical_uri=RESOURCE,
        predicate="status",
        value=value,
        evidence_uri=evidence,
        observed_at=valid_from,
        valid_from=valid_from,
        valid_until=None,
        confidence=1.0,
        authority_class="authoritative_source",
    )


def test_conflicting_values_are_preserved(tmp_path: Path):
    store = ProjectionStore(tmp_path / "projection.json")
    store.upsert_resource(RESOURCE, "Workstream")
    store.add_assertion(_assertion(
        "https://id.example.invalid/assertion/a",
        "COMPLETE",
        "https://id.example.invalid/evidence/sha256/a",
        "2026-08-15T20:00:00Z",
    ))
    store.add_assertion(_assertion(
        "https://id.example.invalid/assertion/b",
        "BLOCKED",
        "https://id.example.invalid/evidence/sha256/b",
        "2026-08-15T20:05:00Z",
    ))
    assert len(store.conflicts()) == 1
    active = store.active_assertions(
        datetime(2026, 8, 15, 20, 6, tzinfo=timezone.utc)
    )
    assert {item.value for item in active} == {"COMPLETE", "BLOCKED"}


def test_retraction_closes_current_view_but_preserves_history(tmp_path: Path):
    store = ProjectionStore(tmp_path / "projection.json")
    store.upsert_resource(RESOURCE, "Workstream")
    uri = "https://id.example.invalid/assertion/a"
    store.add_assertion(_assertion(
        uri,
        "COMPLETE",
        "https://id.example.invalid/evidence/sha256/a",
        "2026-08-15T20:00:00Z",
    ))
    store.retract_assertion(
        uri, datetime(2026, 8, 15, 20, 10, tzinfo=timezone.utc)
    )
    restarted = ProjectionStore(tmp_path / "projection.json")
    assert len(restarted.active_assertions(
        datetime(2026, 8, 15, 20, 5, tzinfo=timezone.utc)
    )) == 1
    assert len(restarted.active_assertions(
        datetime(2026, 8, 15, 20, 11, tzinfo=timezone.utc)
    )) == 0
    assert any(node["id"] == uri for node in restarted.graph_dict()["nodes"])


def test_restart_preserves_same_projection_digest(tmp_path: Path):
    path = tmp_path / "projection.json"
    first = ProjectionStore(path)
    first.upsert_resource(RESOURCE, "Workstream")
    first.add_assertion(_assertion(
        "https://id.example.invalid/assertion/a",
        "COMPLETE",
        "https://id.example.invalid/evidence/sha256/a",
        "2026-08-15T20:00:00Z",
    ))
    digest = first.digest()
    second = ProjectionStore(path)
    assert second.digest() == digest
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
```

Expected: import failure for `ProjectionStore`.

- [ ] **Step 3: Implement store state and deterministic serialization**

Internal JSON shape:

```json
{
  "contract": "shadow-projection/v1",
  "resources": [],
  "assertions": []
}
```

Requirements:

```python
# store.py behavioral core
self.resources = {}   # canonical_uri -> {"canonical_uri", "resource_type"}
self.assertions = {}  # assertion_uri -> AssertionRecord
```

`_flush()` serializes resources sorted by `canonical_uri` and assertions sorted by `assertion_uri`, writes to `<projection>.tmp`, then calls `os.replace(tmp, projection)`.

`add_assertion()` is idempotent when the exact same serialized assertion already exists; if an existing `assertion_uri` has different content, raise `ValueError("assertion identity collision")`.

`clone()` creates `ProjectionStore(None)` and deep-copies both dictionaries. `commit_from(staged)` deep-copies staged dictionaries into the persistent store and calls `_flush()` exactly once.

- [ ] **Step 4: Implement explicit conflict and temporal logic**

A conflict groups active or historical assertions by `(canonical_uri, predicate)` and returns a conflict only when at least two distinct canonical JSON values exist. Each conflict dictionary is:

```python
{
    "canonical_uri": canonical_uri,
    "predicate": predicate,
    "assertion_uris": sorted(assertion_uris),
    "values": sorted(values_as_canonical_json_strings),
}
```

An assertion is active at `at_time` iff:

```python
start_ok = assertion.valid_from is None or assertion.valid_from <= at_time
end_ok = assertion.valid_until is None or at_time < assertion.valid_until
active = start_ok and end_ok
```

`retract_assertion()` must reject unknown IDs and reject a `valid_until` earlier than `valid_from`; it then persists and is verified by reconstructing a new `ProjectionStore` in tests.

- [ ] **Step 5: Implement deterministic property-graph projection**

Every resource becomes one node. Every assertion becomes one node plus one `ABOUT` edge to the resource. Assertion node metadata is exactly `AssertionRecord.model_dump(mode="json")`. Sort nodes by `id` and edges by `(source, type, target, id)`.

- [ ] **Step 6: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add integrations/shadow_projection_v1/store.py tests/integrations/shadow_projection_v1/test_store_projection.py
git commit -m "feat: add deterministic temporal projection store"
```

---

### Task 4: Normative SHACL admission gate

**Files:**
- Create: `integrations/shadow_projection_v1/shapes.ttl`
- Create: `integrations/shadow_projection_v1/validation.py`
- Create: `tests/integrations/shadow_projection_v1/test_validation.py`

**Interfaces:**
- Produces: `ValidationResult(conforms: bool, report_text: str)`
- Produces: `graph_to_rdf(graph_dict: Dict[str, Any]) -> rdflib.Graph`
- Produces: `validate_graph(graph_dict: Dict[str, Any]) -> ValidationResult`

- [ ] **Step 1: Add normative V1 SHACL**

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix sqn: <https://id.example.invalid/schema/> .

sqn:AssertionShape
    a sh:NodeShape ;
    sh:targetClass sqn:Assertion ;
    sh:property [ sh:path sqn:subject ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path sqn:predicate ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path sqn:value ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path sqn:evidence ; sh:minCount 1 ; sh:maxCount 1 ] .
```

- [ ] **Step 2: Write failing SHACL tests with an explicit fixture**

```python
import copy

from integrations.shadow_projection_v1.validation import validate_graph


def _valid_graph():
    resource = "https://id.example.invalid/resource/workstream%3Aws-1"
    assertion = "https://id.example.invalid/assertion/a"
    evidence = "https://id.example.invalid/evidence/sha256/a"
    return {
        "nodes": [
            {"id": resource, "type": "Workstream", "content": resource},
            {
                "id": assertion,
                "type": "Assertion",
                "content": "status=COMPLETE",
                "metadata": {
                    "record_type": "Assertion",
                    "assertion_uri": assertion,
                    "canonical_uri": resource,
                    "predicate": "status",
                    "value": "COMPLETE",
                    "evidence_uri": evidence,
                    "observed_at": "2026-08-15T20:00:00Z",
                    "valid_from": "2026-08-15T20:00:00Z",
                    "valid_until": None,
                    "confidence": 1.0,
                    "authority_class": "authoritative_source"
                }
            }
        ],
        "edges": [
            {
                "id": "about-a",
                "source": assertion,
                "target": resource,
                "type": "ABOUT",
                "weight": 1.0
            }
        ]
    }


def test_valid_assertion_graph_conforms():
    assert validate_graph(_valid_graph()).conforms is True


def test_missing_evidence_fails_admission():
    broken = copy.deepcopy(_valid_graph())
    assertion = next(node for node in broken["nodes"] if node["type"] == "Assertion")
    assertion["metadata"].pop("evidence_uri")
    result = validate_graph(broken)
    assert result.conforms is False
    assert "evidence" in result.report_text.lower()
```

- [ ] **Step 3: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_validation.py -v
```

Expected: import failure for validation module.

- [ ] **Step 4: Implement RDF translation and SHACL validation**

```python
# integrations/shadow_projection_v1/validation.py
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from pyshacl import validate
from rdflib import Graph, Literal, Namespace, RDF, URIRef

SQN = Namespace("https://id.example.invalid/schema/")


@dataclass(frozen=True)
class ValidationResult:
    conforms: bool
    report_text: str


def graph_to_rdf(graph_dict: Dict[str, Any]) -> Graph:
    graph = Graph()
    for node in graph_dict.get("nodes", []):
        if node.get("type") != "Assertion":
            continue
        metadata = node.get("metadata", {})
        assertion_uri = URIRef(node["id"])
        graph.add((assertion_uri, RDF.type, SQN.Assertion))
        if metadata.get("canonical_uri"):
            graph.add((assertion_uri, SQN.subject, URIRef(metadata["canonical_uri"])))
        if metadata.get("predicate"):
            graph.add((assertion_uri, SQN.predicate, Literal(metadata["predicate"])))
        if "value" in metadata:
            graph.add((assertion_uri, SQN.value, Literal(metadata["value"])))
        if metadata.get("evidence_uri"):
            graph.add((assertion_uri, SQN.evidence, URIRef(metadata["evidence_uri"])))
    return graph


def validate_graph(graph_dict: Dict[str, Any]) -> ValidationResult:
    shapes_path = Path(__file__).with_name("shapes.ttl")
    conforms, _report_graph, report_text = validate(
        data_graph=graph_to_rdf(graph_dict),
        shacl_graph=str(shapes_path),
        inference="none",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
    )
    return ValidationResult(bool(conforms), str(report_text))
```

- [ ] **Step 5: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_validation.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add integrations/shadow_projection_v1/shapes.ttl integrations/shadow_projection_v1/validation.py tests/integrations/shadow_projection_v1/test_validation.py
git commit -m "feat: gate shadow projection with normative SHACL"
```

---

### Task 5: Ordered projector, ContextGraph reconstruction, and persistent snapshots

**Files:**
- Create: `integrations/shadow_projection_v1/projector.py`
- Create: `tests/integrations/shadow_projection_v1/test_projector_restart.py`

**Interfaces:**
- Produces: `ProjectionEngine(projection_path: Path, provenance_path: Path, versions_path: Path)`
- Produces: `project_file(path: Path) -> str`
- Produces: `build_context_graph(at_time: Optional[datetime] = None) -> ContextGraph`
- Produces: `snapshot(label: str, description: str) -> Dict[str, Any]`

- [ ] **Step 1: Write failing end-to-end tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from integrations.shadow_projection_v1.projector import ProjectionEngine

FIXTURES = Path(__file__).parent / "fixtures"


def _engine(tmp_path: Path) -> ProjectionEngine:
    return ProjectionEngine(
        projection_path=tmp_path / "projection.json",
        provenance_path=tmp_path / "provenance.db",
        versions_path=tmp_path / "versions.db",
    )


def test_two_sources_preserve_conflict_and_build_context_graph(tmp_path: Path):
    engine = _engine(tmp_path)
    engine.project_file(FIXTURES / "source_a.json")
    engine.project_file(FIXTURES / "source_b_conflict.json")
    assert len(engine.store.conflicts()) == 1
    graph = engine.build_context_graph()
    assert graph.stats()["node_count"] == 3
    assert graph.stats()["edge_count"] == 2


def test_replay_has_identical_projection_digest(tmp_path: Path):
    engine = _engine(tmp_path)
    digest_one = engine.project_file(FIXTURES / "source_a.json")
    digest_two = engine.project_file(FIXTURES / "source_a.json")
    assert digest_two == digest_one


def test_restart_reconstructs_identical_projection_and_snapshot(tmp_path: Path):
    first = _engine(tmp_path)
    first.project_file(FIXTURES / "source_a.json")
    expected = first.store.digest()
    first.snapshot("accepted-1", "accepted state before restart")

    second = _engine(tmp_path)
    assert second.store.digest() == expected
    snapshot = second.versions.get_version("accepted-1")
    assert snapshot is not None
    assert second.versions.verify_checksum(snapshot) is True
    assert snapshot["metadata"]["projection_digest"] == expected


def test_malformed_source_records_evidence_but_never_changes_projection(tmp_path: Path):
    engine = _engine(tmp_path)
    before = engine.store.digest()
    with pytest.raises(ValidationError):
        engine.project_file(FIXTURES / "malformed_source.json")
    assert engine.store.digest() == before
    assert engine.provenance.verify()["total_entries"] == 1
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_projector_restart.py -v
```

Expected: import failure for `ProjectionEngine`.

- [ ] **Step 3: Implement exact source-capture and staging order**

`project_file()` order is fixed:

```python
raw_bytes = path.read_bytes()
content_digest = sha256_hex(raw_bytes)
raw_payload = json.loads(raw_bytes.decode("utf-8"))

# Header capture occurs before semantic SourceEnvelope validation.
source_id = raw_payload["source_id"]
source_version = raw_payload["source_version"]
observed_at = raw_payload["observed_at"]
source_uri = stable_uri("source", source_id)
evidence_uri = evidence_uri_from_digest(content_digest)

evidence = EvidenceRecord(
    evidence_uri=evidence_uri,
    source_uri=source_uri,
    source_id=source_id,
    source_version=source_version,
    content_digest=content_digest,
    observed_at=observed_at,
)
self.provenance.record_evidence(evidence)

envelope = SourceEnvelope.model_validate(raw_payload)
staged = self.store.clone()
```

For each `SourceRecord`:

```python
canonical_uri = stable_uri("resource", record.canonical_key)
staged.upsert_resource(canonical_uri, record.resource_type)
```

For each `RawAssertion`, derive identity from a canonical payload that includes evidence so competing sources stay distinct:

```python
identity_payload = {
    "canonical_uri": canonical_uri,
    "predicate": raw_assertion.predicate,
    "value": raw_assertion.value,
    "evidence_uri": evidence_uri,
}
assertion_uri = stable_uri("assertion", sha256_hex(identity_payload))
```

Create an `AssertionRecord`, add it to `staged`, then validate `staged.graph_dict()`. If SHACL fails, raise `ValueError("SHACL admission failed: %s" % report_text)` and do not call `self.store.commit_from(staged)` or record assertion provenance.

After SHACL passes:

```python
self.store.commit_from(staged)
for assertion in newly_staged_assertions:
    self.provenance.record_assertion(assertion)
return self.store.digest()
```

This gives source-level provenance even when semantic admission fails, while accepted assertion provenance is written only after admission.

- [ ] **Step 4: Implement ContextGraph reconstruction using v0.6.5 public methods**

```python
from semantica.context import ContextGraph


def build_context_graph(self, at_time=None):
    payload = self.store.graph_dict(at_time=at_time)
    graph = ContextGraph()
    for node in payload["nodes"]:
        metadata = dict(node.get("metadata", {}))
        graph.add_node(
            node["id"],
            node["type"],
            node.get("content") or node["id"],
            valid_from=node.get("valid_from"),
            valid_until=node.get("valid_until"),
            **metadata
        )
    for edge in payload["edges"]:
        graph.add_edge(
            edge["source"],
            edge["target"],
            edge["type"],
            weight=edge.get("weight", 1.0),
            id=edge["id"],
        )
    return graph
```

- [ ] **Step 5: Implement persistent version snapshots**

Initialize:

```python
from semantica.change_management import TemporalVersionManager

self.versions = TemporalVersionManager(storage_path=str(versions_path))
```

Snapshot the full accepted historical graph:

```python
def snapshot(self, label, description):
    return self.versions.create_snapshot(
        graph=self.store.graph_dict(),
        version_label=label,
        author="shadow_projection_v1",
        description=description,
        metadata={"projection_digest": self.store.digest()},
    )
```

- [ ] **Step 6: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_projector_restart.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add integrations/shadow_projection_v1/projector.py tests/integrations/shadow_projection_v1/test_projector_restart.py
git commit -m "feat: add deterministic Semantica projection engine"
```

---

### Task 6: Read-only gateway and negative authority proof

**Files:**
- Create: `integrations/shadow_projection_v1/gateway.py`
- Create: `tests/integrations/shadow_projection_v1/test_gateway_authority.py`
- Modify: `integrations/shadow_projection_v1/__init__.py`

**Interfaces:**
- Produces: `ReadGateway(engine: ProjectionEngine)`
- Produces: `entity_get(canonical_uri: str) -> Dict[str, Any]`
- Produces: `assertion_query(canonical_uri: Optional[str] = None, predicate: Optional[str] = None) -> List[Dict[str, Any]]`
- Produces: `relationship_query(canonical_uri: str) -> List[Dict[str, Any]]`
- Produces: `provenance_trace(entity_uri: str) -> Dict[str, Any]`
- Produces: `explain(canonical_uri: str) -> Dict[str, Any]`
- Produces: `graph_summary() -> Dict[str, Any]`

- [ ] **Step 1: Write failing authority tests**

```python
from pathlib import Path

import pytest

import integrations.shadow_projection_v1 as public_package
from integrations.shadow_projection_v1.gateway import ReadGateway
from integrations.shadow_projection_v1.projector import ProjectionEngine

FIXTURES = Path(__file__).parent / "fixtures"


def _gateway(tmp_path: Path) -> ReadGateway:
    engine = ProjectionEngine(
        projection_path=tmp_path / "projection.json",
        provenance_path=tmp_path / "provenance.db",
        versions_path=tmp_path / "versions.db",
    )
    engine.project_file(FIXTURES / "source_a.json")
    return ReadGateway(engine)


def test_package_root_exports_only_read_gateway():
    assert public_package.__all__ == ["ReadGateway"]


def test_gateway_exposes_no_mutation_methods(tmp_path: Path):
    gateway = _gateway(tmp_path)
    for name in ("promote", "retract", "purge", "resolve_conflict", "add_assertion"):
        with pytest.raises(AttributeError):
            getattr(gateway, name)


def test_explain_returns_assertions_and_evidence(tmp_path: Path):
    gateway = _gateway(tmp_path)
    result = gateway.explain(
        "https://id.example.invalid/resource/workstream%3Aws-1"
    )
    assert result["canonical_uri"].endswith("workstream%3Aws-1")
    assert len(result["assertions"]) == 1
    assert result["assertions"][0]["evidence_uri"]
    assert result["provenance"]
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
```

Expected: import failure for gateway module.

- [ ] **Step 3: Implement `ReadGateway` with a private engine reference**

```python
class ReadGateway:
    def __init__(self, engine):
        self._engine = engine
```

The class defines only the six public methods listed in Interfaces. No public property returns `ProjectionEngine`, `ProjectionStore`, `PersistentProvenance`, or `TemporalVersionManager`.

`explain()` returns this exact shape:

```python
{
    "canonical_uri": canonical_uri,
    "resource": resource_dict,
    "assertions": assertion_dicts,
    "conflicts": matching_conflicts,
    "provenance": {
        assertion_uri: self._engine.provenance.lineage(assertion_uri)
        for assertion_uri in assertion_uris
    },
}
```

- [ ] **Step 4: Make the package root read-only by construction**

```python
# integrations/shadow_projection_v1/__init__.py
from .gateway import ReadGateway

__all__ = ["ReadGateway"]
```

`ProjectionEngine` remains importable only from `integrations.shadow_projection_v1.projector` for internal/test execution.

- [ ] **Step 5: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add integrations/shadow_projection_v1/gateway.py integrations/shadow_projection_v1/__init__.py tests/integrations/shadow_projection_v1/test_gateway_authority.py
git commit -m "feat: expose read-only shadow projection gateway"
```

---

### Task 7: G1-G12 acceptance runner and machine-readable receipt

**Files:**
- Create: `integrations/shadow_projection_v1/verification.py`
- Create: `tests/integrations/shadow_projection_v1/test_acceptance.py`
- Create at verification time: `docs/superpowers/receipts/semantica-shadow-projection-v1.json`

**Interfaces:**
- Produces: `run_acceptance(work_dir: Path, corpus_paths: List[Path]) -> ProjectionReceipt`
- Produces: `write_receipt(receipt: ProjectionReceipt, path: Path) -> None`

- [ ] **Step 1: Write failing acceptance test**

```python
from pathlib import Path

from integrations.shadow_projection_v1.verification import run_acceptance

FIXTURES = Path(__file__).parent / "fixtures"


def test_all_v1_acceptance_gates_pass(tmp_path: Path):
    receipt = run_acceptance(
        work_dir=tmp_path,
        corpus_paths=[
            FIXTURES / "source_a.json",
            FIXTURES / "source_b_conflict.json",
        ],
    )
    assert receipt.semantica_version_or_sha == (
        "v0.6.5@5b319560fb0b8403644b70bc592864418cdcc740"
    )
    assert receipt.projection_contract_version == "shadow-projection/v1"
    assert receipt.replay_run_1_digest == receipt.replay_run_2_digest
    assert receipt.provenance_integrity_status == "PASS"
    assert receipt.validation_status == "PASS"
    assert set(receipt.acceptance_gates) == {"G%d" % n for n in range(1, 13)}
    assert all(value == "PASS" for value in receipt.acceptance_gates.values())
```

- [ ] **Step 2: Run acceptance test and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_acceptance.py -v
```

Expected: import failure for verification module.

- [ ] **Step 3: Implement explicit gate helpers**

`verification.py` defines one helper per gate, each raising `AssertionError` on failure:

```python
def _g1_identity():
    assert stable_uri("resource", "workstream:ws-1") == stable_uri(
        "resource", "workstream:ws-1"
    )


def _g10_authority(gateway):
    for name in ("promote", "retract", "purge", "resolve_conflict", "add_assertion"):
        assert not hasattr(gateway, name)
```

The remaining helpers must perform these exact observable checks:

```text
G2  project the same corpus into two fresh directories; digests and node/assertion counts match
G3  every accepted AssertionRecord has provenance lineage containing its evidence URI
G4  reconstruct PersistentProvenance from the SQLite path; verify_chain()["valid"] is True
G5  retract one assertion at 20:10Z; 20:05Z active view contains it and 20:11Z active view omits it
G6  source A + source B yield two assertions for status and exactly one conflict
G7  malformed source raises Pydantic ValidationError; accepted projection digest is unchanged
G8  reconstruct ProjectionEngine from existing files; accepted projection digest is identical
G9  write resource/assertion, reconstruct ProjectionStore from disk, and compare exact model dumps
G11 package __all__ is ["ReadGateway"], forbidden gateway methods are absent, and no server process is started by the verifier
G12 create TemporalVersionManager snapshot, verify checksum, then reconstruct from source corpus and match snapshot metadata projection_digest
```

No helper may use `pytest.skip`, xfail, conditional pass, or `try/except: pass`.

- [ ] **Step 4: Implement `run_acceptance()` with fail-closed gate recording**

```python
def run_acceptance(work_dir, corpus_paths):
    gates = {}

    def run_gate(code, fn):
        fn()
        gates[code] = "PASS"

    run_gate("G1", _g1_identity)
    run_gate("G2", lambda: _g2_replay(work_dir, corpus_paths))
    run_gate("G3", lambda: _g3_provenance(work_dir, corpus_paths))
    run_gate("G4", lambda: _g4_integrity(work_dir, corpus_paths))
    run_gate("G5", lambda: _g5_temporal(work_dir))
    run_gate("G6", lambda: _g6_conflict(work_dir, corpus_paths))
    run_gate("G7", lambda: _g7_validation(work_dir))
    run_gate("G8", lambda: _g8_restart(work_dir, corpus_paths))
    run_gate("G9", lambda: _g9_store_contract(work_dir))
    run_gate("G10", lambda: _g10_authority(_build_gateway(work_dir)))
    run_gate("G11", lambda: _g11_security_surface(_build_gateway(work_dir)))
    run_gate("G12", lambda: _g12_recovery(work_dir, corpus_paths))
```

If any helper raises, `run_acceptance()` propagates the failure; it does not emit a successful receipt. A separate CLI/reporting layer is not part of V1.

For G2 use `work_dir / "replay-1"` and `work_dir / "replay-2"`. Never compare two executions against the same mutable store.

- [ ] **Step 5: Implement deterministic receipt fields**

`source_corpus_digest` is SHA-256 over a sorted list of:

```python
{
    "name": path.name,
    "sha256": sha256_hex(path.read_bytes()),
}
```

`canonical_projection_digest` is the accepted `ProjectionStore.digest()` after source A + source B.

`backend_identifier` is exactly:

```text
json-projection+sqlite-provenance+sqlite-versions
```

`created_at` is current UTC and is receipt metadata only; it is not part of G2 replay comparison.

- [ ] **Step 6: Implement receipt writing**

```python
import json


def write_receipt(receipt, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
```

- [ ] **Step 7: Run complete V1 tests**

```bash
pytest tests/integrations/shadow_projection_v1 -v
```

Expected: all tests PASS; zero skips and zero xfails in this directory.

- [ ] **Step 8: Run focused upstream regressions**

```bash
pytest tests/provenance/test_manager.py tests/context/test_context.py tests/test_graph_store_methods.py -q
```

Expected: PASS. If a failure appears, reproduce it on a clean v0.6.5 checkout before classifying it as pre-existing.

- [ ] **Step 9: Generate and validate the committed receipt**

```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory

from integrations.shadow_projection_v1.verification import run_acceptance, write_receipt

fixtures = Path("tests/integrations/shadow_projection_v1/fixtures")
with TemporaryDirectory() as tmp:
    receipt = run_acceptance(
        Path(tmp),
        [fixtures / "source_a.json", fixtures / "source_b_conflict.json"],
    )
    write_receipt(
        receipt,
        Path("docs/superpowers/receipts/semantica-shadow-projection-v1.json"),
    )
PY

python -m json.tool docs/superpowers/receipts/semantica-shadow-projection-v1.json >/dev/null
git diff --check
```

Expected: JSON parses, `git diff --check` exits 0, and the receipt shows G1-G12 all PASS.

- [ ] **Step 10: Commit the acceptance proof**

```bash
git add integrations/shadow_projection_v1/verification.py tests/integrations/shadow_projection_v1/test_acceptance.py docs/superpowers/receipts/semantica-shadow-projection-v1.json
git commit -m "test: prove Semantica shadow projection acceptance"
```

---

## Final Verification Before PR

Run from the implementation branch rooted at `5b319560fb0b8403644b70bc592864418cdcc740`:

```bash
git merge-base --is-ancestor 5b319560fb0b8403644b70bc592864418cdcc740 HEAD
git status --short
pytest tests/integrations/shadow_projection_v1 -v
pytest tests/provenance/test_manager.py tests/context/test_context.py tests/test_graph_store_methods.py -q
python -m json.tool docs/superpowers/receipts/semantica-shadow-projection-v1.json >/dev/null
git diff --check
git log --oneline --decorate -8
```

Required state:

```text
v0.6.5 ancestor check: PASS
working tree: clean
V1 acceptance tests: PASS, zero skips/xfails
focused upstream regressions: PASS or separately proven pre-existing
receipt G1-G12: PASS
fork main: unchanged
external deployments/resources: none
```

Open a draft PR only after the final verification evidence exists. Do not silently retarget the implementation onto the stale fork `main`; synchronization or retargeting is a separate compatibility decision and requires rerunning the complete acceptance suite.
