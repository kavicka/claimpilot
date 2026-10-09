from datetime import date
from decimal import Decimal

from claimpilot_worker.summaries.factcheck import Facts, check, mentions

FACTS = Facts(
    amounts={Decimal("279.50"), Decimal("214.50"), Decimal("65.00")},
    dates={date(2026, 2, 14), date(2026, 3, 2)},
    clauses={"A4.1", "A4.3"},
)


def test_mentions_in_slovak_and_german():
    m = mentions("Preplácame 214,50 EUR podľa čl. 4 ods. 3 VPP, udalosť zo dňa 14. 2. 2026.")
    assert m.amounts == [Decimal("214.50")]
    assert m.dates == [date(2026, 2, 14)]
    assert m.clauses == ["A4.3"]
    de = mentions("Auszahlung 1.279,50 EUR nach Art. 4 Abs. 1, Ereignis am 14.02.2026.")
    assert de.amounts == [Decimal("1279.50")]
    assert de.clauses == ["A4.1"]
    assert de.dates == [date(2026, 2, 14)]


def test_consistent_text_has_no_violations():
    text = "Preplácame 214,50 EUR. Spoluúčasť 65,00 EUR podľa čl. 4 ods. 3. Faktúra 279,50 EUR zo dňa 14. 2. 2026."
    assert check(text, FACTS) == []


def test_invented_amount_date_and_clause_are_flagged():
    text = "Preplácame 250,00 EUR podľa čl. 7 ods. 2, udalosť zo dňa 15. 2. 2026."
    kinds = sorted(v.kind for v in check(text, FACTS))
    assert kinds == ["amount", "clause", "date"]


def test_plain_counts_and_percentages_are_not_amounts():
    assert (
        mentions(
            "Peniaze odídu do 5 pracovných dní, preplácame 80 % poplatku po 12 hodinách."
        ).amounts
        == []
    )


def test_amounts_with_currency_but_no_decimals_count():
    assert mentions("Limit je 1 000 EUR.").amounts == [Decimal("1000")]
