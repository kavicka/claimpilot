"""Render the synthetic policy terms (VPP) to PDF: the document the coverage index is built from."""

from pathlib import Path

import yaml

from claimpilot_datagen.documents import Built
from claimpilot_datagen.render import render_pdf


def render_vpp(source: Path, target: Path) -> Path:
    raw = yaml.safe_load(source.read_text("utf-8"))
    ctx = {
        "lang": "sk",
        "insurer": raw["insurer"],
        "terms_id": raw["terms_id"],
        "title": raw["title"],
        "articles": raw["articles"],
        "injection": None,
        "handwriting": False,
    }
    target.write_bytes(render_pdf(Built("vpp.html.j2", ctx, {}, [])))
    return target
