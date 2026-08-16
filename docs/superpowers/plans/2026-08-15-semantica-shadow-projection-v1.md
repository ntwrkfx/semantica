# Semantica Shadow Projection V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-first Semantica shadow projection that preserves provenance, conflicting assertions, temporal validity, validation, restart reproducibility, and explicit authority separation on Semantica v0.6.5.

**Architecture:** Implement an isolated integration package under `integrations/shadow_projection_v1/`; do not modify Semantica core. Raw evidence is hashed before semantic validation, source provenance is persisted with `ProvenanceManager`, assertions are staged in a deterministic canonical JSON store, staged graphs pass committed SHACL before acceptance, required assertion provenance is persisted before accepted-state commit, and `ContextGraph` is reconstructed only as a query/working view. A final verifier executes G1-G12 and emits a machine-readable receipt.

**Tech Stack:** Python >=3.8, Semantica v0.6.5 commit `5b319560fb0b8403644b70bc592864418cdcc740`, Pydantic v2, rdflib, pyshacl through `.[shacl]`, SQLite provenance, SQLite temporal snapshots, pytest.

## Global Constraints

- Implementation branch: `feat/semantica-shadow-projection-v1`, created directly from `5b319560fb0b8403644b70bc592864418cdcc740`.
- `design/semantica-shadow-projection-v1` is documentation-only and MUST NOT be the code ancestor.
- Copy the approved design and this plan onto the implementation branch before code changes.
- Do not modify fork `main`.
- Do not modify Semantica core. If G1-G12 cannot be satisfied through v0.6.5 public APIs, stop `BLOCKED` and report the missing capability.
- `ContextGraph` is a working/query graph, not durable authority.
- v0.6.5 predates native `ContextGraph.retract_node()`/`retract_edge()`; V1 retraction closes `valid_until` in our durable store.
- Persistence is deterministic canonical JSON + `ProvenanceManager(storage_path=...)` + `TemporalVersionManager(storage_path=...)`.
- No external graph/vector service, Explorer deployment, MCP server, provider mutation, or production erasure workflow.
- Normative constraints are committed SHACL. Generated ontology/shapes are non-normative.
- There is no V1 `CanonicalFact` creation or promotion API.
- Every persistence/mutation test asserts a public read-after-write postcondition; truthy return values alone are insufficient.
- Accepted projection MUST never be committed before required assertion provenance persists successfully.
- Install test environment with `python -m pip install -e ".[dev,shacl]"`.

## File Map

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

V1 deliberately omits MCP. G10/G11 are proven against the explicit `ReadGateway`; a later MCP adapter may delegate only to that gateway.

---

### Task 1: Deterministic identity, strict models, fixed evidence corpus

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
- `canonical_json_bytes(value: Any) -> bytes`
- `sha256_hex(value: Any) -> str`
- `stable_uri(kind: str, stable_key: str, namespace: str = DEFAULT_NAMESPACE) -> str`
- `evidence_uri_from_digest(content_digest: str, namespace: str = DEFAULT_NAMESPACE) -> str`
- Models: `SourceEnvelope`, `SourceRecord`, `RawAssertion`, `EvidenceRecord`, `AssertionRecord`, `DecisionRecord`, `ProjectionReceipt`

- [ ] **Step 1: Add the fixed corpus**

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

`malformed_source.json` intentionally omits `predicate`:

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


def test_identity_is_stable():
    assert stable_uri("resource", "workstream:ws-1") == (
        "https://id.example.invalid/resource/workstream%3Aws-1"
    )
    assert sha256_hex({"b": 2, "a": 1}) == sha256_hex({"a": 1, "b": 2})
    assert evidence_uri_from_digest("abc123") == (
        "https://id.example.invalid/evidence/sha256/abc123"
    )


def test_bad_source_is_rejected():
    text = (FIXTURES / "malformed_source.json").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        SourceEnvelope.model_validate_json(text)
