"""Extract a supplier invoice: the header in one call, the line items in one call per page.

The header call sees the document text without the item table and returns value + quote + page
per field, grounded to a block as for claims. The line calls see the rebuilt item cells
(ingest/tables.py) as "#N [header] text" and return the values of each item as printed; every
value is grounded to the cells of its own item, so its box is the exact cell it came from.
Normalization reads Slovak and Czech numbers (invoice_values); checks run in validation.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from claimpilot_core.invoice_values import normalize_invoice
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.pii.guard import fold
from claimpilot_core.schemas.invoices import InvoiceHeader, InvoiceLines, ItemValues, line_guide
from claimpilot_core.schemas.parsing import FracBox, ParsedDocument, TableCell
from claimpilot_worker.extraction.extract import Field, flatten, ground, score_confidence
from claimpilot_worker.extraction.schema import grounded_schema, schema_guide

# Company data the checks need stays readable; people's names, e-mails and phones do not.
KEEP_ENTITIES = frozenset({"IBAN", "ADDRESS"})


class InvoiceKind(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    PROFORMA = "proforma"


KIND_RULES = [  # (kind, title words); the first that matches wins
    (InvoiceKind.CREDIT_NOTE, ("dobropis", "opravná faktúra", "opravný daňový doklad",
                               "credit note", "opravný daňový", "opravní daňový doklad")),
    (InvoiceKind.PROFORMA, ("zálohová faktúra", "zálohová faktura", "proforma",
                            "nie je daňový doklad", "není daňový doklad")),
]  # fmt: skip


def invoice_kind(text: str) -> InvoiceKind:
    """Rules only: the title says it. A tax invoice is the default."""
    low = " ".join(text.lower().split())
    for kind, words in KIND_RULES:
        if any(w in low for w in words):
            return kind
    return InvoiceKind.INVOICE


# --- normalization: claimpilot_core.invoice_values.normalize_invoice (the api uses it too) ---


PAGE_NOTE = re.compile(
    r"(?:strana|page:?)\s*1\s*(?:z|/|of)\s*(\d+)|strana\s*1\s*dokladu\s*\S+", re.IGNORECASE
)


def page_note(parsed: ParsedDocument) -> Field | None:
    """The page counter on page 1 ("strana 1 z 9"), found by a rule: a model reads it badly and
    it decides whether pages are missing."""
    for b in parsed.blocks:
        if b.page != 1 or b.hidden:
            continue
        m = PAGE_NOTE.search(b.text.replace(" | ", " "))
        if m:
            f = Field("page_note", m.group(0), b.text, 1, bbox=b.bbox, grounded=True)
            f.value_norm = m.group(0)
            f.confidence = score_confidence(f)
            return f
    return None


# --- inputs -----------------------------------------------------------------------------------


@dataclass
class Item:
    n: int  # 1-based, over the whole document
    page: int
    cells: list[TableCell]


def items_of(cells: list[TableCell]) -> list[Item]:
    by_key: dict[tuple[int, int], list[TableCell]] = defaultdict(list)
    for c in cells:
        by_key[(c.table, c.item)].append(c)
    out = []
    for n, key in enumerate(sorted(by_key), start=1):
        group = sorted(by_key[key], key=lambda c: (c.line, c.col))
        out.append(Item(n, group[0].page, group))
    return out


def items_text(items: list[Item], redacted: dict[int, str] | None = None) -> str:
    """'#N' then one line per visual line: [header] text | [header] text."""
    out = []
    for it in items:
        out.append(f"#{it.n}")
        lines: dict[int, list[str]] = defaultdict(list)
        for c in it.cells:
            text = (redacted or {}).get(id(c), c.text)
            lines[c.line].append(f"[{c.header}] {text}")
        out += ["  " + " | ".join(parts) for _, parts in sorted(lines.items())]
    return "\n".join(out)


def _item_band(cells: list[TableCell]) -> dict[int, tuple[float, float]]:
    """Per page, the vertical band the item cells take."""
    band: dict[int, tuple[float, float]] = {}
    for c in cells:
        lo, hi = band.get(c.page, (1.0, 0.0))
        band[c.page] = (min(lo, c.bbox.y0), max(hi, c.bbox.y1))
    return band


def header_text(parsed: ParsedDocument, redacted: dict[int, str]) -> str:
    """The document without its item table: page-marked, hidden text left out."""
    band = _item_band(parsed.cells)
    out, page = [], None
    for b in parsed.blocks:
        if b.hidden:
            continue
        lo, hi = band.get(b.page, (1.0, 0.0))
        centre = (b.bbox.y0 + b.bbox.y1) / 2
        if lo <= centre <= hi:
            continue
        if b.page != page:
            page = b.page
            out.append(f"=== Page {page} ===")
        out.append(redacted.get(b.seq, b.text))
    return "\n".join(out)


# --- results ----------------------------------------------------------------------------------


@dataclass
class LineResult:
    n: int
    fields: dict[str, Field] = field(default_factory=dict)  # "line_net", "batches[0].batch"


@dataclass
class InvoiceExtraction:
    kind: InvoiceKind
    header: list[Field]
    lines: list[LineResult]
    items_expected: int
    prompt_tags: list[str]
    models: list[str]
    raw: dict[str, Any] = field(default_factory=dict)

    def header_value(self, name: str) -> str | None:
        return next((f.value_norm for f in self.header if f.name == name), None)


def _squash(text: str) -> str:
    return "".join(fold(text).split())


def ground_in_item(
    value: str, item: Item, redacted: dict[int, str]
) -> tuple[bool, int, FracBox | None]:
    """The cells of this item that hold the value; their box is the value's box."""
    target = _squash(value)
    hits = [c for c in item.cells if target and target in _squash(redacted.get(id(c), c.text))]
    if not hits:
        return False, item.page, None
    box = hits[0].bbox
    for c in hits[1:]:
        if c.page == hits[0].page:
            box = box.union(c.bbox)
    return True, hits[0].page, box


