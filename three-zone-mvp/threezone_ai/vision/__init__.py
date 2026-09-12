"""THREEZONE sports-vision evidence library (V0 / P1-V0).

Sports-vision evidence library.

- V0b operator sports-check may call with ``allow_offline_synthetic``.
- G3-B registers gateway task ``sports_vision`` (kill-switch gated; local offline provider).
- G3-C resolves ``asset:archive:<id>`` via authorized DB lookup only.
No publication authority; no arbitrary filesystem/URL opens.

Models emit observations. SportsContextPolicy emits the only decision.
Publication / rights / settlement are out of scope.
"""

from threezone_ai.vision.assets import (
    ArchiveAssetResolver,
    IllicitAssetReference,
    ResolvedAsset,
    SyntheticAssetResolver,
    UnknownArchiveAsset,
    resolve_authorized_asset,
)
from threezone_ai.vision.ontology import (
    ONTOLOGY_CLASSES,
    ONTOLOGY_VERSION,
    MappingStatus,
    OntologyMapping,
    map_label,
)
from threezone_ai.vision.pipeline import (
    VisionPipelineDisabled,
    run_evidence_pipeline,
)
from threezone_ai.vision.policy import evaluate_sports_context
from threezone_ai.vision.providers import (
    EscalationProvider,
    FakeEscalationProvider,
    FakeObjectDetectionProvider,
    FakeSceneReasoningProvider,
    ObjectDetectionProvider,
    SceneReasoningProvider,
)
from threezone_ai.vision.sampler import EvidenceSampler, SampledFrame
from threezone_ai.vision.types import (
    EVIDENCE_SCHEMA_VERSION,
    POLICY_VERSION,
    SportsContextPolicyResult,
    SportsVisionEvidenceBundle,
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "ONTOLOGY_CLASSES",
    "ONTOLOGY_VERSION",
    "POLICY_VERSION",
    "EscalationProvider",
    "EvidenceSampler",
    "FakeEscalationProvider",
    "FakeObjectDetectionProvider",
    "FakeSceneReasoningProvider",
    "ArchiveAssetResolver",
    "IllicitAssetReference",
    "MappingStatus",
    "ObjectDetectionProvider",
    "OntologyMapping",
    "ResolvedAsset",
    "SampledFrame",
    "SceneReasoningProvider",
    "SportsContextPolicyResult",
    "SportsVisionEvidenceBundle",
    "SyntheticAssetResolver",
    "UnknownArchiveAsset",
    "resolve_authorized_asset",
    "VisionPipelineDisabled",
    "evaluate_sports_context",
    "map_label",
    "run_evidence_pipeline",
]
