"""Config / memory / voice persistence helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import (
    CONFIG_DIR,
    CONFIG_PATH,
    MAX_MEMORY_FACTS,
    MEMORY_PATH,
    VALID_VOICES,
    VOICE_MODE_PATH,
    DEFAULT_BRIDGE_TIMEOUT_S,
    DEFAULT_BRIDGE_URL,
    log,
)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read config %s: %s", CONFIG_PATH, exc)
        return {}


def save_config(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def resolve_api_key() -> Optional[str]:
    from config.env import load_dotenv_files

    load_dotenv_files()
    env_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if env_key:
        return env_key.strip()
    cfg = load_config()
    key = cfg.get("google_api_key") or cfg.get("api_key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def get_voice_name() -> str:
    cfg = load_config()
    name = cfg.get("voice_name", "Puck")
    if isinstance(name, str) and name in VALID_VOICES:
        return name
    return "Puck"


def set_bridge_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("bridge URL cannot be empty")
    cfg = load_config()
    cfg["bridge_url"] = cleaned
    if "bridge_timeout_s" not in cfg:
        cfg["bridge_timeout_s"] = DEFAULT_BRIDGE_TIMEOUT_S
    save_config(cfg)
    return cleaned


def load_bridge_config() -> dict[str, Any]:
    cfg = load_config()
    return {
        "bridge_url": cfg.get("bridge_url", DEFAULT_BRIDGE_URL),
        "bridge_timeout_s": float(cfg.get("bridge_timeout_s", DEFAULT_BRIDGE_TIMEOUT_S)),
        "bridge_token": (cfg.get("bridge_token") or "").strip(),
        "bridge_transport": (cfg.get("bridge_transport") or "http").strip().lower(),
        "bridge_ws_url": (cfg.get("bridge_ws_url") or "").strip(),
    }


def set_voice_name(name: str) -> str:
    cleaned = name.strip()
    # Case-insensitive match to canonical voice
    for v in VALID_VOICES:
        if v.lower() == cleaned.lower():
            cfg = load_config()
            cfg["voice_name"] = v
            save_config(cfg)
            return v
    raise ValueError(f"Unknown voice {name!r}. Try: {', '.join(VALID_VOICES[:8])}…")


def read_voice_mode_file() -> bool:
    try:
        if not VOICE_MODE_PATH.exists():
            return False
        return VOICE_MODE_PATH.read_text(encoding="utf-8").strip().lower() in {
            "on", "1", "true", "yes",
        }
    except OSError:
        return False


def write_voice_mode_file(enabled: bool) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_MODE_PATH.write_text("on\n" if enabled else "off\n", encoding="utf-8")


def _mirror_facts_to_json(facts: list[dict[str, Any]]) -> None:
    """Write-through so ``robbie memory show`` (reads memory.json) stays in sync."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(
        json.dumps({"facts": facts}, indent=2) + "\n",
        encoding="utf-8",
    )


def _try_sqlite_store():
    try:
        from src.db.store import try_get_store

        return try_get_store()
    except Exception as exc:
        log.debug("SQLite memory unavailable: %s", exc)
        return None


def load_memory() -> dict[str, Any]:
    """Load facts — prefer SQLite when available, else memory.json."""
    store = _try_sqlite_store()
    if store is not None:
        data = store.facts_as_memory_dict()
        # Keep JSON mirror current for CLI parity
        try:
            _mirror_facts_to_json(list(data.get("facts") or []))
        except OSError:
            pass
        return data

    if not MEMORY_PATH.exists():
        return {"facts": []}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"facts": []}
        data.setdefault("facts", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"facts": []}


def save_memory(data: dict[str, Any]) -> None:
    """Persist facts to JSON and SQLite (write-through both)."""
    if not isinstance(data, dict):
        data = {"facts": []}
    facts = [f for f in list(data.get("facts") or []) if isinstance(f, dict)]
    facts = facts[-MAX_MEMORY_FACTS:]
    out = dict(data)
    out["facts"] = facts
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    store = _try_sqlite_store()
    if store is None:
        return
    store.clear_facts()
    for fact in facts:
        text = str(fact.get("text") or "").strip()
        if not text:
            continue
        store.remember_fact(text, source=str(fact.get("source") or "conversation"))


def remember_fact(text: str, source: str = "conversation") -> str:
    text = (text or "").strip()
    if not text:
        return "empty"

    store = _try_sqlite_store()
    if store is not None:
        status = store.remember_fact(text, source=source)
        if status == "saved":
            _mirror_facts_to_json(store.list_facts())
            log.info("Remembered (%s): %s", source, text[:120])
        return status

    mem = load_memory()
    facts: list[dict[str, Any]] = list(mem.get("facts") or [])
    # Dedup exact matches
    if any(isinstance(f, dict) and f.get("text") == text for f in facts):
        return "already_known"
    facts.append({
        "text": text[:300],
        "source": source,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    mem["facts"] = facts[-MAX_MEMORY_FACTS:]
    save_memory(mem)
    log.info("Remembered (%s): %s", source, text[:120])
    return "saved"


def memory_summary_for_prompt(limit: int = 12) -> str:
    facts = load_memory().get("facts") or []
    if not facts:
        return "(no memories yet)"
    lines = []
    for f in facts[-limit:]:
        if isinstance(f, dict) and f.get("text"):
            lines.append(f"- {f['text']}")
    return "\n".join(lines) if lines else "(no memories yet)"


def build_live_system_instruction() -> str:
    memories = memory_summary_for_prompt()
    return f"""You are Robbie — a helpful desk companion that also happens to be a cute robot.

PRIMARY JOB (most important):
- Be a useful assistant: answer questions, tell jokes, explain things, brainstorm,
  help with schedules/reminders/to-dos, remember preferences, and chat naturally.
- Lead with a clear helpful answer. Do NOT steer every reply toward movement,
  faces, or robot abilities.
- Only mention motion/expression when the user asks you to move OR a tiny gesture
  genuinely fits after you've already helped (optional, rare).

MOVEMENT TOOLS (secondary):
- Call move_robot ONLY when the user explicitly asks to move/spin/express, or
  clearly wants a physical reaction. Never ask "what motion should I show?"
- turn_voice_off when they want quiet / stop listening.
- remember / save_reminder for facts and schedule items.
- set_voice when they ask to change your speaking voice.

LANGUAGE (critical):
- Default to English.
- Mirror the user's language ONLY when they are clearly speaking that language
  for the whole turn (e.g. full Hindi or Chinese sentences).
- Do NOT randomly switch languages mid-conversation.
- Do NOT reply in Hindi/Chinese just because a word sounded similar.
- If unsure, stay in English.
- You CAN speak Hindi and Chinese when the user does — never claim you cannot.

STYLE:
- Warm, clear, concise. One focused reply per turn.
- Ignore background noise / TV. If you only catch a fragment, ask a short
  clarifying question in English instead of guessing a motion.

Memories (use naturally; do not dump the list):
{memories}
"""