```

- [ ] **Step 3: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_identity_models.py -v
```

Expected: import/collection failure because the package does not yet exist.

- [ ] **Step 4: Implement identity functions**

```python
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

- [ ] **Step 5: Implement strict models**

Use `ConfigDict(extra="forbid")` on every model and `model_validator(mode="after")` on `RawAssertion` and `AssertionRecord` to reject `valid_until < valid_from`.

```python
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

- [ ] **Step 6: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_identity_models.py -v
git add integrations/shadow_projection_v1 tests/integrations/shadow_projection_v1
git commit -m "feat: add deterministic shadow projection contracts"
```

---

### Task 2: Persistent, idempotent provenance

**Files:**
- Create: `integrations/shadow_projection_v1/provenance.py`
- Create: `tests/integrations/shadow_projection_v1/test_provenance.py`

**Interfaces:** `PersistentProvenance(path)`, `.record_evidence()`, `.record_assertion()`, `.lineage()`, `.verify()`.

- [ ] **Step 1: Write failing restart/idempotency tests**

```python
from pathlib import Path

from integrations.shadow_projection_v1.models import EvidenceRecord
from integrations.shadow_projection_v1.provenance import PersistentProvenance


def evidence() -> EvidenceRecord:
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
    first.record_evidence(evidence())
    assert first.verify()["valid"] is True

    second = PersistentProvenance(db)
    lineage = second.lineage(evidence().evidence_uri)
    assert lineage["entity_id"] == evidence().evidence_uri
    assert lineage["integrity_verified"] is True
    assert second.verify()["valid"] is True


def test_same_evidence_is_idempotent(tmp_path: Path):
    prov = PersistentProvenance(tmp_path / "provenance.db")
    prov.record_evidence(evidence())
    before = prov.verify()["total_entries"]
    prov.record_evidence(evidence())
    after = prov.verify()["total_entries"]
    assert after == before
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_provenance.py -v
```

- [ ] **Step 3: Implement wrapper through `ProvenanceManager`**

```python
class PersistentProvenance:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.manager = ProvenanceManager(storage_path=str(self.path))

    def lineage(self, entity_uri):
        return self.manager.get_lineage(entity_uri)

    def record_evidence(self, evidence):
        if self.lineage(evidence.evidence_uri):
            return
        entry = self.manager.track_entity(
            entity_id=evidence.evidence_uri,
            source=evidence.source_uri,
            entity_type="Evidence",
            activity_id="shadow_projection_source_capture",
            agent_id="shadow_projection_v1",
            metadata=evidence.model_dump(mode="json"),
        )
        if entry is None:
            raise RuntimeError("persistent evidence provenance write failed")

    def record_assertion(self, assertion):
        if self.lineage(assertion.assertion_uri):
            return
        entry = self.manager.track_entity(
            entity_id=assertion.assertion_uri,
            source=assertion.evidence_uri,
            entity_type="Assertion",
            activity_id="shadow_projection_assertion_projection",
            agent_id="shadow_projection_v1",
            parent_entity_id=assertion.evidence_uri,
            valid_from=assertion.valid_from.isoformat() if assertion.valid_from else None,
            valid_until=assertion.valid_until.isoformat() if assertion.valid_until else None,
            metadata=assertion.model_dump(mode="json"),
        )
        if entry is None:
            raise RuntimeError("persistent assertion provenance write failed")

    def verify(self):
        return self.manager.verify_chain()
```

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_provenance.py -v
git add integrations/shadow_projection_v1/provenance.py tests/integrations/shadow_projection_v1/test_provenance.py
git commit -m "feat: persist shadow projection provenance"
```

---

### Task 3: Canonical projection store, staging, conflicts, temporal filtering

**Files:**
- Create: `integrations/shadow_projection_v1/store.py`
- Create: `tests/integrations/shadow_projection_v1/test_store_projection.py`

