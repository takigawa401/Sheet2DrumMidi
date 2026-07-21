"""Integration tests for the high-level recognition pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

import pytest
from pypdf import PdfWriter

from drum_score_converter.midi_exporter import MIDIExporter
from drum_score_converter.musicxml_exporter import MusicXMLExporter
from drum_score_converter.page_renderer import (
    PageRenderer,
    PageRenderError,
    RenderedPage,
)
from drum_score_converter.pdf_loader import PDFDocument, PDFLoadError
from drum_score_converter.recognition_model import (
    RecognitionResult,
    RecognizedFraction,
    RecognizedInstrument,
    RecognizedMeasure,
    RecognizedNote,
    RecognizedPage,
    RecognizedPart,
    RecognizedTimeSignature,
)
from drum_score_converter.recognition_pipeline import (
    RecognitionPipeline,
    RecognitionPipelineError,
)
from drum_score_converter.recognition_validator import (
    RecognitionValidationError,
    RecognitionValidationErrorCode,
    RecognitionValidator,
)
from drum_score_converter.score_builder import ScoreBuilder, ScoreBuildError
from drum_score_converter.score_model import Score
from drum_score_converter.vision_recognizer import CommunicationError


def _write_pdf(
    path: Path,
    *,
    page_count: int = 1,
    password: str | None = None,
) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    if password is not None:
        writer.encrypt(password, algorithm="AES-256")
    with path.open("wb") as output:
        writer.write(output)


def _recognition_result(
    page_number: int,
    *,
    instrument: str = "snare",
    part_name: str = "Drum Kit",
    measure_number: int | None = None,
) -> RecognitionResult:
    note = RecognizedNote(
        RecognizedInstrument(instrument),
        RecognizedFraction(0, 1),
        RecognizedFraction(1, 1),
    )
    measure = RecognizedMeasure(
        page_number if measure_number is None else measure_number,
        RecognizedTimeSignature(4, 4),
        (note,),
        tempo_bpm=120,
    )
    part = RecognizedPart(part_name, (measure,))
    return RecognitionResult(
        (RecognizedPage(page_number, (part,)),),
        title="Pipeline Test",
    )


class _FakeRecognizer:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        self.calls.append(page.page_number)
        return _recognition_result(page.page_number)


class _FailingRecognizer:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        self.calls.append(page.page_number)
        raise CommunicationError("provider unavailable")


class _FailingOnPageRecognizer:
    def __init__(self, fail_page: int) -> None:
        self.fail_page = fail_page
        self.calls: list[int] = []

    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        self.calls.append(page.page_number)
        if page.page_number == self.fail_page:
            raise CommunicationError("provider unavailable")
        return _recognition_result(page.page_number)


class _MismatchedPartRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        part_name = "Percussion" if page.page_number == 2 else "Drum Kit"
        return _recognition_result(page.page_number, part_name=part_name)


class _ResetMeasureNumberRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        return _recognition_result(page.page_number, measure_number=1)


class _MissingContinuationTimeSignatureRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        result = _recognition_result(page.page_number)
        if page.page_number == 1:
            return result
        recognized_page = result.pages[0]
        part = recognized_page.parts[0]
        measure = part.measures[0]
        missing_signature = RecognizedMeasure(
            measure.number,
            None,
            measure.events,
            measure.tempo_bpm,
        )
        return RecognitionResult(
            (
                RecognizedPage(
                    page.page_number,
                    (RecognizedPart(part.name, (missing_signature,)),),
                ),
            ),
            title=result.title,
        )


class _WrongPageRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        return _recognition_result(page.page_number + 1)


class _MultiplePageRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        first = _recognition_result(page.page_number).pages[0]
        second = _recognition_result(page.page_number + 1).pages[0]
        return RecognitionResult((first, second))


class _UnknownInstrumentRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        return _recognition_result(page.page_number, instrument="unknown stack")


class _DuplicateEventRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        result = _recognition_result(page.page_number)
        recognized_page = result.pages[0]
        measure = recognized_page.parts[0].measures[0]
        event = measure.events[0]
        duplicate_measure = RecognizedMeasure(
            measure.number,
            measure.time_signature,
            (event, event),
            measure.tempo_bpm,
        )
        part = RecognizedPart("Drum Kit", (duplicate_measure,))
        return RecognitionResult((RecognizedPage(page.page_number, (part,)),))


def test_processes_one_page_pdf_and_exporters_accept_score(
    tmp_path: Path,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)
    recognizer = _FakeRecognizer()

    score = asyncio.run(RecognitionPipeline(recognizer, dpi=72).process(path))

    assert isinstance(score, Score)
    assert recognizer.calls == [1]
    assert score.title == "Pipeline Test"
    assert MusicXMLExporter().to_string(score).startswith("<?xml")
    assert MIDIExporter().to_bytes(score).startswith(b"MThd")


def test_processes_password_protected_pdf(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    _write_pdf(path, password="secret")

    score = asyncio.run(
        RecognitionPipeline(_FakeRecognizer(), dpi=72).process(
            path,
            password="secret",
        )
    )

    assert score.parts[0].name == "Drum Kit"


def test_calls_render_recognize_and_build_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, page_count=2)
    calls: list[str] = []
    original_render = PageRenderer.render
    original_validate = RecognitionValidator.validate
    original_build = ScoreBuilder.build

    def tracked_render(
        document: PDFDocument,
        *,
        dpi: int,
        pages: Iterable[int] | None = None,
    ) -> tuple[RenderedPage, ...]:
        requested = tuple(pages or ())
        calls.append(f"render:{requested[0]}")
        return original_render(document, dpi=dpi, pages=requested)

    def tracked_build(
        builder: ScoreBuilder,
        result: RecognitionResult,
    ) -> Score:
        calls.append(f"build:{result.pages[0].page_number}")
        return original_build(builder, result)

    def tracked_validate(
        validator: RecognitionValidator,
        result: RecognitionResult,
    ) -> tuple[object, ...]:
        calls.append(f"validate:{result.pages[0].page_number}")
        return original_validate(validator, result)

    class TrackingRecognizer:
        async def recognize(self, page: RenderedPage) -> RecognitionResult:
            calls.append(f"recognize:{page.page_number}")
            return _recognition_result(page.page_number)

    monkeypatch.setattr(PageRenderer, "render", tracked_render)
    monkeypatch.setattr(RecognitionValidator, "validate", tracked_validate)
    monkeypatch.setattr(ScoreBuilder, "build", tracked_build)

    asyncio.run(RecognitionPipeline(TrackingRecognizer(), dpi=72).process(path))

    assert calls == [
        "render:1",
        "recognize:1",
        "validate:1",
        "build:1",
        "render:2",
        "recognize:2",
        "validate:2",
        "build:2",
    ]


def test_validation_error_is_wrapped_before_score_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)
    build_called = False

    def tracked_build(
        builder: ScoreBuilder,
        result: RecognitionResult,
    ) -> Score:
        nonlocal build_called
        build_called = True
        raise AssertionError("ScoreBuilder must not be called")

    monkeypatch.setattr(ScoreBuilder, "build", tracked_build)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(
            RecognitionPipeline(_DuplicateEventRecognizer(), dpi=72).process(path)
        )

    assert caught.value.stage == "validation"
    assert caught.value.page_number == 1
    assert isinstance(caught.value.__cause__, RecognitionValidationError)
    assert (
        caught.value.__cause__.code
        is RecognitionValidationErrorCode.DUPLICATE_EVENT
    )
    assert build_called is False


def test_invalid_pdf_error_is_wrapped_with_load_stage(tmp_path: Path) -> None:
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"not a PDF")

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(RecognitionPipeline(_FakeRecognizer()).process(path))

    assert caught.value.stage == "pdf_load"
    assert caught.value.page_number is None
    assert isinstance(caught.value.__cause__, PDFLoadError)


def test_page_render_error_is_wrapped_with_page_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)

    def fail_render(
        document: PDFDocument,
        *,
        dpi: int,
        pages: Iterable[int] | None = None,
    ) -> tuple[RenderedPage, ...]:
        raise PageRenderError("render failed")

    monkeypatch.setattr(PageRenderer, "render", fail_render)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(RecognitionPipeline(_FakeRecognizer()).process(path))

    assert caught.value.stage == "page_render"
    assert caught.value.page_number == 1
    assert isinstance(caught.value.__cause__, PageRenderError)


@pytest.mark.parametrize("page_count", [0, 2])
def test_renderer_must_return_exactly_one_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page_count: int,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)
    rendered = RenderedPage(1, b"png", 1, 1, 72)

    def invalid_render(
        document: PDFDocument,
        *,
        dpi: int,
        pages: Iterable[int] | None = None,
    ) -> tuple[RenderedPage, ...]:
        return (rendered,) * page_count

    monkeypatch.setattr(PageRenderer, "render", invalid_render)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(RecognitionPipeline(_FakeRecognizer()).process(path))

    assert caught.value.stage == "page_render"
    assert caught.value.page_number == 1


def test_rendered_page_number_must_match_requested_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)

    def wrong_page_render(
        document: PDFDocument,
        *,
        dpi: int,
        pages: Iterable[int] | None = None,
    ) -> tuple[RenderedPage, ...]:
        return (RenderedPage(2, b"png", 1, 1, dpi),)

    monkeypatch.setattr(PageRenderer, "render", wrong_page_render)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(RecognitionPipeline(_FakeRecognizer()).process(path))

    assert caught.value.stage == "page_render"
    assert caught.value.page_number == 1


@pytest.mark.parametrize(
    "recognizer",
    [_WrongPageRecognizer(), _MultiplePageRecognizer()],
)
def test_recognizer_contract_violations_are_rejected(
    tmp_path: Path,
    recognizer: _WrongPageRecognizer | _MultiplePageRecognizer,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(RecognitionPipeline(recognizer, dpi=72).process(path))

    assert caught.value.stage == "recognition"
    assert caught.value.page_number == 1


def test_recognition_error_is_wrapped_and_stops_processing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)
    recognizer = _FailingRecognizer()

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(RecognitionPipeline(recognizer, dpi=72).process(path))

    assert recognizer.calls == [1]
    assert caught.value.stage == "recognition"
    assert caught.value.page_number == 1
    assert isinstance(caught.value.__cause__, CommunicationError)


def test_failure_on_second_page_reports_page_number_and_stops(
    tmp_path: Path,
) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path, page_count=3)
    recognizer = _FailingOnPageRecognizer(fail_page=2)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(RecognitionPipeline(recognizer, dpi=72).process(path))

    assert recognizer.calls == [1, 2]
    assert caught.value.stage == "recognition"
    assert caught.value.page_number == 2
    assert isinstance(caught.value.__cause__, CommunicationError)


def test_score_build_error_is_wrapped_with_page_context(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(
            RecognitionPipeline(
                _UnknownInstrumentRecognizer(),
                dpi=72,
            ).process(path)
        )

    assert caught.value.stage == "score_build"
    assert caught.value.page_number == 1
    assert isinstance(caught.value.__cause__, ScoreBuildError)


def test_multiple_page_pdf_is_processed_in_order_and_measures_are_merged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "multiple.pdf"
    _write_pdf(path, page_count=2)
    recognizer = _FakeRecognizer()

    score = asyncio.run(RecognitionPipeline(recognizer, dpi=72).process(path))

    assert recognizer.calls == [1, 2]
    assert [measure.number for measure in score.parts[0].measures] == [1, 2]


def test_merge_rejects_mismatched_parts(tmp_path: Path) -> None:
    path = tmp_path / "multiple.pdf"
    _write_pdf(path, page_count=2)

    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(
            RecognitionPipeline(_MismatchedPartRecognizer(), dpi=72).process(path)
        )

    assert caught.value.stage == "score_merge"
    assert caught.value.page_number == 2


def test_page_local_measure_numbers_are_shifted_during_merge(tmp_path: Path) -> None:
    path = tmp_path / "multiple.pdf"
    _write_pdf(path, page_count=2)

    score = asyncio.run(
        RecognitionPipeline(_ResetMeasureNumberRecognizer(), dpi=72).process(path)
    )

    assert [measure.number for measure in score.parts[0].measures] == [1, 2]


def test_time_signature_is_inherited_across_pages(tmp_path: Path) -> None:
    path = tmp_path / "multiple.pdf"
    _write_pdf(path, page_count=2)

    score = asyncio.run(
        RecognitionPipeline(
            _MissingContinuationTimeSignatureRecognizer(),
            dpi=72,
        ).process(path)
    )

    signatures = [
        (measure.time_signature.numerator, measure.time_signature.denominator)
        for measure in score.parts[0].measures
    ]
    assert signatures == [(4, 4), (4, 4)]


def test_pipeline_does_not_write_rendered_images(tmp_path: Path) -> None:
    path = tmp_path / "score.pdf"
    _write_pdf(path)
    before = {item.name for item in tmp_path.iterdir()}

    asyncio.run(RecognitionPipeline(_FakeRecognizer(), dpi=72).process(path))

    assert {item.name for item in tmp_path.iterdir()} == before
    assert not tuple(tmp_path.glob("*.png"))


def test_pipeline_public_api_is_exported() -> None:
    from drum_score_converter import (
        RecognitionPipeline as PublicRecognitionPipeline,
    )
    from drum_score_converter import (
        RecognitionPipelineError as PublicRecognitionPipelineError,
    )

    assert PublicRecognitionPipeline is RecognitionPipeline
    assert PublicRecognitionPipelineError is RecognitionPipelineError
