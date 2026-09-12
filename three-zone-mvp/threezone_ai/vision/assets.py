"""Synthetic asset resolution — source_asset_id only.

Server (this resolver) is the only authority for hash, privacy class, and
environment. Client-supplied paths, file://, and http(s):// are rejected.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ASSET_ID_RE = re.compile(r"^asset:synthetic:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ALLOWED_ENVIRONMENTS = frozenset({"isolated_test", "sandbox"})
ALLOWED_PRIVACY = frozenset({"P0", "P1", "P2", "P3"})

_DEFAULT_FIXTURES = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "vision"
)


class AssetResolutionError(ValueError):
    """Base class for asset resolution failures."""


class IllicitAssetReference(AssetResolutionError):
    """Arbitrary filesystem path or remote URL used as an asset id."""


@dataclass(frozen=True)
class FrameDescriptor:
    t: float
    text: str
    content_seed: str = ""


@dataclass(frozen=True)
class ResolvedAsset:
    source_asset_id: str
    source_asset_hash: str
    input_privacy_class: str
    environment: str
    duration_s: float
    scenario: str
    visibility_state: str
    frame_descriptors: tuple[FrameDescriptor, ...]
    sample_frame_count: int
    catalog_privacy_class: str


def _sha256_hex(payload: str) -> str:
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reject_illicit_asset_ref(source_asset_id: object) -> str:
    if not isinstance(source_asset_id, str) or not source_asset_id.strip():
        raise IllicitAssetReference("source_asset_id required")
    ref = source_asset_id.strip()
    lowered = ref.lower()
    if lowered.startswith(("file://", "http://", "https://", "ftp://")):
        raise IllicitAssetReference("remote or file URL is not an asset id")
    if "/" in ref or chr(92) in ref:
        raise IllicitAssetReference("filesystem path is not an asset id")
    if ref.startswith(".") or ref.startswith("~"):
        raise IllicitAssetReference("relative/home path is not an asset id")
    if not ASSET_ID_RE.match(ref):
        raise IllicitAssetReference("source_asset_id must be asset:synthetic:<id>")
    return ref


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class SyntheticAssetResolver:
    """Resolves authorized synthetic catalog entries only."""

    def __init__(
        self,
        catalog: dict[str, dict[str, Any]] | None = None,
        fixtures_dir: Path | None = None,
    ) -> None:
        self._catalog: dict[str, dict[str, Any]] = dict(catalog or {})
        directory = Path(fixtures_dir) if fixtures_dir is not None else _DEFAULT_FIXTURES
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                data = _load_json(path)
                aid = data.get("source_asset_id")
                if isinstance(aid, str) and aid not in self._catalog:
                    self._catalog[aid] = data
        if not self._catalog:
            self._catalog.update(_builtin_catalog())

    @classmethod
    def default(cls) -> "SyntheticAssetResolver":
        return cls()

    def list_catalog_summaries(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for asset_id, meta in sorted(self._catalog.items()):
            rows.append(
                {
                    "source_asset_id": asset_id,
                    "scenario": meta.get("scenario"),
                    "input_privacy_class": meta.get("input_privacy_class"),
                    "environment": meta.get("environment"),
                    "visibility_state": meta.get("visibility_state"),
                }
            )
        return rows

    def resolve(
        self,
        source_asset_id: str,
        *,
        client_privacy_class: str | None = None,
    ) -> ResolvedAsset:
        aid = reject_illicit_asset_ref(source_asset_id)
        raw = self._catalog.get(aid)
        if raw is None:
            raise AssetResolutionError(f"unknown synthetic asset: {aid}")
        privacy = str(raw.get("input_privacy_class") or "P0")
        if privacy not in ALLOWED_PRIVACY:
            privacy = "P0"
        env = str(raw.get("environment") or "isolated_test")
        if env not in ALLOWED_ENVIRONMENTS:
            env = "isolated_test"
        duration = float(raw.get("duration_s") or 20.0)
        count = int(raw.get("sample_frame_count") or 10)
        count = max(8, min(12, count))
        frames = []
        for item in raw.get("frame_descriptors") or ():
            if not isinstance(item, dict):
                continue
            frames.append(
                FrameDescriptor(
                    t=float(item.get("t") or 0.0),
                    text=str(item.get("text") or ""),
                    content_seed=str(item.get("content_seed") or ""),
                )
            )
        declared_hash = raw.get("source_asset_hash")
        material = json.dumps(
            {
                "id": aid,
                "scenario": raw.get("scenario"),
                "frames": [f.text for f in frames],
                "duration": duration,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        computed = _sha256_hex(material)
        asset_hash = str(declared_hash) if declared_hash else computed
        # client_privacy_class is intentionally unused (server-derived).
        _ = client_privacy_class
        return ResolvedAsset(
            source_asset_id=aid,
            source_asset_hash=asset_hash,
            input_privacy_class=privacy,
            environment=env,
            duration_s=duration,
            scenario=str(raw.get("scenario") or "unknown"),
            visibility_state=str(raw.get("visibility_state") or "clear"),
            frame_descriptors=tuple(frames),
            sample_frame_count=count,
            catalog_privacy_class=privacy,
        )


def _builtin_catalog() -> dict[str, dict[str, Any]]:
    """Minimal in-memory catalog if fixture files are absent."""

    def frames(texts: list[str]) -> list[dict[str, Any]]:
        n = max(8, min(12, len(texts) if len(texts) >= 8 else 10))
        if len(texts) < n:
            texts = (texts * n)[:n]
        step = 20.0 / (n - 1)
        return [{"t": round(i * step, 6), "text": texts[i]} for i in range(n)]

    return {
        "asset:synthetic:basketball-001": {
            "source_asset_id": "asset:synthetic:basketball-001",
            "input_privacy_class": "P0",
            "environment": "isolated_test",
            "duration_s": 20,
            "scenario": "basketball",
            "visibility_state": "clear",
            "sample_frame_count": 10,
            "frame_descriptors": frames(
                ["hardwood court visible, hoop, basketball, players moving"] * 10
            ),
        }
    }
