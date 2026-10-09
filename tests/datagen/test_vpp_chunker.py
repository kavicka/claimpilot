"""The chunker must recover every clause of the rendered VPP PDF with the right id and text."""

import re
from pathlib import Path

from claimpilot_core.policy import load_terms
from claimpilot_datagen.vpp import render_vpp
from claimpilot_worker.coverage.chunker import chunk_pdf

ROOT = Path(__file__).resolve().parents[2]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_every_clause_is_recovered_from_the_pdf(tmp_path):
    pdf = render_vpp(ROOT / "data" / "policies" / "vpp_cp_2026.yaml", tmp_path / "vpp.pdf")
    chunks = {c.clause_id: c for c in chunk_pdf(pdf)}
    terms = load_terms(ROOT / "data" / "policies" / "vpp_cp_2026.yaml")
    assert set(chunks) == terms.clause_ids()
    for clause in terms.clauses:
        got = chunks[clause.clause_id]
        assert norm(got.text) == norm(clause.text), clause.clause_id
        assert got.heading == clause.article_title
    assert chunks["A7.5"].display_id == "čl. 7 ods. 5"
