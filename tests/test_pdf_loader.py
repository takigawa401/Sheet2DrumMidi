"""Tests for PDF loading and metadata extraction."""

from dataclasses import FrozenInstanceError, fields
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.errors import DependencyError

import drum_score_converter.pdf_loader as pdf_loader_module
from drum_score_converter.pdf_loader import PDFDocument, PDFLoader, PDFLoadError


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


def test_load_normal_pdf(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((612, 792),))

    document = PDFLoader.load(path)

    assert isinstance(document, PDFDocument)
    assert document.path == path.resolve()
    assert document.content == path.read_bytes()
    assert document.page_count == 1
    assert document.page_sizes == ((612.0, 792.0),)
    assert document.is_encrypted is False

    content_reader = PdfReader(BytesIO(document.content))
    assert content_reader.is_encrypted is False
    assert len(content_reader.pages) == document.page_count
    content_reader.close()


def test_load_reports_page_count_and_page_sizes(tmp_path: Path) -> None:
    path = tmp_path / "different-sizes.pdf"
    _write_pdf(path, ((612, 792), (400, 300), (595.5, 842.25)))

    document = PDFLoader().load(path)

    assert document.page_count == 3
    assert document.page_sizes == (
        (612.0, 792.0),
        (400.0, 300.0),
        (595.5, 842.25),
    )


def test_load_encrypted_pdf_with_password(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    _write_pdf(path, ((320, 240),), password="correct-password")

    document = PDFLoader.load(path, password="correct-password")

    assert document.page_count == 1
    assert document.page_sizes == ((320.0, 240.0),)
    assert document.is_encrypted is True

    content_reader = PdfReader(BytesIO(document.content))
    assert content_reader.is_encrypted is False
    assert len(content_reader.pages) == document.page_count
    assert (
        float(content_reader.pages[0].mediabox.width),
        float(content_reader.pages[0].mediabox.height),
    ) == document.page_sizes[0]
    content_reader.close()


@pytest.mark.parametrize("password", [None, "wrong-password"])
def test_load_encrypted_pdf_rejects_missing_or_wrong_password(
    tmp_path: Path, password: str | None
) -> None:
    path = tmp_path / "encrypted.pdf"
    _write_pdf(path, ((320, 240),), password="correct-password")

    with pytest.raises(PDFLoadError, match="password"):
        PDFLoader.load(path, password=password)


def test_load_rejects_nonexistent_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.pdf"

    with pytest.raises(PDFLoadError, match="does not exist"):
        PDFLoader.load(path)


def test_load_rejects_invalid_pdf(tmp_path: Path) -> None:
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"this is not a PDF")

    with pytest.raises(PDFLoadError, match="Invalid PDF"):
        PDFLoader.load(path)


def test_load_wraps_unsupported_encryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((612, 792),))

    def raise_dependency_error(*args: object, **kwargs: object) -> None:
        raise DependencyError("unsupported encryption backend")

    monkeypatch.setattr(pdf_loader_module, "PdfReader", raise_dependency_error)

    with pytest.raises(PDFLoadError, match="unsupported encryption"):
        PDFLoader.load(path)


def test_pdf_document_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, ((612, 792),))
    document = PDFLoader.load(path)

    with pytest.raises(FrozenInstanceError):
        setattr(document, "page_count", 2)


def test_pdf_document_does_not_retain_password(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    _write_pdf(path, ((320, 240),), password="correct-password")

    document = PDFLoader.load(path, password="correct-password")

    assert "password" not in {field.name for field in fields(document)}
