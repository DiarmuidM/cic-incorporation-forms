"""
Report Generation Module

Generates human-readable and machine-readable reports
from extraction evaluation results.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from .metrics import compute_all_metrics
from .quality import generate_quality_report, get_quality_label


def generate_summary_report(results: list[dict],
                             output_format: str = 'markdown',
                             pipeline_version: str = '1.0.0') -> str:
    """
    Generate a human-readable summary report.

    Args:
        results: List of extraction result dictionaries
        output_format: 'markdown' or 'text'
        pipeline_version: Version string for the pipeline

    Returns:
        Formatted report string
    """
    # Compute all metrics
    metrics = compute_all_metrics(results)
    quality = generate_quality_report(results)

    doc_metrics = metrics["document_metrics"]
    activity_stats = metrics["activity_statistics"]
    timing = metrics["processing_times"]

    # Build report
    lines = []

    if output_format == 'markdown':
        lines.append("# CIC Document Extraction Report")
        lines.append("")
        lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Pipeline Version**: {pipeline_version}")
        lines.append(f"**Documents Processed**: {doc_metrics['total_count']}")
        lines.append("")

        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")
        success_pct = doc_metrics['overall_success_rate'] * 100
        lines.append(f"- **Overall Success Rate**: {success_pct:.1f}%")
        lines.append(f"- **Total Activities Extracted**: {activity_stats['total_activities']}")
        lines.append(f"- **Mean Quality Score**: {quality['mean_quality_score']:.1f}/100")
        lines.append(f"- **Documents Flagged for Review**: {quality['flagged_count']}")
        lines.append("")

        # Document Statistics
        lines.append("## Document Statistics")
        lines.append("")
        lines.append("| Type | Count | Success Rate |")
        lines.append("|------|-------|--------------|")

        for doc_type in ['electronic', 'scanned', 'hybrid', 'unknown']:
            count = doc_metrics['counts_by_type'].get(doc_type, 0)
            if count > 0:
                rate = doc_metrics['success_rates_by_type'].get(doc_type, 0) * 100
                lines.append(f"| {doc_type.title()} | {count} | {rate:.1f}% |")

        lines.append("")

        # Extraction Status
        lines.append("### Extraction Status Breakdown")
        lines.append("")
        for status, count in doc_metrics['counts_by_status'].items():
            pct = count / doc_metrics['total_count'] * 100 if doc_metrics['total_count'] else 0
            lines.append(f"- **{status.title()}**: {count} ({pct:.1f}%)")
        lines.append("")

        # Activity Statistics
        lines.append("## Activity Statistics")
        lines.append("")
        lines.append(f"- **Total Activities**: {activity_stats['total_activities']}")
        lines.append(f"- **Mean per Document**: {activity_stats['activity_count_mean']:.2f}")
        lines.append(f"- **Median per Document**: {activity_stats['activity_count_median']}")
        lines.append(f"- **Range**: {activity_stats['activity_count_min']} - {activity_stats['activity_count_max']}")
        lines.append(f"- **Documents with 0 Activities**: {activity_stats['documents_with_zero_activities']}")
        lines.append("")

        # Activity Distribution
        if activity_stats['activity_count_distribution']:
            lines.append("### Activity Count Distribution")
            lines.append("")
            lines.append("| Activities | Documents |")
            lines.append("|------------|-----------|")
            for count, docs in sorted(activity_stats['activity_count_distribution'].items()):
                lines.append(f"| {count} | {docs} |")
            lines.append("")

        # Quality Assessment
        lines.append("## Quality Assessment")
        lines.append("")
        lines.append(f"**Mean Quality Score**: {quality['mean_quality_score']:.1f}/100 ({get_quality_label(quality['mean_quality_score'])})")
        lines.append("")
        lines.append("| Quality Level | Count | Percentage |")
        lines.append("|--------------|-------|------------|")

        total = doc_metrics['total_count'] or 1
        for level in ['excellent', 'good', 'fair', 'poor']:
            count = quality['quality_score_distribution'].get(level, 0)
            pct = count / total * 100
            lines.append(f"| {level.title()} | {count} | {pct:.1f}% |")
        lines.append("")

        # Quality by Document Type
        if quality['quality_by_type']:
            lines.append("### Quality by Document Type")
            lines.append("")
            for doc_type, score in quality['quality_by_type'].items():
                lines.append(f"- **{doc_type.title()}**: {score:.1f}/100")
            lines.append("")

        # Error Analysis
        lines.append("## Error Analysis")
        lines.append("")
        lines.append("| Error Category | Count |")
        lines.append("|----------------|-------|")

        for category, count in sorted(quality['error_categorization'].items(),
                                       key=lambda x: x[1], reverse=True):
            lines.append(f"| {category.replace('_', ' ').title()} | {count} |")
        lines.append("")

        # Processing Time (if available)
        if timing.get('mean_processing_time', 0) > 0:
            lines.append("## Processing Performance")
            lines.append("")
            lines.append(f"- **Mean Time per Document**: {timing['mean_processing_time']:.2f}s")
            lines.append(f"- **Median Time**: {timing['median_processing_time']:.2f}s")
            lines.append(f"- **95th Percentile**: {timing['p95_processing_time']:.2f}s")
            lines.append(f"- **Total Processing Time**: {timing['total_processing_time']:.1f}s")
            lines.append("")

            if timing.get('processing_time_by_type'):
                lines.append("### Time by Document Type")
                lines.append("")
                for doc_type, time in timing['processing_time_by_type'].items():
                    lines.append(f"- **{doc_type.title()}**: {time:.2f}s (mean)")
                lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")
        lines.extend(_generate_recommendations(doc_metrics, activity_stats, quality, timing))
        lines.append("")

    else:
        # Plain text format
        lines.append("CIC Document Extraction Report")
        lines.append("=" * 40)
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Documents: {doc_metrics['total_count']}")
        lines.append(f"Success Rate: {doc_metrics['overall_success_rate'] * 100:.1f}%")
        lines.append(f"Activities: {activity_stats['total_activities']}")
        lines.append(f"Quality Score: {quality['mean_quality_score']:.1f}/100")

    return "\n".join(lines)


def _generate_recommendations(doc_metrics: dict, activity_stats: dict,
                               quality: dict, timing: dict) -> list[str]:
    """Generate recommendations based on metrics."""
    recommendations = []

    # Check success rate
    success_rate = doc_metrics['overall_success_rate']
    if success_rate < 0.7:
        recommendations.append("- **Low success rate** (<70%): Review failed documents to identify common extraction issues")
    elif success_rate < 0.9:
        recommendations.append("- **Moderate success rate**: Review failed documents to identify common issues")

    # Check quality by type
    quality_by_type = quality.get('quality_by_type', {})
    for doc_type, score in quality_by_type.items():
        if score < 50:
            recommendations.append(f"- **Poor quality for {doc_type} documents**: Consider specialized extraction approach")

    # Check zero-activity documents
    zero_pct = activity_stats['documents_with_zero_activities'] / doc_metrics['total_count'] if doc_metrics['total_count'] else 0
    if zero_pct > 0.2:
        recommendations.append("- **High rate of zero-activity extractions** (>20%): Review Section B detection patterns")

    # Check error categories
    error_cats = quality.get('error_categorization', {})
    if error_cats.get('ocr_errors', 0) > doc_metrics['total_count'] * 0.1:
        recommendations.append("- **High OCR error rate**: Review OCR settings and image quality")
    if error_cats.get('wrong_section', 0) > 0:
        recommendations.append("- **Wrong section extractions detected**: Improve Section B pattern matching")

    # Check processing time
    if timing.get('mean_processing_time', 0) > 30:
        recommendations.append("- **Slow processing time**: Consider parallel processing or lighter extraction methods")

    if not recommendations:
        recommendations.append("- Pipeline performing well. Continue monitoring quality metrics.")

    return recommendations


def generate_json_report(results: list[dict],
                         pipeline_version: str = '1.0.0') -> dict:
    """
    Generate machine-readable JSON report.

    Args:
        results: List of extraction result dictionaries
        pipeline_version: Version string

    Returns:
        Dictionary with all metrics
    """
    metrics = compute_all_metrics(results)
    quality = generate_quality_report(results)

    return {
        "report_metadata": {
            "generated_at": datetime.now().isoformat(),
            "pipeline_version": pipeline_version,
            "total_documents": len(results)
        },
        "document_metrics": metrics["document_metrics"],
        "activity_metrics": metrics["activity_statistics"],
        "quality_metrics": quality,
        "timing_metrics": metrics["processing_times"],
        "page_location_accuracy": metrics["page_location_accuracy"]
    }


def generate_comparison_report(baseline_results: list[dict],
                                new_results: list[dict],
                                baseline_name: str = "Baseline",
                                new_name: str = "New") -> str:
    """
    Generate comparison report between two extraction runs.

    Args:
        baseline_results: Results from baseline extraction
        new_results: Results from new extraction method
        baseline_name: Label for baseline
        new_name: Label for new method

    Returns:
        Markdown comparison report
    """
    baseline_metrics = compute_all_metrics(baseline_results)
    baseline_quality = generate_quality_report(baseline_results)

    new_metrics = compute_all_metrics(new_results)
    new_quality = generate_quality_report(new_results)

    lines = []
    lines.append("# Extraction Method Comparison Report")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Comparing**: {baseline_name} vs {new_name}")
    lines.append("")

    # Summary comparison
    lines.append("## Summary Comparison")
    lines.append("")
    lines.append("| Metric | " + baseline_name + " | " + new_name + " | Change |")
    lines.append("|--------|" + "-" * len(baseline_name) + "--|" + "-" * len(new_name) + "--|--------|")

    # Success rate
    base_sr = baseline_metrics['document_metrics']['overall_success_rate'] * 100
    new_sr = new_metrics['document_metrics']['overall_success_rate'] * 100
    change_sr = new_sr - base_sr
    lines.append(f"| Success Rate | {base_sr:.1f}% | {new_sr:.1f}% | {change_sr:+.1f}% |")

    # Quality score
    base_qs = baseline_quality['mean_quality_score']
    new_qs = new_quality['mean_quality_score']
    change_qs = new_qs - base_qs
    lines.append(f"| Quality Score | {base_qs:.1f} | {new_qs:.1f} | {change_qs:+.1f} |")

    # Total activities
    base_act = baseline_metrics['activity_statistics']['total_activities']
    new_act = new_metrics['activity_statistics']['total_activities']
    change_act = new_act - base_act
    lines.append(f"| Total Activities | {base_act} | {new_act} | {change_act:+d} |")

    # Mean time
    base_time = baseline_metrics['processing_times'].get('mean_processing_time', 0)
    new_time = new_metrics['processing_times'].get('mean_processing_time', 0)
    if base_time > 0 or new_time > 0:
        change_time = new_time - base_time
        lines.append(f"| Mean Time (s) | {base_time:.2f} | {new_time:.2f} | {change_time:+.2f} |")

    lines.append("")

    # By document type
    lines.append("## Success Rate by Document Type")
    lines.append("")
    lines.append("| Type | " + baseline_name + " | " + new_name + " | Change |")
    lines.append("|------|" + "-" * len(baseline_name) + "--|" + "-" * len(new_name) + "--|--------|")

    all_types = set(baseline_metrics['document_metrics']['success_rates_by_type'].keys()) | \
                set(new_metrics['document_metrics']['success_rates_by_type'].keys())

    for doc_type in sorted(all_types):
        base_rate = baseline_metrics['document_metrics']['success_rates_by_type'].get(doc_type, 0) * 100
        new_rate = new_metrics['document_metrics']['success_rates_by_type'].get(doc_type, 0) * 100
        change = new_rate - base_rate
        lines.append(f"| {doc_type.title()} | {base_rate:.1f}% | {new_rate:.1f}% | {change:+.1f}% |")

    lines.append("")

    # Recommendation
    lines.append("## Recommendation")
    lines.append("")

    if new_sr > base_sr and new_qs >= base_qs:
        lines.append(f"**{new_name}** shows improvement in success rate with maintained or better quality. Consider adopting.")
    elif new_sr > base_sr and new_qs < base_qs:
        lines.append(f"**{new_name}** has higher success rate but lower quality. Review trade-offs before adopting.")
    elif new_sr < base_sr:
        lines.append(f"**{baseline_name}** performs better overall. {new_name} not recommended.")
    else:
        lines.append("Results are similar. Consider other factors (processing time, maintenance) for decision.")

    return "\n".join(lines)


def save_report(report: str | dict, output_path: str | Path,
                format: str = 'auto') -> bool:
    """
    Save report to file.

    Args:
        report: Report content (string for markdown/text, dict for JSON)
        output_path: Output file path
        format: 'markdown', 'json', 'text', or 'auto' (detect from extension)

    Returns:
        True if successful
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Detect format from extension if auto
    if format == 'auto':
        suffix = output_path.suffix.lower()
        if suffix == '.json':
            format = 'json'
        elif suffix in ['.md', '.markdown']:
            format = 'markdown'
        else:
            format = 'text'

    try:
        if format == 'json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        else:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report if isinstance(report, str) else str(report))
        return True
    except Exception as e:
        print(f"Error saving report: {e}")
        return False
