"""Currency conversion from a fixed ECB snapshot, so payouts are reproducible (VPP A12.1)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

CENT = Decimal("0.01")


class UnknownCurrencyError(KeyError):
    pass


class FxSnapshot(BaseModel):
    snapshot_date: date
    source: str
    rates: dict[str, Decimal]  # units of currency per 1 EUR

    @classmethod
    def load(cls, path: Path) -> "FxSnapshot":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def to_eur(self, amount: Decimal, currency: str) -> Decimal:
        rate = self.rates.get(currency.upper())
        if rate is None:
            raise UnknownCurrencyError(currency)
        return (amount / rate).quantize(CENT, rounding=ROUND_HALF_UP)


@lru_cache
def default_fx(config_dir: Path) -> FxSnapshot:
    return FxSnapshot.load(config_dir / "fx_rates.yaml")
