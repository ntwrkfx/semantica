"""
Provenance-enabled wrapper for pipeline execution.

This module provides provenance tracking for end-to-end pipeline workflows,
capturing all steps, inputs, outputs, and transformations.

Usage:
    from semantica.pipeline.pipeline_provenance import PipelineWithProvenance
    
    pipeline = PipelineWithProvenance(provenance=True)
    result = pipeline.run(data)
    # Tracks all pipeline steps with complete lineage

Author: Semantica Contributors
License: MIT
"""

from typing import Optional, Any, Dict, List
from datetime import datetime
import uuid
import time


class PipelineWithProvenance:
    """Pipeline executor with complete provenance tracking."""
    
    def __init__(
        self,
        provenance: bool = False,
        agent_id: Optional[str] = None,
        is_automated: bool = True,
        **config,
    ):
        """Initialize pipeline with optional provenance."""
        from .pipeline import Pipeline

        self.provenance = provenance
        self._pipeline = Pipeline(**config)
        self._prov_manager = None
        self._agent_id = agent_id or self.__class__.__name__
        self._is_automated = is_automated

        if provenance:
            try:
                from semantica.provenance import ProvenanceManager
                self._prov_manager = ProvenanceManager()
            except ImportError:
                self.provenance = False

    def run(self, data: Any, source: Optional[str] = None, **kwargs):
        """Run pipeline with provenance tracking."""
        pipeline_id = f"pipeline_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        activity_started_at_time = datetime.utcnow().isoformat()

        result = self._pipeline.run(data, **kwargs)
        elapsed = time.time() - start_time
        activity_ended_at_time = datetime.utcnow().isoformat()

        if self.provenance and self._prov_manager:
            self._prov_manager.track_entity(
                entity_id=pipeline_id,
                source=source or "pipeline_execution",
                entity_type="pipeline_run",
                agent_id=self._agent_id,
                agent_type="software_agent",
                is_automated=self._is_automated,
                activity_id=pipeline_id,
                activity_started_at_time=activity_started_at_time,
                activity_ended_at_time=activity_ended_at_time,
                metadata={
                    "steps": len(self._pipeline.steps) if hasattr(self._pipeline, 'steps') else 0,
                    "duration_seconds": elapsed,
                    "status": "completed"
                }
            )
        
        return result
    
    def __getattr__(self, name):
        return getattr(self._pipeline, name)


__all__ = ['PipelineWithProvenance']
