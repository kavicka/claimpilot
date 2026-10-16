"""Synthetic invoices for the evals: ground truth from data/synthetic/invoices and a parse cache
with the rebuilt item tables (data/cache/parsed-invoices), so runs skip Docling and OCR."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claimpilot_core.schemas.parsing import ParsedDocument
from claimpilot_core.settings import repo_root

ROOT = repo_root() / "data" / "synthetic" / "invoices"
CACHE_DIR = repo_root() / "data" / "cache" / "parsed-invoices"


@dataclass
class GtInvoice:
    data: dict[str, Any]
    path: Path

    @property
    def id(self) -> str:
        return self.data["invoice_id"]


def invoices(split: str, limit: int | None = None, root: Path = ROOT) -> list[GtInvoice]:
    manifest = json.loads((root / f"manifest-{split}.json").read_text("utf-8"))
    out = []
    for row in manifest["invoices"][:limit]:
        folder = root / split / row["invoice_id"]
        data = json.loads((folder / "ground_truth.json").read_text("utf-8"))
        out.append(GtInvoice(data, folder / data["file"]))
    return out


def parsed_invoice(path: Path, sha: str | None = None, *, cache: bool = True) -> ParsedDocument:
    """Parsed invoice with its item cells. With `sha`, the PDF is only needed on a cache miss."""
    sha = sha or hashlib.sha256(path.read_bytes()).hexdigest()
    target = CACHE_DIR / f"{sha}.json"
    if cache and target.exists():
        return ParsedDocument.model_validate_json(target.read_text("utf-8"))
    from claimpilot_worker.ingest.parser import parse

    doc = parse(path, tables=True)
    if cache:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.model_dump_json(), "utf-8")
    return doc
