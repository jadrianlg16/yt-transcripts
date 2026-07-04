from __future__ import annotations

import ipaddress
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

DEFAULT_AI_SETTINGS_FILE = "ai_settings.json"
DEFAULT_PROVIDER = "ollama"
DEFAULT_AI_BASE_URL = "http://localhost:11434/api"
DEFAULT_SUMMARY_MODEL = "llama3.2:3b"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_PROMPT_VERSION = "stage6-v1"
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 600
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0


DEFAULT_AI_SETTINGS = {
    "enabled": False,
    "provider": DEFAULT_PROVIDER,
    "base_url": DEFAULT_AI_BASE_URL,
    "summary_model": DEFAULT_SUMMARY_MODEL,
    "embedding_model": DEFAULT_EMBEDDING_MODEL,
    "temperature": DEFAULT_TEMPERATURE,
    "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "prompt_version": DEFAULT_PROMPT_VERSION,
}


class AISettingsStore:
    def __init__(
        self,
        file_path: str | Path = DEFAULT_AI_SETTINGS_FILE,
        allow_remote_base_url: bool = False,
    ):
        self.file_path = Path(file_path)
        self.allow_remote_base_url = allow_remote_base_url
        self.data = self._load()

    def get_settings(self) -> dict[str, Any]:
        return deepcopy(self.data)

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        merged = {
            **self.data,
            **(updates or {}),
        }
        self.data = normalize_ai_settings(
            merged,
            allow_remote_base_url=self.allow_remote_base_url,
        )
        self._save()
        return self.get_settings()

    def reset(self) -> dict[str, Any]:
        self.data = default_ai_settings()
        self._save()
        return self.get_settings()

    def _load(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return default_ai_settings()

        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except (OSError, json.JSONDecodeError):
            return default_ai_settings()

        try:
            return normalize_ai_settings(
                raw if isinstance(raw, dict) else {},
                allow_remote_base_url=self.allow_remote_base_url,
            )
        except ValueError:
            return default_ai_settings()

    def _save(self) -> None:
        if self.file_path.parent != Path("."):
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, ensure_ascii=False)


def default_ai_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_AI_SETTINGS)


def normalize_ai_settings(
    settings: dict[str, Any] | None,
    allow_remote_base_url: bool = False,
) -> dict[str, Any]:
    raw = settings or {}
    provider = str(raw.get("provider") or DEFAULT_PROVIDER).strip().lower()
    if provider != DEFAULT_PROVIDER:
        raise ValueError("Only the Ollama provider is supported")

    return {
        "enabled": _as_bool(raw.get("enabled", DEFAULT_AI_SETTINGS["enabled"])),
        "provider": provider,
        "base_url": normalize_base_url(
            raw.get("base_url") or DEFAULT_AI_BASE_URL,
            allow_remote_base_url=allow_remote_base_url,
        ),
        "summary_model": _clean_model_name(raw.get("summary_model"), DEFAULT_SUMMARY_MODEL),
        "embedding_model": _clean_model_name(raw.get("embedding_model"), DEFAULT_EMBEDDING_MODEL),
        "temperature": _bounded_float(
            raw.get("temperature", DEFAULT_TEMPERATURE),
            DEFAULT_TEMPERATURE,
            MIN_TEMPERATURE,
            MAX_TEMPERATURE,
        ),
        "timeout_seconds": int(_bounded_float(
            raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            DEFAULT_TIMEOUT_SECONDS,
            MIN_TIMEOUT_SECONDS,
            MAX_TIMEOUT_SECONDS,
        )),
        "prompt_version": _clean_text(raw.get("prompt_version"), DEFAULT_PROMPT_VERSION, max_length=80),
    }


def normalize_base_url(value: Any, allow_remote_base_url: bool = False) -> str:
    text = str(value or DEFAULT_AI_BASE_URL).strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("AI base_url must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("AI base_url must not include credentials")
    if not allow_remote_base_url and not is_local_base_url(text):
        raise ValueError("AI base_url must point to localhost unless remote URLs are explicitly allowed")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("AI base_url port is invalid") from exc

    hostname = (parsed.hostname or "").rstrip(".").lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{port}" if port else hostname
    path = parsed.path.rstrip("/") or "/api"
    return urlunparse((
        parsed.scheme.lower(),
        netloc,
        path,
        "",
        "",
        "",
    ))


def is_local_base_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    hostname = (parsed.hostname or "").strip("[]").rstrip(".").lower()
    if hostname == "localhost":
        return True

    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clean_model_name(value: Any, default: str) -> str:
    return _clean_text(value, default, max_length=120)


def _clean_text(value: Any, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:max_length]


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)
