from typing import Optional


class ReadGateway:
    def __init__(self, engine):
        self._engine = engine

    def entity_get(self, canonical_uri: str):
        resource = self._engine.store.resources.get(canonical_uri)
        return dict(resource) if resource is not None else None

    def assertion_query(self, canonical_uri=None, predicate=None, at_time=None):
        if at_time is None:
            items = [
                self._engine.store.assertions[key]
                for key in sorted(self._engine.store.assertions)
            ]
        else:
            items = self._engine.store.active_assertions(at_time)
        result = []
        for item in items:
            if canonical_uri is not None and item.canonical_uri != canonical_uri:
                continue
            if predicate is not None and item.predicate != predicate:
                continue
            result.append(item.model_dump(mode="json"))
        return result

    def relationship_query(self, canonical_uri=None, edge_type=None, at_time=None):
        edges = self._engine.store.graph_dict(at_time=at_time)["edges"]
        result = []
        for edge in edges:
            if edge_type is not None and edge["type"] != edge_type:
                continue
            if canonical_uri is not None and canonical_uri not in (
                edge["source"],
                edge["target"],
            ):
                continue
            result.append(dict(edge))
        return result

    def provenance_trace(self, entity_uri: str):
        return self._engine.provenance.lineage(entity_uri)

    def explain(self, canonical_uri: str):
        resource = self.entity_get(canonical_uri)
        assertions = self.assertion_query(canonical_uri=canonical_uri)
        assertion_uris = [item["assertion_uri"] for item in assertions]
        conflicts = [
            item
            for item in self._engine.store.conflicts()
            if item["canonical_uri"] == canonical_uri
        ]
        provenance = {
            uri: self._engine.provenance.lineage(uri) for uri in assertion_uris
        }
        return {
            "canonical_uri": canonical_uri,
            "resource": resource,
            "assertions": assertions,
            "conflicts": conflicts,
            "provenance": provenance,
        }

    def graph_summary(self):
        graph = self._engine.store.graph_dict()
        return {
            "resource_count": len(self._engine.store.resources),
            "assertion_count": len(self._engine.store.assertions),
            "relationship_count": len(graph["edges"]),
            "conflict_count": len(self._engine.store.conflicts()),
            "projection_digest": self._engine.store.digest(),
        }
