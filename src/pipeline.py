"""
CIC Document Extraction Pipeline

Main batch processing script for extracting Section B data from
CIC incorporation documents. Supports parallel processing for
large document collections.
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional
import traceback

from tqdm import tqdm

# Import pipeline modules
from classify_document import classify_document
from locate_cic36 import find_cic36_pages
from extract_electronic import extract_section_b_table, extract_text_fallback
from extract_scanned import extract_section_b_ocr, check_ocr_available
from structure_data import structure_extraction_result, save_to_json, merge_batch_results, validate_structured_data


# Configure logging
def setup_logging(log_dir: Path) -> logging.Logger:
    """Set up logging for the pipeline."""
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"extraction_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    return logging.getLogger(__name__)


def process_single_document(pdf_path: Path) -> dict:
    """
    Process a single PDF document through the extraction pipeline.

    Uses auto-selection based on document type:
    - Electronic PDFs: pdfplumber table extraction with text fallback
    - Scanned/Hybrid PDFs: OCR-based extraction (Tesseract + Poppler)

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Structured extraction result dictionary
    """
    start_time = time.time()

    try:
        # Step 1: Classify document
        doc_type, classification_meta = classify_document(pdf_path)

        # Step 2: Locate CIC 36 form
        location_result = find_cic36_pages(pdf_path, doc_type)

        # Step 3: Determine pages to process
        section_b_page = location_result.get("section_b_page")
        suggested_pages = location_result.get("search_details", {}).get("suggested_pages", [])
        image_pages = classification_meta.get("image_pages", [])

        # Build page list based on doc type
        if doc_type == "electronic":
            pages_to_extract = [section_b_page] if section_b_page else suggested_pages[:1]
        elif doc_type == "scanned":
            if section_b_page:
                pages_to_extract = [section_b_page, section_b_page + 1]
            else:
                pages_to_extract = suggested_pages
        elif doc_type == "hybrid":
            pages_to_extract = image_pages[-25:] if len(image_pages) > 25 else image_pages
        else:
            pages_to_extract = []

        # Step 4: Extract based on document type
        if doc_type == "electronic":
            # Try table extraction first
            if pages_to_extract:
                extraction_result = extract_section_b_table(pdf_path, pages_to_extract[0])
            else:
                extraction_result = {"success": False, "activities": [], "error": "Could not locate Section B"}

            # If table extraction failed, try text fallback
            if not extraction_result.get("success"):
                pages_to_try = extraction_result.get("pages_searched", []) or pages_to_extract
                if pages_to_try:
                    fallback_result = extract_text_fallback(pdf_path, pages_to_try)
                    if fallback_result.get("success"):
                        extraction_result = fallback_result

        elif doc_type == "scanned":
            if pages_to_extract:
                extraction_result = extract_section_b_ocr(pdf_path, pages_to_extract)
            else:
                extraction_result = {"success": False, "activities": [], "error": "No pages identified for OCR"}

        elif doc_type == "hybrid":
            if pages_to_extract:
                extraction_result = extract_section_b_ocr(pdf_path, pages_to_extract)
            else:
                extraction_result = {"success": False, "activities": [], "error": "Hybrid doc but no image pages found"}

        else:
            extraction_result = {"success": False, "activities": [], "error": f"Unknown document type: {doc_type}"}

        # Step 5: Structure the result
        structured = structure_extraction_result(
            pdf_path,
            doc_type,
            classification_meta,
            location_result,
            extraction_result
        )

        # Add processing time
        structured["extraction_metadata"]["processing_time"] = round(time.time() - start_time, 3)

        return structured

    except Exception as e:
        # Return error structure
        return {
            "company_number": None,
            "incorporation_date": None,
            "document_type": "unknown",
            "extraction_status": "error",
            "section_b": {"activities": []},
            "extraction_metadata": {
                "source_file": pdf_path.name if isinstance(pdf_path, Path) else str(pdf_path),
                "error": str(e),
                "traceback": traceback.format_exc(),
                "extracted_at": datetime.utcnow().isoformat() + "Z",
                "processing_time": round(time.time() - start_time, 3)
            }
        }


def run_pipeline(
    input_dir: str | Path,
    output_dir: str | Path,
    log_dir: Optional[str | Path] = None,
    max_workers: int = 4,
    batch_size: int = 50,
    use_dated_folder: bool = True
) -> dict:
    """
    Run the extraction pipeline on all PDFs in a directory.

    Args:
        input_dir: Directory containing PDF files
        output_dir: Base directory for output JSON files
        log_dir: Directory for log files (defaults to output_dir/logs)
        max_workers: Number of parallel workers
        batch_size: Number of documents to process before saving intermediate results
        use_dated_folder: If True, creates a dated subfolder (YYYY-MM-DD_HHMMSS)

    Returns:
        Batch summary with statistics

    Folder Structure:
        output_dir/
        ├── 2025-01-11_143052/          # Dated run folder (if use_dated_folder=True)
        │   ├── logs/
        │   │   ├── extraction_20250111_143052.log
        │   │   └── failed_documents.txt
        │   ├── <company_number>.json    # Individual extraction results
        │   ├── batch_summary.json       # Aggregated statistics
        │   └── batch_summary_intermediate.json
        └── ...
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    # Create dated subfolder if requested
    if use_dated_folder:
        run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_dir = output_dir / run_timestamp

    log_dir = Path(log_dir) if log_dir else output_dir / "logs"

    # Setup
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(log_dir)

    # Check OCR availability
    ocr_status = check_ocr_available()
    logger.info(f"OCR available: {ocr_status['available']}")
    if not ocr_status['available']:
        logger.warning(f"OCR not available: {ocr_status['errors']}")
        logger.warning("Scanned documents will not be processed correctly")

    # Find all PDFs (deduplicate for case-insensitive filesystems like Windows)
    pdf_files = list({p.resolve() for p in input_dir.glob("*.pdf")} |
                     {p.resolve() for p in input_dir.glob("*.PDF")})
    logger.info(f"Found {len(pdf_files)} PDF files in {input_dir}")

    if not pdf_files:
        logger.warning("No PDF files found")
        return {"batch_info": {"total_documents": 0}, "results": []}

    # Process documents
    all_results = []
    failed_docs = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        future_to_pdf = {executor.submit(process_single_document, pdf): pdf for pdf in pdf_files}

        # Process results with progress bar
        with tqdm(total=len(pdf_files), desc="Processing documents") as pbar:
            for future in as_completed(future_to_pdf):
                pdf_path = future_to_pdf[future]
                try:
                    result = future.result()
                    all_results.append(result)

                    # Save individual result
                    output_filename = pdf_path.stem + ".json"
                    save_to_json(result, output_dir / output_filename)

                    # Log status
                    status = result.get("extraction_status", "unknown")
                    if status == "success":
                        act_count = len(result.get("section_b", {}).get("activities", []))
                        logger.info(f"SUCCESS: {pdf_path.name} - {act_count} activities")
                    else:
                        logger.warning(f"FAILED: {pdf_path.name} - {status}")
                        failed_docs.append(str(pdf_path))

                except Exception as e:
                    logger.error(f"ERROR processing {pdf_path.name}: {e}")
                    failed_docs.append(str(pdf_path))

                pbar.update(1)

                # Save intermediate batch results
                if len(all_results) % batch_size == 0:
                    batch_summary = merge_batch_results(all_results)
                    save_to_json(batch_summary, output_dir / "batch_summary_intermediate.json")

    # Save final batch summary
    batch_summary = merge_batch_results(all_results)
    save_to_json(batch_summary, output_dir / "batch_summary.json")

    # Save failed documents list
    if failed_docs:
        with open(log_dir / "failed_documents.txt", 'w') as f:
            f.write("\n".join(failed_docs))

    # Log final statistics
    logger.info("=" * 50)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"Total documents: {batch_summary['batch_info']['total_documents']}")
    logger.info(f"Successful: {batch_summary['batch_info']['successful']}")
    logger.info(f"Failed: {batch_summary['batch_info']['failed']}")
    logger.info(f"No data: {batch_summary['batch_info']['no_data']}")
    logger.info(f"Total activities extracted: {batch_summary['batch_info']['total_activities']}")
    logger.info("=" * 50)

    return batch_summary


