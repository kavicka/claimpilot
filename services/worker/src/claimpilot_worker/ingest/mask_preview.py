"""Masked copies of a document's page renders, for the review UI.

The handler can switch the document viewer to what a cloud model would receive (ADR-010): the same
`mask_pages` that guards the vision path runs over the cached renders and writes `m<n>.png` next to
`p<n>.png`, plus `mask.json` with the counts or the reason masking was refused. Nothing here goes to
a model. The files sit in the document's render directory, so erasure removes them with the renders.
"""

import base64
import json
from collections.abc import Callable
from pathlib import Path

from claimpilot_core.schemas.parsing import ParsedDocument
from claimpilot_worker.ingest.mask import MaskReport, TextFinder, detect_text_lines, mask_pages

MANIFEST = "mask.json"


def write_masked_renders(
    render_dir: Path,
    parsed: ParsedDocument,
    has_personal_data: Callable[[str], bool],
    find_text: TextFinder = detect_text_lines,
) -> MaskReport | None:
    """Write `m<n>.png` for every cached page render and `mask.json`; None without renders.

    Old masked pages go first, so a refusal never leaves a stale masked page behind.
    """
    pages = sorted(render_dir.glob("p*.png"), key=lambda p: int(p.stem[1:]))
    if not pages:
        return None
    for old in render_dir.glob("m*.png"):
        old.unlink()
    images = [base64.b64encode(p.read_bytes()).decode() for p in pages]
    masked, report = mask_pages(images, parsed, has_personal_data, find_text=find_text)
    if masked is not None:
        for n, image_b64 in enumerate(masked, start=1):
            (render_dir / f"m{n}.png").write_bytes(base64.b64decode(image_b64))
    (render_dir / MANIFEST).write_text(
        json.dumps(
            {
                "pages": report.pages,
                "masked_blocks": report.masked_blocks,
                "unread_lines": report.unread_lines,
                "refused": report.refused,
            }
        )
    )
    return report
