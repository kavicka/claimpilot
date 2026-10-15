"""Before and after masking, side by side, for one synthetic scan: what a cloud model would see.

    uv run python scripts/demo/mask_preview.py S42-021/D3 docs/demo/masking.png

Needs the generated PDFs (make data). The masking is the pipeline's own (ingest/mask.py).
"""

import base64
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from claimpilot_evals.cache import page_image
from claimpilot_evals.dataset import Dataset
from claimpilot_evals.suites.common import redact_claim
from claimpilot_worker.ingest.mask import has_personal_data, mask_pages


def main(item_id: str, out: Path) -> None:
    scenario = item_id.split("/")[0]
    claim = next(c for c in Dataset().claims("dev") if c.claim_id == scenario)
    rc = redact_claim(claim)
    doc = next(d for d in rc.docs if d.gt.item_id == item_id)
    images = [page_image(doc.gt.path, p.page, doc.gt.data["sha256"]) for p in doc.parsed.pages]
    masked, report = mask_pages(images, doc.parsed, has_personal_data(rc.redactor))
    if masked is None:
        sys.exit(f"not sent: {report.refused}")
    before = Image.open(io.BytesIO(base64.b64decode(images[0]))).convert("RGB")
    after = Image.open(io.BytesIO(base64.b64decode(masked[0]))).convert("RGB")
    gap, label = 24, 36
    canvas = Image.new("RGB", (before.width * 2 + gap, before.height + label), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), f"{item_id}: page as uploaded", fill="black")
    draw.text(
        (before.width + gap + 8, 8),
        f"what a cloud model sees ({report.masked_blocks} blocks, "
        f"{report.unread_lines} unread lines masked)",
        fill="black",
    )
    canvas.paste(before, (0, label))
    canvas.paste(after, (before.width + gap, label))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, optimize=True)
    print(out, report)


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
