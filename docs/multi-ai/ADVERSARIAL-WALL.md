# THREEZONE adversarial / regression wall

Give the testing AI **requirements**, not the builder’s explanation.

Prompt pattern:
> [REQUIREMENT]. You are the adversarial QA engineer. Design every reasonable way to bypass this. Do not assume the implementation is correct.

## Rights & playback
- [ ] Watch after rights window closes → no playable media
- [ ] Revoke rights while a playback lease exists → lease dies / cannot play
- [ ] Restore rights → old lease does **not** become valid again
- [ ] Tamper with playback token → reject
- [ ] Member cannot call operator endpoints
- [ ] Operator cannot call owner-only endpoints
- [ ] Cannot self-register as staff

## Lifecycle & live
- [ ] scheduled → live must pass required states (no skip)
- [ ] GREEN blocked with stale/dead camera heartbeat
- [ ] Kill primary feed → backup/failover behaves
- [ ] Kill every AI provider → live, rights, scoring, archive, settlement still work

## Archive / schedule / clips
- [ ] Change event sport/team → archive metadata stays canonically linked
- [ ] Malformed schedule import → reject, no partial corruption
- [ ] Schedule correction → new version, no silent overwrite of history
- [ ] Clip cannot detach/spoof source game/archive ID
- [ ] Member upload report → moderation records who decided what and why

## AI Gateway sovereignty
- [ ] Feature code importing Groq/Gemini/Cloudflare/Ollama SDKs directly → **CI fail**
- [ ] AI caption stores provider/model/source/lineage
- [ ] LLM cannot modify official score, clock, rights, or settlement truth
- [ ] `THREEZONE_AI_ENABLED=false` → app boots; `/api/ai/*` disabled; `/healthz` OK

## Smoke after every PR
- [ ] `GET /healthz` → 200 `status=ok`
- [ ] Member login / ops auth still work
- [ ] WebSocket or same-origin WS path (Render: no extra 8765)
- [ ] Archive playback critical path
