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
