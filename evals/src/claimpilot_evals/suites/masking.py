"""Masking before a cloud model (Phase 2): does a masked page still show personal data, and can
the model still read what it needs?

For every scanned dev document: mask the page images as the pipeline would for a cloud model,
read the masked pages again with Apple Vision OCR, and look for every ground-truth personal value
(a surname alone counts) and for the document's critical non-personal values (totals, dates,
numbers). The same OCR on the unmasked pages gives the baseline for the second number. Apple
Vision is a different engine from the ones the masker relies on (Docling's blocks, RapidOCR's
detector), so a line both of them miss still counts against the masker.

Local only (macOS, needs the generated PDFs); not part of `--suite all` and not replayed in CI.
"""

import base64
import io
import re

from claimpilot_core.domain import DocType
from claimpilot_core.pii.guard import fold
from claimpilot_core.schemas.documents import CRITICAL_FIELDS
from claimpilot_evals.cache import page_image
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext, redact_claim
from claimpilot_worker.ingest.mask import has_personal_data, mask_pages

PERSONAL_FIELDS = re.compile(r"name|iban|birth|phone|email|address|passport|plate")


def _ocr(image_b64: str) -> str:
    from ocrmac import ocrmac  # pyright: ignore[reportMissingImports]  # Apple Vision; macOS only
    from PIL import Image

    img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
    return " ".join(text for text, _conf, _box in ocrmac.OCR(img).recognize())


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", fold(text))


def _visible(value: str, text: str) -> bool:
    """A personal value counts as visible when it, or a surname of four letters or more, can be
    read in the OCR text of the masked page."""
    t = _norm(text)
    if _norm(value) in t:
        return True
    words = [w for w in re.split(r"[\s/,]+", fold(value)) if len(w) >= 4 and w.isalpha()]
    return len(words) >= 2 and any(_norm(w) in t for w in words[1:])


async def run(ctx: RunContext) -> Report:
    report = Report("masking", ctx.split)
    readable_masked = readable_plain = critical_total = 0
    for claim in ctx.claims():
        rc = redact_claim(claim)
        detect = has_personal_data(rc.redactor)
        for doc in rc.docs:
            if not doc.gt.data["scan"] or not doc.gt.path.exists():
                continue
            images = [
                page_image(doc.gt.path, p.page, doc.gt.data["sha256"]) for p in doc.parsed.pages
            ]
            masked, mask_report = mask_pages(images, doc.parsed, detect)
            values = sorted({p["value"] for p in doc.gt.data["pii"]})
            critical = [
                f["printed"]
                for name, f in doc.gt.data["fields"].items()
                if name in CRITICAL_FIELDS.get(DocType(doc.gt.doc_type), [])
                and isinstance(f, dict)
                and isinstance(f.get("printed"), str)
                and not PERSONAL_FIELDS.search(name)
            ]
            if masked is None:
                report.items.append(
                    ItemResult(
                        doc.gt.item_id,
                        True,  # not sent at all: nothing can leak; the text path reads it
                        "masked or refused",
                        "refused",
                        ["documents"],
                        {
                            "refused": mask_report.refused,
                            "visible": [],
                            "doc_type": doc.gt.doc_type,
                        },
                    )
                )
                continue
            masked_text = " ".join(_ocr(i) for i in masked)
            plain_text = " ".join(_ocr(i) for i in images)
            visible = [v for v in values if _visible(v, masked_text)]
            critical_total += len(critical)
            readable_masked += sum(_norm(v) in _norm(masked_text) for v in critical)
            readable_plain += sum(_norm(v) in _norm(plain_text) for v in critical)
            report.items.append(
                ItemResult(
                    doc.gt.item_id,
                    not visible,
                    "no personal value readable",
                    f"{len(visible)} readable" if visible else "none readable",
                    ["documents"],
                    {
                        "visible": visible,
                        "masked_blocks": mask_report.masked_blocks,
                        "unread_lines": mask_report.unread_lines,
                        "pages": mask_report.pages,
                        "doc_type": doc.gt.doc_type,
                        "personal_values": len(values),
                    },
                )
            )
    docs = report.items
    report.ratio("documents_without_visible_personal_data", sum(i.ok for i in docs), len(docs))
    report.count("personal_values_visible", sum(len(i.detail["visible"]) for i in docs))
    report.count("documents_refused", sum(i.got == "refused" for i in docs))
    report.ratio("critical_values_readable_masked", readable_masked, critical_total)
    report.ratio("critical_values_readable_unmasked", readable_plain, critical_total)
    return report
