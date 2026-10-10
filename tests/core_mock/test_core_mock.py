import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
POLICIES = json.loads((ROOT / "data" / "synthetic" / "policies.json").read_text())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CORE_MOCK_POLICIES", str(ROOT / "data" / "synthetic" / "policies.json"))
    monkeypatch.setenv("CORE_MOCK_PRODUCTS", str(ROOT / "data" / "policies" / "products.yaml"))
    from claimpilot_core_mock import main

    main.policies.cache_clear()
    main.products.cache_clear()
    main.STORE.clear()
    return TestClient(main.app)


def policy(kind="single"):
    return next(p for p in POLICIES if p["kind"] == kind and not p["prior_paid"])


def submission(p=None, **overrides):
    p = p or policy()
    body = {
        "policy_number": p["policy_number"],
        "claim_type_code": "MED",
        "insured": {
            "name": p["insured"][0]["name"],
            "birth_number": p["insured"][0]["birth_number"],
        },
        "event_date": p["start"],
        "event_country": "AT",
        "iban": "SK3112000000198742637541",
        "currency": "EUR",
        "total_payout": "229.50",
        "items": [
            {
                "ref": "I1",
                "coverage_code": "MED",
                "claimed_eur": "279.50",
                "payout_eur": "229.50",
                "decision": "PAY",
                "clause_refs": ["A4.1", "A4.3"],
            },
        ],
        "handler_id": "handler.demo",
    }
    body.update(overrides)
    return body


def post(client, body, key="k-1"):
    return client.post("/claims", json=body, headers={"Idempotency-Key": key})


def errors(resp):
    return {".".join(str(x) for x in e["loc"][1:]): e["type"] for e in resp.json()["detail"]}


def test_valid_claim_is_registered(client):
    r = post(client, submission())
    assert r.status_code == 201
    assert r.json()["status"] == "REGISTERED"
    assert r.json()["core_claim_id"].startswith("CCS-")


def test_same_idempotency_key_returns_the_same_claim(client):
    first = post(client, submission(), "k-same").json()
    again = post(client, submission(), "k-same")
    assert again.status_code == 201
    assert again.json() == first


def test_same_key_with_a_different_body_is_a_conflict(client):
    post(client, submission(), "k-x")
    r = post(client, submission(total_payout="1.00", items=[]), "k-x")
    assert r.status_code == 409


def test_missing_idempotency_key(client):
    assert client.post("/claims", json=submission()).status_code == 400


def test_unknown_policy(client):
    r = post(client, submission(policy_number="CP00000000"))
    assert r.status_code == 422
    assert errors(r) == {"policy_number": "unknown_policy"}


def test_field_level_errors_come_together(client):
    r = post(client, submission(claim_type_code="MEDICAL", event_country="Austria", iban="SK00123"))
    assert r.status_code == 422
    assert errors(r) == {
        "claim_type_code": "not_in_code_list",
        "event_country": "not_in_code_list",
        "iban": "invalid_iban",
    }


def test_insured_person_must_be_on_the_policy(client):
    r = post(client, submission(insured={"name": "Ján Nikto", "birth_number": "850101/0001"}))
    assert errors(r) == {"insured.birth_number": "not_insured_on_policy"}


def test_event_outside_policy_period(client):
    r = post(client, submission(event_date="2020-01-01"))
    assert errors(r) == {"event_date": "outside_policy_period"}


def test_a_declined_claim_outside_the_period_is_registered(client):
    body = submission(event_date="2020-01-01", total_payout="0.00")
    body["items"][0].update(payout_eur="0.00", decision="DECLINE")
    assert post(client, body).status_code == 201


def test_cancellation_cover_starts_at_issue(client):
    p = policy()
    body = submission(p, claim_type_code="CXL", event_date=p["issue_date"])
    body["items"][0]["coverage_code"] = "CXL"
    assert post(client, body).status_code == 201


def test_total_must_equal_item_payouts(client):
    r = post(client, submission(total_payout="300.00"))
    assert errors(r) == {"total_payout": "does_not_match_items"}


def test_payout_above_remaining_limit(client):
    p = next(x for x in POLICIES if x["prior_paid"])
    cov, _paid = next(iter(p["prior_paid"].items()))
    code = {"medical": "MED", "luggage": "LUG"}[cov]
    body = submission(
        p,
        claim_type_code=code,
        total_payout="2000.00",
        items=[
            {
                "ref": "I1",
                "coverage_code": code,
                "claimed_eur": "2000.00",
                "payout_eur": "2000.00",
                "decision": "PAY",
                "clause_refs": ["A7.1"],
            }
        ],
    )
    r = post(client, body)
    assert errors(r) == {"items.0.payout_eur": "above_remaining_limit"}


def test_only_eur_payouts(client):
    assert errors(post(client, submission(currency="CZK"))) == {"currency": "not_in_code_list"}


def test_code_lists_and_policy_lookup(client):
    assert "MED" in client.get("/codelists/claim_type").json()
    assert client.get("/codelists/nope").status_code == 404
    p = policy()
    got = client.get(f"/policies/{p['policy_number']}").json()
    assert got["product"] == p["product"]
    assert "remaining" in got


def test_attachment_upload(client):
    claim_id = post(client, submission()).json()["core_claim_id"]
    r = client.post(
        f"/claims/{claim_id}/attachments", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert r.status_code == 201
    assert client.get(f"/claims/{claim_id}").json()["attachments"] == ["a.pdf"]


def test_openapi_is_published(client):
    spec = client.get("/openapi.json").json()
    assert "/claims" in spec["paths"]
