"""
Quantitative Metrics Module

Computes quantitative metrics for CIC document extraction results:
- Document counts and success rates by type
- Activity extraction statistics
- Processing time analysis
"""

from typing import Optional
from statistics import mean, median
from collections import Counter


def compute_document_metrics(results: list[dict]) -> dict:
    """
    Calculate document-level metrics.

    Args:
        results: List of extraction result dictionaries

    Returns:
        Dictionary with:
        - total_count: Total documents processed
        - counts_by_type: {electronic: N, scanned: N, hybrid: N, unknown: N}
        - counts_by_status: {success: N, error: N, no_data: N}
        - success_rates_by_type: {electronic: 0.XX, ...}
        - overall_success_rate: float
    """
    if not results:
        return {
            "total_count": 0,
            "counts_by_type": {},
            "counts_by_status": {},
            "success_rates_by_type": {},
            "overall_success_rate": 0.0
        }

    # Count by document type
    type_counter = Counter(r.get("document_type", "unknown") for r in results)

    # Count by extraction status
    status_counter = Counter(r.get("extraction_status", "unknown") for r in results)

    # Calculate success rates by type
    success_by_type = {}
    for doc_type in type_counter.keys():
        type_results = [r for r in results if r.get("document_type") == doc_type]
        if type_results:
            successes = sum(1 for r in type_results if r.get("extraction_status") == "success")
            success_by_type[doc_type] = round(successes / len(type_results), 4)

    # Overall success rate
    total_successes = status_counter.get("success", 0)
    overall_rate = total_successes / len(results) if results else 0.0

    return {
        "total_count": len(results),
        "counts_by_type": dict(type_counter),
        "counts_by_status": dict(status_counter),
        "success_rates_by_type": success_by_type,
        "overall_success_rate": round(overall_rate, 4)
    }


def compute_activity_statistics(results: list[dict]) -> dict:
    """
    Calculate activity extraction statistics.

    Args:
        results: List of extraction result dictionaries

    Returns:
        Dictionary with:
        - total_activities: Total activities extracted across all documents
        - activity_count_mean: Mean activities per document
        - activity_count_median: Median activities per document
        - activity_count_min: Minimum activities in any document
        - activity_count_max: Maximum activities in any document
        - activity_count_distribution: {0: N, 1: N, 2: N, ...}
        - documents_with_zero_activities: Count of docs with no activities
        - documents_with_activities: Count of docs with at least one activity
    """
    if not results:
        return {
            "total_activities": 0,
            "activity_count_mean": 0.0,
            "activity_count_median": 0.0,
            "activity_count_min": 0,
            "activity_count_max": 0,
            "activity_count_distribution": {},
            "documents_with_zero_activities": 0,
            "documents_with_activities": 0
        }

    # Extract activity counts
    activity_counts = []
    for r in results:
        activities = r.get("section_b", {}).get("activities", [])
        activity_counts.append(len(activities))

    total = sum(activity_counts)

    # Distribution
    distribution = Counter(activity_counts)

    return {
        "total_activities": total,
        "activity_count_mean": round(mean(activity_counts), 2) if activity_counts else 0.0,
        "activity_count_median": median(activity_counts) if activity_counts else 0.0,
        "activity_count_min": min(activity_counts) if activity_counts else 0,
        "activity_count_max": max(activity_counts) if activity_counts else 0,
        "activity_count_distribution": dict(sorted(distribution.items())),
        "documents_with_zero_activities": distribution.get(0, 0),
        "documents_with_activities": len(results) - distribution.get(0, 0)
    }


