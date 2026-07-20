"""Tests for conversion from recognition results to the score domain."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

import drum_score_converter.score_builder as score_builder_module
from drum_score_converter.midi_exporter import MIDIExporter
from drum_score_converter.musicxml_exporter import MusicXMLExporter
from drum_score_converter.recognition_model import (
    RecognitionLocation,
    RecognitionResult,
    RecognitionWarning,
    RecognitionWarningCode,
    RecognizedFraction,
    RecognizedInstrument,
    RecognizedMeasure,
    RecognizedNote,
    RecognizedPage,
    RecognizedPart,
    RecognizedRest,
    RecognizedTimeSignature,
)
from drum_score_converter.score_builder import (
    InconsistentRecognitionError,
    InstrumentMappingError,
    MissingScoreDataError,
    ScoreBuilder,
    ScoreConstructionError,
)
from drum_score_converter.score_model import DrumInstrument, Note, Rest


def _fraction(numerator: int, denominator: int = 1) -> RecognizedFraction:
    return RecognizedFraction(numerator, denominator)


def _note(
    instrument: str = "snare",
    *,
    offset: RecognizedFraction | None = None,
    duration: RecognizedFraction | None = None,
    velocity: int | None = 90,
    accent: bool | None = True,
    ghost: bool | None = False,
) -> RecognizedNote:
    return RecognizedNote(
        RecognizedInstrument(instrument),
        _fraction(0) if offset is None else offset,
        _fraction(1) if duration is None else duration,
        velocity=velocity,
        accent=accent,
        ghost=ghost,
    )


def _measure(
    *,
    number: int | None = 1,
    signature: RecognizedTimeSignature | None = None,
    events: tuple[RecognizedNote | RecognizedRest, ...] | None = None,
    tempo_bpm: float | None = 120,
) -> RecognizedMeasure:
    if signature is None:
        signature = RecognizedTimeSignature(4, 4)
    if events is None:
        events = (_note(),)
    return RecognizedMeasure(number, signature, events, tempo_bpm)


def _result(
    *,
    parts: tuple[RecognizedPart, ...] | None = None,
    title: str | None = "Recognized Score",
    warnings: tuple[RecognitionWarning, ...] = (),
) -> RecognitionResult:
    if parts is None:
        parts = (RecognizedPart("Drum Kit", (_measure(),)),)
    return RecognitionResult(
        (RecognizedPage(1, parts),),
        title=title,
        warnings=warnings,
    )


def test_build_converts_notes_rests_title_tempo_and_time_signature() -> None:
    events = (
        _note("kick", duration=_fraction(1, 2)),
        RecognizedRest(_fraction(1, 2), _fraction(1, 2)),
    )
    result = _result(
        parts=(
            RecognizedPart(
                "Drums",
                (_measure(signature=RecognizedTimeSignature(6, 8), events=events),),
            ),
        )
    )

    score = ScoreBuilder().build(result)

    measure = score.parts[0].measures[0]
    assert score.title == "Recognized Score"
    assert measure.time_signature.numerator == 6
    assert measure.time_signature.denominator == 8
    assert measure.tempo is not None
    assert measure.tempo.bpm == 120
    assert isinstance(measure.events[0], Note)
    assert isinstance(measure.events[1], Rest)


def test_fraction_values_remain_in_quarter_note_units() -> None:
    events = (
        _note("kick", offset=_fraction(0), duration=_fraction(1)),
        _note("snare", offset=_fraction(1, 2), duration=_fraction(1, 2)),
        _note("closed_hi_hat", offset=_fraction(3, 4), duration=_fraction(1, 4)),
    )
    result = _result(parts=(RecognizedPart("Drums", (_measure(events=events),)),))

    score = ScoreBuilder().build(result)
    converted = score.parts[0].measures[0].events

    assert [(event.offset, event.duration) for event in converted] == [
        (Fraction(0), Fraction(1)),
        (Fraction(1, 2), Fraction(1, 2)),
        (Fraction(3, 4), Fraction(1, 4)),
    ]


@pytest.mark.parametrize("instrument", list(DrumInstrument))
def test_all_standard_instrument_labels_are_mapped(
    instrument: DrumInstrument,
) -> None:
    result = _result(
        parts=(
            RecognizedPart("Drums", (_measure(events=(_note(instrument.value),)),)),
        )
    )

    score = ScoreBuilder().build(result)

    note = score.parts[0].measures[0].events[0]
    assert isinstance(note, Note)
    assert note.instrument is instrument


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Bass Drum", DrumInstrument.KICK),
        ("cross-stick", DrumInstrument.SIDE_STICK),
        ("Acoustic Snare", DrumInstrument.SNARE),
        ("Closed Hi-Hat", DrumInstrument.CLOSED_HI_HAT),
        ("Open Hi Hat", DrumInstrument.OPEN_HI_HAT),
        ("Pedal Hihat", DrumInstrument.PEDAL_HI_HAT),
        ("Ride Cymbal", DrumInstrument.RIDE),
        ("Crash_Cymbal", DrumInstrument.CRASH),
        ("Middle Tom", DrumInstrument.MID_TOM),
    ],
)
def test_explicit_instrument_aliases_are_mapped(
    label: str,
    expected: DrumInstrument,
) -> None:
    result = _result(
        parts=(RecognizedPart("Drums", (_measure(events=(_note(label),)),)),)
    )

    score = ScoreBuilder().build(result)
    note = score.parts[0].measures[0].events[0]

    assert isinstance(note, Note)
    assert note.instrument is expected


def test_optional_note_attributes_use_score_defaults() -> None:
    result = _result(
        parts=(
            RecognizedPart(
                "Drums",
                (
                    _measure(
                        events=(
                            _note(
                                velocity=None,
                                accent=None,
                                ghost=None,
                            ),
                        )
                    ),
                ),
            ),
        )
    )

    score = ScoreBuilder().build(result)
    note = score.parts[0].measures[0].events[0]

    assert isinstance(note, Note)
    assert (note.velocity, note.accent, note.ghost) == (100, False, False)


def test_events_are_stably_sorted_by_offset() -> None:
    late = _note("kick", offset=_fraction(2))
    same_offset_first = _note("snare", offset=_fraction(1))
    same_offset_second = _note("closed_hi_hat", offset=_fraction(1))
    result = _result(
        parts=(
            RecognizedPart(
                "Drums",
                (_measure(events=(late, same_offset_first, same_offset_second)),),
            ),
        )
    )

    score = ScoreBuilder().build(result)
    notes = score.parts[0].measures[0].events

    assert [note.instrument for note in notes if isinstance(note, Note)] == [
        DrumInstrument.SNARE,
        DrumInstrument.CLOSED_HI_HAT,
        DrumInstrument.KICK,
    ]


def test_builder_does_not_add_exporter_specific_cross_part_constraints() -> None:
    first = RecognizedPart("First", (_measure(number=1),))
    second = RecognizedPart(
        "Second",
        (
            _measure(number=10, signature=RecognizedTimeSignature(3, 4)),
            _measure(number=11, signature=RecognizedTimeSignature(5, 8)),
        ),
    )

    score = ScoreBuilder().build(_result(parts=(first, second)))

    assert [len(part.measures) for part in score.parts] == [1, 2]
    assert score.parts[1].measures[0].number == 10


def test_exporters_accept_a_score_built_from_valid_recognition_data() -> None:
    score = ScoreBuilder().build(_result())

    assert MusicXMLExporter().to_string(score).startswith("<?xml")
    assert MIDIExporter().to_bytes(score).startswith(b"MThd")


def test_unknown_instrument_has_event_location() -> None:
    result = _result(
        parts=(
            RecognizedPart(
                "Drums",
                (_measure(events=(_note("vendor splash stack"),)),),
            ),
        )
    )

    with pytest.raises(InstrumentMappingError) as caught:
        ScoreBuilder().build(result)

    assert caught.value.location == RecognitionLocation(1, 0, 0, 0)


@pytest.mark.parametrize(
    "parts",
    [
        (),
        (RecognizedPart(None, (_measure(),)),),
        (RecognizedPart("Drums", ()),),
        (RecognizedPart("Drums", (_measure(number=None),)),),
        (
            RecognizedPart(
                "Drums",
                (
                    RecognizedMeasure(
                        1,
                        None,
                        (_note(),),
                    ),
                ),
            ),
        ),
    ],
)
def test_missing_required_score_data_is_rejected(
    parts: tuple[RecognizedPart, ...],
) -> None:
    with pytest.raises(MissingScoreDataError) as caught:
        ScoreBuilder().build(_result(parts=parts))

    assert caught.value.location is not None


def test_multiple_pages_are_rejected() -> None:
    page = _result().pages[0]
    result = RecognitionResult((page, RecognizedPage(2, page.parts)))

    with pytest.raises(InconsistentRecognitionError, match="exactly one"):
        ScoreBuilder().build(result)


def test_measure_capacity_overrun_is_rejected_with_cause() -> None:
    overrun = _note("crash", offset=_fraction(7, 2), duration=_fraction(1))
    result = _result(
        parts=(RecognizedPart("Drums", (_measure(events=(overrun,)),)),)
    )

    with pytest.raises(InconsistentRecognitionError) as caught:
        ScoreBuilder().build(result)

    assert caught.value.location == RecognitionLocation(1, 0, 0)
    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.parametrize("numbers", [(1, 1), (2, 1)])
def test_duplicate_or_descending_measure_numbers_are_rejected(
    numbers: tuple[int, int],
) -> None:
    measures = tuple(_measure(number=number) for number in numbers)
    result = _result(parts=(RecognizedPart("Drums", measures),))

    with pytest.raises(InconsistentRecognitionError) as caught:
        ScoreBuilder().build(result)

    assert caught.value.location == RecognitionLocation(1, 0, 1)


def test_low_confidence_warning_alone_does_not_block_conversion() -> None:
    warning = RecognitionWarning(
        RecognitionWarningCode.LOW_CONFIDENCE,
        "Review this page",
        RecognitionLocation(1),
    )

    score = ScoreBuilder().build(_result(warnings=(warning,)))

    assert score.parts[0].name == "Drum Kit"


def test_build_does_not_mutate_recognition_result() -> None:
    unsorted_events = (
        _note("kick", offset=_fraction(2)),
        _note("snare", offset=_fraction(0)),
    )
    result = _result(
        parts=(RecognizedPart("Drums", (_measure(events=unsorted_events),)),)
    )
    original_events = result.pages[0].parts[0].measures[0].events

    ScoreBuilder().build(result)

    assert result.pages[0].parts[0].measures[0].events == original_events
    assert result.pages[0].parts[0].measures[0].events is original_events


def test_score_construction_failure_is_wrapped_and_chained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_score(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("construction failed")

    monkeypatch.setattr(score_builder_module, "Score", fail_score)

    with pytest.raises(ScoreConstructionError) as caught:
        ScoreBuilder().build(_result())

    assert caught.value.location == RecognitionLocation(1)
    assert isinstance(caught.value.__cause__, ValueError)


def test_public_score_builder_types_are_exported() -> None:
    from drum_score_converter import (
        InconsistentRecognitionError as PublicInconsistentRecognitionError,
    )
    from drum_score_converter import (
        InstrumentMappingError as PublicInstrumentMappingError,
    )
    from drum_score_converter import (
        MissingScoreDataError as PublicMissingScoreDataError,
    )
    from drum_score_converter import (
        ScoreBuilder as PublicScoreBuilder,
    )
    from drum_score_converter import (
        ScoreBuildError as PublicScoreBuildError,
    )
    from drum_score_converter import (
        ScoreConstructionError as PublicScoreConstructionError,
    )
    from drum_score_converter import (
        UnsupportedNotationError as PublicUnsupportedNotationError,
    )

    assert PublicScoreBuilder is ScoreBuilder
    assert issubclass(PublicMissingScoreDataError, PublicScoreBuildError)
    assert issubclass(PublicInstrumentMappingError, PublicScoreBuildError)
    assert issubclass(PublicUnsupportedNotationError, PublicScoreBuildError)
    assert issubclass(PublicInconsistentRecognitionError, PublicScoreBuildError)
    assert issubclass(PublicScoreConstructionError, PublicScoreBuildError)