async def extract_invoice(
    parsed: ParsedDocument,
    redacted: dict[int, str],
    gateway: LLMGateway,
    *,
    redacted_cells: dict[int, str] | None = None,
) -> InvoiceExtraction:
    """`redacted`: block seq -> redacted text; `redacted_cells`: id(cell) -> redacted text."""
    parsed = parsed.visible()
    kind = invoice_kind(" ".join(redacted.get(b.seq, b.text) for b in parsed.blocks if b.page == 1))
    tags, models = [], []

    gen = await gateway.generate_json(
        "invoice_header",
        "invoice_extraction/header",
        grounded_schema(InvoiceHeader),
        {"fields": schema_guide(InvoiceHeader), "document": header_text(parsed, redacted)},
    )
    tags.append(gen.prompt_tag or "")
    models.append(gen.spec.key)
    raw: dict[str, Any] = {"header": gen.value.model_dump()}
    header = flatten(raw["header"])
    for f in header:
        f.grounded, f.bbox = ground(f.quote, f.value_raw, f.page, parsed, redacted)
        f.value_norm = normalize_invoice(f.name, f.value_raw)
        f.confidence = score_confidence(f)
    if (note := page_note(parsed)) is not None:
        header.append(note)

    items = items_of(parsed.cells)
    by_n = {it.n: it for it in items}
    results: dict[int, LineResult] = {}
    raw["lines"] = []
    for chunk in _chunks(items):
        gen_lines = await gateway.generate_json(
            "invoice_lines",
            "invoice_extraction/lines",
            InvoiceLines,
            {"fields": line_guide(), "items": items_text(chunk, redacted_cells)},
        )
        tags.append(gen_lines.prompt_tag or "")
        models.append(gen_lines.spec.key)
        allowed = {it.n for it in chunk}
        for answer in gen_lines.value.items:
            raw["lines"].append(answer.model_dump())
            if answer.item not in allowed or answer.item in results:
                continue  # an item the model invented, or one from another call
            results[answer.item] = _line_result(answer, by_n[answer.item], redacted_cells or {})
    # Every item on the page becomes a line, answered or not; what the export needs and the model
    # did not give stays as an empty field, which validation flags and a handler fills in.
    for it in items:
        lr = results.setdefault(it.n, LineResult(it.n))
        for name in REQUIRED_LINE_FIELDS:
            lr.fields.setdefault(name, Field(name, None, None, it.page))
    return InvoiceExtraction(
        kind,
        header,
        [results[n] for n in sorted(results)],
        len(items),
        sorted(set(tags)),
        sorted(set(models)),
        raw,
    )


