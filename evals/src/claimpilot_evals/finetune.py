"""Training data for the invoice extraction adapter (ADR-014).

Each example is one model call as the pipeline makes it: the rendered prompt (header, or one
chunk of line items) and the answer it should have given, from ground truth. Only the train
split is used; dev and test stay unseen, so the eval gate measures what the adapter learned.
An invoice whose rebuilt items do not line up one to one with its ground-truth lines is left
out: an example with a wrong answer teaches the wrong thing.

Handler corrections join the same format: the stored prompt inputs of a corrected, approved
invoice and its final values (`corrections_examples`).
"""

import asyncio
import json
import random
import re
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from claimpilot_core.llm.prompts import load_prompt
from claimpilot_core.schemas.invoices import InvoiceHeader, line_guide
from claimpilot_core.schemas.parsing import ParsedDocument
from claimpilot_evals.invoice_data import GtInvoice, invoices, parsed_invoice
from claimpilot_worker.extraction.invoice import (
    _chunks,
    header_text,
    items_of,
    items_text,
    redact_invoice,
)
from claimpilot_worker.extraction.schema import schema_guide

HEADER_KEYS = [k for k in InvoiceHeader.model_fields if k not in ("recap", "fees")]


def _messages(prompt_id: str, variables: dict[str, Any], answer: dict[str, Any]) -> dict:
    prompt = load_prompt(prompt_id)
    messages = [{"role": m.role, "content": m.content} for m in prompt.render(**variables)]
    messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    return {"messages": messages, "prompt": prompt.tag}


def header_answer(gt: dict[str, Any]) -> dict[str, Any]:
    empty = {"value": None, "quote": None, "page": None}
    out: dict[str, Any] = {k: dict(empty) for k in HEADER_KEYS}
    for k, v in gt["header"].items():
        if k in out and v.get("page"):
            out[k] = {"value": v["printed"], "quote": v["printed"], "page": v["page"]}
    out["recap"] = [
        {"rate": r["rate"]["printed"], "base": r["base"]["printed"], "vat": r["vat"]["printed"],
         "quote": None, "page": r["page"]}
        for r in gt["recap"] if r.get("page")
    ]  # fmt: skip
    out["fees"] = [
        {
            "label": f["label"]["printed"],
            "net": f["net"]["printed"],
            "quote": None,
            "page": f["page"],
        }
        for f in gt["fees"]
        if f.get("page") and not f["included"]
    ]
    return out


def line_values(line: dict[str, Any]) -> list[dict[str, str]]:
    values = [{"field": k, "value": v["printed"]} for k, v in line["cells"].items()]
    batches = line.get("batches", [])
    for b in batches:
        values.append({"field": "batch", "value": b["batch"]["printed"]})
        values.append({"field": "expiry", "value": b["expiry"]["printed"]})
        if len(batches) > 1:
            values.append({"field": "batch_quantity", "value": b["quantity"]["printed"]})
    return values


Stored = tuple[str | None, str | None, int | None]  # value, quote, page of a stored field


def header_from_fields(fields: dict[str, Stored]) -> dict[str, Any]:
    """The header answer from an invoice's stored (corrected) fields."""
    empty = {"value": None, "quote": None, "page": None}
    out: dict[str, Any] = {k: dict(empty) for k in HEADER_KEYS}
    rows: dict[str, dict[int, dict[str, Any]]] = {"recap": {}, "fees": {}}
    for name, (value, quote, page) in fields.items():
        if m := re.fullmatch(r"(recap|fees)\[(\d+)\]\.(\w+)", name):
            row = rows[m[1]].setdefault(int(m[2]), {"quote": None, "page": page})
            row[m[3]] = value
        elif name in out and value is not None:
            out[name] = {"value": value, "quote": quote, "page": page}
    keys = {"recap": ("rate", "base", "vat"), "fees": ("label", "net")}
    for kind, by_n in rows.items():
        out[kind] = [
            {**{k: row.get(k) for k in keys[kind]}, "quote": None, "page": row["page"]}
            for _, row in sorted(by_n.items())
        ]
    return out


def lines_from_fields(values: dict[str, str | None]) -> dict[int, list[dict[str, str]]]:
    """Per item number, the (field, value) pairs of the line answer, batches last."""
    plain: dict[int, list[dict[str, str]]] = {}
    batches: dict[int, dict[int, dict[str, str]]] = {}
    for name, value in values.items():
        m = re.fullmatch(r"lines\[(\d+)\]\.(.+)", name)
        if not m:
            continue
        n = int(m[1])
        plain.setdefault(n, [])
        if value is None:
            continue
        if b := re.fullmatch(r"batches\[(\d+)\]\.(\w+)", m[2]):
            batches.setdefault(n, {}).setdefault(int(b[1]), {})[b[2]] = value
        else:
            plain[n].append({"field": m[2], "value": value})
    for n, rows in batches.items():
        for _, row in sorted(rows.items()):
            for leaf, field in (("batch", "batch"), ("expiry", "expiry")):
                if leaf in row:
                    plain[n].append({"field": field, "value": row[leaf]})
            if len(rows) > 1 and "quantity" in row:
                plain[n].append({"field": "batch_quantity", "value": row["quantity"]})
    return plain


