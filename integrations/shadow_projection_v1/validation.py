from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from pyshacl import validate
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from .identity import canonical_json_bytes

SQN = Namespace("https://id.example.invalid/schema/")


@dataclass(frozen=True)
class ValidationResult:
    conforms: bool
    report_text: str


def _literal_value(value: Any) -> Literal:
    if isinstance(value, (dict, list, tuple)):
        return Literal(canonical_json_bytes(value).decode("utf-8"))
    return Literal(value)


def graph_to_rdf(graph_dict: Dict[str, Any]) -> Graph:
    graph = Graph()
    for node in graph_dict.get("nodes", []):
        if node.get("type") != "Assertion":
            continue
        metadata = node.get("metadata", {})
        uri = URIRef(node["id"])
        graph.add((uri, RDF.type, SQN.Assertion))
        if metadata.get("canonical_uri"):
            graph.add((uri, SQN.subject, URIRef(metadata["canonical_uri"])))
        if metadata.get("predicate"):
            graph.add((uri, SQN.predicate, Literal(metadata["predicate"])))
        if "value" in metadata:
            graph.add((uri, SQN.value, _literal_value(metadata["value"])))
        if metadata.get("evidence_uri"):
            graph.add((uri, SQN.evidence, URIRef(metadata["evidence_uri"])))
    return graph


def validate_graph(graph_dict: Dict[str, Any]) -> ValidationResult:
    conforms, _report_graph, report_text = validate(
        data_graph=graph_to_rdf(graph_dict),
        shacl_graph=str(Path(__file__).with_name("shapes.ttl")),
        inference="none",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
    )
    return ValidationResult(bool(conforms), str(report_text))
