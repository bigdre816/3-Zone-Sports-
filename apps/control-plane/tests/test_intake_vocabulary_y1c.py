"""Y1c — intake transport language must never mean Treasure Path A release."""

from __future__ import annotations


def test_intake_response_is_transport_only_not_released(client, monkeypatch):
    monkeypatch.setenv("MOTEN_INGEST_SHARED_SECRET", "shared-secret")
    body = {
        "schema": "three-zone.moten.event.v1",
        "source_system": "three-zone-mvp",
        "source_service": "three-zone-api",
        "handoff_type": "event",
        "event_id": "evt_y1c_vocab",
        "object_version": "v1",
        "rights_version": 1,
        "event": {"event_id": "evt_y1c_vocab", "status": "live"},
    }
    res = client.post("/intake/event", headers={"X-Moten-Shared-Secret": "shared-secret"}, json=body)
    assert res.status_code == 202
    payload = res.json()

    assert payload["intake_accepted"] is True
    assert payload["status"] == "intake_accepted"
    assert payload["means"] == "transport_receipt_only"
    assert payload["governance"] == "none"
    # Killer rule: transport fields must not claim release / dual review.
    assert payload.get("released") is not True
    assert "review_1" not in payload
    assert "review_2" not in payload
    assert "release_authority" not in payload
    assert payload.get("status") != "released"

    record = client.get(f"/intake/{payload['intake_id']}").json()
    assert record["status"] == "intake_accepted"
    assert record["governance"] == "none"
    assert record["means"] == "intake_accepted_transport_only"
    assert record["status"] != "released"

    audit = client.get("/audit").json()
    types = [item["event_type"] for item in audit["events"]]
    assert any(t == "three-zone.intake.event.intake_accepted" for t in types)
    assert not any(t.endswith(".released") for t in types if "intake.event" in t)


def test_vocabulary_doc_exists_and_bans_bare_accepted_as_release():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    doc = root / "docs" / "multi-ai" / "TREASURE-EVIDENCE-VOCABULARY.md"
    text = doc.read_text(encoding="utf-8")
    assert "Killer rule" in text
    assert "intake_accepted" in text
    assert "Moten" in text and "does **not** create a Treasure institution" in text
    assert "released" in text
    assert "Path A" in text and "Path B" in text
