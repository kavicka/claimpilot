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
from claimpilot_core.fields import normalize
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.llm.untrusted import neutralize
from claimpilot_core.pii.guard import TOKEN_RE, fold
from claimpilot_core.schemas.parsing import FracBox, ParsedDocument
from claimpilot_core.settings import get_settings
from claimpilot_worker.extraction.checks import run_checks
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
    """The visible blocks with page markers; text that imitates our markup is neutralized."""
    parts, page = [], 0
    for b in parsed.blocks:
        if b.hidden:
            continue
        if b.page != page:
            page = b.page
            parts.append(f"=== Page {page} ===")
        parts.append(neutralize(redacted.get(b.seq, b.text)))
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


def _squash(text: str) -> str:
    # OCR drops or adds spaces ("21.7.2026" for "21. 7. 2026"); every other character counts.
    return "".join(fold(text).split())


def check_as_printed(
    fields: list["Field"], parsed: ParsedDocument, redacted: dict[int, str]
) -> None:
    """Values are copied as printed, so a grounded value must appear in the document's text
    character for character (case, diacritics and spaces aside). Grounding is fuzzy and goes by
    the quote: it finds the right line even when the value lost a character, as when a vision
    model read "R-2026 36818" off a printed "R-2026-36818". A value that fails this check keeps
    its field out of straight-through processing."""
    text = _squash(" ".join(redacted.get(b.seq, b.text) for b in parsed.blocks))
    for f in fields:
        if f.grounded and f.value_raw and not f.value_raw.startswith("["):
            f.checks["as_printed"] = _squash(f.value_raw) in text


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
    parsed = parsed.visible()  # hidden text is neither model input nor a grounding target
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
    check_as_printed(fields, parsed, redacted)
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
    masked: bool = False,
) -> Extraction:
    """Scans and photos read by a vision model. Unmasked images hold personal data, so they go to
    local models only (ADR-003). A cloud model gets masked images (ingest/mask.py) together with
    the redacted OCR text, where personal values are tokens (ADR-010). Returned values are
    tokenized with the claim's redactor before anything else sees them."""
    parsed = parsed.visible()
    spec = gateway.spec_for("extraction_vision")
    if spec.provider != "ollama" and not masked:
        raise PermissionError("page images with personal data may only go to a local model")
    variables: dict[str, Any] = {
        "doc_type": DOC_TYPE_LABELS[doc_type],
        "fields": field_guide(doc_type),
        "pages": len(images_b64),
    }
    if masked:
        variables["text"] = page_marked_text(parsed, redacted)
    gen = await gateway.generate_json(
        "extraction_vision",
        "extraction/vision_masked" if masked else "extraction/vision",
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
    check_as_printed(fields, parsed, redacted)
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
