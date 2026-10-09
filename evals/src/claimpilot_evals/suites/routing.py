"""Routing: queue accuracy, fraud recall and a cost-weighted score, claim by claim.

Claims run in manifest order so the duplicate check sees earlier submissions, as in production.
Extraction replays from cassettes (run the extraction suite first, or use --fast).
"""

from decimal import Decimal

from claimpilot_core.domain import DocType
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.settings import get_settings
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext, redact_claim
from claimpilot_worker.extraction.extract import extract_document
from claimpilot_worker.routing.facts import DocInput, History, build_facts, remember
from claimpilot_worker.routing.route import route

# Cost of sending a claim of the expected queue (row) to the predicted queue (column).
COST = {
    "fraud_review": {
        "fraud_review": 0,
        "senior": 3,
        "standard": 8,
        "fast_track": 10,
        "NEEDS_INFO": 5,
    },
    "senior": {"fraud_review": 1, "senior": 0, "standard": 3, "fast_track": 6, "NEEDS_INFO": 2},
    "standard": {"fraud_review": 1, "senior": 1, "standard": 0, "fast_track": 3, "NEEDS_INFO": 1},
    "fast_track": {"fraud_review": 1, "senior": 1, "standard": 1, "fast_track": 0, "NEEDS_INFO": 1},
    "NEEDS_INFO": {"fraud_review": 2, "senior": 2, "standard": 3, "fast_track": 5, "NEEDS_INFO": 0},
}


def _policy_issue_dates() -> dict[str, str]:
    import json

    path = get_settings().config_dir.parent / "data" / "synthetic" / "policies.json"
    return {p["policy_number"]: p["issue_date"] for p in json.loads(path.read_text("utf-8"))}


async def run(ctx: RunContext) -> Report:
    from datetime import date

    report = Report("routing", ctx.split)
    fx = FxSnapshot.load(get_settings().config_dir / "fx_rates.yaml")
    history = History()
    register = _policy_issue_dates()
    total_cost = 0
    for claim in ctx.claims():
        rc = redact_claim(claim)
        mapping = {t: v for t, (_, v) in rc.redactor.mapping().items()}
        docs = []
        for doc in rc.docs:
            doc_type = DocType(doc.gt.doc_type)
            ex = await extract_document(
                doc_type,
                doc.parsed,
                doc.redacted,
                ctx.gateway,
                language=doc.gt.data["language"],
                mapping=mapping,
                exclude_example=doc.gt.item_id,
            )
            docs.append(DocInput(doc_type, ex, doc.gt.data["sha256"], doc.text(redacted=True)))
        policy_number = next(
            (
                d.extraction.value("policy_number")
                for d in docs
                if d.doc_type is DocType.CLAIM_FORM and d.extraction
            ),
            None,
        )
        issue = register.get(policy_number or "")
        facts = build_facts(
            docs,
            fx,
            history,
            claim_id=claim.claim_id,
            policy_issue_date=date.fromisoformat(issue) if issue else None,
        )
        remember(docs, history, claim.claim_id)
        decision = await route(facts, docs, ctx.gateway)
        got = decision.result.queue.value if decision.result.queue else "NEEDS_INFO"
        exp = claim.data["expected"]
        expected = exp["queue"] or "NEEDS_INFO"
        ok = got == expected
        cost = COST[expected][got]
        total_cost += cost
        tags = ["accuracy"] + (["fraud_recall"] if expected == "fraud_review" else [])
        report.items.append(
            ItemResult(
                claim.claim_id,
                ok,
                f"{expected} ({exp['rule']})",
                f"{got} ({decision.result.rule})",
                tags,
                {
                    "llm_used": decision.llm_used,
                    "cost": cost,
                    "hits": [h.rule for h in decision.result.hits],
                    "rationale": decision.rationale[:300],
                    "total_eur": str(facts.claimed_total_eur),
                    "archetype": claim.data["archetype"],
                },
            )
        )
    n = len(report.items)
    report.ratio("accuracy", sum(i.ok for i in report.items), n)
    fraud = [i for i in report.items if "fraud_recall" in i.tags]
    report.ratio("fraud_recall", sum(i.ok for i in fraud), len(fraud))
    report.ratio(
        "rule_agreement",
        sum(1 for i in report.items if i.expected.split(" ")[1] == i.got.split(" ")[1]),
        n,
    )
    report.count("cost", total_cost)
    report.ratio("llm_used", sum(i.detail["llm_used"] for i in report.items), n)
    exp_fast = [i for i in report.items if i.expected.startswith("fast_track")]
    report.ratio(
        "fast_track_recall", sum(i.got.startswith("fast_track") for i in exp_fast), len(exp_fast)
    )
    _ = Decimal
    return report
