"""
Scanned PDF Extraction Module

Extracts Section B table data (Activities & Benefits) from scanned
CIC incorporation documents using OCR (pytesseract + pdf2image).

OCR Strategies:
1. Layout-aware OCR: Uses pytesseract.image_to_data() to get word bounding boxes,
   then separates left/right columns based on x-coordinates. Best for two-column tables.
2. Linear OCR: Uses pytesseract.image_to_string() for simpler pages or as fallback.
"""

from pathlib import Path
from typing import Optional
import re
import logging

import os
import platform

logger = logging.getLogger(__name__)

# Check for optional OpenCV support (Phase 2 image preprocessing)
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    import pytesseract

    # Configure Tesseract and Poppler paths for Windows if not in PATH
    if platform.system() == "Windows":
        # Tesseract configuration
        tesseract_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for tess_path in tesseract_paths:
            if os.path.exists(tess_path):
                pytesseract.pytesseract.tesseract_cmd = tess_path
                break

        # Poppler configuration - find and add to PATH
        poppler_search_paths = [
            r"C:\Program Files\poppler-25.12.0\Library\bin",
            r"C:\Program Files\poppler-24.08.0\Library\bin",
            r"C:\Program Files (x86)\poppler-25.12.0\Library\bin",
            r"C:\Program Files (x86)\poppler-24.08.0\Library\bin",
        ]
        # Also search for any poppler version in Program Files
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        from pathlib import Path
        for poppler_dir in Path(program_files).glob("poppler-*"):
            lib_bin = poppler_dir / "Library" / "bin"
            if lib_bin.exists():
                poppler_search_paths.insert(0, str(lib_bin))
            bin_dir = poppler_dir / "bin"
            if bin_dir.exists():
                poppler_search_paths.insert(0, str(bin_dir))

        for poppler_path in poppler_search_paths:
            if os.path.exists(poppler_path) and os.path.exists(os.path.join(poppler_path, "pdftoppm.exe")):
                # Add to PATH if not already there
                if poppler_path not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = poppler_path + os.pathsep + os.environ.get("PATH", "")
                break

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


def check_ocr_available() -> dict:
    """
    Check if OCR dependencies are available and properly configured.

    Returns:
        Dictionary with availability status and any error messages
    """
    result = {
        "available": False,
        "pdf2image": False,
        "pytesseract": False,
        "tesseract_binary": False,
        "poppler_binary": False,
        "errors": []
    }

    try:
        from pdf2image import convert_from_path
        result["pdf2image"] = True

        # Check if poppler (pdftoppm) is accessible
        import shutil
        if shutil.which("pdftoppm"):
            result["poppler_binary"] = True
        else:
            # Try common Windows paths
            poppler_paths = [
                r"C:\Program Files\poppler-25.12.0\Library\bin\pdftoppm.exe",
                r"C:\Program Files\poppler-24.08.0\Library\bin\pdftoppm.exe",
            ]
            for pp in poppler_paths:
                if os.path.exists(pp):
                    result["poppler_binary"] = True
                    break
            if not result["poppler_binary"]:
                result["errors"].append("Poppler not found. Install from: https://github.com/oschwartz10612/poppler-windows/releases")
    except ImportError:
        result["errors"].append("pdf2image not installed. Run: pip install pdf2image")

    try:
        import pytesseract
        result["pytesseract"] = True

        # Check if tesseract binary is accessible
        try:
            pytesseract.get_tesseract_version()
            result["tesseract_binary"] = True
        except Exception as e:
            result["errors"].append(f"Tesseract binary not found: {e}")
    except ImportError:
        result["errors"].append("pytesseract not installed. Run: pip install pytesseract")

    result["available"] = (result["pdf2image"] and result["pytesseract"] and
                           result["tesseract_binary"] and result["poppler_binary"])
    return result


# =============================================================================
# CIC 36 Form Detection
# =============================================================================

def _find_cic36_start_page(all_text: dict) -> int | None:
    """
    Find the page where CIC 36 form begins.

    CIC 36 forms are identified by markers on the FIRST page of the form:
    - "CIC 36" or "CIC36" as form title (not in brackets or as reference)
    - "Declarations on Formation of a Community Interest Company"
    - "Form CIC 36"

    Section B will be 2-5 pages AFTER this marker.

    Args:
        all_text: Dictionary of page_num -> OCR text

    Returns:
        Page number where CIC 36 form starts, or None if not found
    """
    # HIGH CONFIDENCE: "Declarations on Formation" is unique to CIC 36 form
    # This pattern should never appear in Articles of Association
    high_confidence_patterns = [
        r'Declarations?\s+on\s+Formation\s+of\s+a\s+Community\s+Interest\s+Company',
        r'Declaration\s+on\s+Formation.*Community\s+Interest',
        r'Form\s+CIC\s*36',
    ]

    # MEDIUM CONFIDENCE: "CIC 36" alone - but must verify it's a form title
    # NOT a reference like "[ Section A CIC36 ]" in Articles
    # The actual form has "CIC 36" on its own line or near "Declarations"
    medium_confidence_patterns = [
        # CIC 36 at start of line or after newline (form title position)
        r'(?:^|\n)\s*CIC\s*36\b',
        # CIC 36 followed by newline (standalone title)
        r'\bCIC\s*36\s*(?:\n|$)',
    ]

    # First pass: Look for high confidence patterns
    for page_num in sorted(all_text.keys()):
        text = all_text.get(page_num, "")
        if not isinstance(text, str):
            continue
        for pattern in high_confidence_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                logger.debug(f"CIC 36 form found on page {page_num} (high confidence)")
                return page_num

    # Second pass: Look for medium confidence patterns
    # But exclude pages that look like Articles of Association
    articles_markers = [
        r'\[\s*Section\s+[A-Z]\s+CIC',  # Reference like [ Section A CIC36 ]
        r'Articles\s+of\s+Association',
        r'Memorandum\s+of\s+Association',
    ]

    for page_num in sorted(all_text.keys()):
        text = all_text.get(page_num, "")
        if not isinstance(text, str):
            continue

        # Skip if page looks like Articles
        is_articles = any(re.search(p, text, re.IGNORECASE) for p in articles_markers)
        if is_articles:
            continue

        for pattern in medium_confidence_patterns:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                logger.debug(f"CIC 36 form found on page {page_num} (medium confidence)")
                return page_num

    return None


def _find_section_a_page(all_text: dict) -> int | None:
    """
    Find the page containing Section A (beneficiaries) header directly.
    
    This is a fallback when CIC 36 marker detection fails.
    Searches for Section A header patterns in all OCR'd pages.
    
    Args:
        all_text: Dictionary of page_num -> OCR text
        
    Returns:
        Page number containing Section A header, or None if not found
    """
    # Section A header patterns
    section_a_patterns = [
        # Modern form: "SECTION A: COMMUNITY INTEREST STATEMENT - beneficiaries"
        r'SECTION\s*A[:\s]+COMMUNITY\s+INTEREST\s+STATEMENT',
        r'Section\s*A[:\s]+Community\s+Interest\s+Statement',
        # Legacy form: "SECTION A: DECLARATIONS ON FORMATION"
        r'SECTION\s*A[:\s]+DECLARATIONS\s+ON\s+FORMATION',
        # Standalone beneficiaries header
        r'COMMUNITY\s+INTEREST\s+STATEMENT\s*[-–—]?\s*beneficiaries',
        # OCR variations with I/1 confusion
        r'SECT[I1]ON\s*A[:\s]+(?:COMMUNITY|DECLARATIONS)',
    ]
    
    for page_num in sorted(all_text.keys()):
        text = all_text.get(page_num, "")
        if not isinstance(text, str):
            continue
        for pattern in section_a_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                logger.debug(f"Section A found on page {page_num}")
                return page_num
    
    return None



def _validate_cic36_content(activities: list, text: str) -> dict:
    """
    Validate that extracted content is from CIC 36, not IN01 or other forms.

    Args:
        activities: List of extracted activity dictionaries
        text: Combined text from Section B pages

    Returns:
        Dictionary with 'valid' boolean and 'reason' if invalid
    """
    # Check for IN01 patterns in extracted content
    in01_patterns = [
        r'Application\s+to\s+register\s+a\s+company',
        r'Proposed\s+officers',
        r'appointment\s+of\s+a\s+secretary',
        r'For\s+a\s+secretary\s+who\s+is\s+an\s+individual',
        r'go\s+to\s+Section\s+[BC]\d',
        r'Private\s+companies\s+must\s+appoint',
        r'Public\s+companies\s+are\s+required',
    ]

    combined_text = text or ""
    for act in activities:
        combined_text += " " + str(act.get("activity", ""))
        combined_text += " " + str(act.get("benefit", "") or act.get("description", ""))

    for pattern in in01_patterns:
        if re.search(pattern, combined_text, re.IGNORECASE):
            return {"valid": False, "reason": "IN01 form content detected"}

    # Check for expected CIC 36 content markers (at least one should be present)
    cic36_markers = [
        r'community',
        r'benefit',
        r'activit',
        r'surplus',
        r'differs?\s+from',
    ]
    markers_found = sum(1 for p in cic36_markers
                        if re.search(p, combined_text, re.IGNORECASE))

    if markers_found < 1 and len(combined_text) > 100:
        return {"valid": False, "reason": "Content doesn't look like CIC 36 Section B"}

    return {"valid": True}