CHUNK_ITEMS = 12
REQUIRED_LINE_FIELDS = ("quantity", "line_net")


def _chunks(items: list[Item]) -> list[list[Item]]:
    """Items of one page per call, at most CHUNK_ITEMS at a time."""
    out: list[list[Item]] = []
    for it in items:
        if out and out[-1][-1].page == it.page and len(out[-1]) < CHUNK_ITEMS:
            out[-1].append(it)
        else:
            out.append([it])
    return out


# A batch row printed without labels: "2L58861 11/28", on scans with the batch quantity after it.
# The model tends to shift such a pair (the expiry lands in batch), so a rule reads it.
BATCH_ROW = re.compile(
    r"^(?=\S*\d)(?=\S*[A-Z])([A-Z0-9]{5,12}) (\d{2}/\d{2}(?:\d{2})?)(?: [\d.,]+)?$"
)


def printed_batches(item: Item) -> list[tuple[str, str, list[TableCell]]]:
    """(batch, expiry, cells) for each unlabelled batch row of the item, in print order."""
    rows: dict[tuple[int, int], list[TableCell]] = defaultdict(list)
    for c in item.cells:
        if c.line > 0:
            rows[(c.page, c.line)].append(c)
    out = []
    for key in sorted(rows):
        cells = sorted(rows[key], key=lambda c: c.col)
        if m := BATCH_ROW.match(" ".join(c.text.strip() for c in cells)):
            out.append((m[1], m[2], cells))
    return out


def _line_result(answer: ItemValues, item: Item, redacted_cells: dict[int, str]) -> LineResult:
    out = _model_line_result(answer, item, redacted_cells)
    printed = printed_batches(item)
    if not printed:
        return out
    taken = {v for batch, expiry, _ in printed for v in (batch, expiry, f"{batch} {expiry}")}
    for name, f in list(out.fields.items()):
        is_batch = name.startswith("batches[") and not name.endswith("quantity")
        # The model also files a batch under a neighbouring column ("ŠUKL kód").
        if is_batch or (not name.startswith("batches[") and f.value_raw in taken):
            del out.fields[name]
    for i, (batch, expiry, cells) in enumerate(printed):
        box = cells[0].bbox
        for c in cells[1:]:
            box = box.union(c.bbox)
        for leaf, value in (("batch", batch), ("expiry", expiry)):
            name = f"batches[{i}].{leaf}"
            f = Field(name, value, None, cells[0].page, box, grounded=True)
            f.value_norm = normalize_invoice(name, value)
            f.confidence = score_confidence(f)
            out.fields[name] = f
    return out


def _model_line_result(
    answer: ItemValues, item: Item, redacted_cells: dict[int, str]
) -> LineResult:
    out = LineResult(answer.item)
    batch = -1  # index of the batch row being filled
    for cv in answer.values:
        if cv.field in ("batch", "expiry", "batch_quantity"):
            leaf = "quantity" if cv.field == "batch_quantity" else cv.field
            # "batch" opens a row; an expiry or quantity opens one when none is open, or when
            # the open row has it already.
            if cv.field == "batch" or batch < 0 or f"batches[{batch}].{leaf}" in out.fields:
                batch += 1
            name = f"batches[{batch}].{leaf}"
        else:
            name = cv.field
            if name in out.fields:
                continue  # the first value of a field counts
        f = Field(name, cv.value, None, item.page)
        f.grounded, f.page, f.bbox = ground_in_item(cv.value, item, redacted_cells)
        f.value_norm = normalize_invoice(name, cv.value)
        f.confidence = score_confidence(f)
        out.fields[name] = f
    return out


