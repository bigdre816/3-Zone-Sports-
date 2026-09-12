"""AI Gateway — the only product-facing AI entrypoint (sovereignty switchboard)."""

from __future__ import annotations

from typing import Any

from threezone_ai.config import (
    config_enabled,
    get_settings,
    load_gateway_config,
    process_ai_enabled,
)
from threezone_ai.types import (
    AIRequest,
    AIResponse,
    CostCeiling,
    PrivacyClass,
    TaskType,
)

# Providers considered paid / cloud for cost ceilings
_COST_RANK = {"free": 0, "low": 1, "any": 2}
_CEILING_RANK = {
    CostCeiling.FREE_ONLY: 0,
    CostCeiling.LOW: 1,
    CostCeiling.ANY: 2,
}


def _task_cfg(cfg: dict[str, Any], task: TaskType) -> dict[str, Any]:
    tasks = cfg.get("tasks") or {}
    return dict(tasks.get(task.value) or {})


def _blocked_for_privacy(cfg: dict[str, Any], privacy: PrivacyClass) -> set[str]:
    rules = (cfg.get("privacy_rules") or {}).get(privacy.value) or {}
    blocked = rules.get("block_providers") or []
    return {str(x) for x in blocked}


def _allowed_by_cost(cfg: dict[str, Any], ceiling: CostCeiling) -> set[str] | None:
    tiers = cfg.get("cost_tiers") or {}
    key = ceiling.value
    names = tiers.get(key)
    if names is None:
        return None
    return {str(x) for x in names}


def _resolve_order(request: AIRequest, cfg: dict[str, Any], task: TaskType) -> list[str]:
    if request.fallback_order:
        return list(request.fallback_order)
    if request.allowed_providers:
        # Respect allowlist order as given
        tcfg = _task_cfg(cfg, task)
        default = list(tcfg.get("default_order") or [])
        allow = set(request.allowed_providers)
        ordered = [p for p in default if p in allow]
        for p in request.allowed_providers:
            if p not in ordered:
                ordered.append(p)
        return ordered
    tcfg = _task_cfg(cfg, task)
    return list(tcfg.get("default_order") or [])


def _human_review_required(request: AIRequest, cfg: dict[str, Any], task: TaskType) -> bool:
    if request.require_human_review is not None:
        return bool(request.require_human_review)
    tcfg = _task_cfg(cfg, task)
    return bool(tcfg.get("human_review_default", False))


def _provider_cost_ok(provider: object, ceiling: CostCeiling, cfg: dict[str, Any]) -> bool:
    allowed = _allowed_by_cost(cfg, ceiling)
    if allowed is not None:
        return provider.name in allowed
    # Fallback to band rank if cost_tiers missing
    band = _COST_RANK.get(provider.cost_band, 2)
    return band <= _CEILING_RANK.get(ceiling, 2)


def select_providers(request: AIRequest, cfg: dict[str, Any] | None = None) -> list:
    """Resolve ordered provider list after privacy / cost / allowlist filters.

    Imports the provider registry lazily — call only after enablement gates pass.
    """
    from threezone_ai.providers.base import get_provider_registry

    cfg = cfg if cfg is not None else load_gateway_config()
    task = request.normalized_task()
    privacy = request.normalized_privacy()
    ceiling = request.normalized_cost()
    blocked = _blocked_for_privacy(cfg, privacy)
    order = _resolve_order(request, cfg, task)
    registry = get_provider_registry()
    selected: list = []
    for name in order:
        if name in blocked:
            continue
        if request.allowed_providers is not None and name not in request.allowed_providers:
            continue
        prov = registry.get(name)
        if prov is None:
            continue
        if not prov.supports(task):
            continue
        if not _provider_cost_ok(prov, ceiling, cfg):
            continue
        selected.append(prov)
    return selected


