"""Claim context shared by the routing, retrieval and coverage suites: extraction (replayed from
cassettes; scans through the vision model, as in the pipeline), DocInputs, policy register lookups,
delay hours."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from claimpilot_core.domain import Coverage, DocType, Product
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_evals.cache import page_image
from claimpilot_evals.dataset import GtClaim
from claimpilot_evals.suites.common import RedactedClaim, RunContext, redact_claim
from claimpilot_worker.extraction.extract import extract_document, extract_document_vision
from claimpilot_worker.ingest.doctype import classify
from claimpilot_worker.ingest.language import detect_language
from claimpilot_worker.routing.facts import DocInput


@dataclass
class ClaimCtx:
    gt: GtClaim
    rc: RedactedClaim
    docs: list[DocInput]
    mapping: dict[str, str]


async def load_claim(claim: GtClaim, ctx: RunContext) -> ClaimCtx:
    rc = redact_claim(claim)
    mapping = {t: v for t, (_, v) in rc.redactor.mapping().items()}
    vision = ctx.options.get("scan_path", get_settings().scan_path) == "vision"
    docs = []
    for doc in rc.docs:
        # As in the pipeline: the type comes from the classifier and the language from the text,
        # so typing errors flow into routing, coverage and injection metrics.
        typed = await classify(doc.text(redacted=True), ctx.gateway)
        doc_type = typed.doc_type
        if vision and any(b.ocr for b in doc.parsed.blocks):  # the pipeline's test for a scan
            ex = await extract_document_vision(
                doc_type,
                [page_image(doc.gt.path, p.page, doc.gt.data["sha256"]) for p in doc.parsed.pages],
                doc.parsed,
                doc.redacted,
                ctx.gateway,
                tokenize=rc.redactor.tokenize,
                mapping=mapping,
            )
        else:
            ex = await extract_document(
                doc_type,
                doc.parsed,
                doc.redacted,
                ctx.gateway,
                language=detect_language(doc.text(redacted=False)),
                mapping=mapping,
                exclude_example=doc.gt.item_id,
            )
        docs.append(DocInput(doc_type, ex, doc.gt.data["sha256"], doc.text(redacted=True)))
    return ClaimCtx(claim, rc, docs, mapping)


def register() -> dict[str, dict]:
    path = repo_root() / "data" / "synthetic" / "policies.json"
    return {p["policy_number"]: p for p in json.loads(path.read_text("utf-8"))}


def first(docs: list[DocInput], doc_type: DocType):
    return next((d.extraction for d in docs if d.doc_type is doc_type and d.extraction), None)


def product_of(docs: list[DocInput], reg: dict | None) -> Product | None:
    cert = first(docs, DocType.POLICY_CERTIFICATE)
    name = (cert.value("product_name") or "").lower() if cert else ""
    for p in Product:
        if p.value in name:
            return p
    return Product(reg["product"]) if reg else None


def _d(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def periods(
    docs: list[DocInput], reg: dict | None
) -> tuple[tuple[date, date] | None, tuple[date, date] | None]:
    cert = first(docs, DocType.POLICY_CERTIFICATE)
    start = _d(cert.value("policy_start")) if cert else None
    end = _d(cert.value("policy_end")) if cert else None
    if not (start and end) and reg:
        start, end = _d(reg["start"]), _d(reg["end"])
    form = first(docs, DocType.CLAIM_FORM)
    ts, te = (_d(form.value("trip_start")), _d(form.value("trip_end"))) if form else (None, None)
    return ((start, end) if start and end else None), ((ts, te) if ts and te else None)


def delay_hours(docs: list[DocInput]) -> int | None:
    pir = first(docs, DocType.PROPERTY_IRREGULARITY_REPORT)
    if not pir or not pir.value("arrival_time") or not pir.value("delivery_time"):
        return None
    try:
        a = datetime.fromisoformat(pir.value("arrival_time") or "")
        b = datetime.fromisoformat(pir.value("delivery_time") or "")
    except ValueError:
        return None
    return int((b - a).total_seconds() // 3600)


def prior_paid(reg: dict | None) -> dict[Coverage, Decimal]:
    if not reg:
        return {}
    return {Coverage(k): Decimal(v) for k, v in reg.get("prior_paid", {}).items()}
