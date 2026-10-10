"""Can a document be read at all? Checked before Docling, so a file the client must send again goes
back to the client (NEEDS_INFO) instead of failing three retries and landing in the dead letter."""

from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageFile

MAX_PAGES = 40
MAX_PIXELS = 60_000_000  # a 60-megapixel photo is already far beyond any phone camera


@dataclass(frozen=True)
class Problem:
    code: str
    detail: str  # English, for the handler
    client: str  # Slovak, for the request to the client


def _pdf(path: Path) -> Problem | None:
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                return Problem("password", "protected by a password", "je chránený heslom")
            if doc.page_count == 0:
                return Problem("no_pages", "has no pages", "neobsahuje žiadnu stranu")
            if doc.page_count > MAX_PAGES:
                return Problem(
                    "too_many_pages",
                    f"has {doc.page_count} pages; at most {MAX_PAGES} per document",
                    f"má {doc.page_count} strán, najviac {MAX_PAGES} na jeden dokument",
                )
            doc.load_page(0).get_text()  # a broken page tree fails here
    except Exception:
        return Problem("damaged", "damaged or not a PDF", "je poškodený alebo to nie je PDF")
    return None


def _image(path: Path) -> Problem | None:
    too_large = Problem("too_large", "image larger than 60 megapixels", "je príliš veľký obrázok")
    # Some libraries (WeasyPrint) switch on loading truncated images for the whole process; this
    # check must see a cut-off file as damaged whatever else was imported.
    lenient, ImageFile.LOAD_TRUNCATED_IMAGES = ImageFile.LOAD_TRUNCATED_IMAGES, False
    try:
        return _open_image(path, too_large)
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = lenient


def _open_image(path: Path, too_large: Problem) -> Problem | None:
    try:
        with Image.open(path) as img:
            if img.width * img.height > MAX_PIXELS:
                return too_large
            img.load()  # a truncated image fails only when its pixels are decoded
    except Image.DecompressionBombError:  # Pillow refuses to even open it
        return too_large
    except (OSError, SyntaxError, ValueError):
        return Problem("damaged", "damaged or not an image", "je poškodený alebo to nie je obrázok")
    return None


def problem_of(path: Path) -> Problem | None:
    return _pdf(path) if path.suffix.lower() == ".pdf" else _image(path)


def unreadable_request(problems: dict[str, Problem]) -> str:
    """The request to the client, in Slovak (formal)."""
    lines = "\n".join(f"- „{name}“ {p.client}" for name, p in problems.items())
    return (
        "Vážená pani / Vážený pán,\n\n"
        "niektoré doklady, ktoré ste k poistnej udalosti poslali, sa nedajú otvoriť:\n"
        f"{lines}\n\n"
        "Pošlite ich prosím znova ako PDF bez hesla alebo ako fotografiu (JPG, PNG). Kým ich "
        "nedostaneme, lehota na vybavenie neplynie (čl. 13 ods. 3 VPP).\n\n"
        "S pozdravom\nOddelenie likvidácie poistných udalostí\nVzorová poisťovňa, a. s."
    )
