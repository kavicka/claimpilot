"""APPROVED -> SUBMITTED: map the approved decision, submit it, recover from 422 errors."""

from typing import Any

from sqlalchemy import select

from claimpilot_core.db.models import AuditLog, Claim, CoverageDecision
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import ClaimType, Coverage, DocType, PipelineStep
from claimpilot_core.normalize import parse_country
from claimpilot_core.pii.vault import Vault
from claimpilot_worker.context import first, load_docs, to_date
from claimpilot_worker.pipeline import register
from claimpilot_worker.submission.core_client import CoreClient
from claimpilot_worker.submission.submit import map_payload, submit


class SubmissionNeedsHandlerError(RuntimeError):
    pass


@register(S.APPROVED, PipelineStep.SUBMIT)
async def submit_claim(session, claim: Claim, ctx: dict[str, Any]) -> S:
    docs = [s.doc for s in await load_docs(session, claim.id)]
    form = first(docs, DocType.CLAIM_FORM)
    items = (
        await session.scalars(
            select(CoverageDecision)
            .where(CoverageDecision.claim_id == claim.id)
            .order_by(CoverageDecision.id)
        )
    ).all()
    mapping = await Vault(ctx["settings"].pii_vault_key.get_secret_value()).load(session, claim.id)
    from claimpilot_core.fx import default_fx

    fx = default_fx(ctx["settings"].config_dir)
    payload, missing = map_payload(
        policy_number=claim.policy_id,
        claim_type=ClaimType(claim.claim_type) if claim.claim_type else None,
        insured_token=form.raw_value("insured_name") if form else None,
        birth_number_token=form.raw_value("insured_birth_number") if form else None,
        iban_token=form.raw_value("iban") if form else None,
        event_date=to_date(form.value("event_date")) if form else None,
        event_country=parse_country(form.value("destination_country")) if form else None,
        items=[
            {
                "ref": i.item_ref,
                "coverage": Coverage(i.coverage) if i.coverage else Coverage.MEDICAL,
                "claimed_eur": fx.to_eur(i.claimed_amount, i.claimed_currency)
                if i.claimed_amount is not None and i.claimed_currency in fx.rates
                else None,
                "payout_eur": i.payout_eur,
                "clauses": i.clause_ids,
            }
            for i in items
        ],
        handler_id="handler",
    )
    core = CoreClient(ctx["settings"].core_mock_url)
    try:
        result = await submit(
            payload,
            missing,
            mapping=mapping,
            core=core,
            gateway=ctx["gateway"],
            idempotency_key=str(claim.id),
        )
    finally:
        await core.aclose()
    session.add(
        AuditLog(
            claim_id=claim.id,
            action="submission",
            details={
                "status": result.status,
                "core_claim_id": result.core_claim_id,
                "submissions": result.submissions,
                "agent": result.used_agent,
                "fields": result.fields,
            },
        )
    )
    if result.status != "registered":
        raise SubmissionNeedsHandlerError(
            f"core system needs: {', '.join(result.fields) or result.status}"
        )
    claim.core_claim_id = result.core_claim_id
    return S.SUBMITTED
