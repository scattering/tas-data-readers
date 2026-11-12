"""General TAS data-reader adapters."""

from .format_detection import classify_path, scan_directory

__all__ = ["classify_path", "scan_directory"]
