"""Invoice validation on ground-truth values (a perfect extraction): no check may fail on a
clean invoice, and every planted or injected error must fail the check it belongs to.

Planted errors come from the generator (missing pages). Injected errors are made here, one per
invoice and kind, on a copy of its values: a line total off by one euro, a total off by ten cents,
a recap base off, a buyer that is not ours, a broken IBAN, a due date before the issue date.
"""

import copy
from collections import Counter
from typing import Any

from claimpilot_evals.invoice_data import invoices
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext
from claimpilot_worker.validation.invoice import validate
from claimpilot_worker.validation.settings import ours

Values = tuple[dict[str, str], list[dict[str, str]]]


def values_of(gt: dict[str, Any]) -> Values:
    """Header and line values as printed, only what is in the file."""
    header = {
        k: v["printed"] for k, v in gt["header"].items() if v.get("page") and k != "document_kind"
    }
    for i, row in enumerate(r for r in gt["recap"] if r.get("page")):
        header |= {f"recap[{i}].{k}": row[k]["printed"] for k in ("rate", "base", "vat")}
    for i, fee in enumerate(f for f in gt["fees"] if f.get("page") and not f["included"]):
        header |= {
            f"fees[{i}].label": fee["label"]["printed"],
            f"fees[{i}].net": fee["net"]["printed"],
        }
    lines = []
    for ln in gt["lines"]:
        if ln.get("page") is None:
            continue
        values = {k: v["printed"] for k, v in ln["cells"].items()}
        for i, b in enumerate(ln.get("batches", [])):
            values |= {
                f"batches[{i}].{k}": b[k]["printed"] for k in ("batch", "expiry", "quantity")
            }
        lines.append(values)
    return header, lines


def _shift(printed: str, by: str) -> str:
    """The printed amount moved by `by` euros, in the same print style."""
    from decimal import Decimal

    from claimpilot_core.invoice_values import parse_number

    value = parse_number(printed)
    assert value is not None
    shifted = value + Decimal(by)
    decimals = len(printed.split(",")[1]) if "," in printed else 2
    thousands = "." if "." in printed.split(",")[0] else " "
    from claimpilot_datagen.invoices.fmt import number

    return number(shifted, decimals, thousands)


def mutations(header: dict[str, str], lines: list[dict[str, str]]) -> list[tuple[str, str, Values]]:
    """(name, the check that must fail, values)."""
    out = []

    def mutated(fn) -> Values:
        h, ls = copy.deepcopy(header), copy.deepcopy(lines)
        fn(h, ls)
        return h, ls

    if lines and "line_net" in lines[0]:
        out.append(
            (
                "line_net+1",
                "line_math",
                mutated(lambda h, ls: ls[0].update(line_net=_shift(ls[0]["line_net"], "1"))),
            )
        )
    if "total" in header and "total_net" in header:
        out.append(
            (
                "total+0.10",
                "total",
                mutated(lambda h, ls: h.update(total=_shift(h["total"], "0.10"))),
            )
        )
    if "recap[0].base" in header and lines:
        out.append(
            (
                "recap_base+1",
                "recap_base",
                mutated(lambda h, ls: h.update({"recap[0].base": _shift(h["recap[0].base"], "1")})),
            )
        )
    if len(lines) >= 2 and ("total" in header or "total_net" in header or "amount_due" in header):
        # A line the extraction left out: the recap (per rate) or the totals must not hold.
        check = "recap_base" if "recap[0].base" in header else "lines_total"
        out.append(("line_dropped", check, mutated(lambda h, ls: ls.pop())))
    if "buyer_vat_id" in header:
        out.append(
            (
                "foreign_buyer",
                "buyer_is_ours",
                mutated(lambda h, ls: h.update(buyer_ico="91583632", buyer_vat_id="SK2998051309")),
            )
        )
    if "supplier_iban" in header:

        def break_iban(h, ls):
            last = h["supplier_iban"][-1]
            h["supplier_iban"] = h["supplier_iban"][:-1] + ("0" if last != "0" else "1")

        out.append(("iban_digit", "supplier_iban", mutated(break_iban)))
    if "due_date" in header and "issue_date" in header:
        out.append(
            (
                "due_before_issue",
                "date_order",
                mutated(lambda h, ls: h.update(due_date="01.01.2024")),
            )
        )
    return out  # fmt: skip


async def run(ctx: RunContext) -> Report:
    report = Report("invoice_validation", ctx.split)
    buyers = ours()
    false_alarms = Counter[str]()
    for gt_inv in invoices(ctx.split, ctx.limit):
        gt = gt_inv.data
        header, lines = values_of(gt)
        clean = validate(header, lines, buyers, pages_present=gt["pages_present"], kind=gt["kind"])
        planted_pages = "truncated" in gt["edge_cases"]
        fails = [c for c in clean.failed if not (planted_pages and c.name == "pages_complete")]
        for c in fails:
            false_alarms[c.name] += 1
        report.items.append(
            ItemResult(
                f"{gt_inv.id}/clean",
                not fails,
                [],
                [f"{c.name}:{c.fields[:2]}" for c in fails],
                ["clean"],
            )
        )
        if planted_pages:
            report.items.append(
                ItemResult(
                    f"{gt_inv.id}/pages_missing",
                    clean.needs_info,
                    True,
                    clean.needs_info,
                    ["planted"],
                )
            )
        for name, check, (h, ls) in mutations(header, lines):
            result = validate(h, ls, buyers, pages_present=gt["pages_present"], kind=gt["kind"])
            caught = any(c.name == check for c in result.failed)
            report.items.append(
                ItemResult(
                    f"{gt_inv.id}/{name}",
                    caught,
                    check,
                    [c.name for c in result.failed],
                    ["injected"],
                )
            )

    def share(tag: str) -> tuple[int, int]:
        items = [i for i in report.items if tag in i.tags]
        return sum(i.ok for i in items), len(items)

    report.ratio("clean_invoices_pass", *share("clean"))
    report.ratio("planted_errors_caught", *share("planted"))
    report.ratio("injected_errors_caught", *share("injected"))
    report.count("false_alarms", sum(false_alarms.values()))
    for name, k in false_alarms.most_common():
        report.notes.append(f"false alarm {name}: {k}")
    return report
