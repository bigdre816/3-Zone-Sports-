"""Evidence sampler — 8–12 stills across a ~20s window.

This is NOT continuous FPS detection. Capture sampling ≠ inference sampling.
The detector runs only on the selected frames.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from threezone_ai.vision.assets import ResolvedAsset

WINDOW_SECONDS = 20.0
MIN_FRAMES = 8
MAX_FRAMES = 12
DEFAULT_FRAMES = 10


@dataclass(frozen=True)
class SampledFrame:
    frame_id: str
    timestamp_s: float
    content_hash: str
    descriptor: str


class EvidenceSampler:
    """Uniform temporal sampling over the observation window.

    Algorithm (documented, deterministic):
    - n = clamp(asset.sample_frame_count, 8, 12), default 10
    - window = min(asset.duration_s, 20.0) seconds (inclusive endpoints)
    - timestamps t_i = i * window / (n - 1) for i in 0..n-1
    - If the catalog supplies descriptors, pick the nearest descriptor by t
    - frame_id = frm_{i:04d}
    - content_hash = SHA-256 of asset_id|asset_hash|frame_id|t|descriptor

    Forbidden: a continuous 5–10 FPS loop over 20s (~100 inferences).
    """

    def sample(self, asset: ResolvedAsset) -> tuple[SampledFrame, ...]:
        n = int(asset.sample_frame_count or DEFAULT_FRAMES)
        n = max(MIN_FRAMES, min(MAX_FRAMES, n))
        window = float(asset.duration_s or WINDOW_SECONDS)
        if window <= 0:
            window = WINDOW_SECONDS
        window = min(window, WINDOW_SECONDS)
        if n == 1:
            stamps = [0.0]
        else:
            stamps = [i * window / (n - 1) for i in range(n)]
        catalog = list(asset.frame_descriptors)
        frames: list[SampledFrame] = []
        for i, ts in enumerate(stamps):
            desc = _nearest_descriptor(catalog, ts) if catalog else asset.scenario
            frame_id = f"frm_{i:04d}"
            material = "|".join(
                (
                    asset.source_asset_id,
                    asset.source_asset_hash,
                    frame_id,
                    f"{ts:.6f}",
                    desc,
                )
            )
            digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            frames.append(
                SampledFrame(
                    frame_id=frame_id,
                    timestamp_s=ts,
                    content_hash=f"sha256:{digest}",
                    descriptor=desc,
                )
            )
        return tuple(frames)


def _nearest_descriptor(catalog, ts: float) -> str:
    best = catalog[0]
    best_d = abs(float(best.t) - ts)
    for item in catalog[1:]:
        d = abs(float(item.t) - ts)
        if d < best_d:
            best = item
            best_d = d
    return str(best.text or "")
