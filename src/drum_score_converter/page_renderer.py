"""Render loaded PDF pages as PNG images."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import pymupdf

from drum_score_converter.pdf_loader import PDFDocument

DEFAULT_DPI = 300


class _Pixmap(Protocol):
    width: int
    height: int

    def tobytes(self, output: str) -> bytes: ...


class _Page(Protocol):
    def get_pixmap(self, *, dpi: int, alpha: bool) -> _Pixmap: ...


class _PDF(Protocol):
    needs_pass: bool
    page_count: int

    def load_page(self, page_id: int) -> _Page: ...

    def close(self) -> None: ...


_open_pdf = cast(Callable[..., _PDF], pymupdf.open)


class PageRenderError(Exception):
    """Raised when PDF pages cannot be rendered or saved."""


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """Immutable PNG rendering of one PDF page.

    ``page_number`` is one-based to match page numbers shown to users.
    """

    page_number: int
    content: bytes
    width: int
    height: int
    dpi: int
    media_type: str = "image/png"


class PageRenderer:
    """Render pages from the in-memory content of a PDF document."""

    @staticmethod
    def render(
        document: PDFDocument,
        *,
        dpi: int = DEFAULT_DPI,
        pages: Iterable[int] | None = None,
    ) -> tuple[RenderedPage, ...]:
        """Render selected pages to PNG in memory.

        Page numbers are one-based. When ``pages`` is omitted, all pages are
        rendered in document order.
        """
        _validate_dpi(dpi)
        page_numbers = _normalize_page_numbers(pages, document.page_count)

        try:
            pdf = _open_pdf(stream=document.content, filetype="pdf")
        except (pymupdf.EmptyFileError, pymupdf.FileDataError, RuntimeError) as error:
            raise PageRenderError("PDF content cannot be opened") from error

        try:
            if pdf.needs_pass:
                raise PageRenderError("PDF content must be decrypted before rendering")
            if pdf.page_count != document.page_count:
                raise PageRenderError(
                    "PDF content page count does not match PDFDocument metadata"
                )

            rendered_pages = []
            for page_number in page_numbers:
                page = pdf.load_page(page_number - 1)
                pixmap = page.get_pixmap(dpi=dpi, alpha=False)
                rendered_pages.append(
                    RenderedPage(
                        page_number=page_number,
                        content=pixmap.tobytes("png"),
                        width=pixmap.width,
                        height=pixmap.height,
                        dpi=dpi,
                    )
                )
            return tuple(rendered_pages)
        except PageRenderError:
            raise
        except (RuntimeError, ValueError) as error:
            raise PageRenderError("PDF page rendering failed") from error
        finally:
            pdf.close()

    @staticmethod
    def save(
        rendered_pages: Iterable[RenderedPage],
        output_directory: str | Path,
    ) -> tuple[Path, ...]:
        """Save already-rendered PNG pages to an output directory."""
        directory = Path(output_directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise PageRenderError(
                    f"Output path is not a directory: {output_directory}"
                )

            output_paths = []
            for page in rendered_pages:
                output_path = directory / f"page_{page.page_number:03d}.png"
                output_path.write_bytes(page.content)
                output_paths.append(output_path)
            return tuple(output_paths)
        except PageRenderError:
            raise
        except OSError as error:
            raise PageRenderError(
                f"Rendered pages cannot be saved to: {output_directory}"
            ) from error

    @classmethod
    def render_to_directory(
        cls,
        document: PDFDocument,
        output_directory: str | Path,
        *,
        dpi: int = DEFAULT_DPI,
        pages: Iterable[int] | None = None,
    ) -> tuple[Path, ...]:
        """Render selected pages and save them as PNG files."""
        return cls.save(
            cls.render(document, dpi=dpi, pages=pages),
            output_directory,
        )


def _validate_dpi(dpi: int) -> None:
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise PageRenderError("DPI must be a positive integer")


def _normalize_page_numbers(
    pages: Iterable[int] | None,
    page_count: int,
) -> tuple[int, ...]:
    if pages is None:
        return tuple(range(1, page_count + 1))

    page_numbers = tuple(pages)
    if len(set(page_numbers)) != len(page_numbers):
        raise PageRenderError("Page numbers must not contain duplicates")
    for page_number in page_numbers:
        if isinstance(page_number, bool) or not isinstance(page_number, int):
            raise PageRenderError("Page numbers must be integers")
        if not 1 <= page_number <= page_count:
            raise PageRenderError(
                f"Page number {page_number} is outside the range 1-{page_count}"
            )
    return page_numbers