**Interfaces:** `ProjectionStore(path=None)`, `.clone()`, `.commit_from()`, `.upsert_resource()`, `.add_assertion()`, `.retract_assertion()`, `.active_assertions()`, `.conflicts()`, `.graph_dict(at_time=None)`, `.digest()`.

**Contract:** `graph_dict(None)` returns full accepted history. `graph_dict(explicit_datetime)` filters assertions at that explicit time. `digest()` hashes full accepted history and never reads the wall clock.

- [ ] **Step 1: Write failing store tests**

```python
from datetime import datetime, timezone
from pathlib import Path

from integrations.shadow_projection_v1.models import AssertionRecord
from integrations.shadow_projection_v1.store import ProjectionStore

RESOURCE = "https://id.example.invalid/resource/workstream%3Aws-1"


def assertion(uri: str, value: str, evidence_uri: str, valid_from: str):
    return AssertionRecord(
        assertion_uri=uri,
        canonical_uri=RESOURCE,
        predicate="status",
        value=value,
        evidence_uri=evidence_uri,
        observed_at=valid_from,
        valid_from=valid_from,
        valid_until=None,
        confidence=1.0,
        authority_class="authoritative_source",
    )


def test_conflicts_preserve_both_values(tmp_path: Path):
    store = ProjectionStore(tmp_path / "projection.json")
    store.upsert_resource(RESOURCE, "Workstream")
    store.add_assertion(assertion(
        "https://id.example.invalid/assertion/a", "COMPLETE",
        "https://id.example.invalid/evidence/sha256/a", "2026-08-15T20:00:00Z"
    ))
    store.add_assertion(assertion(
        "https://id.example.invalid/assertion/b", "BLOCKED",
        "https://id.example.invalid/evidence/sha256/b", "2026-08-15T20:05:00Z"
    ))
    active = store.active_assertions(datetime(2026, 8, 15, 20, 6, tzinfo=timezone.utc))
    assert {item.value for item in active} == {"COMPLETE", "BLOCKED"}
    assert len(store.conflicts()) == 1


def test_retraction_preserves_history_after_restart(tmp_path: Path):
    path = tmp_path / "projection.json"
    store = ProjectionStore(path)
    store.upsert_resource(RESOURCE, "Workstream")
    uri = "https://id.example.invalid/assertion/a"
    store.add_assertion(assertion(
        uri, "COMPLETE", "https://id.example.invalid/evidence/sha256/a",
        "2026-08-15T20:00:00Z"
    ))
    store.retract_assertion(uri, datetime(2026, 8, 15, 20, 10, tzinfo=timezone.utc))

    restarted = ProjectionStore(path)
    assert len(restarted.active_assertions(
        datetime(2026, 8, 15, 20, 5, tzinfo=timezone.utc)
    )) == 1
    assert len(restarted.active_assertions(
        datetime(2026, 8, 15, 20, 11, tzinfo=timezone.utc)
    )) == 0
    assert any(node["id"] == uri for node in restarted.graph_dict()["nodes"])


def test_restart_preserves_digest(tmp_path: Path):
    path = tmp_path / "projection.json"
    first = ProjectionStore(path)
    first.upsert_resource(RESOURCE, "Workstream")
    first.add_assertion(assertion(
        "https://id.example.invalid/assertion/a", "COMPLETE",
        "https://id.example.invalid/evidence/sha256/a", "2026-08-15T20:00:00Z"
    ))
    expected = first.digest()
    assert ProjectionStore(path).digest() == expected
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
```

- [ ] **Step 3: Implement deterministic persistence/staging**

Persist exact shape:

```json
{"contract":"shadow-projection/v1","resources":[],"assertions":[]}
```

Implement these invariants:

```python
self.resources = {}
self.assertions = {}
```

`_flush()` sorts resources by `canonical_uri`, assertions by `assertion_uri`, writes `<path>.tmp`, then `os.replace`. `clone()` deep-copies into `ProjectionStore(None)`. `commit_from(staged)` deep-copies staged dictionaries and calls `_flush()` once.

