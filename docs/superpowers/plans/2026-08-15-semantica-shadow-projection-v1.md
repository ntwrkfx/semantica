# Semantica Shadow Projection V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-first Semantica shadow projection that preserves provenance, conflicting assertions, temporal validity, validation, restart reproducibility, and explicit authority separation on the pinned Semantica v0.6.5 baseline.

**Architecture:** Implement the proof as an isolated integration package under `integrations/shadow_projection_v1/`, leaving Semantica core behavior unchanged. Source JSON is captured and hashed first, provenance is persisted through `ProvenanceManager(storage_path=...)`, assertions are projected into a deterministic JSON store and Semantica `ContextGraph` working set, normative SHACL validates the graph before acceptance, and a verification runner emits a machine-readable G1-G12 receipt.

**Tech Stack:** Python >=3.8, Semantica v0.6.5, Pydantic v2, `rdflib`, `pyshacl` via the existing `shacl` optional extra, SQLite-backed `ProvenanceManager`, SQLite-backed `TemporalVersionManager`, pytest.

## Global Constraints

- Execution code MUST branch from Semantica v0.6.5 commit `5b319560fb0b8403644b70bc592864418cdcc740`.
- Do NOT use `design/semantica-shadow-projection-v1` as the code baseline; that branch exists only to persist the approved design and plan and has newer upstream ancestry.
- The implementation branch name is `feat/semantica-shadow-projection-v1`.
- Copy the approved design and this plan into the implementation branch before the first code commit so execution evidence remains self-contained.
- Do not modify fork `main` during implementation.
- Do not modify Semantica core modules unless an acceptance gate is impossible through public APIs; stop BLOCKED before doing so.
- `ContextGraph` is a working/query graph, not the sole durable state.
- Native `ContextGraph.retract_node()` / `retract_edge()` are NOT available in the pinned v0.6.5 release; V1 retraction closes `valid_until` in our durable projection and reconstructs the working graph.
- V1 uses persistent SQLite provenance and persistent SQLite version snapshots, plus a deterministic canonical JSON projection.
- No external graph database, vector database, public Explorer deployment, unrestricted MCP write surface, or provider mutation is part of V1.
- Normative graph constraints live in version-controlled SHACL; generated ontology/shapes are not normative.
- No `CanonicalFact` may be created through the public V1 read gateway.
- Every test that claims persistence or mutation success MUST verify an observable read-after-write postcondition; a truthy return value is insufficient.
- Test environment command: `python -m pip install -e ".[dev,shacl]"`.

---

## File Structure

Create the following bounded integration package and tests:

```text
integrations/shadow_projection_v1/
├── __init__.py              # public read-first integration API
├── identity.py              # canonical JSON, digests, stable URIs
├── models.py                # strict ingress/projected/receipt models
├── provenance.py            # persistent Semantica provenance wrapper
├── store.py                 # deterministic durable JSON projection + temporal filtering
├── validation.py            # RDF translation + normative SHACL gate
├── projector.py             # ordered source -> provenance -> projection orchestration
├── gateway.py               # read-only query/explain surface
├── verification.py          # G1-G12 execution and receipt generation
└── shapes.ttl               # normative V1 SHACL constraints

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

Do not add an MCP wrapper in V1. G10/G11 are proven against the explicit read gateway; MCP remains a later adapter over that gateway.

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
- Produces: `SourceEnvelope`, `SourceRecord`, `RawAssertion`, `EvidenceRecord`, `AssertionRecord`, `DecisionRecord`, `ProjectionReceipt`

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

from integrations.shadow_projection_v1.identity import sha256_hex, stable_uri
from integrations.shadow_projection_v1.models import SourceEnvelope

FIXTURES = Path(__file__).parent / "fixtures"


def test_stable_uri_is_deterministic():
    first = stable_uri("resource", "workstream:ws-1")
    second = stable_uri("resource", "workstream:ws-1")
    assert first == second
    assert first.startswith("https://id.example.invalid/resource/")


def test_sha256_hex_is_order_independent_for_mapping_keys():
    assert sha256_hex({"b": 2, "a": 1}) == sha256_hex({"a": 1, "b": 2})


def test_source_envelope_rejects_missing_assertion_predicate():
    payload = (FIXTURES / "malformed_source.json").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        SourceEnvelope.model_validate_json(payload)
```

