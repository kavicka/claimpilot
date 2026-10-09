"""Extract one document: context assembly, the model call, grounding, normalization, checks.

The model sees only this document's redacted pages, the field list, and examples of the same type
and language. Each value comes back with the quote it was read from; the quote is matched to a
parsed block to get its bounding box. A value whose quote matches nothing is ungrounded, and its
confidence is capped: that is the hallucination detector.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from claimpilot_core.domain import DocType, ExtractionMethod
from claimpilot_core.fields import kind_of, normalize
from claimpilot_core.identifiers import is_valid_iban, parse_rodne_cislo
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.normalize import parse_amount
from claimpilot_core.pii.guard import TOKEN_RE, fold, rehydrate
from claimpilot_core.schemas.parsing import FracBox, ParsedDocument
from claimpilot_core.settings import get_settings
from claimpilot_worker.extraction.schema import field_guide, grounded_model

GROUNDING_MIN = 85
DOC_TYPE_LABELS = {
    DocType.CLAIM_FORM: "claim form (hlásenie poistnej udalosti), Slovak",
    DocType.POLICY_CERTIFICATE: "insurance policy certificate, Slovak",
    DocType.MEDICAL_REPORT: "medical report from a clinic or hospital",
    DocType.MEDICAL_INVOICE: "invoice from a clinic or hospital",
    DocType.PHARMACY_RECEIPT: "receipt from a pharmacy, drugstore or shop",
    DocType.PROPERTY_IRREGULARITY_REPORT: "airline Property Irregularity Report",
    DocType.POLICE_REPORT: "police theft report",
    DocType.BOOKING_CONFIRMATION: "travel agency booking and cancellation confirmation",
}


@dataclass
class Field:
    name: str  # "total", "line_items[2].amount"
    value_raw: str | None
    quote: str | None
    page: int | None
    bbox: FracBox | None = None
    grounded: bool = False
    value_norm: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class Extraction:
    doc_type: DocType
    fields: list[Field]
    raw: dict[str, Any]
    prompt_tag: str | None
    model: str
    method: ExtractionMethod = ExtractionMethod.LLM_TEXT
    attempts: int = 1

    def get(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    def value(self, name: str) -> str | None:
        f = self.get(name)
        return f.value_norm if f else None

    def raw_value(self, name: str) -> str | None:
        f = self.get(name)
        return f.value_raw if f else None


# --- context ------------------------------------------------------------------------------


def page_marked_text(parsed: ParsedDocument, redacted: dict[int, str]) -> str:
    parts, page = [], 0
    for b in parsed.blocks:
        if b.page != page:
            page = b.page
            parts.append(f"=== Page {page} ===")
        parts.append(redacted.get(b.seq, b.text))
    return "\n".join(parts)


@lru_cache(maxsize=64)
def _examples_file(path: Path, mtime: float) -> list[dict]:
    return json.loads(path.read_text("utf-8"))


def load_examples(doc_type: DocType, language: str, *, exclude: str | None = None) -> list[dict]:
    """Examples of the same type and language; any language of the type as a fallback."""
    folder = get_settings().prompts_dir / "extraction" / "examples"
    path = folder / f"{doc_type.value}-{language}.json"
    if not path.exists():
        options = sorted(folder.glob(f"{doc_type.value}-*.json"))
        if not options:
            return []
        path = options[0]
    examples = _examples_file(path, path.stat().st_mtime)
    return [e for e in examples if e["source"] != exclude]


# --- grounding ----------------------------------------------------------------------------


def ground(
    quote: str | None,
    value: str | None,
    page: int | None,
    parsed: ParsedDocument,
    redacted: dict[int, str],
) -> tuple[bool, FracBox | None]:
    needle = quote or value
    if not needle:
        return False, None
    target = fold(needle)
    best, best_box = 0.0, None
    for pass_page in ([page] if page else []) + [None]:
        for b in parsed.blocks:
            if pass_page is not None and b.page != pass_page:
                continue
            text = fold(redacted.get(b.seq, b.text))
            score = 100.0 if target in text else fuzz.partial_ratio(target, text)
            if score > best:
                best, best_box = score, b.bbox
        if best >= GROUNDING_MIN:
            break
    return best >= GROUNDING_MIN, best_box if best >= GROUNDING_MIN else None


# --- flatten ------------------------------------------------------------------------------


def flatten(raw: dict[str, Any]) -> list[Field]:
    out: list[Field] = []
    for name, v in raw.items():
        if isinstance(v, list):
            for i, row in enumerate(v):
                for k, val in row.items():
                    if k in ("quote", "page"):
                        continue
                    out.append(Field(f"{name}[{i}].{k}", val, row.get("quote"), row.get("page")))
        elif isinstance(v, dict) and "values" in v:
            joined = json.dumps(v["values"], ensure_ascii=False) if v["values"] else None
            out.append(Field(name, joined, v.get("quote"), v.get("page")))
        elif isinstance(v, dict):
            out.append(Field(name, v.get("value"), v.get("quote"), v.get("page")))
    return out


# --- checks and confidence ----------------------------------------------------------------


def run_checks(doc_type: DocType, fields: list[Field], mapping: dict[str, str]) -> None:
    by_name = {f.name: f for f in fields}
    for f in fields:
        if f.value_raw is None:
            continue
        kind = kind_of(f.name)
        if kind != "text":
            f.checks["parses"] = f.value_norm is not None
    if doc_type in (DocType.MEDICAL_INVOICE, DocType.PHARMACY_RECEIPT):
        total = by_name.get("total")
        lines = [
            f for f in fields if f.name.startswith("line_items[") and f.name.endswith(".amount")
        ]
        if total and total.value_norm and lines:
            amounts = [parse_amount(f.value_norm) for f in lines]
            if all(a is not None for a in amounts):
                ok = (
                    abs(
                        sum(a for a in amounts if a is not None)
                        - (parse_amount(total.value_norm) or 0)
                    )
                    <= 0.01
                )
                total.checks["total_matches_lines"] = ok
                for f in lines:
                    f.checks["total_matches_lines"] = ok
    if doc_type is DocType.CLAIM_FORM:
        if (f := by_name.get("iban")) and f.value_raw:
            f.checks["iban_checksum"] = is_valid_iban(rehydrate(f.value_raw, mapping))
        if (f := by_name.get("insured_birth_number")) and f.value_raw:
            f.checks["birth_number_valid"] = (
                parse_rodne_cislo(rehydrate(f.value_raw, mapping)) is not None
            )
    for a, b in [
        ("trip_start", "trip_end"),
        ("policy_start", "policy_end"),
        ("service_date", "issue_date"),
        ("visit_date", "discharge_date"),
        ("arrival_time", "delivery_time"),
    ]:
        fa, fb = by_name.get(a), by_name.get(b)
        if fa and fb and fa.value_norm and fb.value_norm:
            ok = fa.value_norm[:10] <= fb.value_norm[:10]
            fa.checks["date_order"] = ok
            fb.checks["date_order"] = ok


def score_confidence(f: Field) -> float:
    """Rule-based: grounding and passing checks raise it; an ungrounded value is capped."""
    if f.value_raw is None:
        return 0.0
    conf = 0.55
    if f.grounded:
        conf += 0.25
    if f.checks:
        conf += 0.15 if all(f.checks.values()) else -0.25
    else:
        conf += 0.1
    if not f.grounded:
        conf = min(conf, 0.45)
    return round(max(0.0, min(conf, 0.99)), 2)


# --- the step -----------------------------------------------------------------------------


async def extract_document(
    doc_type: DocType,
    parsed: ParsedDocument,
    redacted: dict[int, str],
    gateway: LLMGateway,
    *,
    language: str,
    mapping: dict[str, str] | None = None,
    exclude_example: str | None = None,
    country_hint: str | None = None,
) -> Extraction:
    examples = load_examples(doc_type, language, exclude=exclude_example)
    variables = {
        "doc_type": DOC_TYPE_LABELS[doc_type],
        "fields": field_guide(doc_type),
        "examples": [
            {"text": e["text"], "output": json.dumps(e["output"], ensure_ascii=False)}
            for e in examples
        ],
        "document": page_marked_text(parsed, redacted),
    }
    gen = await gateway.generate_json(
        "extraction", "extraction/document", grounded_model(doc_type), variables
    )
    raw = gen.value.model_dump()
    fields = flatten(raw)
    country = country_hint
    if country is None:
        for name in ("provider_country", "facility_country"):
            f = next((x for x in fields if x.name == name), None)
            if f and f.value_raw:
                country = normalize(name, f.value_raw)
    for f in fields:
        f.grounded, f.bbox = ground(f.quote, f.value_raw, f.page, parsed, redacted)
        f.value_norm = normalize(f.name, f.value_raw, country=country)
    run_checks(doc_type, fields, mapping or {})
    for f in fields:
        f.confidence = score_confidence(f)
    return Extraction(doc_type, fields, raw, gen.prompt_tag, gen.spec.key, attempts=gen.attempts)


def has_tokens(value: str | None) -> bool:
    return bool(value and TOKEN_RE.search(value))


async def extract_document_vision(
    doc_type: DocType,
    images_b64: list[str],
    parsed: ParsedDocument,
    redacted: dict[int, str],
    gateway: LLMGateway,
    *,
    tokenize,
    mapping: dict[str, str] | None = None,
) -> Extraction:
    """Scans and photos read by the local vision model. The images hold unredacted personal data,
    so this path is allowed only for local providers (ADR-003); returned values are tokenized with
    the claim's redactor before anything else sees them."""
    spec = gateway.spec_for("extraction_vision")
    if spec.provider != "ollama":
        raise PermissionError("page images with personal data may only go to a local model")
    variables = {
        "doc_type": DOC_TYPE_LABELS[doc_type],
        "fields": field_guide(doc_type),
        "pages": len(images_b64),
    }
    gen = await gateway.generate_json(
        "extraction_vision",
        "extraction/vision",
        grounded_model(doc_type),
        variables,
        images=images_b64,
    )
    raw = gen.value.model_dump()
    fields = flatten(raw)
    for f in fields:
        if f.value_raw:
            f.value_raw = tokenize(f.value_raw)
        if f.quote:
            f.quote = tokenize(f.quote)
    country = None
    for name in ("provider_country", "facility_country"):
        f = next((x for x in fields if x.name == name), None)
        if f and f.value_raw:
            country = normalize(name, f.value_raw)
    for f in fields:
        f.grounded, f.bbox = ground(f.quote, f.value_raw, f.page, parsed, redacted)
        f.value_norm = normalize(f.name, f.value_raw, country=country)
    run_checks(doc_type, fields, mapping or {})
    for f in fields:
        f.confidence = score_confidence(f)
    return Extraction(
        doc_type,
        fields,
        raw,
        gen.prompt_tag,
        gen.spec.key,
        ExtractionMethod.LLM_VISION,
        gen.attempts,
    )
