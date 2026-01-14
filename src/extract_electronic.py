"""
Electronic PDF Extraction Module

Extracts Section B table data (Activities & Benefits) from electronically
filed CIC incorporation documents using pdfplumber.
"""

import logging
import pdfplumber
from pathlib import Path
from typing import Optional
import re

from common import (
    is_header_or_instruction,
    clean_cell_text,
    deduplicate_activities,
    find_header_row,
)

logger = logging.getLogger(__name__)


def extract_section_b_table(pdf_path: str | Path, section_b_page: int,
                            search_nearby_pages: bool = True) -> dict:
    """
    Extract the Section B Activities & Benefits table from an electronic PDF.

    Args:
        pdf_path: Path to the PDF file
        section_b_page: 1-indexed page number where Section B starts
        search_nearby_pages: If True, also search adjacent pages for table content

    Returns:
        Dictionary with:
        - success: Boolean indicating extraction success
        - activities: List of {activity, benefit} dictionaries
        - raw_tables: Raw table data for debugging
        - extraction_method: Description of method used
        - pages_searched: List of page numbers searched
    """
    pdf_path = Path(pdf_path)

    result = {
        "success": False,
        "activities": [],
        "raw_tables": [],
        "extraction_method": "pdfplumber",
        "pages_searched": []
    }

    if not pdf_path.exists():
        result["error"] = f"PDF not found: {pdf_path}"
        return result

    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)

            # Determine pages to search
            pages_to_search = [section_b_page]
            if search_nearby_pages:
                if section_b_page > 1:
                    pages_to_search.insert(0, section_b_page - 1)
                if section_b_page < page_count:
                    pages_to_search.append(section_b_page + 1)
                if section_b_page + 1 < page_count:
                    pages_to_search.append(section_b_page + 2)

            # Filter valid page numbers
            pages_to_search = [p for p in pages_to_search if 1 <= p <= page_count]
            result["pages_searched"] = pages_to_search

            all_activities = []

            for page_num in pages_to_search:
                page = pdf.pages[page_num - 1]

                # Try table extraction with different settings
                tables = _extract_tables_with_fallback(page)

                for table_data in tables:
                    result["raw_tables"].append({
                        "page": page_num,
                        "data": table_data
                    })

                    # Parse table for activities and benefits
                    parsed = _parse_activities_table(table_data, page_num)
                    if parsed:
                        all_activities.extend(parsed)

            # Deduplicate activities (same content might span pages)
            result["activities"] = deduplicate_activities(all_activities)
            result["success"] = len(result["activities"]) > 0

            # Extract surplus_use and company_differs from page text
            # These appear after the activities table, not in the table itself
            full_text = ""
            for page_num in pages_to_search:
                if 1 <= page_num <= page_count:
                    page = pdf.pages[page_num - 1]
                    page_text = page.extract_text() or ""
                    full_text += page_text + "\n"

            surplus_use = _extract_surplus_use_from_text(full_text)
            company_differs = _extract_company_differs_from_text(full_text)

            if surplus_use:
                result["surplus_use"] = surplus_use
            if company_differs:
                result["company_differs"] = company_differs

            # Extract beneficiaries from Section A (typically on pages before Section B)
            # Section A is usually 1-2 pages before Section B
            section_a_text = ""
            section_a_pages = [section_b_page - 2, section_b_page - 1, section_b_page]
            section_a_pages = [p for p in section_a_pages if 1 <= p <= page_count]
            for page_num in section_a_pages:
                page = pdf.pages[page_num - 1]
                page_text = page.extract_text() or ""
                section_a_text += page_text + "\n"

            beneficiaries = _extract_beneficiaries_from_text(section_a_text)
            if beneficiaries:
                result["beneficiaries"] = beneficiaries

    except Exception as e:
        logger.error(f"Error extracting from {pdf_path}: {e}")
        result["error"] = str(e)

    return result


def _extract_tables_with_fallback(page) -> list:
    """
    Extract tables from a page using multiple strategies.
    """
    tables = []

    # Strategy 1: Default table extraction
    try:
        default_tables = page.extract_tables()
        if default_tables:
            tables.extend(default_tables)
    except Exception as e:
        logger.debug(f"Default table extraction failed: {e}")

    # Strategy 2: Line-based table detection
    if not tables:
        try:
            table_settings = {
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 5,
                "intersection_tolerance": 15
            }
            line_tables = page.extract_tables(table_settings)
            if line_tables:
                tables.extend(line_tables)
        except Exception as e:
            logger.debug(f"Line-based table extraction failed: {e}")

    # Strategy 3: Text-based table detection
    if not tables:
        try:
            table_settings = {
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
            }
            text_tables = page.extract_tables(table_settings)
            if text_tables:
                tables.extend(text_tables)
        except Exception as e:
            logger.debug(f"Text-based table extraction failed: {e}")

    return tables