- [ ] **Step 3: Run the tests and confirm RED**

Run:

```bash
pytest tests/integrations/shadow_projection_v1/test_identity_models.py -v
```

Expected: collection/import failure because the integration package does not exist.

- [ ] **Step 4: Implement deterministic identity functions**

`identity.py` core:

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
    if isinstance(value, bytes):
        payload = value
    else:
        payload = canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def stable_uri(kind: str, stable_key: str, namespace: str = DEFAULT_NAMESPACE) -> str:
    if not kind or not stable_key:
        raise ValueError("kind and stable_key are required")
    return "%s/%s/%s" % (
        namespace.rstrip("/"),
        quote(kind, safe=""),
        quote(stable_key, safe=""),
    )
```

- [ ] **Step 5: Implement strict Pydantic models**

`models.py` must use `ConfigDict(extra="forbid")` and Python-3.8-compatible `typing` forms. Minimum model contracts:

```python
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    assertions: List[RawAssertion]


class SourceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    observed_at: datetime
    records: List[SourceRecord]
```

Add projected models with explicit fields from the approved spec. `DecisionRecord` requires `decision_maker`, `scenario`, `reasoning`, and `outcome`; `ProjectionReceipt` has fixed fields for version/SHA, contract version, corpus/projection digests, integrity/validation statuses, replay digests, backend identifier, gate map, and `created_at`.

- [ ] **Step 6: Run tests and confirm GREEN**

Run:

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

### Task 2: Persistent provenance with idempotent evidence recording

**Files:**
- Create: `integrations/shadow_projection_v1/provenance.py`
- Create: `tests/integrations/shadow_projection_v1/test_provenance.py`

**Interfaces:**
- Consumes: `EvidenceRecord`, `AssertionRecord`
- Produces: `PersistentProvenance(path: Path)`
- Produces: `record_evidence(evidence: EvidenceRecord) -> None`
- Produces: `record_assertion(assertion: AssertionRecord) -> None`
- Produces: `verify() -> Dict[str, Any]`

- [ ] **Step 1: Write failing persistence and idempotency tests**

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
    lineage = second.manager.get_lineage(_evidence().evidence_uri)
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

- [ ] **Step 3: Implement the Semantica provenance wrapper**

Core behavior:

```python
from pathlib import Path
from typing import Any, Dict

from semantica.provenance import ProvenanceManager

from .models import AssertionRecord, EvidenceRecord


class PersistentProvenance:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.manager = ProvenanceManager(storage_path=str(self.path))

    def record_evidence(self, evidence: EvidenceRecord) -> None:
        if self.manager.get_lineage(evidence.evidence_uri):
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
            },
        )
        if entry is None:
            raise RuntimeError("persistent evidence provenance write failed")

    def record_assertion(self, assertion: AssertionRecord) -> None:
        if self.manager.get_lineage(assertion.assertion_uri):
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

    def verify(self) -> Dict[str, Any]:
        return self.manager.verify_chain()
```

- [ ] **Step 4: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_provenance.py -v
```

Expected: PASS, including restart and idempotency.

- [ ] **Step 5: Commit**

```bash
git add integrations/shadow_projection_v1/provenance.py tests/integrations/shadow_projection_v1/test_provenance.py

git commit -m "feat: persist shadow projection provenance"
```

---

### Task 3: Deterministic durable projection, conflicts, and temporal filtering

