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
