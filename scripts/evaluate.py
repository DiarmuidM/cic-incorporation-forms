#!/usr/bin/env python
"""
CIC Extraction Evaluation Script

Generates evaluation reports, creates validation samples, and calculates accuracy
from completed validation worksheets.

Usage:
    # Generate evaluation report from extraction results
    python scripts/evaluate.py --input data/output --report reports/evaluation.md

    # Use random 10% sample of input data
    python scripts/evaluate.py --input data/output --sample 10 --report reports/evaluation.md

    # Create validation sample for manual review
    python scripts/evaluate.py --create-sample --size 50 --output validation/sample.xlsx

    # Calculate accuracy from completed validation worksheet
    python scripts/evaluate.py --accuracy validation/completed.xlsx

    # Generate JSON report for programmatic access
    python scripts/evaluate.py --input data/output --json reports/metrics.json
"""

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from evaluation.metrics import compute_all_metrics
from evaluation.quality import generate_quality_report, get_quality_label
from evaluation.sampling import (
    create_validation_sample,
    generate_validation_worksheet,
    calculate_validation_accuracy
)
from evaluation.report import (
    generate_summary_report,
    generate_json_report,
    save_report
)


def load_extraction_results(input_path: Path,
                            sample_percent: float = None,
                            seed: int = None) -> list[dict]:
    """
    Load extraction results from JSON files in a directory.

    Args:
        input_path: Path to JSON file or directory of JSON files
        sample_percent: If specified, randomly sample this percentage (0-100)
        seed: Random seed for reproducibility

    Returns:
        List of extraction result dictionaries
    """
    results = []

    if input_path.is_file():
        # Single file
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
    elif input_path.is_dir():
        # Directory of JSON files
        for json_file in input_path.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        results.extend(data)
                    else:
                        results.append(data)
            except Exception as e:
                print(f"Warning: Could not load {json_file}: {e}")

    # Apply random sampling if requested
    if sample_percent is not None and 0 < sample_percent < 100:
        if seed is not None:
            random.seed(seed)
        sample_size = max(1, int(len(results) * sample_percent / 100))
        results = random.sample(results, min(sample_size, len(results)))
        print(f"Randomly sampled {len(results)} documents ({sample_percent}%)")

    return results


def cmd_generate_report(args):
    """Generate evaluation report from extraction results."""
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Input path does not exist: {input_path}")
        return 1

    print(f"Loading extraction results from: {input_path}")
    results = load_extraction_results(
        input_path,
        sample_percent=args.sample,
        seed=args.seed
    )

    if not results:
        print("Error: No extraction results found")
        return 1

    print(f"Loaded {len(results)} extraction results")

    # Generate report
    if args.json:
        # JSON report
        report = generate_json_report(
            results,
            pipeline_version=args.version
        )
        output_path = Path(args.json)
    else:
        # Markdown report
        report = generate_summary_report(
            results,
            output_format='markdown',
            pipeline_version=args.version
        )
        output_path = Path(args.report) if args.report else Path("reports/evaluation.md")

    # Add date prefix to filename unless --no-dated specified
    if not args.no_dated:
        date_prefix = datetime.now().strftime("%Y-%m-%d")
        # Check if filename already has a date-like prefix (YYYY-)
        if not output_path.stem.startswith(("20", "19")):
            output_path = output_path.parent / f"{date_prefix}_{output_path.name}"

    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if save_report(report, output_path):
        print(f"Report saved to: {output_path}")
        return 0
    else:
        print("Error: Failed to save report")
        return 1


def cmd_create_sample(args):
    """Create validation sample for manual review."""
    input_path = Path(args.input) if args.input else Path("data/output")

    if not input_path.exists():
        print(f"Error: Input path does not exist: {input_path}")
        return 1

    print(f"Loading extraction results from: {input_path}")
    results = load_extraction_results(
        input_path,
        sample_percent=args.sample,
        seed=args.seed
    )

    if not results:
        print("Error: No extraction results found")
        return 1

    print(f"Loaded {len(results)} extraction results")

    # Create stratified sample
    sample = create_validation_sample(
        results,
        sample_size=args.size,
        stratify_by='document_type',
        include_errors=True
    )

    print(f"Created sample with {len(sample)} documents")

    # Generate worksheet
    output_path = Path(args.output) if args.output else Path("validation/sample.xlsx")

    # Add date prefix to filename unless --no-dated specified
    if not args.no_dated:
        date_prefix = datetime.now().strftime("%Y-%m-%d")
        if not output_path.stem.startswith(("20", "19")):
            output_path = output_path.parent / f"{date_prefix}_{output_path.name}"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    success = generate_validation_worksheet(
        sample,
        output_path=str(output_path),
        max_activities=args.max_activities
    )

    if success:
        print(f"Validation worksheet saved to: {output_path}")
        print("\nWorksheet columns include:")
        print("  - Extracted activity/benefit pairs")
        print("  - Blank columns for correct values")
        print("  - Match indicator and error type columns")
        print("  - Overall rating and notes columns")
        return 0
    else:
        print("Error: Failed to create validation worksheet")
        return 1


