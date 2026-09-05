"""API contract + end-to-end reconstruction (the Phase 1 exit evidence)."""

from __future__ import annotations


def test_reserved_routes_fail_closed_501(client):
    assert client.get("/v1/discovery").status_code == 501
    assert client.post("/v1/settlements/2026Q3/close").status_code == 501


def test_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_end_to_end_reconstruction(client):
    hdr = {"X-Moten-Actor": "P-2026-000004"}
    # persons/projects must exist — create the minimal set via seed-less inserts
    # by using the seeded client would be simpler; here we self-provision.
    import moten.app as appmod

    app = client.app
    from moten.models import Person

    with app.state.session_scope() as s:
        s.add_all(
            [
                Person(person_id="P-2026-000001", display_name="Andre", role_default="founder", is_natural_person=True),
                Person(person_id="P-2026-000004", display_name="Research", role_default="research_steward", is_natural_person=True),
                Person(person_id="P-2026-000003", display_name="Counsel", role_default="counsel", is_natural_person=True),
            ]
        )
        s.flush()

    # 1. Research question + version + observation
    rq = client.post(
        "/v1/research/questions",
        json={"owner_person_id": "P-2026-000004", "exact_wording": "Pay $5?", "longitudinal_intent": "controlled"},
    ).json()
    client.post(
        f"/v1/research/questions/{rq['rq_id']}/versions",
        headers=hdr,
        json={"exact_wording": "Pay $7?", "change_reason": "price", "comparability_assessment": "not comparable"},
    )
    obs = client.post(
        "/v1/research/observations",
        headers=hdr,
        json={"rq_id": rq["rq_id"], "rq_revision": 1, "payload": {"yes_rate": 0.4}},
    )
    assert obs.status_code == 201

    # 2. Invention candidate with mechanism
    inv = client.post(
        "/v1/inventions",
        headers={"X-Moten-Actor": "P-2026-000001"},
        json={
            "title": "TZ-02", "problem": "rights misallocation",
            "mechanism": {"inputs": ["demand"], "transformation": "join+rank", "outputs": ["queue"]},
            "alternatives": [{"v": "cloud"}], "technical_effect": "reduce stale-rights decisions",
        },
    ).json()
    inv_id = inv["inv_id"]
    client.post(f"/v1/inventions/{inv_id}/embodiments", headers=hdr, json={"label": "A", "package": {"x": 1}})
    client.post(f"/v1/inventions/{inv_id}/ip-posture", headers=hdr, json={"posture": "patent"})
    client.post(
        f"/v1/inventions/{inv_id}/contributions",
        json={"person_id": "P-2026-000001", "contribution_class": "mechanism", "statement": "conceived", "attested": True},
    )
    ai = client.post(
        f"/v1/inventions/{inv_id}/ai-interactions",
        json={"human_operator_person_id": "P-2026-000001", "tool": "gw", "purpose": "brainstorm", "human_action": "selected approach"},
    ).json()
    assert ai["inventor_status_of_ai"] == "tool_only"

    # 3. Name inventors (two-person) then advance lifecycle
    named = client.post(
        f"/v1/inventions/{inv_id}/inventors",
        headers={"X-Moten-Actor": "P-2026-000003"},
        json={"inventor_person_ids": ["P-2026-000001"], "approver_person_id": "P-2026-000001"},
    )
    assert named.status_code == 200
    for target in ["Hypothesis", "Mechanism", "Invention Candidate", "Prior-Art Review", "Provisional Ready"]:
        r = client.post(f"/v1/inventions/{inv_id}/transition", headers=hdr, json={"target_state": target})
        assert r.status_code == 200, (target, r.json())

    # 4. Filing (two-person) → calendar; check date label
    filing = client.post(
        "/v1/filings",
        headers={"X-Moten-Actor": "P-2026-000001"},
        json={
            "inv_id": inv_id, "uspto_receipt_ref": "USPTO-X", "verified_filing_date": "2026-09-05",
            "named_inventors": ["P-2026-000001"], "supported_versions": [f"{inv_id}#v1.0"],
            "approver_person_id": "P-2026-000003", "owner": "P-2026-000001",
        },
    )
    assert filing.status_code == 201
    assert filing.json()["date_label"] == "uspto_filing"

    cal = client.get("/v1/calendar").json()
    assert len(cal) == 5

    # 5. Hash-linked export reconstructs the whole candidate
    pkg = client.get(f"/v1/exports/invention/{inv_id}").json()
    assert pkg["chain_verified"] is True
    assert len(pkg["hash_manifest"]) > 0
    assert pkg["filings"][0]["verified_filing_date_label"] == "uspto_filing"
    assert pkg["cover"]["legal_effect"] == "provenance_only"

    # 6. Evidence chain endpoint
    assert client.get("/v1/evidence/chain").json()["verified"] is True
