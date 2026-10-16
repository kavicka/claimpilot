"""Training data for the invoice extraction adapter (ADR-014).

Each example is one model call as the pipeline makes it: the rendered prompt (header, or one
chunk of line items) and the answer it should have given, from ground truth. Only the train
split is used; dev and test stay unseen, so the eval gate measures what the adapter learned.
An invoice whose rebuilt items do not line up one to one with its ground-truth lines is left
out: an example with a wrong answer teaches the wrong thing.

Handler corrections join the same format: the stored prompt inputs of a corrected, approved
invoice and its final values (`corrections_examples`).
"""

import json
import random
from pathlib import Path
from typing import Any

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


def build_dataset(
    out: Path,
    *,
    split: str = "train",
    valid_share: float = 0.1,
    seed: int = 7,
    limit: int | None = None,
) -> dict:
    """train.jsonl and valid.jsonl for `mlx_lm.lora`, split by invoice so that the calls of one
    invoice never sit on both sides."""
    gts: list[GtInvoice] = invoices(split, limit)
    rng = random.Random(seed)
    rng.shuffle(gts)
    n_valid = max(1, int(len(gts) * valid_share))
    stats = {"invoices": 0, "skipped": 0, "train": 0, "valid": 0}
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
    (out / "stats.json").write_text(json.dumps(stats, indent=1), "utf-8")
    return stats
