import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from pydantic import ValidationError

import integrations.shadow_projection_v1 as public_package
from .gateway import ReadGateway
from .identity import sha256_hex, stable_uri
from .models import AssertionRecord, ProjectionReceipt
from .projector import ProjectionEngine
from .provenance import PersistentProvenance
from .store import ProjectionStore

SEMANTICA_BASELINE = "v0.6.5@5b319560fb0b8403644b70bc592864418cdcc740"
CONTRACT = "shadow-projection/v1"
BACKEND = "json-projection+sqlite-provenance+sqlite-versions"
FORBIDDEN_MUTATORS = (
    "promote",
    "retract",
    "purge",
    "resolve_conflict",
    "add_assertion",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _engine(root: Path) -> ProjectionEngine:
    root.mkdir(parents=True, exist_ok=True)
    return ProjectionEngine(
        projection_path=root / "projection.json",
        provenance_path=root / "provenance.db",
        versions_path=root / "versions.db",
    )


def _project_corpus(root: Path, corpus_paths: Iterable[Path]) -> ProjectionEngine:
    item = _engine(root)
    for path in corpus_paths:
        item.project_file(path)
    return item


def _source_a(corpus_paths: Iterable[Path]) -> Path:
    for path in corpus_paths:
        if path.name == "source_a.json":
            return path
    raise AssertionError("source_a.json missing from acceptance corpus")


def g1_identity() -> None:
    left = stable_uri("resource", "workstream:ws-1")
    right = stable_uri("resource", "workstream:ws-1")
    _require(left == right, "canonical identity is not deterministic")


def g2_replay(work_dir: Path, corpus_paths: List[Path]) -> Tuple[str, str]:
    first = _project_corpus(work_dir / "g2-replay-1", corpus_paths)
    second = _project_corpus(work_dir / "g2-replay-2", corpus_paths)
    first_digest = first.store.digest()
    second_digest = second.store.digest()
    _require(first_digest == second_digest, "replay digests differ")
    _require(
        len(first.store.resources) == len(second.store.resources),
        "replay resource counts differ",
    )
    _require(
        len(first.store.assertions) == len(second.store.assertions),
        "replay assertion counts differ",
    )
    return first_digest, second_digest


def g3_provenance(work_dir: Path, corpus_paths: List[Path]) -> None:
    item = _project_corpus(work_dir / "g3-provenance", corpus_paths)
    for assertion in item.store.assertions.values():
        lineage = item.provenance.lineage(assertion.assertion_uri)
        _require(bool(lineage), "accepted assertion has no lineage")
        ids = {
            entry.get("entity_id")
            for entry in lineage.get("lineage_chain", [])
            if isinstance(entry, dict)
        }
        _require(
            assertion.evidence_uri in ids,
            "accepted assertion lineage does not contain its evidence URI",
        )


def g4_integrity(work_dir: Path, corpus_paths: List[Path]) -> None:
    root = work_dir / "g4-integrity"
    item = _project_corpus(root, corpus_paths)
    reopened = PersistentProvenance(item.provenance_path)
    result = reopened.verify()
    _require(result.get("valid") is True, "provenance chain failed after restart")


def g5_temporal(work_dir: Path) -> None:
    path = work_dir / "g5-temporal" / "projection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    resource = stable_uri("resource", "workstream:ws-temporal")
    assertion_uri = stable_uri("assertion", "temporal-status")
    store = ProjectionStore(path)
    store.upsert_resource(resource, "Workstream")
    store.add_assertion(
        AssertionRecord(
            assertion_uri=assertion_uri,
            canonical_uri=resource,
            predicate="status",
            value="COMPLETE",
            evidence_uri=stable_uri("evidence", "temporal-evidence"),
            observed_at="2026-08-15T20:00:00Z",
            valid_from="2026-08-15T20:00:00Z",
            valid_until=None,
            confidence=1.0,
            authority_class="authoritative_source",
        )
    )
    store.retract_assertion(
        assertion_uri, datetime(2026, 8, 15, 20, 10, tzinfo=timezone.utc)
    )
    reopened = ProjectionStore(path)
    before = reopened.active_assertions(
        datetime(2026, 8, 15, 20, 5, tzinfo=timezone.utc)
    )
    after = reopened.active_assertions(
        datetime(2026, 8, 15, 20, 11, tzinfo=timezone.utc)
    )
    _require(len(before) == 1, "historical assertion disappeared after retraction")
    _require(len(after) == 0, "retracted assertion remains active")


def g6_conflict(work_dir: Path, corpus_paths: List[Path]) -> None:
    item = _project_corpus(work_dir / "g6-conflict", corpus_paths)
    status = [a for a in item.store.assertions.values() if a.predicate == "status"]
    _require(len(status) == 2, "expected exactly two status assertions")
    conflicts = item.store.conflicts()
    _require(len(conflicts) == 1, "expected exactly one preserved conflict")


def g7_validation(work_dir: Path, corpus_paths: List[Path]) -> None:
    root = work_dir / "g7-validation"
    item = _engine(root)
    item.project_file(_source_a(corpus_paths))
    before = item.store.digest()
    malformed = _source_a(corpus_paths).with_name("malformed_source.json")
    try:
        item.project_file(malformed)
    except ValidationError:
        pass
    else:
        raise AssertionError("malformed source was admitted")
    _require(item.store.digest() == before, "invalid source changed accepted state")


def g8_restart(work_dir: Path, corpus_paths: List[Path]) -> None:
    root = work_dir / "g8-restart"
    first = _project_corpus(root, corpus_paths)
    expected = first.store.digest()
    second = _engine(root)
    _require(second.store.digest() == expected, "restart changed projection digest")


def g9_store_contract(work_dir: Path) -> None:
    path = work_dir / "g9-store" / "projection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    resource = stable_uri("resource", "workstream:ws-store")
    assertion = AssertionRecord(
        assertion_uri=stable_uri("assertion", "store-contract"),
        canonical_uri=resource,
        predicate="status",
        value="COMPLETE",
        evidence_uri=stable_uri("evidence", "store-contract"),
        observed_at="2026-08-15T20:00:00Z",
        valid_from="2026-08-15T20:00:00Z",
        valid_until=None,
        confidence=1.0,
        authority_class="authoritative_source",
    )
    first = ProjectionStore(path)
    first.upsert_resource(resource, "Workstream")
    first.add_assertion(assertion)
    resource_expected = dict(first.resources[resource])
    assertion_expected = assertion.model_dump(mode="json")
    reopened = ProjectionStore(path)
    _require(reopened.resources[resource] == resource_expected, "resource readback differs")
    _require(
        reopened.assertions[assertion.assertion_uri].model_dump(mode="json")
        == assertion_expected,
        "assertion readback differs",
    )


def build_gateway(root: Path, corpus_paths: List[Path]) -> ReadGateway:
    return ReadGateway(_project_corpus(root, [_source_a(corpus_paths)]))


def g10_authority(item: ReadGateway) -> None:
    for name in FORBIDDEN_MUTATORS:
        _require(not hasattr(item, name), "read gateway exposes mutator %s" % name)


def g11_security_surface(item: ReadGateway) -> None:
    _require(public_package.__all__ == ["ReadGateway"], "package root export widened")
    g10_authority(item)
    _require("semantica.server" not in sys.modules, "server entry point imported")
    _require("semantica.mcp_server" not in sys.modules, "MCP server entry point imported")


def g12_recovery(work_dir: Path, corpus_paths: List[Path]) -> None:
    root = work_dir / "g12-snapshot"
    first = _project_corpus(root, corpus_paths)
    expected = first.store.digest()
    snapshot = first.snapshot("accepted-proof", "shadow projection recovery proof")
    _require(first.versions.verify_checksum(snapshot) is True, "snapshot checksum failed")
    _require(
        snapshot["metadata"]["projection_digest"] == expected,
        "snapshot projection digest mismatch",
    )
    rebuilt = _project_corpus(work_dir / "g12-rebuilt", corpus_paths)
    _require(rebuilt.store.digest() == expected, "source reconstruction differs from snapshot")


def run_gate(gates: Dict[str, str], code: str, function: Callable):
    result = function()
    gates[code] = "PASS"
    return result


def run_acceptance(work_dir, corpus_paths) -> ProjectionReceipt:
    work_dir = Path(work_dir)
    corpus_paths = [Path(path) for path in corpus_paths]
    gates: Dict[str, str] = {}

    run_gate(gates, "G1", g1_identity)
    replay_1, replay_2 = run_gate(
        gates, "G2", lambda: g2_replay(work_dir, corpus_paths)
    )
    run_gate(gates, "G3", lambda: g3_provenance(work_dir, corpus_paths))
    run_gate(gates, "G4", lambda: g4_integrity(work_dir, corpus_paths))
    run_gate(gates, "G5", lambda: g5_temporal(work_dir))
    run_gate(gates, "G6", lambda: g6_conflict(work_dir, corpus_paths))
    run_gate(gates, "G7", lambda: g7_validation(work_dir, corpus_paths))
    run_gate(gates, "G8", lambda: g8_restart(work_dir, corpus_paths))
    run_gate(gates, "G9", lambda: g9_store_contract(work_dir))
    run_gate(
        gates,
        "G10",
        lambda: g10_authority(build_gateway(work_dir / "g10", corpus_paths)),
    )
    run_gate(
        gates,
        "G11",
        lambda: g11_security_surface(build_gateway(work_dir / "g11", corpus_paths)),
    )
    run_gate(gates, "G12", lambda: g12_recovery(work_dir, corpus_paths))

    corpus_rows = [
        {"name": path.name, "sha256": sha256_hex(path.read_bytes())}
        for path in corpus_paths
    ]
    corpus_rows.sort(key=lambda row: row["name"])
    source_corpus_digest = sha256_hex(corpus_rows)

    return ProjectionReceipt(
        semantica_version_or_sha=SEMANTICA_BASELINE,
        projection_contract_version=CONTRACT,
        source_corpus_digest=source_corpus_digest,
        canonical_projection_digest=replay_1,
        provenance_integrity_status="PASS",
        validation_status="PASS",
        replay_run_1_digest=replay_1,
        replay_run_2_digest=replay_2,
        backend_identifier=BACKEND,
        acceptance_gates=gates,
        created_at=datetime.now(timezone.utc),
    )


def write_receipt(receipt: ProjectionReceipt, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
