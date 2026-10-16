"""Parsed-document cache keyed by file hash, so eval runs do not re-run Docling and OCR; and an
index of page-image hashes, so the vision path replays without the page files."""

import hashlib
import json
from pathlib import Path

from claimpilot_core.schemas.parsing import ParsedDocument
from claimpilot_core.settings import repo_root

CACHE_DIR = repo_root() / "data" / "cache" / "parsed"
PAGE_INDEX = repo_root() / "data" / "cache" / "page_images.json"


def parsed(path: Path, sha: str | None = None) -> ParsedDocument:
    """Parsed text of a file. With `sha` (from ground truth) the file itself is only needed on a
    cache miss, so CI runs on the committed cache without the generated PDFs."""
    sha = sha or hashlib.sha256(path.read_bytes()).hexdigest()
    target = CACHE_DIR / f"{sha}.json"
    if target.exists():
        doc = ParsedDocument.model_validate_json(target.read_text("utf-8"))
        if path.exists():  # entries from before hidden-text marking; marking twice is a no-op
            from claimpilot_worker.ingest.hidden_text import hidden_spans, mark_hidden

            doc = mark_hidden(doc, hidden_spans(path))
        return doc
    from claimpilot_worker.ingest.parser import parse  # heavy import only when needed

    doc = parse(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc.model_dump_json(), "utf-8")
    return doc


def page_image(path: Path, page: int, sha: str) -> str:
    """The page as base64 PNG for the vision model when the file is here; otherwise a
    "sha256:<hex>" reference from the committed index, which only a cassette replay can serve."""
    from claimpilot_core.llm.cassette import IMAGE_REF, image_digest
    from claimpilot_worker.ingest.renders import page_png_b64

    index = json.loads(PAGE_INDEX.read_text("utf-8")) if PAGE_INDEX.exists() else {}
    key = f"{sha}:{page}"
    if not path.exists():
        if key not in index:
            raise FileNotFoundError(f"{path.name} is missing and page {page} is not indexed")
        return IMAGE_REF + index[key]
    image = page_png_b64(path, page)
    if index.get(key) != image_digest(image):
        index[key] = image_digest(image)
        PAGE_INDEX.write_text(json.dumps(index, indent=0, sort_keys=True), "utf-8")
    return image


def reparse() -> int:
    """Parse every document of the synthetic and adversarial datasets again and overwrite its
    cache entry. Run after a parser change; needs the generated PDFs."""
    from claimpilot_evals.dataset import Dataset

    done: set[str] = set()
    for root in (repo_root() / "data" / "synthetic", repo_root() / "data" / "adversarial"):
        for manifest in sorted(root.glob("manifest-*.json")):
            split = manifest.stem.removeprefix("manifest-")
            for claim in Dataset(root).claims(split):
                for d in claim.docs:
                    sha = d.data["sha256"]
                    if sha not in done:
                        (CACHE_DIR / f"{sha}.json").unlink(missing_ok=True)
                        parsed(d.path, sha)
                        done.add(sha)
    return len(done)
