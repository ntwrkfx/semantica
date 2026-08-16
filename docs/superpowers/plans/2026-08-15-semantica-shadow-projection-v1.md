# Semantica Shadow Projection V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-first Semantica shadow projection that preserves provenance, conflicting assertions, temporal validity, validation, restart reproducibility, and explicit authority separation on Semantica v0.6.5.

**Architecture:** Implement an isolated package under `integrations/shadow_projection_v1/`; do not change Semantica core. Hash raw evidence before semantic parsing, persist source provenance with `ProvenanceManager`, stage deterministic assertions in a canonical JSON projection, validate the staged graph with committed SHACL, persist assertion provenance before atomically committing accepted state, reconstruct `ContextGraph` only as a query/working view, and emit a G1-G12 verification receipt.

**Tech Stack:** Python >=3.8, Semantica v0.6.5 commit `5b319560fb0b8403644b70bc592864418cdcc740`, Pydantic v2, rdflib, pyshacl through `.[shacl]`, SQLite provenance, SQLite temporal snapshots, pytest.

## Global Constraints

- Implementation branch: `feat/semantica-shadow-projection-v1`, created **directly** from `5b319560fb0b8403644b70bc592864418cdcc740`.
- `design/semantica-shadow-projection-v1` is documentation-only and MUST NOT be the code ancestor.
- Copy the approved design and this plan onto the implementation branch before code changes.
- Do not modify fork `main`.
- Do not modify Semantica core. Stop `BLOCKED` if G1-G12 cannot be satisfied through v0.6.5 public APIs.
- `ContextGraph` is a working/query graph, not durable authority.
- v0.6.5 predates native `ContextGraph.retract_node()`/`retract_edge()`; V1 retraction closes `valid_until` in our durable store.
- Persistence: deterministic canonical JSON + `ProvenanceManager(storage_path=...)` + `TemporalVersionManager(storage_path=...)`.
- No external graph/vector service, Explorer deployment, MCP server, provider mutation, or production erasure workflow.
- Normative constraints are committed SHACL. Generated ontology/shapes are non-normative.
- There is no V1 `CanonicalFact` creation or promotion API.
- Acceptance/mutation tests assert read-after-write postconditions, not truthy return values.
- Accepted projection MUST never be committed before required assertion provenance persists successfully. Extra provenance for an admission-passed but commit-failed assertion is preferable to accepted state lacking provenance.
- Install test environment with `python -m pip install -e ".[dev,shacl]"`.

## File Map

```text
integrations/shadow_projection_v1/
  __init__.py        public root: ReadGateway only
  identity.py        canonical JSON, SHA-256, stable HTTPS identifiers
  models.py          strict Pydantic source/projected/receipt models
  provenance.py      persistent Semantica provenance wrapper
  store.py           canonical JSON state, staging, conflicts, temporal filtering
  validation.py      property graph -> RDF + SHACL validation
  projector.py       ordered ingestion/admission/ContextGraph reconstruction
  gateway.py         read-only query/explain interface
  verification.py    G1-G12 runner and receipt writer
  shapes.ttl         normative Assertion shape

tests/integrations/shadow_projection_v1/
  fixtures/source_a.json
  fixtures/source_b_conflict.json
  fixtures/malformed_source.json
  test_identity_models.py
  test_provenance.py
  test_store_projection.py
  test_validation.py
  test_projector_restart.py
  test_gateway_authority.py
  test_acceptance.py
```

---

### Task 1: Identity, strict models, and committed corpus

**Files:** create `identity.py`, `models.py`, package/test `__init__.py`, three fixture files, `test_identity_models.py`.

**Produces:**

```python
canonical_json_bytes(value: Any) -> bytes
sha256_hex(value: Any) -> str
stable_uri(kind: str, stable_key: str, namespace: str = DEFAULT_NAMESPACE) -> str
evidence_uri_from_digest(content_digest: str, namespace: str = DEFAULT_NAMESPACE) -> str
```

Models: `SourceEnvelope`, `SourceRecord`, `RawAssertion`, `EvidenceRecord`, `AssertionRecord`, `DecisionRecord`, `ProjectionReceipt`.

- [ ] **Step 1: Commit the fixed corpus**

`source_a.json`:

```json
{"source_id":"ops-state-a","source_version":"commit-a1","observed_at":"2026-08-15T20:00:00Z","records":[{"canonical_key":"workstream:ws-1","resource_type":"Workstream","assertions":[{"predicate":"status","value":"COMPLETE","confidence":1.0,"authority_class":"authoritative_source","valid_from":"2026-08-15T20:00:00Z","valid_until":null}]}]}
```

