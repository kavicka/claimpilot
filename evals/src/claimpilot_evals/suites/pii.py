"""PII guard: recall per entity type on every ground-truth value printed in the documents.

A value counts as present when the parsed text contains it (fuzzy, so OCR noise still counts) and
as redacted when the redacted text no longer does. Values the parser never saw are reported apart.
"""

from rapidfuzz import fuzz

from claimpilot_core.pii.guard import fold
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext, redact_claim

IDENTIFIERS = {"BIRTH_NUMBER", "IBAN", "PHONE", "EMAIL", "ID_CARD", "LICENCE_PLATE"}
FUZZY_MIN = 90


def _present(value: str, text: str) -> bool:
    v, t = fold(value), fold(text)
    if v in t:
        return True
    return len(v) >= 6 and fuzz.partial_ratio(v, t) >= FUZZY_MIN


async def run(ctx: RunContext) -> Report:
    report = Report("pii", ctx.split)
    over_redactions = 0
    unseen = 0
    for claim in ctx.claims():
        rc = redact_claim(claim)

        def key(v: str) -> str:
            return fold(v).replace(" ", "")

        gt_values = {key(v) for _, v in claim.pii_values()}
        redacted_all = "\n".join(d.text(redacted=True) for d in rc.docs)
        for e in rc.redactor.entities:
            if e.token not in redacted_all:
                continue  # registered (e.g. a birth date from a birth number) but replaced nothing
            forms = {key(v) for v in e.variants} | {key(e.value)}
            if not any(f in g or g in f for f in forms for g in gt_values):
                over_redactions += 1
                report.items.append(
                    ItemResult(
                        f"{claim.claim_id}/over/{e.token}",
                        True,
                        None,
                        e.value,
                        ["over_redaction"],
                        {"entity": e.entity},
                    )
                )
        for doc in rc.docs:
            original = doc.text(redacted=False)
            redacted = doc.text(redacted=True)
            for p in doc.gt.data["pii"]:
                entity, value = p["type"], p["value"]
                if not _present(value, original):
                    unseen += 1
                    continue
                ok = not _present(value, redacted)
                tag = (
                    "recall_names"
                    if entity == "PERSON"
                    else "recall_birth_dates"
                    if entity == "BIRTH_DATE"
                    else ("recall_identifiers" if entity in IDENTIFIERS else "recall_address")
                )
                report.items.append(
                    ItemResult(
                        f"{doc.gt.item_id}/{entity}/{value}",
                        ok,
                        "redacted",
                        "redacted" if ok else "leaked",
                        [tag],
                        {"entity": entity, "scan": doc.gt.data["scan"]},
                    )
                )
    for tag in ("recall_identifiers", "recall_names", "recall_address", "recall_birth_dates"):
        rows = [i for i in report.items if tag in i.tags]
        report.ratio(tag, sum(i.ok for i in rows), len(rows))
    leaked = [i for i in report.items if not i.ok and "over_redaction" not in i.tags]
    report.count("leaked_values", len(leaked))
    report.count("over_redactions", over_redactions)
    report.notes.append(
        f"{unseen} ground-truth values were not in the parsed text (OCR, layout); not scored"
    )
    by_entity: dict[str, list[bool]] = {}
    for i in report.items:
        if "over_redaction" not in i.tags:
            by_entity.setdefault(i.detail["entity"], []).append(i.ok)
    for ent, oks in sorted(by_entity.items()):
        report.notes.append(f"{ent}: {sum(oks)}/{len(oks)} redacted")
    return report