def run_single(pdf_path: str | Path, output_path: Optional[str | Path] = None) -> dict:
    """
    Run the pipeline on a single document.

    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path for output JSON file

    Returns:
        Structured extraction result
    """
    pdf_path = Path(pdf_path)
    result = process_single_document(pdf_path)

    # Validate result
    validation = validate_structured_data(result)
    result["extraction_metadata"]["validation"] = validation

    # Save if output path provided
    if output_path:
        save_to_json(result, output_path)

    return result


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="CIC Document Extraction Pipeline",
        epilog="""
Folder Structure:
  By default, output is organized in dated folders:
    data/output/
    └── 2025-01-11_143052/     # Run timestamp
        ├── logs/
        │   ├── extraction_*.log
        │   └── failed_documents.txt
        ├── <company_number>.json
        └── batch_summary.json

  Use --no-dated to write directly to output folder.
"""
    )
    parser.add_argument("input", help="Input PDF file or directory")
    parser.add_argument("-o", "--output", help="Output directory (default: data/output)")
    parser.add_argument("-w", "--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--single", action="store_true", help="Process single file instead of directory")
    parser.add_argument("--no-dated", action="store_true",
                        help="Don't create dated subfolder for output")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else Path("data/output")

    if args.single or input_path.is_file():
        # Single file mode
        print(f"Processing single file: {input_path}")

        # For single files, create dated folder if not disabled
        if not args.no_dated:
            run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            output_path = output_path / run_timestamp
            output_path.mkdir(parents=True, exist_ok=True)

        output_file = output_path / (input_path.stem + ".json")
        result = run_single(input_path, output_file)

        print(f"\nExtraction Status: {result['extraction_status']}")
        print(f"Document Type: {result['document_type']}")
        print(f"Company Number: {result['company_number']}")
        print(f"Activities Found: {len(result['section_b']['activities'])}")

        for i, act in enumerate(result['section_b']['activities'], 1):
            print(f"\n  Activity {i}:")
            print(f"    {act['activity'][:100]}...")
            print(f"    Benefit: {act['benefit'][:100]}...")

        print(f"\nOutput saved to: {output_file}")

    else:
        # Batch mode
        print(f"Processing directory: {input_path}")
        summary = run_pipeline(
            input_path,
            output_path,
            max_workers=args.workers,
            use_dated_folder=not args.no_dated
        )

        print(f"\nBatch Summary:")
        print(f"  Total: {summary['batch_info']['total_documents']}")
        print(f"  Successful: {summary['batch_info']['successful']}")
        print(f"  Failed: {summary['batch_info']['failed']}")
        print(f"  Activities: {summary['batch_info']['total_activities']}")
