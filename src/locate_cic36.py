"""
CIC 36 Form Locator Module

Locates the CIC 36 form ("Declarations on Formation of a Community Interest Company")
within CIC incorporation documents, specifically finding Section B which contains
the Activities and Benefits table.
"""

import pdfplumber
from pathlib import Path
from typing import Optional
import re


# Patterns to identify CIC 36 form and Section B
# Enhanced patterns with high/medium confidence levels

# High confidence CIC 36 patterns
CIC36_PATTERNS_PRIMARY = [
    r"CIC\s*36",
    r"Form\s+CIC\s*36",
    r"Declarations?\s+on\s+Formation\s+of\s+a\s+Community\s+Interest\s+Company",
]

# Medium confidence CIC 36 patterns
CIC36_PATTERNS_SECONDARY = [
    r"Community\s+Interest\s+Statement",
    r"Declarations?\s+on\s+Formation",
]

# Combined for backwards compatibility
CIC36_PATTERNS = CIC36_PATTERNS_PRIMARY + CIC36_PATTERNS_SECONDARY

# High confidence Section B patterns
# The exact CIC 36 boilerplate header is:
# "SECTION B: Community Interest Statement - Activities & Related Benefit"
# Some documents use "SCHEDULE 2" instead of "SECTION B"
# Older forms (circa 2006) use "SECTION B: COMPANY ACTIVITIES" at the beginning
SECTION_B_PATTERNS_PRIMARY = [
    # Full exact header (highest confidence)
    r"SECTION\s*B\s*[:\-\.]?\s*Community\s+Interest\s+Statement\s*[-–—]?\s*Activities\s*(?:&|and)\s*Related\s*Benefit",
    # SCHEDULE 2 variant (alternative form format) - include period for OCR variations
    r"SCHEDULE\s*2\s*[:\-\.]?\s*Community\s+Interest\s+Statement",
    # Partial matches (still high confidence)
    r"Section\s*B[:\s\-\.]+Community\s+Interest\s+Statement",
    r"Section\s*B[:\s\-\.]+Activities\s*(?:&|and)\s*Related\s*Benefit",
    # Legacy CIC 36 patterns (circa 2006) - Section B at beginning of document
    r"SECTION\s*B\s*[:\-\.]?\s*COMPANY\s+ACTIVITIES",
    r"Section\s*B[:\s\-\.]+Company\s+Activities",
]

# Medium confidence Section B patterns
SECTION_B_PATTERNS_SECONDARY = [
    r"Activities\s*(?:&|and)\s*Related\s*Benefit",
    r"What\s+activities\s+will\s+the\s+(?:company|CIC)\s+carry\s+out",
    r"How\s+will\s+(?:the\s+)?activit(?:y|ies)\s+benefit\s+the\s+community",
]

# Table header patterns (for direct table matching)
SECTION_B_TABLE_PATTERNS = [
    r"Activities?\s*\|?\s*(?:How\s+will|Benefit)",
    r"Description\s+of\s+(?:the\s+)?Activities",
]

# Combined for backwards compatibility
SECTION_B_PATTERNS = SECTION_B_PATTERNS_PRIMARY + SECTION_B_PATTERNS_SECONDARY + SECTION_B_TABLE_PATTERNS

# Patterns to EXCLUDE (wrong sections) - helps reduce false positives
EXCLUDE_PATTERNS = [
    r"Section\s*A[:\s]",
    r"Section\s*C[:\s]",
    r"Memorandum\s+of\s+Association",
    r"Articles\s+of\s+Association",
    r"Certificate\s+of\s+Incorporation",
    r"Statement\s+of\s+Compliance",
]