@dataclass
class RedactedInvoice:
    blocks: dict[int, str]  # block seq -> redacted text
    cells: dict[int, str]  # id(cell) -> redacted text
    redactor: Any


COMPANY_FORM = re.compile(
    r"^\s*,?\s*(s\.\s?r\.\s?o|spol\.|a\.\s?s\.|k\.\s?s\.|v\.\s?o\.\s?s|gmbh|ltd|inc|s\.\s?a\.)",
    re.IGNORECASE,
)


UPPER = "A-ZÁÄČĎÉĚÍĹĽŇÓÔŘŔŠŤÚŮÝŽÖÜ"
NAME_WORD = rf"[{UPPER}][^\W\d_]+(?:-[{UPPER}][^\W\d_]+)?"
# The person who issued or handles the invoice, after its label. NER misses rare first names
# ("Belo Kríž"); the label is reason enough.
ISSUER_NAME = re.compile(
    r"(?i:vystavil|vyhotovil|vybavuje|kontaktn[áa] osoba|kontakt|contact person|issued by)a?"
    rf"\s*:\s*({NAME_WORD}(?: {NAME_WORD}){{1,2}})"
)


def company_aware_ner(text: str) -> list[Any]:
    """Names the NER model finds, plus names after an issuer label, minus those followed by a
    legal form: "Lekárne Sever s.r.o." is a company, and a company name is data the checks need."""
    from claimpilot_core.pii import guard

    spans = guard.transformer_ner(text)
    for m in ISSUER_NAME.finditer(text):
        if not any(s.start < m.end(1) and m.start(1) < s.end for s in spans):
            spans.append(guard.Span(m.start(1), m.end(1), "PERSON", m[1], 0.9, "label"))
    return [s for s in spans if not COMPANY_FORM.match(text[s.end :])]


def redact_invoice(parsed: ParsedDocument, *, ner: Any = company_aware_ner) -> RedactedInvoice:
    """People's names, e-mails and phones become tokens; company data stays (KEEP_ENTITIES).
    Names are looked for only outside the item table: product names ("France Lait") are not
    people, and a contact person found in the header is replaced wherever it appears. Patterned
    identifiers (e-mail, phone, birth number) are looked for everywhere."""
    from claimpilot_core.pii.guard import ClaimRedactor

    redactor = ClaimRedactor(ner, keep=KEEP_ENTITIES)
    band = _item_band(parsed.cells)

    def outside(b: Any) -> bool:
        lo, hi = band.get(b.page, (1.0, 0.0))
        return not lo <= (b.bbox.y0 + b.bbox.y1) / 2 <= hi

    redactor.observe(b.text for b in parsed.blocks if outside(b))
    # Inside the table, identifiers by pattern still count: a patient's phone in an item note.
    redactor.observe((b.text for b in parsed.blocks if not outside(b)), ner=False)
    redactor.observe((c.text for c in parsed.cells), ner=False)
    # A name that appears anywhere with a legal form is a company ("Lekárne Sever s.r.o." also
    # printed as "Lekárne Sever - sklad Senec"): it stays readable.
    text = " ".join(b.text.replace(" | ", " ") for b in parsed.blocks)
    redactor.entities = [
        e
        for e in redactor.entities
        if e.entity != "PERSON"
        or not re.search(re.escape(e.value) + COMPANY_FORM.pattern[1:], text, re.I)
    ]
    return RedactedInvoice(
        {b.seq: redactor.redact(b.text) for b in parsed.blocks},
        {id(c): redactor.redact(c.text) for c in parsed.cells},
        redactor,
    )
