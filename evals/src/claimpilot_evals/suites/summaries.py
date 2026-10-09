"""Summaries and letters: fact-consistency violations on every claim, judge scores on a sample."""

from decimal import Decimal

from pydantic import BaseModel, Field

from claimpilot_core.domain import Coverage, CoverageVerdict, DocType
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.policy import load_products
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_evals.report import ItemResult, Metric, Report
from claimpilot_evals.suites.claimctx import first, load_claim
from claimpilot_evals.suites.common import RunContext
from claimpilot_worker.coverage.payout import PayoutItem, compute_payout
from claimpilot_worker.summaries.write import DecisionFacts, write_all

JUDGE_SAMPLE = 10


class Scores(BaseModel):
    completeness: int = Field(ge=1, le=5)
    tone: int = Field(ge=1, le=5)
    no_overpromise: int = Field(ge=1, le=5)
    note: str


async def run(ctx: RunContext) -> Report:
    from datetime import date

    report = Report("summaries", ctx.split)
    fx = FxSnapshot.load(get_settings().config_dir / "fx_rates.yaml")
    catalog = load_products(repo_root() / "data" / "policies" / "products.yaml")
    judged: list[float] = []
    words_over = 0
    for n, claim in enumerate(
        c for c in ctx.claims() if c.data["expected"]["status"] != "NEEDS_INFO"
    ):
        c = await load_claim(claim, ctx)
        form = first(c.docs, DocType.CLAIM_FORM)
        gt_items = claim.data["items"]
        pay = compute_payout(
            catalog.product(claim.data["product"]),
            [
                PayoutItem(
                    i["ref"],
                    Coverage(i["coverage"]),
                    i["category"],
                    Decimal(i["amount"]),
                    i["currency"],
                    CoverageVerdict(i["verdict"]),
                    i["valuables"],
                )
                for i in gt_items
            ],
            fx,
            delay_hours=claim.data["facts"].get("delay_hours"),
        )
        facts = DecisionFacts(
            reference=claim.claim_id,
            product=catalog.product(claim.data["product"]).name,
            claim_type=claim.data["claim_type"],
            event_date=date.fromisoformat(claim.data["event_date"]),
            queue=claim.data["expected"]["queue"],
            items=[
                {
                    "description": g["description_sk"],
                    "amount": Decimal(g["amount"]),
                    "currency": g["currency"],
                    "verdict": g["verdict"],
                    "clauses": g["clause_ids"],
                    "payout": p.payout,
                }
                for g, p in zip(gt_items, pay.items, strict=True)
            ],
            total_payout=pay.total,
            deductible=pay.deductible,
            red_flags=[
                e
                for e in claim.data["edge_cases"]
                if e.startswith(("exclusion", "duplicate", "date_", "early"))
            ],
            missing=[],
            insured_token=(form.raw_value("insured_name") if form else None) or "<PERSON_1>",
        )
        texts = await write_all(facts, ctx.gateway)
        for t in texts:
            if t.kind == "handler" and len(t.text.split()) > 150:
                words_over += 1
            report.items.append(
                ItemResult(
                    f"{claim.claim_id}/{t.kind}",
                    not t.violations,
                    [],
                    [v.__dict__ for v in t.violations],
                    ["fact_violations"],
                    {"text": t.text[:600], "words": len(t.text.split())},
                )
            )
            if n < JUDGE_SAMPLE:
                gen = await ctx.gateway.generate_json(
                    "judge",
                    "summaries/judge",
                    Scores,
                    {
                        "facts": facts.as_prompt_json(),
                        "kind": t.kind,
                        "language": t.language,
                        "text": t.text,
                    },
                )
                s = gen.value
                judged.append((s.completeness + s.tone + s.no_overpromise) / 3)
                report.items[-1].detail["judge"] = s.model_dump()
    rows = [i for i in report.items if "fact_violations" in i.tags]
    report.count("fact_violations", sum(len(i.got) for i in rows))
    report.ratio("texts_without_violations", sum(i.ok for i in rows), len(rows))
    report.metrics["judge_score"] = Metric(
        round(sum(judged) / len(judged), 2) if judged else 0.0, len(judged), 0
    )
    report.count("handler_summaries_over_150_words", words_over)
    return report
