"""Tests for rendering PDF pages as PNG images."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Protocol, cast

import pymupdf
import pytest
from pypdf import PdfWriter

from drum_score_converter.page_renderer import (
    DEFAULT_DPI,
    PageRenderer,
    PageRenderError,
)
from drum_score_converter.pdf_loader import PDFLoader

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class _DecodedImage(Protocol):
    width: int
    height: int


_decode_image = cast(Callable[[bytes], _DecodedImage], pymupdf.Pixmap)


def _write_pdf(
    path: Path,
    page_sizes: tuple[tuple[float, float], ...],
    *,
    password: str | None = None,
) -> None:
    writer = PdfWriter()
    for width, height in page_sizes:
        writer.add_blank_page(width=width, height=height)
    if password is not None:
        writer.encrypt(password, algorithm="AES-256")
    with path.open("wb") as output:
        writer.write(output)


def test_render_all_pages_to_memory_from_document_content(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72), (144, 72)))
    document = PDFLoader.load(path)
    path.unlink()

    pages = PageRenderer.render(document, dpi=144)

    assert tuple(page.page_number for page in pages) == (1, 2)
    assert tuple((page.width, page.height) for page in pages) == (
        (144, 144),
        (288, 144),
    )
    assert all(page.content.startswith(PNG_SIGNATURE) for page in pages)
    assert all(page.dpi == 144 for page in pages)
    assert all(page.media_type == "image/png" for page in pages)
    for page in pages:
        decoded_image = _decode_image(page.content)
        assert decoded_image.width == page.width
        assert decoded_image.height == page.height


def test_render_selected_pages_at_300_dpi_or_more(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72), (72, 144), (144, 144)))
    document = PDFLoader.load(path)

    pages = PageRenderer.render(document, dpi=360, pages=(3, 1))

    assert tuple(page.page_number for page in pages) == (3, 1)
    assert tuple((page.width, page.height) for page in pages) == (
        (720, 720),
        (360, 360),
    )


def test_render_decrypted_content_without_reopening_source(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    _write_pdf(path, ((72, 72),), password="secret")
    document = PDFLoader.load(path, password="secret")
    path.unlink()

    (page,) = PageRenderer.render(document, dpi=72)

    assert document.is_encrypted is True
    assert page.content.startswith(PNG_SIGNATURE)
    assert (page.width, page.height) == (72, 72)


def test_default_dpi_is_300(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72),))

    (page,) = PageRenderer.render(PDFLoader.load(path))

    assert DEFAULT_DPI == 300
    assert page.dpi == 300
    assert (page.width, page.height) == (300, 300)


def test_higher_dpi_produces_larger_dimensions_for_same_page(
    tmp_path: Path,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((144, 72),))
    document = PDFLoader.load(path)

    (low_dpi_page,) = PageRenderer.render(document, dpi=72, pages=(1,))
    (high_dpi_page,) = PageRenderer.render(document, dpi=300, pages=(1,))

    assert high_dpi_page.width > low_dpi_page.width
    assert high_dpi_page.height > low_dpi_page.height


def test_save_and_render_to_directory(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72), (72, 72)))
    document = PDFLoader.load(path)

    output_paths = PageRenderer.render_to_directory(
        document,
        tmp_path / "nested" / "pages",
        dpi=72,
        pages=(2,),
    )

    assert tuple(output_path.name for output_path in output_paths) == (
        "page_002.png",
    )
    assert output_paths[0].read_bytes().startswith(PNG_SIGNATURE)


@pytest.mark.parametrize("dpi", [0, -1, True, 72.5])
def test_render_rejects_invalid_dpi(tmp_path: Path, dpi: Any) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72),))

    with pytest.raises(PageRenderError, match="DPI"):
        PageRenderer.render(PDFLoader.load(path), dpi=dpi)


@pytest.mark.parametrize("pages", [(0,), (3,), (1, 1), (True,)])
def test_render_rejects_invalid_page_selection(
    tmp_path: Path, pages: tuple[int, ...]
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72), (72, 72)))

    with pytest.raises(PageRenderError, match="Page"):
        PageRenderer.render(PDFLoader.load(path), pages=pages)


def test_render_rejects_invalid_document_content(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72),))
    document = PDFLoader.load(path)
    object.__setattr__(document, "content", b"not a PDF")

    with pytest.raises(PageRenderError, match="cannot be opened"):
        PageRenderer.render(document)


def test_rendered_page_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((72, 72),))
    (page,) = PageRenderer.render(PDFLoader.load(path), dpi=72)

    with pytest.raises(FrozenInstanceError):
        setattr(page, "dpi", 300)
