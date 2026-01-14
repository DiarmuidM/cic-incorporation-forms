# CIC Incorporation Forms Extraction Pipeline

A Python pipeline for extracting structured data from UK Community Interest Company (CIC) incorporation documents (CIC 36 forms).

> **Beta Version**: This pipeline is under active development. Features, output formats, and APIs may change. Feedback and contributions are welcome.

## Overview

Community Interest Companies (CICs) are the primary legal form for social enterprises in the UK. This pipeline extracts key information from CIC 36 incorporation forms filed with Companies House, specifically:

- **Section A**: Beneficiaries - who the company is set up to benefit
- **Section B**: Activities and community benefit descriptions
- **Surplus use**: How any profits will be reinvested in the community

The pipeline handles both electronic (text-based) and scanned (image-based) PDF documents using a combination of text extraction and OCR techniques.

## Features

- Automatic document classification (electronic, scanned, or hybrid)
- CIC 36 form location within multi-page incorporation documents
- Table extraction from electronic PDFs using pdfplumber
- OCR extraction from scanned PDFs using Tesseract and pdf2image
- Parallel processing support with configurable workers
- Structured JSON output with comprehensive metadata
- Evaluation and validation tools for quality assessment

## Quick Start

### Windows

```batch
# Install dependencies
pip install -r requirements.txt

# Run extraction on sample documents
run_extraction.bat --sample-n 10
```

### Linux

```bash
# Make scripts executable and run setup
chmod +x setup_server.sh run_extraction.sh
./setup_server.sh

# Run extraction on sample documents
./run_extraction.sh --sample-n 10
```

## Installation

### Prerequisites

- Python 3.11 or higher
- Tesseract OCR
- Poppler (for PDF to image conversion)

### Windows Setup

