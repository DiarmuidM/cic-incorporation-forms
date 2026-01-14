"""
Quality Assessment Module

Provides qualitative assessment of extraction quality:
- Scoring individual extractions (0-100)
- Categorizing errors
- Generating quality reports
"""

import re
import sys
from pathlib import Path
from typing import Optional
from collections import Counter

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from common import OCR_ARTIFACTS, INSTRUCTION_PATTERNS


def score_extraction_quality(extraction: dict) -> dict:
    """
    Score the quality of a single extraction result (0-100 scale).

    Args:
        extraction: Single extraction result dictionary

    Returns:
        Dictionary with:
        - overall_score: 0-100 overall quality score
        - completeness_score: 0-100 based on activity-benefit pairs
        - coherence_score: 0-100 based on text quality
        - noise_score: 0-100 (higher = less noise)
        - issues: List of identified issues
    """
    issues = []
    activities = extraction.get("section_b", {}).get("activities", [])

    # Base case: no activities
    if not activities:
        return {
            "overall_score": 0,
            "completeness_score": 0,
            "coherence_score": 0,
            "noise_score": 100,
            "issues": ["No activities extracted"]
        }

    # Calculate component scores
    completeness_scores = []
    coherence_scores = []
    noise_scores = []

    for i, act in enumerate(activities):
        activity_text = act.get("activity", "")
        benefit_text = act.get("benefit", "")

        # Completeness: both activity and benefit present with content
        comp_score = _score_completeness(activity_text, benefit_text)
        completeness_scores.append(comp_score)
        if comp_score < 50:
            issues.append(f"Activity {i+1}: Incomplete pair")

        # Coherence: text makes sense, proper length, structure
        coh_score = _score_coherence(activity_text, benefit_text)
        coherence_scores.append(coh_score)
        if coh_score < 50:
            issues.append(f"Activity {i+1}: Poor text quality")

        # Noise: presence of OCR artifacts or garbage
        noise_score = _score_noise(activity_text, benefit_text)
        noise_scores.append(noise_score)
        if noise_score < 50:
            issues.append(f"Activity {i+1}: OCR artifacts detected")

    # Average component scores
    avg_completeness = sum(completeness_scores) / len(completeness_scores)
    avg_coherence = sum(coherence_scores) / len(coherence_scores)
    avg_noise = sum(noise_scores) / len(noise_scores)

    # Weighted overall score
    overall = (avg_completeness * 0.4) + (avg_coherence * 0.35) + (avg_noise * 0.25)

    return {
        "overall_score": round(overall, 1),
        "completeness_score": round(avg_completeness, 1),
        "coherence_score": round(avg_coherence, 1),
        "noise_score": round(avg_noise, 1),
        "issues": issues,
        "activity_count": len(activities)
    }


def _score_completeness(activity: str, benefit: str) -> float:
    """Score completeness of activity-benefit pair."""
    score = 100.0

    activity_len = len(activity.strip())
    benefit_len = len(benefit.strip())

    # Penalize missing or very short content
    if activity_len == 0:
        score -= 50
    elif activity_len < 20:
        score -= 30
    elif activity_len < 50:
        score -= 10

    if benefit_len == 0:
        score -= 50
    elif benefit_len < 20:
        score -= 30
    elif benefit_len < 50:
        score -= 10

    return max(0, score)


def _score_coherence(activity: str, benefit: str) -> float:
    """Score coherence/quality of text content."""
    score = 100.0
    combined = activity + " " + benefit

    # Check for instruction text instead of actual content
    for pattern in INSTRUCTION_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            score -= 20

    # Check for reasonable word count
    words = combined.split()
    if len(words) < 5:
        score -= 30
    elif len(words) < 10:
        score -= 15

    # Check for excessive repetition
    if len(words) > 5:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.3:  # Very repetitive
            score -= 20

    # Check for proper sentence structure (has spaces between words)
    if combined and ' ' not in combined:
        score -= 30

    return max(0, score)


def _score_noise(activity: str, benefit: str) -> float:
    """Score based on absence of OCR noise/artifacts."""
    score = 100.0
    combined = activity + " " + benefit

    # Check for OCR artifacts
    for artifact in OCR_ARTIFACTS:
        if artifact in combined:
            score -= 15

    # Check for excessive special characters
    special_count = sum(1 for c in combined if not c.isalnum() and c not in ' .,;:!?()-\'\"')
    char_count = len(combined) or 1
    special_ratio = special_count / char_count

    if special_ratio > 0.2:
        score -= 30
    elif special_ratio > 0.1:
        score -= 15

    # Check for non-ASCII characters (potential encoding issues)
    non_ascii = sum(1 for c in combined if ord(c) > 127)
    if non_ascii > len(combined) * 0.1:
        score -= 20

    return max(0, score)


