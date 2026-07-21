"""High-level orchestration from a PDF path to an immutable Score."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from drum_score_converter.page_renderer import (
    DEFAULT_DPI,
    PageRenderer,
    PageRenderError,
    RenderedPage,
)
from drum_score_converter.pdf_loader import PDFDocument, PDFLoader, PDFLoadError
from drum_score_converter.recognition_model import (
    RecognitionResult,
    RecognizedTimeSignature,
)
from drum_score_converter.recognition_validator import (
    RecognitionValidationError,
    RecognitionValidator,
)
from drum_score_converter.score_builder import ScoreBuilder, ScoreBuildError
from drum_score_converter.score_model import Part, Score
from drum_score_converter.vision_recognizer import RecognitionError, VisionRecognizer

type _PipelineStage = Literal[
    "pdf_load",
    "page_render",
    "recognition",
    "validation",
    "score_build",
    "score_merge",
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
    """Orchestrate PDF loading, page recognition, and score construction."""

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
        """Process PDF pages sequentially in memory and return one merged Score."""
        try:
            document = PDFLoader.load(pdf_path, password=password)
        except PDFLoadError as error:
            raise RecognitionPipelineError(
                "The PDF could not be loaded.",
                stage="pdf_load",
            ) from error

        merged_score: Score | None = None
        for page_number in range(1, document.page_count + 1):
            rendered_page = self._render_page(document, page_number)
            recognition_result = await self._recognize_page(
                rendered_page,
                page_number,
            )
            recognition_result = self._inherit_time_signatures(
                recognition_result,
                merged_score,
            )
            self._validate_result(recognition_result, page_number)
            page_score = self._build_score(recognition_result, page_number)
            if merged_score is None:
                merged_score = page_score
            else:
                merged_score = self._merge_page_score(
                    merged_score,
                    page_score,
                    page_number,
                )

        if merged_score is not None:
            return merged_score

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

    def _inherit_time_signatures(
        self,
        result: RecognitionResult,
        merged_score: Score | None,
    ) -> RecognitionResult:
        page = result.pages[0]
        normalized_parts = []
        for part_index, part in enumerate(page.parts):
            current_signature: RecognizedTimeSignature | None = None
            if merged_score is not None and part_index < len(merged_score.parts):
                previous = merged_score.parts[part_index].measures[-1].time_signature
                current_signature = RecognizedTimeSignature(
                    previous.numerator,
                    previous.denominator,
                )

            normalized_measures = []
            for measure in part.measures:
                if measure.time_signature is not None:
                    current_signature = measure.time_signature
                    normalized_measures.append(measure)
                elif current_signature is not None:
                    normalized_measures.append(
                        replace(measure, time_signature=current_signature)
                    )
                else:
                    normalized_measures.append(measure)
            normalized_parts.append(
                replace(part, measures=tuple(normalized_measures))
            )

        return replace(
            result,
            pages=(replace(page, parts=tuple(normalized_parts)),),
        )

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

    def _merge_page_score(
        self,
        merged_score: Score,
        page_score: Score,
        page_number: int,
    ) -> Score:
        if len(merged_score.parts) != len(page_score.parts):
            raise RecognitionPipelineError(
                f"Part count does not match on page {page_number}.",
                stage="score_merge",
                page_number=page_number,
            )

        merged_parts: list[Part] = []
        for existing_part, page_part in zip(
            merged_score.parts,
            page_score.parts,
            strict=True,
        ):
            if existing_part.name != page_part.name:
                raise RecognitionPipelineError(
                    f"Part order or name does not match on page {page_number}.",
                    stage="score_merge",
                    page_number=page_number,
                )
            try:
                page_measures = page_part.measures
                if (
                    page_measures[0].number
                    <= existing_part.measures[-1].number
                ):
                    number_shift = (
                        existing_part.measures[-1].number
                        + 1
                        - page_measures[0].number
                    )
                    page_measures = tuple(
                        replace(measure, number=measure.number + number_shift)
                        for measure in page_measures
                    )
                merged_parts.append(
                    Part(
                        name=existing_part.name,
                        measures=existing_part.measures + page_measures,
                    )
                )
            except (TypeError, ValueError) as error:
                raise RecognitionPipelineError(
                    f"Scores could not be merged at page {page_number}.",
                    stage="score_merge",
                    page_number=page_number,
                ) from error

        try:
            return Score(parts=tuple(merged_parts), title=merged_score.title)
        except (TypeError, ValueError) as error:
            raise RecognitionPipelineError(
                f"Scores could not be merged at page {page_number}.",
                stage="score_merge",
                page_number=page_number,
            ) from error
