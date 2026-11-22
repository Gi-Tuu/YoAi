"""证据基础设施包 · M2 前置。

只消费真实 Core 事件流，不伪造证据。
"""

from yoai.evidence.models import (
    ExecutionEvidence, Attribution,
    SAMPLE_EVOLUTION, SAMPLE_VALIDATION, SAMPLE_CLASSES,
    ATTRIBUTION_CAPABILITY, ATTRIBUTION_ROUTING,
    ATTRIBUTION_ENVIRONMENT, ATTRIBUTION_NONE,
)
from yoai.evidence.collector import ExecutionEvidenceCollector
from yoai.evidence.store import EvidenceStore
from yoai.evidence.attribution import AttributionEngine
from yoai.evidence.benchmark_lab import BenchmarkLab, EvaluationReport, BoundaryResult, wilson_interval

__all__ = [
    "ExecutionEvidence", "Attribution",
    "SAMPLE_EVOLUTION", "SAMPLE_VALIDATION", "SAMPLE_CLASSES",
    "ATTRIBUTION_CAPABILITY", "ATTRIBUTION_ROUTING",
    "ATTRIBUTION_ENVIRONMENT", "ATTRIBUTION_NONE",
    "ExecutionEvidenceCollector", "EvidenceStore", "AttributionEngine",
    "BenchmarkLab", "EvaluationReport", "BoundaryResult", "wilson_interval",
]
