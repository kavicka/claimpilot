"""Matching tolerances from config/invoices.yaml."""

from decimal import Decimal

from claimpilot_worker.matching.invoice import MatchSettings
from claimpilot_worker.validation.settings import config


def match_settings() -> MatchSettings:
    m = config()["matching"]
    return MatchSettings(
        price_tolerance_pct=Decimal(m["price_tolerance_pct"]),
        per_supplier={ico: Decimal(str(v)) for ico, v in (m.get("per_supplier") or {}).items()},
    )