def run(
    request: AIRequest,
    *,
    config_overlay: dict[str, Any] | None = None,
    record_lineage: bool = True,
) -> AIResponse:
    """
    Execute an AI task via the sovereignty switchboard.

    Never raises for missing providers — returns degraded AIResponse(provider='no_ai').

    Fail-closed: THREEZONE_AI_ENABLED process kill switch must be explicitly on.
    Settings/YAML may further restrict but cannot bypass the process gate.
    Provider registry/selection runs only after both gates pass.
    """
    task = request.normalized_task()
    # Minimal review flag without loading settings/config when process gate is off.
    human_review = (
        bool(request.require_human_review)
        if request.require_human_review is not None
        else False
    )

    # 1) Process-level kill switch — before settings, credentials, or providers.
    if not process_ai_enabled():
        return AIResponse.no_ai(
            task_type=task.value,
            error="AI gateway disabled (THREEZONE_AI_ENABLED process gate)",
            fallback_path=["no_ai"],
            human_review_required=human_review,
            trace_id=request.trace_id,
            metadata=dict(request.metadata or {}),
        )

    settings = get_settings()
    cfg = load_gateway_config(overlay=config_overlay)
    human_review = _human_review_required(request, cfg, task)
    path_log: list[str] = []

    # 2) Config/Settings layer — further restriction only (cannot enable alone).
    if not settings.ai_enabled or not config_enabled(cfg):
        return AIResponse.no_ai(
            task_type=task.value,
            error="AI gateway disabled (Settings/config.enabled)",
            fallback_path=["no_ai"],
            human_review_required=human_review,
            trace_id=request.trace_id,
            metadata=dict(request.metadata or {}),
        )

    # Lazy: lineage import only on enabled path (providers via select_providers).
    from threezone_ai.lineage import record_generation

    providers = select_providers(request, cfg)
    if not providers:
        return AIResponse.no_ai(
            task_type=task.value,
            error="no providers eligible after privacy/cost/allowlist filters",
            fallback_path=["no_ai"],
            human_review_required=human_review,
            trace_id=request.trace_id,
            metadata=dict(request.metadata or {}),
        )

    errors: list[str] = []
    for prov in providers:
        if not prov.available(settings):
            path_log.append(f"{prov.name}:skipped")
            errors.append(f"{prov.name}: not available")
            continue
        path_log.append(f"{prov.name}:attempt")
        try:
            result = prov.run(request, settings)
        except Exception as exc:
            path_log.append(f"{prov.name}:error")
            errors.append(f"{prov.name}: {type(exc).__name__}: {exc}")
            continue

        path_log.append(f"{prov.name}:ok")
        lineage_id = None
        output_text = result.text
        # Captions / descriptions: always lineage when generative
        should_lineage = record_lineage and task in {
            TaskType.CAPTION,
            TaskType.DESCRIPTION,
        }
        # Embeddings: lighter provenance optional via metadata flag
        if record_lineage and task == TaskType.EMBEDDING and (
            request.metadata or {}
        ).get("record_provenance"):
            should_lineage = True
            output_text = f"embedding_dim={len(result.embedding or [])}"

        if should_lineage:
            try:
                rec = record_generation(
                    source_asset_id=request.source_asset_id
                    or request.asset_ref
                    or (request.metadata or {}).get("source_asset_id"),
                    provider=prov.name,
                    model=result.model,
                    version=result.version,
                    generated_output=output_text,
                    task_type=task.value,
                    trace_id=request.trace_id,
                    metadata={
                        "privacy_class": request.normalized_privacy().value,
                        **dict(request.metadata or {}),
                    },
                )
                lineage_id = rec.id
                # Stash output_id for callers
                meta = dict(result.metadata or {})
                meta["output_id"] = rec.output_id
            except Exception as exc:
                meta = dict(result.metadata or {})
                meta["lineage_error"] = str(exc)
        else:
            meta = dict(result.metadata or {})

        title_suggestion = None
        if task == TaskType.CAPTION and result.text:
            title_suggestion = _maybe_title(
                result.text, request, cfg, config_overlay=config_overlay
            )

        return AIResponse(
            ok=True,
            task_type=task.value,
            provider=prov.name,
            text=result.text,
            embedding=result.embedding,
            labels=result.labels,
            segments=result.segments,
            model=result.model,
            version=result.version,
            confidence=result.confidence,
            human_review_required=human_review,
            degraded=False,
            fallback_path=path_log,
            lineage_id=lineage_id,
            title_suggestion=title_suggestion,
            metadata=meta,
            trace_id=request.trace_id,
        )

    return AIResponse.no_ai(
        task_type=task.value,
        error="; ".join(errors) if errors else "all providers failed",
        fallback_path=path_log + ["no_ai"],
        human_review_required=human_review,
        trace_id=request.trace_id,
        metadata=dict(request.metadata or {}),
    )


def _maybe_title(
    transcript: str,
    request: AIRequest,
    cfg: dict[str, Any],
    config_overlay: dict[str, Any] | None = None,
) -> str | None:
    """Optional title via same gateway (description task) — never imports cloud SDKs."""
    if (request.metadata or {}).get("skip_title"):
        return None
    try:
        title_req = AIRequest(
            task_type=TaskType.DESCRIPTION,
            input_text=(
                "Suggest a short catchy sports highlight title (max 8 words). "
                "Reply with the title only.\n\n"
                f"{transcript[:2000]}"
            ),
            privacy_class=request.privacy_class,
            cost_ceiling=request.cost_ceiling,
            allowed_providers=request.allowed_providers,
            timeout_ms=min(request.timeout_ms, 30_000),
            metadata={"system": "You write concise sports highlight titles.", "skip_title": True},
            trace_id=request.trace_id,
            require_human_review=False,
        )
        resp = run(title_req, config_overlay=config_overlay, record_lineage=False)
        if resp.ok and resp.text:
            return resp.text.strip().splitlines()[0].strip().strip("\"'")[:120]
    except Exception:
        pass
    words = transcript.split()
    snippet = " ".join(words[:8])
    if len(words) > 8:
        snippet += "…"
    return snippet[:80] or None