def _strip_section_b_boilerplate(text: str) -> str:
    """
    Remove Section B boilerplate instructions from OCR text.

    This should be called early, before activity parsing, to remove
    the instruction paragraph and column headers that appear before
    the actual table content.

    Boilerplate to remove:
    - "Please indicate how it is proposed that the company's activities..."
    - Column headers like "Activities (Please provide the day to day...)"
    - Surplus instruction "(If donating to a non-nominated Asset Locked Body...)"
    - Legacy form (circa 2006): "SECTION B: COMPANY ACTIVITIES" header and instructions
    - Legacy form: "Our company differs from a general commercial company because..."
    """
    if not text:
        return ""

    # Main Section B instruction paragraph (various OCR variations)
    # This is the paragraph that appears above the table
    # NOTE: Patterns are applied in order - put more specific patterns FIRST
    instruction_patterns = [
        # LEGACY FORM (circa 2006) instruction patterns - MUST come first
        # These are more specific and should match before the general patterns
        # "Please indicate how it is proposed...to enable the Regulator to make a properly informed decision"
        r'Please\s+indicate\s+how\s+i[tf]\s+is\s+proposed\s+that\s+the\s+company.{0,30}activities\s+will\s+benefit\s+the\s+community.*?(?:community\s+interest\s+company|See\s+note\s+\d)[^)]*\)?\.?',
        r'Please\s+provide\s+as\s+much\s+detail\s+as\s+possible\s+to\s+enable\s+the\s+Regulator.*?(?:community\s+interest\s+company|See\s+note)[^)]*\)?\.?',
        r'to\s+enable\s+the\s+Regulator\s+to\s+make\s+a\s+properly\s+informed\s+decision.*?(?:community\s+interest\s+company|See\s+note)[^)]*\)?\.?',
        # Fragments from legacy form
        r'\(or\s+a\s+section\s+of\s+the\s+community\)',
        r'\(See\s+note\s+\d+\)\.?',

        # MODERN FORM - Full paragraph match - most comprehensive
        r'Please\s+indicate\s+how\s+i[tf]\s+is\s+proposed\s+that\s+the\s+company.{0,30}activities\s+will\s+benefit\s+the\s+community.*?(?:individual|personal)\s*,?\s*gain\.?',

        # Partial matches for OCR variations - these need to be CAREFUL not to over-match
        # Only match "commercial company" when it's in the specific boilerplate phrase context
        r'Please\s+indicate\s+how\s+i[tf]\s+is\s+proposed.*?different\s+from\s+a\s+commercial\s+company\s+providing\s+similar[^.]*\.?',
        r'We\s+would\s+find\s+i[tf]\s+useful\s+if\s+you.*?for\s+(?:individual|personal)\s*,?\s*gain\.?',
        r'Please\s+provide\s+as\s+much\s+detail\s+as\s+possible.*?(?:set\s+up\s+to\s+do|being\s+set\s+up)[^.]*\.?',
        r'to\s+enable\s+the\s+CIC\s+Regulator\s+to\s+make\s+an\s+informed\s+decision.*?(?:community\s+interest|eligible)[^.]*\.?',

        # Catch fragments that may appear due to OCR splitting
        r'(?:a\s+)?section\s+of\s+the\s+community\.\s*Please\s+provide\s+as\s+much\s+detail',
        r'eligible\s+to\s+become\s+a\s+community\s+interest\s+company[^.]*\.?',
        r'different\s+from\s+a\s+commercial\s+company\s+providing\s+similar\s+services[^.]*\.?',

        # OCR-MANGLED instruction fragments (words get jumbled/substituted)
        # These catch boilerplate that OCR has corrupted
        r'i[tf]\s+would\s+(?:be\s+)?(?:useful|think)\s+if\s+you[^.]*\.?',
        r'your\s+company\s+will\s+be\s+different\s+from\s+a[^.]*(?:products?|services?)[^.]*\.?',
        r'commercial\s+company\s+providing\s+similar[^.]*\.?',
        r'for\s+individual\s*,?\s*(?:or\s+)?personal\s+gain\.?',
        r'\.?\s*I[tf]\s+would\s+think\s+your\s+company[^.]*\.?',
        r'would\s+be\s+different\s+from\s+a\s+(?:commercial\s+)?company[^.]*\.?',
        # Leading boilerplate fragments at start of extracted text
        r'^\.?\s*I[tf]\s+would\s+(?:be\s+)?(?:useful|think)[^.]{0,50}',
        r'^\.?\s*would\s+(?:be\s+)?(?:useful|think)[^.]{0,50}',
    ]

    # Column headers - these appear as table headers
    column_header_patterns = [
        # Modern form - Activities column header
        r'Activities\s*\(?\s*Please\s+provide\s+the\s+day\s+to\s+day\s+activities[^)]*\)?',
        r'\(Please\s+provide\s+the\s+day\s+to\s+day\s+activities[^)]*\)',
        r'Tell\s+us\s+here\s+what\s+the\s+company.*?is\s+being\s+set\s+up\s+to\s+do[^)]*\)?',
        # Modern form - Benefit column header
        r'How\s+will\s+the\s+activity\s+benefit\s+the\s+community\s*\??\s*\(?\s*The\s+community\s+will\s+benefit\s+by[^)]*\)?',
        r'\(The\s+community\s+will\s+benefit\s+by[^)]*\)',
        r'The\s+community\s+will\s+benefit\s+by\s*\.{0,3}\s*\)',

        # LEGACY FORM column headers
        r'Activities\s+How\s+each\s+activity\s+benefits\s+the\s+community',
        r'Activities\s+How\s+each\s+activity\s+benefits[^a-zA-Z]*',
        r'^How\s+each\s+activity\s+benefits\s+the\s+community\s*$',
        r'^\s*the\s+community\s*$',  # Orphaned fragment after partial header match
        # Alternative legacy column headers
        r'Activities\s+How\s+will\s+the\s+activity\s+benefit\s+the\s+community\s*\??',
        r'\(Tell\s+us\s+here\s+what\s+the\s+company\s*\(?The\s+community\s+will\s+benefit\s+by[^)]*\)?\s*\)?',
        r'\(Tell\s+us\s+here\s+what\s+the\s+company',
        r'is\s+being\s+set\s+up\s+to\s+do\)',
        r'\(The\s+community\s+will\s+benefit\s+by\.\.\.\)',
        # OCR-mangled column headers (words jumbled mid-text)
        r'Activities\s+How\s+will\b',
        r'How\s+will\s+the\s+activity\s+benefit\b',
        r'^\s*Activities\s*$',  # Orphaned "Activities" on its own line
        r'^\s*How\s+will\s*$',  # Orphaned "How will"
    ]

    # Surplus instruction boilerplate
    surplus_instruction_patterns = [
        r'\(If\s+donating\s+to\s+a\s+non-nominated\s+Asset\s+Locked\s+Body[^)]*\)',
        r'If\s+donating\s+to\s+a\s+non-nominated.*?(?:rejected|Regulator)[^.]*\.?',
        r"you\s+will\s+need\s+to\s+include\s+the\s+wording\s*['\"]?with\s+the\s+consent[^.]*\.?",
    ]

    # LEGACY FORM "company differs" boilerplate
    # This is the row label that appears below the table in legacy forms
    company_differs_boilerplate = [
        r'Our\s+company\s+differs\s+from\s+a\s+general\s+commercial\s+company\s+because[:\s]*\.{0,3}',
        r'Our\s+company\s+differs\s+from\s+a\s+(?:general\s+)?commercial\s+company\s+because',
    ]

    # Section headers (should be removed, keeping only content)
    section_header_patterns = [
        # Legacy form section header
        r'SECTION\s+B\s*:\s*COMPANY\s+ACTIVITIES\s*',
        # Modern form section header (if it appears)
        r'SECTION\s+B\s*:\s*Community\s+Interest\s+Statement\s*[-–—]?\s*Activities\s*(?:&|and)?\s*Related\s+Benefit\s*',
        r'Community\s+Interest\s+Statement\s*[-–—]?\s*Activities\s*(?:&|and)?\s*Related\s+Benefit\s*',
    ]

    # Other form boilerplate
    other_boilerplate = [
        r'Please\s+continue\s+on\s+separate\s+sheet\s+if\s+necessary',
        r'COMPANY\s+NAME\s+.*?Community\s+Interest\s+Company\s*\]?',
        r'COMPANY\s+NAME\s+[^\n]+\s*\n?',  # Company name line at start of page
        r'The\s+company\s+name\s+will\s+need\s+to\s+be\s+consistent\s+throughout',
        # Form title headers
        r'Declarations?\s+on\s+Formation\s+of\s+a\s*\n?\s*Community\s+[Ii]nterest\s+Company',
        r'^\s*\]\s*$',  # Orphaned bracket from company name match
        # Full instruction paragraph that may not match other patterns
        r'Please\s+indicate\s+how\s+i[tf]\s+[1i]s\s+proposed\s+that\s+the\s+company.{0,30}activities\s+will\s+benefit[^.]*\.',
        r'Please\s+provide\s+as\s+much\s+detail\s+as\s+possible[^.]*\.',
        r'a\s+section\s+of\s+the\s+community\s*\.\s*',
    ]

    # Apply all patterns
    all_patterns = (instruction_patterns + column_header_patterns +
                    surplus_instruction_patterns + company_differs_boilerplate +
                    section_header_patterns + other_boilerplate)
    for pattern in all_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)

    # Clean up extra whitespace left behind
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'  +', ' ', text)
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)

    # Clean up orphaned punctuation from pattern removal
    text = re.sub(r'^\s*[(\[\])\s]+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\(\s*$', '', text, flags=re.MULTILINE)

    return text.strip()


# =============================================================================
# Layout-Aware OCR Functions (Phase 1)
# =============================================================================

def _extract_with_layout_ocr(image) -> dict:
    """
    Extract text from an image using layout-aware OCR.

    Uses pytesseract.image_to_data() to get word bounding boxes, then
    separates text into left and right columns based on x-coordinates.
    This is much more reliable for two-column tables than linear OCR.

    Args:
        image: PIL Image object

    Returns:
        Dictionary with:
        - linear_text: Full text in reading order (for Section B detection)
        - left_column: Text from left side of page
        - right_column: Text from right side of page
        - has_two_columns: Boolean indicating if two-column layout detected
        - column_boundary: X-coordinate used as column separator
    """
    result = {
        "linear_text": "",
        "left_column": "",
        "right_column": "",
        "has_two_columns": False,
        "column_boundary": 0
    }

    if not OCR_AVAILABLE:
        return result

    try:
        # Get OCR data with bounding boxes
        # PSM 6 (single uniform block) often works better for forms
        custom_config = '--psm 6'
        data = pytesseract.image_to_data(image, config=custom_config, output_type=pytesseract.Output.DICT)

        # Convert to structured format
        words = []
        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            conf = int(data['conf'][i]) if data['conf'][i] != '-1' else 0

            # Skip empty text and very low confidence words
            if not text or conf < 20:
                continue

            words.append({
                'text': text,
                'left': data['left'][i],
                'top': data['top'][i],
                'width': data['width'][i],
                'height': data['height'][i],
                'conf': conf,
                'line_num': data['line_num'][i],
                'block_num': data['block_num'][i],
            })

        if not words:
            # Fallback to linear OCR
            result["linear_text"] = pytesseract.image_to_string(image)
            return result

        # Calculate page dimensions and potential column boundary
        page_width = image.width
        midpoint = page_width / 2

        # Analyze x-positions to detect two-column layout
        # For two-column tables, words should cluster around two x-positions
        left_words = []
        right_words = []

        for word in words:
            word_center = word['left'] + word['width'] / 2

            # Use midpoint as initial boundary
            if word_center < midpoint:
                left_words.append(word)
            else:
                right_words.append(word)

        # Check if we have a valid two-column layout
        # Both columns should have substantial content
        left_text_len = sum(len(w['text']) for w in left_words)
        right_text_len = sum(len(w['text']) for w in right_words)

        # Heuristic: two-column if both sides have >15% of content
        total_len = left_text_len + right_text_len
        if total_len > 0:
            left_ratio = left_text_len / total_len
            right_ratio = right_text_len / total_len

            if left_ratio > 0.15 and right_ratio > 0.15:
                result["has_two_columns"] = True
                result["column_boundary"] = midpoint

        # Build linear text (for Section B header detection)
        sorted_words = sorted(words, key=lambda w: (w['top'], w['left']))
        result["linear_text"] = ' '.join(w['text'] for w in sorted_words)

        # Build column texts if two-column layout detected
        if result["has_two_columns"]:
            # Sort each column by vertical position, then horizontal
            left_sorted = sorted(left_words, key=lambda w: (w['top'], w['left']))
            right_sorted = sorted(right_words, key=lambda w: (w['top'], w['left']))

            # Group words into lines based on vertical position
            result["left_column"] = _reconstruct_text_from_words(left_sorted)
            result["right_column"] = _reconstruct_text_from_words(right_sorted)
        else:
            # Single column - use linear text for both
            result["left_column"] = result["linear_text"]
            result["right_column"] = ""

    except Exception as e:
        logger.debug(f"Layout OCR failed, falling back to linear: {e}")
        try:
            result["linear_text"] = pytesseract.image_to_string(image)
        except Exception as e2:
            logger.error(f"Both layout and linear OCR failed: {e2}")

    return result


def _reconstruct_text_from_words(words: list, line_threshold: int = 15) -> str:
    """
    Reconstruct readable text from a list of word dictionaries.

    Groups words into lines based on vertical position, then joins them.

    Args:
        words: List of word dictionaries with 'text', 'top', 'left' keys
        line_threshold: Pixel difference to consider words on same line

    Returns:
        Reconstructed text with line breaks
    """
    if not words:
        return ""

    # Sort by vertical position first
    sorted_words = sorted(words, key=lambda w: (w['top'], w['left']))

    lines = []
    current_line = []
    current_top = sorted_words[0]['top']

    for word in sorted_words:
        # Check if this word is on a new line
        if abs(word['top'] - current_top) > line_threshold:
            # Finish current line
            if current_line:
                # Sort words in line by horizontal position
                current_line.sort(key=lambda w: w['left'])
                line_text = ' '.join(w['text'] for w in current_line)
                lines.append(line_text)
            current_line = [word]
            current_top = word['top']
        else:
            current_line.append(word)

    # Don't forget the last line
    if current_line:
        current_line.sort(key=lambda w: w['left'])
        line_text = ' '.join(w['text'] for w in current_line)
        lines.append(line_text)

    return '\n'.join(lines)


def _preprocess_image_for_ocr(image):
    """
    Preprocess image to improve OCR quality (Phase 2 - requires OpenCV).

    Applies:
    - Grayscale conversion
    - Adaptive thresholding for better contrast
    - Noise reduction

    Args:
        image: PIL Image object

    Returns:
        Preprocessed PIL Image, or original if OpenCV not available
    """
    if not CV2_AVAILABLE:
        return image

    try:
        import numpy as np
        from PIL import Image

        # Convert PIL to OpenCV format
        img_array = np.array(image)

        # Convert to grayscale if needed
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # Apply adaptive thresholding
        # This helps with uneven lighting and faded scans
        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2
        )

        # Optional: Noise reduction with median blur
        # Use small kernel to preserve text detail
        denoised = cv2.medianBlur(thresh, 3)

        # Convert back to PIL
        return Image.fromarray(denoised)

    except Exception as e:
        logger.debug(f"Image preprocessing failed: {e}")
        return image


# =============================================================================
# Main Extraction Functions
# =============================================================================

