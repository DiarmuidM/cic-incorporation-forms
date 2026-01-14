"""
Table Structure Validator

Validates that extracted tables have the correct Section B structure:
- Two columns
- Activity header in first column
- Benefit/Community header in second column
"""

import re
from typing import Optional


def validate_section_b_table(table_data: list) -> dict:
    """
    Validate that a table has the correct Section B structure.

    Args:
        table_data: List of rows, where each row is a list of cell values

    Returns:
        Dictionary with:
        - is_valid: bool - Whether table is a valid Section B table
        - column_count: int - Number of columns detected
        - has_activity_column: bool - Whether activity header found
        - has_benefit_column: bool - Whether benefit header found
        - row_count: int - Number of data rows (excluding header)
        - issues: list[str] - List of validation issues
        - confidence: str - 'high', 'medium', or 'low'
    """
    result = {
        "is_valid": False,
        "column_count": 0,
        "has_activity_column": False,
        "has_benefit_column": False,
        "row_count": 0,
        "issues": [],
        "confidence": "low"
    }

    if not table_data:
        result["issues"].append("Empty table data")
        return result

    # Check column count
    first_row = table_data[0] if table_data else []
    result["column_count"] = len(first_row)

    if result["column_count"] < 2:
        result["issues"].append(f"Table has {result['column_count']} columns, expected 2")
    elif result["column_count"] > 3:
        result["issues"].append(f"Table has {result['column_count']} columns, expected 2")

    # Find and validate headers
    header_row_idx, header_info = _find_header_row(table_data)

    result["has_activity_column"] = header_info.get("has_activity", False)
    result["has_benefit_column"] = header_info.get("has_benefit", False)

    if not result["has_activity_column"]:
        result["issues"].append("No 'Activities' column header found")
    if not result["has_benefit_column"]:
        result["issues"].append("No 'Benefit' or 'Community' column header found")

    # Count data rows
    data_start = header_row_idx + 1 if header_row_idx >= 0 else 0
    result["row_count"] = len(table_data) - data_start

    if result["row_count"] == 0:
        result["issues"].append("No data rows in table")

    # Determine overall validity and confidence
    if result["has_activity_column"] and result["has_benefit_column"]:
        if result["column_count"] == 2 and result["row_count"] > 0:
            result["is_valid"] = True
            result["confidence"] = "high"
        elif result["row_count"] > 0:
            result["is_valid"] = True
            result["confidence"] = "medium"
    elif result["has_activity_column"] or result["has_benefit_column"]:
        if result["row_count"] > 0:
            result["is_valid"] = True
            result["confidence"] = "low"

    return result


def _find_header_row(table_data: list) -> tuple[int, dict]:
    """
    Find the header row in table data.

    Returns:
        Tuple of (header_row_index, header_info_dict)
    """
    activity_patterns = [
        r'activit',
        r'what.*will.*company.*do',
        r'describe.*activit',
    ]

    benefit_patterns = [
        r'benefit',
        r'community',
        r'how.*will.*benefit',
    ]

    for i, row in enumerate(table_data[:5]):  # Check first 5 rows
        if not row:
            continue

        row_text = ' '.join(str(cell or '').lower() for cell in row)

        has_activity = any(re.search(p, row_text) for p in activity_patterns)
        has_benefit = any(re.search(p, row_text) for p in benefit_patterns)

        if has_activity or has_benefit:
            return i, {"has_activity": has_activity, "has_benefit": has_benefit}

    return -1, {"has_activity": False, "has_benefit": False}


def is_valid_table_structure(table_data: list,
                             require_both_headers: bool = True) -> bool:
    """
    Quick check if table has valid Section B structure.

    Args:
        table_data: Table data to check
        require_both_headers: Whether to require both activity and benefit headers

    Returns:
        True if table structure is valid
    """
    result = validate_section_b_table(table_data)

    if require_both_headers:
        return result["has_activity_column"] and result["has_benefit_column"]
    else:
        return result["has_activity_column"] or result["has_benefit_column"]


def extract_table_headers(table_data: list) -> dict:
    """
    Extract and analyze table headers.

    Args:
        table_data: Table data

    Returns:
        Dictionary with header information
    """
    if not table_data:
        return {"headers": [], "header_row": -1}

    header_row_idx, _ = _find_header_row(table_data)

    if header_row_idx >= 0:
        headers = [str(cell or '').strip() for cell in table_data[header_row_idx]]
    else:
        headers = []

    return {
        "headers": headers,
        "header_row": header_row_idx,
        "column_count": len(table_data[0]) if table_data else 0
    }


def suggest_column_mapping(headers: list) -> dict:
    """
    Suggest which columns contain activities and benefits.

    Args:
        headers: List of header strings

    Returns:
        Dictionary mapping column index to field type
    """
    mapping = {}

    for i, header in enumerate(headers):
        header_lower = header.lower()

        if re.search(r'activit', header_lower):
            mapping[i] = "activity"
        elif re.search(r'benefit|community', header_lower):
            mapping[i] = "benefit"

    return mapping
