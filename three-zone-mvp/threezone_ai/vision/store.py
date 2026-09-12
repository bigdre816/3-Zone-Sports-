"""Isolated test evidence store. Sandbox cannot write production paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from threezone_ai.vision.types import SportsVisionEvidenceBundle, content_hash

_PRODUCTION_MARKERS = (
    "threezone-prod",
    "/var/lib/threezone",
    "production/evidence",
    "prod/evidence",
    "/var/lib/three-zone",
)


class ProductionStoreForbidden(PermissionError):
    """Sandbox / isolated_test must not write production evidence stores."""


class IdempotencyConflict(ValueError):
    """Same idempotency key observed with a different source asset hash."""


@dataclass
class _Fingerprint:
    source_asset_hash: str
    bundle_id: str
    observation_fingerprint: str


class IsolatedEvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._fingerprints: dict[str, _Fingerprint] = {}
        self._bundles: dict[str, SportsVisionEvidenceBundle] = {}

    def _assert_not_production(self, target: Path | None = None) -> None:
        probe = str((target or self.root).resolve()).replace("\\", "/").lower()
        for marker in _PRODUCTION_MARKERS:
            if marker in probe:
                raise ProductionStoreForbidden(
                    "sandbox task cannot write production evidence stores"
                )

    def put(self, bundle: SportsVisionEvidenceBundle) -> Path:
        self._assert_not_production()
        dest = self.root / f"{bundle.bundle_id}.json"
        self._assert_not_production(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(bundle.canonical_json(), encoding="utf-8")
        self._bundles[bundle.bundle_id] = bundle
        return dest

    def get(self, bundle_id: str) -> SportsVisionEvidenceBundle | None:
        return self._bundles.get(bundle_id)

    def remember(
        self,
        idempotency_key: str,
        source_asset_hash: str,
        bundle: SportsVisionEvidenceBundle,
    ) -> SportsVisionEvidenceBundle:
        existing = self._fingerprints.get(idempotency_key)
        if existing is not None and existing.source_asset_hash != source_asset_hash:
            raise IdempotencyConflict(
                "idempotency key reused with a different source_asset_hash"
            )
        if existing is not None and existing.observation_fingerprint == bundle.observation_fingerprint():
            cached = self._bundles.get(existing.bundle_id)
            if cached is not None:
                return cached
        self._fingerprints[idempotency_key] = _Fingerprint(
            source_asset_hash=source_asset_hash,
            bundle_id=bundle.bundle_id,
            observation_fingerprint=bundle.observation_fingerprint(),
        )
        self.put(bundle)
        return bundle


def idempotency_key(source_asset_id: str, detector_model: str, policy_version: str) -> str:
    return content_hash(
        {
            "source_asset_id": source_asset_id,
            "detector_model": detector_model,
            "policy_version": policy_version,
        }
    )