def extract_section_b_ocr(pdf_path: str | Path, page_numbers: list,
                          dpi: int = 200) -> dict:
    """
    Extract Section B content from scanned PDF pages using OCR.

    Args:
        pdf_path: Path to the PDF file
        page_numbers: List of 1-indexed page numbers to process
        dpi: DPI for image conversion (default 200 - better reliability than 300)

    Returns:
        Dictionary with:
        - success: Boolean indicating extraction success
        - activities: List of {activity, benefit} dictionaries
        - raw_text: Raw OCR text for debugging
        - extraction_method: 'ocr_pytesseract'
        - pages_processed: List of page numbers processed
    """
    pdf_path = Path(pdf_path)

    result = {
        "success": False,
        "activities": [],
        "raw_text": {},
        "extraction_method": "ocr_pytesseract",
        "pages_processed": []
    }

    if not OCR_AVAILABLE:
        result["error"] = "OCR dependencies not available. Install pytesseract and pdf2image."
        return result

    if not pdf_path.exists():
        result["error"] = f"PDF not found: {pdf_path}"
        return result

    try:
        # Convert specified pages to images and perform OCR
        all_text = {}  # Standard OCR text for CIC 36/Section B header detection
        all_layout_data = {}  # Layout-aware data for column separation (table parsing)

        for page_num in page_numbers:
            try:
                # Convert single page (pdf2image uses 1-indexed pages)
                images = convert_from_path(
                    str(pdf_path),
                    first_page=page_num,
                    last_page=page_num,
                    dpi=dpi
                )

                if images:
                    image = images[0]
                    original_image = image  # Keep original for standard OCR

                    # Apply image preprocessing for layout OCR (Phase 2)
                    # Note: Don't use preprocessing for standard OCR as it can
                    # affect reading order and cause column interleaving
                    preprocessed_image = image
                    if CV2_AVAILABLE:
                        preprocessed_image = _preprocess_image_for_ocr(image)

                    # Use STANDARD OCR on ORIGINAL image for header detection
                    # Preserves reading order needed for surplus extraction
                    standard_text = pytesseract.image_to_string(original_image)

                    # DPI fallback: if OCR returns very short text, retry at different DPI
                    # Some pages OCR poorly at certain DPI values
                    if len(standard_text.strip()) < 50:
                        fallback_dpis = [150, 250, 300] if dpi == 200 else [200, 150, 250]
                        for fallback_dpi in fallback_dpis:
                            try:
                                fallback_images = convert_from_path(
                                    str(pdf_path),
                                    first_page=page_num,
                                    last_page=page_num,
                                    dpi=fallback_dpi
                                )
                                if fallback_images:
                                    fallback_text = pytesseract.image_to_string(fallback_images[0])
                                    if len(fallback_text.strip()) > len(standard_text.strip()):
                                        standard_text = fallback_text
                                        image = fallback_images[0]
                                        logger.debug(f"Page {page_num}: DPI fallback {fallback_dpi} improved OCR ({len(fallback_text)} chars)")
                                        break
                            except:
                                pass

                    all_text[page_num] = standard_text

                    # Use layout-aware OCR for table column separation
                    layout_result = _extract_with_layout_ocr(preprocessed_image)
                    all_layout_data[page_num] = layout_result

                    result["pages_processed"].append(page_num)

            except Exception as e:
                logger.debug(f"OCR failed for page {page_num}: {e}")
                result["raw_text"][f"page_{page_num}_error"] = str(e)

        result["raw_text"] = all_text

        # STEP 1: Find where CIC 36 form starts
        # This ensures we search for Section B in the right place (not in IN01 form)
        cic36_start_page = _find_cic36_start_page(all_text)
        result["cic36_start_page"] = cic36_start_page

        # STEP 1.5: Extract Section A beneficiaries
        # First try CIC 36 start page, then fallback to searching all pages
        beneficiaries = ""
        if cic36_start_page and cic36_start_page in all_text:
            section_a_text = all_text.get(cic36_start_page, "")
            next_page = cic36_start_page + 1
            if next_page in all_text:
                section_a_text += "\n" + all_text.get(next_page, "")
            beneficiaries = _extract_beneficiaries(section_a_text)
            if beneficiaries:
                logger.debug(f"Extracted beneficiaries from CIC 36 page {cic36_start_page}")

        # Fallback: Search ALL pages for Section A header directly
        if not beneficiaries:
            section_a_page = _find_section_a_page(all_text)
            if section_a_page:
                section_a_text = all_text.get(section_a_page, "")
                next_page = section_a_page + 1
                if next_page in all_text:
                    section_a_text += "\n" + all_text.get(next_page, "")
                beneficiaries = _extract_beneficiaries(section_a_text)
                if beneficiaries:
                    logger.debug(f"Extracted beneficiaries from Section A page {section_a_page}")

        result["beneficiaries"] = beneficiaries

        if cic36_start_page:
            logger.debug(f"CIC 36 form found starting on page {cic36_start_page}")
            # Search for Section B only on pages AFTER the CIC 36 marker
            section_b_pages = _find_section_b_pages(all_text, cic36_start_page)
        else:
            # Fallback: No CIC 36 marker found, search all pages but use strict patterns
            logger.debug("No CIC 36 marker found, using fallback search")
            section_b_pages = _find_section_b_pages(all_text, None)

        # If Section B pages found, parse only those
        if section_b_pages:
            section_b_text_raw = "\n".join(all_text[p] for p in section_b_pages if p in all_text)
            # Strip boilerplate instructions before parsing
            section_b_text = _strip_section_b_boilerplate(section_b_text_raw)
            result["section_b_pages"] = section_b_pages

            # Check if any Section B pages have two-column layout
            has_layout_data = any(
                all_layout_data.get(p, {}).get("has_two_columns", False)
                for p in section_b_pages
            )
            if has_layout_data:
                result["extraction_method"] = "ocr_pytesseract_layout"
                # Store column data for parsing
                result["layout_data"] = {
                    p: all_layout_data[p]
                    for p in section_b_pages
                    if p in all_layout_data
                }
        else:
            # NO Section B found - do NOT blindly use all text
            # This prevents extracting wrong content (e.g., Articles of Association)
            result["section_b_not_found"] = True
            if cic36_start_page:
                result["error"] = f"CIC 36 form found on page {cic36_start_page} but Section B not detected on following pages"
            else:
                result["error"] = "No CIC 36 form found in document"
                result["extraction_status"] = "no_cic36_form"
            return result

        # Parse extracted text for activities and benefits
        # Use layout-aware parsing if we have column data
        if result.get("layout_data"):
            activities = _parse_ocr_with_layout(result["layout_data"], section_b_text, section_b_text_raw)
        else:
            activities = _parse_ocr_text_for_activities(section_b_text)

        # Check OCR quality on the extracted text
        ocr_quality = _check_ocr_quality(section_b_text)
        result["ocr_quality"] = ocr_quality

        # Check for handwritten content
        if _is_likely_handwritten(section_b_text):
            result["handwritten_content"] = True
            result["note"] = "Handwritten content detected - manual review required"
            # Still attempt extraction but flag it
            for act in activities if activities else []:
                act["handwritten"] = True

        if activities:
            # Check if content is from wrong section (e.g., IN01 form)
            # Use new validation function that checks both activities and full text
            validation = _validate_cic36_content(activities, section_b_text)
            if not validation["valid"]:
                result["error"] = f"Wrong section detected - {validation['reason']}"
                result["wrong_section"] = True
                result["extraction_status"] = "wrong_section"
                result["activities"] = []  # Clear the wrong content
                return result

            # Check if OCR quality is too low to trust
            if ocr_quality == "very_low":
                result["ocr_quality_issue"] = True
                result["note"] = "Very low OCR quality - manual review recommended"
                # Still include activities but mark them as unreliable
                for act in activities:
                    act["ocr_confidence"] = "very_low"

            # Check if the extracted content is just referential ("Please see attached")
            if _is_referential_content(activities):
                # Search for standalone Section B content in remaining pages
                standalone_activities = _find_standalone_section_b(all_text, section_b_pages)
                if standalone_activities:
                    result["activities"] = standalone_activities
                    result["success"] = True
                    result["extraction_method"] = "ocr_pytesseract_standalone"
                    result["note"] = "Content found via 'see attached' reference"
                else:
                    # Keep original but mark as potentially incomplete
                    result["activities"] = activities
                    result["success"] = True
                    result["note"] = "Content may be referential - check for attached pages"
            else:
                result["activities"] = activities
                result["success"] = True
        else:
            # Try alternative parsing strategies
            activities = _parse_ocr_text_alternative(section_b_text)
            if activities:
                result["activities"] = activities
                result["success"] = True
                result["extraction_method"] = "ocr_pytesseract_alternative"

    except Exception as e:
        result["error"] = str(e)

    return result


def _check_ocr_quality(text: str) -> str:
    """
    Assess OCR quality based on text characteristics.

    Returns:
        'very_low' - garbled/unreadable text
        'low' - some quality issues
        'medium' - acceptable quality
        'high' - good quality (rare for scanned docs)
    """
    if not text or len(text.strip()) < 50:
        return "very_low"

    # Count vowels and consonants
    text_lower = text.lower()
    vowels = sum(1 for c in text_lower if c in 'aeiou')
    consonants = sum(1 for c in text_lower if c in 'bcdfghjklmnpqrstvwxyz')
    letters = vowels + consonants

    if letters == 0:
        return "very_low"

    # English typically has ~38% vowels
    vowel_ratio = vowels / letters if letters > 0 else 0

    # Check for common English words
    common_words = ['the', 'and', 'for', 'will', 'community', 'be', 'to', 'of', 'is', 'in', 'that', 'with', 'by', 'as', 'are', 'from']
    words_found = sum(1 for word in common_words if re.search(r'\b' + word + r'\b', text_lower))

    # Check for excessive special characters (excluding normal punctuation)
    special_chars = sum(1 for c in text if c in '{}[]|\\<>~`^@#$%&*+=')
    special_ratio = special_chars / len(text) if len(text) > 0 else 0

    # Check for consecutive consonants (garbled text often has long consonant runs)
    long_consonant_runs = len(re.findall(r'[bcdfghjklmnpqrstvwxyz]{6,}', text_lower))

    # Determine quality
    if (vowel_ratio < 0.15 or vowel_ratio > 0.65 or
        words_found < 3 or
        special_ratio > 0.1 or
        long_consonant_runs > 3):
        return "very_low"

    if (vowel_ratio < 0.25 or vowel_ratio > 0.55 or
        words_found < 6 or
        special_ratio > 0.05 or
        long_consonant_runs > 1):
        return "low"

    if words_found >= 10:
        return "medium"

    return "low"


def _is_likely_handwritten(text: str) -> bool:
    """
    Detect likely handwritten content based on OCR characteristics.

    Handwritten OCR typically has:
    - Very few recognizable common words
    - High proportion of short word fragments (1-2 chars)
    - Unusual character sequences
    - Low overall coherence

    Returns:
        True if text appears to be from handwritten content
    """
    if not text or len(text.strip()) < 50:
        return False

    words = text.split()
    if not words:
        return False

    # Check for short word fragments (handwriting often OCRs as fragments)
    short_words = sum(1 for w in words if len(w) <= 2)
    short_ratio = short_words / len(words)

    # Check for common English words that should appear in CIC forms
    common_words = ['the', 'and', 'for', 'will', 'community', 'be', 'to', 'of',
                    'is', 'in', 'that', 'with', 'by', 'as', 'are', 'from',
                    'company', 'benefit', 'activity', 'activities', 'section']
    text_lower = text.lower()
    words_found = sum(1 for word in common_words if re.search(r'\b' + word + r'\b', text_lower))

    # Expected common words based on text length (~1 per 100 chars for printed text)
    expected_common_words = len(text) / 100

    # Handwriting indicators:
    # 1. >40% short fragments AND <5 common words found
    if short_ratio > 0.4 and words_found < 5:
        return True

    # 2. Very low common word density relative to text length
    if expected_common_words > 2 and words_found < expected_common_words * 0.3:
        return True

    # 3. Check for characteristic handwriting OCR errors
    # Handwriting often produces unusual character combinations
    unusual_patterns = [
        r'[bcdfghjklmnpqrstvwxyz]{5,}',  # Long consonant runs
        r'[aeiou]{4,}',  # Long vowel runs
        r'\|{2,}',  # Multiple pipe characters (common OCR error for handwriting)
    ]
    unusual_count = sum(len(re.findall(p, text_lower)) for p in unusual_patterns)
    if unusual_count > 5:
        return True

    return False


def _is_wrong_section_content(activities: list) -> bool:
    """
    Check if extracted content is from the wrong form section.

    Returns True if content appears to be from IN01 (company registration form)
    or other non-CIC36 sections that have "Section B" headings.
    """
    if not activities:
        return False

    # Patterns that indicate IN01 form (company registration) content
    wrong_section_patterns = [
        r'Application\s+to\s+register\s+a\s+company',
        r'Proposed\s+officers',
        r'appointment\s+of\s+a\s+secretary',
        r'For\s+a\s+secretary\s+who\s+is\s+an\s+individual',
        r'Private\s+companies\s+must\s+appoint',
        r'Public\s+companies\s+are\s+required',
        r'For\s+a\s+corporate\s+secretary',
        r'go\s+to\s+Section\s+[BC]\d',  # "go to Section B1", "go to Section C2"
    ]

    # Check all activities
    for act in activities:
        activity_text = str(act.get("activity", ""))
        benefit_text = str(act.get("description", "") or act.get("benefit", ""))
        combined = activity_text + " " + benefit_text

        for pattern in wrong_section_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return True

    return False


def _is_referential_content(activities: list) -> bool:
    """
    Check if extracted activities are just referential ("Please see attached").

    Returns True if content appears to just reference attached documents
    rather than containing actual activity descriptions.
    """
    if not activities:
        return False

    referential_patterns = [
        r'please\s+see\s+attached',
        r'see\s+attached',
        r'refer\s+to\s+attached',
        r'as\s+per\s+attached',
        r'attached\s+(?:appendix|schedule|document)',
    ]

    # Check all activities
    for act in activities:
        activity_text = str(act.get("activity", "")).lower()
        benefit_text = str(act.get("benefit", "")).lower()
        combined = activity_text + " " + benefit_text

        for pattern in referential_patterns:
            if re.search(pattern, combined):
                # If found and content is short, it's likely just a reference
                if len(combined.strip()) < 300:
                    return True

    return False