`source_b_conflict.json`:

```json
{"source_id":"provider-observation-b","source_version":"snapshot-b1","observed_at":"2026-08-15T20:05:00Z","records":[{"canonical_key":"workstream:ws-1","resource_type":"Workstream","assertions":[{"predicate":"status","value":"BLOCKED","confidence":0.95,"authority_class":"provider_observation","valid_from":"2026-08-15T20:05:00Z","valid_until":null}]}]}
```

`malformed_source.json` intentionally omits `predicate`:

```json
{"source_id":"bad-source","source_version":"bad-1","observed_at":"2026-08-15T20:10:00Z","records":[{"canonical_key":"workstream:ws-bad","resource_type":"Workstream","assertions":[{"value":"COMPLETE","confidence":1.0,"authority_class":"authoritative_source"}]}]}
```

- [ ] **Step 2: Write failing model/identity tests**

```python
from pathlib import Path
import pytest
from pydantic import ValidationError
from integrations.shadow_projection_v1.identity import evidence_uri_from_digest, sha256_hex, stable_uri
from integrations.shadow_projection_v1.models import SourceEnvelope

FIXTURES = Path(__file__).parent / "fixtures"


def test_identity_is_stable():
    assert stable_uri("resource", "workstream:ws-1") == "https://id.example.invalid/resource/workstream%3Aws-1"
    assert sha256_hex({"b": 2, "a": 1}) == sha256_hex({"a": 1, "b": 2})
    assert evidence_uri_from_digest("abc123") == "https://id.example.invalid/evidence/sha256/abc123"


def test_bad_source_is_rejected():
    with pytest.raises(ValidationError):
        SourceEnvelope.model_validate_json((FIXTURES / "malformed_source.json").read_text())
```

- [ ] **Step 3: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_identity_models.py -v
```

- [ ] **Step 4: Implement identity functions**

```python
import hashlib, json
from typing import Any
from urllib.parse import quote

DEFAULT_NAMESPACE = "https://id.example.invalid"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def stable_uri(kind: str, stable_key: str, namespace: str = DEFAULT_NAMESPACE) -> str:
    if not kind or not stable_key:
        raise ValueError("kind and stable_key are required")
    return "%s/%s/%s" % (namespace.rstrip("/"), quote(kind, safe=""), quote(stable_key, safe=""))


def evidence_uri_from_digest(content_digest: str, namespace: str = DEFAULT_NAMESPACE) -> str:
    if not content_digest:
        raise ValueError("content_digest is required")
    return "%s/evidence/sha256/%s" % (namespace.rstrip("/"), quote(content_digest, safe=""))
```

- [ ] **Step 5: Implement strict models**

Use `ConfigDict(extra="forbid")`. `RawAssertion` and `AssertionRecord` validate `valid_until >= valid_from`. Exact projected fields:

```python
class EvidenceRecord(BaseModel):
    evidence_uri: str
    source_uri: str
    source_id: str
    source_version: str
    content_digest: str
    observed_at: datetime

class AssertionRecord(BaseModel):
    record_type: Literal["Assertion"] = "Assertion"
    assertion_uri: str
    canonical_uri: str
    predicate: str
    value: Any
    evidence_uri: str
    observed_at: datetime
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    confidence: float = Field(ge=0.0, le=1.0)
    authority_class: AuthorityClass

class DecisionRecord(BaseModel):
    record_type: Literal["Decision"] = "Decision"
    decision_uri: str
    decision_maker: str
    scenario: str
    reasoning: str
    outcome: str
    confidence: float = Field(ge=0.0, le=1.0)
    observed_at: datetime

class ProjectionReceipt(BaseModel):
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

`SourceEnvelope` requires non-empty `source_id`, `source_version`, `records`; `SourceRecord` requires non-empty `canonical_key`, `resource_type`, `assertions`; `RawAssertion` requires `predicate`, JSON value, bounded confidence and `authority_class`.