`add_assertion()` logic:

```python
existing = self.assertions.get(assertion.assertion_uri)
if existing is not None:
    if existing.model_dump(mode="json") != assertion.model_dump(mode="json"):
        raise ValueError("assertion identity collision")
    return
self.assertions[assertion.assertion_uri] = assertion
self._flush_if_persistent()
```

- [ ] **Step 4: Implement conflict/temporal rules**

```python
start_ok = item.valid_from is None or item.valid_from <= at_time
end_ok = item.valid_until is None or at_time < item.valid_until
active = start_ok and end_ok
```

Conflict key is `(canonical_uri, predicate)`. Emit conflict only when at least two canonical JSON values differ. Return:

```python
{
    "canonical_uri": canonical_uri,
    "predicate": predicate,
    "assertion_uris": sorted(assertion_uris),
    "values": sorted(canonical_json_value_strings),
}
```

- [ ] **Step 5: Implement deterministic graph projection**

Each resource => one node. Each assertion => one `Assertion` node with exact `AssertionRecord.model_dump(mode="json")` metadata and one deterministic `ABOUT` edge. Sort nodes by `id`, edges by `(source, type, target, id)`.

- [ ] **Step 6: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
git add integrations/shadow_projection_v1/store.py tests/integrations/shadow_projection_v1/test_store_projection.py
git commit -m "feat: add deterministic temporal projection store"
```

---

### Task 4: Normative SHACL admission gate

**Files:**
- Create: `integrations/shadow_projection_v1/shapes.ttl`
- Create: `integrations/shadow_projection_v1/validation.py`
- Create: `tests/integrations/shadow_projection_v1/test_validation.py`

- [ ] **Step 1: Commit normative shape**

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix sqn: <https://id.example.invalid/schema/> .

sqn:AssertionShape a sh:NodeShape ;
  sh:targetClass sqn:Assertion ;
  sh:property [ sh:path sqn:subject ; sh:minCount 1 ; sh:maxCount 1 ] ;
  sh:property [ sh:path sqn:predicate ; sh:minCount 1 ; sh:maxCount 1 ] ;
  sh:property [ sh:path sqn:value ; sh:minCount 1 ; sh:maxCount 1 ] ;
  sh:property [ sh:path sqn:evidence ; sh:minCount 1 ; sh:maxCount 1 ] .
```

- [ ] **Step 2: Write failing SHACL tests**

```python
import copy

from integrations.shadow_projection_v1.validation import validate_graph


def valid_graph():
    resource = "https://id.example.invalid/resource/workstream%3Aws-1"
    assertion_uri = "https://id.example.invalid/assertion/a"
    evidence_uri = "https://id.example.invalid/evidence/sha256/a"
    return {
        "nodes": [
            {"id": resource, "type": "Workstream", "content": resource},
            {
                "id": assertion_uri,
                "type": "Assertion",
                "content": "status=COMPLETE",
                "metadata": {
                    "record_type": "Assertion",
                    "assertion_uri": assertion_uri,
                    "canonical_uri": resource,
                    "predicate": "status",
                    "value": "COMPLETE",
                    "evidence_uri": evidence_uri,
                    "observed_at": "2026-08-15T20:00:00Z",
                    "valid_from": "2026-08-15T20:00:00Z",
                    "valid_until": None,
                    "confidence": 1.0,
                    "authority_class": "authoritative_source",
                },
            },
        ],
        "edges": [
            {
                "id": "about-a",
                "source": assertion_uri,
                "target": resource,
                "type": "ABOUT",
                "weight": 1.0,
            }
        ],
    }


def test_valid_graph_conforms():
    assert validate_graph(valid_graph()).conforms is True


def test_missing_evidence_fails():
    broken = copy.deepcopy(valid_graph())
    assertion_node = next(node for node in broken["nodes"] if node["type"] == "Assertion")
    assertion_node["metadata"].pop("evidence_uri")
    result = validate_graph(broken)
    assert result.conforms is False
    assert "evidence" in result.report_text.lower()
```