1. **Install Python 3.11+** from [python.org](https://www.python.org/downloads/)

2. **Install Tesseract OCR** via one of these methods:
   - Chocolatey: `choco install tesseract`
   - Manual: Download from [UB-Mannheim GitHub](https://github.com/UB-Mannheim/tesseract/wiki)

3. **Install Poppler**:
   - Chocolatey: `choco install poppler`
   - Manual: Download from [poppler-windows releases](https://github.com/oschwartz10612/poppler-windows/releases) and extract to `C:\Program Files\poppler-*`

4. **Install Python dependencies**:
   ```batch
   pip install -r requirements.txt
   ```

The pipeline auto-detects Tesseract and Poppler paths on Windows.

### Linux Setup

Run the setup script which handles all dependencies:

```bash
chmod +x setup_server.sh
./setup_server.sh
```

This script will:
- Install system dependencies (tesseract-ocr, poppler-utils)
- Create a Python virtual environment
- Install Python packages from requirements-server.txt

## Usage

### Local Extraction

```batch
# Windows - Run with default 1% sample (~65 docs)
run_extraction.bat

# Run with specific sample size
run_extraction.bat --sample 5          # 5% sample
run_extraction.bat --sample-n 100      # Exactly 100 documents

# Run full extraction with custom worker count
run_extraction.bat --full -w 8         # All documents, 8 parallel workers

# Re-run on specific input folder
run_extraction.bat --input data\input\sample100
```

```bash
# Linux - Same options available
./run_extraction.sh --sample-n 100
./run_extraction.sh --full -w 4
```

### Server Deployment

The `server.bat` script provides remote server management (Windows client):

```batch
# Upload extraction code to server
server upload-code

# Install dependencies on server (run once)
server setup

# Start extraction (interactive menu for sample size)
server start

# Monitor progress
server status
server logs

# Download results when complete
server download
```

## Output Format

### Directory Structure

```
data/output/
└── YYYY-MM-DD_HHMMSS/           # Timestamped run folder
    ├── logs/
    │   ├── extraction_*.log     # Detailed extraction log
    │   └── failed_documents.txt # List of failed documents
    ├── <company_number>.json    # Per-document results
    └── batch_summary.json       # Aggregated statistics
```

### JSON Output Structure

Each extracted document produces a JSON file:

```json
{
  "company_number": "12345678",
  "incorporation_date": "2023-06-16",
  "document_type": "electronic",
  "extraction_status": "success",
  "section_a": {
    "beneficiaries": "young people in the local community facing educational disadvantage"
  },
  "section_b": {
    "activities": [
      {
        "activity": "Provide educational workshops and mentoring programmes",
        "description": "Community benefits through improved educational outcomes and career prospects for disadvantaged youth"
      }
    ],
    "company_differs": "We operate on a not-for-profit basis with all surplus reinvested",
    "surplus_use": "reinvested into expanding community programmes and reaching more beneficiaries"
  },
  "extraction_metadata": {
    "source_file": "12345678_newinc_2023-06-16.pdf",
    "cic36_page": 34,
    "extraction_method": "pdfplumber",
    "extracted_at": "2025-01-14T15:30:00.000Z",
    "document_page_count": 45
  }
}
```

### Extraction Status Values

| Status | Description |
|--------|-------------|
| `success` | Valid Section B content extracted |
| `wrong_section` | Content extracted from wrong form section (e.g., IN01 instead of CIC 36) |
| `ocr_quality_issue` | OCR quality too low for reliable extraction |
| `no_cic36_found` | CIC 36 form not found in document |
| `extraction_failed` | Error during extraction process |

## Pipeline Architecture

### Module Overview

| Module | Purpose |
|--------|---------|
| `pipeline.py` | Main orchestrator - coordinates all extraction stages |
| `classify_document.py` | Classifies PDFs as electronic, scanned, or hybrid |
| `locate_cic36.py` | Finds CIC 36 form pages using pattern matching |
| `extract_electronic.py` | Extracts tables from text-based PDFs |
| `extract_scanned.py` | OCR-based extraction for image PDFs |
| `structure_data.py` | Normalizes output to consistent JSON format |
| `config.py` | Centralized configuration settings |
| `common.py` | Shared utility functions |

### Processing Flow

```
Input PDF
    │
    ▼
┌─────────────────────┐
│ classify_document   │ ─── Determine if electronic/scanned/hybrid
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ locate_cic36        │ ─── Find CIC 36 form pages
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ extract_*           │ ─── Extract Section A & B content
│ (electronic/scanned)│
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ structure_data      │ ─── Normalize to JSON output
└─────────────────────┘
    │
    ▼
Output JSON
```

## Evaluation

### Running Evaluation

```bash
# Generate statistics for an extraction run
python scripts/evaluate.py --input "data/output/2025-01-14_153000" --stats

# Create a sample for manual validation
python scripts/evaluate.py --input "data/output/2025-01-14_153000" --create-sample --size 50

# Calculate accuracy from completed validation
python scripts/evaluate.py --accuracy validation/completed.xlsx
```

### Manual Validation Workflow

1. Run extraction on a sample
2. Create validation worksheet with `--create-sample`
3. Manually review extracted content against source PDFs
4. Rate each extraction: good / partial / wrong / empty
5. Calculate accuracy metrics

## Data

### Input Format

The pipeline expects PDF files with the naming convention:
- `{company_number}_newinc_{date}.pdf` (e.g., `12345678_newinc_2023-06-16.pdf`)
- `{company_number}.pdf` (legacy format)

### Sample Data

The repository includes:
- `data/examples/` - Example CIC 36 forms and documentation
- `data/input/sample100/` - Sample of 100 input PDFs for testing
- `data/output/` - Example extraction results

## Troubleshooting

### Common Issues

**Tesseract not found**
- Windows: Ensure Tesseract is installed and in PATH, or installed to `C:\Program Files\Tesseract-OCR`
- Linux: Run `sudo apt-get install tesseract-ocr`

**Poppler not found**
- Windows: Install Poppler and ensure `pdftoppm` is accessible
- Linux: Run `sudo apt-get install poppler-utils`

**Low OCR quality**
- Try increasing DPI in `src/config.py` (default: 300)
- Some heavily degraded scans may not be recoverable

**Memory issues on server**
- Reduce worker count: `--workers 2`
- Use `requirements-server.txt` which excludes heavy packages

## Configuration

Key settings in `src/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `OCR_DPI` | 300 | Resolution for OCR processing |
| `DEFAULT_WORKERS` | 6 | Parallel processing threads |
| `MAX_PAGES_TO_SEARCH` | 15 | Pages to search for Section B |
| `CONFIDENCE_THRESHOLD` | 0.3 | Document classification threshold |

## License

This project is licensed under the **Creative Commons Attribution 4.0 International License (CC BY 4.0)**.

You are free to:
- **Share** - copy and redistribute the material in any medium or format
- **Adapt** - remix, transform, and build upon the material for any purpose

Under the following terms:
- **Attribution** - You must give appropriate credit and indicate if changes were made

See [LICENSE](LICENSE) for the full license text.
