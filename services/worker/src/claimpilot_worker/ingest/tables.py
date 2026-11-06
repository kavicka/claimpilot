"""Line-item tables rebuilt from word positions.

Docling joins a table row's cells into one block and, on invoices, often cuts rows one line late:
an item's EAN lands at the start of the next item. This module rebuilds item tables from the
words themselves:

1. Words are grouped into visual lines by their vertical centre.
2. A header line is a line with at least three header terms ("množstvo", "cena", "DPH", ...);
   a second header line right under it is merged into the same columns.
3. Columns come from the header phrases; a data phrase goes to the column it overlaps most.
4. An anchor line carries amounts (a decimal number with a comma) in at least two columns: it is
   the line of one item. Other lines are continuations (name wrapped over lines, EAN, batch).
5. When the anchors print their description, continuations belong to the anchor above them
   (the EAN under its item). When the anchors leave the description empty, the description is
   wrapped around the numbers, and each continuation goes to the nearest anchor.
6. A line that starts with a total ("Spolu", "Súčet", "Total", ...) ends the table.

The output is one cell per (item, line, column), each with its own box, so an extracted value can
be grounded to the exact cell it was read from.
"""

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from claimpilot_core.schemas.parsing import FracBox, TableCell

HEADER_TERMS = {
    "množstvo", "mnozstvo", "kusy", "mj", "cena", "j.cena", "cena/mj", "jednotková", "dph",
    "%dph", "spolu", "total", "celkom", "zľava", "zlava", "ean", "názov", "popis", "označenie",
    "kód", "quantity", "price", "description", "expiration", "sadzba", "tarifná", "šarža",
    "expirácia", "ks", "(eur)", "unit", "customs",
}  # fmt: skip
END_TERMS = (
    "spolu", "súčet", "total (eur)", "total:", "total due", "celkom k", "k úhrade",
    "rekapitul", "dodacie listy", "* na faktúre", "základ", "suma k", "sazba", "celkem",
    "dodání zboží", "dodanie tovaru", "intra-community",
)  # fmt: skip
NUMERIC = re.compile(r"^-?[\d .\u00a0]*\d(?:,\d+)?%?$")
THOUSANDS_TAIL = re.compile(r"^\d{3}(?:,\d+)?$")
END_GAP = 4.0  # line heights of empty space that end a table
AMOUNT = re.compile(r"^-?\d{1,3}(?:[ . ]?\d{3})*,\d{2,4}%?$")


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Phrase:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def box(self) -> FracBox:
        return FracBox(
            x0=self.x0,
            y0=min(w.y0 for w in self.words),
            x1=self.x1,
            y1=max(w.y1 for w in self.words),
        )

    @property
    def is_amount(self) -> bool:
        return bool(AMOUNT.match(self.text.replace(" ", " ")))


