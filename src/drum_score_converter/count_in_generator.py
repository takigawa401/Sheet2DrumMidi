"""Generate an optional one-measure count-in for a drum score.

Example::

    config = CountInConfig(enabled=True)
    score_with_count_in = CountInGenerator(config).apply(score)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Final

from drum_score_converter.score_model import (
    DEFAULT_TEMPO_BPM,
    DrumInstrument,
    Measure,
    Note,
    Part,
    Score,
    Tempo,
    TimeSignature,
)

COUNT_IN_BEATS: Final = 4
COUNT_IN_NOTE: Final = 37
COUNT_IN_VELOCITY: Final = 100
_COUNT_IN_SIGNATURE: Final = TimeSignature(4, 4)
_COUNT_IN_NOTE_DURATION: Final = Fraction(1)


class CountInError(ValueError):
    """Raised when a score cannot receive a count-in unambiguously."""


@dataclass(frozen=True, slots=True)
class CountInConfig:
    """Configuration for optional count-in generation."""

    enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")


class CountInGenerator:
    """Prepend a fixed four-beat side-stick count without mutating a Score."""

    def __init__(self, config: CountInConfig | None = None) -> None:
        if config is not None and not isinstance(config, CountInConfig):
            raise TypeError("config must be a CountInConfig")
        self._config = config if config is not None else CountInConfig()

    def apply(self, score: Score) -> Score:
        """Return the original score when disabled, or a copied count-in score."""
        if not isinstance(score, Score):
            raise TypeError("score must be a Score")
        if not self._config.enabled:
            return score

        tempo = _initial_tempo(score)
        parts = tuple(
            _prepend_count_in(part, tempo, with_notes=part_index == 0)
            for part_index, part in enumerate(score.parts)
        )
        return replace(score, parts=parts)


def _initial_tempo(score: Score) -> Tempo:
    bpms = {
        part.measures[0].tempo.bpm
        for part in score.parts
        if part.measures[0].tempo is not None
    }
    if len(bpms) > 1:
        raise CountInError("score parts have conflicting initial tempos")
    return Tempo(bpms.pop() if bpms else DEFAULT_TEMPO_BPM)


def _prepend_count_in(part: Part, tempo: Tempo, *, with_notes: bool) -> Part:
    events: tuple[Note, ...] = ()
    if with_notes:
        events = tuple(
            Note(
                instrument=DrumInstrument.SIDE_STICK,
                offset=Fraction(beat),
                duration=_COUNT_IN_NOTE_DURATION,
                velocity=COUNT_IN_VELOCITY,
            )
            for beat in range(COUNT_IN_BEATS)
        )

    count_in = Measure(
        number=1,
        time_signature=_COUNT_IN_SIGNATURE,
        events=events,
        tempo=tempo,
    )
    shifted_measures = tuple(
        replace(measure, number=measure.number + 1) for measure in part.measures
    )
    return replace(part, measures=(count_in, *shifted_measures))
