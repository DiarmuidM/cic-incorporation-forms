#!/bin/bash
# Server Setup Script for CIC Document Extraction
# Run this once on the server to set up the environment
#
# Usage: ./setup_server.sh

set -e  # Exit on any error

PROJECT_DIR="${PROJECT_DIR:-$HOME/cic-incorporation-docs}"

echo ""
echo "============================================================"
echo "CIC Document Extraction - Server Setup"
echo "============================================================"
echo ""

# Create project directory structure
echo "Creating directory structure..."
mkdir -p "$PROJECT_DIR"/{data/{input,output},src,scripts,logs}

cd "$PROJECT_DIR"

# Install system dependencies
echo ""
echo "Installing system dependencies (requires sudo)..."
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils python3-venv python3-pip

# Create virtual environment
echo ""
echo "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python packages
echo ""
echo "Installing Python packages..."
pip install --upgrade pip
pip install pdfplumber pytesseract pdf2image tqdm

# Verify installations
echo ""
echo "Verifying installations..."
echo -n "  Tesseract: "
tesseract --version 2>&1 | head -1
echo -n "  Poppler (pdftoppm): "
pdftoppm -v 2>&1 | head -1
echo -n "  Python: "
python3 --version
echo -n "  pdfplumber: "
python3 -c "import pdfplumber; print(pdfplumber.__version__)"
echo -n "  pytesseract: "
python3 -c "import pytesseract; print(pytesseract.get_tesseract_version())"

echo ""
echo "============================================================"
echo "Setup complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Upload source code:  server upload-code"
echo "  2. Upload PDFs:         server upload-pdfs"
echo "  3. Run extraction:      ./run_extraction.sh --sample-n 100"
echo ""
echo "For low-memory servers (2GB RAM), use:"
echo "  ./run_extraction.sh -w 1 --sample-n 100"
echo ""