- [ ] **Step 6: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_identity_models.py -v
git add integrations/shadow_projection_v1 tests/integrations/shadow_projection_v1
git commit -m "feat: add deterministic shadow projection contracts"
```

---

### Task 2: Persistent, idempotent provenance

**Files:** create `provenance.py`, `test_provenance.py`.

**Produces:** `PersistentProvenance(path)`, `.record_evidence()`, `.record_assertion()`, `.lineage()`, `.verify()`.

- [ ] **Step 1: Write failing restart/idempotency tests**

```python
def test_provenance_survives_restart(tmp_path):
    db = tmp_path / "provenance.db"
    first = PersistentProvenance(db)
    first.record_evidence(EVIDENCE)
    second = PersistentProvenance(db)
    assert second.lineage(EVIDENCE.evidence_uri)["integrity_verified"] is True
    assert second.verify()["valid"] is True


def test_same_evidence_is_idempotent(tmp_path):
    prov = PersistentProvenance(tmp_path / "provenance.db")
    prov.record_evidence(EVIDENCE)
    before = prov.verify()["total_entries"]
    prov.record_evidence(EVIDENCE)
    assert prov.verify()["total_entries"] == before
```

`EVIDENCE` is an explicit `EvidenceRecord` using `https://id.example.invalid/evidence/sha256/abc123` and observed time `2026-08-15T20:00:00Z`.

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_provenance.py -v
```

- [ ] **Step 3: Implement wrapper using Semantica public manager methods**

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

### Task 3: Canonical projection store, staging, conflicts, and temporal filtering

**Files:** create `store.py`, `test_store_projection.py`.

**Produces:** `ProjectionStore(path=None)`, `.clone()`, `.commit_from()`, `.upsert_resource()`, `.add_assertion()`, `.retract_assertion()`, `.active_assertions()`, `.conflicts()`, `.graph_dict(at_time=None)`, `.digest()`.

**Contract:** `graph_dict(None)` returns full accepted history. `graph_dict(explicit_datetime)` filters assertions by validity at that instant. `digest()` always hashes full history, never wall-clock-dependent state.

- [ ] **Step 1: Write RED tests** proving: two conflicting status values remain; retraction is visible before 20:10Z and absent after; restarting from JSON yields the same digest; re-reading after every mutation returns the exact stored model.

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
```

- [ ] **Step 3: Implement deterministic state**

Persist exact top-level shape:

```json
{"contract":"shadow-projection/v1","resources":[],"assertions":[]}
```

In memory:

```python
self.resources = {}   # canonical_uri -> {canonical_uri, resource_type}
self.assertions = {}  # assertion_uri -> AssertionRecord
```

Sort resources by `canonical_uri`, assertions by `assertion_uri`; `_flush()` writes `<path>.tmp` then `os.replace`. `clone()` deep-copies into `ProjectionStore(None)`. `commit_from()` deep-copies staged state then performs one atomic `_flush()`.

`add_assertion()` is idempotent for byte-equivalent model dumps and raises `ValueError("assertion identity collision")` if the same URI maps to different content.

- [ ] **Step 4: Implement conflict/temporal rules**

```python
active = (
    (a.valid_from is None or a.valid_from <= at_time)
    and (a.valid_until is None or at_time < a.valid_until)
)
```

Conflict key is `(canonical_uri, predicate)`; emit a conflict only when canonical JSON values differ. `retract_assertion()` rejects unknown URI or closure before `valid_from`, updates `valid_until`, flushes, and tests reopen the store to verify.

- [ ] **Step 5: Implement property graph projection**

Each resource is one node. Each assertion is one `Assertion` node with `AssertionRecord.model_dump(mode="json")` metadata plus one deterministic `ABOUT` edge to its resource. Sort nodes by `id`; edges by `(source,type,target,id)`.

- [ ] **Step 6: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_store_projection.py -v
git add integrations/shadow_projection_v1/store.py tests/integrations/shadow_projection_v1/test_store_projection.py
git commit -m "feat: add deterministic temporal projection store"
```

---

### Task 4: Normative SHACL admission

**Files:** create `shapes.ttl`, `validation.py`, `test_validation.py`.

- [ ] **Step 1: Commit this shape**

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

- [ ] **Step 2: Write RED tests** with an explicit two-node/one-edge valid graph and a deep-copied graph where `evidence_uri` is removed. Require valid graph `conforms=True`; broken graph `conforms=False` and report contains `evidence`.

- [ ] **Step 3: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_validation.py -v
```

- [ ] **Step 4: Implement validator**

