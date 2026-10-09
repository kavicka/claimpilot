"""Structure-aware chunking of policy terms: one chunk per paragraph (odsek) of an article (článok).

Clause ids are A<article>.<paragraph>, the same ids the ground truth uses. A paragraph is the unit a
handler cites ("čl. 7 ods. 5"), so retrieval is scored on it.
"""

import re
from dataclasses import dataclass

import pymupdf

ARTICLE = re.compile(r"^Článok\s+(\d+)\s*$")
PARAGRAPH = re.compile(r"^\((\d+)\)\s+(.*)$")
PAGE_FOOTER = re.compile(r"^\d+\s*/\s*\d+$")


@dataclass
class Chunk:
    clause_id: str
    article: int
    paragraph: int
    heading: str
    text: str
    page: int

    @property
    def display_id(self) -> str:
        return f"čl. {self.article} ods. {self.paragraph}"


def chunk_lines(lines: list[tuple[int, str]]) -> list[Chunk]:
    chunks: list[Chunk] = []
    article: int | None = None
    heading = ""
    expect_heading = False
    for page, raw in lines:
        line = raw.strip()
        if not line or PAGE_FOOTER.match(line):
            continue
        if m := ARTICLE.match(line):
            article, heading, expect_heading = int(m[1]), "", True
            continue
        if expect_heading:
            heading, expect_heading = line, False
            continue
        if article is None:
            continue
        if m := PARAGRAPH.match(line):
            n = int(m[1])
            chunks.append(Chunk(f"A{article}.{n}", article, n, heading, m[2], page))
        elif chunks and chunks[-1].article == article:
            chunks[-1].text += " " + line  # wrapped line of the same paragraph
    for c in chunks:
        c.text = re.sub(r"\s+", " ", c.text).strip()
    return chunks


def chunk_pdf(path) -> list[Chunk]:
    lines: list[tuple[int, str]] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            for line in str(page.get_text()).splitlines():
                lines.append(((page.number or 0) + 1, line))
    return chunk_lines(lines)
