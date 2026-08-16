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
