"""Score rebuilt item tables against invoice ground truth (used by the eval suite and tests).

A ground-truth cell counts as found when exactly one parsed cell of the matching item holds its
printed text as whole words; items are matched in reading order.
"""

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from claimpilot_core.schemas.parsing import TableCell


@dataclass
class TableScore:
    items_expected: int = 0
    items_found: int = 0
    cells_expected: int = 0
    cells_exact: int = 0  # in exactly one parsed cell of the right item
    cells_ambiguous: int = 0  # in more than one cell of the item
    misses: list[str] = field(default_factory=list)

    def add(self, other: "TableScore") -> None:
        self.items_expected += other.items_expected
        self.items_found += other.items_found
        self.cells_expected += other.cells_expected
        self.cells_exact += other.cells_exact
        self.cells_ambiguous += other.cells_ambiguous
        self.misses += other.misses[:3]


def _norm(text: str) -> str:
    return " ".join(text.replace(" ", " ").split())


def loose(text: str) -> str:
    """For OCR text: no accents, no case, no spaces inside numbers ("2 874,96" = "2874,96")."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"(?<=\d)[ .](?=\d{3}\b)", "", _norm(plain))


def _holds(cell: str, printed: str, *, ocr: bool = False) -> bool:
    if ocr:
        cell, printed = loose(cell), loose(printed)
    return (
        re.search(rf"(?<![\w,.]){re.escape(_norm(printed))}(?![\w,]|\.\d)", _norm(cell)) is not None
    )


def gt_cells(line: dict[str, Any]) -> list[tuple[str, str]]:
    out = [(k, v["printed"]) for k, v in line["cells"].items() if v.get("printed")]
    for b in line.get("batches", []):
        out += [(f"batch.{k}", v["printed"]) for k, v in b.items()]
    # A one-batch line prints its quantity once; the batch quantity is the line quantity.
    if len(line.get("batches", [])) == 1:
        out = [o for o in out if o[0] != "batch.quantity"]
    return out


def score(
    cells: list[TableCell],
    gt_lines: list[dict[str, Any]],
    doc_id: str = "",
    fee_labels: tuple[str, ...] = (),
    *,
    ocr: bool = False,
) -> TableScore:
    """`fee_labels`: rows such as "Doprava" are table rows on the page but fees in the ground
    truth; they are left out of the item count."""
    items: dict[tuple[int, int], list[TableCell]] = defaultdict(list)
    for c in cells:
        items[(c.table, c.item)].append(c)
    parsed = [
        items[k]
        for k in sorted(items)
        if not any(_holds(c.text, label) and c.col == 0 for c in items[k] for label in fee_labels)
    ]
    expected = [ln for ln in gt_lines if ln.get("page") is not None]
    s = TableScore(items_expected=len(expected), items_found=len(parsed))
    for i, line in enumerate(expected):
        got = parsed[i] if i < len(parsed) else []
        columns = column_texts(got)
        expected_cells = gt_cells(line)
        for key, printed in expected_cells:
            s.cells_expected += 1
            hits = [col for col, text in columns.items() if _holds(text, printed, ocr=ocr)]
            hits += [c.col for c in got if _holds(c.text, printed, ocr=ocr) and c.col not in hits]
            # The same text printed in two cells of the line (price before and after a zero
            # discount) may sit in two columns.
            same = sum(1 for _, other in expected_cells if _holds(other, printed, ocr=ocr))
            if hits and len(set(hits)) <= same:
                s.cells_exact += 1
            elif hits:
                s.cells_ambiguous += 1
            else:
                s.misses.append(
                    f"{doc_id} item {i} {key}={printed!r} in {sorted(columns.values())}"
                )
    return s


def column_texts(cells: list[TableCell]) -> dict[int, str]:
    """An item's text per column, its visual lines joined (a name wrapped over two lines)."""
    out: dict[int, list[str]] = defaultdict(list)
    for c in sorted(cells, key=lambda c: (c.line, c.col)):
        out[c.col].append(c.text)
    return {col: " ".join(parts) for col, parts in out.items()}
