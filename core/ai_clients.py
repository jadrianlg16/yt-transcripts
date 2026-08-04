from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.ai_settings import (
    DEFAULT_AI_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_SUMMARY_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT_SECONDS,
    normalize_ai_settings,
    normalize_base_url,
)


class OllamaClientError(RuntimeError):
    pass


class OllamaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_AI_BASE_URL,
        timeout_seconds: int | float = DEFAULT_TIMEOUT_SECONDS,
        default_model: str = DEFAULT_SUMMARY_MODEL,
        default_embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        allow_remote_base_url: bool = False,
    ):
        self.base_url = normalize_base_url(
            base_url,
            allow_remote_base_url=allow_remote_base_url,
        )
        self.timeout_seconds = max(1, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
        self.default_model = str(default_model or DEFAULT_SUMMARY_MODEL).strip()
        self.default_embedding_model = str(default_embedding_model or DEFAULT_EMBEDDING_MODEL).strip()
        self.temperature = float(temperature if temperature is not None else DEFAULT_TEMPERATURE)

    @classmethod
    def from_settings(
        cls,
        settings: dict[str, Any],
        allow_remote_base_url: bool = False,
    ) -> "OllamaClient":
        normalized = normalize_ai_settings(
            settings,
            allow_remote_base_url=allow_remote_base_url,
        )
        return cls(
            base_url=normalized["base_url"],
            timeout_seconds=normalized["timeout_seconds"],
            default_model=normalized["summary_model"],
            default_embedding_model=normalized["embedding_model"],
            temperature=normalized["temperature"],
            allow_remote_base_url=allow_remote_base_url,
        )

    def list_models(self, timeout_seconds: int | float | None = None) -> list[dict[str, Any]]:
        data = self._request_json("GET", "/tags", timeout_seconds=timeout_seconds)
        models = data.get("models", [])
        if not isinstance(models, list):
            raise OllamaClientError("Ollama model list response did not include a models array")
        return [model for model in models if isinstance(model, dict)]

    def health(self, timeout_seconds: int | float | None = None) -> dict[str, Any]:
        try:
            models = self.list_models(timeout_seconds=timeout_seconds)
        except OllamaClientError as exc:
            return {
                "ok": False,
                "status": "error",
                "base_url": self.base_url,
                "models": [],
                "error": str(exc),
            }

        return {
            "ok": True,
            "status": "ok",
            "base_url": self.base_url,
            "models": models,
            "model_count": len(models),
        }

    def generate_json(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        schema: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        timeout_seconds: int | float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": str(model or self.default_model).strip(),
            "prompt": str(prompt or ""),
            "stream": False,
            "format": schema or "json",
            "options": {
                **(options or {}),
                "temperature": self.temperature if temperature is None else float(temperature),
            },
        }
        if system:
            payload["system"] = str(system)

        data = self._request_json("POST", "/generate", payload, timeout_seconds=timeout_seconds)
        response_text = data.get("response")
        if not isinstance(response_text, str):
            raise OllamaClientError("Ollama generate response did not include text")

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Ollama generate response was not valid JSON") from exc

        return {
            "json": parsed,
            "response": response_text,
            "raw": data,
            "model": str(data.get("model") or payload["model"]),
        }

    def embed(
        self,
        input_text: str | list[str],
        model: str | None = None,
        truncate: bool = True,
        timeout_seconds: int | float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": str(model or self.default_embedding_model).strip(),
            "input": input_text,
            "truncate": bool(truncate),
        }
        data = self._request_json("POST", "/embed", payload, timeout_seconds=timeout_seconds)
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise OllamaClientError("Ollama embed response did not include embeddings")

        return {
            "embeddings": embeddings,
            "raw": data,
            "model": str(data.get("model") or payload["model"]),
        }

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: int | float | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            self._endpoint(path),
            data=data,
            headers=headers,
            method=method.upper(),
        )
        timeout = max(1, int(timeout_seconds or self.timeout_seconds))

        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            message = _read_error_message(exc)
            raise OllamaClientError(f"Ollama HTTP {exc.code}: {message}") from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise OllamaClientError(f"Ollama request failed: {exc}") from exc

        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Ollama response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OllamaClientError("Ollama response must be a JSON object")
        return parsed

    def _endpoint(self, path: str) -> str:
        clean_path = "/" + str(path or "").strip("/")
        return f"{self.base_url}{clean_path}"


def ollama_client_from_settings(
    settings: dict[str, Any],
    allow_remote_base_url: bool = False,
) -> OllamaClient:
    runtime_settings = dict(settings or {})
    runtime_base_url = os.getenv("YT_TRANSCRIPTS_OLLAMA_BASE_URL", "").strip()
    if runtime_base_url:
        runtime_settings["base_url"] = runtime_base_url
        allow_remote_base_url = True
    return OllamaClient.from_settings(
        runtime_settings,
        allow_remote_base_url=allow_remote_base_url,
    )


def _read_error_message(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:
        return str(exc.reason or exc)

    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError:
        return body.strip() or str(exc.reason or exc)

    if isinstance(parsed, dict):
        return str(parsed.get("error") or parsed.get("message") or body)
    return body.strip() or str(exc.reason or exc)
