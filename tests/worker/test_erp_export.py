"""The mock ERP's intake is safe to repeat (idempotency key), refuses a different document with a
taken number, and asks for a bearer token when one is configured (ADR-015)."""

import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal as Dec

import pytest
from fastapi.testclient import TestClient

from claimpilot_core.settings import Settings, repo_root
from claimpilot_core_mock import erp
from claimpilot_core_mock.ubl_rules import CBC
from claimpilot_worker.export.ubl import Line, Party, UblInvoice, build

SUPPLIER = Party("Medika Distribúcia a.s.", "98618881", "SK2918078559", "SK", "Lenardova 254")
BUYER = Party("Lekárne Sever s.r.o.", "90882750", "SK2997673481", "SK")
IBAN = "SK44 5200 0000 0074 5333 0369"


def xml(number: str = "260104417", price: str = "2.656") -> bytes:
    net = Dec(price) * 2
    return build(
        UblInvoice(
            kind="invoice",
            number=number,
            issue_date=date(2025, 8, 20),
            due_date=date(2025, 9, 19),
            tax_point_date=date(2025, 8, 20),
            currency="EUR",
            supplier=SUPPLIER,
            buyer=BUYER,
            iban=IBAN,
            payment_id=number,
            order_number="OB25000001",
            delivery_note=None,
            original_number=None,
            reverse_charge=False,
            lines=[Line(Dec("2"), "ks", "Šampón", Dec(price), net.quantize(Dec("0.01")), 23)],
        )
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ERP_MOCK_DATA", str(repo_root() / "data" / "synthetic" / "invoices"))
    monkeypatch.delenv("ERP_MOCK_TOKEN", raising=False)
    erp.records.cache_clear()
    erp.POSTED.clear()
    erp.KEYS.clear()
    yield TestClient(erp.app)
    erp.records.cache_clear()
    erp.POSTED.clear()
    erp.KEYS.clear()


def post(client, body: bytes, key: str | None = None, **kw):
    headers = {"content-type": "application/xml"} | ({"Idempotency-Key": key} if key else {})
    return client.post("/invoices", content=body, headers=headers | kw.pop("headers", {}))


def test_the_test_document_is_accepted(client):
    resp = post(client, xml(), "inv-1")
    assert resp.status_code == 201, resp.text
    assert resp.json()["erp_id"] == "ERP-000001"


def test_a_repeated_key_gets_the_same_answer_and_stores_nothing_new(client):
    first = post(client, xml(), "inv-1")
    again = post(client, xml(), "inv-1")
    assert again.status_code == 200
    assert again.json() == first.json()
    assert len(erp.POSTED) == 1


def test_a_second_key_with_the_same_number_is_refused_with_the_first_id(client):
    first = post(client, xml(), "inv-1").json()["erp_id"]
    resp = post(client, xml(), "inv-2")  # even the identical document: another invoice row
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["erp_id"] == first
    assert detail["errors"][0]["rule"] == "ERP-DUPLICATE"
    assert len(erp.POSTED) == 1


def test_the_same_number_without_a_key_is_refused_too(client):
    post(client, xml())
    assert post(client, xml()).status_code == 409


def test_the_same_key_with_other_content_is_refused(client):
    post(client, xml(), "inv-1")
    resp = post(client, xml(price="3.000"), "inv-1")
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["rule"] == "idempotency_key_reused"
    assert len(erp.POSTED) == 1


def test_a_refused_document_does_not_burn_its_key(client):
    root = ET.fromstring(xml())
    root.findall(f".//{CBC}PayableAmount")[0].text = "1.00"
    broken = ET.tostring(root, encoding="utf-8")
    resp = post(client, broken, "inv-1")
    assert resp.status_code == 422 and not erp.POSTED
    assert post(client, xml(), "inv-1").status_code == 201  # corrected, same key


def test_without_a_token_configured_everything_is_open(client):
    assert client.get("/suppliers", params={"ico": "98618881"}).status_code == 200


@pytest.fixture
def secured(client, monkeypatch):
    monkeypatch.setenv("ERP_MOCK_TOKEN", "s3cret")
    return client


def test_a_token_is_required_everywhere_but_health(secured):
    assert secured.get("/health").status_code == 200
    for method, url in (
        ("get", "/suppliers?ico=98618881"),
        ("get", "/orders/OB-1"),
        ("get", "/orders/OB-1/receipts"),
        ("post", "/invoices"),
    ):
        resp = getattr(secured, method)(url)
        assert resp.status_code == 401, url
        assert resp.headers["www-authenticate"] == "Bearer"


def test_a_wrong_token_is_refused_and_the_right_one_works(secured):
    bad = {"Authorization": "Bearer nope"}
    assert secured.get("/suppliers?ico=98618881", headers=bad).status_code == 401
    assert (
        secured.get("/suppliers?ico=98618881", headers={"Authorization": "s3cret"}).status_code
        == 401
    )
    good = {"Authorization": "Bearer s3cret"}
    assert secured.get("/suppliers?ico=98618881", headers=good).status_code == 200
    assert post(secured, xml(), "inv-1", headers=good).status_code == 201


def test_the_worker_sends_the_token_on_every_call():
    from claimpilot_worker.steps.invoice import erp_client

    c = erp_client(Settings(erp_url="http://erp.test", erp_token="s3cret"))  # type: ignore[arg-type]
    assert c.headers["authorization"] == "Bearer s3cret"
    assert "authorization" not in erp_client(Settings(erp_token="")).headers  # type: ignore[arg-type]
