"""Coverage retrieval: recall@5 and MRR of the ground-truth clause ids, per claimed item.

Queries use the ground-truth coverage and category (oracle mapping), so this measures retrieval
alone. Items decided by code (A3.2, A3.3, A13.4) and NEEDS_INFO claims are not retrieval items.
Options: rerank=off, mode=vector|fts|hybrid.
"""

from claimpilot_core.db.session import session_scope
from claimpilot_core.settings import repo_root
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.claimctx import load_claim
from claimpilot_evals.suites.common import RunContext
from claimpilot_worker.coverage.decide import evidence
from claimpilot_worker.coverage.index import build_index
from claimpilot_worker.coverage.retrieve import hybrid

CODE_DECIDED = {"A3.2", "A3.3", "A13.4", "A13.3"}


async def run(ctx: RunContext) -> Report:
    report = Report("retrieval", ctx.split)
    rerank = ctx.options.get("rerank", "on") != "off"
    async with session_scope() as session:
        n = await build_index(
            session, repo_root() / "data" / "policies" / "vpp_cp_2026.pdf", ctx.gateway
        )
    report.notes.append(f"index: {n} clauses")
    rr_sum = 0.0
    for claim in ctx.claims():
        if claim.data["expected"]["status"] == "NEEDS_INFO":
            continue
        c = await load_claim(claim, ctx)
        ev = evidence(c.docs)
        for item in claim.data["items"]:
            gold = [x for x in item["clause_ids"] if x not in CODE_DECIDED]
            if not gold:
                continue
            query = f"{item['coverage']} {item['category']}: {item['description_sk']}\n{ev[:1200]}"
            async with session_scope() as session:
                hits = await hybrid(session, ctx.gateway, query, k=5, rerank=rerank)
            got = [h.clause_id for h in hits]
            ok = all(g in got for g in gold)
            ranks = [got.index(g) + 1 for g in gold if g in got]
            rr_sum += 1.0 / min(ranks) if ranks else 0.0
            report.items.append(
                ItemResult(
                    f"{claim.claim_id}/{item['ref']}",
                    ok,
                    gold,
                    got,
                    ["recall_at_5"],
                    {
                        "coverage": item["coverage"],
                        "verdict": item["verdict"],
                        "exclusion": item["exclusion"],
                    },
                )
            )
    k = len(report.items)
    report.ratio("recall_at_5", sum(i.ok for i in report.items), k)
    report.metrics["mrr"] = _metric(rr_sum / k if k else 0.0, k)
    excl = [i for i in report.items if i.detail["exclusion"]]
    report.ratio("recall_at_5_exclusions", sum(i.ok for i in excl), len(excl))
    return report


def _metric(value: float, n: int):
    from claimpilot_evals.report import Metric

    return Metric(value, n, 0)
