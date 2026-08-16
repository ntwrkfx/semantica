import json
from pathlib import Path

from semantica.change_management import TemporalVersionManager
from semantica.context.context_graph import ContextGraph

from .identity import evidence_uri_from_digest, sha256_hex, stable_uri
from .models import AssertionRecord, EvidenceRecord, SourceEnvelope
from .provenance import PersistentProvenance
from .store import ProjectionStore
from .validation import validate_graph


class ProjectionEngine:
    def __init__(self, projection_path, provenance_path, versions_path):
        self.projection_path = Path(projection_path)
        self.provenance_path = Path(provenance_path)
        self.versions_path = Path(versions_path)
        self.store = ProjectionStore(self.projection_path)
        self.provenance = PersistentProvenance(self.provenance_path)
        self.versions = TemporalVersionManager(storage_path=str(self.versions_path))

    def project_file(self, path):
        path = Path(path)
        raw = path.read_bytes()
        digest = sha256_hex(raw)
        payload = json.loads(raw.decode("utf-8"))

        source_uri = stable_uri("source", payload["source_id"])
        evidence_uri = evidence_uri_from_digest(digest)
        self.provenance.record_evidence(
            EvidenceRecord(
                evidence_uri=evidence_uri,
                source_uri=source_uri,
                source_id=payload["source_id"],
                source_version=payload["source_version"],
                content_digest=digest,
                observed_at=payload["observed_at"],
            )
        )

        envelope = SourceEnvelope.model_validate(payload)
        staged = self.store.clone()
        new_assertions = []

        for record in envelope.records:
            canonical_uri = stable_uri("resource", record.canonical_key)
            staged.upsert_resource(canonical_uri, record.resource_type)
            for raw_assertion in record.assertions:
                assertion_uri = stable_uri(
                    "assertion",
                    sha256_hex(
                        {
                            "canonical_uri": canonical_uri,
                            "predicate": raw_assertion.predicate,
                            "value": raw_assertion.value,
                            "evidence_uri": evidence_uri,
                        }
                    ),
                )
                assertion = AssertionRecord(
                    assertion_uri=assertion_uri,
                    canonical_uri=canonical_uri,
                    predicate=raw_assertion.predicate,
                    value=raw_assertion.value,
                    evidence_uri=evidence_uri,
                    observed_at=envelope.observed_at,
                    valid_from=raw_assertion.valid_from,
                    valid_until=raw_assertion.valid_until,
                    confidence=raw_assertion.confidence,
                    authority_class=raw_assertion.authority_class,
                )
                staged.add_assertion(assertion)
                new_assertions.append(assertion)

        validation = validate_graph(staged.graph_dict())
        if not validation.conforms:
            raise ValueError("SHACL admission failed: %s" % validation.report_text)

        for assertion_item in new_assertions:
            self.provenance.record_assertion(assertion_item)

        self.store.commit_from(staged)
        return self.store.digest()

    def build_context_graph(self, at_time=None):
        payload = self.store.graph_dict(at_time=at_time)
        graph = ContextGraph(advanced_analytics=False)
        for node in payload["nodes"]:
            metadata = dict(node.get("metadata", {}))
            valid_from = metadata.pop("valid_from", node.get("valid_from", None))
            valid_until = metadata.pop("valid_until", node.get("valid_until", None))
            graph.add_node(
                node["id"],
                node["type"],
                node.get("content") or node["id"],
                valid_from=valid_from,
                valid_until=valid_until,
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

    def snapshot(self, label, description):
        return self.versions.create_snapshot(
            graph=self.store.graph_dict(),
            version_label=label,
            author="shadow-projection-v1@example.invalid",
            description=description,
            metadata={"projection_digest": self.store.digest()},
        )
