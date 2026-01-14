"""
Common Utilities and Constants

Shared functions and constants used across multiple extraction modules.
Consolidates duplicated code from extract_electronic.py, extract_scanned.py,
content_validator.py, and quality.py.
"""

import re
from typing import Optional


# OCR artifacts commonly found in poor extractions
OCR_ARTIFACTS = [
    '\x00', '|', '[]', '}{', '@@', '##', '***',
    '\ufffd', '\u0000', '�', '|||', '___'
]

# Patterns indicating form instructions rather than content
INSTRUCTION_PATTERNS = [
    r'^please\s+(describe|explain|provide|enter)',
    r'^use\s+continuation\s+sheet',
    r'^see\s+guidance\s+notes',
    r'^if\s+necessary',
    r'page\s+\d+\s+of\s+\d+',
    r'^cic\s*36',
    r'^form\s+cic',
    r'companies\s+house',
    r'^\d{8}$',  # Company registration number
]

# Header patterns for detecting table headers
HEADER_PATTERNS = [
    r"^activities?\s*$",
    r"^how\s+will",
    r"^describe\s+the",
    r"^please\s+(describe|explain|provide)",
    r"^section\s+[a-z]",
    r"^\d+\.\s*$",
    r"activit",
    r"benefit",
    r"community",
]

# Section B detection patterns (primary - high confidence)
SECTION_B_PRIMARY_PATTERNS = [
    r"Section\s*B[\s:]*Community\s+Interest\s+Statement",
    r"Community\s+Interest\s+Statement[\s\-:]+Activities",
    r"SECTION\s*B\s*:?\s*COMMUNITY\s+INTEREST",
    r"Activities\s*&?\s*Related\s+Benefit",
    r"SECTION\s*B\s*:?\s*COMPANY\s+ACTIVITIES",
]

# Section B detection patterns (secondary - lower confidence)
SECTION_B_SECONDARY_PATTERNS = [
    r"Activities.*How\s+will\s+the\s+activity",
    r"Tell\s+us\s+here\s+what\s+the\s+company\s+is",
    r"The\s+community\s+will\s+benefit\s+by",
    r"benefit\s+the\s+community",
]

# Patterns for placeholder/example text
PLACEHOLDER_PATTERNS = [
    r'lorem\s+ipsum',
    r'\[.*placeholder.*\]',
    r'\[.*example.*\]',
    r'xxx+',
    r'enter\s+text\s+here',
]


def is_header_or_instruction(text: str) -> bool:
    """
    Check if text looks like a header or instruction rather than activity content.

    Args:
        text: Text to check

    Returns:
        True if text appears to be a header or instruction
    """
    if not text:
        return True

    text_lower = text.lower().strip()

    # Check header patterns
    for pattern in HEADER_PATTERNS:
        if re.match(pattern, text_lower):
            return True

    # Check instruction patterns
    for pattern in INSTRUCTION_PATTERNS:
        if re.search(pattern, text_lower):
            return True

    return False


def clean_cell_text(value: Optional[str], remove_artifacts: bool = True) -> str:
    """
    Clean a cell value for output.

    Args:
        value: Text to clean
        remove_artifacts: Whether to remove OCR artifacts

    Returns:
        Cleaned text string
    """
    if value is None:
        return ""

    text = str(value).strip()

    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)

    # Remove OCR artifacts if requested
    if remove_artifacts:
        text = text.replace('\x00', '')
        for artifact in OCR_ARTIFACTS:
            if len(artifact) > 1:  # Don't remove single chars like |
                text = text.replace(artifact, '')

    return text


def deduplicate_activities(activities: list, use_prefix: bool = False) -> list:
    """
    Remove duplicate activities (same activity/benefit combo).

    Args:
        activities: List of activity dictionaries with 'activity' and 'benefit' keys
        use_prefix: If True, use first 100 chars for comparison (OCR tolerance)

    Returns:
        List with duplicates removed
    """
    seen = set()
    unique = []

    for act in activities:
        activity = act.get("activity", "")
        benefit = act.get("benefit", "")

        if use_prefix:
            # Use first 100 chars for comparison (handles OCR variations)
            key = (activity[:100].lower(), benefit[:100].lower())
        else:
            key = (activity.lower(), benefit.lower())

        if key not in seen and (activity or benefit):
            seen.add(key)
            unique.append(act)

    return unique


def calculate_special_char_ratio(text: str) -> float:
    """
    Calculate ratio of special characters in text.

    Args:
        text: Text to analyze

    Returns:
        Ratio of special characters (0.0 to 1.0)
    """
    if not text:
        return 0.0

    special = sum(1 for c in text if not c.isalnum() and c not in ' .,;:!?()-\'\"')
    return special / len(text)


def has_ocr_artifacts(text: str) -> bool:
    """
    Check if text contains OCR artifacts.

    Args:
        text: Text to check

    Returns:
        True if artifacts found
    """
    for artifact in OCR_ARTIFACTS:
        if artifact in text:
            return True
    return False


def find_header_row(table_data: list) -> int:
    """
    Find the header row index in a table.

    Args:
        table_data: List of table rows

    Returns:
        Index of header row, or -1 if not found
    """
    header_keywords = [
        r"activit",
        r"benefit",
        r"how\s+will",
        r"community",
    ]

    for i, row in enumerate(table_data):
        if not row:
            continue
        row_text = " ".join(str(cell or "") for cell in row).lower()
        matches = sum(1 for p in header_keywords if re.search(p, row_text))
        if matches >= 2:
            return i

    return -1


def filter_form_instructions(text: str) -> str:
    """
    Remove form instruction text from extracted content.

    Args:
        text: Raw text to filter

    Returns:
        Filtered text
    """
    if not text:
        return ""

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
