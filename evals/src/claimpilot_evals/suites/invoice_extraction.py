"""Invoice extraction: header fields, line items cell by cell, grounding, payload leakage.

Each ground-truth value counts once: a header field printed on a page of the file, a cell of a
line printed in the file. Numbers are compared as numbers ("20,00" = "20"), text as printed
(case and spaces aside). A value the model gives for a field the invoice does not print is a
false value; customer numbers copied from an order number are the usual case.
"""

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from claimpilot_evals.invoice_data import invoices, parsed_invoice
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext
from claimpilot_worker.extraction.invoice import extract_invoice, redact_invoice

SKIP_HEADER = {"document_kind"}
TEXT_FIELDS = {
    "name", "supplier_name", "buyer_name", "delivery_note_numbers", "unit", "supplier_code",
    "batch", "expiry", "origin", "customs_code", "sukl_code", "invoice_number",
    "order_number", "customer_number", "original_invoice_number", "proforma_number",
    "variable_symbol", "constant_symbol", "specific_symbol", "currency", "page_note",
}  # fmt: skip


def _plain(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


def same(name: str, gt: dict[str, Any], pred_raw: str | None, pred_norm: str | None) -> bool:
    leaf = name.rsplit(".", 1)[-1]
    if pred_raw is None:
        return False
    if leaf in TEXT_FIELDS:
        return _plain(pred_raw) == _plain(gt["printed"])
    if leaf == "reverse_charge":
        return True  # present, and present in the ground truth
    try:
        return Decimal(str(gt["value"])) == Decimal(str(pred_norm))
    except (InvalidOperation, TypeError, ValueError):
        return str(gt["value"]) == str(pred_norm)


def gt_line_cells(line: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cells = dict(line["cells"])
    batches = line.get("batches", [])
    for i, b in enumerate(batches):
        for k, v in b.items():
            if k == "quantity" and len(batches) == 1:
                continue  # one batch: its quantity is the line's, printed once
            cells[f"batches[{i}].{k}"] = v
    return cells


async def run(ctx: RunContext) -> Report:
    report = Report("invoice_extraction", ctx.split)
    pii: list[str] = []
    kinds = Counter[tuple[str, str]]()
    lines_expected = lines_found = 0
    false_values = grounded = predicted = 0
    by_column: dict[str, list[bool]] = {}
    for gt_inv in invoices(ctx.split, ctx.limit):
        gt = gt_inv.data
        pii += gt.get("pii", [])
        parsed = parsed_invoice(gt_inv.path, gt["sha256"])
        red = redact_invoice(parsed)
        ex = await extract_invoice(parsed, red.blocks, ctx.gateway, redacted_cells=red.cells)
        kinds[(gt["kind"], ex.kind.value)] += 1
        report.items.append(
            ItemResult(
                f"{gt_inv.id}/kind",
                ex.kind.value == gt["kind"],
                gt["kind"],
                ex.kind.value,
                ["kind"],
            )
        )
        # header
        pred = {f.name: f for f in ex.header if f.value_raw}
        expected_header = {
            k: v for k, v in gt["header"].items() if k not in SKIP_HEADER and v.get("page")
        }
        for i, row in enumerate(r for r in gt["recap"] if r.get("page")):
            expected_header |= {f"recap[{i}].{k}": v for k, v in row.items() if k != "page"}
        for i, fee in enumerate(f for f in gt["fees"] if f.get("page") and not f["included"]):
            expected_header |= {f"fees[{i}].label": fee["label"], f"fees[{i}].net": fee["net"]}
        for name, g in expected_header.items():
            p = pred.get(name)
            ok = same(name, g, p.value_raw if p else None, p.value_norm if p else None)
            report.items.append(
                ItemResult(
                    f"{gt_inv.id}/header.{name}",
                    ok,
                    g["printed"],
                    p.value_raw if p else None,
                    ["header"],
                )
            )
        for name, p in pred.items():
            predicted += 1
            grounded += p.grounded
            if name not in expected_header:
                false_values += 1
                report.items.append(
                    ItemResult(
                        f"{gt_inv.id}/header.{name}", False, None, p.value_raw, ["false_value"]
                    )
                )
        # lines, in reading order
        gt_lines = [ln for ln in gt["lines"] if ln.get("page") is not None]
        got = {lr.n: lr for lr in ex.lines}
        lines_expected += len(gt_lines)
        lines_found += sum(1 for n in range(1, len(gt_lines) + 1) if n in got)
        for n, line in enumerate(gt_lines, start=1):
            lr = got.get(n)
            for name, g in gt_line_cells(line).items():
                f = lr.fields.get(name) if lr else None
                ok = same(name, g, f.value_raw if f else None, f.value_norm if f else None)
                by_column.setdefault(name.split(".")[-1], []).append(ok)
                report.items.append(
                    ItemResult(
                        f"{gt_inv.id}/line{n}.{name}",
                        ok,
                        g["printed"],
                        f.value_raw if f else None,
                        ["line"],
                    )
                )
            if lr:
                for name, f in lr.fields.items():
                    if f.value_raw is None:
                        continue  # an empty field left for the handler, not a prediction
                    predicted += 1
                    grounded += f.grounded
                    if name not in gt_line_cells(line):
                        false_values += 1
                        report.items.append(
                            ItemResult(
                                f"{gt_inv.id}/line{n}.{name}",
                                False,
                                None,
                                f.value_raw,
                                ["false_value"],
                            )
                        )
        report.notes.append(f"{gt_inv.id} {gt['layout']}: lines {len(ex.lines)}/{len(gt_lines)}")

    def share(tag: str) -> tuple[int, int]:
        items = [i for i in report.items if tag in i.tags]
        return sum(i.ok for i in items), len(items)

    report.ratio("kind_accuracy", *share("kind"))
    report.ratio("header_field_accuracy", *share("header"))
    report.ratio("line_recall", lines_found, lines_expected)
    report.ratio("line_cell_accuracy", *share("line"))
    report.count("false_values", false_values)
    report.ratio("grounded_share", grounded, predicted)
    leaks = ctx.recorder.leaks(pii)
    report.count("leaked_values_in_payloads", len(leaks))
    if leaks:
        report.notes.append(f"leaked: {leaks[:5]}")
    for col, oks in sorted(by_column.items()):
        report.notes.append(f"column {col}: {sum(oks)}/{len(oks)}")
    for (exp, got_kind), k in sorted(kinds.items()):
        if exp != got_kind:
            report.notes.append(f"kind {exp} -> {got_kind}: {k}")
    return report
