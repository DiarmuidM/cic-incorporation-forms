#!/usr/bin/env python
"""
Create a random sample of PDF files for pipeline testing.

Usage:
    python scripts/create_sample.py <input_dir> <output_dir> <sample_size>
"""

import random
import shutil
import sys
from pathlib import Path


def create_sample(input_dir: str, output_dir: str, sample_size: int, seed: int = None, clear_existing: bool = True):
    """Copy a random sample of PDFs to output directory.

    Args:
        input_dir: Source directory containing PDFs
        output_dir: Destination directory for sample
        sample_size: Number of files to sample
        seed: Random seed for reproducibility
        clear_existing: If True, removes existing files in output_dir first
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # Find all PDFs
    pdfs = list(input_path.glob("*.pdf")) + list(input_path.glob("*.PDF"))

    if not pdfs:
        print(f"No PDF files found in {input_dir}")
        return 0

    # Set seed for reproducibility if provided
    if seed is not None:
        random.seed(seed)

    # Sample
    sample_size = min(sample_size, len(pdfs))
    sample = random.sample(pdfs, sample_size)

    # Clear existing directory if requested
    if clear_existing and output_path.exists():
        existing_pdfs = list(output_path.glob("*.pdf")) + list(output_path.glob("*.PDF"))
        # Remove duplicates (case-insensitive match on Windows)
        existing_pdfs = list({p.resolve(): p for p in existing_pdfs}.values())
        if existing_pdfs:
            print(f"Clearing {len(existing_pdfs)} existing files from {output_dir}")
            for pdf in existing_pdfs:
                try:
                    pdf.unlink()
                except FileNotFoundError:
                    pass  # Already deleted

    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)

    # Copy files
    for pdf in sample:
        shutil.copy(pdf, output_path / pdf.name)

    print(f"Copied {len(sample)} files to {output_dir}")
    return len(sample)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python create_sample.py <input_dir> <output_dir> <sample_size> [seed]")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_dir = sys.argv[2]
    sample_size = int(sys.argv[3])
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else None

    create_sample(input_dir, output_dir, sample_size, seed)
