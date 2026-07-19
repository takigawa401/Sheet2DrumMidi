"""Tests for the score domain model."""

from fractions import Fraction

import pytest

from drum_score_converter.score_model import (
    DrumInstrument,
    Measure,
    Note,
    Part,
    Rest,
    Score,
    Tempo,
    TimeSignature,
)


def test_score_exposes_parts_measures_and_events() -> None:
    """Exporters can traverse the complete score hierarchy."""
    signature = TimeSignature(4, 4)
    kick = Note(DrumInstrument.KICK, Fraction(0), Fraction(1, 4))
    hi_hat = Note(DrumInstrument.CLOSED_HI_HAT, Fraction(0), Fraction(1, 4))
    rest = Rest(Fraction(1, 4), Fraction(3, 4))
    measure = Measure(1, signature, (kick, hi_hat, rest), Tempo(120))
    part = Part("Drum Kit", (measure,))
    score = Score((part,), title="Example")

    assert score.parts[0].measures[0].events == (kick, hi_hat, rest)
    assert measure.tempo == Tempo(120)
    assert measure.duration == Fraction(4)


def test_time_signature_returns_exact_measure_duration() -> None:
    assert TimeSignature(6, 8).measure_duration == Fraction(3)


@pytest.mark.parametrize("bpm", [0, -1, float("inf"), float("nan")])
def test_tempo_rejects_invalid_bpm(bpm: float) -> None:
    with pytest.raises(ValueError):
        Tempo(bpm)


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [(0, 4), (-1, 4), (4, 0), (4, 3)],
)
def test_time_signature_rejects_invalid_values(
    numerator: int, denominator: int
) -> None:
    with pytest.raises(ValueError):
        TimeSignature(numerator, denominator)


@pytest.mark.parametrize("velocity", [-1, 128])
def test_note_rejects_velocity_outside_midi_range(velocity: int) -> None:
    with pytest.raises(ValueError):
        Note(
            DrumInstrument.SNARE,
            Fraction(0),
            Fraction(1),
            velocity=velocity,
        )


def test_note_and_rest_reject_invalid_positions_or_durations() -> None:
    with pytest.raises(ValueError):
        Note(DrumInstrument.KICK, Fraction(-1), Fraction(1))
    with pytest.raises(ValueError):
        Rest(Fraction(0), Fraction(0))


def test_measure_rejects_an_event_past_its_boundary() -> None:
    note = Note(DrumInstrument.CRASH, Fraction(7, 2), Fraction(1))

    with pytest.raises(ValueError, match="fit within"):
        Measure(1, TimeSignature(4, 4), (note,))


def test_part_requires_increasing_measure_numbers() -> None:
    signature = TimeSignature(4, 4)
    first = Measure(2, signature)
    second = Measure(1, signature)

    with pytest.raises(ValueError, match="strictly increasing"):
        Part("Drum Kit", (first, second))


def test_score_part_and_title_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        Score(())
    with pytest.raises(ValueError, match="at least one measure"):
        Part("Drum Kit", ())

    measure = Measure(1, TimeSignature(4, 4))
    with pytest.raises(ValueError, match="title must not be empty"):
        Score((Part("Drum Kit", (measure,)),), title=" ")
