"""The mock ERP serves the synthetic invoice set's records."""

import pytest
from fastapi.testclient import TestClient

from claimpilot_core.settings import repo_root
from claimpilot_core_mock import erp


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ERP_MOCK_DATA", str(repo_root() / "data" / "synthetic" / "invoices"))
    erp.records.cache_clear()
    yield TestClient(erp.app)
    erp.records.cache_clear()


def test_health_counts_records(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["suppliers"] == 12 and body["orders"] > 50


def test_supplier_by_vat_id_or_ico(client):
    some = next(iter(erp.records()["suppliers"].values()))
    assert client.get("/suppliers", params={"vat_id": some["vat_id"]}).json()["ico"] == some["ico"]
    assert client.get("/suppliers", params={"ico": some["ico"]}).status_code == 200
    assert client.get("/suppliers", params={"ico": "00000000"}).status_code == 404


def test_order_and_its_receipts(client):
    number = next(iter(erp.records()["orders"]))
    order = client.get(f"/orders/{number}").json()
    assert order["lines"] and order["number"] == number
    assert isinstance(client.get(f"/orders/{number}/receipts").json(), list)
    assert client.get("/orders/OB-NONE").status_code == 404
