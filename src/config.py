"""
Centralized Configuration

All configurable settings for the CIC extraction pipeline.
Values can be overridden via environment variables.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class OCRConfig:
    """OCR-specific configuration."""
    dpi: int = 300
    tesseract_paths: list = field(default_factory=lambda: [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\diarm\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    ])
    poppler_paths: list = field(default_factory=lambda: [
        r"C:\Program Files\poppler-25.01.0\Library\bin",
        r"C:\Program Files\poppler-24.08.0\Library\bin",
        r"C:\Program Files\poppler-24.07.0\Library\bin",
        r"C:\Program Files\poppler\Library\bin",
    ])


@dataclass
class ExtractionConfig:
    """Extraction-related configuration."""
    min_chars_per_page: int = 50
    confidence_threshold: float = 0.3
    max_pages_to_search: int = 15
    default_workers: int = 6


@dataclass
class PathConfig:
    """Path configuration - can be overridden via environment variables."""
    project_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Optional[Path] = None
    output_dir: Optional[Path] = None

    def __post_init__(self):
        # Allow environment variable overrides
        if os.environ.get("CIC_DATA_DIR"):
            self.data_dir = Path(os.environ["CIC_DATA_DIR"])
        elif self.data_dir is None:
            self.data_dir = self.project_dir / "data"

        if os.environ.get("CIC_OUTPUT_DIR"):
            self.output_dir = Path(os.environ["CIC_OUTPUT_DIR"])
        elif self.output_dir is None:
            self.output_dir = self.data_dir / "output"


@dataclass
class Config:
    """Main configuration container."""
    ocr: OCRConfig = field(default_factory=OCRConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    paths: PathConfig = field(default_factory=PathConfig)


# Global configuration instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config():
    """Reset configuration to defaults (useful for testing)."""
    global _config
    _config = None
