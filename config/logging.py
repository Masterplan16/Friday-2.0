#!/usr/bin/env python3
"""
Friday 2.0 - Configuration structlog (Story 1.5 review fix L2)

Configuration centralisée de structlog pour logging JSON structuré.

Usage:
    from config.logging import configure_logging

    # Au démarrage de l'application
    configure_logging()

    # Dans les modules
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("message", key=value)
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


def add_app_context(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """
    Ajoute contexte applicatif à chaque log.

    Ajoute :
    - app: "friday-2.0"
    - environment: dev/prod
    """
    event_dict["app"] = "friday-2.0"
    event_dict["environment"] = "development"  # TODO: Read from env var
    return event_dict


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
    enable_colors: bool = False,
) -> None:
    """
    Configure structlog pour Friday 2.0.

    Args:
        level: Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Si True, logs en JSON. Si False, logs lisibles (dev)
        enable_colors: Si True, colorise les logs console (dev uniquement)

    Example:
        >>> configure_logging(level="DEBUG", json_format=False, enable_colors=True)
    """
    # Configuration standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    # Processors structlog
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_app_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Format final
    if json_format:
        # Production : JSON
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Development : Human-readable
        if enable_colors:
            processors.append(structlog.dev.ConsoleRenderer(colors=True))
        else:
            processors.append(structlog.dev.ConsoleRenderer(colors=False))

    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


# Auto-configuration si importé comme module
# Par défaut : JSON format pour production readiness
try:
    import os

    log_level = os.getenv("LOG_LEVEL", "INFO")
    json_logs = os.getenv("LOG_FORMAT", "json") == "json"

    configure_logging(level=log_level, json_format=json_logs)
except Exception as e:
    # Fallback : config minimaliste si erreur
    print(f"Warning: structlog auto-config failed: {e}", file=sys.stderr)
    logging.basicConfig(level=logging.INFO)
