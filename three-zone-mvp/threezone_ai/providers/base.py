"""Provider base + registry (gateway-internal)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from threezone_ai.types import AIRequest, ProviderResult, TaskType

if TYPE_CHECKING:
    from threezone_ai.config import Settings


class BaseProvider(ABC):
    name: str = "base"
    supported_tasks: set[TaskType] = set()
    cost_band: str = "any"  # free | low | any
    is_local: bool = False

    def supports(self, task: TaskType) -> bool:
        return task in self.supported_tasks

    @abstractmethod
    def available(self, settings: "Settings") -> bool:
        ...

    @abstractmethod
    def run(self, request: AIRequest, settings: "Settings") -> ProviderResult:
        ...


_REGISTRY: dict[str, BaseProvider] | None = None


def get_provider_registry() -> dict[str, BaseProvider]:
    global _REGISTRY
    if _REGISTRY is None:
        from threezone_ai.providers.cloudflare_chat import CloudflareChatProvider
        from threezone_ai.providers.gemini_chat import GeminiChatProvider
        from threezone_ai.providers.groq_chat import GroqChatProvider
        from threezone_ai.providers.groq_whisper import GroqWhisperProvider
        from threezone_ai.providers.local_moderation import LocalModerationProvider
        from threezone_ai.providers.sports_vision_offline import SportsVisionOfflineProvider
        from threezone_ai.providers.transcription_offline import TranscriptionOfflineProvider
        from threezone_ai.providers.local_whisper import LocalFasterWhisperProvider
        from threezone_ai.providers.ollama_chat import OllamaChatProvider
        from threezone_ai.providers.ollama_embed import OllamaEmbedProvider

        providers = [
            LocalFasterWhisperProvider(),
            GroqWhisperProvider(),
            OllamaEmbedProvider(),
            OllamaChatProvider(),
            GroqChatProvider(),
            GeminiChatProvider(),
            CloudflareChatProvider(),
            LocalModerationProvider(),
            SportsVisionOfflineProvider(),
            TranscriptionOfflineProvider(),
        ]
        _REGISTRY = {p.name: p for p in providers}
    return _REGISTRY


def reset_provider_registry() -> None:
    global _REGISTRY
    _REGISTRY = None