def _find_standalone_section_b(all_text: dict, exclude_pages: list) -> list:
    """
    Search for standalone Section B content in pages not already processed.

    Used when the main Section B form says "Please see attached".
    Looks for a standalone "Section B" heading with content following it.
    """
    activities = []
    found_pages = set()

    # Patterns for standalone Section B heading
    standalone_patterns = [
        r'Section\s*B\s*[:\-]?\s*(?:Community\s+Interest|Activities)',
        r'Community\s+Interest\s+Statement\s*[-–—]?\s*Activities',
        r'SECTION\s*B\b',
    ]

    # Search pages not in the exclude list
    for page_num, text in all_text.items():
        if page_num in exclude_pages:
            continue

        if not isinstance(text, str):
            continue

        # Check for standalone Section B heading
        for pattern in standalone_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Found a Section B heading - extract content after it
                content_start = match.end()
                content = text[content_start:]

                # Look for end markers
                end_patterns = [
                    r'Section\s*C',
                    r'Declaration',
                    r'Signature',
                    r'CHECKLIST',
                ]

                for end_pattern in end_patterns:
                    end_match = re.search(end_pattern, content, re.IGNORECASE)
                    if end_match:
                        content = content[:end_match.start()]
                        break

                # Parse this content for activities
                if len(content.strip()) > 50:
                    parsed = _parse_ocr_text_for_activities(content)
                    if parsed and not _is_referential_content(parsed):
                        # Mark source page before adding
                        for act in parsed:
                            act["source_page"] = page_num
                            act["extraction_note"] = "Found via 'see attached' reference"
                        activities.extend(parsed)
                        found_pages.add(page_num)
                        # Only use first matching page to avoid duplicates
                        break

        # Stop after finding content on one page
        if found_pages:
            break

    # Deduplicate activities based on activity text
    return _deduplicate_activities(activities)


def _deduplicate_activities(activities: list) -> list:
    """Remove duplicate activities based on activity text similarity."""
    if not activities:
        return activities

    seen = set()
    unique = []

    for act in activities:
        # Create a normalized key from activity text
        activity_text = str(act.get("activity", "")).lower().strip()
        # Use first 100 chars as key to handle minor OCR variations
        key = activity_text[:100] if activity_text else ""

        if key and key not in seen:
            seen.add(key)
            unique.append(act)
        elif not key:
            # Keep activities with empty activity but non-empty benefit
            if act.get("benefit", "").strip():
                unique.append(act)

    return unique


def _find_section_b_pages(all_text: dict, cic36_start_page: int = None) -> list:
    """
    Identify which pages contain Section B content.

    Args:
        all_text: Dictionary of page_num -> OCR text
        cic36_start_page: If provided, only search pages AFTER this page (where CIC 36 form starts)
                         Section B is typically 2-5 pages after the CIC 36 marker.

    Returns:
        List of page numbers (sorted) that contain Section B content,
        including continuation pages where the content spans multiple pages.

    Logic:
    1. If cic36_start_page provided, only search pages after it (pages N+1 to N+6)
    2. Find the first page with a Section B header marker
    3. Include subsequent pages until Section C (or at least 2 continuation pages for surplus)
    """
    section_b_pages = []
    header_page = None

    # HIGH CONFIDENCE: Exact CIC 36 Section B header boilerplate
    # Modern forms: "SECTION B: Community Interest Statement - Activities & Related Benefit"
    # Some documents use "SCHEDULE 2" instead of "SECTION B"
    # Legacy forms (circa 2006): "SECTION B: COMPANY ACTIVITIES" at beginning of document
    # Allow for OCR variations in spacing, punctuation (including periods), and & vs "and"
    # Also handle common OCR errors: I→1, B→8
    primary_patterns = [
        # Modern form pattern
        (
            r'(?:SECT[I1]ON\s*[B8]|SCHEDULE\s*2)\s*[:\-\.]?\s*'
            r'Community\s+Interest\s+Statement\s*'
            r'[-–—]?\s*'
            r'(?:Activities\s*(?:&|and)\s*Related\s*Benefit)?'
        ),
        # Legacy form pattern (circa 2006)
        r'SECT[I1]ON\s*[B8]\s*[:\-\.]?\s*COMPANY\s+ACTIVITIES',
        r'Sect[i1]on\s*[B8][:\s\-\.]+Company\s+Activities',
        # OCR-friendly patterns for "SECTION B"
        r'SECT[I1]ON\s*[B8]\s*[:\-\.]',
    ]

    # MEDIUM CONFIDENCE: Fallback patterns if exact header not found
    fallback_markers = [
        # Section B with "Community Interest Statement" nearby
        r'Section\s*[B8][:\s\-]+\s*Community\s+Interest',
        # The specific table column headers from Section B
        r'Activities\s+How\s+will\s+the\s+activity\s+benefit',
        # Table instruction text unique to Section B
        r'Tell\s+us\s+here\s+what\s+the\s+company.*is\s+being\s+set\s+up\s+to\s+do',
        r'\(The\s+community\s+will\s+benefit\s+by',
        # Alternative: Just look for "Community Interest Statement"
        r'Community\s+Interest\s+Statement\s*[-–—]?\s*Activities',
    ]

    # LOW CONFIDENCE: Jumbled patterns for cross-column OCR reading
    jumbled_markers = [
        r'SECTION.*Community\s+Interest.*B',
        r'Community\s+Interest.*SECTION.*B',
        r'activity\s+benefit.*community',
        r'benefit.*community.*activity',
        r'company.*set\s+up\s+to\s+do',
        r'set\s+up\s+to\s+do.*company',
    ]

    # End markers that indicate Section B has ended
    end_markers = [
        r'SECT[I1]ON\s*C\b',
        r'Section\s*C\b',
        r'SIGNATORIES',
        r'Signatories',
        r'Declaration\s+of\s+compliance',
        r'CHECKLIST',
    ]

    # Determine which pages to search
    sorted_pages = sorted(all_text.keys())

    if cic36_start_page is not None:
        # Section B is typically 2-5 pages after CIC 36 marker
        # Search from cic36_start_page+1 to cic36_start_page+6
        min_page = cic36_start_page + 1
        max_page = cic36_start_page + 6
        pages_to_search = [p for p in sorted_pages if min_page <= p <= max_page]
        logger.debug(f"Searching for Section B on pages {pages_to_search} (after CIC 36 on page {cic36_start_page})")
    else:
        pages_to_search = sorted_pages

    # Search for Section B header with priority: primary > fallback > jumbled
    all_patterns = [
        (primary_patterns, "primary"),
        (fallback_markers, "fallback"),
        (jumbled_markers, "jumbled"),
    ]

    for patterns, confidence in all_patterns:
        if header_page:
            break
        for page_num in pages_to_search:
            text = all_text.get(page_num, "")
            if isinstance(text, str):
                for pattern in patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        header_page = page_num
                        section_b_pages.append(page_num)
                        logger.debug(f"Section B header found on page {page_num} ({confidence} confidence)")
                        break
                if header_page:
                    break

    # If we found a header page, include continuation pages
    # IMPORTANT: Section B ends with the surplus statement, not necessarily Section C
    # Include pages until we find the surplus marker (which marks the end of Section B content)
    if header_page:
        found_surplus = False

        # Surplus patterns that mark the end of Section B content
        surplus_patterns = [
            r'[I1]f\s+the\s+company\s+makes\s+any\s+surplus',
            r'Any\s+surplus\s+(?:gained|from\s+trading|will\s+be)',
            r'surplus\s+(?:it\s+)?will\s+be\s+(?:used|reinvested)',
        ]

        # First check if surplus is on the header page itself
        header_text = all_text.get(header_page, "")
        for pattern in surplus_patterns:
            if re.search(pattern, header_text, re.IGNORECASE):
                found_surplus = True
                logger.debug(f"Surplus marker found on header page {header_page}")
                break

        # If surplus not on header page, look at subsequent pages
        if not found_surplus:
            for page_num in sorted_pages:
                if page_num <= header_page:
                    continue

                text = all_text.get(page_num, "")
                if not isinstance(text, str):
                    continue

                # Include this page
                section_b_pages.append(page_num)

                # Check for surplus marker (primary end indicator)
                for pattern in surplus_patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        found_surplus = True
                        logger.debug(f"Surplus marker found on page {page_num}, stopping")
                        break

                if found_surplus:
                    break

                # Check for Section C (secondary end marker)
                section_c_match = re.search(r'SECT[I1]ON\s*C\b', text, re.IGNORECASE)
                if section_c_match:
                    logger.debug(f"Section C found on page {page_num}, stopping")
                    break

                # Check for other end markers
                for end_pattern in end_markers[2:]:  # Skip Section C patterns
                    if re.search(end_pattern, text, re.IGNORECASE):
                        logger.debug(f"End marker found on page {page_num}, stopping")
                        break
                else:
                    # Safety limit: don't go more than 4 pages beyond header
                    if page_num > header_page + 4:
                        logger.debug(f"Reached 4 pages after header, stopping")
                        break
                    continue
                break

    return sorted(set(section_b_pages))


def _parse_ocr_text_for_activities(text: str) -> list:
    """
    Parse OCR text to extract activities and benefits from Section B.

    Handles the typical CIC 36 Section B table format:
    - Two columns: "Activities" and "How will the activity benefit..."
    - Attempts to detect and split multiple activity rows
    - Handwritten entries may be harder to parse accurately
    - Also extracts "company differs" and "surplus use" sections
    """
    activities = []

    if not text:
        return activities

    # Strip boilerplate first (safety net - should already be done in main function)
    text = _strip_section_b_boilerplate(text)

    # FIRST: Extract "company differs" and "surplus use" from full text BEFORE trimming
    # These are in separate sections after the main activities table
    company_differs = _extract_company_differs(text)
    surplus_use = _extract_surplus_use(text)

    # Now find the table structure with column headers
    # CIC 36 form typically has: "Activities | How will the activity benefit..."
    # We need to skip past all the column header text

    # Find the end of column headers - look for the closing parenthesis pattern
    header_end_patterns = [
        r'is\s+being\s+set\s+up\s+to\s+do\s*\)',  # End of left column header
        r'\(The\s+community\s+will\s+benefit\s+by[^)]*\)',  # End of right column header
        r'The\s+community\s+will\s+benefit\s+by\s*\.{0,3}\s*\)',
    ]

    # Find where the actual table content starts (after column headers)
    table_content_start = 0
    for pattern in header_end_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            table_content_start = max(table_content_start, match.end())

    # If no header found, try simpler patterns
    if table_content_start == 0:
        simple_patterns = [
            r'Activities\s+How\s+will',
            r'\(Tell\s+us\s+here\s+what\s+the\s+company',
            # Legacy form patterns (circa 2006)
            r'SECTION\s*B\s*[:\-\.]?\s*COMPANY\s+ACTIVITIES',
            r'Section\s*B[:\s\-\.]+Company\s+Activities',
        ]
        for pattern in simple_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                table_content_start = match.end()
                break

    # PRIMARY BOUNDARY: All Section B content is between "SECTION B" and "SECTION C"
    # This is the most reliable rule for CIC 36 forms
    section_end_patterns = [
        # Primary: Section C marker (with OCR error handling)
        r'SECT[I1]ON\s*C\b',
        r'Section\s*C\b',
        # Secondary fallbacks (for malformed documents)
        r'SIGNATORIES',
        r'Signatories',
        r'Declaration\s+of\s+compliance',
        r'CHECKLIST',
    ]

    section_content = text[table_content_start:]
    end_pos = len(section_content)
    for pattern in section_end_patterns:
        match = re.search(pattern, section_content, re.IGNORECASE)
        if match:
            end_pos = min(end_pos, match.start())
            break  # Stop at first match - Section C is definitive
    section_content = section_content[:end_pos]

    # Filter out form instruction text
    # These are the boilerplate instructions that appear in CIC36 forms
    # NOT actual activity content - must be removed before parsing
    form_instructions = [
        # Main instruction paragraph patterns
        r'Please\s+indicate\s+how\s+it\s+is\s+proposed\s+that\s+the\s+activities.*?community[,.]?\s*',
        r'Please\s+indicate\s+how\s+it\s+is\s+proposed',
        r'Please\s+provide\s+as\s+much\s+detail\s+as\s+possible',
        r'to\s+enable\s+the\s+(?:CIC\s+)?Regulator\s+to\s+make\s+an?\s*(?:properly\s+)?informed\s+decision',
        r'to\s+enable\s+the\s+(?:CIC\s+)?Regulator',
        r'make\s+(?:a\s+properly\s+)?informed\s+decision\s+(?:about\s+)?(?:whether\s+)?',
        r'whether\s+your\s+(?:proposed\s+)?company\s+is\s+eligible',
        r'eligible\s+to\s+(?:be(?:come)?|become)\s+a\s+community\s+interest',
        r'would\s+(?:be\s+)?useful\s+if\s+you\s+were\s+to\s+explain',
        r'[Ii]t\s+would\s+(?:be\s+)?useful\s+if\s+you',
        r'different\s+from\s+a\s+commercial\s+company',
        r'providing\s+similar\s+services\s+or\s+products',
        r'individual\s*,?\s*(?:or\s+)?personal\s+gain',
        r'think\s+your\s+company\s+will\s+be\s+for\s+individual\s+or\s+personal\s+gain',
        # Form header text that gets mixed in
        r'COMPANY\s+NAME\b',
        r"that\s+the\s+company['']?s\s+activities\s+will\s+benefit\s+the\s+community[,.]?\s*(?:or\s+a\s+section\s+of\s+the\s+community)?",
        r'or\s+a\s+section\s+of\s+the\s+community',
        # Column header instruction text
        r'Activities\s+How\s+will\s+the\s+activity\s+benefit\s+the\s+community\??\s*',
        r'How\s+will\s+the\s+activity\s+benefit\s+the\s+community\??\s*',
        # Parenthetical instructions from column headers
        r'\(Tell\s+us\s+here\s+what\s+the\s+company[^)]*\)',
        r'\(The\s+community\s+will\s+benefit\s+by[^)]*\)',
        r'\(Please\s+continue\s+on[^)]*\)',
        # Version footer text
        r'Version\s+\d+\s*[-–—]\s*Last\s+Updated\s+on\s+\d{2}/\d{2}/\d{4}',
        r'Version\s+\d+\s*[-–—]?\s*Last\s+Updated',
        # Legacy form (2006) boilerplate - extracted separately
    ]

    # Remove form instructions
    cleaned_content = section_content
    for pattern in form_instructions:
        cleaned_content = re.sub(pattern, '', cleaned_content, flags=re.IGNORECASE)

    # Also remove any standalone instruction fragments
    # These are partial phrases that remain after the above removals
    instruction_fragments = [
        r'^[\s,\.]*that\s+the\s+company[\s,\.]*$',
        r'^[\s,\.]*a\s+section\s+of\s+the\s+community[\s,\.]*$',
        r'^[\s,\.]*SECTION\s+B[\s:,\.]*$',
        r'^[\s,\.]*Community\s+Interest\s+Statement[\s,\.—\-]*$',
    ]
    lines = cleaned_content.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        is_fragment = False
        for frag_pattern in instruction_fragments:
            if re.match(frag_pattern, stripped, re.IGNORECASE):
                is_fragment = True
                break
        if not is_fragment:
            cleaned_lines.append(line)
    cleaned_content = '\n'.join(cleaned_lines)

    # First, try the two-column table parser for legacy forms
    # This handles OCR that reads across columns (activity | benefit on same line)
    # Pass the full text so it can also extract company_differs/surplus if needed
    activities = _parse_two_column_table(cleaned_content, full_text=text)

    if activities:
        # Add company_differs and surplus_use to first activity if not already present
        if activities and (company_differs or surplus_use):
            if not activities[0].get("company_differs"):
                activities[0]["company_differs"] = company_differs
            if not activities[0].get("surplus_use"):
                activities[0]["surplus_use"] = surplus_use
        return activities

    # Try to detect multiple activity rows
    # Look for patterns that indicate separate activities
    activities = _split_into_activity_rows(cleaned_content)

    # If row splitting didn't work, fall back to single entry parsing
    if not activities:
        activities = _parse_single_activity_entry(cleaned_content)

    # Add company_differs and surplus_use to the activities
    if activities and (company_differs or surplus_use):
        activities[0]["company_differs"] = company_differs
        activities[0]["surplus_use"] = surplus_use
    elif company_differs or surplus_use:
        # No activities found but we have differs/surplus - create placeholder
        activities.append({
            "activity": "",
            "benefit": "",
            "company_differs": company_differs,
            "surplus_use": surplus_use,
            "source_page": 0,
            "ocr_confidence": "low"
        })

    return activities


