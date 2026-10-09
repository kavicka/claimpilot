"""Document type: accuracy on redacted text, share decided by rules, payload leakage."""

from collections import Counter

from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext, redact_claim
from claimpilot_worker.ingest.doctype import classify


async def run(ctx: RunContext) -> Report:
    report = Report("doc_type", ctx.split)
    gt_values: list[str] = []
    confusion: Counter[tuple[str, str]] = Counter()
    for claim in ctx.claims():
        rc = redact_claim(claim)
        gt_values += [v for _, v in claim.pii_values()]
        for doc in rc.docs:
            result = await classify(doc.text(redacted=True), ctx.gateway)
            expected = doc.gt.doc_type
            ok = result.doc_type.value == expected
            confusion[(expected, result.doc_type.value)] += 1
            report.items.append(
                ItemResult(
                    doc.gt.item_id,
                    ok,
                    expected,
                    result.doc_type.value,
                    ["accuracy"],
                    {"method": result.method, "scan": doc.gt.data["scan"]},
                )
            )
    n = len(report.items)
    report.ratio("accuracy", sum(i.ok for i in report.items), n)
    report.ratio("decided_by_rules", sum(i.detail["method"] == "rule" for i in report.items), n)
    leaks = ctx.recorder.leaks(gt_values)
    report.count("leaked_values_in_payloads", len(leaks))
    if leaks:
        report.notes.append(f"leaked: {leaks[:5]}")
    for (exp, got), k in sorted(confusion.items()):
        if exp != got:
            report.notes.append(f"confused {exp} -> {got}: {k}")
    return report
