from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.organization import utc_now

DEFAULT_MCP_SETTINGS_FILE = "mcp_settings.json"
DEFAULT_SYSTEM_SETTINGS_FILE = "system_settings.json"

DEFAULT_MCP_SETTINGS = {
    "enabled": True,
    "updated_at": None,
}

DEFAULT_SYSTEM_SETTINGS = {
    "ingestion_paused": False,
    "maintenance_mode": False,
    "updated_at": None,
}


def load_mcp_settings(file_path: str | Path = DEFAULT_MCP_SETTINGS_FILE) -> dict[str, Any]:
    return _normalize_mcp_settings(_load_json(file_path, DEFAULT_MCP_SETTINGS))


def update_mcp_settings(
    updates: dict[str, Any],
    file_path: str | Path = DEFAULT_MCP_SETTINGS_FILE,
) -> dict[str, Any]:
    current = load_mcp_settings(file_path)
    merged = {**current, **updates, "updated_at": utc_now()}
    settings = _normalize_mcp_settings(merged)
    _save_json(file_path, settings)
    return settings


def load_system_settings(file_path: str | Path = DEFAULT_SYSTEM_SETTINGS_FILE) -> dict[str, Any]:
    return _normalize_system_settings(_load_json(file_path, DEFAULT_SYSTEM_SETTINGS))


def update_system_settings(
    updates: dict[str, Any],
    file_path: str | Path = DEFAULT_SYSTEM_SETTINGS_FILE,
) -> dict[str, Any]:
    current = load_system_settings(file_path)
    merged = {**current, **updates, "updated_at": utc_now()}
    settings = _normalize_system_settings(merged)
    _save_json(file_path, settings)
    return settings


def _load_json(file_path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        return dict(default)

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return dict(default)

    return data if isinstance(data, dict) else dict(default)


def _save_json(file_path: str | Path, data: dict[str, Any]) -> None:
    path = Path(file_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def _normalize_mcp_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(settings.get("enabled", DEFAULT_MCP_SETTINGS["enabled"])),
        "updated_at": settings.get("updated_at"),
    }


def _normalize_system_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "ingestion_paused": bool(settings.get("ingestion_paused", False)),
        "maintenance_mode": bool(settings.get("maintenance_mode", False)),
        "updated_at": settings.get("updated_at"),
    }
