from pathlib import Path
from typing import Any, Dict

from semantica.provenance import ProvenanceManager

from .models import AssertionRecord, EvidenceRecord


class PersistentProvenance:
    def __init__(self, path):
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
            metadata=evidence.model_dump(mode="json"),
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
            valid_from=assertion.valid_from.isoformat() if assertion.valid_from else None,
            valid_until=assertion.valid_until.isoformat() if assertion.valid_until else None,
            metadata=assertion.model_dump(mode="json"),
        )
        if entry is None:
            raise RuntimeError("persistent assertion provenance write failed")

    def verify(self) -> Dict[str, Any]:
        return self.manager.verify_chain()
