"""
Document Classification Module

Classifies CIC incorporation PDFs as 'electronic', 'scanned', or 'hybrid' based on
extractable text content. Electronic documents have clean text that can
be extracted directly, scanned documents require OCR, and hybrid documents
have both electronic and image-based pages.
"""

import logging
import pdfplumber
from pathlib import Path
from typing import Literal, Tuple

logger = logging.getLogger(__name__)

DocumentType = Literal["electronic", "scanned", "hybrid", "unknown"]


def classify_document(pdf_path: str | Path, sample_pages: int = 5, min_chars_per_page: int = 100) -> Tuple[DocumentType, dict]:
    """
    Classify a PDF document as electronic, scanned, or hybrid.

    Args:
        pdf_path: Path to the PDF file
        sample_pages: Number of pages to sample for classification
        min_chars_per_page: Minimum average characters per page to be considered electronic

    Returns:
        Tuple of (document_type, metadata_dict)
        - document_type: 'electronic', 'scanned', 'hybrid', or 'unknown'
        - metadata_dict: Contains page_count, avg_chars_per_page, sampled_pages,
                         electronic_pages, image_pages
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)

            # Analyze ALL pages to detect hybrid documents
            electronic_pages = []
            image_pages = []
            sampled_pages = []

            for idx in range(page_count):
                page = pdf.pages[idx]
                text = page.extract_text() or ""
                char_count = len(text.strip())

                sampled_pages.append({
                    "page_number": idx + 1,
                    "char_count": char_count
                })

                # Classify each page
                if char_count >= 50:  # Page has meaningful text
                    electronic_pages.append(idx + 1)
                else:
                    image_pages.append(idx + 1)

            # Calculate average for pages with text
            total_chars = sum(p["char_count"] for p in sampled_pages)
            avg_chars = total_chars / page_count if page_count > 0 else 0

            metadata = {
                "page_count": page_count,
                "avg_chars_per_page": round(avg_chars, 2),
                "sampled_pages": sampled_pages,
                "total_sampled_chars": total_chars,
                "electronic_pages": electronic_pages,
                "image_pages": image_pages,
                "electronic_page_count": len(electronic_pages),
                "image_page_count": len(image_pages)
            }

            # Classification logic
            if len(image_pages) == 0:
                # All pages have text
                doc_type = "electronic"
            elif len(electronic_pages) == 0:
                # No pages have text - fully scanned
                doc_type = "scanned"
            else:
                # Mix of electronic and image pages
                doc_type = "hybrid"

            return doc_type, metadata

    except Exception as e:
        logger.error(f"Error classifying {pdf_path}: {e}")
        return "unknown", {"error": str(e)}


def classify_batch(pdf_paths: list[str | Path], sample_pages: int = 5) -> dict:
    """
    Classify multiple PDF documents.

    Args:
        pdf_paths: List of paths to PDF files
        sample_pages: Number of pages to sample per document

    Returns:
        Dictionary mapping file paths to classification results
    """
    results = {}
    for pdf_path in pdf_paths:
        path_str = str(pdf_path)
        doc_type, metadata = classify_document(pdf_path, sample_pages)
        results[path_str] = {
            "document_type": doc_type,
            "metadata": metadata
        }
    return results


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python classify_document.py <pdf_path> [pdf_path2 ...]")
        sys.exit(1)

    paths = sys.argv[1:]

    for path in paths:
        doc_type, metadata = classify_document(path)
        print(f"\n{path}")
        print(f"  Type: {doc_type}")
        print(f"  Pages: {metadata.get('page_count', 'N/A')}")
        print(f"  Avg chars/page: {metadata.get('avg_chars_per_page', 'N/A')}")
