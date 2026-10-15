"""Load every model the worker uses once, so they land in the image at build time.

The ECS task has no route to the internet (infra/terraform/network.tf) and runs with
HF_HUB_OFFLINE=1, so a model that is not in the image fails the first claim that needs it.
Run by the worker Dockerfile; `claimpilot-prefetch --check` repeats the loads offline.
"""

import os
import sys
import tempfile
from pathlib import Path


def _tiny_pdf(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rechnung Nr. RE-2026-1 Betrag EUR 10,00")
    doc.save(path)


def main() -> None:
    if "--check" in sys.argv:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from PIL import Image

    from claimpilot_core.pii.guard import transformer_ner
    from claimpilot_worker.coverage.retrieve import _reranker
    from claimpilot_worker.ingest.mask import detect_text_lines
    from claimpilot_worker.ingest.parser import parse

    print("ner", transformer_ner("Jana Kováčová, Bratislava"))
    print("reranker", _reranker().predict([("zuby", "ošetrenie zubov")]).tolist())
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "tiny.pdf"
        _tiny_pdf(pdf)
        print("docling", [b.text for b in parse(pdf).blocks])
    print("text detector", len(detect_text_lines(Image.new("RGB", (64, 64), "white"))))


if __name__ == "__main__":
    main()