def compute_processing_times(results: list[dict]) -> dict:
    """
    Calculate processing time metrics.

    Args:
        results: List of extraction result dictionaries
                 (must have extraction_metadata.processing_time)

    Returns:
        Dictionary with:
        - mean_processing_time: Mean time in seconds
        - median_processing_time: Median time in seconds
        - min_processing_time: Minimum time
        - max_processing_time: Maximum time
        - p95_processing_time: 95th percentile time
        - total_processing_time: Sum of all processing times
        - processing_time_by_type: {electronic: mean, scanned: mean, ...}
    """
    if not results:
        return {
            "mean_processing_time": 0.0,
            "median_processing_time": 0.0,
            "min_processing_time": 0.0,
            "max_processing_time": 0.0,
            "p95_processing_time": 0.0,
            "total_processing_time": 0.0,
            "processing_time_by_type": {}
        }

    # Extract processing times
    times = []
    times_by_type = {}

    for r in results:
        proc_time = r.get("extraction_metadata", {}).get("processing_time")
        if proc_time is not None:
            times.append(proc_time)

            doc_type = r.get("document_type", "unknown")
            if doc_type not in times_by_type:
                times_by_type[doc_type] = []
            times_by_type[doc_type].append(proc_time)

    if not times:
        return {
            "mean_processing_time": 0.0,
            "median_processing_time": 0.0,
            "min_processing_time": 0.0,
            "max_processing_time": 0.0,
            "p95_processing_time": 0.0,
            "total_processing_time": 0.0,
            "processing_time_by_type": {},
            "note": "No processing times recorded"
        }

    # Calculate p95
    sorted_times = sorted(times)
    p95_idx = int(len(sorted_times) * 0.95)
    p95 = sorted_times[p95_idx] if p95_idx < len(sorted_times) else sorted_times[-1]

    # Mean by type
    mean_by_type = {
        doc_type: round(mean(type_times), 3)
        for doc_type, type_times in times_by_type.items()
        if type_times
    }

    return {
        "mean_processing_time": round(mean(times), 3),
        "median_processing_time": round(median(times), 3),
        "min_processing_time": round(min(times), 3),
        "max_processing_time": round(max(times), 3),
        "p95_processing_time": round(p95, 3),
        "total_processing_time": round(sum(times), 3),
        "processing_time_by_type": mean_by_type
    }


def compute_page_location_accuracy(results: list[dict],
                                    ground_truth: Optional[dict] = None) -> dict:
    """
    Calculate page location accuracy (if ground truth available).

    Args:
        results: List of extraction result dictionaries
        ground_truth: Dict mapping company_number to correct section_b_page

    Returns:
        Dictionary with accuracy metrics
    """
    if not ground_truth:
        return {
            "accuracy_available": False,
            "note": "Ground truth not provided"
        }

    matches = {"exact": 0, "within_1": 0, "within_2": 0, "total": 0}

    for r in results:
        company = r.get("company_number")
        if company not in ground_truth:
            continue

        matches["total"] += 1
        detected = r.get("extraction_metadata", {}).get("cic36_page")
        actual = ground_truth[company]

        if detected is None or actual is None:
            continue

        diff = abs(detected - actual)
        if diff == 0:
            matches["exact"] += 1
            matches["within_1"] += 1
            matches["within_2"] += 1
        elif diff == 1:
            matches["within_1"] += 1
            matches["within_2"] += 1
        elif diff == 2:
            matches["within_2"] += 1

    total = matches["total"] or 1  # Avoid division by zero

    return {
        "accuracy_available": True,
        "total_evaluated": matches["total"],
        "exact_match_rate": round(matches["exact"] / total, 4),
        "within_1_page_rate": round(matches["within_1"] / total, 4),
        "within_2_pages_rate": round(matches["within_2"] / total, 4)
    }


def compute_all_metrics(results: list[dict],
                        ground_truth: Optional[dict] = None) -> dict:
    """
    Compute all quantitative metrics.

    Args:
        results: List of extraction result dictionaries
        ground_truth: Optional ground truth for page location accuracy

    Returns:
        Combined metrics dictionary
    """
    return {
        "document_metrics": compute_document_metrics(results),
        "activity_statistics": compute_activity_statistics(results),
        "processing_times": compute_processing_times(results),
        "page_location_accuracy": compute_page_location_accuracy(results, ground_truth)
    }