def examples_for(gt: dict[str, Any], parsed: ParsedDocument) -> list[dict]:
    """The calls of one invoice with their right answers; [] when its items do not line up."""
    present = [ln for ln in gt["lines"] if ln.get("page") is not None]
    items = items_of(parsed.cells)
    if len(items) != len(present):
        return []
    red = redact_invoice(parsed)
    out = [
        _messages(
            "invoice_extraction/header",
            {"fields": schema_guide(InvoiceHeader), "document": header_text(parsed, red.blocks)},
            header_answer(gt),
        )
    ]
    for chunk in _chunks(items):
        answer = {
            "items": [{"item": it.n, "values": line_values(present[it.n - 1])} for it in chunk]
        }
        out.append(
            _messages(
                "invoice_extraction/lines",
                {"fields": line_guide(), "items": items_text(chunk, red.cells)},
                answer,
            )
        )
    return out


def _grounded(value: str | None, text: str) -> bool:
    """A corrected value is trained on only when the prompt holds it: a value typed in by a
    handler that is not on the page (or that the vault would have tokenized) is left out."""
    from claimpilot_worker.extraction.invoice import _squash

    return value is not None and _squash(value) in text


async def corrections_examples() -> list[dict]:
    """Calls of approved invoices that a handler corrected, with the corrected values as the
    answers. Prompts are rebuilt from the stored redacted text, exactly as extraction saw it."""
    from sqlalchemy import select

    from claimpilot_core.db.models import Correction, Document, ExtractedField, Invoice
    from claimpilot_core.db.session import session_scope
    from claimpilot_worker.extraction.invoice import _squash
    from claimpilot_worker.steps.invoice import load_parsed

    out: list[dict] = []
    async with session_scope() as s:
        corrected = select(ExtractedField.case_id).join(
            Correction, Correction.field_id == ExtractedField.id
        )
        invoices = (
            await s.scalars(
                select(Invoice).where(
                    Invoice.id.in_(corrected), Invoice.status.in_(["APPROVED", "EXPORTED"])
                )
            )
        ).all()
        for inv in invoices:
            doc = (await s.scalars(select(Document).where(Document.case_id == inv.id))).first()
            if doc is None:
                continue
            parsed, blocks, pairs = await load_parsed(s, doc)
            if any(b.text_redacted is None for b in blocks) or any(
                row.text_redacted is None for _, row in pairs
            ):
                continue  # never train on text without its redacted form
            parsed = parsed.visible()
            red_blocks = {b.seq: b.text_redacted or "" for b in blocks}
            red_cells = {id(tc): row.text_redacted or "" for tc, row in pairs}
            rows = (
                await s.scalars(select(ExtractedField).where(ExtractedField.case_id == inv.id))
            ).all()
            document = header_text(parsed, red_blocks)
            seen = _squash(document)
            header = header_from_fields(
                {r.field: (r.value_raw, r.source_quote, r.page) for r in rows
                 if not r.field.startswith("lines[")}
            )  # fmt: skip
            for k, v in header.items():
                if isinstance(v, dict) and not _grounded(v["value"], seen):
                    header[k] = {"value": None, "quote": None, "page": None}
            for kind in ("recap", "fees"):
                header[kind] = [
                    r for r in header[kind]
                    if all(_grounded(v, seen) for k, v in r.items() if k not in ("quote", "page"))
                ]  # fmt: skip
            out.append(
                _messages(
                    "invoice_extraction/header",
                    {"fields": schema_guide(InvoiceHeader), "document": document},
                    header,
                )
            )
            lines = lines_from_fields({r.field: r.value_raw for r in rows})
            for chunk in _chunks(items_of(parsed.cells)):
                text = items_text(chunk, red_cells)
                seen_items = _squash(text)
                answer = {
                    "items": [
                        {
                            "item": it.n,
                            "values": [
                                v for v in lines.get(it.n, []) if _grounded(v["value"], seen_items)
                            ],
                        }
                        for it in chunk
                    ]
                }
                out.append(
                    _messages(
                        "invoice_extraction/lines", {"fields": line_guide(), "items": text}, answer
                    )
                )
    return out


def build_dataset(
    out: Path,
    *,
    split: str = "train",
    valid_share: float = 0.1,
    seed: int = 7,
    limit: int | None = None,
    corrections: bool = True,
) -> dict:
    """train.jsonl and valid.jsonl for `mlx_lm.lora`, split by invoice so that the calls of one
    invoice never sit on both sides."""
    gts: list[GtInvoice] = invoices(split, limit)
    rng = random.Random(seed)
    rng.shuffle(gts)
    n_valid = max(1, int(len(gts) * valid_share))
    stats: dict[str, Any] = {"invoices": 0, "skipped": 0, "train": 0, "valid": 0}
    out.mkdir(parents=True, exist_ok=True)
    with (
        (out / "train.jsonl").open("w", encoding="utf-8") as train,
        (out / "valid.jsonl").open("w", encoding="utf-8") as valid,
    ):
        for i, g in enumerate(gts):
            # Train invoices are parsed fresh, not cached: the committed cache holds dev and test.
            examples = examples_for(g.data, parsed_invoice(g.path, g.data["sha256"], cache=False))
            if not examples:
                stats["skipped"] += 1
                continue
            stats["invoices"] += 1
            target, key = (valid, "valid") if i < n_valid else (train, "train")
            for ex in examples:
                target.write(json.dumps({"messages": ex["messages"]}, ensure_ascii=False) + "\n")
                stats[key] += 1
        if corrections:
            try:
                extra = asyncio.run(corrections_examples())
            except (OSError, SQLAlchemyError) as exc:  # no database: synthetic data only
                stats["corrections"] = f"skipped ({type(exc).__name__})"
            else:
                stats["corrections"] = len(extra)
                for ex in extra:  # all to the train side: dev and test stay synthetic
                    train.write(json.dumps({"messages": ex["messages"]}, ensure_ascii=False) + "\n")
                    stats["train"] += 1
    (out / "stats.json").write_text(json.dumps(stats, indent=1), "utf-8")
    return stats
