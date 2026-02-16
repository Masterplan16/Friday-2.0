"""
Batch progress tracker with Telegram updates.

Features:
- Real-time counters (total, success, failed, skipped)
- Telegram message updates (edit existing message)
- Throttled updates (max every 5s)
- Inline buttons [Pause/Annuler/Détails]
- Category breakdown

AC3: Progress tracking & notifications
"""

import time
from pathlib import Path
from typing import Dict, Optional

import structlog
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = structlog.get_logger(__name__)


def format_duration(seconds: int) -> str:
    """Format duration in human-readable format."""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    elif minutes > 0:
        return f"{minutes}m{secs:02d}s"
    else:
        return f"{secs}s"


class BatchProgressTracker:
    """
    Track batch processing progress and update Telegram.

    Features:
    - Real-time counters (total, success, failed, skipped)
    - Telegram message updates (edit existing message)
    - Throttled updates (max every 5s)
    - Inline buttons [Pause/Annuler/Détails]
    - Category breakdown

    AC3: Progress tracking temps réel
    """

    def __init__(
        self,
        batch_id: str,
        folder_path: str,
        bot: telegram.Bot,
        chat_id: int,
        message_id: int,
        topic_id: int,  # Metrics & Logs topic
    ):
        """
        Initialize progress tracker.

        Args:
            batch_id: Unique batch ID
            folder_path: Folder being processed (displayed in progress)
            bot: Telegram bot instance
            chat_id: Chat ID
            message_id: Message ID to edit
            topic_id: Topic ID (Metrics & Logs)
        """
        self.batch_id = batch_id
        self.folder_path = folder_path
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.topic_id = topic_id

        # Counters
        self.total_files = 0
        self.processed = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0

        # Tracking
        self.start_time = time.time()
        self.last_update_time = 0
        self.failed_files: list[tuple[str, str]] = []  # (file_path, error)
        self.categories: Dict[str, int] = {}

        # State
        self.paused = False
        self.cancelled = False

    def increment_success(self, category: Optional[str] = None):
        """
        Increment success counter.

        Args:
            category: File category (optional)
        """
        self.processed += 1
        self.success += 1

        if category:
            self.categories[category] = self.categories.get(category, 0) + 1

    def increment_failed(self, file_path: str, error: str):
        """
        Increment failed counter.

        Args:
            file_path: Failed file path
            error: Error message
        """
        self.processed += 1
        self.failed += 1
        self.failed_files.append((file_path, error))

    def increment_skipped(self, file_path: str, reason: str):
        """
        Increment skipped counter.

        Args:
            file_path: Skipped file path
            reason: Skip reason
        """
        self.processed += 1
        self.skipped += 1

    async def update_telegram(self, throttle: bool = True, force: bool = False):
        """
        Update Telegram progress message (edit existing).

        Args:
            throttle: If True, only update if >5s since last update
            force: If True, ignore throttle

        AC3: Update progression Telegram (throttle 5s)
        """
        # Throttle check
        if throttle and not force:
            if time.time() - self.last_update_time < 5:
                return

        # Progress percentage
        progress_pct = (self.processed / self.total_files * 100) if self.total_files > 0 else 0

        # Elapsed time
        elapsed = int(time.time() - self.start_time)
        elapsed_str = format_duration(elapsed)

        # Display folder name instead of batch_id for readability
        folder_display = Path(self.folder_path).name if self.folder_path else self.batch_id

        # Categories breakdown
        categories_str = "\n".join(
            f"  - {cat} : {count} fichiers"
            for cat, count in sorted(self.categories.items(), key=lambda x: -x[1])
        )

        # Message
        message = (
            f"Traitement batch : {folder_display}/\n"
            f"Progression : {self.processed}/{self.total_files} fichiers ({progress_pct:.0f}%)\n"
            f"Traites : {self.success}\n"
            f"Echecs : {self.failed}\n"
            f"Skip : {self.skipped}\n"
            f"Temps ecoule : {elapsed_str}\n"
            f"Categories :\n{categories_str or '  (aucune encore)'}"
        )

        # Inline buttons
        keyboard = [
            [
                InlineKeyboardButton(
                    "Pause" if not self.paused else "Reprendre",
                    callback_data=f"batch_pause_{self.batch_id}",
                ),
                InlineKeyboardButton("Annuler", callback_data=f"batch_cancel_{self.batch_id}"),
            ],
            [InlineKeyboardButton("Details", callback_data=f"batch_details_{self.batch_id}")],
        ]

        # Edit message
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                message_thread_id=self.topic_id or None,
            )
            self.last_update_time = time.time()
        except telegram.error.BadRequest as e:
            # Message identical -> skip
            if "message is not modified" not in str(e).lower():
                logger.error(
                    "telegram_update_failed",
                    batch_id=self.batch_id,
                    error=str(e),
                )
