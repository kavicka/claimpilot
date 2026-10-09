"""Parsed-document cache keyed by file hash, so eval runs do not re-run Docling and OCR."""

import hashlib
from pathlib import Path

from claimpilot_core.schemas.parsing import ParsedDocument
from claimpilot_core.settings import repo_root

CACHE_DIR = repo_root() / "data" / "cache" / "parsed"


def parsed(path: Path, sha: str | None = None) -> ParsedDocument:
    """Parsed text of a file. With `sha` (from ground truth) the file itself is only needed on a
    cache miss, so CI runs on the committed cache without the generated PDFs."""
    sha = sha or hashlib.sha256(path.read_bytes()).hexdigest()
    target = CACHE_DIR / f"{sha}.json"
    if target.exists():
        return ParsedDocument.model_validate_json(target.read_text("utf-8"))
    from claimpilot_worker.ingest.parser import parse  # heavy import only when needed

    doc = parse(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc.model_dump_json(), "utf-8")
    return doc
