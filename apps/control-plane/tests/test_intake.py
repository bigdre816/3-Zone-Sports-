from __future__ import annotations


def test_three_zone_intake_preserves_payload_and_chain(client, monkeypatch):
    monkeypatch.setenv("MOTEN_INGEST_SHARED_SECRET", "shared-secret")
    body = {
        "schema": "three-zone.moten.event.v1",
        "source_system": "three-zone-mvp",
        "source_service": "three-zone-api",
        "handoff_type": "event",
        "event_id": "evt_mw_basketball",
        "object_version": "v1",
        "rights_version": 7,
        "payload": {"title": "Lincoln vs Central"},
        "event": {"event_id": "evt_mw_basketball", "status": "live"},
        "recent_audit": [{"action": "event.created"}],
    }

    res = client.post("/intake/event", headers={"X-Moten-Shared-Secret": "shared-secret"}, json=body)
    assert res.status_code == 202
    payload = res.json()
    assert payload["accepted"] is True
    assert payload["intake_id"].startswith("EVD-")
    assert payload["source_object_id"] == "evt_mw_basketball"
    assert payload["chain_verified"] is True

    record = client.get(f"/intake/{payload['intake_id']}")
    assert record.status_code == 200
    record_body = record.json()
    assert record_body["handoff_type"] == "event"
    assert record_body["rights_version"] == "7"
    assert record_body["source_system"] == "three-zone-mvp"

    audit = client.get("/audit")
    assert audit.status_code == 200
    audit_body = audit.json()
    assert audit_body["verified"] is True
    assert any(item["event_type"] == "three-zone.intake.event.accepted" for item in audit_body["events"])


def test_health_aliases_and_phase2_fail_closed(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.post("/phase2/example").status_code == 501


def test_intake_secret_is_enforced(client, monkeypatch):
    monkeypatch.setenv("MOTEN_INGEST_SHARED_SECRET", "shared-secret")
    res = client.post("/intake/event", json={"schema": "x", "source_system": "three-zone-mvp"})
    assert res.status_code == 403