```python
@dataclass(frozen=True)
class ValidationResult:
    conforms: bool
    report_text: str


def graph_to_rdf(graph_dict):
    g = Graph()
    for node in graph_dict.get("nodes", []):
        if node.get("type") != "Assertion":
            continue
        m = node.get("metadata", {})
        u = URIRef(node["id"])
        g.add((u, RDF.type, SQN.Assertion))
        if m.get("canonical_uri"):
            g.add((u, SQN.subject, URIRef(m["canonical_uri"])))
        if m.get("predicate"):
            g.add((u, SQN.predicate, Literal(m["predicate"])))
        if "value" in m:
            g.add((u, SQN.value, Literal(m["value"])))
        if m.get("evidence_uri"):
            g.add((u, SQN.evidence, URIRef(m["evidence_uri"])))
    return g


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

**Files:** create `projector.py`, `test_projector_restart.py`.

**Produces:** `ProjectionEngine(projection_path, provenance_path, versions_path)`, `.project_file()`, `.build_context_graph()`, `.snapshot()`.

- [ ] **Step 1: Write RED end-to-end tests** proving:
  1. source A + B => 3 graph nodes, 2 `ABOUT` edges, 1 explicit conflict;
  2. replay of source A leaves projection digest unchanged;
  3. process restart preserves digest and snapshot checksum;
  4. malformed source records one evidence provenance entry but leaves accepted projection digest unchanged.

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_projector_restart.py -v
```

- [ ] **Step 3: Implement exact ingestion order**

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
```

For each record, `canonical_uri = stable_uri("resource", record.canonical_key)`. Assertion URI is:

```python
stable_uri("assertion", sha256_hex({
    "canonical_uri": canonical_uri,
    "predicate": raw_assertion.predicate,
    "value": raw_assertion.value,
    "evidence_uri": evidence_uri,
}))
```

Add `AssertionRecord`s only to `staged`. Validate `staged.graph_dict()`.

**Fail-closed commit ordering after SHACL PASS:**

```python
for assertion in newly_staged_assertions:
    self.provenance.record_assertion(assertion)
# only after every required provenance call succeeds:
self.store.commit_from(staged)
return self.store.digest()
```

If assertion provenance fails, accepted JSON remains unchanged. If atomic JSON commit fails after provenance succeeds, the extra provenance describes an admission-passed attempted projection but no unsupported claim of accepted state is created.

- [ ] **Step 4: Reconstruct `ContextGraph` through v0.6.5 public calls**

```python
def build_context_graph(self, at_time=None):
    payload = self.store.graph_dict(at_time=at_time)
    graph = ContextGraph()
    for node in payload["nodes"]:
        metadata = dict(node.get("metadata", {}))
        graph.add_node(node["id"], node["type"], node.get("content") or node["id"],
                       valid_from=node.get("valid_from"), valid_until=node.get("valid_until"), **metadata)
    for edge in payload["edges"]:
        graph.add_edge(edge["source"], edge["target"], edge["type"],
                       weight=edge.get("weight", 1.0), id=edge["id"])
    return graph
```

- [ ] **Step 5: Persist accepted-state snapshots**

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

### Task 6: Read-only gateway and authority boundary

**Files:** create `gateway.py`, `test_gateway_authority.py`; modify package `__init__.py`.

**Public methods:** `entity_get`, `assertion_query`, `relationship_query`, `provenance_trace`, `explain`, `graph_summary`.

- [ ] **Step 1: Write RED tests**

```python
def test_root_exports_only_gateway():
    assert public_package.__all__ == ["ReadGateway"]


def test_gateway_has_no_mutators(gateway):
    for name in ("promote", "retract", "purge", "resolve_conflict", "add_assertion"):
        with pytest.raises(AttributeError):
            getattr(gateway, name)
```

Also project source A and require `explain(resource_uri)` to return one assertion, its evidence URI, and non-empty assertion provenance.

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
```

- [ ] **Step 3: Implement gateway with private engine**

```python
class ReadGateway:
    def __init__(self, engine):
        self._engine = engine
```

No public method/property returns `ProjectionEngine`, `ProjectionStore`, `PersistentProvenance`, or `TemporalVersionManager`. `explain()` returns:

```python
{
  "canonical_uri": canonical_uri,
  "resource": resource_dict,
  "assertions": assertion_dicts,
  "conflicts": matching_conflicts,
  "provenance": {uri: self._engine.provenance.lineage(uri) for uri in assertion_uris},
}
```

- [ ] **Step 4: Root export is read-only**

```python
from .gateway import ReadGateway
__all__ = ["ReadGateway"]
```

