from __future__ import annotations

import os
import re
from pathlib import Path


def get_agent_api_key(agent_name: str) -> str | None:
    agent = agent_name.lower().strip()
    env_map = {
        "chat": os.getenv("GROQ_API_KEY_CHAT") or os.getenv("GROQ_API_KEY"),
        "optimizer": os.getenv("GROQ_API_KEY_OPT"),
        "forecast": os.getenv("GROQ_API_KEY_FORECAST"),
    }
    if env_map.get(agent):
        return env_map[agent].strip()

    keys_from_csv = _keys_from_env_csv()
    if keys_from_csv:
        idx = {"chat": 0, "optimizer": 1, "forecast": 2}.get(agent, 0)
        if idx < len(keys_from_csv):
            return keys_from_csv[idx]

    keys_from_file = _keys_from_file()
    if keys_from_file:
        idx = {"chat": 0, "optimizer": 1, "forecast": 2}.get(agent, 0)
        if idx < len(keys_from_file):
            return keys_from_file[idx]
    return None


def _keys_from_env_csv() -> list[str]:
    raw = os.getenv("GROQ_API_KEYS", "")
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _keys_from_file() -> list[str]:
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    candidate_files = [
        repo_root / "groq api key.txt",
        backend_root / "groq api key.txt",
    ]
    keys: list[str] = []
    for path in candidate_files:
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = re.findall(r"(gsk_[A-Za-z0-9]+)", content)
        if found:
            keys.extend([item.strip() for item in found])
        if keys:
            return keys
    return []
