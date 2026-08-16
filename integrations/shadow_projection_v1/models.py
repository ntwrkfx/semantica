from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthorityClass(str, Enum):
    AUTHORITATIVE_SOURCE = "authoritative_source"
    PROVIDER_OBSERVATION = "provider_observation"
    DERIVED = "derived"
    PROPOSED = "proposed"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _TemporalModel(_StrictModel):
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_interval(self):
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must not precede valid_from")
        return self


class RawAssertion(_TemporalModel):
    predicate: str = Field(min_length=1)
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    authority_class: AuthorityClass


class SourceRecord(_StrictModel):
    canonical_key: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    assertions: List[RawAssertion] = Field(min_length=1)


class SourceEnvelope(_StrictModel):
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    observed_at: datetime
    records: List[SourceRecord] = Field(min_length=1)


class EvidenceRecord(_StrictModel):
    evidence_uri: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    content_digest: str = Field(min_length=1)
    observed_at: datetime


class AssertionRecord(_TemporalModel):
    record_type: Literal["Assertion"] = "Assertion"
    assertion_uri: str = Field(min_length=1)
    canonical_uri: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: Any
    evidence_uri: str = Field(min_length=1)
    observed_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    authority_class: AuthorityClass


class DecisionRecord(_StrictModel):
    record_type: Literal["Decision"] = "Decision"
    decision_uri: str = Field(min_length=1)
    decision_maker: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    observed_at: datetime


class ProjectionReceipt(_StrictModel):
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