- [ ] **Step 3: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_validation.py -v
```

- [ ] **Step 4: Implement RDF translation + pyshacl**

```python
@dataclass(frozen=True)
class ValidationResult:
    conforms: bool
    report_text: str


def graph_to_rdf(graph_dict):
    graph = Graph()
    for node in graph_dict.get("nodes", []):
        if node.get("type") != "Assertion":
            continue
        metadata = node.get("metadata", {})
        uri = URIRef(node["id"])
        graph.add((uri, RDF.type, SQN.Assertion))
        if metadata.get("canonical_uri"):
            graph.add((uri, SQN.subject, URIRef(metadata["canonical_uri"])))
        if metadata.get("predicate"):
            graph.add((uri, SQN.predicate, Literal(metadata["predicate"])))
        if "value" in metadata:
            graph.add((uri, SQN.value, Literal(metadata["value"])))
        if metadata.get("evidence_uri"):
            graph.add((uri, SQN.evidence, URIRef(metadata["evidence_uri"])))
    return graph


def validate_graph(graph_dict):
    conforms, _report_graph, report_text = validate(
        data_graph=graph_to_rdf(graph_dict),
        shacl_graph=str(Path(__file__).with_name("shapes.ttl")),
        inference="none",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
    )
    return ValidationResult(bool(conforms), str(report_text))
```

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_validation.py -v
git add integrations/shadow_projection_v1/shapes.ttl integrations/shadow_projection_v1/validation.py tests/integrations/shadow_projection_v1/test_validation.py
git commit -m "feat: gate shadow projection with normative SHACL"
```

---

### Task 5: Ordered projector, provenance-before-commit, ContextGraph reconstruction, snapshots

**Files:**
- Create: `integrations/shadow_projection_v1/projector.py`
- Create: `tests/integrations/shadow_projection_v1/test_projector_restart.py`

**Interfaces:** `ProjectionEngine(projection_path, provenance_path, versions_path)`, `.project_file()`, `.build_context_graph()`, `.snapshot()`.

- [ ] **Step 1: Write failing end-to-end tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from integrations.shadow_projection_v1.projector import ProjectionEngine

FIXTURES = Path(__file__).parent / "fixtures"


def engine(tmp_path):
    return ProjectionEngine(
        projection_path=tmp_path / "projection.json",
        provenance_path=tmp_path / "provenance.db",
        versions_path=tmp_path / "versions.db",
    )


def test_two_sources_preserve_conflict_and_reconstruct_graph(tmp_path):
    item = engine(tmp_path)
    item.project_file(FIXTURES / "source_a.json")
    item.project_file(FIXTURES / "source_b_conflict.json")
    assert len(item.store.conflicts()) == 1
    graph = item.build_context_graph()
    assert graph.stats()["node_count"] == 3
    assert graph.stats()["edge_count"] == 2


def test_replay_is_idempotent(tmp_path):
    item = engine(tmp_path)
    first = item.project_file(FIXTURES / "source_a.json")
    second = item.project_file(FIXTURES / "source_a.json")
    assert second == first


def test_restart_preserves_digest_and_snapshot(tmp_path):
    first = engine(tmp_path)
    first.project_file(FIXTURES / "source_a.json")
    expected = first.store.digest()
    first.snapshot("accepted-1", "accepted state before restart")

    second = engine(tmp_path)
    assert second.store.digest() == expected
    snapshot = second.versions.get_version("accepted-1")
    assert snapshot is not None
    assert second.versions.verify_checksum(snapshot) is True
    assert snapshot["metadata"]["projection_digest"] == expected


