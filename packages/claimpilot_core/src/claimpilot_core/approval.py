"""Four-eyes rule for invoice approval (`approval:` in config/invoices.yaml).

At or above the limit of its currency an invoice needs an approver who did not correct any of its
fields. An amount we cannot read, or a currency without a limit, counts as above the limit: the
rule fails closed.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FourEyes:
    limits: dict[str, Decimal]  # currency -> amount at which a second person is needed

    def applies(self, total: Decimal | None, currency: str | None) -> bool:
        if total is None or not currency:
            return True
        limit = self.limits.get(currency.upper())
        return limit is None or total >= limit


def load_four_eyes(config_dir: Path) -> FourEyes:
    raw = yaml.safe_load((config_dir / "invoices.yaml").read_text("utf-8"))
    limits = (raw.get("approval") or {}).get("four_eyes_amount") or {}
    return FourEyes({str(k).upper(): Decimal(str(v)) for k, v in limits.items()})
