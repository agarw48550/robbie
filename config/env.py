"""Environment / .env loading helpers (optional; does not replace config.json)."""

from __future__ import annotations

import os
from pathlib import Path

from config.settings import log

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_LOADED = False


def load_dotenv_files() -> None:
    """Load project ``.env`` then ``~/.config/robbie/.env`` if python-dotenv is available.

    Existing process env and ``~/.config/robbie/config.json`` remain authoritative
    when keys are already set.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        log.debug("python-dotenv not installed — skipping .env load")
        return

    project_env = _PROJECT_ROOT / ".env"
    if project_env.exists():
        load_dotenv(project_env, override=False)
        log.debug("Loaded %s", project_env)

    home_env = Path.home() / ".config" / "robbie" / ".env"
    if home_env.exists():
        load_dotenv(home_env, override=False)
        log.debug("Loaded %s", home_env)


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def body_audio_flag() -> bool:
    """``ROBBIE_BODY_AUDIO`` — default 0 / False (Pi sounddevice path)."""
    from config.settings import ROBBIE_BODY_AUDIO_DEFAULT

    return env_flag("ROBBIE_BODY_AUDIO", default=ROBBIE_BODY_AUDIO_DEFAULT)