def test_malformed_source_records_evidence_but_not_accepted_state(tmp_path):
    item = engine(tmp_path)
    before = item.store.digest()
    with pytest.raises(ValidationError):
        item.project_file(FIXTURES / "malformed_source.json")
    assert item.store.digest() == before
    assert item.provenance.verify()["total_entries"] == 1
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_projector_restart.py -v
```

- [ ] **Step 3: Implement exact ingestion/admission order**

```python
raw = path.read_bytes()
digest = sha256_hex(raw)
payload = json.loads(raw.decode("utf-8"))
source_uri = stable_uri("source", payload["source_id"])
evidence_uri = evidence_uri_from_digest(digest)
self.provenance.record_evidence(EvidenceRecord(
    evidence_uri=evidence_uri,
    source_uri=source_uri,
    source_id=payload["source_id"],
    source_version=payload["source_version"],
    content_digest=digest,
    observed_at=payload["observed_at"],
))
envelope = SourceEnvelope.model_validate(payload)
staged = self.store.clone()
new_assertions = []
```

For every `SourceRecord`:

```python
canonical_uri = stable_uri("resource", record.canonical_key)
staged.upsert_resource(canonical_uri, record.resource_type)
```

Assertion identity:

```python
assertion_uri = stable_uri("assertion", sha256_hex({
    "canonical_uri": canonical_uri,
    "predicate": raw_assertion.predicate,
    "value": raw_assertion.value,
    "evidence_uri": evidence_uri,
}))
```

Add `AssertionRecord` to `staged` and `new_assertions`. Then:

```python
validation = validate_graph(staged.graph_dict())
if not validation.conforms:
    raise ValueError("SHACL admission failed: %s" % validation.report_text)

for assertion_item in new_assertions:
    self.provenance.record_assertion(assertion_item)

self.store.commit_from(staged)
return self.store.digest()
```

If assertion provenance raises, `commit_from()` is never called.

- [ ] **Step 4: Reconstruct `ContextGraph` through v0.6.5 public methods**

```python
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
            edge["source"], edge["target"], edge["type"],
            weight=edge.get("weight", 1.0), id=edge["id"]
        )
    return graph
```

- [ ] **Step 5: Persist accepted snapshots**

```python
self.versions = TemporalVersionManager(storage_path=str(versions_path))


def snapshot(self, label, description):
    return self.versions.create_snapshot(
        graph=self.store.graph_dict(),
        version_label=label,
        author="shadow_projection_v1",
        description=description,
        metadata={"projection_digest": self.store.digest()},
    )
```

- [ ] **Step 6: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_projector_restart.py -v
git add integrations/shadow_projection_v1/projector.py tests/integrations/shadow_projection_v1/test_projector_restart.py
git commit -m "feat: add deterministic Semantica projection engine"
```

---

### Task 6: Read-only gateway and negative authority proof

**Files:**
- Create: `integrations/shadow_projection_v1/gateway.py`
- Create: `tests/integrations/shadow_projection_v1/test_gateway_authority.py`
- Modify: `integrations/shadow_projection_v1/__init__.py`

**Public methods:** `entity_get`, `assertion_query`, `relationship_query`, `provenance_trace`, `explain`, `graph_summary`.

- [ ] **Step 1: Write failing gateway tests**

```python
from pathlib import Path

import pytest

import integrations.shadow_projection_v1 as public_package
from integrations.shadow_projection_v1.gateway import ReadGateway
from integrations.shadow_projection_v1.projector import ProjectionEngine

FIXTURES = Path(__file__).parent / "fixtures"


def gateway(tmp_path):
    engine = ProjectionEngine(
        projection_path=tmp_path / "projection.json",
        provenance_path=tmp_path / "provenance.db",
        versions_path=tmp_path / "versions.db",
    )
    engine.project_file(FIXTURES / "source_a.json")
    return ReadGateway(engine)


def test_root_exports_only_gateway():
    assert public_package.__all__ == ["ReadGateway"]


def test_gateway_has_no_mutators(tmp_path):
    item = gateway(tmp_path)
    for name in ("promote", "retract", "purge", "resolve_conflict", "add_assertion"):
        with pytest.raises(AttributeError):
            getattr(item, name)


def test_explain_contains_assertion_and_provenance(tmp_path):
    result = gateway(tmp_path).explain(
        "https://id.example.invalid/resource/workstream%3Aws-1"
    )
    assert len(result["assertions"]) == 1
    assert result["assertions"][0]["evidence_uri"]
    assert result["provenance"]
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
```

