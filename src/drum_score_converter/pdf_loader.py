"""PDF loading and metadata extraction."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.errors import DependencyError, PyPdfError, WrongPasswordError


class PDFLoadError(Exception):
    """Raised when a PDF cannot be loaded or decrypted."""


@dataclass(frozen=True, slots=True)
class PDFDocument:
    """Immutable content and metadata for a loaded PDF.

    Page sizes are stored as ``(width, height)`` pairs in PDF points.
    """

    path: Path
    content: bytes
    page_count: int
    page_sizes: tuple[tuple[float, float], ...]
    is_encrypted: bool


class PDFLoader:
    """Load reusable PDF content and metadata using pypdf."""

    @staticmethod
    def load(path: str | Path, password: str | None = None) -> PDFDocument:
        """Load a PDF and return its immutable content and metadata."""
        source_path = Path(path)
        if not source_path.is_file():
            raise PDFLoadError(f"PDF file does not exist: {source_path}")

        try:
            content = source_path.read_bytes()
        except OSError as error:
            raise PDFLoadError(f"PDF file cannot be read: {source_path}") from error

        reader: PdfReader | None = None
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            is_encrypted = reader.is_encrypted
            if is_encrypted:
                result = reader.decrypt(password or "")
                if result == PasswordType.NOT_DECRYPTED:
                    raise PDFLoadError("PDF password is missing or incorrect")
                loaded_content = _create_decrypted_content(reader)
            else:
                loaded_content = content

            page_sizes = tuple(
                (float(page.mediabox.width), float(page.mediabox.height))
                for page in reader.pages
            )
        except PDFLoadError:
            raise
        except WrongPasswordError as error:
            raise PDFLoadError("PDF password is missing or incorrect") from error
        except (DependencyError, NotImplementedError) as error:
            raise PDFLoadError("PDF uses unsupported encryption") from error
        except (PyPdfError, ValueError, TypeError, KeyError, EOFError) as error:
            raise PDFLoadError(f"Invalid PDF file: {source_path}") from error
        finally:
            if reader is not None:
                reader.close()

        return PDFDocument(
            path=source_path.resolve(),
            content=loaded_content,
            page_count=len(page_sizes),
            page_sizes=page_sizes,
            is_encrypted=is_encrypted,
        )


def _create_decrypted_content(reader: PdfReader) -> bytes:
    output = BytesIO()
    writer = PdfWriter(clone_from=reader)
    writer.write(output)
    return output.getvalue()
