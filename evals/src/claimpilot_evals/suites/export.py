"""Export: every dev invoice, credit note and proforma, built from ground-truth values (a perfect
extraction) as Peppol BIS Billing 3.0 UBL, must pass the mock ERP's rules, and the posted XML must
give back the values it was built from."""

import json
import xml.etree.ElementTree as ET

from claimpilot_core.invoice_values import parse_number
from claimpilot_core_mock.ubl_rules import _dec, _p, _text, check, parse
from claimpilot_evals.invoice_data import ROOT, invoices
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext
from claimpilot_evals.suites.invoice_validation import values_of
from claimpilot_worker.export.ubl import build
from claimpilot_worker.export.values import ExportError, from_values
from claimpilot_worker.validation.settings import config


def round_trip(
    root: ET.Element, header: dict[str, str], lines: list[dict[str, str]], kind: str
) -> list[str]:
    """Values that came out different from what went in."""
    bad = []
    if _text(root, "ID") != header.get("invoice_number"):
        bad.append("invoice_number")
    payable = _dec(root, "LegalMonetaryTotal/PayableAmount")
    due = parse_number(header.get("amount_due") or header.get("total"))
    if due is not None and payable is not None and abs(payable) != abs(due):
        bad.append(f"payable {payable} != {due}")
    tag = _p("CreditNoteLine" if kind == "credit_note" else "InvoiceLine")
    got = root.findall(tag)
    if len(got) != len(lines):
        bad.append(f"lines {len(got)} != {len(lines)}")
    for el, ln in zip(got, lines, strict=False):
        amount = _dec(el, "LineExtensionAmount")
        net = parse_number(ln.get("line_net"))
        if amount is None or net is None or abs(amount) != abs(net):
            bad.append(f"line {_text(el, 'ID')} amount")
    return bad


async def run(ctx: RunContext) -> Report:
    report = Report("export", ctx.split)
    records = json.loads((ROOT / f"erp-{ctx.split}.json").read_text("utf-8"))
    suppliers = {s["ico"]: s for s in records["suppliers"]}
    buyers = {b["ico"]: b for b in config()["buyers"]}
    rules = {}
    for g in invoices(ctx.split, ctx.limit):
        gt = g.data
        if gt["pages_total"] != gt["pages_present"] or "unknown_supplier" in gt["edge_cases"]:
            continue  # never approved: pages missing, or a supplier the ERP does not know
        header, lines = values_of(gt)
        ico = gt["header"]["supplier_ico"]["value"]
        try:
            ubl = from_values(
                header,
                lines,
                kind=gt["kind"],
                supplier_record=suppliers.get(ico),
                buyer_record=buyers.get(gt["header"].get("buyer_ico", {}).get("value", "")),
            )
            body = build(ubl)
        except ExportError as exc:
            report.items.append(ItemResult(f"{g.id}/accepted", False, True, str(exc), ["accepted"]))
            continue
        _kind, errors = check(parse(body))
        for e in errors:
            rules[e["rule"]] = rules.get(e["rule"], 0) + 1
        report.items.append(
            ItemResult(
                f"{g.id}/accepted", not errors, True, [e["rule"] for e in errors], ["accepted"]
            )
        )
        bad = round_trip(parse(body), header, lines, gt["kind"])
        report.items.append(ItemResult(f"{g.id}/round_trip", not bad, [], bad, ["round_trip"]))

    def share(tag: str) -> tuple[int, int]:
        items = [i for i in report.items if tag in i.tags]
        return sum(i.ok for i in items), len(items)

    report.ratio("accepted", *share("accepted"))
    report.ratio("round_trip", *share("round_trip"))
    for rule, n in sorted(rules.items()):
        report.notes.append(f"rule {rule}: {n}")
    return report
