"""V1-bakeoff / G3-D — ObjectDetectionProvider metrics harness + license gate.

CI uses stub detectors only. No weight download. No production Layer-1 switch.
Popularity is not GREEN; license gate is required.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

from threezone_ai.vision.assets import ResolvedAsset, SyntheticAssetResolver
from threezone_ai.vision.ontology import ONTOLOGY_CLASSES, map_label
from threezone_ai.vision.providers import (
    DetectionLayerResult,
    ObjectDetectionProvider,
)
from threezone_ai.vision.sampler import EvidenceSampler, SampledFrame

BAKEOFF_SCHEMA_VERSION = "threezone.vision.bakeoff.v1"

LicenseStatus = Literal["permissive", "restricted", "unknown", "unlicensed"]
Verdict = Literal["GREEN", "NOT_GREEN"]

LICENSE_BLOCKED = frozenset({"unlicensed", "unknown"})

# Proxies: ball / court / net / player (ontology classes).
_PROXY_BALL = frozenset({"basketball"})
_PROXY_COURT = frozenset({"court", "field", "football_field", "wrestling_mat"})
_PROXY_NET = frozenset({"volleyball_net", "hoop", "soccer_goal", "goalpost"})
_PROXY_PLAYER = frozenset({"uniformed_participant", "person", "referee"})


@dataclass(frozen=True)
class BakeoffScenario:
    """Labeled synthetic scenario for detector comparison."""

    scenario_id: str
    source_asset_id: str
    expected_classes: frozenset[str]
    expect_obstruction: bool = False
    # Classes that are false positives if emitted (e.g. sports gear on non-sports).
    forbidden_classes: frozenset[str] = frozenset()


@dataclass
class BakeoffCandidate:
    """Detector candidate with license / offline metadata for the gate."""

    candidate_id: str
    provider: ObjectDetectionProvider
    license_status: LicenseStatus
    offline_capable: bool
    latency_ms_estimate: float = 0.0
    memory_estimate_mb: float = 0.0
    notes: str = ""


@dataclass
class CandidateMetrics:
    candidate_id: str
    class_hits: int
    class_expected: int
    recall: float
    false_positives: int
    obstruction_behavior_flag: bool
    latency_ms: float
    memory_estimate_mb: float
    license_status: LicenseStatus
    offline_capable: bool
    verdict: Verdict
    gate_reason: str | None
    per_scenario: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BakeoffReport:
    schema_version: str
    offline_required: bool
    scenarios: list[str]
    candidates: list[CandidateMetrics]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "offline_required": self.offline_required,
            "scenarios": list(self.scenarios),
            "candidates": [c.to_dict() for c in self.candidates],
            "notes": list(self.notes),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def default_bakeoff_corpus() -> list[BakeoffScenario]:
    """V0 synthetic scenarios with expected ontology labels (proxies)."""

    sports_fp = frozenset(
        {
            "court",
            "field",
            "hoop",
            "basketball",
            "football_field",
            "goalpost",
            "soccer_goal",
            "volleyball_net",
            "wrestling_mat",
            "scoreboard",
            "uniformed_participant",
        }
    )
    return [
        BakeoffScenario(
            scenario_id="basketball",
            source_asset_id="asset:synthetic:basketball-001",
            expected_classes=frozenset(
                {"court", "hoop", "basketball", "uniformed_participant"}
            ),
        ),
        BakeoffScenario(
            scenario_id="soccer",
            source_asset_id="asset:synthetic:soccer-001",
            expected_classes=frozenset(
                {"field", "soccer_goal", "uniformed_participant"}
            ),
        ),
        BakeoffScenario(
            scenario_id="football",
            source_asset_id="asset:synthetic:football-001",
            expected_classes=frozenset(
                {"football_field", "goalpost", "uniformed_participant"}
            ),
        ),
        BakeoffScenario(
            scenario_id="empty_gym",
            source_asset_id="asset:synthetic:empty-gym-001",
            expected_classes=frozenset({"court"}),
            forbidden_classes=frozenset({"uniformed_participant", "basketball"}),
        ),
        BakeoffScenario(
            scenario_id="non_sports",
            source_asset_id="asset:synthetic:non-sports-001",
            expected_classes=frozenset(),
            forbidden_classes=sports_fp,
        ),
        BakeoffScenario(
            scenario_id="obstructed",
            source_asset_id="asset:synthetic:obstructed-001",
            expected_classes=frozenset(),
            expect_obstruction=True,
        ),
        BakeoffScenario(
            scenario_id="tv_in_frame",
            source_asset_id="asset:synthetic:tv-in-frame-001",
            expected_classes=frozenset({"tv_monitor_boundary"}),
        ),
        BakeoffScenario(
            scenario_id="unreadable",
            source_asset_id="asset:synthetic:unreadable-001",
            expected_classes=frozenset(),
        ),
    ]


# ---------------------------------------------------------------------------
# Stub ObjectDetectionProvider adapters (CI only — no weights)
# ---------------------------------------------------------------------------


class _BakeoffStubBase:
    """Shared stub machinery. Modes change behavior profiles only."""

    name = "bakeoff_stub"
    model = "bakeoff-stub-v0"
    version = "unknown"
    is_cloud = False
    supported_classes: frozenset[str] = frozenset(ONTOLOGY_CLASSES)
    profile: str = "base"

    def __init__(self, *, name: str | None = None, model: str | None = None) -> None:
        if name:
            self.name = name
        if model:
            self.model = model

    def detect(
        self, frames: Sequence[SampledFrame], asset: ResolvedAsset
    ) -> DetectionLayerResult:
        frame_id = frames[0].frame_id if frames else "frm_0000"
        mid = frames[len(frames) // 2].frame_id if frames else frame_id
        detections = self._profile_detections(asset.scenario, frame_id, mid)
        return DetectionLayerResult(
            provider=self.name,
            model=self.model,
            version=self.version or "unknown",
            detections=detections,
            raw_payload={"profile": self.profile, "detections": detections},
        )

    def _profile_detections(
        self, scenario: str, frame_id: str, mid: str
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


def _box(x: float, y: float, w: float, h: float) -> dict[str, float]:
    return {"x": x, "y": y, "w": w, "h": h}


def _det(frame_id: str, raw: str, bbox: dict[str, float], score: float) -> dict[str, Any]:
    return {
        "raw_label": raw,
        "bbox": dict(bbox),
        "score": score,
        "frame_id": frame_id,
    }


class HighRecallStubDetector(_BakeoffStubBase):
    """High-recall profile: hits expected classes + extra false positives."""

    name = "stub_high_recall"
    model = "stub-high-recall-v0"
    profile = "high_recall"

    def _profile_detections(
        self, scenario: str, frame_id: str, mid: str
    ) -> list[dict[str, Any]]:
        from threezone_ai.vision.providers import _scenario_detections

        dets = list(_scenario_detections(scenario, frame_id, mid))
        # Extra FPs: sports gear on non-sports / empty / obstructed.
        if scenario in {"non_sports", "empty_gym", "obstructed", "unreadable"}:
            dets.append(_det(frame_id, "basketball", _box(0.4, 0.4, 0.1, 0.1), 0.55))
            dets.append(_det(mid, "hoop", _box(0.5, 0.1, 0.1, 0.1), 0.52))
        if scenario == "basketball":
            dets.append(_det(mid, "soccer_goal", _box(0.1, 0.3, 0.2, 0.2), 0.48))
        return dets


class PreciseStubDetector(_BakeoffStubBase):
    """Precise profile: fewer boxes, fewer FPs, may miss some expected classes."""

    name = "stub_precise"
    model = "stub-precise-v0"
    profile = "precise"

    def _profile_detections(
        self, scenario: str, frame_id: str, mid: str
    ) -> list[dict[str, Any]]:
        if scenario == "basketball":
            return [
                _det(frame_id, "court", _box(0.05, 0.10, 0.90, 0.80), 0.96),
                _det(frame_id, "hoop", _box(0.42, 0.08, 0.16, 0.22), 0.94),
                # Deliberately omit basketball ball + player → lower recall.
            ]
        if scenario == "soccer":
            return [
                _det(frame_id, "field", _box(0.04, 0.12, 0.92, 0.78), 0.95),
                _det(frame_id, "soccer_goal", _box(0.10, 0.30, 0.18, 0.28), 0.93),
            ]
        if scenario == "football":
            return [
                _det(frame_id, "football_field", _box(0.04, 0.12, 0.92, 0.78), 0.95),
                _det(frame_id, "goalpost", _box(0.10, 0.30, 0.18, 0.28), 0.92),
            ]
        if scenario == "empty_gym":
            return [_det(frame_id, "court", _box(0.05, 0.10, 0.90, 0.80), 0.97)]
        if scenario == "tv_in_frame":
            return [
                _det(frame_id, "tv_monitor_boundary", _box(0.20, 0.15, 0.60, 0.50), 0.98)
            ]
        if scenario == "obstructed":
            # Honest low-confidence person only — no invented sports gear.
            return [_det(frame_id, "person", _box(0.30, 0.40, 0.10, 0.35), 0.35)]
        if scenario in {"non_sports", "unreadable"}:
            return []
        return []


class YoloLikeStubDetector(HighRecallStubDetector):
    """Named stub only — not a brand lock, not GREEN by name."""

    name = "stub_yolo_like"
    model = "stub-yolo-like-v0"
    profile = "yolo_like_high_recall"


class RfDetrLikeStubDetector(PreciseStubDetector):
    """Named stub only — not a brand lock, not GREEN by name."""

    name = "stub_rfdetr_like"
    model = "stub-rfdetr-like-v0"
    profile = "rfdetr_like_precise"


def default_ci_candidates() -> list[BakeoffCandidate]:
    """≥2 stub candidates with distinct profiles. No weight download."""

    return [
        BakeoffCandidate(
            candidate_id="stub_high_recall",
            provider=HighRecallStubDetector(),
            license_status="permissive",
            offline_capable=True,
            latency_ms_estimate=12.0,
            memory_estimate_mb=64.0,
            notes="CI high-recall stub",
        ),
        BakeoffCandidate(
            candidate_id="stub_precise",
            provider=PreciseStubDetector(),
            license_status="permissive",
            offline_capable=True,
            latency_ms_estimate=8.0,
            memory_estimate_mb=48.0,
            notes="CI precise stub",
        ),
        BakeoffCandidate(
            candidate_id="stub_yolo_like",
            provider=YoloLikeStubDetector(),
            license_status="unknown",
            offline_capable=True,
            latency_ms_estimate=15.0,
            memory_estimate_mb=256.0,
            notes="Named stub only; license unknown → cannot GREEN",
        ),
        BakeoffCandidate(
            candidate_id="stub_rfdetr_like",
            provider=RfDetrLikeStubDetector(),
            license_status="unlicensed",
            offline_capable=True,
            latency_ms_estimate=18.0,
            memory_estimate_mb=320.0,
            notes="Named stub only; unlicensed → cannot GREEN",
        ),
    ]


# ---------------------------------------------------------------------------
# License gate + metrics
# ---------------------------------------------------------------------------


def apply_license_gate(
    *,
    license_status: LicenseStatus,
    offline_capable: bool,
    offline_required: bool,
) -> tuple[Verdict, str | None]:
    """Candidate cannot be GREEN if unlicensed/unknown, or offline missing when required."""

    reasons: list[str] = []
    if license_status in LICENSE_BLOCKED:
        reasons.append(f"license_status={license_status}")
    if offline_required and not offline_capable:
        reasons.append("offline_capable=false while offline_required")
    if reasons:
        return "NOT_GREEN", "license_gate: " + "; ".join(reasons)
    return "GREEN", None


def _mapped_classes(detections: Sequence[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for det in detections:
        raw = str(det.get("raw_label") or "")
        mapping = map_label(raw, provider_supported=ONTOLOGY_CLASSES)
        if mapping.ontology_class:
            found.add(mapping.ontology_class)
    return found


def _score_scenario(
    scenario: BakeoffScenario,
    detections: Sequence[dict[str, Any]],
    asset: ResolvedAsset | None,
) -> dict[str, Any]:
    found = _mapped_classes(detections)
    expected = set(scenario.expected_classes)
    hits = expected & found
    fps = found & set(scenario.forbidden_classes)
    # Also count unexpected sports anchors when expected is empty and forbidden empty
    # (obstructed/unreadable): any sports proxy beyond person is FP-ish for obstruction.
    if scenario.expect_obstruction:
        sportsish = found & (_PROXY_BALL | _PROXY_COURT | _PROXY_NET - {"person"})
        # person alone is OK; inventing court/ball/net is bad obstruction behavior
        obstruction_ok = len(sportsish) == 0
    else:
        obstruction_ok = True

    return {
        "scenario_id": scenario.scenario_id,
        "expected": sorted(expected),
        "found": sorted(found),
        "hits": sorted(hits),
        "hit_count": len(hits),
        "expected_count": len(expected),
        "false_positives": sorted(fps),
        "false_positive_count": len(fps),
        "obstruction_ok": obstruction_ok,
        "visibility_state": getattr(asset, "visibility_state", None),
    }


def evaluate_candidate(
    candidate: BakeoffCandidate,
    corpus: Sequence[BakeoffScenario],
    *,
    offline_required: bool = True,
    resolver: SyntheticAssetResolver | None = None,
    sampler: EvidenceSampler | None = None,
) -> CandidateMetrics:
    """Run detector on labeled corpus; compute metrics; apply license gate."""

    resolver = resolver or SyntheticAssetResolver.default()
    sampler = sampler or EvidenceSampler()

    total_hits = 0
    total_expected = 0
    total_fps = 0
    obstruction_ok_all = True
    per_scenario: list[dict[str, Any]] = []
    latency_samples: list[float] = []

    for scenario in corpus:
        asset = resolver.resolve(scenario.source_asset_id)
        frames = sampler.sample(asset)
        t0 = time.perf_counter()
        result = candidate.provider.detect(frames, asset)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latency_samples.append(elapsed_ms)
        dets = list(result.detections or [])
        scored = _score_scenario(scenario, dets, asset)
        scored["latency_ms"] = round(elapsed_ms, 3)
        scored["timed_out"] = bool(result.timed_out)
        scored["error"] = result.error
        per_scenario.append(scored)
        total_hits += int(scored["hit_count"])
        total_expected += int(scored["expected_count"])
        total_fps += int(scored["false_positive_count"])
        if scenario.expect_obstruction and not scored["obstruction_ok"]:
            obstruction_ok_all = False

    recall = (total_hits / total_expected) if total_expected else 1.0
    measured_latency = (
        candidate.latency_ms_estimate
        if candidate.latency_ms_estimate > 0
        else (sum(latency_samples) / len(latency_samples) if latency_samples else 0.0)
    )

    # Metrics first; license gate can still veto GREEN even with strong metrics.
    metrics_verdict: Verdict = "GREEN"
    metrics_reason: str | None = None
    # Soft quality flags do not themselves GREEN; gate is authoritative for license.
    gate_verdict, gate_reason = apply_license_gate(
        license_status=candidate.license_status,
        offline_capable=candidate.offline_capable,
        offline_required=offline_required,
    )
    if gate_verdict == "NOT_GREEN":
        verdict: Verdict = "NOT_GREEN"
        reason = gate_reason
    else:
        verdict = metrics_verdict
        reason = metrics_reason

    return CandidateMetrics(
        candidate_id=candidate.candidate_id,
        class_hits=total_hits,
        class_expected=total_expected,
        recall=round(recall, 4),
        false_positives=total_fps,
        obstruction_behavior_flag=obstruction_ok_all,
        latency_ms=round(float(measured_latency), 3),
        memory_estimate_mb=float(candidate.memory_estimate_mb),
        license_status=candidate.license_status,
        offline_capable=candidate.offline_capable,
        verdict=verdict,
        gate_reason=reason,
        per_scenario=per_scenario,
    )


def run_bakeoff(
    candidates: Sequence[BakeoffCandidate] | None = None,
    corpus: Sequence[BakeoffScenario] | None = None,
    *,
    offline_required: bool = True,
    resolver: SyntheticAssetResolver | None = None,
) -> BakeoffReport:
    """Execute bakeoff; return JSON-serializable report. Never switches prod detector."""

    cands = list(candidates) if candidates is not None else default_ci_candidates()
    scenarios = list(corpus) if corpus is not None else default_bakeoff_corpus()
    metrics = [
        evaluate_candidate(
            c,
            scenarios,
            offline_required=offline_required,
            resolver=resolver,
        )
        for c in cands
    ]
    return BakeoffReport(
        schema_version=BAKEOFF_SCHEMA_VERSION,
        offline_required=offline_required,
        scenarios=[s.scenario_id for s in scenarios],
        candidates=metrics,
        notes=[
            "Popularity is not GREEN.",
            "License gate required: unlicensed|unknown cannot GREEN.",
            "offline_capable=false cannot GREEN when offline_required.",
            "Bakeoff does not auto-switch production Layer-1 detector.",
            "Named stubs (yolo-like / rfdetr-like) are not brand locks.",
        ],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="THREEZONE vision detector bakeoff (stubs only; no weight download)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON report",
    )
    parser.add_argument(
        "--offline-required",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require offline_capable for GREEN (default: true)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_bakeoff(offline_required=bool(args.offline_required))
    if args.json:
        print(report.to_json())
    else:
        print(f"schema={report.schema_version} offline_required={report.offline_required}")
        for c in report.candidates:
            gate = c.gate_reason or "ok"
            print(
                f"  {c.candidate_id}: verdict={c.verdict} recall={c.recall} "
                f"fp={c.false_positives} license={c.license_status} "
                f"offline={c.offline_capable} latency_ms={c.latency_ms} "
                f"mem_mb={c.memory_estimate_mb} gate={gate}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
