"""
Content Validator

Validates the quality of extracted activity-benefit pairs:
- Checks for minimum content length
- Detects OCR artifacts
- Filters form instructions and placeholder text
"""

import re
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from common import (
    OCR_ARTIFACTS,
    INSTRUCTION_PATTERNS,
    PLACEHOLDER_PATTERNS,
    calculate_special_char_ratio,
)


def validate_activity_benefit_pair(activity: str, benefit: str,
                                    min_length: int = 20) -> dict:
    """
    Validate an activity-benefit pair for quality.

    Args:
        activity: Activity description text
        benefit: Benefit description text
        min_length: Minimum length for valid content

    Returns:
        Dictionary with:
        - is_valid: bool - Whether pair passes validation
        - quality_score: float - Quality score 0.0 to 1.0
        - issues: list[str] - List of issues found
        - suggestions: list[str] - Suggestions for improvement
    """
    issues = []
    suggestions = []

    activity = str(activity or "").strip()
    benefit = str(benefit or "").strip()

    # Check minimum length
    if len(activity) < min_length:
        issues.append(f"Activity too short ({len(activity)} chars, min {min_length})")
        suggestions.append("Activity description should be more detailed")

    if len(benefit) < min_length:
        issues.append(f"Benefit too short ({len(benefit)} chars, min {min_length})")
        suggestions.append("Benefit description should explain community impact")

    # Check for OCR artifacts
    combined = activity + " " + benefit
    for artifact in OCR_ARTIFACTS:
        if artifact in combined:
            issues.append(f"OCR artifact detected: '{artifact}'")
            suggestions.append("Manual review recommended for OCR quality")
            break

    # Check for instruction text
    for pattern in INSTRUCTION_PATTERNS:
        if re.search(pattern, activity, re.IGNORECASE):
            issues.append("Activity appears to be form instruction text")
        if re.search(pattern, benefit, re.IGNORECASE):
            issues.append("Benefit appears to be form instruction text")

    # Check for placeholder text
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            issues.append("Placeholder or example text detected")
            break

    # Check for excessive special characters (OCR noise)
    special_ratio = calculate_special_char_ratio(combined)
    if special_ratio > 0.15:
        issues.append(f"High special character ratio ({special_ratio:.1%})")
        suggestions.append("Text may contain OCR noise")

    # Check for both fields present
    if not activity and not benefit:
        issues.append("Both activity and benefit are empty")
    elif not activity:
        issues.append("Activity is empty")
    elif not benefit:
        issues.append("Benefit is empty")
        suggestions.append("Consider adding community benefit description")

    # Calculate quality score
    quality_score = _calculate_quality_score(activity, benefit, issues)

    return {
        "is_valid": len(issues) == 0,
        "quality_score": round(quality_score, 2),
        "issues": issues,
        "suggestions": suggestions,
        "activity_length": len(activity),
        "benefit_length": len(benefit)
    }


def _calculate_quality_score(activity: str, benefit: str, issues: list) -> float:
    """Calculate quality score based on content and issues."""
    score = 1.0

    # Deduct for each issue
    score -= 0.15 * len(issues)

    # Bonus for good content length
    if len(activity) > 100:
        score += 0.1
    if len(benefit) > 100:
        score += 0.1

    # Penalty for very short content
    if len(activity) < 20:
        score -= 0.2
    if len(benefit) < 20:
        score -= 0.2

    return max(0.0, min(1.0, score))


def filter_non_table_content(text: str) -> str:
    """
    Remove content that is clearly not from Section B table.

    Args:
        text: Raw text to filter

    Returns:
        Filtered text with non-content removed
    """
    if not text:
        return ""

    # Patterns to remove
    removal_patterns = [
        r'Please\s+(?:describe|explain|provide|enter).*?(?:\.|$)',
        r'Use\s+continuation\s+sheet\s+if\s+necessary',
        r'See\s+guidance\s+notes',
        r'Page\s+\d+\s+of\s+\d+',
        r'CIC\s*36\s*\([^)]+\)',
        r'Companies\s+House',
        r'\d{8}',  # Company numbers
        r'^[\s\-_=]+$',  # Decorative lines
    ]

    filtered = text
    for pattern in removal_patterns:
        filtered = re.sub(pattern, '', filtered, flags=re.IGNORECASE | re.MULTILINE)

    # Clean up extra whitespace
    filtered = re.sub(r'\s+', ' ', filtered)
    filtered = filtered.strip()

    return filtered


def is_form_instruction(text: str) -> bool:
    """
    Check if text is a form instruction rather than content.

    Args:
        text: Text to check

    Returns:
        True if text appears to be instruction
    """
    if not text:
        return False

    text_lower = text.lower().strip()

    for pattern in INSTRUCTION_PATTERNS:
        if re.search(pattern, text_lower):
            return True

    # Additional checks
    instruction_markers = [
        "please describe",
        "how will the activity",
        "what activities will",
        "see guidance",
        "continuation sheet",
    ]

    for marker in instruction_markers:
        if marker in text_lower:
            return True

    return False


def compute_overall_quality(activities: list) -> float:
    """
    Compute overall quality score for a list of activities.

    Args:
        activities: List of activity dictionaries with 'activity' and 'benefit' keys

    Returns:
        Overall quality score 0.0 to 1.0
    """
    if not activities:
        return 0.0

    scores = []
    for act in activities:
        validation = validate_activity_benefit_pair(
            act.get("activity", ""),
            act.get("benefit", "")
        )
        scores.append(validation["quality_score"])

    return sum(scores) / len(scores)


def clean_extracted_text(text: str) -> str:
    """
    Clean extracted text for better quality.

    Args:
        text: Raw extracted text

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Remove OCR artifacts
    cleaned = text
    for artifact in OCR_ARTIFACTS:
        cleaned = cleaned.replace(artifact, '')

    # Normalize whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)

    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()

    # Fix common OCR errors
    ocr_fixes = {
        'l1': 'll',
        '0f': 'of',
        'c0mmunity': 'community',
        'act1vit': 'activit',
    }

    for wrong, correct in ocr_fixes.items():
        cleaned = re.sub(wrong, correct, cleaned, flags=re.IGNORECASE)

    return cleaned
