from decimal import Decimal

import pytest

from claimpilot_core.domain import Coverage, Product
from claimpilot_core.fx import FxSnapshot, UnknownCurrencyError
from claimpilot_core.policy import load_products, load_terms


@pytest.fixture(scope="module")
def products(request):
    return load_products(request.config.rootpath / "data" / "policies" / "products.yaml")


@pytest.fixture(scope="module")
def terms(request):
    return load_terms(request.config.rootpath / "data" / "policies" / "vpp_cp_2026.yaml")


def test_every_referenced_clause_exists_in_the_terms(products, terms):
    referenced = products.referenced_clauses()
    assert referenced, "products reference no clauses"
    assert referenced <= terms.clause_ids()


def test_clause_ids_are_article_dot_paragraph(terms):
    clause = terms.clause("A4.4")
    assert clause.article == 4
    assert clause.paragraph == 4
    assert "zubné" in clause.text
    assert terms.display_id("A4.4") == "čl. 4 ods. 4"


def test_basic_has_no_cancellation_or_delay(products):
    basic = products.product(Product.BASIC)
    assert basic.coverage(Coverage.CANCELLATION) is None
    assert basic.coverage(Coverage.DELAY) is None
    assert basic.coverage(Coverage.MEDICAL).limit == Decimal(60000)


def test_premium_covers_extreme_sports_others_do_not(products):
    assert products.product(Product.PREMIUM).extreme_sports
    assert not products.product(Product.STANDARD).extreme_sports


def test_exclusion_lookup(products):
    excl = products.exclusions["alcohol_or_drugs"]
    assert excl.clause == "A11.2"
    assert Coverage.MEDICAL in excl.coverages


def test_required_documents_per_claim_type(products):
    assert products.required_documents["medical"] == [
        "claim_form",
        "medical_report",
        "medical_invoice",
    ]


@pytest.fixture
def fx(request):
    return FxSnapshot.load(request.config.rootpath / "config" / "fx_rates.yaml")


@pytest.mark.parametrize(
    ("amount", "currency", "eur"),
    [
        ("100.00", "EUR", "100.00"),
        ("2450.00", "CZK", "100.00"),
        ("1000", "CZK", "40.82"),  # 40.8163... rounds half up to cents
        ("39500", "HUF", "100.00"),
        ("108.00", "USD", "100.00"),
        ("0.01", "TRY", "0.00"),
    ],
)
def test_fx_converts_to_eur_and_rounds_half_up(fx, amount, currency, eur):
    assert fx.to_eur(Decimal(amount), currency) == Decimal(eur)


def test_fx_unknown_currency_raises(fx):
    with pytest.raises(UnknownCurrencyError):
        fx.to_eur(Decimal(1), "XYZ")


def test_fx_snapshot_date_is_recorded(fx):
    assert fx.snapshot_date.isoformat() == "2026-01-30"
