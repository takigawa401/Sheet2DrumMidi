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
) -> RecognitionResult:
    note = RecognizedNote(
        RecognizedInstrument(instrument),
        RecognizedFraction(0, 1),
        RecognizedFraction(1, 1),
    )
    measure = RecognizedMeasure(
        1,
        RecognizedTimeSignature(4, 4),
        (note,),
        tempo_bpm=120,
    )
    part = RecognizedPart("Drum Kit", (measure,))
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
    _write_pdf(path)
    calls: list[str] = []
    original_render = PageRenderer.render
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

    class TrackingRecognizer:
        async def recognize(self, page: RenderedPage) -> RecognitionResult:
            calls.append(f"recognize:{page.page_number}")
            return _recognition_result(page.page_number)

    monkeypatch.setattr(PageRenderer, "render", tracked_render)
    monkeypatch.setattr(ScoreBuilder, "build", tracked_build)

    asyncio.run(RecognitionPipeline(TrackingRecognizer(), dpi=72).process(path))

    assert calls == ["render:1", "recognize:1", "build:1"]


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


def test_multiple_page_pdf_is_rejected_before_page_processing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "multiple.pdf"
    _write_pdf(path, page_count=3)
    recognizer = _FakeRecognizer()

    with pytest.raises(RecognitionPipelineError, match="exactly one") as caught:
        asyncio.run(RecognitionPipeline(recognizer, dpi=72).process(path))

    assert caught.value.stage == "pipeline"
    assert caught.value.page_number is None
    assert recognizer.calls == []


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
