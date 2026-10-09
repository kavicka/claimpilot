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
    parser: str = "docling"
    seconds: float = 0.0

    @property
    def has_text_layer(self) -> bool:
        return any(p.text_chars > 20 for p in self.pages)

    def page_text(self, page: int, *, redacted: dict[int, str] | None = None) -> str:
        parts = [(redacted or {}).get(b.seq, b.text) for b in self.blocks if b.page == page]
        return "\n".join(parts)

    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)
