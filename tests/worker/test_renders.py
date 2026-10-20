"""Page renders are capped in pixels, so a huge MediaBox cannot allocate gigabytes."""

import pymupdf
import pytest
from PIL import Image

from claimpilot_worker.ingest import check, renders
from claimpilot_worker.ingest.renders import PageTooLargeError, capped_dpi, render_pages


def pdf_with_page(tmp_path, width: float, height: float):
    doc = pymupdf.open()
    doc.new_page(width=width, height=height).insert_text((72, 72), "Faktúra")
    path = tmp_path / "doc.pdf"
    doc.save(path)
    return path


def test_a_normal_page_keeps_its_resolution():
    assert capped_dpi(595, 842, 110) == 110  # A4


def test_a_page_over_the_cap_is_scaled_down_to_fit(monkeypatch):
    monkeypatch.setattr(renders, "MAX_RENDER_PIXELS", 1_000_000)
    dpi = capped_dpi(2000, 2000, 110)  # 3055 x 3055 px at 110 dpi
    assert 20 < dpi < 110
    side = 2000 * dpi / 72
    assert side * side <= 1_000_000 * 1.001


def test_a_page_needing_more_than_four_times_less_resolution_is_refused(monkeypatch):
    monkeypatch.setattr(renders, "MAX_RENDER_PIXELS", 1_000_000)
    with pytest.raises(PageTooLargeError):
        capped_dpi(20_000, 20_000, 110)


def test_render_pages_writes_an_image_inside_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(renders, "MAX_RENDER_PIXELS", 1_000_000)
    (out,) = render_pages(pdf_with_page(tmp_path, 2000, 2000), tmp_path / "out")
    with Image.open(out) as img:
        assert img.width * img.height <= 1_000_000 * 1.02


def test_render_pages_refuses_a_giant_page_without_allocating_it(tmp_path):
    path = pdf_with_page(tmp_path, 200_000, 200_000)  # 305 000 px a side at 110 dpi
    with pytest.raises(PageTooLargeError):
        render_pages(path, tmp_path / "out")
    assert not list((tmp_path / "out").glob("*.png"))


def test_the_vision_image_is_capped_too(tmp_path):
    with pytest.raises(PageTooLargeError):
        renders.page_png_b64(pdf_with_page(tmp_path, 200_000, 200_000), 1)


def test_ingest_check_sends_a_giant_page_back_to_the_client(tmp_path):
    problem = check.problem_of(pdf_with_page(tmp_path, 200_000, 200_000))
    assert problem is not None and problem.code == "page_too_large"
    assert check.problem_of(pdf_with_page(tmp_path, 595, 842)) is None
