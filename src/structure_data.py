"""
Data Structuring Module

Normalizes extracted CIC document data into consistent JSON format
for storage and analysis.
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
import re
import json

logger = logging.getLogger(__name__)


def parse_filename(filename: str) -> dict:
    """
    Parse CIC document filename to extract company number and date.

    Expected filename formats:
    - {company_number}_newinc_{date}.pdf (e.g., 14941059_newinc_2023-06-16.pdf)
    - companies_house_document.pdf (older format, no metadata)

    Returns:
        Dictionary with company_number and incorporation_date (or None if not parseable)
    """
    result = {
        "company_number": None,
        "incorporation_date": None,
        "filename_format": "unknown"
    }

    filename = Path(filename).stem  # Remove extension

    # Try modern format: {company_number}_newinc_{date}
    modern_match = re.match(r'^(\d+)_newinc_(\d{4}-\d{2}-\d{2})$', filename)
    if modern_match:
        result["company_number"] = modern_match.group(1)
        result["incorporation_date"] = modern_match.group(2)
        result["filename_format"] = "modern"
        return result

    # Try format with just company number
    number_match = re.match(r'^(\d{6,8})', filename)
    if number_match:
        result["company_number"] = number_match.group(1)
        result["filename_format"] = "partial"
        return result

    # Old format - no metadata in filename
    result["filename_format"] = "legacy"
    return result


def structure_extraction_result(
    pdf_path: str | Path,
    document_type: str,
    classification_metadata: dict,
    location_result: dict,
    extraction_result: dict
) -> dict:
    """
    Structure all extraction data into the final JSON format.

    Args:
        pdf_path: Path to the source PDF
        document_type: 'electronic' or 'scanned'
        classification_metadata: Output from classify_document
        location_result: Output from find_cic36_pages
        extraction_result: Output from extract_section_b_table or extract_section_b_ocr

    Returns:
        Structured JSON-compatible dictionary
    """
    pdf_path = Path(pdf_path)
    filename_info = parse_filename(pdf_path.name)

    # Determine extraction status
    if extraction_result.get("success"):
        status = "success"
    elif extraction_result.get("error"):
        status = "error"
    else:
        status = "no_data"

    # Build activities list
    activities = []
    company_differs = ""
    surplus_use = ""
    beneficiaries = ""

    # First check for top-level fields (from electronic or scanned extraction)
    if extraction_result.get("surplus_use"):
        surplus_use = extraction_result.get("surplus_use", "")
    if extraction_result.get("company_differs"):
        company_differs = extraction_result.get("company_differs", "")
    if extraction_result.get("beneficiaries"):
        beneficiaries = extraction_result.get("beneficiaries", "")

    for act in extraction_result.get("activities", []):
        activities.append({
            "activity": act.get("activity", ""),
            "description": act.get("benefit", "") or act.get("description", "")
        })
        # Extract company_differs and surplus_use from first activity that has them
        # (for scanned extraction which stores these in activities)
        if not company_differs and act.get("company_differs"):
            company_differs = act.get("company_differs", "")
        if not surplus_use and act.get("surplus_use"):
            surplus_use = act.get("surplus_use", "")

    # Build the structured output
    output = {
        "company_number": filename_info["company_number"],
        "incorporation_date": filename_info["incorporation_date"],
        "document_type": document_type,
        "extraction_status": status,
        "section_a": {
            "beneficiaries": beneficiaries
        },
        "section_b": {
            "activities": activities,
            "company_differs": company_differs,
            "surplus_use": surplus_use
        },
        "extraction_metadata": {
            "source_file": pdf_path.name,
            "cic36_page": location_result.get("section_b_page"),
            "cic36_pages_found": location_result.get("cic36_pages", []),
            "location_confidence": location_result.get("confidence"),
            "extraction_method": extraction_result.get("extraction_method"),
            "pages_searched": extraction_result.get("pages_searched", []) or extraction_result.get("pages_processed", []),
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "document_page_count": classification_metadata.get("page_count"),
            "avg_chars_per_page": classification_metadata.get("avg_chars_per_page")
        }
    }

    # Add error information if present
    if extraction_result.get("error"):
        output["extraction_metadata"]["error"] = extraction_result["error"]

    # Add OCR confidence for scanned documents
    if document_type == "scanned":
        first_activity = extraction_result.get("activities", [{}])[0] if extraction_result.get("activities") else {}
        output["extraction_metadata"]["ocr_confidence"] = first_activity.get("ocr_confidence", "unknown")

    return output


def validate_structured_data(data: dict) -> dict:
    """
    Validate structured extraction data.

    Returns:
        Dictionary with validation results and any issues found
    """
    issues = []

    # Check required fields
    if not data.get("company_number"):
        issues.append("Missing company_number")

    if not data.get("extraction_status"):
        issues.append("Missing extraction_status")

    # Check activities
    activities = data.get("section_b", {}).get("activities", [])
    if data["extraction_status"] == "success" and not activities:
        issues.append("Status is 'success' but no activities found")

    for i, act in enumerate(activities):
        if not act.get("activity") and not act.get("description"):
            issues.append(f"Activity {i+1} has no content")

    # Check metadata
    metadata = data.get("extraction_metadata", {})
    if not metadata.get("source_file"):
        issues.append("Missing source_file in metadata")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "activity_count": len(activities)
    }


def save_to_json(data: dict, output_path: str | Path, pretty: bool = True) -> bool:
    """
    Save structured data to a JSON file.

    Args:
        data: Structured extraction data
        output_path: Path to output JSON file
        pretty: Whether to format JSON with indentation

    Returns:
        True if successful, False otherwise
    """
    output_path = Path(output_path)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            if pretty:
                json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                json.dump(data, f, ensure_ascii=False)

        return True

    except Exception as e:
        logger.error(f"Error saving to {output_path}: {e}")
        return False


def load_from_json(json_path: str | Path) -> Optional[dict]:
    """
    Load structured data from a JSON file.
    """
    json_path = Path(json_path)

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading from {json_path}: {e}")
        return None


def merge_batch_results(results: list[dict]) -> dict:
    """
    Merge multiple extraction results into a batch summary.

    Args:
        results: List of structured extraction results

    Returns:
        Batch summary with statistics and all results
    """
    summary = {
        "batch_info": {
            "total_documents": len(results),
            "successful": 0,
            "failed": 0,
            "no_data": 0,
            "electronic_docs": 0,
            "scanned_docs": 0,
            "total_activities": 0,
            "processed_at": datetime.utcnow().isoformat() + "Z"
        },
        "results": results
    }

    for result in results:
        status = result.get("extraction_status", "unknown")
        if status == "success":
            summary["batch_info"]["successful"] += 1
        elif status == "error":
            summary["batch_info"]["failed"] += 1
        else:
            summary["batch_info"]["no_data"] += 1

        doc_type = result.get("document_type", "unknown")
        if doc_type == "electronic":
            summary["batch_info"]["electronic_docs"] += 1
        elif doc_type == "scanned":
            summary["batch_info"]["scanned_docs"] += 1

        activities = result.get("section_b", {}).get("activities", [])
        summary["batch_info"]["total_activities"] += len(activities)

    return summary


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python structure_data.py <filename>")
        print("\nExample: python structure_data.py 14941059_newinc_2023-06-16.pdf")
        sys.exit(1)

    filename = sys.argv[1]
    info = parse_filename(filename)

    print(f"\nFilename: {filename}")
    print(f"  Company Number: {info['company_number']}")
    print(f"  Incorporation Date: {info['incorporation_date']}")
    print(f"  Format: {info['filename_format']}")