def _parse_ocr_with_layout(layout_data: dict, linear_text: str, raw_text: str = None) -> list:
    """
    Parse OCR results using layout-aware column separation.

    This function uses the pre-separated column data from layout-aware OCR
    to extract activities and benefits without needing to reconstruct columns
    from interleaved text.

    Args:
        layout_data: Dictionary mapping page numbers to layout OCR results
        linear_text: Full linear text for extracting company_differs/surplus

    Returns:
        List of activity dictionaries
    """
    activities = []

    if not layout_data:
        return activities

    # Extract company_differs and surplus_use from raw text (before boilerplate stripping)
    # This preserves the "(Please continue on..." marker needed for surplus end boundary
    extraction_text = raw_text if raw_text else linear_text
    company_differs = _extract_company_differs(extraction_text)
    surplus_use = _extract_surplus_use(extraction_text)

    # Combine column text from all pages
    all_left_text = []
    all_right_text = []

    for page_num in sorted(layout_data.keys()):
        page_data = layout_data[page_num]

        if page_data.get("has_two_columns"):
            left = page_data.get("left_column", "")
            right = page_data.get("right_column", "")

            # Clean the column texts
            left_clean = _clean_layout_column(left, is_activity=True)
            right_clean = _clean_layout_column(right, is_activity=False)

            if left_clean:
                all_left_text.append(left_clean)
            if right_clean:
                all_right_text.append(right_clean)
        else:
            # Single column - fall back to linear text parsing for this page
            linear = page_data.get("linear_text", "")
            if linear:
                all_left_text.append(linear)

    # Join column texts
    activity_text = "\n".join(all_left_text).strip()
    benefit_text = "\n".join(all_right_text).strip()

    # Final cleanup - remove any leading boilerplate that slipped through
    # This catches OCR-jumbled text that starts with boilerplate fragments
    leading_boilerplate_patterns = [
        r'^\s*\.\s*[Ii][tf]\s+would\s+[^\n]*?\n*',
        r'^\s*[Ii][tf]\s+would\s+think\s+[^\n]*?\n*',
        r'^[^a-zA-Z]*[Ii][tf]\s+would\s+[^\n]*?\n*',
        r'^\s*\.\s+',  # Leading period and space
    ]
    for pattern in leading_boilerplate_patterns:
        activity_text = re.sub(pattern, '', activity_text, flags=re.IGNORECASE | re.MULTILINE)
        benefit_text = re.sub(pattern, '', benefit_text, flags=re.IGNORECASE | re.MULTILINE)

    activity_text = activity_text.strip()
    benefit_text = benefit_text.strip()

    # If we have separated columns, create the activity entry
    if activity_text or benefit_text:
        activities.append({
            "activity": activity_text,
            "benefit": benefit_text,
            "company_differs": company_differs,
            "surplus_use": surplus_use,
            "source_page": min(layout_data.keys()) if layout_data else 0,
            "ocr_confidence": "medium",
            "extraction_note": "layout_aware_ocr"
        })

    # If layout parsing didn't produce good results, fall back to linear parsing
    # But preserve surplus_use from raw_text extraction (it's more accurate)
    if not activities or (not activity_text and not benefit_text):
        fallback = _parse_ocr_text_for_activities(linear_text)
        if fallback and surplus_use:
            fallback[0]["surplus_use"] = surplus_use
        return fallback

    # Validate layout results - if they look like mostly boilerplate or garbage, fall back
    # Check if activity text is too short (likely just fragments) or benefit is empty/minimal
    if activity_text and len(activity_text) < 50:
        # Very short activity - probably failed extraction
        fallback = _parse_ocr_text_for_activities(linear_text)
        if fallback and surplus_use:
            fallback[0]["surplus_use"] = surplus_use
        return fallback

    if benefit_text and len(benefit_text) < 20:
        # Very short benefit - layout probably failed, benefit is garbage
        # Fall back to linear parsing
        fallback = _parse_ocr_text_for_activities(linear_text)
        if fallback and surplus_use:
            fallback[0]["surplus_use"] = surplus_use
        return fallback

    return activities


