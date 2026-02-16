"""
Dedup Agent (Story 3.8).

Modules:
- scanner: PC-wide file scanner with SHA256 deduplication
- priority_engine: Selection rules for duplicate groups
- report_generator: CSV dry-run report generation
- deleter: Batch deletion with safety checks
- models: Pydantic data models
"""

from agents.src.agents.dedup.models import (
    DedupGroup,
    DedupJob,
    FileEntry,
    ScanConfig,
    ScanResult,
    ScanStats,
)

__all__ = [
    "DedupGroup",
    "DedupJob",
    "FileEntry",
    "ScanConfig",
    "ScanResult",
    "ScanStats",
]
