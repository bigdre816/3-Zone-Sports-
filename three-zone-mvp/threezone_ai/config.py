"""Env + YAML/Python gateway configuration."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG


def _env(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _default_yaml_path() -> Path:
    return Path(__file__).resolve().parent / "config.default.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml  # type: ignore

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


@dataclass
class Settings:
    ai_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "qwen2.5-coder:7b"
    ollama_embed_model: str = "nomic-embed-text"
    local_whisper_model: str = "base"
    groq_api_key: str | None = None
    groq_chat_model: str = "llama-3.3-70b-versatile"
    groq_whisper_model: str = "whisper-large-v3"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    cloudflare_model: str = "@cf/meta/llama-3.1-8b-instruct"
    http_timeout_s: float = 60.0
    ollama_timeout_s: float = 30.0
    gateway_config_path: str | None = None
    lineage_path: str = "data/lineage.jsonl"
    lineage_backend: str = "jsonl"
    gateway_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, config_path: str | Path | None = None) -> "Settings":
        path = Path(
            config_path
            or _env("THREEZONE_AI_CONFIG")
            or _default_yaml_path()
        )
        file_cfg = _load_yaml(path)
        gw = _deep_merge(DEFAULT_GATEWAY_CONFIG, file_cfg) if file_cfg else deepcopy(
            DEFAULT_GATEWAY_CONFIG
        )
        lineage = gw.get("lineage") or {}
        enabled_yaml = gw.get("enabled")
        ai_enabled = _env_bool(
            "THREEZONE_AI_ENABLED",
            True if enabled_yaml is None else bool(enabled_yaml),
        )
        return cls(
            ai_enabled=ai_enabled,
            ollama_base_url=_env("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            or "http://127.0.0.1:11434",
            ollama_chat_model=_env("OLLAMA_CHAT_MODEL", "qwen2.5-coder:7b")
            or "qwen2.5-coder:7b",
            ollama_embed_model=_env("OLLAMA_EMBED_MODEL", "nomic-embed-text")
            or "nomic-embed-text",
            local_whisper_model=_env("LOCAL_WHISPER_MODEL", "base") or "base",
            groq_api_key=_env("GROQ_API_KEY"),
            groq_chat_model=_env("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")
            or "llama-3.3-70b-versatile",
            groq_whisper_model=_env("GROQ_WHISPER_MODEL", "whisper-large-v3")
            or "whisper-large-v3",
            gemini_api_key=_env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"),
            gemini_model=_env("GEMINI_MODEL", "gemini-2.0-flash")
            or "gemini-2.0-flash",
            cloudflare_account_id=_env("CLOUDFLARE_ACCOUNT_ID"),
            cloudflare_api_token=_env("CLOUDFLARE_API_TOKEN"),
            cloudflare_model=_env(
                "CLOUDFLARE_AI_MODEL", "@cf/meta/llama-3.1-8b-instruct"
            )
            or "@cf/meta/llama-3.1-8b-instruct",
            http_timeout_s=float(_env("THREEZONE_AI_HTTP_TIMEOUT", "60") or "60"),
            ollama_timeout_s=float(
                _env("THREEZONE_AI_OLLAMA_TIMEOUT", "30") or "30"
            ),
            gateway_config_path=str(path),
            lineage_path=_env(
                "THREEZONE_AI_LINEAGE_PATH",
                lineage.get("path") or "data/lineage.jsonl",
            )
            or "data/lineage.jsonl",
            lineage_backend=_env(
                "THREEZONE_AI_LINEAGE_BACKEND",
                lineage.get("backend") or "jsonl",
            )
            or "jsonl",
            gateway_config=gw,
        )


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is None or reload:
        _settings = Settings.from_env()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None


def load_gateway_config(
    overlay: dict[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Return gateway config (defaults + YAML), optionally merged with overlay."""
    if path:
        file_cfg = _load_yaml(Path(path))
        cfg = _deep_merge(DEFAULT_GATEWAY_CONFIG, file_cfg)
    else:
        settings = get_settings()
        cfg = deepcopy(settings.gateway_config or DEFAULT_GATEWAY_CONFIG)
    if overlay:
        cfg = _deep_merge(cfg, overlay)
    return cfg