def categorize_error(extraction: dict) -> str:
    """
    Categorize the type of extraction error.

    Args:
        extraction: Single extraction result dictionary

    Returns:
        Error category string:
        - 'success': No error
        - 'missing_data': No activities found
        - 'partial_extraction': Has activity but no benefit (or vice versa)
        - 'ocr_errors': Garbled text, special characters
        - 'wrong_section': Content clearly not from Section B
        - 'truncated': Activity/benefit appears cut off
        - 'processing_error': Pipeline error
    """
    status = extraction.get("extraction_status", "unknown")

    # Check for processing error
    if extraction.get("extraction_metadata", {}).get("error"):
        return "processing_error"

    activities = extraction.get("section_b", {}).get("activities", [])

    # No activities
    if not activities:
        return "missing_data"

    # Check each activity
    has_partial = False
    has_ocr_errors = False
    has_truncated = False
    has_wrong_section = False

    for act in activities:
        activity_text = act.get("activity", "")
        benefit_text = act.get("benefit", "")

        # Partial extraction
        if (activity_text and not benefit_text) or (benefit_text and not activity_text):
            has_partial = True

        # OCR errors - check for artifacts
        combined = activity_text + benefit_text
        for artifact in OCR_ARTIFACTS:
            if artifact in combined:
                has_ocr_errors = True
                break

        # Truncated - ends mid-word or with common truncation markers
        for text in [activity_text, benefit_text]:
            if text and (text.endswith('...') or text.endswith('-') or
                        (len(text) > 10 and not text[-1] in '.!?"\'')):
                has_truncated = True

        # Wrong section - check for section markers
        wrong_markers = ["section a", "section c", "memorandum", "certificate of incorporation"]
        if any(marker in combined.lower() for marker in wrong_markers):
            has_wrong_section = True

    # Return most severe error category
    if has_wrong_section:
        return "wrong_section"
    if has_ocr_errors:
        return "ocr_errors"
    if has_truncated:
        return "truncated"
    if has_partial:
        return "partial_extraction"

    return "success"


def generate_quality_report(results: list[dict]) -> dict:
    """
    Generate overall quality report for batch of extractions.

    Args:
        results: List of extraction result dictionaries

    Returns:
        Dictionary with:
        - quality_score_distribution: {excellent: N, good: N, fair: N, poor: N}
        - error_categorization: {category: count}
        - mean_quality_score: float
        - flagged_for_review: list of company numbers needing review
        - quality_by_type: {doc_type: mean_score}
    """
    if not results:
        return {
            "quality_score_distribution": {},
            "error_categorization": {},
            "mean_quality_score": 0.0,
            "flagged_for_review": [],
            "quality_by_type": {}
        }

    # Score each extraction
    scores = []
    categories = []
    flagged = []
    scores_by_type = {}

    for r in results:
        quality = score_extraction_quality(r)
        score = quality["overall_score"]
        scores.append(score)

        category = categorize_error(r)
        categories.append(category)

        # Flag low quality extractions for review
        if score < 50 or category != "success":
            company = r.get("company_number", r.get("extraction_metadata", {}).get("source_file", "unknown"))
            flagged.append(company)

        # Track by document type
        doc_type = r.get("document_type", "unknown")
        if doc_type not in scores_by_type:
            scores_by_type[doc_type] = []
        scores_by_type[doc_type].append(score)

    # Quality distribution
    distribution = {
        "excellent": sum(1 for s in scores if s >= 90),
        "good": sum(1 for s in scores if 70 <= s < 90),
        "fair": sum(1 for s in scores if 50 <= s < 70),
        "poor": sum(1 for s in scores if s < 50)
    }

    # Error categorization
    error_counts = Counter(categories)

    # Mean by type
    mean_by_type = {
        doc_type: round(sum(type_scores) / len(type_scores), 1)
        for doc_type, type_scores in scores_by_type.items()
        if type_scores
    }

    return {
        "quality_score_distribution": distribution,
        "error_categorization": dict(error_counts),
        "mean_quality_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "flagged_for_review": flagged,
        "flagged_count": len(flagged),
        "quality_by_type": mean_by_type
    }


def get_quality_label(score: float) -> str:
    """Convert numeric score to quality label."""
    if score >= 90:
        return "Excellent"
    elif score >= 70:
        return "Good"
    elif score >= 50:
        return "Fair"
    else:
        return "Poor"
