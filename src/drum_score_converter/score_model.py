"""Output-neutral domain model for a drum score."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction


class DrumInstrument(StrEnum):
    """Drum instruments recognized by the score model."""

    KICK = "kick"
    SNARE = "snare"
    CLOSED_HI_HAT = "closed_hi_hat"
    OPEN_HI_HAT = "open_hi_hat"
    PEDAL_HI_HAT = "pedal_hi_hat"
    RIDE = "ride"
    CRASH = "crash"
    HIGH_TOM = "high_tom"
    MID_TOM = "mid_tom"
    FLOOR_TOM = "floor_tom"


def _require_positive_fraction(value: Fraction, field_name: str) -> None:
    if not isinstance(value, Fraction):
        raise TypeError(f"{field_name} must be a Fraction")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def _require_non_negative_fraction(value: Fraction, field_name: str) -> None:
    if not isinstance(value, Fraction):
        raise TypeError(f"{field_name} must be a Fraction")
    if value < 0:
        raise ValueError(f"{field_name} must not be negative")


@dataclass(frozen=True, slots=True)
class Tempo:
    """Tempo in quarter-note beats per minute."""

    bpm: float

    def __post_init__(self) -> None:
        if isinstance(self.bpm, bool) or not isinstance(self.bpm, (int, float)):
            raise TypeError("bpm must be a number")
        if not math.isfinite(self.bpm) or self.bpm <= 0:
            raise ValueError("bpm must be finite and positive")
        object.__setattr__(self, "bpm", float(self.bpm))


@dataclass(frozen=True, slots=True)
class TimeSignature:
    """Number of beats in a measure and the note value receiving one beat."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise TypeError("numerator must be an integer")
        if isinstance(self.denominator, bool) or not isinstance(self.denominator, int):
            raise TypeError("denominator must be an integer")
        if self.numerator <= 0:
            raise ValueError("numerator must be positive")
        if self.denominator <= 0 or self.denominator & (self.denominator - 1):
            raise ValueError("denominator must be a positive power of two")

    @property
    def measure_duration(self) -> Fraction:
        """Return the measure length expressed in quarter notes."""
        return Fraction(self.numerator * 4, self.denominator)


@dataclass(frozen=True, slots=True)
class Note:
    """A drum hit positioned in quarter-note units within a measure."""

    instrument: DrumInstrument
    offset: Fraction
    duration: Fraction
    velocity: int = 100
    accent: bool = False
    ghost: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, DrumInstrument):
            raise TypeError("instrument must be a DrumInstrument")
        _require_non_negative_fraction(self.offset, "offset")
        _require_positive_fraction(self.duration, "duration")
        if isinstance(self.velocity, bool) or not isinstance(self.velocity, int):
            raise TypeError("velocity must be an integer")
        if not 0 <= self.velocity <= 127:
            raise ValueError("velocity must be between 0 and 127")
        if not isinstance(self.accent, bool) or not isinstance(self.ghost, bool):
            raise TypeError("accent and ghost must be booleans")


@dataclass(frozen=True, slots=True)
class Rest:
    """A silent span positioned in quarter-note units within a measure."""

    offset: Fraction
    duration: Fraction

    def __post_init__(self) -> None:
        _require_non_negative_fraction(self.offset, "offset")
        _require_positive_fraction(self.duration, "duration")


@dataclass(frozen=True, slots=True)
class Measure:
    """An ordered measure containing notes and rests.

    Tempo, when present, applies from the beginning of this measure.
    """

    number: int
    time_signature: TimeSignature
    events: tuple[Note | Rest, ...] = ()
    tempo: Tempo | None = None

    def __post_init__(self) -> None:
        if isinstance(self.number, bool) or not isinstance(self.number, int):
            raise TypeError("number must be an integer")
        if self.number <= 0:
            raise ValueError("number must be positive")
        if not isinstance(self.time_signature, TimeSignature):
            raise TypeError("time_signature must be a TimeSignature")
        if self.tempo is not None and not isinstance(self.tempo, Tempo):
            raise TypeError("tempo must be a Tempo or None")
        if not isinstance(self.events, tuple):
            raise TypeError("events must be a tuple")

        for event in self.events:
            if not isinstance(event, (Note, Rest)):
                raise TypeError("events must contain only Note or Rest instances")
            if event.offset + event.duration > self.duration:
                raise ValueError("event must fit within the measure")

    @property
    def duration(self) -> Fraction:
        """Return this measure's length expressed in quarter notes."""
        return self.time_signature.measure_duration


@dataclass(frozen=True, slots=True)
class Part:
    """A named sequence of measures, such as a drum-kit part."""

    name: str
    measures: tuple[Measure, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("name must be a string")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not isinstance(self.measures, tuple):
            raise TypeError("measures must be a tuple")
        if not self.measures:
            raise ValueError("part must contain at least one measure")
        if not all(isinstance(measure, Measure) for measure in self.measures):
            raise TypeError("measures must contain only Measure instances")

        numbers = tuple(measure.number for measure in self.measures)
        measure_pairs = zip(numbers, numbers[1:])
        if any(current >= following for current, following in measure_pairs):
            raise ValueError("measure numbers must be strictly increasing")


@dataclass(frozen=True, slots=True)
class Score:
    """A complete score composed of one or more parts."""

    parts: tuple[Part, ...]
    title: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.parts, tuple):
            raise TypeError("parts must be a tuple")
        if not self.parts:
            raise ValueError("score must contain at least one part")
        if not all(isinstance(part, Part) for part in self.parts):
            raise TypeError("parts must contain only Part instances")
        if self.title is not None:
            if not isinstance(self.title, str):
                raise TypeError("title must be a string or None")
            if not self.title.strip():
                raise ValueError("title must not be empty")
