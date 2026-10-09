"""Build the few-shot examples for extraction from the dev split.

    uv run claimpilot-eval fewshot

For each document type and language the dev split has, one or two clean (non-scanned) documents
become examples: their redacted text and the expected output built from ground truth, with PII
values replaced by the same tokens the redactor gives them. The examples are committed under
prompts/extraction/examples; the extraction suite leaves the source documents out of its metrics.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from claimpilot_core.pii.guard import fold
from claimpilot_core.settings import repo_root
from claimpilot_evals.dataset import Dataset
from claimpilot_evals.suites.common import RedactedDoc, redact_claim

EXAMPLES_DIR = repo_root() / "prompts" / "extraction" / "examples"
MAX_CHARS = 3200


def _quote_for(value: str | None, doc: RedactedDoc) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    fv = fold(value)
    for b in doc.parsed.blocks:
        red = doc.redacted[b.seq]
        if fv in fold(red):
            return red[:160], b.page
    return value, 1


def _tokenize(value: Any, redact) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_tokenize(v, redact) for v in value]
    return value


def expected_output(doc: RedactedDoc, redact) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, f in doc.gt.data["fields"].items():
        if isinstance(f, list):  # rows: line items, claimed items, insured persons, stolen items
            rows = []
            for row in f:
                entry = {k: _tokenize(v["printed"], redact) for k, v in row.items()}
                first = next((v for v in entry.values() if v), None)
                quote, page = _quote_for(first, doc)
                rows.append({**entry, "quote": quote, "page": page})
            out[name] = rows
        elif isinstance(f.get("printed"), list):
            values = _tokenize(f["printed"], redact)
            quote, page = _quote_for(values[0] if values else None, doc)
            out[name] = {"values": values, "quote": quote, "page": page}
        else:
            value = _tokenize(f["printed"], redact)
            quote, page = _quote_for(value[:60] if value else None, doc)
            out[name] = {"value": value, "quote": quote, "page": page}
    return out


def page_marked_text(doc: RedactedDoc) -> str:
    parts, page = [], 0
    for b in doc.parsed.blocks:
        if b.page != page:
            page = b.page
            parts.append(f"=== Page {page} ===")
        parts.append(doc.redacted[b.seq])
    return "\n".join(parts)


def build(dataset: Dataset | None = None) -> dict[str, list[dict]]:
    dataset = dataset or Dataset()
    candidates: dict[tuple[str, str], list[tuple[RedactedDoc, Any]]] = defaultdict(list)
    for claim in dataset.claims("dev"):
        if claim.data["duplicate_of"] or "prompt_injection" in claim.data["edge_cases"]:
            continue
        rc = redact_claim(claim)
        for doc in rc.docs:
            if doc.gt.data["scan"] or doc.gt.data["copy_of"]:
                continue
            candidates[(doc.gt.doc_type, doc.gt.data["language"])].append((doc, rc.redactor.redact))
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    written: dict[str, list[dict]] = {}
    for (doc_type, lang), docs in sorted(candidates.items()):
        # Shortest documents first: two examples when they fit the budget, otherwise one.
        docs.sort(key=lambda d: len(page_marked_text(d[0])))
        examples, used = [], 0
        for doc, redact in docs[:2]:
            text = page_marked_text(doc)
            if examples and used + len(text) > 2 * MAX_CHARS:
                break
            used += len(text)
            examples.append(
                {"source": doc.gt.item_id, "text": text, "output": expected_output(doc, redact)}
            )
        name = f"{doc_type}-{lang}"
        (EXAMPLES_DIR / f"{name}.json").write_text(
            json.dumps(examples, ensure_ascii=False, indent=1) + "\n", "utf-8"
        )
        written[name] = examples
    return written


def examples_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