**Files:**
- Create: `integrations/shadow_projection_v1/store.py`
- Create: `tests/integrations/shadow_projection_v1/test_store_projection.py`

**Interfaces:**
- Produces: `ProjectionStore(path: Path)`
- Produces: `upsert_resource(canonical_uri: str, resource_type: str) -> None`
- Produces: `add_assertion(assertion: AssertionRecord) -> None`
- Produces: `retract_assertion(assertion_uri: str, valid_until: datetime) -> None`
- Produces: `active_assertions(at_time: datetime) -> List[AssertionRecord]`
- Produces: `conflicts() -> List[Dict[str, Any]]`
- Produces: `graph_dict(at_time: Optional[datetime] = None) -> Dict[str, Any]`
- Produces: `digest(at_time: Optional[datetime] = None) -> str`

- [ ] **Step 1: Write failing deterministic/conflict/temporal tests**

```python
from datetime import datetime, timezone
from pathlib import Path

from integrations.shadow_projection_v1.models import AssertionRecord
from integrations.shadow_projection_v1.store import ProjectionStore


def _assertion(uri: str, value: str, evidence: str, valid_from: str) -> AssertionRecord:
    return AssertionRecord(
        assertion_uri=uri,
        canonical_uri="https://id.example.invalid/resource/workstream%3Aws-1",
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
    store.upsert_resource("https://id.example.invalid/resource/workstream%3Aws-1", "Workstream")
    store.add_assertion(_assertion("urn:assertion:a", "COMPLETE", "urn:evidence:a", "2026-08-15T20:00:00Z"))
    store.add_assertion(_assertion("urn:assertion:b", "BLOCKED", "urn:evidence:b", "2026-08-15T20:05:00Z"))
    assert len(store.conflicts()) == 1
    assert {item.value for item in store.active_assertions(datetime(2026, 8, 15, 20, 6, tzinfo=timezone.utc))} == {"COMPLETE", "BLOCKED"}


def test_retraction_closes_current_view_but_preserves_history(tmp_path: Path):
    store = ProjectionStore(tmp_path / "projection.json")
    store.upsert_resource("https://id.example.invalid/resource/workstream%3Aws-1", "Workstream")
    store.add_assertion(_assertion("urn:assertion:a", "COMPLETE", "urn:evidence:a", "2026-08-15T20:00:00Z"))
    store.retract_assertion("urn:assertion:a", datetime(2026, 8, 15, 20, 10, tzinfo=timezone.utc))
    assert len(store.active_assertions(datetime(2026, 8, 15, 20, 5, tzinfo=timezone.utc))) == 1
    assert len(store.active_assertions(datetime(2026, 8, 15, 20, 11, tzinfo=timezone.utc))) == 0


def test_restart_preserves_same_projection_digest(tmp_path: Path):
    path = tmp_path / "projection.json"
    first = ProjectionStore(path)
    first.upsert_resource("https://id.example.invalid/resource/workstream%3Aws-1", "Workstream")
    first.add_assertion(_assertion("urn:assertion:a", "COMPLETE", "urn:evidence:a", "2026-08-15T20:00:00Z"))
    digest = first.digest()
    second = ProjectionStore(path)
    assert second.digest() == digest
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
```

Expected: import failure for `ProjectionStore`.

- [ ] **Step 3: Implement deterministic storage and atomic persistence**

Use dictionaries keyed by canonical URI/assertion URI in memory; serialize sorted lists only. Persist through `path.with_suffix(path.suffix + ".tmp")` followed by `os.replace()`.

The graph representation must be deterministic:

```python
{
    "nodes": [
        {"id": resource_uri, "type": resource_type, "content": resource_uri},
        {
            "id": assertion.assertion_uri,
            "type": "Assertion",
            "content": "%s=%s" % (assertion.predicate, assertion.value),
            "metadata": assertion.model_dump(mode="json"),
            "valid_from": assertion.valid_from.isoformat() if assertion.valid_from else None,
            "valid_until": assertion.valid_until.isoformat() if assertion.valid_until else None,
        },
    ],
    "edges": [
        {
            "id": "about:" + assertion.assertion_uri,
            "source": assertion.assertion_uri,
            "target": assertion.canonical_uri,
            "type": "ABOUT",
            "weight": 1.0,
        }
    ],
}
```