def cmd_calculate_accuracy(args):
    """Calculate accuracy from completed validation worksheet."""
    input_path = Path(args.accuracy)

    if not input_path.exists():
        print(f"Error: Validation file does not exist: {input_path}")
        return 1

    print(f"Loading validation results from: {input_path}")

    accuracy = calculate_validation_accuracy(str(input_path))

    if "error" in accuracy:
        print(f"Error: {accuracy['error']}")
        return 1

    # Print results
    print("\n" + "=" * 60)
    print("VALIDATION ACCURACY RESULTS")
    print("=" * 60)

    print(f"\nDocuments Validated: {accuracy['documents_validated']}")
    print(f"Activities Validated: {accuracy['activities_validated']}")

    print(f"\n--- Match Rates ---")
    print(f"Exact Match Rate: {accuracy['exact_match_rate']*100:.1f}%")
    print(f"Partial Match Rate: {accuracy['partial_match_rate']*100:.1f}%")

    print(f"\n--- Quality Distribution ---")
    for rating, count in accuracy['rating_distribution'].items():
        pct = count / accuracy['documents_validated'] * 100 if accuracy['documents_validated'] else 0
        print(f"  {rating}: {count} ({pct:.1f}%)")

    print(f"\n--- Error Distribution ---")
    for error_type, count in accuracy['error_distribution'].items():
        print(f"  {error_type}: {count}")

    print(f"\nMean Rating: {accuracy['mean_rating']:.2f}/5")

    # Save results if output specified
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(accuracy, f, indent=2)
        print(f"\nResults saved to: {output_path}")

    return 0


def cmd_quick_stats(args):
    """Show quick statistics from extraction results."""
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Input path does not exist: {input_path}")
        return 1

    results = load_extraction_results(
        input_path,
        sample_percent=args.sample,
        seed=args.seed
    )

    if not results:
        print("Error: No extraction results found")
        return 1

    metrics = compute_all_metrics(results)
    quality = generate_quality_report(results)

    doc = metrics['document_metrics']
    act = metrics['activity_statistics']

    print("\n" + "=" * 50)
    print("QUICK STATISTICS")
    print("=" * 50)

    print(f"\nDocuments: {doc['total_count']}")
    print(f"Success Rate: {doc['overall_success_rate']*100:.1f}%")
    print(f"Total Activities: {act['total_activities']}")
    print(f"Mean Activities/Doc: {act['activity_count_mean']:.2f}")
    print(f"Quality Score: {quality['mean_quality_score']:.1f}/100 ({get_quality_label(quality['mean_quality_score'])})")

    print(f"\n--- By Document Type ---")
    for dtype, count in doc['counts_by_type'].items():
        rate = doc['success_rates_by_type'].get(dtype, 0) * 100
        print(f"  {dtype}: {count} docs, {rate:.1f}% success")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="CIC Extraction Evaluation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Input/output arguments
    parser.add_argument('--input', '-i',
                        help="Input path (JSON file or directory)")
    parser.add_argument('--output', '-o',
                        help="Output path for results")

    # Sampling options
    parser.add_argument('--sample', '-s', type=float,
                        help="Random sample percentage (0-100) of input data")
    parser.add_argument('--seed', type=int,
                        help="Random seed for reproducible sampling")

    # Report generation
    parser.add_argument('--report', '-r',
                        help="Generate markdown report to this path")
    parser.add_argument('--json', '-j',
                        help="Generate JSON report to this path")

    # Validation sample
    parser.add_argument('--create-sample', action='store_true',
                        help="Create validation sample worksheet")
    parser.add_argument('--size', type=int, default=50,
                        help="Sample size (default: 50)")
    parser.add_argument('--max-activities', type=int, default=5,
                        help="Max activities per doc in worksheet (default: 5)")

    # Accuracy calculation
    parser.add_argument('--accuracy', '-a',
                        help="Calculate accuracy from completed validation file")

    # Quick stats
    parser.add_argument('--stats', action='store_true',
                        help="Show quick statistics")

    # Metadata
    parser.add_argument('--version', default='1.0.0',
                        help="Pipeline version for report")

    # Output options
    parser.add_argument('--no-dated', action='store_true',
                        help="Don't add date prefix to output filenames")

    args = parser.parse_args()

    # Determine which command to run
    if args.accuracy:
        return cmd_calculate_accuracy(args)
    elif args.create_sample:
        return cmd_create_sample(args)
    elif args.stats:
        if not args.input:
            parser.error("--stats requires --input")
        return cmd_quick_stats(args)
    elif args.input and (args.report or args.json):
        return cmd_generate_report(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
