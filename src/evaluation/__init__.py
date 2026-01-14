"""
Evaluation Framework for CIC Document Extraction Pipeline

This package provides tools for measuring and reporting extraction quality:
- metrics: Quantitative metrics (success rates, activity counts, timing)
- quality: Qualitative assessment (scoring, error categorization)
- sampling: Manual validation sample creation
- report: Report generation (markdown, JSON, comparison)
"""

from .metrics import (
    compute_document_metrics,
    compute_activity_statistics,
    compute_processing_times,
)
from .quality import (
    score_extraction_quality,
    categorize_error,
    generate_quality_report,
)
from .sampling import (
    create_validation_sample,
    generate_validation_worksheet,
)
from .report import (
    generate_summary_report,
    generate_json_report,
    generate_comparison_report,
)

__all__ = [
    "compute_document_metrics",
    "compute_activity_statistics",
    "compute_processing_times",
    "score_extraction_quality",
    "categorize_error",
    "generate_quality_report",
    "create_validation_sample",
    "generate_validation_worksheet",
    "generate_summary_report",
    "generate_json_report",
    "generate_comparison_report",
]