Sort nodes by `id` and edges by `(source, type, target, id)` before hashing or writing.

`retract_assertion()` must raise `KeyError` for unknown assertions, reject a close time earlier than `valid_from`, update only `valid_until`, persist, then reread the stored record in the test path.

- [ ] **Step 4: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Add normative V1 shapes**

`shapes.ttl` must require every `sqn:Assertion` to have exactly one `sqn:subject`, at least one `sqn:predicate`, exactly one `sqn:value`, and exactly one `sqn:evidence`:

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix sqn: <https://id.example.invalid/schema/> .

sqn:AssertionShape
    a sh:NodeShape ;
    sh:targetClass sqn:Assertion ;
    sh:property [ sh:path sqn:subject ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path sqn:predicate ; sh:minCount 1 ] ;
    sh:property [ sh:path sqn:value ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:property [ sh:path sqn:evidence ; sh:minCount 1 ; sh:maxCount 1 ] .
```

- [ ] **Step 2: Write failing SHACL tests**

```python
from integrations.shadow_projection_v1.validation import validate_graph


def test_valid_assertion_graph_conforms(valid_graph_dict):
    result = validate_graph(valid_graph_dict)
    assert result.conforms is True


def test_missing_evidence_fails_admission(valid_graph_dict):
    broken = valid_graph_dict.copy()
    broken["nodes"] = [dict(node) for node in valid_graph_dict["nodes"]]
    assertion = next(node for node in broken["nodes"] if node["type"] == "Assertion")
    assertion["metadata"] = dict(assertion["metadata"])
    assertion["metadata"].pop("evidence_uri")
    result = validate_graph(broken)
    assert result.conforms is False
    assert "evidence" in result.report_text.lower()
```

Create the `valid_graph_dict` pytest fixture in this test file from an explicit two-node/one-edge dictionary; do not reuse internal `ProjectionStore` state.

- [ ] **Step 3: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_validation.py -v
```

Expected: import failure for validation module.

- [ ] **Step 4: Implement RDF translation and SHACL validation**

`graph_to_rdf()` must map property-graph Assertion nodes to RDF:

```python
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from pyshacl import validate

SQN = Namespace("https://id.example.invalid/schema/")


def graph_to_rdf(graph_dict):
    graph = Graph()
    for node in graph_dict["nodes"]:
        if node.get("type") != "Assertion":
            continue
        metadata = node.get("metadata", {})
        assertion_uri = URIRef(node["id"])
        graph.add((assertion_uri, RDF.type, SQN.Assertion))
        graph.add((assertion_uri, SQN.subject, URIRef(metadata["canonical_uri"])))
        graph.add((assertion_uri, SQN.predicate, Literal(metadata["predicate"])))
        graph.add((assertion_uri, SQN.value, Literal(metadata["value"])))
        if metadata.get("evidence_uri"):
            graph.add((assertion_uri, SQN.evidence, URIRef(metadata["evidence_uri"])))
    return graph
```

`validate_graph()` loads `shapes.ttl` by `Path(__file__).with_name("shapes.ttl")` and calls `pyshacl.validate(..., inference="none", abort_on_first=False, allow_infos=False, allow_warnings=False)`.

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

### Task 5: Ordered projector, ContextGraph reconstruction, and restart snapshots

**Files:**
- Create: `integrations/shadow_projection_v1/projector.py`
- Create: `tests/integrations/shadow_projection_v1/test_projector_restart.py`

**Interfaces:**
- Consumes: source JSON file, `PersistentProvenance`, `ProjectionStore`, `validate_graph`
- Produces: `ProjectionEngine(projection_path: Path, provenance_path: Path, versions_path: Path)`
- Produces: `project_file(path: Path) -> str` returning accepted projection digest
- Produces: `build_context_graph(at_time: Optional[datetime] = None) -> ContextGraph`
- Produces: `snapshot(label: str, description: str) -> Dict[str, Any]`

- [ ] **Step 1: Write failing end-to-end projection tests**

```python
from pathlib import Path

import pytest

from integrations.shadow_projection_v1.projector import ProjectionEngine

FIXTURES = Path(__file__).parent / "fixtures"


def test_two_sources_preserve_conflict_and_build_context_graph(tmp_path: Path):
    engine = ProjectionEngine(
        projection_path=tmp_path / "projection.json",
        provenance_path=tmp_path / "provenance.db",
        versions_path=tmp_path / "versions.db",
    )
    engine.project_file(FIXTURES / "source_a.json")
    engine.project_file(FIXTURES / "source_b_conflict.json")
    assert len(engine.store.conflicts()) == 1
    graph = engine.build_context_graph()
    assert graph.stats()["node_count"] == 3
    assert graph.stats()["edge_count"] == 2


def test_replay_has_identical_projection_digest(tmp_path: Path):
    kwargs = {
        "projection_path": tmp_path / "projection.json",
        "provenance_path": tmp_path / "provenance.db",
        "versions_path": tmp_path / "versions.db",
    }
    first = ProjectionEngine(**kwargs)
    digest_one = first.project_file(FIXTURES / "source_a.json")
    digest_two = first.project_file(FIXTURES / "source_a.json")
    assert digest_two == digest_one


def test_restart_reconstructs_identical_graph(tmp_path: Path):
    kwargs = {
        "projection_path": tmp_path / "projection.json",
        "provenance_path": tmp_path / "provenance.db",
        "versions_path": tmp_path / "versions.db",
    }
    first = ProjectionEngine(**kwargs)
    first.project_file(FIXTURES / "source_a.json")
    expected = first.store.digest()
    first.snapshot("accepted-1", "accepted state before restart")

    second = ProjectionEngine(**kwargs)
    assert second.store.digest() == expected
    assert second.versions.verify_checksum(second.versions.get_version("accepted-1")) is True


def test_malformed_source_never_changes_projection(tmp_path: Path):
    engine = ProjectionEngine(
        projection_path=tmp_path / "projection.json",
        provenance_path=tmp_path / "provenance.db",
        versions_path=tmp_path / "versions.db",
    )
    before = engine.store.digest()
    with pytest.raises(Exception):
        engine.project_file(FIXTURES / "malformed_source.json")
    assert engine.store.digest() == before
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_projector_restart.py -v
```

Expected: import failure for `ProjectionEngine`.

- [ ] **Step 3: Implement source capture and deterministic assertion identity**

For every file:

1. Read raw bytes.
2. Compute `content_digest = sha256_hex(raw_bytes)` before semantic normalization.
3. Parse `SourceEnvelope`.
4. Build `source_uri = stable_uri("source", envelope.source_id)`.
5. Build `evidence_uri = stable_uri("evidence/sha256", content_digest)`.
6. Persist `EvidenceRecord` through `PersistentProvenance.record_evidence()`.
7. For each source record, build `canonical_uri = stable_uri("resource", record.canonical_key)`.
8. For each assertion, derive `assertion_uri` from SHA-256 of canonical subject, predicate, JSON value, and evidence URI so identical replay is idempotent and conflicting values remain distinct.
9. Stage resource/assertion changes in memory.
10. Validate the staged full graph through SHACL.
11. Only after `conforms=True`, persist staged projection and assertion provenance.

Use a temporary `ProjectionStore` copy/staging representation so validation failure does not modify the accepted JSON projection.

- [ ] **Step 4: Implement ContextGraph reconstruction using v0.6.5 public calls**

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

Snapshot accepted graph only:

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

- [ ] **Step 1: Write failing read/authority tests**

```python
from pathlib import Path

from integrations.shadow_projection_v1.gateway import ReadGateway
from integrations.shadow_projection_v1.projector import ProjectionEngine


def test_gateway_exposes_only_read_methods(tmp_path: Path):
    engine = ProjectionEngine(
        projection_path=tmp_path / "projection.json",
        provenance_path=tmp_path / "provenance.db",
        versions_path=tmp_path / "versions.db",
    )
    gateway = ReadGateway(engine)
    public = {name for name in dir(gateway) if not name.startswith("_")}
    forbidden = {"promote", "retract", "purge", "resolve_conflict", "add_assertion"}
    assert public.isdisjoint(forbidden)


def test_explain_returns_assertions_and_evidence(projected_gateway):
    result = projected_gateway.explain(
        "https://id.example.invalid/resource/workstream%3Aws-1"
    )
    assert result["canonical_uri"].endswith("workstream%3Aws-1")
    assert len(result["assertions"]) >= 1
    assert all(item["evidence_uri"] for item in result["assertions"])
```

Create `projected_gateway` locally in the test file by projecting `source_a.json`; do not rely on mutable global fixtures.

- [ ] **Step 2: Run tests and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
```

Expected: import failure for gateway module.

- [ ] **Step 3: Implement the explicit read surface**

`ReadGateway` is a plain class with only the six public methods listed above. It receives a `ProjectionEngine` but never exposes `engine.store` or any write-capable object from return values.

`explain()` must return:

```python
{
    "canonical_uri": canonical_uri,
    "resource": resource_dict,
    "assertions": assertion_dicts,
    "conflicts": matching_conflicts,
    "provenance": {
        assertion_uri: self.engine.provenance.manager.get_lineage(assertion_uri)
        for assertion_uri in assertion_uris
    },
}
```

- [ ] **Step 4: Run tests and confirm GREEN**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
```

Expected: PASS.

- [ ] **Step 5: Export only approved public objects**

`__init__.py`:

```python
from .gateway import ReadGateway
from .projector import ProjectionEngine

__all__ = ["ProjectionEngine", "ReadGateway"]
```

Do not export `ProjectionStore` or provenance manager wrappers from package root.

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

**Interfaces:**
- Produces: `run_acceptance(work_dir: Path, corpus_paths: List[Path]) -> ProjectionReceipt`
- Produces: `write_receipt(receipt: ProjectionReceipt, path: Path) -> None`

- [ ] **Step 1: Write the failing acceptance test**

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
    assert receipt.semantica_version_or_sha == "v0.6.5@5b319560fb0b8403644b70bc592864418cdcc740"
    assert receipt.projection_contract_version == "shadow-projection/v1"
    assert receipt.replay_run_1_digest == receipt.replay_run_2_digest
    assert receipt.provenance_integrity_status == "PASS"
    assert receipt.validation_status == "PASS"
    assert set(receipt.acceptance_gates) == {"G%d" % number for number in range(1, 13)}
    assert all(value == "PASS" for value in receipt.acceptance_gates.values())
```

- [ ] **Step 2: Run acceptance test and confirm RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_acceptance.py -v
```

Expected: import failure for verification module.

- [ ] **Step 3: Implement explicit gate checks**

`run_acceptance()` must execute each gate independently and record `PASS` or raise an assertion/error that causes the receipt to report `FAIL`. Do not mark skipped work as PASS.

Required checks:

```text
G1  same stable key -> same canonical URI
G2  fresh replay run 1 digest == fresh replay run 2 digest; no duplicate counts
G3  every accepted assertion has non-empty persisted lineage to evidence
G4  ProvenanceManager.verify_chain()["valid"] is True after new manager instance
G5  close valid_until; historical query returns assertion; later current query omits it
G6  source A + source B produce two assertions and one explicit conflict
G7  malformed source raises validation and accepted digest is unchanged
G8  new ProjectionEngine instance reconstructs same accepted digest
G9  write resource/assertion -> new ProjectionStore instance reads exact same records
G10 ReadGateway exposes no promote/retract/purge/resolve_conflict/add_assertion methods
G11 attempted getattr on forbidden mutation names raises AttributeError and no public Explorer/MCP server is started
G12 TemporalVersionManager snapshot checksum verifies and a fresh engine reproduces snapshot metadata digest from source corpus
```

For G2, use separate directories `replay-1/` and `replay-2/`; do not compare two calls against the same mutable store.

For G7, record the projection digest before attempting malformed input and assert it is identical afterward.

For G12, compare the stored snapshot metadata `projection_digest` with the reconstructed projection digest; do not invoke automatic rollback.

- [ ] **Step 4: Implement deterministic corpus and projection digest fields**

`source_corpus_digest` is SHA-256 over a sorted list of `{path_name, raw_file_sha256}` records, not filesystem paths.

`canonical_projection_digest` is `ProjectionStore.digest()` after projecting both accepted fixtures.

`backend_identifier` is exactly:

```text
json-projection+sqlite-provenance+sqlite-versions
```

`created_at` may be the current UTC time because it is receipt metadata and is excluded from replay digest comparison.

- [ ] **Step 5: Implement receipt writing**

```python
import json


def write_receipt(receipt, path):
    payload = receipt.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
```

- [ ] **Step 6: Run the complete V1 suite**

```bash
pytest tests/integrations/shadow_projection_v1 -v
```

Expected: all tests PASS; zero xfails/skips in this directory.

- [ ] **Step 7: Run focused Semantica regression tests for touched public contracts**

```bash
pytest tests/provenance/test_manager.py tests/context/test_context.py tests/test_graph_store_methods.py -q
```

Expected: PASS. If a pre-existing baseline failure occurs, prove it against clean v0.6.5 before classifying it as unrelated.

- [ ] **Step 8: Generate a committed verification receipt in a clean temporary directory**

Run:

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
    write_receipt(receipt, Path("docs/superpowers/receipts/semantica-shadow-projection-v1.json"))
PY
```

Then verify:

```bash
python -m json.tool docs/superpowers/receipts/semantica-shadow-projection-v1.json >/dev/null

git diff --check
```

Expected: JSON parses, `git diff --check` exits 0, receipt contains G1-G12 all PASS.

- [ ] **Step 9: Commit the acceptance proof**

```bash
git add integrations/shadow_projection_v1/verification.py tests/integrations/shadow_projection_v1/test_acceptance.py docs/superpowers/receipts/semantica-shadow-projection-v1.json

git commit -m "test: prove Semantica shadow projection acceptance"
```

---

## Final Verification Before PR

Run all commands from the implementation branch rooted at `5b319560fb0b8403644b70bc592864418cdcc740`:

```bash
git status --short
pytest tests/integrations/shadow_projection_v1 -v
pytest tests/provenance/test_manager.py tests/context/test_context.py tests/test_graph_store_methods.py -q
python -m json.tool docs/superpowers/receipts/semantica-shadow-projection-v1.json >/dev/null
git diff --check
git log --oneline --decorate -8
```

Required state:

```text
working tree: clean
V1 acceptance tests: PASS
focused upstream regressions: PASS or separately proven pre-existing
receipt G1-G12: PASS
implementation ancestry: v0.6.5 commit 5b319560fb0b8403644b70bc592864418cdcc740
fork main: unchanged
external deployments/resources: none
```

Open a draft PR in `ntwrkfx/semantica` only after the final verification evidence exists. The PR base should remain a dedicated v0.6.5-derived integration branch unless fork `main` is explicitly synchronized and compatibility-reverified; do not silently retarget onto the stale current fork `main`.