- [ ] **Step 3: Implement gateway with private engine reference**

```python
class ReadGateway:
    def __init__(self, engine):
        self._engine = engine
```

No public property returns `ProjectionEngine`, `ProjectionStore`, `PersistentProvenance`, or `TemporalVersionManager`.

`explain()` exact shape:

```python
{
    "canonical_uri": canonical_uri,
    "resource": resource_dict,
    "assertions": assertion_dicts,
    "conflicts": matching_conflicts,
    "provenance": {
        uri: self._engine.provenance.lineage(uri)
        for uri in assertion_uris
    },
}
```

- [ ] **Step 4: Root export only `ReadGateway`**

```python
from .gateway import ReadGateway

__all__ = ["ReadGateway"]
```

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
git add integrations/shadow_projection_v1/gateway.py integrations/shadow_projection_v1/__init__.py tests/integrations/shadow_projection_v1/test_gateway_authority.py
git commit -m "feat: expose read-only shadow projection gateway"
```

---

### Task 7: G1-G12 verifier and receipt

**Files:**
- Create: `integrations/shadow_projection_v1/verification.py`
- Create: `tests/integrations/shadow_projection_v1/test_acceptance.py`
- Generate after PASS: `docs/superpowers/receipts/semantica-shadow-projection-v1.json`

- [ ] **Step 1: Write failing acceptance test**

```python
from pathlib import Path

from integrations.shadow_projection_v1.verification import run_acceptance

FIXTURES = Path(__file__).parent / "fixtures"