Internal tests import `ProjectionEngine` from `.projector`, never package root.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest tests/integrations/shadow_projection_v1/test_gateway_authority.py -v
git add integrations/shadow_projection_v1/gateway.py integrations/shadow_projection_v1/__init__.py tests/integrations/shadow_projection_v1/test_gateway_authority.py
git commit -m "feat: expose read-only shadow projection gateway"
```

---

### Task 7: G1-G12 verifier and receipt

**Files:** create `verification.py`, `test_acceptance.py`; generate `docs/superpowers/receipts/semantica-shadow-projection-v1.json`.

- [ ] **Step 1: Write RED acceptance test**

```python
def test_all_gates_pass(tmp_path):
    receipt = run_acceptance(tmp_path, [SOURCE_A, SOURCE_B])
    assert receipt.semantica_version_or_sha == "v0.6.5@5b319560fb0b8403644b70bc592864418cdcc740"
    assert receipt.replay_run_1_digest == receipt.replay_run_2_digest
    assert set(receipt.acceptance_gates) == {"G%d" % n for n in range(1, 13)}
    assert all(v == "PASS" for v in receipt.acceptance_gates.values())
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/integrations/shadow_projection_v1/test_acceptance.py -v
```

- [ ] **Step 3: Implement one fail-closed helper per gate**

```text
G1  same stable key => exact same HTTPS URI
G2  same corpus in two fresh directories => identical digest and counts
G3  every accepted assertion lineage includes its evidence URI
G4  new PersistentProvenance instance => verify_chain().valid true
G5  explicit 20:05Z historical view contains retracted assertion; 20:11Z view omits it
G6  A+B => two status assertions and exactly one conflict
G7  malformed source raises ValidationError and accepted digest is unchanged
G8  new ProjectionEngine over same files => identical digest
G9  write then reopen ProjectionStore => exact resource/assertion model dumps
G10 gateway has none of promote/retract/purge/resolve_conflict/add_assertion
G11 package root exports only ReadGateway; verifier starts no Explorer/MCP/server process
G12 snapshot checksum verifies; clean source reconstruction matches snapshot metadata projection_digest
```

No skips, xfails, conditional PASS, or swallowed exceptions.

- [ ] **Step 4: Implement gate runner**

```python
def run_gate(gates, code, fn):
    fn()
    gates[code] = "PASS"
```

Call G1 through G12 in order. Propagate failures; do not write a successful receipt when any gate raises. G2 uses `replay-1/` and `replay-2/`, never the same mutable store.

- [ ] **Step 5: Compute receipt fields deterministically**

`source_corpus_digest = sha256_hex(sorted([{"name": p.name, "sha256": sha256_hex(p.read_bytes())} ...], key=lambda x: x["name"]))`.

Backend identifier exactly:

```text
json-projection+sqlite-provenance+sqlite-versions
```

`created_at` is UTC receipt metadata and excluded from replay equality.

- [ ] **Step 6: Write receipt**

```python
def write_receipt(receipt, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt.model_dump(mode="json"), sort_keys=True, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 7: Run full V1 and focused upstream tests**

```bash
pytest tests/integrations/shadow_projection_v1 -v
pytest tests/provenance/test_manager.py tests/context/test_context.py tests/test_graph_store_methods.py -q
```

Required: V1 suite has zero skips/xfails. Any upstream failure must be reproduced on clean v0.6.5 before being labeled pre-existing.

- [ ] **Step 8: Generate receipt and verify formatting**

```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from integrations.shadow_projection_v1.verification import run_acceptance, write_receipt
fixtures = Path("tests/integrations/shadow_projection_v1/fixtures")
with TemporaryDirectory() as tmp:
    receipt = run_acceptance(Path(tmp), [fixtures / "source_a.json", fixtures / "source_b_conflict.json"])
    write_receipt(receipt, Path("docs/superpowers/receipts/semantica-shadow-projection-v1.json"))
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

The implementation branch must prove its fork point, not merely contain v0.6.5 somewhere in history:

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
fork point with current upstream main: exactly v0.6.5 commit 5b319560...
working tree: clean
V1 tests: PASS, zero skips/xfails
focused upstream regressions: PASS or independently proven pre-existing
receipt: G1-G12 PASS
fork main: unchanged
external deployments/resources: none
```

Open a draft PR only after this evidence exists. Do not retarget or merge onto stale fork `main` without a separate synchronization decision and complete compatibility rerun.
