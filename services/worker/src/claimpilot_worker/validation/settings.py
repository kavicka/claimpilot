"""config/invoices.yaml: our own entities and the tolerances of validation and matching."""

from decimal import Decimal
from functools import lru_cache
from typing import Any

import yaml

from claimpilot_core.invoice_values import DEFAULT_CURRENCIES, DEFAULT_VAT_RATES
from claimpilot_core.settings import repo_root
from claimpilot_worker.validation.invoice import Ours, Tolerance


@lru_cache
def config() -> dict[str, Any]:
    return yaml.safe_load((repo_root() / "config" / "invoices.yaml").read_text("utf-8"))


def ours() -> Ours:
    buyers = config()["buyers"]
    return Ours(icos={b["ico"] for b in buyers}, vat_ids={b["vat_id"] for b in buyers})


def vat_rates() -> frozenset[int]:
    return frozenset(int(r) for r in config().get("vat", {}).get("rates", DEFAULT_VAT_RATES))


def currencies() -> frozenset[str]:
    return frozenset(str(c).upper() for c in config().get("currencies", DEFAULT_CURRENCIES))


def senior_amounts() -> dict[str, Decimal]:
    """The senior limit per currency."""
    return {str(c).upper(): Decimal(a) for c, a in config()["routing"]["senior_amount"].items()}


def tolerance() -> Tolerance:
    v = config()["validation"]
    return Tolerance(line=Decimal(v["line_tolerance"]), sum=Decimal(v["sum_tolerance"]))


def max_items() -> int:
    """An invoice with more items than this goes back to the supplier ('split the invoice')."""
    return int(config().get("limits", {}).get("max_items", 400))
