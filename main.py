#!/usr/bin/env python3
"""Robbie — single entry point for the desk-pet AI orchestrator.

Usage:
  python main.py
  robbie start / robbie run
"""

from __future__ import annotations

import asyncio

from config.settings import log
from src.app import main


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
