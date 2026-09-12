"""Canonical gateway defaults (YAML file mirrors this; swap via overlay/config path)."""

from __future__ import annotations

from typing import Any

DEFAULT_GATEWAY_CONFIG: dict[str, Any] = {
    "enabled": False,
    "privacy_rules": {
        "public": {"block_providers": []},
        "member": {"block_providers": []},
        "restricted": {
            "block_providers": ["groq", "groq_whisper", "gemini", "cloudflare"]
        },
        "internal": {
            "block_providers": ["groq", "groq_whisper", "gemini", "cloudflare"]
        },
    },
    "cost_tiers": {
        "free_only": [
            "local_faster_whisper",
            "ollama_nomic",
            "ollama_chat",
            "local_classifier_stub",
            "sports_vision_offline",
            "transcription_offline",
        ],
        "low": [
            "local_faster_whisper",
            "ollama_nomic",
            "ollama_chat",
            "local_classifier_stub",
            "groq",
            "groq_whisper",
            "sports_vision_offline",
            "transcription_offline",
        ],
        "any": [
            "local_faster_whisper",
            "ollama_nomic",
            "ollama_chat",
            "local_classifier_stub",
            "groq",
            "groq_whisper",
            "gemini",
            "cloudflare",
            "sports_vision_offline",
            "transcription_offline",
        ],
    },
    "tasks": {
        "caption": {
            "default_order": ["local_faster_whisper", "groq_whisper"],
            "human_review_default": True,
        },
        "embedding": {
            "default_order": ["ollama_nomic"],
            "human_review_default": False,
        },
        "description": {
            "default_order": ["ollama_chat", "groq", "gemini", "cloudflare"],
            "human_review_default": False,
        },
        "moderation": {
            "default_order": ["local_classifier_stub"],
            "human_review_default": False,
        },
        "sports_vision": {
            # G3-B: kill-switch gated; local offline evidence only
            "default_order": ["sports_vision_offline"],
            "human_review_default": True,
        },
        "transcription": {
            # Y2: typed segments via fake/offline provider; real Whisper path is Y4
            "default_order": ["transcription_offline"],
            "human_review_default": True,
        },
    },
    "providers": {
        "local_faster_whisper": {"tier": "local_first", "cost": "free"},
        "groq_whisper": {"tier": "overflow", "cost": "low"},
        "ollama_nomic": {"tier": "local_first", "cost": "free"},
        "ollama_chat": {"tier": "local_first", "cost": "free"},
        "groq": {"tier": "overflow", "cost": "low"},
        "gemini": {"tier": "fallback", "cost": "any"},
        "cloudflare": {"tier": "fallback", "cost": "any"},
        "local_classifier_stub": {"tier": "local_first", "cost": "free"},
        "sports_vision_offline": {"tier": "local_first", "cost": "free"},
        "transcription_offline": {"tier": "local_first", "cost": "free"},
    },
    "lineage": {"backend": "jsonl", "path": "data/lineage.jsonl"},
}
