#!/usr/bin/env python3
"""
Script d'initialisation cold start mode (Story 2.2 Task 7).

Initialise ou reset le cold start tracking pour email.classify.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import structlog

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

logger = structlog.get_logger()


async def init_cold_start(reset: bool = False):
    """
    Initialise ou reset le cold start pour email.classify.

    Args:
        reset: Si True, reset le compteur même si déjà existant
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    try:
        conn = await asyncpg.connect(dsn=database_url)

        # Check si existe déjà
        existing = await conn.fetchrow(
            """
            SELECT phase, emails_processed, accuracy
            FROM core.cold_start_tracking
            WHERE module = 'email' AND action_type = 'classify'
            """
        )

        if existing and not reset:
            logger.info(
                "cold_start_already_exists",
                phase=existing["phase"],
                emails_processed=existing["emails_processed"],
                accuracy=existing["accuracy"],
                message="Utiliser --reset pour réinitialiser",
            )
            await conn.close()
            return

        # Insert ou update
        await conn.execute(
            """
            INSERT INTO core.cold_start_tracking
                (module, action_type, phase, emails_processed, accuracy)
            VALUES ('email', 'classify', 'cold_start', 0, NULL)
            ON CONFLICT (module, action_type)
            DO UPDATE SET
                phase = 'cold_start',
                emails_processed = 0,
                accuracy = NULL
            """
        )

        action = "reset" if existing else "initialized"
        logger.info(
            f"cold_start_{action}",
            module="email",
            action="classify",
            phase="cold_start",
            emails_processed=0,
        )

        await conn.close()

    except Exception as e:
        logger.error("init_cold_start_failed", error=str(e), error_type=type(e).__name__)
        sys.exit(1)


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Initialiser cold start mode pour email.classify")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset le compteur même si déjà existant",
    )

    args = parser.parse_args()

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )

    asyncio.run(init_cold_start(reset=args.reset))


if __name__ == "__main__":
    main()