def find_cic36_pages(pdf_path: str | Path, document_type: str = "electronic") -> dict:
    """
    Locate CIC 36 form pages within a PDF document.

    Args:
        pdf_path: Path to the PDF file
        document_type: 'electronic' or 'scanned' - affects extraction method

    Returns:
        Dictionary with:
        - cic36_pages: List of page numbers (1-indexed) containing CIC 36 form
        - section_b_page: Page number where Section B starts (or None)
        - confidence: 'high', 'medium', or 'low'
        - search_details: Additional information about the search
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    result = {
        "cic36_pages": [],
        "section_b_page": None,
        "confidence": "low",
        "search_details": {}
    }

    if document_type == "scanned":
        # For scanned documents, we'll need OCR - return placeholder for now
        # The actual OCR is handled in extract_scanned.py
        result["search_details"]["note"] = "Scanned document - requires OCR for accurate detection"
        result["search_details"]["suggested_pages"] = _guess_cic36_location_scanned(pdf_path)
        return result

    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            result["search_details"]["page_count"] = page_count

            cic36_matches = []
            section_b_matches = []
            section_b_confidence = {}  # Track confidence per page

            # Search each page for patterns
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""

                # Skip pages that match exclusion patterns
                is_excluded = any(re.search(p, text, re.IGNORECASE) for p in EXCLUDE_PATTERNS)

                # Check for CIC 36 form markers
                for pattern in CIC36_PATTERNS:
                    if re.search(pattern, text, re.IGNORECASE):
                        cic36_matches.append(page_num)
                        break

                # Check for Section B markers with confidence levels
                # Skip if page is clearly wrong section
                if not is_excluded or page_num not in cic36_matches:
                    # Check high confidence patterns first
                    for pattern in SECTION_B_PATTERNS_PRIMARY:
                        if re.search(pattern, text, re.IGNORECASE):
                            section_b_matches.append(page_num)
                            section_b_confidence[page_num] = "high"
                            break

                    # If no high confidence match, try secondary patterns
                    if page_num not in section_b_matches:
                        for pattern in SECTION_B_PATTERNS_SECONDARY:
                            if re.search(pattern, text, re.IGNORECASE):
                                section_b_matches.append(page_num)
                                section_b_confidence[page_num] = "medium"
                                break

                    # Try table patterns last
                    if page_num not in section_b_matches:
                        for pattern in SECTION_B_TABLE_PATTERNS:
                            if re.search(pattern, text, re.IGNORECASE):
                                section_b_matches.append(page_num)
                                section_b_confidence[page_num] = "low"
                                break

            # Remove duplicates and sort
            cic36_pages = sorted(set(cic36_matches))
            section_b_pages = sorted(set(section_b_matches))

            result["cic36_pages"] = cic36_pages
            result["search_details"]["section_b_candidates"] = section_b_pages

            # Determine Section B page (first match that's also a CIC 36 page or follows one)
            if section_b_pages:
                for sb_page in section_b_pages:
                    # Section B should be on or after a CIC 36 page
                    if any(sb_page >= c36_page for c36_page in cic36_pages):
                        result["section_b_page"] = sb_page
                        break
                if not result["section_b_page"]:
                    result["section_b_page"] = section_b_pages[0]

            # Determine confidence
            if cic36_pages and result["section_b_page"]:
                result["confidence"] = "high"
            elif cic36_pages or result["section_b_page"]:
                result["confidence"] = "medium"
            else:
                result["confidence"] = "low"
                # Try to guess based on document structure (usually near end)
                result["search_details"]["suggested_pages"] = list(range(max(1, page_count - 10), page_count + 1))

    except Exception as e:
        result["search_details"]["error"] = str(e)

    return result


def _guess_cic36_location_scanned(pdf_path: Path) -> list:
    """
    For scanned documents, guess likely CIC 36 form location.

    Modern forms (post-2006): Usually in the last 10-25 pages
    Legacy forms (circa 2006): Section B at the beginning of the document
    Mid-range: Some documents have CIC 36 in the middle (pages 35-65)

    Returns pages from all likely locations to handle various form versions.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)

            # Legacy forms (2006): Section B at beginning - first 15 pages
            legacy_pages = list(range(1, min(16, page_count + 1)))

            # Mid-range: For documents > 30 pages, search pages 35-65
            # This covers cases where CIC 36 is in the middle of large documents
            # (Manual evaluation showed failures on pages 39, 40, 52, 55, 60)
            mid_pages = []
            if page_count > 30:
                mid_start = 35
                mid_end = min(66, page_count + 1)
                mid_pages = list(range(mid_start, mid_end))

            # Modern forms: CIC 36 typically near the end - last 30 pages
            # Increased from 25 to catch more edge cases
            end_start = max(1, page_count - 30)
            modern_pages = list(range(end_start, page_count + 1))

            # Combine all ranges, removing duplicates while preserving order
            # Check beginning first (for legacy), then mid, then end (for modern)
            all_pages = legacy_pages.copy()
            for p in mid_pages:
                if p not in all_pages:
                    all_pages.append(p)
            for p in modern_pages:
                if p not in all_pages:
                    all_pages.append(p)
            return all_pages
    except:
        return []


def find_section_b_table_bounds(pdf_path: str | Path, page_number: int) -> Optional[dict]:
    """
    Find the bounds of the Section B table on a specific page.

    Args:
        pdf_path: Path to the PDF file
        page_number: 1-indexed page number to search

    Returns:
        Dictionary with table bounds or None if not found
    """
    pdf_path = Path(pdf_path)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return None

            page = pdf.pages[page_number - 1]

            # Find tables on the page
            tables = page.find_tables()

            for i, table in enumerate(tables):
                # The Section B table typically has 2 columns
                # Check if this looks like the activities/benefits table
                bbox = table.bbox  # (x0, y0, x1, y1)
                cells = table.cells

                # A valid Section B table should have at least 2 columns
                if len(cells) >= 2:
                    return {
                        "table_index": i,
                        "bbox": bbox,
                        "cell_count": len(cells),
                        "page_number": page_number
                    }

    except Exception as e:
        return {"error": str(e)}

    return None


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python locate_cic36.py <pdf_path> [document_type]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "electronic"

    result = find_cic36_pages(pdf_path, doc_type)

    print(f"\nCIC 36 Form Location Results for: {pdf_path}")
    print(f"  CIC 36 Pages: {result['cic36_pages']}")
    print(f"  Section B Page: {result['section_b_page']}")
    print(f"  Confidence: {result['confidence']}")
    print(f"  Details: {json.dumps(result['search_details'], indent=2)}")
