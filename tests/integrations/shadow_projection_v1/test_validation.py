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
