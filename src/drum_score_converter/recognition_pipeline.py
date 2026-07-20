"""High-level orchestration from a PDF path to an immutable Score."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from drum_score_converter.page_renderer import (
    DEFAULT_DPI,
    PageRenderer,
    PageRenderError,
    RenderedPage,
)
from drum_score_converter.pdf_loader import PDFDocument, PDFLoader, PDFLoadError
from drum_score_converter.recognition_model import RecognitionResult
from drum_score_converter.recognition_validator import (
    RecognitionValidationError,
    RecognitionValidator,
)
from drum_score_converter.score_builder import ScoreBuilder, ScoreBuildError
from drum_score_converter.score_model import Score
from drum_score_converter.vision_recognizer import RecognitionError, VisionRecognizer

type _PipelineStage = Literal[
    "pdf_load",
    "page_render",
    "recognition",
    "validation",
    "score_build",
    "pipeline",
]


class RecognitionPipelineError(Exception):
    """A pipeline failure with its stage and optional source page number."""

    def __init__(
        self,
        message: str,
        *,
        stage: _PipelineStage,
        page_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.page_number = page_number


class RecognitionPipeline:
    """Orchestrate PDF loading, rendering, recognition, and score building.

    The MVP accepts exactly one PDF page. It does not aggregate page-level
    recognition results or scores.
    """

    def __init__(
        self,
        recognizer: VisionRecognizer,
        *,
        dpi: int = DEFAULT_DPI,
    ) -> None:
        self._recognizer = recognizer
        self._dpi = dpi
        self._validator = RecognitionValidator()
        self._score_builder = ScoreBuilder()

    async def process(
        self,
        pdf_path: str | Path,
        *,
        password: str | None = None,
    ) -> Score:
        """Process one PDF page entirely in memory and return its Score."""
        try:
            document = PDFLoader.load(pdf_path, password=password)
        except PDFLoadError as error:
            raise RecognitionPipelineError(
                "The PDF could not be loaded.",
                stage="pdf_load",
            ) from error

        if document.page_count != 1:
            raise RecognitionPipelineError(
                "RecognitionPipeline currently supports exactly one PDF page.",
                stage="pipeline",
            )

        for page_number in range(1, document.page_count + 1):
            rendered_page = self._render_page(document, page_number)
            recognition_result = await self._recognize_page(
                rendered_page,
                page_number,
            )
            self._validate_result(recognition_result, page_number)
            return self._build_score(recognition_result, page_number)

        raise RecognitionPipelineError(
            "The PDF does not contain a processable page.",
            stage="pipeline",
        )

    def _render_page(
        self,
        document: PDFDocument,
        page_number: int,
    ) -> RenderedPage:
        try:
            rendered_pages = PageRenderer.render(
                document,
                dpi=self._dpi,
                pages=(page_number,),
            )
        except PageRenderError as error:
            raise RecognitionPipelineError(
                f"Page rendering failed for page {page_number}.",
                stage="page_render",
                page_number=page_number,
            ) from error

        if len(rendered_pages) != 1:
            raise RecognitionPipelineError(
                f"PageRenderer returned an invalid result for page {page_number}.",
                stage="page_render",
                page_number=page_number,
            )
        rendered_page = rendered_pages[0]
        if not isinstance(rendered_page, RenderedPage):
            raise RecognitionPipelineError(
                f"PageRenderer returned an invalid page for page {page_number}.",
                stage="page_render",
                page_number=page_number,
            )
        if rendered_page.page_number != page_number:
            raise RecognitionPipelineError(
                "Rendered page number does not match the requested page number.",
                stage="page_render",
                page_number=page_number,
            )
        return rendered_page

    async def _recognize_page(
        self,
        page: RenderedPage,
        page_number: int,
    ) -> RecognitionResult:
        try:
            result = await self._recognizer.recognize(page)
        except RecognitionError as error:
            raise RecognitionPipelineError(
                f"Vision recognition failed for page {page_number}.",
                stage="recognition",
                page_number=page_number,
            ) from error

        if not isinstance(result, RecognitionResult):
            raise RecognitionPipelineError(
                f"VisionRecognizer returned an invalid result for page {page_number}.",
                stage="recognition",
                page_number=page_number,
            )
        if len(result.pages) != 1:
            raise RecognitionPipelineError(
                "VisionRecognizer must return exactly one recognized page.",
                stage="recognition",
                page_number=page_number,
            )
        if result.pages[0].page_number != page_number:
            raise RecognitionPipelineError(
                "Recognized page number does not match the rendered page number.",
                stage="recognition",
                page_number=page_number,
            )
        return result

    def _validate_result(
        self,
        result: RecognitionResult,
        page_number: int,
    ) -> None:
        try:
            self._validator.validate(result)
        except RecognitionValidationError as error:
            raise RecognitionPipelineError(
                f"Recognition validation failed for page {page_number}.",
                stage="validation",
                page_number=page_number,
            ) from error

    def _build_score(
        self,
        result: RecognitionResult,
        page_number: int,
    ) -> Score:
        try:
            return self._score_builder.build(result)
        except ScoreBuildError as error:
            raise RecognitionPipelineError(
                f"Score construction failed for page {page_number}.",
                stage="score_build",
                page_number=page_number,
            ) from error
