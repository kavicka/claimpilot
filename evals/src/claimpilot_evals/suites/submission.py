"""Submission: first-try success on clean payloads, recovery on perturbed ones, invented values.

Decisions come from ground truth (oracle), so this measures mapping and the agent, not coverage.
core_mock runs in-process. Perturbed runs break code-list values the way an upstream change would
("AUT" instead of "AT", "medical" instead of "MED"); the agent must fix them from the code lists.
"""

import os
import random
from decimal import Decimal

import httpx

from claimpilot_core.domain import ClaimType, Coverage, CoverageVerdict, DocType
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.normalize import parse_country
from claimpilot_core.policy import load_products
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.claimctx import first, load_claim
from claimpilot_evals.suites.common import RunContext
from claimpilot_worker.coverage.payout import PayoutItem, compute_payout
from claimpilot_worker.submission.core_client import CoreClient
from claimpilot_worker.submission.submit import map_payload, submit

ALPHA3 = {
    "AT": "AUT",
    "DE": "DEU",
    "CH": "CHE",
    "IT": "ITA",
    "HR": "HRV",
    "ES": "ESP",
    "GR": "GRC",
    "CZ": "CZE",
    "HU": "HUN",
    "TR": "TUR",
    "US": "USA",
}
CLAIM_TYPES = {
    "medical": ClaimType.MEDICAL,
    "accident": ClaimType.ACCIDENT,
    "luggage": ClaimType.LUGGAGE,
    "cancellation": ClaimType.CANCELLATION,
}
LONG_NAMES = {
    "MED": "medical",
    "ACC": "accident",
    "LUG": "luggage",
    "DLY": "delay",
    "CXL": "cancellation",
}


def perturb(payload: dict, rng: random.Random) -> dict:
    p = {**payload, "items": [dict(i) for i in payload["items"]]}
    choice = rng.choice(["country", "claim_type", "coverage"])
    if choice == "country" and p["event_country"] in ALPHA3:
        p["event_country"] = ALPHA3[p["event_country"]]
    elif choice == "claim_type":
        p["claim_type_code"] = LONG_NAMES.get(p["claim_type_code"], p["claim_type_code"])
    else:
        p["items"][0]["coverage_code"] = LONG_NAMES.get(p["items"][0]["coverage_code"], "x")
    return p


def invented(original: dict, final: dict | None) -> list[str]:
    """Fields whose final value is neither the mapper's value nor a code for the same thing."""
    if final is None:
        return []
    bad = []
    for key in ("policy_number", "event_date", "iban", "currency", "total_payout", "handler_id"):
        if final.get(key) != original.get(key):
            bad.append(key)
    if final.get("insured") != original.get("insured"):
        bad.append("insured")
    ok_country = {original["event_country"], ALPHA3.get(original["event_country"])}
    if final.get("event_country") not in ok_country:
        bad.append("event_country")
    for o, f in zip(original["items"], final.get("items", []), strict=False):
        for key in ("claimed_eur", "payout_eur", "decision", "clause_refs"):
            if o.get(key) != f.get(key):
                bad.append(f"items.{o['ref']}.{key}")
    if len(final.get("items", [])) != len(original["items"]):
        bad.append("items")
    return bad


async def run(ctx: RunContext) -> Report:
    report = Report("submission", ctx.split)
    os.environ.setdefault(
        "CORE_MOCK_POLICIES", str(repo_root() / "data" / "synthetic" / "policies.json")
    )
    os.environ.setdefault(
        "CORE_MOCK_PRODUCTS", str(repo_root() / "data" / "policies" / "products.yaml")
    )
    from claimpilot_core_mock import main as core_app

    core_app.STORE.clear()
    core = CoreClient("http://core.test", transport=httpx.ASGITransport(app=core_app.app))
    fx = FxSnapshot.load(get_settings().config_dir / "fx_rates.yaml")
    catalog = load_products(repo_root() / "data" / "policies" / "products.yaml")
    rng = random.Random(7)
    for claim in ctx.claims():
        if claim.data["expected"]["status"] == "NEEDS_INFO":
            continue
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
        from datetime import date

        items = [
            {
                "ref": p.ref,
                "coverage": p.coverage,
                "claimed_eur": p.amount_eur,
                "payout_eur": p.payout,
                "clauses": g["clause_ids"],
            }
            for p, g in zip(pay.items, gt_items, strict=True)
        ]
        val = form.value if form else (lambda _n: None)
        payload, missing = map_payload(
            policy_number=val("policy_number"),
            claim_type=CLAIM_TYPES.get(claim.data["claim_type"]),
            insured_token=form.raw_value("insured_name") if form else None,
            birth_number_token=form.raw_value("insured_birth_number") if form else None,
            iban_token=form.raw_value("iban") if form else None,
            event_date=date.fromisoformat(claim.data["event_date"]),
            event_country=parse_country(val("destination_country")),
            items=items,
            handler_id="handler.eval",
        )
        for variant in ("clean", "perturbed"):
            body = payload if variant == "clean" else perturb(payload, rng)
            result = await submit(
                body,
                missing,
                mapping=c.mapping,
                core=core,
                gateway=ctx.gateway,
                idempotency_key=f"{claim.claim_id}-{variant}",
            )
            inv = invented(payload, result.final_payload)
            report.items.append(
                ItemResult(
                    f"{claim.claim_id}/{variant}",
                    result.status == "registered" and not inv,
                    "registered",
                    result.status,
                    [f"{variant}_success"],
                    {
                        "submissions": result.submissions,
                        "first_try": result.first_try,
                        "agent": result.used_agent,
                        "invented": inv,
                        "fields": result.fields,
                        "errors": result.errors[:2],
                    },
                )
            )
    clean = [i for i in report.items if i.id.endswith("/clean")]
    pert = [i for i in report.items if i.id.endswith("/perturbed")]
    report.ratio("first_try_success", sum(i.detail["first_try"] for i in clean), len(clean))
    report.ratio("after_retry_success", sum(i.ok for i in pert), len(pert))
    report.count("invented_values", sum(len(i.detail["invented"]) for i in report.items))
    report.ratio("agent_used_on_perturbed", sum(i.detail["agent"] for i in pert), len(pert))
    await core.aclose()
    return report
