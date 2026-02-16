"""
Priority rules engine for duplicate file selection (Story 3.8).

Selects which file to keep among duplicates using hierarchical rules:
1. Path location (BeeStation > Desktop > Downloads)
2. Resolution (for images, via Pillow)
3. EXIF date (for photos, via Pillow)
4. Filename quality (descriptive > generic)

AC3: Regles de priorite pour selection conservation
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import structlog
from agents.src.agents.dedup.models import (
    DedupAction,
    DedupGroup,
    FileEntry,
)

logger = structlog.get_logger(__name__)

# Image extensions for resolution/EXIF checks
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".heic",
    ".heif",
}

# Photo extensions (subset of images, typically from cameras)
PHOTO_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".heic",
    ".heif",
    ".tiff",
    ".tif",
}

# Generic filename patterns (camera/screenshot defaults)
GENERIC_PREFIXES = [
    "img_",
    "dsc_",
    "pxl_",
    "screenshot_",
    "scan_",
    "photo_",
    "image_",
    "pic_",
    "cap_",
    "wp_",
]

# Duplicate suffix patterns
DUPLICATE_PATTERNS = re.compile(
    r"[\s_-]*\(?(\d+)\)?$|[\s_-]*(copy|copie|copier|duplicat|duplicate)[\s_-]*\d*$",
    re.IGNORECASE,
)


class PriorityEngine:
    """
    Select which file to keep among duplicates.

    Priority rules (hierarchical):
    1. Path location (BeeStation > Desktop > Downloads)
    2. Resolution (for images)
    3. EXIF date (for photos)
    4. Filename quality
    """

    PRIORITY_PATHS: dict[str, int] = {
        "BeeStation\\Friday\\Archives\\Photos": 100,
        "BeeStation\\Friday\\Archives\\Documents": 100,
        "BeeStation\\Friday\\Archives": 90,
        "BeeStation": 80,
        "Desktop": 50,
        "Downloads": 30,
        "Temp": 10,
    }

    def select_keeper(self, group: DedupGroup) -> DedupGroup:
        """
        Select 1 file to KEEP, mark others for DELETE.

        Scores each file and selects highest score as keeper.

        Args:
            group: Duplicate group with files

        Returns:
            Updated DedupGroup with keeper and to_delete set
        """
        if len(group.files) < 2:
            if group.files:
                group.files[0].action = DedupAction.keep
                group.keeper = group.files[0]
            return group

        # Score each file
        for entry in group.files:
            score, reason = self.score_file(entry.file_path)
            entry.priority_score = score
            entry.reason = reason

        # Sort by score descending
        sorted_files = sorted(group.files, key=lambda f: f.priority_score, reverse=True)

        # Highest score = keeper
        keeper = sorted_files[0]
        keeper.action = DedupAction.keep
        group.keeper = keeper

        # Rest = delete
        group.to_delete = []
        for entry in sorted_files[1:]:
            entry.action = DedupAction.delete
            group.to_delete.append(entry)

        return group

    def score_file(self, file_path: Path) -> tuple[int, str]:
        """
        Calculate priority score for file.

        Score components:
        - Path priority (0-100)
        - Resolution bonus (0-50) if image
        - EXIF bonus (0-20) if photo
        - Filename quality (-10 to 30)

        Returns:
            (total_score, reason_string)
        """
        reasons = []

        # 1. Path priority (most important)
        path_score = self.get_path_priority(file_path)
        if path_score > 0:
            reasons.append(f"path={path_score}")

        # 2. Resolution (images only)
        resolution_score = 0
        if self._is_image(file_path):
            resolution_score = self.get_resolution_bonus(file_path)
            if resolution_score > 0:
                reasons.append(f"resolution={resolution_score}")

        # 3. EXIF date (photos only)
        exif_score = 0
        if self._is_photo(file_path):
            exif_score = self.get_exif_bonus(file_path)
            if exif_score > 0:
                reasons.append(f"exif={exif_score}")

        # 4. Filename quality
        filename_score = self.get_filename_score(file_path)
        reasons.append(f"filename={filename_score}")

        total = path_score + resolution_score + exif_score + filename_score
        reason = ", ".join(reasons)

        return total, reason

    def get_path_priority(self, file_path: Path) -> int:
        """
        Get priority based on path location.

        Checks if any priority path fragment is contained in the file path.
        Returns highest matching priority.

        Returns: 0-100
        """
        path_str = str(file_path).lower()
        best_score = 0

        for priority_path, score in self.PRIORITY_PATHS.items():
            if priority_path.lower() in path_str:
                best_score = max(best_score, score)

        return best_score

    def get_resolution_bonus(self, file_path: Path) -> int:
        """
        Get bonus for higher resolution images.

        Uses Pillow to read image dimensions.

        Returns: 0-50
        """
        try:
            from PIL import Image

            with Image.open(file_path) as img:
                width, height = img.size
                total_pixels = width * height

                if total_pixels >= 8_000_000:  # 4K+ (3840x2160)
                    return 50
                elif total_pixels >= 2_000_000:  # HD (1920x1080)
                    return 30
                elif total_pixels >= 900_000:  # SD (1280x720)
                    return 10
                else:
                    return 0
        except Exception:
            return 0

    def get_exif_bonus(self, file_path: Path) -> int:
        """
        Get bonus if photo has EXIF original date.

        Returns: 0-20
        """
        try:
            from PIL import Image

            with Image.open(file_path) as img:
                exif = img._getexif()
                if exif and 36867 in exif:  # DateTimeOriginal tag
                    return 20
        except Exception:
            pass

        return 0

    def get_filename_score(self, file_path: Path) -> int:
        """
        Score filename quality.

        Heuristics:
        - Long descriptive name (>20 chars) -> +30
        - Medium name (10-20 chars) -> +15
        - Short name (<10 chars) -> +5
        - Generic pattern (IMG_, DSC_, etc.) -> +0
        - Copy/duplicate suffix -> -10

        Returns: -10 to 30
        """
        name = file_path.stem  # Without extension

        # Duplicate suffix penalty
        if self._has_duplicate_suffix(name):
            return -10

        # Generic patterns
        name_lower = name.lower()
        if any(name_lower.startswith(prefix) for prefix in GENERIC_PREFIXES):
            return 0

        # Length-based score
        if len(name) > 20:
            return 30
        elif len(name) > 10:
            return 15
        else:
            return 5

    def get_resolution_string(self, file_path: Path) -> Optional[str]:
        """
        Get resolution string for an image file.

        Returns: "WIDTHxHEIGHT" or None
        """
        if not self._is_image(file_path):
            return None

        try:
            from PIL import Image

            with Image.open(file_path) as img:
                w, h = img.size
                return f"{w}x{h}"
        except Exception:
            return None

    def get_exif_date_string(self, file_path: Path) -> Optional[str]:
        """
        Get EXIF original date string for a photo.

        Returns: Date string or None
        """
        if not self._is_photo(file_path):
            return None

        try:
            from PIL import Image

            with Image.open(file_path) as img:
                exif = img._getexif()
                if exif and 36867 in exif:
                    return str(exif[36867])
        except Exception:
            pass

        return None

    @staticmethod
    def _is_image(file_path: Path) -> bool:
        """Check if file is an image based on extension."""
        return file_path.suffix.lower() in IMAGE_EXTENSIONS

    @staticmethod
    def _is_photo(file_path: Path) -> bool:
        """Check if file is a photo (camera-origin image)."""
        return file_path.suffix.lower() in PHOTO_EXTENSIONS

    @staticmethod
    def _has_duplicate_suffix(name: str) -> bool:
        """Check if filename has a duplicate suffix like (1), _copy, etc."""
        return DUPLICATE_PATTERNS.search(name) is not None
