# Surgical patch: wire AI Gateway into `backend/http_server.py`

Phone-friendly: ~8 lines. Branch `feat/ai-gateway` recommended.

## 1) Import (near other backend imports)

Find the block that imports portal / network / Moten, and add:

```python
from .ai_gateway_routes import AiGatewayHandlers, extra_routes
```

## 2) Extend `_routes()` (end of the returned list)

Change the closing of `def _routes(): return [ ... ]` so the AI routes are appended:

**Before** (last network media route, then `]`):

```python
        ("GET", re.compile(r"^/api/network/media/(?P<asset_id>med_[a-z0-9]+)$"), "h_net_media", "optional"),
    ]
```

**After:**

```python
        ("GET", re.compile(r"^/api/network/media/(?P<asset_id>med_[a-z0-9]+)$"), "h_net_media", "optional"),
        *extra_routes(),
    ]
```

## 3) Mixin on `_Handler`

**Before:**

```python
class _Handler(BaseHTTPRequestHandler):
```

**After:**

```python
class _Handler(AiGatewayHandlers, BaseHTTPRequestHandler):
```

(`AiGatewayHandlers` first so its methods bind cleanly; MRO still reaches `BaseHTTPRequestHandler`.)

## 4) Env / deps (outside this file)

- Add `httpx>=0.27` to requirements (see `CODING-NOW/requirements-add.txt`)
- Set `THREEZONE_AI_ENABLED=false` until staging (see `CODING-NOW/config-ai.env.snippet`)
- Vendor `threezone_ai/` at `three-zone-mvp/threezone_ai/` (already in this pack)

## Smoke

- Boot with AI off → `GET /healthz` 200, `GET /api/ai/status` → `{"enabled": false, ...}`
- Member `POST /api/ai/*` while off → `503 {"error":"ai_disabled","code":"ai_disabled"}`
