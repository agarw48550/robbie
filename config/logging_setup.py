"""Structured logging setup for Robbie (Pi-safe rotating files)."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from config.settings import CONFIG_DIR

_CONFIGURED = False


def setup_logging(*, debug: Optional[bool] = None) -> logging.Logger:
    """Configure root robbie logger once. Safe to call repeatedly."""
    global _CONFIGURED
    logger = logging.getLogger("robbie")
    if _CONFIGURED:
        return logger

    if debug is None:
        debug = os.environ.get("ROBBIE_DEBUG", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)
    # Avoid duplicate handlers if basicConfig already ran
    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        stream.setLevel(level)
        logger.addHandler(stream)

        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = Path(CONFIG_DIR) / "robbie.log"
            rotating = RotatingFileHandler(
                log_path,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            rotating.setFormatter(fmt)
            rotating.setLevel(level)
            logger.addHandler(rotating)
        except OSError:
            pass

    # Quiet noisy third-party loggers on Pi
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _CONFIGURED = True
    return logger
