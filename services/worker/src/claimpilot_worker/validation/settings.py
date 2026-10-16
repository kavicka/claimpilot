"""config/invoices.yaml: our own entities and the tolerances of validation and matching."""

from decimal import Decimal
from functools import lru_cache
from typing import Any

import yaml

from claimpilot_core.settings import repo_root
from claimpilot_worker.validation.invoice import Ours, Tolerance


@lru_cache
def config() -> dict[str, Any]:
    return yaml.safe_load((repo_root() / "config" / "invoices.yaml").read_text("utf-8"))


def ours() -> Ours:
    buyers = config()["buyers"]
    return Ours(icos={b["ico"] for b in buyers}, vat_ids={b["vat_id"] for b in buyers})


def tolerance() -> Tolerance:
    v = config()["validation"]
    return Tolerance(line=Decimal(v["line_tolerance"]), sum=Decimal(v["sum_tolerance"]))
