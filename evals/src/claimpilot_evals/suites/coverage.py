"""Coverage decision end to end: Step A mapping, prechecks, retrieval, Step B verdicts, payout.

Per item: verdict and deciding clause against ground truth (items align by claim-form row order).
Per claim: payout exact match to the cent. NEEDS_INFO claims are not assessed.
"""

from decimal import Decimal

from claimpilot_core.db.session import session_scope
from claimpilot_core.domain import DocType
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.policy import load_products
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.claimctx import (
    _d,
    delay_hours,
    first,
    load_claim,
    periods,
    prior_paid,
    product_of,
    register,
)
from claimpilot_evals.suites.common import RunContext
from claimpilot_worker.context import issued_on
from claimpilot_worker.coverage.decide import decide_coverage
from claimpilot_worker.coverage.index import build_index
from claimpilot_worker.coverage.retrieve import hybrid
from claimpilot_worker.routing.facts import History, claim_type_of, remember


async def run(ctx: RunContext) -> Report:
    report = Report("coverage", ctx.split)
    fx = FxSnapshot.load(get_settings().config_dir / "fx_rates.yaml")
    catalog = load_products(repo_root() / "data" / "policies" / "products.yaml")
    reg_all = register()
    history = History()
    async with session_scope() as session:
        await build_index(
            session, repo_root() / "data" / "policies" / "vpp_cp_2026.pdf", ctx.gateway
        )

    async def retrieve(query: str):
        async with session_scope() as session:
            return await hybrid(session, ctx.gateway, query, k=5)

    for claim in ctx.claims():
        c = await load_claim(claim, ctx)
        form = first(c.docs, DocType.CLAIM_FORM)
        policy_number = form.value("policy_number") if form else None
        reg = reg_all.get(policy_number or "")
        dup = any(
            d.sha256 in history.files for d in c.docs if d.doc_type is DocType.MEDICAL_INVOICE
        ) or any(
            (d.extraction.value("invoice_number") or "").upper() in history.invoices
            for d in c.docs
            if d.doc_type is DocType.MEDICAL_INVOICE and d.extraction
        )
        remember(c.docs, history, claim.claim_id)
        if claim.data["expected"]["status"] == "NEEDS_INFO":
            continue
        policy, trip = periods(c.docs, reg)

        event = _d(form.value("event_date")) if form else None
        outcome = await decide_coverage(
            c.docs,
            claim_type=claim_type_of(c.docs),
            product=product_of(c.docs, reg),
            catalog=catalog,
            fx=fx,
            gateway=ctx.gateway,
            retrieve=retrieve,
            event=event,
            policy=policy,
            trip=trip,
            duplicate=dup,
            prior_paid=prior_paid(reg),
            delay_hours=delay_hours(c.docs),
            issued=issued_on(c.docs, reg),
        )
        gt_items = claim.data["items"]
        # Items align by claim-form row order; a missing or extra item counts as a failure.
        for n in range(max(len(gt_items), len(outcome.items))):
            gt = gt_items[n] if n < len(gt_items) else None
            it = outcome.items[n] if n < len(outcome.items) else None
            verdict_ok = bool(gt and it and it.verdict and it.verdict.value == gt["verdict"])
            clause_ok = bool(gt and it and set(gt["clause_ids"]) & set(it.clause_ids))
            ref = gt["ref"] if gt else f"extra-{n + 1}"
            report.items.append(
                ItemResult(
                    f"{claim.claim_id}/{ref}",
                    verdict_ok and clause_ok,
                    f"{gt['verdict']} {gt['clause_ids']}" if gt else None,
                    f"{it.verdict.value if it and it.verdict else None} "
                    f"{it.clause_ids if it else []}",
                    ["verdict_accuracy"],
                    {
                        "verdict_ok": verdict_ok,
                        "clause_ok": clause_ok,
                        "method": it.method if it else "missing",
                        "mapped": (
                            f"{it.coverage.value if it and it.coverage else None}/"
                            f"{it.category if it else None}"
                        ),
                        "expected_map": f"{gt['coverage']}/{gt['category']}" if gt else None,
                        "retrieved": it.retrieved if it else [],
                        "rationale": it.rationale[:200] if it else "",
                        "archetype": claim.data["archetype"],
                    },
                )
            )
        expected = Decimal(claim.data["expected"]["total_payout_eur"])
        got = outcome.payout.total if outcome.payout else None
        report.items.append(
            ItemResult(
                f"{claim.claim_id}/payout",
                got == expected,
                str(expected),
                str(got),
                ["payout_exact_match"],
                {"archetype": claim.data["archetype"]},
            )
        )
    rows = [i for i in report.items if "verdict_accuracy" in i.tags]
    report.ratio("verdict_accuracy", sum(i.ok for i in rows), len(rows))
    report.ratio("verdict_only", sum(i.detail["verdict_ok"] for i in rows), len(rows))
    report.ratio("clause_match", sum(i.detail["clause_ok"] for i in rows), len(rows))
    pays = [i for i in report.items if "payout_exact_match" in i.tags]
    report.ratio("payout_exact_match", sum(i.ok for i in pays), len(pays))
    return report
