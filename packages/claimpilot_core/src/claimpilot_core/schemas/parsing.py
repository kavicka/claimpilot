"""Parser output shared by the worker, the evals and the api.

Bounding boxes are fractions of the page (0-1) with the origin top-left, so the same box works on
a PDF page in points, a scan in pixels and a page render of any size.
"""

from pydantic import BaseModel, Field


class FracBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    def union(self, other: "FracBox") -> "FracBox":
        return FracBox(
            x0=min(self.x0, other.x0),
            y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1),
            y1=max(self.y1, other.y1),
        )


class Block(BaseModel):
    page: int  # 1-based
    seq: int
    kind: str  # text | section_header | table_row | list_item | ...
    text: str
    bbox: FracBox
    ocr: bool = False
    # Why a reader cannot see this text (white on white, 1 pt, off the page...); None when visible.
    # Hidden blocks are kept for the handler and the injection signals, never sent to a model.
    hidden: str | None = None


class TableCell(BaseModel):
    """One cell of a line-item table, rebuilt from word positions (ingest/tables.py).

    `item` is the table row a reader sees (one invoice line); `line` counts the visual lines of
    that item (0 = the line with the amounts, or the first line of a wrapped name)."""

    page: int
    table: int
    item: int
    line: int
    col: int
    header: str
    text: str
    bbox: FracBox


class PageInfo(BaseModel):
    page: int
    width: float
    height: float
    text_chars: int = 0  # characters from the text layer; 0 means the page is an image


class ParsedDocument(BaseModel):
    sha256: str
    mime_type: str
    pages: list[PageInfo]
    blocks: list[Block] = Field(default_factory=list)
    # Line-item tables, filled for invoices only; claims keep their block-only output.
    cells: list[TableCell] = Field(default_factory=list)
    parser: str = "docling"
    seconds: float = 0.0

    @property
    def has_text_layer(self) -> bool:
        return any(p.text_chars > 20 for p in self.pages)

    def visible(self) -> "ParsedDocument":
        """The document as a reader sees it: without hidden blocks."""
        if not any(b.hidden for b in self.blocks):
            return self
        return self.model_copy(update={"blocks": [b for b in self.blocks if not b.hidden]})

    def page_text(self, page: int, *, redacted: dict[int, str] | None = None) -> str:
        parts = [
            (redacted or {}).get(b.seq, b.text)
            for b in self.blocks
            if b.page == page and not b.hidden
        ]
        return "\n".join(parts)

    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if not b.hidden)
