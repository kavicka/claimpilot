from decimal import Decimal

import pytest

from claimpilot_core.domain import Queue
from claimpilot_worker.routing.invoice import route_invoice

OK = [{"name": "line_math", "ok": True, "fields": []}]
LIMIT = {"EUR": Decimal("20000"), "CZK": Decimal("500000")}


def route(
    validation=OK, findings=(), kind="invoice", total=Decimal("100"), injection=None, currency="EUR"
):
    return route_invoice(
        list(validation),
        list(findings),
        kind=kind,
        total=total,
        currency=currency,
        senior_amount=LIMIT,
        injection=injection,
    )


def test_a_clean_invoice_goes_to_fast_track():
    r = route()
    assert (r.queue, r.rule, r.hits) == (Queue.FAST_TRACK, None, [])


@pytest.mark.parametrize(
    ("kwargs", "queue", "rule"),
    [
        ({"findings": [{"kind": "iban_changed"}]}, Queue.FRAUD_REVIEW, "I1"),
        ({"validation": [{"name": "duplicate", "ok": False, "detail": "F-1"}]}, Queue.FRAUD_REVIEW, "I2"),
        ({"injection": ["page 1: hidden text"]}, Queue.SENIOR, "I3"),
        ({"findings": [{"kind": "unknown_supplier"}]}, Queue.SENIOR, "I4"),
        ({"kind": "credit_note", "total": Decimal("-5")}, Queue.SENIOR, "I5"),
        ({"total": Decimal("20000.01")}, Queue.SENIOR, "I6"),
        ({"findings": [{"kind": "price_diff", "line": 3}]}, Queue.STANDARD, "I7"),
        ({"validation": [{"name": "recap_vat", "ok": False}]}, Queue.STANDARD, "I8"),
    ],
)  # fmt: skip
def test_each_rule(kwargs, queue, rule):
    r = route(**kwargs)
    assert (r.queue, r.rule) == (queue, rule)


def test_the_most_serious_hit_decides_and_all_are_kept():
    r = route(
        findings=[{"kind": "price_diff", "line": 1}, {"kind": "iban_changed"}],
        validation=[{"name": "recap_vat", "ok": False}],
        total=Decimal("50000"),
    )
    assert r.queue is Queue.FRAUD_REVIEW and r.rule == "I1"
    assert [h.rule for h in r.hits] == ["I1", "I6", "I7", "I8"]


def test_the_senior_limit_counts_the_amount_either_way():
    assert route(kind="credit_note", total=Decimal("-25000")).hits[-1].rule == "I6"


def test_another_partys_order_goes_to_a_senior():
    r = route_invoice(
        [],
        [{"kind": "order_mismatch"}],
        kind="invoice",
        total=Decimal("1"),
        currency="EUR",
        senior_amount=LIMIT,
    )
    assert (r.queue.value, r.rule) == ("senior", "I4")


def test_the_limit_is_per_currency():
    # 20 000 CZK is about 800 EUR: below its own limit, so no senior.
    assert route(total=Decimal("20000"), currency="CZK").rule is None
    assert route(total=Decimal("500000.01"), currency="CZK").rule == "I6"


@pytest.mark.parametrize("currency", [None, "USD", ""])
def test_a_currency_without_a_limit_goes_to_a_senior(currency):
    r = route(total=Decimal("10"), currency=currency)
    assert (r.queue, r.rule) == (Queue.SENIOR, "I6")
    assert "currency" in r.hits[0].detail


def test_an_amount_that_was_not_read_goes_to_a_senior():
    r = route(total=None)
    assert (r.queue, r.rule) == (Queue.SENIOR, "I6")
    assert "not read" in r.hits[0].detail


def test_goods_invoiced_twice_go_to_a_standard_handler():
    r = route(findings=[{"kind": "already_invoiced", "line": 0}])
    assert (r.queue, r.rule) == (Queue.STANDARD, "I7")
