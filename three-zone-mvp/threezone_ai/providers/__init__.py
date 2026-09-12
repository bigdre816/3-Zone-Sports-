"""Provider adapters — used ONLY by the AI Gateway (not feature modules)."""

from threezone_ai.providers.base import BaseProvider, get_provider_registry

__all__ = ["BaseProvider", "get_provider_registry"]
