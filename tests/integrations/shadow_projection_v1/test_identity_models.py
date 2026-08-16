from pathlib import Path

import pytest
from pydantic import ValidationError

from integrations.shadow_projection_v1.identity import (
    evidence_uri_from_digest,
    sha256_hex,
    stable_uri,
)
from integrations.shadow_projection_v1.models import SourceEnvelope

FIXTURES = Path(__file__).parent / "fixtures"


def test_identity_is_stable():
    assert stable_uri("resource", "workstream:ws-1") == (
        "https://id.example.invalid/resource/workstream%3Aws-1"
    )
    assert sha256_hex({"b": 2, "a": 1}) == sha256_hex({"a": 1, "b": 2})
    assert evidence_uri_from_digest("abc123") == (
        "https://id.example.invalid/evidence/sha256/abc123"
    )


def test_bad_source_is_rejected():
    text = (FIXTURES / "malformed_source.json").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        SourceEnvelope.model_validate_json(text)