def _parse_activities_table(table_data: list, page_num: int) -> list:
    """
    Parse a table to extract activities and benefits.

    The Section B table typically has:
    - Header row with "Activities" and "How will the activity benefit..."
    - Data rows with activity descriptions and corresponding benefits
    """
    if not table_data or len(table_data) < 2:
        return []

    activities = []

    # Try to find header row
    header_idx = find_header_row(table_data)

    # Start from row after header
    start_row = header_idx + 1 if header_idx >= 0 else 0

    for row in table_data[start_row:]:
        if not row or len(row) < 2:
            continue

        # Clean cell values
        activity = clean_cell_text(row[0])
        benefit = clean_cell_text(row[1]) if len(row) > 1 else ""

        # Skip empty rows or continuation markers
        if not activity and not benefit:
            continue

        # Skip rows that look like headers or instructions
        if is_header_or_instruction(activity):
            continue

        activities.append({
            "activity": activity,
            "benefit": benefit,
            "source_page": page_num
        })

    return activities


def extract_text_fallback(pdf_path: str | Path, page_numbers: list) -> dict:
    """
    Fallback extraction using raw text when table extraction fails.
    Attempts to parse Section B content from page text.
    """
    pdf_path = Path(pdf_path)

    result = {
        "success": False,
        "activities": [],
        "raw_text": "",
        "extraction_method": "text_fallback"
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            text_parts = []
            for page_num in page_numbers:
                if 1 <= page_num <= len(pdf.pages):
                    page = pdf.pages[page_num - 1]
                    text = page.extract_text() or ""
                    text_parts.append(f"--- Page {page_num} ---\n{text}")

            full_text = "\n".join(text_parts)
            result["raw_text"] = full_text

            # Try to extract activities from text
            activities = _parse_text_for_activities(full_text)
            if activities:
                result["activities"] = activities
                result["success"] = True

    except Exception as e:
        logger.error(f"Error in text fallback extraction: {e}")
        result["error"] = str(e)

    return result


def _parse_text_for_activities(text: str) -> list:
    """
    Parse raw text to extract activities and benefits.
    Used as fallback when table extraction fails.
    """
    activities = []

    # Look for Section B content
    section_b_match = re.search(
        r'Section\s*B[:\s].*?Activities.*?Benefit(.*?)(?=Section\s*[C-Z]|$)',
        text,
        re.IGNORECASE | re.DOTALL
    )

    if section_b_match:
        content = section_b_match.group(1)
        lines = content.strip().split('\n')

        current_activity = ""
        for line in lines:
            line = line.strip()
            if line and not is_header_or_instruction(line):
                current_activity += " " + line

        if current_activity.strip():
            activities.append({
                "activity": current_activity.strip(),
                "benefit": "(extracted from raw text - manual review recommended)",
                "source_page": 0
            })

    return activities


def _extract_surplus_use_from_text(text: str) -> str:
    """
    Extract the surplus_use statement from page text.

    Looks for "If the company makes any surplus it will be used for..."
    or similar phrasings that appear after the activities table.
    """
    if not text:
        return ""

    # Patterns to find surplus statements (matching those in extract_scanned.py)
    start_patterns = [
        r'If\s+the\s+company\s+makes\s+any\s+surplus\s+it\s+will\s+be\s+used\s+for\s*[.:]?\s*',
        r'If\s+the\s+company\s+makes\s+any\s+surplus\s+it\s+will\s+be\s+reinvested\s*[.:]?\s*',
        r'Any\s+surplus\s+(?:gained|from\s+trading)\s+will\s+be\s+reinvested\s*[.:]?\s*',
        r'Any\s+surplus\s+(?:will\s+be|is)\s+(?:used|reinvested|invested)\s*[.:]?\s*',
        r'surplus\s+(?:it\s+)?will\s+be\s+(?:used|reinvested)\s*[.:]?\s*',
    ]

    # End markers
    end_patterns = [
        r'Section\s*C\b',
        r'SECTION\s*C\b',
        r'SIGNATORIES',
        r'\(Please\s+continue\s+on',
        r'CHECKLIST',
    ]

    for start_pattern in start_patterns:
        match = re.search(start_pattern, text, re.IGNORECASE)
        if match:
            remaining = text[match.end():]

            # Find end boundary
            end_pos = len(remaining)
            for end_pattern in end_patterns:
                end_match = re.search(end_pattern, remaining, re.IGNORECASE)
                if end_match:
                    end_pos = min(end_pos, end_match.start())
                    break

            content = remaining[:end_pos].strip()

            # Clean up
            content = re.sub(r'\s+', ' ', content)
            content = re.sub(r'^\s*[.:]?\s*', '', content)

            # Remove boilerplate
            boilerplate_patterns = [
                r"\(if donating or fundraising[^)]*\)",
                r"\(Please continue on separate[^)]*\)",
                r"COMPANY NAME\s*$",
            ]
            for bp in boilerplate_patterns:
                content = re.sub(bp, '', content, flags=re.IGNORECASE)

            content = content.strip()
            if content:
                return content

    return ""


def _extract_company_differs_from_text(text: str) -> str:
    """
    Extract the company_differs statement from page text.

    Looks for "Our company differs from a general commercial company because..."
    This is found in legacy CIC 36 forms (circa 2006).
    """
    if not text:
        return ""

    start_patterns = [
        r'Our\s+company\s+differs\s+from\s+a\s+general\s+commercial\s+company\s+because\s*[.:]?\s*',
        r'company\s+differs\s+from\s+a\s+(?:general\s+)?commercial\s+company\s+because\s*[.:]?\s*',
    ]

    end_patterns = [
        r'If\s+the\s+company\s+makes\s+any\s+surplus',
        r'Any\s+surplus',
        r'Section\s*C\b',
        r'SECTION\s*C\b',
        r'SIGNATORIES',
    ]

    for start_pattern in start_patterns:
        match = re.search(start_pattern, text, re.IGNORECASE)
        if match:
            remaining = text[match.end():]

            end_pos = len(remaining)
            for end_pattern in end_patterns:
                end_match = re.search(end_pattern, remaining, re.IGNORECASE)
                if end_match:
                    end_pos = min(end_pos, end_match.start())
                    break

            content = remaining[:end_pos].strip()
            content = re.sub(r'\s+', ' ', content)
            content = content.strip()

            if content:
                return content

    return ""


def _extract_beneficiaries_from_text(text: str) -> str:
    """
    Extract beneficiaries statement from Section A of CIC 36 form.

    Looks for text after "The company's activities will provide benefit to..."
    which appears in both modern and legacy CIC 36 forms.
    """
    if not text:
        return ""

    # Patterns to find the start of beneficiaries text
    start_patterns = [
        r"The\s+company'?s?\s+activities\s+will\s+provide\s+benefit\s+to\s*[.:]?\s*",
        r"activities\s+will\s+provide\s+benefit\s+to\s*[.:]?\s*",
        r"provide\s+benefit\s+to\s+the\s+following\s*:?\s*",
    ]

    # End markers - Section B header
    end_patterns = [
        r'Section\s*B\b',
        r'SECTION\s*B\b',
        r'Community\s+Interest\s+Statement\s*[-–—]?\s*Activities',
        r'COMPANY\s+ACTIVITIES',
    ]

    for start_pattern in start_patterns:
        match = re.search(start_pattern, text, re.IGNORECASE)
        if match:
            remaining = text[match.end():]

            # Find end boundary
            end_pos = len(remaining)
            for end_pattern in end_patterns:
                end_match = re.search(end_pattern, remaining, re.IGNORECASE)
                if end_match:
                    end_pos = min(end_pos, end_match.start())

            content = remaining[:end_pos].strip()

            # Clean up
            content = re.sub(r'\s+', ' ', content)
            content = re.sub(r'^\s*[.:]?\s*', '', content)

            # Remove trailing boilerplate
            boilerplate_patterns = [
                r'\s*Page\s+\d+\s*(?:of\s+\d+)?.*$',
                r'\s*Please\s+continue\s+on\s+separate\s+sheet.*$',
                r'\s*CIC\s*36.*$',
            ]
            for bp in boilerplate_patterns:
                content = re.sub(bp, '', content, flags=re.IGNORECASE)

            content = content.strip()

            # Strip the standard prefix boilerplate (per user requirement)
            # "The company's activities will provide benefit to..." should be removed
            prefix_patterns = [
                r"^(?:Pr\s+)?The\s+company['\u2019]?s?\s+activities\s+will\s+provide\s+benefit\s+to\s*\.{0,5}\s*",
                r"^activities\s+will\s+provide\s+benefit\s+to\s*\.{0,5}\s*",
                r"^provide\s+benefit\s+to\s*\.{0,5}\s*",
            ]
            for pattern in prefix_patterns:
                content = re.sub(pattern, '', content, flags=re.IGNORECASE)
            content = content.strip()

            if content:
                return content

    return ""


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 3:
        print("Usage: python extract_electronic.py <pdf_path> <section_b_page>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    page_num = int(sys.argv[2])

    result = extract_section_b_table(pdf_path, page_num)

    print(f"\nExtraction Results for: {pdf_path}")
    print(f"  Success: {result['success']}")
    print(f"  Pages Searched: {result['pages_searched']}")
    print(f"  Activities Found: {len(result['activities'])}")

    for i, act in enumerate(result['activities'], 1):
        print(f"\n  Activity {i}:")
        print(f"    Activity: {act['activity'][:100]}...")
        print(f"    Benefit: {act['benefit'][:100]}...")
