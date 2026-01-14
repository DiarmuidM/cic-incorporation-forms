#!/bin/bash
# CIC Incorporation Document Extraction Pipeline (Linux Server)
# Run from: ~/cic-incorporation-docs
#
# Usage:
#   ./run_extraction.sh                    - Run on 1% sample (default)
#   ./run_extraction.sh --full             - Run on all documents
#   ./run_extraction.sh --sample 5         - Run on 5% sample
#   ./run_extraction.sh --sample-n 100     - Run on exactly 100 documents
#   ./run_extraction.sh --help             - Show help

# === CONFIGURATION ===
PROJECT_DIR="${PROJECT_DIR:-$HOME/cic-incorporation-docs}"
INPUT_DIR="${PROJECT_DIR}/data/input"
OUTPUT_DIR="${PROJECT_DIR}/data/output"
WORKERS=2  # Conservative for 2GB RAM server
SAMPLE_PERCENT=1
SAMPLE_N=""

# === PARSE ARGUMENTS ===
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            echo ""
            echo "CIC Incorporation Document Extraction Pipeline"
            echo "==============================================="
            echo ""
            echo "Usage: ./run_extraction.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --sample N      Process N% random sample (default: 1%)"
            echo "  --sample-n N    Process exactly N random documents"
            echo "  -n N            Alias for --sample-n"
            echo "  --full          Process all documents (100%)"
            echo "  --workers N     Number of parallel workers (default: 2)"
            echo "  -w N            Alias for --workers"
            echo "  --input PATH    Use custom input folder"
            echo "  -i PATH         Alias for --input"
            echo "  --help, -h      Show this help message"
            echo ""
            echo "Directories:"
            echo "  Input:  $INPUT_DIR"
            echo "  Output: $OUTPUT_DIR"
            echo ""
            echo "Examples:"
            echo "  ./run_extraction.sh                     Process 1% sample"
            echo "  ./run_extraction.sh --sample 5          Process 5% sample"
            echo "  ./run_extraction.sh --sample-n 100      Process exactly 100 docs"
            echo "  ./run_extraction.sh --full -w 1         Process all with 1 worker"
            echo ""
            exit 0
            ;;
        --full)
            SAMPLE_PERCENT=100
            shift
            ;;
        --sample)
            SAMPLE_PERCENT="$2"
            shift 2
            ;;
        --sample-n|-n)
            SAMPLE_N="$2"
            shift 2
            ;;
        --workers|-w)
            WORKERS="$2"
            shift 2
            ;;
        --input|-i)
            CUSTOM_INPUT="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# === MAIN ===
echo ""
echo "============================================================"
echo "CIC Incorporation Document Extraction Pipeline"
echo "============================================================"
echo ""

cd "$PROJECT_DIR" || exit 1

# Activate virtual environment if it exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Check if custom input folder is specified
if [ -n "$CUSTOM_INPUT" ]; then
    RUN_INPUT="$CUSTOM_INPUT"
    PDF_COUNT=$(find "$CUSTOM_INPUT" -name "*.pdf" -o -name "*.PDF" | wc -l)
    echo "Using custom input folder: $CUSTOM_INPUT"
    echo "Found $PDF_COUNT PDF files"
    echo "Workers: $WORKERS"
    echo ""
else
    # Count PDFs in input directory
    PDF_COUNT=$(find "$INPUT_DIR" -name "*.pdf" -o -name "*.PDF" | wc -l)
    echo "Found $PDF_COUNT PDF files in input directory"

    # Calculate sample size
    if [ -n "$SAMPLE_N" ]; then
        SAMPLE_SIZE=$SAMPLE_N
        echo "Sample: $SAMPLE_N documents (fixed count)"
    else
        SAMPLE_SIZE=$((PDF_COUNT * SAMPLE_PERCENT / 100))
        [ $SAMPLE_SIZE -lt 1 ] && SAMPLE_SIZE=1
        echo "Sample: ${SAMPLE_PERCENT}% = ~$SAMPLE_SIZE documents"
    fi
    echo "Workers: $WORKERS"
    echo ""

    # Create sample or use full
    if [ -n "$SAMPLE_N" ]; then
        echo "Creating random sample of $SAMPLE_N documents..."
        SAMPLE_DIR="$PROJECT_DIR/data/sample_${SAMPLE_N}docs"
        rm -rf "$SAMPLE_DIR"
        python3 scripts/create_sample.py "$INPUT_DIR" "$SAMPLE_DIR" "$SAMPLE_N"
        RUN_INPUT="$SAMPLE_DIR"
    elif [ "$SAMPLE_PERCENT" -lt 100 ]; then
        echo "Creating random sample..."
        SAMPLE_DIR="$PROJECT_DIR/data/sample_${SAMPLE_PERCENT}pct"
        rm -rf "$SAMPLE_DIR"
        python3 scripts/create_sample.py "$INPUT_DIR" "$SAMPLE_DIR" "$SAMPLE_SIZE"
        RUN_INPUT="$SAMPLE_DIR"
    else
        RUN_INPUT="$INPUT_DIR"
    fi
fi

echo ""
echo "Input directory: $RUN_INPUT"
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Starting extraction..."
echo "============================================================"
echo ""

# Run pipeline
python3 src/pipeline.py "$RUN_INPUT" -o "$OUTPUT_DIR" -w "$WORKERS"

# Get most recent output folder
FINAL_OUTPUT=$(ls -td "$OUTPUT_DIR"/20* 2>/dev/null | head -1)

echo ""
echo "============================================================"
echo "Extraction complete!"
echo "============================================================"
echo ""
echo "Output saved to: $FINAL_OUTPUT"
echo ""
echo "Next steps:"
echo "  1. Check the output folder: $FINAL_OUTPUT"
echo "  2. Review batch_summary.json for statistics"
echo "  3. Run: python3 scripts/evaluate.py --input \"$FINAL_OUTPUT\" --stats"
echo ""