def test_all_gates_pass(tmp_path):
    receipt = run_acceptance(
        tmp_path,
        [FIXTURES / "source_a.json", FIXTURES / "source_b_conflict.json"],
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

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_acceptance.py -v
```

- [ ] **Step 3: Implement one explicit helper per gate**

```python
def g1_identity():
    assert stable_uri("resource", "workstream:ws-1") == stable_uri(
        "resource", "workstream:ws-1"
    )


def g10_authority(item):
    for name in ("promote", "retract", "purge", "resolve_conflict", "add_assertion"):
        assert not hasattr(item, name)
```

Implement the other gate helpers with these postconditions:

```text
G2  Project A+B into replay-1 and replay-2 fresh directories; digests, resource counts, assertion counts are identical.
G3  For every accepted AssertionRecord, provenance.lineage(assertion_uri) is non-empty and contains its evidence URI in the lineage chain.
G4  Construct a new PersistentProvenance against the existing SQLite file; verify()["valid"] is True.
G5  Create one assertion valid at 20:05Z, retract at 20:10Z, prove present at 20:05Z and absent at 20:11Z after reopening ProjectionStore.
G6  A+B produces exactly two status assertions and exactly one conflict.
G7  Record accepted digest, project malformed source expecting ValidationError, verify accepted digest unchanged.
G8  Construct a new ProjectionEngine over existing files and verify identical accepted digest.
G9  Write resource/assertion, reopen ProjectionStore, compare exact resource dictionary and AssertionRecord.model_dump(mode="json").
G11 Assert package __all__ == ["ReadGateway"], forbidden gateway mutation attributes absent, and verification code imports/starts no server entry point.
G12 Create TemporalVersionManager snapshot; verify checksum; reconstruct from clean source corpus and match snapshot metadata projection_digest.
```

No `pytest.skip`, xfail, conditional PASS, or swallowed exception is allowed.

- [ ] **Step 4: Implement fail-closed runner**

```python
def run_gate(gates, code, function):
    function()
    gates[code] = "PASS"


def run_acceptance(work_dir, corpus_paths):
    gates = {}
    run_gate(gates, "G1", g1_identity)
    run_gate(gates, "G2", lambda: g2_replay(work_dir, corpus_paths))
    run_gate(gates, "G3", lambda: g3_provenance(work_dir, corpus_paths))
    run_gate(gates, "G4", lambda: g4_integrity(work_dir, corpus_paths))
    run_gate(gates, "G5", lambda: g5_temporal(work_dir))
    run_gate(gates, "G6", lambda: g6_conflict(work_dir, corpus_paths))
    run_gate(gates, "G7", lambda: g7_validation(work_dir))
    run_gate(gates, "G8", lambda: g8_restart(work_dir, corpus_paths))
    run_gate(gates, "G9", lambda: g9_store_contract(work_dir))
    run_gate(gates, "G10", lambda: g10_authority(build_gateway(work_dir)))
    run_gate(gates, "G11", lambda: g11_security_surface(build_gateway(work_dir)))
    run_gate(gates, "G12", lambda: g12_recovery(work_dir, corpus_paths))
```

If any helper raises, propagate the failure and do not emit a successful receipt.

- [ ] **Step 5: Compute deterministic receipt values**

```python
corpus_rows = [
    {"name": path.name, "sha256": sha256_hex(path.read_bytes())}
    for path in corpus_paths
]
corpus_rows.sort(key=lambda row: row["name"])
source_corpus_digest = sha256_hex(corpus_rows)
```

Backend identifier exactly:

```text
json-projection+sqlite-provenance+sqlite-versions
```

`created_at` is UTC receipt metadata only and is excluded from replay equality.

- [ ] **Step 6: Implement receipt writer**

```python
def write_receipt(receipt, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
```

- [ ] **Step 7: Run complete V1 + focused upstream tests**

```bash
pytest tests/integrations/shadow_projection_v1 -v
pytest tests/provenance/test_manager.py tests/context/test_context.py tests/test_graph_store_methods.py -q
```

Required: V1 has zero skips/xfails. Any upstream failure must be reproduced on clean v0.6.5 before classification as pre-existing.

- [ ] **Step 8: Generate and validate committed receipt**

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

- [ ] **Step 9: Commit proof**

```bash
git add integrations/shadow_projection_v1/verification.py tests/integrations/shadow_projection_v1/test_acceptance.py docs/superpowers/receipts/semantica-shadow-projection-v1.json
git commit -m "test: prove Semantica shadow projection acceptance"
```

---

## Final Verification Before PR

Prove the actual fork point, not merely that v0.6.5 appears somewhere in history:

```bash
git fetch https://github.com/semantica-agi/semantica.git main:refs/remotes/semantica-upstream/main
test "$(git merge-base HEAD refs/remotes/semantica-upstream/main)" = "5b319560fb0b8403644b70bc592864418cdcc740"
git status --short
pytest tests/integrations/shadow_projection_v1 -v
pytest tests/provenance/test_manager.py tests/context/test_context.py tests/test_graph_store_methods.py -q
python -m json.tool docs/superpowers/receipts/semantica-shadow-projection-v1.json >/dev/null
git diff --check
```

Required state:

```text
fork point with current upstream main: exactly 5b319560fb0b8403644b70bc592864418cdcc740
working tree: clean
V1 tests: PASS, zero skips/xfails
focused upstream regressions: PASS or independently proven pre-existing
receipt: G1-G12 PASS
fork main: unchanged
external deployments/resources: none
```

Open a draft PR only after this evidence exists. Do not retarget or merge onto stale fork `main` without a separate synchronization decision and complete compatibility rerun.
