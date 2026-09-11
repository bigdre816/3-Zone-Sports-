"""THREEZONE AI — product code talks to the Gateway only."""

from threezone_ai.gateway import run, select_providers
from threezone_ai.lineage import (
    get_lineage,
    record_approval,
    record_generation,
    record_human_edit,
)
from threezone_ai.studio_ffmpeg import StudioError, cut_clip, ffmpeg_available
from threezone_ai.types import (
    AIRequest,
    AIResponse,
    CostCeiling,
    PrivacyClass,
    TaskType,
)

__all__ = [
    "AIRequest",
    "AIResponse",
    "CostCeiling",
    "PrivacyClass",
    "StudioError",
    "TaskType",
    "cut_clip",
    "ffmpeg_available",
    "get_lineage",
    "record_approval",
    "record_generation",
    "record_human_edit",
    "run",
    "select_providers",
]

__version__ = "0.2.0"
