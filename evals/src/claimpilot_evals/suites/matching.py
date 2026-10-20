"""Matching on ground-truth values (a perfect extraction) against the ERP records of the split:
every planted discrepancy must come out as its finding on its line, and nothing else may.

Planted kinds scored here: unknown_supplier, iban_changed, price_diff, short_delivery,
unknown_original. Missing pages and duplicates belong to validation.
"""

import json
from collections import Counter
from typing import Any

from claimpilot_evals.invoice_data import ROOT, invoices
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext
from claimpilot_evals.suites.invoice_validation import values_of
from claimpilot_worker.matching.invoice import match
from claimpilot_worker.matching.settings import match_settings

SCORED = {"unknown_supplier", "iban_changed", "price_diff", "short_delivery", "unknown_original"}


class JsonErp:
    """The ERP records of a split, as the mock ERP serves them."""

    def __init__(self, records: dict[str, Any], known: set[tuple[str, str]]) -> None:
        self.records, self.known = records, known
        self.orders = {o["number"]: o for o in records["orders"]}

    def supplier(self, ico: str | None, vat_id: str | None) -> dict[str, Any] | None:
        s = self.records["suppliers"]
        return next((x for x in s if vat_id and x["vat_id"] == vat_id), None) or next(
            (x for x in s if ico and x["ico"] == ico), None
        )

    def order(self, number: str) -> dict[str, Any] | None:
        return self.orders.get(number)

    def receipts_for(self, number: str) -> list[dict[str, Any]]:
        return [r for r in self.records["receipts"] if r["order_number"] == number]

    def invoice_known(self, supplier_ico: str, number: str) -> bool:
        return (supplier_ico, number) in self.known

    def invoiced_before(self, number: str) -> dict[int, Any]:
        return {}  # each synthetic invoice is judged on its own, against an untouched receipt


async def run(ctx: RunContext) -> Report:
    report = Report("matching", ctx.split)
    gts = invoices(ctx.split, ctx.limit)
    records = json.loads((ROOT / f"erp-{ctx.split}.json").read_text("utf-8"))
    known = {
        (g.data["header"]["supplier_ico"]["value"], g.data["header"]["invoice_number"]["value"])
        for g in gts
        if g.data["kind"] == "invoice"
    }
    erp = JsonErp(records, known)
    settings = match_settings()
    missed, extra = Counter[str](), Counter[str]()
    for g in gts:
        header, lines = values_of(g.data)
        result = match(header, lines, erp, settings, kind=g.data["kind"])
        expected = {(f["kind"], f["line"]) for f in g.data["findings"] if f["kind"] in SCORED}
        got = {(f.kind, f.line) for f in result.findings}
        for k, line in expected:
            ok = (k, line) in got
            missed[k] += not ok
            report.items.append(ItemResult(f"{g.id}/{k}/{line}", ok, k, sorted(got), ["planted"]))
        for k, line in got - expected:
            extra[k] += 1
            report.items.append(ItemResult(f"{g.id}/extra/{k}/{line}", False, None, k, ["extra"]))
        report.items.append(
            ItemResult(f"{g.id}/exact", got == expected, sorted(expected), sorted(got), ["invoice"])
        )

    def share(tag: str) -> tuple[int, int]:
        items = [i for i in report.items if tag in i.tags]
        return sum(i.ok for i in items), len(items)

    report.ratio("planted_findings_found", *share("planted"))
    report.ratio("invoices_exact", *share("invoice"))
    report.count("extra_findings", sum(extra.values()))
    for k in sorted(SCORED):
        report.notes.append(f"{k}: missed {missed[k]}, extra {extra[k]}")
    return report