@dataclass
class Line:
    words: list[Word]
    page: int
    phrases: list[Phrase] = field(default_factory=list)

    @property
    def yc(self) -> float:
        return statistics.fmean(w.yc for w in self.words)

    @property
    def height(self) -> float:
        return statistics.median(w.y1 - w.y0 for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Column:
    header: str
    x0: float
    x1: float


def group_lines(words: list[Word], page: int) -> list[Line]:
    lines: list[Line] = []
    for w in sorted(words, key=lambda w: (w.yc, w.x0)):
        if lines and abs(w.yc - lines[-1].yc) < 0.45 * max(lines[-1].height, w.y1 - w.y0):
            lines[-1].words.append(w)
        else:
            lines.append(Line([w], page))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
        ln.phrases = phrases(ln)
    return lines


def phrases(line: Line) -> list[Phrase]:
    """Words closer than about one character pair belong to one phrase. An amount never joins a
    word ("20,00" and "KS" sit in two columns); the groups of "5 812,40" join each other; a plain
    number inside a name ("250 ml") joins it when only a normal space separates them."""
    h = line.height
    out: list[Phrase] = []
    for w in line.words:
        prev = out[-1] if out else None
        gap = w.x0 - prev.x1 if prev is not None else 1.0
        if prev is not None and gap < 0.55 * h and _joins(prev, w, gap / h):
            prev.words.append(w)
        else:
            out.append(Phrase([w]))
    return out


def _joins(prev: Phrase, w: Word, gap: float) -> bool:
    """`gap` in line heights; a normal word space is about a quarter of one."""
    last = prev.words[-1].text
    prev_num, w_num = bool(NUMERIC.match(last)), bool(NUMERIC.match(w.text))
    if not prev_num and not w_num:
        return True
    if prev_num and w_num:
        # "5" + "812,40" is one amount; "0,573" + "0,6819" are two prices
        if (
            len(prev.words) == 1
            and re.fullmatch(r"-?\d{1,3}", last) is not None
            and bool(THOUSANDS_TAIL.match(w.text))
        ):
            return True
        # digit groups of a phone number, an IBAN or a postcode, a normal space apart
        return "," not in last and "," not in w.text and gap < 0.38
    if prev.text.endswith(":") and len(prev.words) == 1:
        return True  # a label and its value: "EAN: 2904012071349"
    if re.fullmatch(r"\+?[A-Z]{0,2}\d+", last) and w_num and "," not in w.text and gap < 0.38:
        return True  # "+421 921", "SK62 6500": a prefix and the next digit group
    amount = AMOUNT.match(last) if prev_num else AMOUNT.match(w.text)
    return not amount and gap < 0.38


def is_header(line: Line) -> bool:
    tokens = {t.lower().strip(":") for t in line.text.replace("/", " / ").split()}
    tokens |= {t.lower() for t in line.text.split()}
    hits = {t for t in tokens if t in HEADER_TERMS} | (
        {"bez dph"} if "bez dph" in line.text.lower() else set()
    )
    return len(hits) >= 3 and not any(p.is_amount for p in line.phrases)


def is_end(line: Line) -> bool:
    first = line.phrases[0].text.lower() if line.phrases else ""
    return first.startswith(END_TERMS)


def header_columns(lines: list[Line]) -> list[Column]:
    cols = [Column(p.text, p.x0, p.x1) for p in lines[0].phrases]
    for extra in lines[1:]:
        for p in extra.phrases:
            if _is_header_note(p):
                continue
            target = _best_column(cols, p.x0, p.x1, touch=True)
            if target is None:
                cols.append(Column(p.text, p.x0, p.x1))
            else:
                target.header = f"{target.header} {p.text}"
                target.x0, target.x1 = min(target.x0, p.x0), max(target.x1, p.x1)
    cols.sort(key=lambda c: c.x0)
    return cols


def _is_header_note(p: Phrase) -> bool:
    """A note printed in the header block ("Dodací list DL/12 03.02.2026 (SKLAD)"): digits and no
    header term. It sits among the column titles but is no part of one."""
    tokens = {t.lower().strip("():") for t in p.text.split()}
    return not tokens & HEADER_TERMS and any(ch.isdigit() for ch in p.text)


def _best_column(cols: list[Column], x0: float, x1: float, *, touch: bool = False) -> Column | None:
    best, best_overlap = None, 0.0
    for c in cols:
        overlap = min(c.x1, x1) - max(c.x0, x0)
        if overlap > best_overlap:
            best, best_overlap = c, overlap
    if best is None and not touch:
        centre = (x0 + x1) / 2
        best = min(cols, key=lambda c: min(abs(centre - c.x0), abs(centre - c.x1)))
    return best


def _bounds(cols: list[Column]) -> list[tuple[float, float]]:
    """Each column owns the space up to halfway to its neighbours."""
    out = []
    for i, c in enumerate(cols):
        left = 0.0 if i == 0 else (cols[i - 1].x1 + c.x0) / 2
        right = 1.0 if i == len(cols) - 1 else (c.x1 + cols[i + 1].x0) / 2
        out.append((left, right))
    return out


def assign(line: Line, cols: list[Column]) -> dict[int, list[Phrase]]:
    """Amounts are right-aligned and may run past their header: an amount belongs to the last
    column whose header starts left of its right edge. Text and codes are left-aligned: they go
    to the column whose share of the line holds their left edge, however far they run."""
    bounds = _bounds(cols)
    out: dict[int, list[Phrase]] = {}
    for p in line.phrases:
        if p.is_amount:
            starts = [i for i, c in enumerate(cols) if c.x0 <= p.x1]
            idx = starts[-1] if starts else 0
        else:
            idx = next(
                (i for i, (lft, r) in enumerate(bounds) if lft <= p.x0 <= r + 1e-6), len(cols) - 1
            )
        out.setdefault(idx, []).append(p)
    return out


@dataclass
class _Table:
    columns: list[Column]
    lines: list[Line] = field(default_factory=list)
    page_columns: dict[int, list[Column]] = field(default_factory=dict)


def _header_key(cols: list[Column]) -> str:
    return " ".join(c.header.lower() for c in cols)


def find_tables(pages: list[list[Word]]) -> list[_Table]:
    """Item tables in reading order. On a new page an open table is suspended: the page's own
    header block is skipped, and the table goes on at its repeated header or at the next line
    with amounts. A table whose header names no quantity (a VAT recap) is not an item table."""
    tables: list[_Table] = []
    open_table: _Table | None = None
    suspended = False
    for page_no, words in enumerate(pages, start=1):
        lines = group_lines(words, page_no)
        suspended = open_table is not None
        last_y: float | None = None
        i = 0
        while i < len(lines):
            ln = lines[i]
            if is_header(ln):
                head = [ln]
                while (
                    i + 1 < len(lines)
                    and lines[i + 1].yc - head[-1].yc < 2.2 * ln.height
                    and not any(p.is_amount for p in lines[i + 1].phrases)
                    and (
                        is_header(lines[i + 1])
                        or (not _has_code(lines[i + 1]) and _looks_like_header_tail(lines[i + 1]))
                    )
                ):
                    head.append(lines[i + 1])
                    i += 1
                cols = header_columns(head)
                if tables and _header_key(tables[-1].columns) == _header_key(cols):
                    open_table = tables[-1]
                else:
                    open_table = _Table(cols)
                    tables.append(open_table)
                open_table.page_columns[page_no] = cols  # positions can differ per page
                suspended, last_y = False, head[-1].yc
            elif open_table is not None:
                if suspended and not _is_anchor_line(ln):
                    i += 1
                    continue  # the page header of a continuation page
                gap = (ln.yc - last_y) / max(ln.height, 1e-6) if last_y is not None else 0.0
                if is_end(ln) or (not suspended and gap > END_GAP):
                    open_table = None
                elif _is_summary(ln):
                    pass  # a subtotal inside the table ("Dodací list DL/12 ... Množstvo 147,000")
                else:
                    suspended = False
                    open_table.lines.append(ln)
                    last_y = ln.yc
            i += 1
    return [t for t in tables if _has_quantity(t.columns)]


SUMMARY_TERMS = {"množstvo", "spolu", "celkom", "total", "súčet", "hmotnosť", "základ"}


def _is_summary(line: Line) -> bool:
    words = {w.text.lower().strip(":()") for w in line.words}
    return _is_anchor_line(line) and bool(words & SUMMARY_TERMS)


QUANTITY_TERMS = ("množstvo", "mnozstvo", "kusy", "quantity", "mj", "ks", "počet")


def _has_quantity(cols: list[Column]) -> bool:
    return any(any(t in c.header.lower() for t in QUANTITY_TERMS) for c in cols)


def _is_anchor_line(line: Line) -> bool:
    return sum(1 for p in line.phrases if p.is_amount) >= 2


def _has_code(line: Line) -> bool:
    """A long digit string (an EAN, an order number) marks data, never a header."""
    return any(sum(ch.isdigit() for ch in w.text) >= 5 for w in line.words)


def _looks_like_header_tail(line: Line) -> bool:
    """Header pieces under the header ("cena bez DPH", "(EUR)"), not an item: most phrases hold a
    header term, and there are several of them."""
    hits = sum(
        1 for p in line.phrases if {t.lower().strip("():") for t in p.text.split()} & HEADER_TERMS
    )
    return len(line.phrases) >= 2 and hits * 2 >= len(line.phrases)


def items(table: _Table) -> list[list[tuple[Line, dict[int, list[Phrase]]]]]:
    rows = [(ln, assign(ln, table.page_columns.get(ln.page, table.columns))) for ln in table.lines]
    # Two amounts on a line make it an item line, whichever columns they landed in (a header
    # the OCR missed leaves two amounts in one column).
    anchors = [k for k, (ln, _) in enumerate(rows) if _is_anchor_line(ln)]
    if not anchors:
        return []
    desc = 0
    centred = (
        sum(1 for k in anchors if desc not in rows[k][1]) > len(anchors) / 2
    )  # numbers printed beside a wrapped description
    groups: list[list[int]] = [[k] for k in anchors]
    for k in range(len(rows)):
        if k in anchors:
            continue
        if centred:
            same_page = [
                a for a in range(len(anchors)) if rows[anchors[a]][0].page == rows[k][0].page
            ]
            if not same_page:
                continue  # text on a page without items (a repeated payment block)
            target = min(same_page, key=lambda a: abs(rows[anchors[a]][0].yc - rows[k][0].yc))
        else:
            before = [a for a, idx in enumerate(anchors) if idx < k]
            if not before:
                continue  # text above the first item ("Fakturujeme Vám tovar...")
            target = before[-1]
        groups[target].append(k)
    return [[rows[k] for k in sorted(g)] for g in groups]


def table_cells(pages: list[list[Word]]) -> list[TableCell]:
    out: list[TableCell] = []
    for t_idx, table in enumerate(find_tables(pages)):
        for item_idx, group in enumerate(items(table)):
            for line_idx, (ln, cells) in enumerate(group):
                for col_idx, ps in sorted(cells.items()):
                    box = ps[0].box
                    for p in ps[1:]:
                        box = box.union(p.box)
                    out.append(
                        TableCell(
                            page=ln.page,
                            table=t_idx,
                            item=item_idx,
                            line=line_idx,
                            col=col_idx,
                            header=table.columns[col_idx].header,
                            text=" ".join(p.text for p in ps),
                            bbox=box,
                        )
                    )
    return out


def words_from_pdf(path) -> list[list[Word]]:
    """Words of every page from the text layer, in page fractions (top-left origin)."""
    import pymupdf as fitz

    pages: list[list[Word]] = []
    with fitz.open(path) as doc:
        for page in doc:
            w, h = page.rect.width, page.rect.height
            pages.append(
                [
                    Word(t[4], t[0] / w, t[1] / h, t[2] / w, t[3] / h)
                    for t in page.get_text("words")
                    if t[4].strip()
                ]
            )
    return pages


def words_from_scan(path, dpi: int = 200) -> list[list[Word]]:
    """Words of every page of a scan through OCR: macOS LiveText gives word boxes; elsewhere
    RapidOCR gives line boxes, which are split into words by character count."""
    import sys

    import pymupdf as fitz
    from PIL import Image

    pages: list[list[Word]] = []
    with fitz.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            words = _ocr_mac(img) if sys.platform == "darwin" else _ocr_rapid(img)
            pages.append(deskew(words, pix.width / pix.height))
    return pages


def deskew(words: list[Word], aspect: float) -> list[Word]:
    """Undo the tilt of a scanned page: the median slope between neighbouring words of one line
    gives the angle, and a shear moves every word back onto a level baseline. `aspect` is page
    width / height, since boxes are fractions of each."""
    slopes = []
    ordered = sorted(words, key=lambda w: (w.yc, w.x0))
    for a in ordered:
        h = a.y1 - a.y0
        for b in ordered:
            dx = b.x0 - a.x1
            if 0 < dx < 0.05 and abs(b.yc - a.yc) < 0.8 * h:
                slopes.append((b.yc - a.yc) / ((b.x0 + b.x1) / 2 - (a.x0 + a.x1) / 2))
                break
    if len(slopes) < 10:
        return words
    slope = statistics.median(slopes)
    if abs(slope) < 1e-4:
        return words
    del aspect  # the slope is measured in the same fractions it is applied in
    return [
        Word(w.text, w.x0, w.y0 - slope * (w.x0 + w.x1) / 2, w.x1, w.y1 - slope * (w.x0 + w.x1) / 2)
        for w in words
    ]


def _ocr_mac(img) -> list[Word]:
    from ocrmac.ocrmac import OCR  # pyright: ignore[reportMissingImports]  # macOS only

    out = []
    for text, _conf, (x, y, w, h) in OCR(
        img,
        framework="livetext",
        recognition_level="accurate",
        language_preference=["sk-SK", "cs-CZ", "en-US", "de-DE"],
        unit="token",
    ).recognize():
        if text.strip():  # Vision boxes have their origin bottom-left
            out.append(Word(text, x, 1 - (y + h), x + w, 1 - y))
    return out


def _ocr_rapid(img) -> list[Word]:
    import numpy as np
    from rapidocr import RapidOCR

    result = RapidOCR()(np.asarray(img))
    width, height = img.size
    boxes: Any = getattr(result, "boxes", None)
    texts: Any = getattr(result, "txts", None) or ()
    out = []
    for box, text in zip(boxes if boxes is not None else [], texts, strict=False):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        x0, x1, y0, y1 = min(xs) / width, max(xs) / width, min(ys) / height, max(ys) / height
        tokens = text.split()
        total = max(1, len(text))
        pos = 0
        for t in tokens:
            start = text.index(t, pos)
            pos = start + len(t)
            out.append(
                Word(t, x0 + (x1 - x0) * start / total, y0, x0 + (x1 - x0) * pos / total, y1)
            )
    return out


def page_words(path, pages: list) -> list[list[Word]]:
    """Words of every page: the text layer where a page has one, OCR on scanned pages."""
    text_words = words_from_pdf(path) if str(path).lower().endswith(".pdf") else []
    scan_words: list[list[Word]] | None = None
    out: list[list[Word]] = []
    for info in pages:
        if info.text_chars > 20 and info.page <= len(text_words):
            out.append(text_words[info.page - 1])
        else:
            if scan_words is None:
                scan_words = words_from_scan(path)
            out.append(scan_words[info.page - 1] if info.page <= len(scan_words) else [])
    return out


def item_table_cells(path, pages: list, hidden: list | None = None) -> list[TableCell]:
    """Line-item cells of a document. Words a reader cannot see (`hidden`, from
    ingest/hidden_text.py) are dropped first: they never reach a cell, so never a model."""
    return table_cells(_visible(page_words(path, pages), hidden or []))


def _visible(pages: list[list[Word]], hidden: list) -> list[list[Word]]:
    out = []
    for page_no, words in enumerate(pages, start=1):
        boxes = [h.bbox for h in hidden if h.page == page_no]
        out.append([w for w in words if not any(_inside(w, b) for b in boxes)])
    return out


def line_blocks(pages: list[list[Word]], hidden: list) -> list:
    """Visual lines as blocks, phrases joined by " | " so columns stay apart ("5,00% | 665,46 |
    33,27 | Základ | 2 272,72"). Docling reorders cells of such rows; words in their own
    reading order do not. Hidden text becomes blocks of its own, marked with the reason, for the
    handler and the injection signals; it never reaches a model."""
    from claimpilot_core.schemas.parsing import Block

    blocks: list[Block] = []
    for page_no, words in enumerate(pages, start=1):
        spans = [h for h in hidden if h.page == page_no]
        visible = [w for w in words if not any(_inside(w, h.bbox) for h in spans)]
        for ln in group_lines(visible, page_no):
            box = ln.phrases[0].box
            for ph in ln.phrases[1:]:
                box = box.union(ph.box)
            text = " | ".join(ph.text for ph in ln.phrases)
            blocks.append(Block(page=page_no, seq=len(blocks), kind="line", text=text, bbox=box))
        for h in spans:
            blocks.append(
                Block(
                    page=page_no,
                    seq=len(blocks),
                    kind="line",
                    text=h.text,
                    bbox=h.bbox,
                    hidden=h.reason,
                )
            )
    return blocks


HIDDEN_SHARE = 0.9  # share of a word's width a hidden span must cover to hide the word


def _inside(w: Word, box: FracBox) -> bool:
    """A word is hidden when a hidden span covers it. A word the span only touches stays: "30,000"
    printed with ",000" in pale grey is a mostly visible word, and dropping it loses the number."""
    if not box.y0 <= w.yc <= box.y1:
        return False
    width = w.x1 - w.x0
    covered = min(w.x1, box.x1) - max(w.x0, box.x0)
    return covered >= HIDDEN_SHARE * width if width > 0 else box.x0 <= w.x0 <= box.x1
