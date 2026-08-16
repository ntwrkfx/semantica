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