def _clean_layout_column(text: str, is_activity: bool = True) -> str:
    """
    Clean column text extracted from layout-aware OCR.

    Removes form headers, instructions, and other boilerplate while
    preserving actual content.

    Args:
        text: Raw column text
        is_activity: True if this is the activity column (left), False for benefit (right)

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # First apply the comprehensive boilerplate stripping
    cleaned = _strip_section_b_boilerplate(text)

    # Common patterns to remove from both columns
    common_patterns = [
        r'SECTION\s*B\s*[:\-]?\s*',
        r'Community\s+Interest\s+Statement\s*[-–—]?\s*',
        r'Activities\s*(?:&|and)\s*Related\s*Benefit\s*',
        r'COMPANY\s+NAME\s*',
        r'Version\s+\d+\s*[-–—]?\s*Last\s+Updated[^\\n]*',
        r'\(Please\s+continue\s+on[^)]*\)',
        # Additional boilerplate fragments that may remain after stripping
        r'a\s+section\s+of\s+the\s+community[.,]?\s*',
        r'to\s+enable\s+the\s+CIC\s+Regulator[^.]*\.?\s*',
        r'informed\s+decision\s+about[^.]*\.?\s*',
        r'eligible\s+to\s+become[^.]*\.?\s*',
        r'would\s+be\s+useful\s+if\s+you[^.]*\.?\s*',
        r'different\s+from\s+a\s+commercial[^.]*\.?\s*',
        r'for\s+individual[,]?\s*(?:or\s+)?personal\s+gain\.?\s*',
        # OCR-mangled boilerplate fragments (jumbled from layout OCR)
        r'\.?\s*[Ii][tf]\s+would\s+(?:be\s+)?(?:useful|think)[^.]*\.?\s*',
        r'your\s+company\s+will\s+be\s+different[^.]*\.?\s*',
        r'think\s+your\s+company[^.]*\.?\s*',
        r'company\s+providing\s+similar\s+services[^.]*\.?\s*',
        r'products?\s+for\s+individual[^.]*\.?\s*',
        # Leading boilerplate fragments
        r'^\s*\.\s*[Ii][tf]\s+would\s+',
        r'^\s*[Ii][tf]\s+would\s+think\s+',
    ]

    # Activity column (left) specific patterns
    activity_patterns = [
        r'Activities\s*$',
        r'^\s*Activities\s*',
        r'\(Tell\s+us\s+here\s+what\s+the\s+company[^)]*\)',
        r'Tell\s+us\s+here\s+what\s+the\s+company[^.]*\.?\s*',
        r'is\s+being\s+set\s+up\s+to\s+do\.?\s*\)?\s*',
        r'\(Please\s+provide\s+the\s+day\s+to\s+day[^)]*\)',
        r'Please\s+provide\s+the\s+day\s+to\s+day[^.]*\.?\s*',
        # Split boilerplate instruction fragments (from layout OCR splitting)
        r'Please\s+indicate\s+how\s+i[tf]\s+[i1]s\s+proposed[^.]*\.?\s*',
        r'Regulator\s+to\s+make\s+an\s+informed\s+decision[^.]*\.?\s*',
        r'become\s+a\s+community\s+interest\s+company[^.]*\.?\s*',
        r'Activities\s+How\s+will\s*',
        r'COMPANY\s+NAME\s+[A-Z][a-z]+\s*',
    ]

    # Benefit column (right) specific patterns
    benefit_patterns = [
        r'How\s+will\s+the\s+activity\s+benefit\s+the\s+community\??\s*',
        r'\(The\s+community\s+will\s+benefit\s+by[^)]*\)',
        r'The\s+community\s+will\s+benefit\s+by[^)]*\)?\s*',
        # Split boilerplate instruction fragments (from layout OCR splitting)
        r'company.?s?\s+activities\s+will\s+benefit\s+the\s+community[^.]*\.?\s*',
        r'much\s+detail\s+as\s+possible\s+to\s+enable[^.]*\.?\s*',
        r'whether\s+your\s+(?:proposed\s+)?company\s+[it]s\s+eligible[^.]*\.?\s*',
        r'be\s+useful\s+if\s+you\s+were\s+to\s+explain[^.]*\.?\s*',
        r'commercial\s+company\s+providing\s+similar[^.]*\.?\s*',
        r'the\s+activity\s+benefit\s+the\s+community\??\s*',
        # Company name fragments
        r'Healthy\s+Choices\s+CIC\s*[�\-]?\s*',
        r'[A-Z][a-z]+\s+[A-Z][a-z]+\s+CIC\s*[�\-]?\s*',
    ]

    # Apply common patterns
    for pattern in common_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Apply column-specific patterns
    patterns = activity_patterns if is_activity else benefit_patterns
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Normalize whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip()

    return cleaned


def _parse_two_column_table(text: str, full_text: str = None) -> list:
    """
    Parse OCR text from a two-column table where columns are read side-by-side.

    Legacy CIC36 forms (circa 2006) have a table with:
    - Left column: Activity description
    - Right column: How it benefits the community

    OCR reads these line-by-line across both columns, producing interleaved text.
    We need to separate the columns based on content markers.

    Args:
        text: Cleaned table content text
        full_text: Optional full OCR text for extracting company_differs/surplus
    """
    activities = []

    if not text or len(text.strip()) < 50:
        return activities

    # First, try line-by-line column separation for legacy forms
    # Pass full_text if available for extracting additional fields
    line_based_result = _parse_interleaved_columns(text, full_text=full_text)
    if line_based_result:
        return line_based_result

    # Fall back to benefit marker splitting
    # Look for explicit "The community will benefit" markers that split columns
    benefit_markers = [
        r'The\s+community\s+will\s+benefit\s+(?:by\s+)?',
        r'community\s+will\s+benefit\s+significantly',
        r'\|\s*(?:The\s+)?community',  # Pipe separator from OCR
    ]

    # Check if text has clear benefit markers
    has_benefit_marker = False
    for marker in benefit_markers:
        if re.search(marker, text, re.IGNORECASE):
            has_benefit_marker = True
            break

    if not has_benefit_marker:
        return activities  # Let other parsers handle it

    # Split by "The community will benefit" pattern
    # This should give us [activity, benefit, activity, benefit, ...]
    split_pattern = r'(The\s+community\s+will\s+benefit\s+(?:by\s+)?(?:significantly\s+)?(?:as\s+)?)'
    parts = re.split(split_pattern, text, flags=re.IGNORECASE)

    # Process pairs: each activity followed by benefit marker + benefit text
    current_activity = ""
    i = 0
    while i < len(parts):
        part = parts[i].strip()

        # Check if this is a benefit marker
        if re.match(r'The\s+community\s+will\s+benefit', part, re.IGNORECASE):
            # Next part is the benefit text
            if i + 1 < len(parts):
                benefit_text = parts[i + 1].strip()

                if current_activity:
                    # Clean up activity - remove trailing fragments
                    activity_clean = _clean_activity_text(current_activity)
                    benefit_clean = _clean_benefit_text(benefit_text)

                    if activity_clean or benefit_clean:
                        activities.append({
                            "activity": activity_clean,
                            "benefit": benefit_clean,
                            "source_page": 0,
                            "ocr_confidence": "medium"
                        })
                    current_activity = ""
                i += 2
            else:
                i += 1
        else:
            # This is activity text (or mixed content)
            current_activity += " " + part if current_activity else part
            i += 1

    # Handle any remaining activity without a benefit
    if current_activity.strip():
        activity_clean = _clean_activity_text(current_activity)
        if activity_clean and len(activity_clean) > 20:
            activities.append({
                "activity": activity_clean,
                "benefit": "",
                "source_page": 0,
                "ocr_confidence": "low"
            })

    # If we only got one activity, try alternative parsing
    if len(activities) == 1:
        # Check if the single activity should actually be split
        alt_activities = _try_split_single_activity(activities[0])
        if alt_activities:
            return alt_activities

    return activities


def _parse_interleaved_columns(text: str, full_text: str = None) -> list:
    """
    Parse OCR text where two table columns are interleaved line-by-line.

    Legacy CIC36 forms have text that looks like:
    "Activity text here The community will benefit by having..."
    "more activity text | more benefit text..."

    Strategy:
    1. Find the table content area (between headers and end markers)
    2. Look for pipe characters | or "The community will benefit" as column separators
    3. Reconstruct left column (activity) and right column (benefit) separately
    4. Also extract "company differs" and "surplus" sections

    Args:
        text: Cleaned table content text
        full_text: Optional full OCR text for extracting company_differs/surplus
    """
    activities = []

    # Use full_text for extracting additional fields if available, otherwise use text
    extraction_text = full_text if full_text else text

    # Look for table start - after column headers
    table_start_patterns = [
        r'\(The\s+community\s+will\s+benefit\s+by[^)]*\)',
        r'is\s+being\s+set\s+up\s+to\s+do\s*\)',
    ]

    start_pos = 0
    for pattern in table_start_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start_pos = max(start_pos, match.end())

    # Look for table end - these patterns indicate end of table content
    # Be more aggressive about detecting post-table content
    end_patterns = [
        r'(?:Our\s+)?company\s+differs\s+from\s+a?\s*general',  # "Our company differs..." or "company differs..."
        r'differs\s+from\s+a\s+general\s+commercial',
        r'If\s+the\s+company\s+makes\s+any\s+surplus',
        r'company\s+makes\s+any\s+surplus',
        r'its\s+primary\s+aim\s+is\s+to',  # Common start of "differs" explanation
        r'Section\s*C',
        r'SIGNATORIES',
        r'\(Please\s+continue\s+on',
    ]

    table_text = text[start_pos:]
    end_pos = len(table_text)
    for pattern in end_patterns:
        match = re.search(pattern, table_text, re.IGNORECASE)
        if match:
            end_pos = min(end_pos, match.start())

    table_text = table_text[:end_pos]

    # Extract "company differs" and "surplus" sections from full text
    company_differs = _extract_company_differs(extraction_text)
    surplus_use = _extract_surplus_use(extraction_text)

    if len(table_text.strip()) < 30:
        # Even if no table content, we might have differs/surplus
        if company_differs or surplus_use:
            activities.append({
                "activity": "",
                "benefit": "",
                "company_differs": company_differs,
                "surplus_use": surplus_use,
                "source_page": 0,
                "ocr_confidence": "low"
            })
        return activities

    # Process line by line, looking for column separators
    lines = table_text.split('\n')

    left_column = []  # Activity text
    right_column = []  # Benefit text

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        # Check for pipe separator (common OCR artifact for table cells)
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 2:
                left_column.append(parts[0].strip())
                right_column.append('|'.join(parts[1:]).strip())
                continue

        # Check for "The community will benefit" in the middle of line
        benefit_match = re.search(
            r'^(.+?)\s+(The\s+community\s+will\s+benefit.*)$',
            line,
            re.IGNORECASE
        )
        if benefit_match:
            left_part = benefit_match.group(1).strip()
            right_part = benefit_match.group(2).strip()
            if len(left_part) > 5:
                left_column.append(left_part)
            if len(right_part) > 5:
                right_column.append(right_part)
            continue

        # Check for other benefit indicators
        benefit_mid_match = re.search(
            r'^(.{20,}?)\s+(having\s+access|young\s+people\s+will|significantly|towards\s+the)',
            line,
            re.IGNORECASE
        )
        if benefit_mid_match:
            left_part = benefit_mid_match.group(1).strip()
            right_part = line[benefit_mid_match.start(2):].strip()
            left_column.append(left_part)
            right_column.append(right_part)
            continue

        # Can't determine column - try heuristics based on content
        # Activity text often describes what the company does
        # Benefit text often describes community impact
        if re.search(r'(community|benefit|impact|improve|regeneration)', line, re.IGNORECASE):
            right_column.append(line)
        else:
            left_column.append(line)

    # Combine column text
    activity_text = ' '.join(left_column).strip()
    benefit_text = ' '.join(right_column).strip()

    # Clean up the extracted text
    activity_text = _clean_activity_text(activity_text)
    benefit_text = _clean_benefit_text(benefit_text)

    # Remove redundant "The community will benefit by" prefixes from benefit
    benefit_text = re.sub(
        r'^The\s+community\s+will\s+benefit\s+(by\s+)?',
        '',
        benefit_text,
        flags=re.IGNORECASE
    ).strip()

    if activity_text or benefit_text or company_differs or surplus_use:
        activities.append({
            "activity": activity_text,
            "benefit": benefit_text,
            "company_differs": company_differs,
            "surplus_use": surplus_use,
            "source_page": 0,
            "ocr_confidence": "medium"
        })

    return activities


def _extract_beneficiaries(text: str) -> str:
    """
    Extract beneficiaries statement from Section A of CIC 36 form.

    The beneficiaries follow the boilerplate instruction text and may start with:
    "The company's activities will provide benefit to [description]"

    This appears in both modern and legacy forms:
    - Modern: "SECTION A: COMMUNITY INTEREST STATEMENT – beneficiaries"
    - Legacy: "SECTION A: DECLARATIONS ON FORMATION OF A COMMUNITY INTEREST COMPANY"

    Extract text until Section B header or end of text.
    """
    if not text:
        return ""

    # Patterns to find the END of the boilerplate instruction (beneficiaries follow after)
    # The boilerplate instruction ends with phrases like "...below" or "...below ]"
    # The actual beneficiary content starts AFTER this
    boilerplate_end_patterns = [
        # Modern form: "...which it is intended that the company will benefit below"
        r"which\s+i[tf]\s+[i1]s\s+intended\s+that\s+the\s+company\s+will\s+benefit\s+below\s*\]?\s*",
        r"the\s+company\s+will\s+benefit\s+below\s*\]?\s*",
        r"will\s+benefit\s+below\s*\]?\s*[E\s]*",  # OCR may add stray 'E'
        # Legacy form variations
        r"benefit\s+below\s*\]?\s*",
        # Alternate form: declaration ending with "...or a section of the community" (doc 14891915)
        # Must have the declaration prefix to avoid matching mid-text
        r"declare\s+that\s+the\s+company\s+will\s+carry\s+on\s+its\s+activities\s+for\s+the\s+benefit\s+of\s+the\s+community,?\s+or\s+a\s+section\s+of\s+the\s+community\s*[.,\d]*\s*",
        r"activities\s+for\s+the\s+benefit\s+of\s+the\s+community,?\s+or\s+a\s+section\s+of\s+the\s+community\s*[.,\d]*\s*",
        # Shorter form: "...activities for the benefit of the community." (doc 13034936)
        r"declare\s+that\s+the\s+company\s+will\s+carry\s+on\s+its\s+activities\s+for\s+the\s+benefit\s+of\s+the\s+community\s*\.\s*",
        r"activities\s+for\s+the\s+benefit\s+of\s+the\s+community\s*\.\s*",
    ]

    # Fallback patterns - only match the boilerplate prefix WITH trailing dots
    # (meaning it's an unfilled form field, not actual content)
    fallback_start_patterns = [
        # Only match if there are trailing dots (unfilled field marker)
        r"The\s+company'?s?\s+activities\s+will\s+provide\s+benefit\s+to\s*\.{3,}\s*",
        r"activities\s+will\s+provide\s+benefit\s+to\s*\.{3,}\s*",
    ]

    # End patterns - Section B header marks the end of Section A
    end_patterns = [
        r'SECT[I1]ON\s*B\b',  # With OCR error handling (I/1 confusion)
        r'Section\s*B\b',
        r'Community\s+Interest\s+Statement\s*[-–—]?\s*Activities',
        r'COMPANY\s+ACTIVITIES',
    ]

    content = ""

    # First, try to find the end of the boilerplate instruction
    # The actual beneficiary content starts AFTER this
    for end_pattern in boilerplate_end_patterns:
        match = re.search(end_pattern, text, re.IGNORECASE)
        if match:
            remaining = text[match.end():]

            # Find end - look for Section B header
            end_pos = len(remaining)
            for section_end_pattern in end_patterns:
                end_match = re.search(section_end_pattern, remaining, re.IGNORECASE)
                if end_match:
                    end_pos = min(end_pos, end_match.start())

            content = remaining[:end_pos].strip()
            break

    # If no boilerplate end found, try fallback patterns (only match unfilled form fields)
    if not content:
        for fallback_pattern in fallback_start_patterns:
            match = re.search(fallback_pattern, text, re.IGNORECASE)
            if match:
                remaining = text[match.end():]

                # Find end - look for Section B header
                end_pos = len(remaining)
                for section_end_pattern in end_patterns:
                    end_match = re.search(section_end_pattern, remaining, re.IGNORECASE)
                    if end_match:
                        end_pos = min(end_pos, end_match.start())

                content = remaining[:end_pos].strip()
                break

    # Clean up the content
    content = re.sub(r'\s+', ' ', content)
    content = re.sub(r'^\s*\.{1,3}\s*', '', content)  # Remove leading dots
    # Remove leading single-letter OCR artifacts (common: r, E, etc.) before "The company"
    content = re.sub(r'^[A-Za-z]\s+(?=The\s+company)', '', content)
    content = re.sub(r'^[^a-zA-Z]+', '', content)  # Remove any leading non-letter characters
    content = content.strip()

    # Remove any trailing form boilerplate that might have been captured
    # e.g., page numbers, form instructions, Companies House headers
    boilerplate_end_patterns = [
        r'\s*Page\s+\d+\s*(?:of\s+\d+)?.*$',
        r'\s*Please\s+continue\s+on\s+separate\s+sheet.*$',
        r'\s*CIC\s*36.*$',
        # Companies House headers/footers that OCR may pick up
        r'\s*COMPANIES\s+HOUSE.*$',
        r'\s*Declarations?\s+on\s+Formation\s+of\s+a.*$',
        r'\s*Community\s+[Ii]nterest\s+Company\s*$',
        # Form field labels that appear after beneficiaries content
        r'\s*COMPANY\s+NAME\s+.*$',  # "COMPANY NAME [company name here]"
        r'\s*COMPANY\s+NAME\s*$',    # Just "COMPANY NAME"
        r'\s*\[?[A-Z][a-z]+.*?CIC\s*$',  # "[Something CIC" or "Something CIC"
        # OCR noise patterns
        r'\s*[A-Z]{2,}\s*\?\s*[A-Z]+\s*$',  # Random uppercase letters
        r'\s*ct\s+Wo\s*$',  # Common OCR artifact
        r'\s*E\s+MET\?DIGOI\s*$',  # OCR artifact
        r'\s+[A-Z]\s*$',  # Trailing single uppercase letter
        r'\s+[A-Z]{1,2}\s*$',  # Trailing 1-2 uppercase letters (OCR artifacts)
    ]
    for pattern in boilerplate_end_patterns:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE)

    # Final cleanup - remove any trailing punctuation or whitespace
    content = re.sub(r'[\s.,:;]+$', '', content)

    # Strip the standard prefix boilerplate (per user requirement)
    # "The company's activities will provide benefit to..." should be removed
    # Note: Handle OCR variations like fancy apostrophe and trailing "..." or ". . ."
    prefix_patterns = [
        r"^(?:Pr\s+)?The\s+company[’']?s?\s+activities\s+will\s+provide\s+benefit\s+to\s*\.{0,5}\s*",
        r"^activities\s+will\s+provide\s+benefit\s+to\s*\.{0,5}\s*",
        r"^provide\s+benefit\s+to\s*\.{0,5}\s*",
    ]
    for pattern in prefix_patterns:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE)
    content = content.strip()

    return content.strip()


def _extract_company_differs(text: str) -> str:
    """
    Extract the "Our company differs from a general commercial company because..."
    section from the OCR text.
    """
    if not text:
        return ""

    # Pattern to find the start of this section
    start_patterns = [
        r'(?:Our\s+)?company\s+differs\s+from\s+a\s+general\s+commercial\s+company\s+because\s*\.{0,3}\s*',
        r'differs\s+from\s+a\s+general\s+commercial\s+company\s+because\s*\.{0,3}\s*',
    ]

    # Pattern to find the end of this section
    # The "company differs" section ends at the surplus statement or Section C
    end_patterns = [
        r'If\s+the\s+company\s+makes\s+any\s+surplus',
        r'company\s+makes\s+any\s+surplus',
        r'SECT[I1]ON\s*C\b',  # With OCR error handling
        r'Section\s*C\b',
        r'SIGNATORIES',
    ]

    content = ""
    for start_pattern in start_patterns:
        match = re.search(start_pattern, text, re.IGNORECASE)
        if match:
            remaining = text[match.end():]

            # Find end
            end_pos = len(remaining)
            for end_pattern in end_patterns:
                end_match = re.search(end_pattern, remaining, re.IGNORECASE)
                if end_match:
                    end_pos = min(end_pos, end_match.start())
                    break  # Stop at first match

            content = remaining[:end_pos].strip()
            break

    # Clean up the content
    content = re.sub(r'\s+', ' ', content)
    content = re.sub(r'^\s*\.{1,3}\s*', '', content)  # Remove leading dots
    content = content.strip()

    return content


def _extract_surplus_use(text: str) -> str:
    """
    Extract the "If the company makes any surplus it will be used for..."
    section from the OCR text.

    Common variations found in manual evaluation:
    - "If the company makes any surplus it will be used for..."
    - "Any surplus gained will be reinvested..."
    - "Any surplus from trading will be reinvested..."
    - "If the company makes any surplus it will be reinvested..."
    - Bullet point lists following the surplus header
    """
    if not text:
        return ""

    # Pattern to find the start of this section
    # Note: OCR sometimes reads "it" as "if", so allow both
    # Extended patterns based on manual evaluation feedback
    start_patterns = [
        # Standard boilerplate patterns
        r'If\s+the\s+company\s+makes\s+any\s+surplus\s+i[tf]\s+will\s+be\s+used\s+for\s*\.{0,3}\s*',
        r'company\s+makes\s+any\s+surplus\s+i[tf]\s+will\s+be\s+used\s+for\s*\.{0,3}\s*',
        r'surplus\s+i[tf]\s+will\s+be\s+used\s+for\s*\.{0,3}\s*',
        r'any\s+surplus\s+(?:it\s+)?will\s+be\s+used\s+for\s*\.{0,3}\s*',
        # "reinvested" variations (common in manual evaluation failures)
        r'If\s+the\s+company\s+makes\s+any\s+surplus\s+i[tf]\s+will\s+be\s+reinvested\s*\.{0,3}\s*',
        r'any\s+surplus\s+(?:it\s+)?will\s+be\s+reinvested\s*\.{0,3}\s*',
        r'surplus\s+(?:it\s+)?will\s+be\s+reinvested\s*\.{0,3}\s*',
        r'Any\s+surplus\s+(?:gained|from\s+trading)\s+will\s+be\s+reinvested\s*\.{0,3}\s*',
        r'surplus\s+(?:gained|from\s+trading)\s+will\s+be\s*\.{0,3}\s*',
        # "invest in" variations
        r'any\s+surplus\s+(?:it\s+)?will\s+be\s+used\s+to\s+invest\s*\.{0,3}\s*',
        r'surplus\s+will\s+be\s+used\s+to\s+invest\s*\.{0,3}\s*',
        # More flexible patterns to catch edge cases
        # Match just the header text, content follows
        r'If\s+the\s+company\s+makes\s+any\s+surplus[,:]?\s*',
        r'surplus\s+(?:income|profits?)\s+will\s+be\s*\.{0,3}\s*',
        # Catch "Any surplus" at start of sentence
        r'Any\s+surplus\s+(?:will\s+be|is)\s+(?:used|reinvested|invested)\s*',
    ]

    # Pattern to find the end of this section
    # PRIMARY RULE: Section C is the definitive boundary
    end_patterns = [
        r'SECT[I1]ON\s*C\b',  # With OCR error handling
        r'Section\s*C\b',
        r'SIGNATORIES',
        r'CHECKLIST',
        r'\(Please\s+continue\s+on',
        # Activity content indicators - surplus shouldn't contain these
        r'\s+gives\s+(?:schools|communities|people)\s+',
        r'\s+(?:schools|communities)\s+(?:and|or)\s+(?:other|community)\s+',
        r'The\s+internet\s+tells\s+',
        r'young\s+people\s+(?:around|with)\s+the\s+',
        r'training\s+establishments\s+',
    ]

    content = ""
    for start_pattern in start_patterns:
        match = re.search(start_pattern, text, re.IGNORECASE)
        if match:
            remaining = text[match.end():]

            # Find end - Section C is the definitive boundary
            end_pos = len(remaining)
            for end_pattern in end_patterns:
                end_match = re.search(end_pattern, remaining, re.IGNORECASE)
                if end_match:
                    end_pos = min(end_pos, end_match.start())
                    break  # Stop at first match

            content = remaining[:end_pos].strip()
            break

    # Clean up the content
    content = re.sub(r'\s+', ' ', content)
    content = re.sub(r'^\s*\.{1,3}\s*', '', content)  # Remove leading dots

    # Remove form boilerplate that may have leaked through
    boilerplate_patterns = [
        r"\(if donating or fundraising[^)]*\)",  # Charity donation instruction
        r"\(Please continue on separate[^)]*\)",  # Continuation instruction
        r"COMPANY NAME\s*$",  # Form field label at end
        r"^\s*Il\.{0,3}\s*",  # OCR artifact "Il..."
        r"with the consent of the CIC Regulator['\"]?\)?",  # Partial boilerplate
        # Asset Locked Body form boilerplate (doc 16727702)
        r"\(?[Ii]f\s+donating\s+to\s+a\s+non[^}]*\}?",
        r"Asset\s+Locked\s+Body[^.]*(?:rejected|wording)[^.]*\.?",
        r"otherwise\s+your\s+application\s+will\s+be\s+rejected[^.]*",
        r"you\s+will\s+need\s+to\s+include\s+the\s+wording[^.]*",
        # Footer text patterns (doc 16727702, 13034936, 12716495)
        r"\(Please\s+continue\s+(?:on\s+)?separate\s+sheet[^)]*\)\.?",
        r"Version\s+\d+[^.]*(?:Last\s+Updated[^.]*)?",
        r"Last\s+Updated\s+(?:on\s+)?\d{2}/\d{2}/\d{4}",
        # Activity content that leaked into surplus (doc 11701303)
        r"Peer\s+supporters?\s+will\s+support[^.]*",
        r"support\s+will\s+be\s+both\s+practical\s+and\s+emotional[^.]*",
        r"will\s+benefit\s+the\s+community\s+by\s+promoting[^.]*",
    ]
    for pattern in boilerplate_patterns:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE)

    # Remove trailing artifacts like "(.", "()", "(.)", etc.
    trailing_cleanup = [
        r'\s*\(\s*\.\s*\)\s*$',  # "(.) " at end
        r'\s*\(\s*\)\s*$',       # "( )" at end
        r'\s*\.\s*\(\s*\.\s*\)\s*$',  # ". (.)" at end
        r'\s*\(\s*\.\s*$',       # "(." at end
        r'\s*[(\[\])\s]+$',      # Orphaned brackets at end
        # OCR artifacts from page decorations/footers (doc 14891915, 12716495)
        r'\s*[—_\-]{3,}[\s\w]*$',  # "———_—_— ee" type artifacts
        r'\s*[-—_]{2,}\s*[a-z]{1,3}\s*$',  # "—— ee" or "——— nn"
        r'\s*[nNeE]{2,}\s*$',  # "nn", "ee" artifacts
        r'\s*_\s*[a-z]\s*\|?\s*$',  # "_ a |" type artifacts
        # Random OCR garbage at end (doc 11701303) - specific patterns only
        r'\s*Vseewtan.*$',  # Specific OCR artifact
        r'\s*Nfeeete\s+ee.*$',  # Specific OCR artifact
    ]
    for pattern in trailing_cleanup:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE)

    # Additional cleanup for uppercase-only garbage (case-SENSITIVE)
    # These patterns intentionally don't use IGNORECASE to only match actual uppercase
    uppercase_garbage_patterns = [
        r'\s*[A-Z]{3,}\s+[A-Z]{3,}\s*$',  # Multiple uppercase-only words at end
    ]
    for pattern in uppercase_garbage_patterns:
        content = re.sub(pattern, '', content)  # Note: no IGNORECASE flag

    content = content.strip()

    # Surplus statements are typically short (1-3 sentences)
    # If extracted content is very long, it likely contains activity content
    # that bled through - truncate at a reasonable boundary
    MAX_SURPLUS_LENGTH = 300
    if len(content) > MAX_SURPLUS_LENGTH:
        # Find last complete sentence within limit
        truncated = content[:MAX_SURPLUS_LENGTH]
        # Find the last sentence-ending punctuation
        last_period = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
        if last_period > 50:  # Only truncate if we have reasonable content
            content = truncated[:last_period + 1]

    return content


def _clean_activity_text(text: str) -> str:
    """Clean up extracted activity text."""
    if not text:
        return ""

    # Remove common OCR artifacts
    text = re.sub(r'[|¦]', ' ', text)  # Table cell separators
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    text = re.sub(r'^\s*[-–—]\s*', '', text)  # Leading dashes
    text = re.sub(r'\s*[-–—]\s*$', '', text)  # Trailing dashes

    # Remove form instructions that may have leaked through
    text = re.sub(r'\(Tell\s+us\s+here[^)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(The\s+community\s+will\s+benefit[^)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Activities?\s+How\s+will.*?community\s*\?', '', text, flags=re.IGNORECASE | re.DOTALL)

    # Remove fragments that are clearly from the benefit column
    text = re.sub(r'having\s+access\s+to\s+flexible.*$', '', text, flags=re.IGNORECASE)

    # Remove very short trailing fragments (often OCR errors)
    text = re.sub(r'\s+\w{1,3}\s*$', '', text)

    return text.strip()


def _clean_benefit_text(text: str) -> str:
    """Clean up extracted benefit text."""
    if not text:
        return ""

    # Remove common OCR artifacts
    text = re.sub(r'[|¦]', ' ', text)  # Table cell separators
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

    # Remove trailing activity text that leaked in
    # Look for patterns that indicate start of next activity
    next_activity_patterns = [
        r'(?:By\s+improving|work\s+closely|will\s+also|will\s+benefit)',
        r'\.\s*[A-Z][a-z]+\s+(?:to|for|the)\s+',
    ]

    # Remove form instructions
    text = re.sub(r'\(Please\s+continue[^)]*\)', '', text, flags=re.IGNORECASE)

    return text.strip()


def _try_split_single_activity(activity: dict) -> list:
    """
    Try to split a single activity entry that may contain multiple activities.

    Returns list of activities if split successful, empty list otherwise.
    """
    act_text = activity.get("activity", "")
    ben_text = activity.get("benefit", "")

    # Look for sentence boundaries that might indicate multiple activities
    # e.g., "Activity 1. Activity 2."
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', act_text)

    if len(sentences) <= 1:
        return []

    # Check if sentences look like distinct activities
    activities = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) > 30 and not _is_form_instruction_only(sent):
            activities.append({
                "activity": sent,
                "benefit": ben_text if len(activities) == 0 else "",
                "source_page": activity.get("source_page", 0),
                "ocr_confidence": "low"
            })

    return activities if len(activities) > 1 else []


def _split_into_activity_rows(text: str) -> list:
    """
    Attempt to split OCR text into multiple activity rows.

    Looks for common patterns that indicate separate activities:
    - Numbered lists (1., 2., a., b.)
    - Bullet points (•, -, *)
    - Category labels (General:, Specific:, A., B.)
    - Clear paragraph breaks
    """
    activities = []

    if not text:
        return activities

    # Patterns that indicate start of a new activity row
    row_delimiter_patterns = [
        # Numbered activities: "1.", "2)", "1:"
        r'\n\s*(\d+[\.\)\:])\s+',
        # Lettered activities: "a.", "A)", "a:"
        r'\n\s*([a-zA-Z][\.\)\:])\s+',
        # Bullet points
        r'\n\s*[•●○◦▪▸►]\s+',
        r'\n\s*[\-\*]\s+(?=[A-Z])',
        # Category labels like "General:", "Specific:", "Primary:"
        r'\n\s*((?:General|Specific|Primary|Secondary|Main|Additional|Other)\s*:)',
        # Roman numerals: "i.", "ii.", "iii."
        r'\n\s*((?:i{1,3}|iv|vi{0,3}|ix|x)[\.\)])\s+',
    ]

    # First, check if any delimiter pattern exists
    has_delimiters = False
    for pattern in row_delimiter_patterns:
        if re.search(pattern, '\n' + text, re.IGNORECASE):
            has_delimiters = True
            break

    if not has_delimiters:
        # No clear row delimiters found - try paragraph-based splitting
        return _split_by_paragraphs(text)

    # Split by the detected delimiters
    segments = ['\n' + text]  # Add newline prefix for pattern matching
    for pattern in row_delimiter_patterns:
        new_segments = []
        for segment in segments:
            # Split this segment and keep the delimiter with the following text
            parts = re.split(f'({pattern})', segment, flags=re.IGNORECASE)

            current = ""
            for i, part in enumerate(parts):
                if part is None:
                    continue
                # Check if this part matches a delimiter pattern
                is_delimiter = any(re.match(p.replace(r'\n\s*', ''), part.strip(), re.IGNORECASE)
                                   for p in row_delimiter_patterns if p.replace(r'\n\s*', ''))
                if is_delimiter and current.strip():
                    new_segments.append(current.strip())
                    current = part
                else:
                    current += part
            if current.strip():
                new_segments.append(current.strip())
        segments = new_segments if new_segments else segments

    # Process each segment into an activity entry
    for segment in segments:
        segment = segment.strip()
        if len(segment) < 20:  # Too short to be meaningful
            continue
        if _is_form_instruction_only(segment):
            continue

        # Extract activity and description from this segment
        activity_text, benefit_text = _extract_activity_description(segment)

        if activity_text or benefit_text:
            activities.append({
                "activity": _clean_extracted_text(activity_text),
                "benefit": _clean_extracted_text(benefit_text),
                "source_page": 0,
                "ocr_confidence": "medium" if len(activities) > 0 else "low"
            })

    return activities


def _split_by_paragraphs(text: str) -> list:
    """
    Split text into activities based on paragraph breaks.
    Used when no explicit row delimiters are found.
    """
    activities = []

    # Look for double newlines or significant breaks
    paragraphs = re.split(r'\n\s*\n+', text)

    if len(paragraphs) <= 1:
        # No paragraph breaks - return empty to trigger fallback
        return activities

    for para in paragraphs:
        para = para.strip()
        if len(para) < 30:  # Too short
            continue
        if _is_form_instruction_only(para):
            continue

        activity_text, benefit_text = _extract_activity_description(para)

        if activity_text or benefit_text:
            activities.append({
                "activity": _clean_extracted_text(activity_text),
                "benefit": _clean_extracted_text(benefit_text),
                "source_page": 0,
                "ocr_confidence": "low"
            })

    return activities


def _extract_activity_description(text: str) -> tuple:
    """
    Extract activity and description/benefit from a text segment.

    Returns:
        Tuple of (activity_text, benefit_text)
    """
    # Clean up whitespace but preserve some structure
    text = re.sub(r'\s+', ' ', text).strip()

    # Look for benefit/description markers
    benefit_markers = [
        r'The\s+community\s+will\s+benefit\s+by',
        r'community\s+will\s+benefit',
        r'will\s+benefit\s+the\s+community',
        r'This\s+will\s+(?:help|benefit|support|enable)',
        r'Benefits?\s*:',
    ]

    activity_text = text
    benefit_text = ""

    for marker in benefit_markers:
        match = re.search(marker, text, re.IGNORECASE)
        if match:
            activity_text = text[:match.start()].strip()
            benefit_text = text[match.end():].strip()
            break

    # If no explicit marker, try to split by sentence structure
    if not benefit_text and '.' in activity_text:
        sentences = activity_text.split('.')
        if len(sentences) >= 2:
            # First sentence(s) describe activity, rest describe benefit
            mid_point = len(sentences) // 2
            activity_text = '. '.join(sentences[:mid_point]).strip()
            benefit_text = '. '.join(sentences[mid_point:]).strip()
            if activity_text and not activity_text.endswith('.'):
                activity_text += '.'

    return activity_text, benefit_text


def _parse_single_activity_entry(text: str) -> list:
    """
    Fallback parser when row splitting doesn't work.
    Treats entire content as a single activity entry.
    """
    activities = []

    # Clean up extra whitespace
    cleaned_content = re.sub(r'\s+', ' ', text).strip()

    if not cleaned_content or len(cleaned_content) < 20:
        return activities

    # Try to split into activity and benefit parts
    activity_text, benefit_text = _extract_activity_description(cleaned_content)

    # Clean up the extracted text
    activity_text = _clean_extracted_text(activity_text)
    benefit_text = _clean_extracted_text(benefit_text)

    # Create activity entry if we have meaningful content
    if activity_text or benefit_text:
        # Skip if it looks like form instructions only
        if _is_form_instruction_only(activity_text) and _is_form_instruction_only(benefit_text):
            return activities

        activities.append({
            "activity": activity_text,
            "benefit": benefit_text,
            "source_page": 0,  # Will be filled by caller
            "ocr_confidence": "low"  # Scanned documents have lower confidence
        })

    return activities


def _clean_extracted_text(text: str) -> str:
    """Clean up extracted text by removing artifacts and normalizing whitespace."""
    if not text:
        return ""

    # Remove common OCR artifacts
    text = re.sub(r'[|¦]', '', text)  # Table cell separators
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    text = re.sub(r'^\s*[-–—]\s*', '', text)  # Leading dashes
    text = re.sub(r'\s*[-–—]\s*$', '', text)  # Trailing dashes

    # Remove stray parentheses content that looks like form instructions
    text = re.sub(r'\([^)]*tell\s+us[^)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\([^)]*community\s+will\s+benefit\s+by[^)]*\)', '', text, flags=re.IGNORECASE)

    return text.strip()


def _is_form_instruction_only(text: str) -> bool:
    """Check if text contains only form instructions without actual content."""
    if not text or len(text) < 20:
        return True

    # Patterns that indicate form instructions (match at start)
    start_instruction_patterns = [
        r'^please\s+indicate',
        r'^please\s+provide',
        r'^a\s+section\s+of\s+the\s+community',
        r'^to\s+enable\s+the\s+(?:cic\s+)?regulator',
        r'^how\s+will\s+the\s+activity',
        r'^tell\s+us\s+here',
        r'^the\s+community\s+will\s+benefit\s+by\s*\.{0,3}\s*$',
        r'^it\s+would\s+(?:be\s+)?useful\s+if\s+you',
        r'^eligible\s+to\s+be(?:come)?\s+a\s+community',
        r"^that\s+the\s+company['']?s\s+activities",
        r'^section\s*b\s*[:\-]?\s*community\s+interest',
    ]

    # Patterns that indicate text is MOSTLY form boilerplate (search anywhere)
    boilerplate_indicators = [
        r'enable\s+the\s+(?:cic\s+)?regulator\s+to\s+make',
        r'informed\s+decision\s+about\s+whether',
        r'would\s+(?:be\s+)?useful\s+if\s+you\s+were\s+to\s+explain',
        r'think\s+your\s+company\s+will\s+be\s+for\s+individual',
        r'individual\s+or\s+personal\s+gain',
        r'different\s+from\s+a\s+commercial\s+company',
        r'company\s+name\s+section\s+b',
    ]

    text_lower = text.lower().strip()

    # Check start patterns
    for pattern in start_instruction_patterns:
        if re.match(pattern, text_lower):
            return True

    # Check if text is predominantly boilerplate
    # Count how many boilerplate indicators are found
    boilerplate_count = 0
    for pattern in boilerplate_indicators:
        if re.search(pattern, text_lower):
            boilerplate_count += 1

    # If more than one boilerplate indicator and text is short, it's likely instructions
    if boilerplate_count >= 2 and len(text_lower) < 500:
        return True

    # If single boilerplate indicator and very short text
    if boilerplate_count >= 1 and len(text_lower) < 200:
        return True

    return False


def _parse_ocr_text_alternative(text: str) -> list:
    """
    Alternative parsing strategy for difficult OCR text.
    Simply extracts all meaningful text as a single activity entry.
    """
    activities = []

    if not text:
        return activities

    # Clean up the text
    lines = text.split('\n')
    meaningful_lines = []

    for line in lines:
        line = line.strip()
        if len(line) > 10 and not _is_header_line(line):
            meaningful_lines.append(line)

    if meaningful_lines:
        # Just capture all text as a single entry for manual review
        activities.append({
            "activity": ' '.join(meaningful_lines[:len(meaningful_lines)//2]),
            "benefit": ' '.join(meaningful_lines[len(meaningful_lines)//2:]),
            "source_page": 0,
            "ocr_confidence": "very_low",
            "note": "Manual review recommended - OCR parsing uncertain"
        })

    return activities


def _is_header_line(line: str) -> bool:
    """
    Check if a line appears to be a header or form instruction.
    """
    header_patterns = [
        r'^activities?\s*$',
        r'^benefits?\s*$',
        r'^section\s*[a-z]',
        r'^cic\s*\d+',
        r'^form\s+',
        r'^page\s+\d+',
        r'^companies\s+house',
        r'^how\s+will\s+the\s+activity',
        r'^\d+\s*$',
        r'^[\-_=]+$',
    ]

    line_lower = line.lower().strip()

    for pattern in header_patterns:
        if re.match(pattern, line_lower):
            return True

    return False


def extract_with_enhanced_ocr(pdf_path: str | Path, page_numbers: list,
                               preprocess: bool = True) -> dict:
    """
    Enhanced OCR extraction with image preprocessing for better results.

    Args:
        pdf_path: Path to the PDF file
        page_numbers: List of 1-indexed page numbers to process
        preprocess: Whether to apply image preprocessing

    Returns:
        Same structure as extract_section_b_ocr
    """
    pdf_path = Path(pdf_path)

    result = {
        "success": False,
        "activities": [],
        "raw_text": {},
        "extraction_method": "ocr_enhanced",
        "pages_processed": []
    }

    if not OCR_AVAILABLE:
        result["error"] = "OCR dependencies not available"
        return result

    try:
        from PIL import Image, ImageEnhance, ImageFilter

        for page_num in page_numbers:
            try:
                images = convert_from_path(
                    str(pdf_path),
                    first_page=page_num,
                    last_page=page_num,
                    dpi=400  # Higher DPI for scanned docs
                )

                if images:
                    img = images[0]

                    if preprocess:
                        # Convert to grayscale
                        img = img.convert('L')

                        # Enhance contrast
                        enhancer = ImageEnhance.Contrast(img)
                        img = enhancer.enhance(2.0)

                        # Sharpen
                        img = img.filter(ImageFilter.SHARPEN)

                    # OCR with custom config for handwriting
                    custom_config = r'--oem 3 --psm 6'
                    text = pytesseract.image_to_string(img, config=custom_config)

                    result["raw_text"][page_num] = text
                    result["pages_processed"].append(page_num)

            except Exception as e:
                result["raw_text"][f"page_{page_num}_error"] = str(e)

        # Parse combined text
        combined_text = "\n".join(str(v) for v in result["raw_text"].values() if not str(v).startswith("page_"))
        activities = _parse_ocr_text_for_activities(combined_text)

        if activities:
            result["activities"] = activities
            result["success"] = True

    except ImportError:
        result["error"] = "PIL/Pillow not available for image preprocessing"
    except Exception as e:
        result["error"] = str(e)

    return result


if __name__ == "__main__":
    import sys
    import json

    # Check OCR availability first
    ocr_check = check_ocr_available()
    print("OCR Availability Check:")
    print(f"  Available: {ocr_check['available']}")
    print(f"  pdf2image: {ocr_check['pdf2image']}")
    print(f"  pytesseract: {ocr_check['pytesseract']}")
    print(f"  Tesseract binary: {ocr_check['tesseract_binary']}")
    if ocr_check['errors']:
        print(f"  Errors: {ocr_check['errors']}")

    if len(sys.argv) < 3:
        print("\nUsage: python extract_scanned.py <pdf_path> <page_numbers>")
        print("  page_numbers: comma-separated list (e.g., 20,21,22)")
        sys.exit(1)

    pdf_path = sys.argv[1]
    page_numbers = [int(p) for p in sys.argv[2].split(',')]

    print(f"\nExtracting from: {pdf_path}")
    print(f"Pages: {page_numbers}")

    result = extract_section_b_ocr(pdf_path, page_numbers)

    print(f"\nResults:")
    print(f"  Success: {result['success']}")
    print(f"  Pages Processed: {result['pages_processed']}")
    print(f"  Activities Found: {len(result['activities'])}")

    if result.get('error'):
        print(f"  Error: {result['error']}")

    for i, act in enumerate(result['activities'], 1):
        print(f"\n  Activity {i}:")
        print(f"    Activity: {act['activity'][:100]}...")
        print(f"    Benefit: {act['benefit'][:100]}...")
