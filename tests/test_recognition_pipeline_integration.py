"""End-to-end integration tests using a project-owned PDF and fake vision."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

import mido
import pytest

from drum_score_converter.midi_exporter import DRUM_CHANNEL, MIDIExporter
from drum_score_converter.musicxml_exporter import MusicXMLExporter
from drum_score_converter.page_renderer import RenderedPage
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
    RecognitionValidationWarning,
    RecognitionValidator,
)
from drum_score_converter.score_model import Score

_PDF_FIXTURE = Path(__file__).parent / "fixtures" / "minimal_drum_score.pdf"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _fraction(numerator: int, denominator: int = 1) -> RecognizedFraction:
    return RecognizedFraction(numerator, denominator)


def _note(
    instrument: str,
    offset: int,
    velocity: int,
) -> RecognizedNote:
    return RecognizedNote(
        RecognizedInstrument(instrument),
        _fraction(offset),
        _fraction(1),
        velocity=velocity,
        accent=False,
        ghost=False,
    )


def _valid_recognition(page_number: int) -> RecognitionResult:
    events = (
        _note("kick", 0, 110),
        _note("closed hi-hat", 0, 80),
        _note("snare", 1, 100),
        _note("closed hi-hat", 1, 80),
        _note("kick", 2, 110),
        _note("closed hi-hat", 2, 80),
        _note("snare", 3, 100),
        _note("closed hi-hat", 3, 80),
    )
    measure = RecognizedMeasure(
        1,
        RecognizedTimeSignature(4, 4),
        events,
        tempo_bpm=120,
    )
    part = RecognizedPart("Drum Kit", (measure,))
    return RecognitionResult(
        (RecognizedPage(page_number, (part,)),),
        title="Integration Fixture",
    )


class _DeterministicFakeRecognizer:
    def __init__(self) -> None:
        self.rendered_pages: list[RenderedPage] = []

    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        assert page.content.startswith(_PNG_SIGNATURE)
        assert (page.width, page.height, page.dpi) == (612, 792, 72)
        self.rendered_pages.append(page)
        return _valid_recognition(page.page_number)


class _InvalidFakeRecognizer:
    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        result = _valid_recognition(page.page_number)
        measure = result.pages[0].parts[0].measures[0]
        event = measure.events[0]
        invalid_measure = RecognizedMeasure(
            measure.number,
            measure.time_signature,
            (event, event),
            measure.tempo_bpm,
        )
        part = RecognizedPart("Drum Kit", (invalid_measure,))
        return RecognitionResult((RecognizedPage(page.page_number, (part,)),))


def _run_pipeline(recognizer: _DeterministicFakeRecognizer) -> Score:
    return asyncio.run(RecognitionPipeline(recognizer, dpi=72).process(_PDF_FIXTURE))


def test_pdf_fixture_to_musicxml_has_expected_structure(tmp_path: Path) -> None:
    recognizer = _DeterministicFakeRecognizer()
    score = _run_pipeline(recognizer)
    output = tmp_path / "integration.musicxml"

    MusicXMLExporter().write(score, output)
    root = ET.parse(output).getroot()
    measure = root.find("part/measure")

    assert recognizer.rendered_pages[0].page_number == 1
    assert root.tag == "score-partwise"
    assert root.findtext("movement-title") == "Integration Fixture"
    assert root.findtext("part-list/score-part/part-name") == "Drum Kit"
    assert measure is not None
    assert measure.get("number") == "1"
    assert measure.findtext("attributes/time/beats") == "4"
    assert measure.findtext("attributes/time/beat-type") == "4"
    sound = measure.find("direction/sound")
    assert sound is not None
    assert sound.get("tempo") == "120"
    assert len(measure.findall("note")) == 8
    assert len(measure.findall("note/chord")) == 4
    assert {
        element.text
        for element in root.findall(
            "part-list/score-part/score-instrument/instrument-name"
        )
    } == {"Kick Drum", "Snare Drum", "Closed Hi-Hat"}


def test_pdf_fixture_to_midi_has_expected_events(tmp_path: Path) -> None:
    recognizer = _DeterministicFakeRecognizer()
    score = _run_pipeline(recognizer)
    output = tmp_path / "integration.mid"

    MIDIExporter().write(score, output)
    midi = mido.MidiFile(output, charset="utf8")
    conductor = midi.tracks[0]
    absolute_tick = 0
    note_ons: list[tuple[int, int, int, int]] = []
    for message in midi.tracks[1]:
        absolute_tick += message.time
        if message.type == "note_on":
            note_ons.append(
                (absolute_tick, message.note, message.velocity, message.channel)
            )

    tempo = [message for message in conductor if message.type == "set_tempo"]
    signature = [
        message for message in conductor if message.type == "time_signature"
    ]

    assert recognizer.rendered_pages[0].page_number == 1
    assert midi.type == 1
    assert midi.ticks_per_beat == 480
    assert len(midi.tracks) == 2
    assert [(message.tempo, message.time) for message in tempo] == [(500_000, 0)]
    assert [
        (message.numerator, message.denominator, message.time)
        for message in signature
    ] == [(4, 4, 0)]
    assert note_ons == [
        (0, 36, 110, DRUM_CHANNEL),
        (0, 42, 80, DRUM_CHANNEL),
        (480, 38, 100, DRUM_CHANNEL),
        (480, 42, 80, DRUM_CHANNEL),
        (960, 36, 110, DRUM_CHANNEL),
        (960, 42, 80, DRUM_CHANNEL),
        (1_440, 38, 100, DRUM_CHANNEL),
        (1_440, 42, 80, DRUM_CHANNEL),
    ]


def test_complete_flow_runs_real_recognition_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    original_validate = RecognitionValidator.validate

    def tracked_validate(
        validator: RecognitionValidator,
        result: RecognitionResult,
    ) -> tuple[RecognitionValidationWarning, ...]:
        calls.append(result.pages[0].page_number)
        return original_validate(validator, result)

    monkeypatch.setattr(RecognitionValidator, "validate", tracked_validate)

    score = _run_pipeline(_DeterministicFakeRecognizer())

    assert calls == [1]
    assert score.parts[0].measures[0].number == 1


def test_invalid_fake_recognition_fails_at_validation_stage() -> None:
    with pytest.raises(RecognitionPipelineError) as caught:
        asyncio.run(
            RecognitionPipeline(_InvalidFakeRecognizer(), dpi=72).process(
                _PDF_FIXTURE
            )
        )

    assert caught.value.stage == "validation"
    assert caught.value.page_number == 1
    assert isinstance(caught.value.__cause__, RecognitionValidationError)
    assert (
        caught.value.__cause__.code
        is RecognitionValidationErrorCode.DUPLICATE_EVENT
    )
