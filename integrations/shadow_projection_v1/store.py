import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .identity import canonical_json_bytes, sha256_hex, stable_uri
from .models import AssertionRecord

CONTRACT = "shadow-projection/v1"


class ProjectionStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.assertions: Dict[str, AssertionRecord] = {}
        if self.path is not None and self.path.exists():
            self._load()

    def _load(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("contract") != CONTRACT:
            raise ValueError("unsupported projection contract")
        self.resources = {
            item["canonical_uri"]: item for item in payload.get("resources", [])
        }
        self.assertions = {
            item["assertion_uri"]: AssertionRecord.model_validate(item)
            for item in payload.get("assertions", [])
        }

    def _payload(self) -> Dict[str, Any]:
        return {
            "contract": CONTRACT,
            "resources": [
                copy.deepcopy(self.resources[key]) for key in sorted(self.resources)
            ],
            "assertions": [
                self.assertions[key].model_dump(mode="json")
                for key in sorted(self.assertions)
            ],
        }

    def _flush(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_bytes(canonical_json_bytes(self._payload()) + b"\n")
        os.replace(temp, self.path)

    def _flush_if_persistent(self) -> None:
        if self.path is not None:
            self._flush()

    def clone(self):
        staged = ProjectionStore(None)
        staged.resources = copy.deepcopy(self.resources)
        staged.assertions = copy.deepcopy(self.assertions)
        return staged

    def commit_from(self, staged) -> None:
        self.resources = copy.deepcopy(staged.resources)
        self.assertions = copy.deepcopy(staged.assertions)
        self._flush()

    def upsert_resource(self, canonical_uri: str, resource_type: str) -> None:
        candidate = {
            "canonical_uri": canonical_uri,
            "resource_type": resource_type,
        }
        existing = self.resources.get(canonical_uri)
        if existing is not None:
            if existing != candidate:
                raise ValueError("resource identity collision")
            return
        self.resources[canonical_uri] = candidate
        self._flush_if_persistent()

    def add_assertion(self, assertion: AssertionRecord) -> None:
        existing = self.assertions.get(assertion.assertion_uri)
        if existing is not None:
            if existing.model_dump(mode="json") != assertion.model_dump(mode="json"):
                raise ValueError("assertion identity collision")
            return
        if assertion.canonical_uri not in self.resources:
            raise ValueError("assertion references unknown resource")
        self.assertions[assertion.assertion_uri] = assertion
        self._flush_if_persistent()

    def retract_assertion(self, assertion_uri: str, at_time: datetime) -> None:
        existing = self.assertions.get(assertion_uri)
        if existing is None:
            raise KeyError(assertion_uri)
        if existing.valid_until is not None:
            if existing.valid_until == at_time:
                return
            raise ValueError("assertion is already retracted")
        updated = existing.model_copy(update={"valid_until": at_time})
        updated = AssertionRecord.model_validate(updated.model_dump())
        self.assertions[assertion_uri] = updated
        self._flush_if_persistent()

    def active_assertions(self, at_time: datetime) -> List[AssertionRecord]:
        active = []
        for key in sorted(self.assertions):
            item = self.assertions[key]
            start_ok = item.valid_from is None or item.valid_from <= at_time
            end_ok = item.valid_until is None or at_time < item.valid_until
            if start_ok and end_ok:
                active.append(item)
        return active

    def conflicts(self) -> List[Dict[str, Any]]:
        groups: Dict[Any, List[AssertionRecord]] = {}
        for item in self.assertions.values():
            groups.setdefault((item.canonical_uri, item.predicate), []).append(item)

        result = []
        for (canonical_uri, predicate), items in sorted(groups.items()):
            values = sorted(
                {canonical_json_bytes(item.value).decode("utf-8") for item in items}
            )
            if len(values) < 2:
                continue
            result.append(
                {
                    "canonical_uri": canonical_uri,
                    "predicate": predicate,
                    "assertion_uris": sorted(item.assertion_uri for item in items),
                    "values": values,
                }
            )
        return result

    def graph_dict(self, at_time: Optional[datetime] = None) -> Dict[str, Any]:
        assertions = (
            [self.assertions[key] for key in sorted(self.assertions)]
            if at_time is None
            else self.active_assertions(at_time)
        )
        nodes: List[Dict[str, Any]] = []
        for key in sorted(self.resources):
            item = self.resources[key]
            nodes.append(
                {
                    "id": item["canonical_uri"],
                    "type": item["resource_type"],
                    "content": item["canonical_uri"],
                }
            )
        edges: List[Dict[str, Any]] = []
        for item in assertions:
            metadata = item.model_dump(mode="json")
            nodes.append(
                {
                    "id": item.assertion_uri,
                    "type": "Assertion",
                    "content": "%s=%s" % (item.predicate, item.value),
                    "metadata": metadata,
                    "valid_from": metadata.get("valid_from"),
                    "valid_until": metadata.get("valid_until"),
                }
            )
            edge_id = stable_uri(
                "relationship",
                sha256_hex(
                    {
                        "source": item.assertion_uri,
                        "type": "ABOUT",
                        "target": item.canonical_uri,
                    }
                ),
            )
            edges.append(
                {
                    "id": edge_id,
                    "source": item.assertion_uri,
                    "target": item.canonical_uri,
                    "type": "ABOUT",
                    "weight": 1.0,
                }
            )
        nodes.sort(key=lambda node: node["id"])
        edges.sort(
            key=lambda edge: (
                edge["source"], edge["type"], edge["target"], edge["id"]
            )
        )
        return {"nodes": nodes, "edges": edges}

    def digest(self) -> str:
        return sha256_hex(self._payload())
