"""Split dense page images and merge page-local OpenAI recognition results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol, cast

import pymupdf

from drum_score_converter.page_renderer import RenderedPage
from drum_score_converter.recognition_model import (
    RecognitionResult,
    RecognizedMeasure,
    RecognizedPage,
    RecognizedPart,
)
from drum_score_converter.vision_recognizer import RecognitionConversionError

_MIN_SEGMENTED_HEIGHT = 2400
_SEGMENT_COUNT = 4
_ANALYSIS_DPI = 72


class _Rect(Protocol):
    width: float
    height: float


class _Pixmap(Protocol):
    width: int
    height: int
    samples: bytes

    def tobytes(self, output: str) -> bytes: ...


class _ImagePage(Protocol):
    rect: _Rect

    def get_pixmap(self, **kwargs: object) -> _Pixmap: ...


class _ImageDocument(Protocol):
    def __getitem__(self, page_number: int) -> _ImagePage: ...

    def close(self) -> None: ...


_open_image = cast(Callable[..., _ImageDocument], pymupdf.open)
_make_rect = cast(Callable[[float, float, float, float], object], pymupdf.Rect)
_make_matrix = cast(Callable[[float, float], object], pymupdf.Matrix)


def split_openai_page(page: RenderedPage) -> tuple[RenderedPage, ...]:
    """Split a dense portrait page at whitespace near equal-height boundaries."""
    if page.height < _MIN_SEGMENTED_HEIGHT or page.height <= page.width:
        return (page,)

    try:
        image = _open_image(stream=page.content, filetype="png")
        try:
            image_page = image[0]
            analysis = image_page.get_pixmap(
                dpi=_ANALYSIS_DPI,
                alpha=False,
                colorspace=pymupdf.csGRAY,
            )
            dark_counts = _row_dark_counts(analysis)
            boundaries = _segment_boundaries(dark_counts, analysis.width)
            if len(boundaries) <= 2:
                return (page,)

            scale = page.width / image_page.rect.width
            segments = []
            for top, bottom in zip(boundaries, boundaries[1:]):
                if not _contains_notation(
                    dark_counts,
                    analysis.width,
                    top,
                    bottom,
                ):
                    continue
                clip = _make_rect(
                    0,
                    image_page.rect.height * top / analysis.height,
                    image_page.rect.width,
                    image_page.rect.height * bottom / analysis.height,
                )
                pixmap = image_page.get_pixmap(
                    matrix=_make_matrix(scale, scale),
                    clip=clip,
                    alpha=False,
                )
                segments.append(
                    RenderedPage(
                        page_number=page.page_number,
                        content=pixmap.tobytes("png"),
                        width=pixmap.width,
                        height=pixmap.height,
                        dpi=page.dpi,
                        media_type=page.media_type,
                    )
                )
            return tuple(segments) or (page,)
        finally:
            image.close()
    except (RuntimeError, TypeError, ValueError) as error:
        raise RecognitionConversionError(
            "Rendered page could not be segmented for vision recognition."
        ) from error


def _row_dark_counts(pixmap: _Pixmap) -> tuple[int, ...]:
    samples = pixmap.samples
    return tuple(
        sum(
            value < 245
            for value in samples[
                row * pixmap.width : (row + 1) * pixmap.width
            ]
        )
        for row in range(pixmap.height)
    )


def _segment_boundaries(
    dark_counts: Sequence[int],
    width: int,
) -> tuple[int, ...]:
    height = len(dark_counts)
    blank_limit = max(1, width // 500)
    blank_rows = tuple(count <= blank_limit for count in dark_counts)
    boundaries = [0]
    search_radius = height // 8
    for index in range(1, _SEGMENT_COUNT):
        target = height * index // _SEGMENT_COUNT
        start = max(boundaries[-1] + 1, target - search_radius)
        end = min(height - 1, target + search_radius)
        runs = _blank_runs(blank_rows, start, end)
        if runs:
            run_start, run_end = min(
                runs,
                key=lambda run: abs((run[0] + run[1]) // 2 - target),
            )
            boundary = (run_start + run_end) // 2
            if boundary > boundaries[-1]:
                boundaries.append(boundary)
    boundaries.append(height)
    return tuple(boundaries)


def _blank_runs(
    blank_rows: Sequence[bool],
    start: int,
    end: int,
) -> tuple[tuple[int, int], ...]:
    runs = []
    run_start: int | None = None
    for row in range(start, end + 1):
        if blank_rows[row] and run_start is None:
            run_start = row
        elif not blank_rows[row] and run_start is not None:
            if row - run_start >= 3:
                runs.append((run_start, row - 1))
            run_start = None
    if run_start is not None and end + 1 - run_start >= 3:
        runs.append((run_start, end))
    return tuple(runs)


def _contains_notation(
    dark_counts: Sequence[int],
    width: int,
    top: int,
    bottom: int,
) -> bool:
    area = width * (bottom - top)
    return sum(dark_counts[top:bottom]) >= area // 1000


def merge_openai_segments(
    results: Sequence[RecognitionResult],
) -> RecognitionResult:
    """Merge ordered segment results into one page-level RecognitionResult."""
    if not results:
        raise RecognitionConversionError("Vision recognition returned no segments.")
    page_number = results[0].pages[0].page_number
    title = next(
        (result.title for result in results if result.title is not None),
        None,
    )
    usable = [
        result
        for result in results
        if any(part.measures for part in result.pages[0].parts)
    ]
    if not usable:
        return results[0]

    first_page = usable[0].pages[0]
    part_count = len(first_page.parts)
    combined_measures: list[list[RecognizedMeasure]] = [
        [] for _ in range(part_count)
    ]
    part_names = [part.name for part in first_page.parts]
    part_confidences: list[list[float]] = [[] for _ in range(part_count)]
    page_confidences: list[float] = []
    warnings = []

    for result in usable:
        page = result.pages[0]
        if page.page_number != page_number or len(page.parts) != part_count:
            raise RecognitionConversionError(
                "Vision segment results cannot be combined into one page."
            )
        if page.confidence is not None:
            page_confidences.append(page.confidence)
        offsets = tuple(len(measures) for measures in combined_measures)
        for part_index, part in enumerate(page.parts):
            if part.name != part_names[part_index]:
                raise RecognitionConversionError(
                    "Vision segment part names do not match."
                )
            if part.confidence is not None:
                part_confidences[part_index].append(part.confidence)
            for measure in part.measures:
                combined_measures[part_index].append(
                    replace(
                        measure,
                        number=len(combined_measures[part_index]) + 1,
                    )
                )
        for warning in result.warnings:
            location = warning.location
            if (
                location is not None
                and location.part_index is not None
                and location.measure_index is not None
                and location.part_index < len(offsets)
            ):
                location = replace(
                    location,
                    measure_index=(
                        location.measure_index + offsets[location.part_index]
                    ),
                )
            warnings.append(replace(warning, location=location))

    parts = tuple(
        RecognizedPart(
            name=part_names[index],
            measures=tuple(combined_measures[index]),
            confidence=(
                min(part_confidences[index])
                if part_confidences[index]
                else None
            ),
        )
        for index in range(part_count)
    )
    return RecognitionResult(
        pages=(
            RecognizedPage(
                page_number=page_number,
                parts=parts,
                confidence=min(page_confidences) if page_confidences else None,
            ),
        ),
        title=title,
        warnings=tuple(warnings),
    )
