"""Provider-independent models for incomplete score recognition results."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction


def _validate_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("confidence must be a number or None")
    if not math.isfinite(value):
        raise ValueError("confidence must be finite")
    if not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")
    return float(value)


def _require_integer(value: int, field_name: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        qualifier = "positive" if minimum == 1 else "non-negative"
        raise ValueError(f"{field_name} must be {qualifier}")


def _require_optional_index(value: int | None, field_name: str) -> None:
    if value is not None:
        _require_integer(value, field_name, minimum=0)


def _fraction_value(value: RecognizedFraction) -> Fraction:
    return Fraction(value.numerator, value.denominator)


@dataclass(frozen=True, slots=True)
class RecognizedFraction:
    """An exact non-negative value expressed in quarter-note units.

    A quarter note is ``1``, an eighth note is ``1/2``, and a sixteenth note
    is ``1/4``. Offsets and durations use the same units as the Score domain.
    """

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        _require_integer(self.numerator, "numerator", minimum=0)
        _require_integer(self.denominator, "denominator", minimum=1)


@dataclass(frozen=True, slots=True)
class RecognizedInstrument:
    """A losslessly retained instrument label and optional confidence."""

    value: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("value must be a string")
        if not self.value.strip():
            raise ValueError("value must not be empty")
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )


@dataclass(frozen=True, slots=True)
class RecognizedTimeSignature:
    """A recognized time signature that may still require validation."""

    numerator: int
    denominator: int
    confidence: float | None = None

    def __post_init__(self) -> None:
        _require_integer(self.numerator, "numerator", minimum=1)
        _require_integer(self.denominator, "denominator", minimum=1)
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )


@dataclass(frozen=True, slots=True)
class RecognizedNote:
    """A drum note timed exactly in quarter-note units."""

    instrument: RecognizedInstrument
    offset: RecognizedFraction
    duration: RecognizedFraction
    velocity: int | None = None
    accent: bool | None = None
    ghost: bool | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, RecognizedInstrument):
            raise TypeError("instrument must be a RecognizedInstrument")
        if not isinstance(self.offset, RecognizedFraction):
            raise TypeError("offset must be a RecognizedFraction")
        if not isinstance(self.duration, RecognizedFraction):
            raise TypeError("duration must be a RecognizedFraction")
        if _fraction_value(self.offset) < 0:
            raise ValueError("offset must be non-negative")
        if _fraction_value(self.duration) <= 0:
            raise ValueError("duration must be positive")
        if self.velocity is not None:
            _require_integer(self.velocity, "velocity", minimum=0)
            if self.velocity > 127:
                raise ValueError("velocity must be between 0 and 127")
        if self.accent is not None and not isinstance(self.accent, bool):
            raise TypeError("accent must be a boolean or None")
        if self.ghost is not None and not isinstance(self.ghost, bool):
            raise TypeError("ghost must be a boolean or None")
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )


@dataclass(frozen=True, slots=True)
class RecognizedRest:
    """A recognized rest timed exactly in quarter-note units."""

    offset: RecognizedFraction
    duration: RecognizedFraction
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.offset, RecognizedFraction):
            raise TypeError("offset must be a RecognizedFraction")
        if not isinstance(self.duration, RecognizedFraction):
            raise TypeError("duration must be a RecognizedFraction")
        if _fraction_value(self.offset) < 0:
            raise ValueError("offset must be non-negative")
        if _fraction_value(self.duration) <= 0:
            raise ValueError("duration must be positive")
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )


@dataclass(frozen=True, slots=True)
class RecognizedMeasure:
    """A recognized measure that may omit its number or time signature."""

    number: int | None
    time_signature: RecognizedTimeSignature | None
    events: tuple[RecognizedNote | RecognizedRest, ...] = ()
    tempo_bpm: float | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.number is not None:
            _require_integer(self.number, "number", minimum=1)
        if self.time_signature is not None and not isinstance(
            self.time_signature, RecognizedTimeSignature
        ):
            raise TypeError(
                "time_signature must be a RecognizedTimeSignature or None"
            )
        if not isinstance(self.events, tuple):
            raise TypeError("events must be a tuple")
        if not all(
            isinstance(event, (RecognizedNote, RecognizedRest))
            for event in self.events
        ):
            raise TypeError(
                "events must contain only RecognizedNote or RecognizedRest instances"
            )
        if self.tempo_bpm is not None:
            if isinstance(self.tempo_bpm, bool) or not isinstance(
                self.tempo_bpm, (int, float)
            ):
                raise TypeError("tempo_bpm must be a number or None")
            if not math.isfinite(self.tempo_bpm) or self.tempo_bpm <= 0:
                raise ValueError("tempo_bpm must be finite and positive")
            object.__setattr__(self, "tempo_bpm", float(self.tempo_bpm))
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )


@dataclass(frozen=True, slots=True)
class RecognizedPart:
    """A recognized part whose name and measures may be incomplete."""

    name: str | None
    measures: tuple[RecognizedMeasure, ...]
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            if not isinstance(self.name, str):
                raise TypeError("name must be a string or None")
            if not self.name.strip():
                raise ValueError("name must not be empty")
        if not isinstance(self.measures, tuple):
            raise TypeError("measures must be a tuple")
        if not all(isinstance(measure, RecognizedMeasure) for measure in self.measures):
            raise TypeError("measures must contain only RecognizedMeasure instances")
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )


@dataclass(frozen=True, slots=True)
class RecognizedPage:
    """Recognition results for one source PDF page."""

    page_number: int
    parts: tuple[RecognizedPart, ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        _require_integer(self.page_number, "page_number", minimum=1)
        if not isinstance(self.parts, tuple):
            raise TypeError("parts must be a tuple")
        if not all(isinstance(part, RecognizedPart) for part in self.parts):
            raise TypeError("parts must contain only RecognizedPart instances")
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )


class RecognitionWarningCode(StrEnum):
    """Machine-readable categories for recognition warnings."""

    LOW_CONFIDENCE = "low_confidence"
    AMBIGUOUS_INSTRUMENT = "ambiguous_instrument"
    MISSING_TIME_SIGNATURE = "missing_time_signature"
    MISSING_MEASURE_NUMBER = "missing_measure_number"
    UNSUPPORTED_NOTATION = "unsupported_notation"


@dataclass(frozen=True, slots=True)
class RecognitionLocation:
    """Hierarchical source location for a recognition warning."""

    page_number: int
    part_index: int | None = None
    measure_index: int | None = None
    event_index: int | None = None

    def __post_init__(self) -> None:
        _require_integer(self.page_number, "page_number", minimum=1)
        _require_optional_index(self.part_index, "part_index")
        _require_optional_index(self.measure_index, "measure_index")
        _require_optional_index(self.event_index, "event_index")
        if self.measure_index is not None and self.part_index is None:
            raise ValueError("measure_index requires part_index")
        if self.event_index is not None and (
            self.part_index is None or self.measure_index is None
        ):
            raise ValueError("event_index requires part_index and measure_index")


@dataclass(frozen=True, slots=True)
class RecognitionWarning:
    """A warning associated with a recognition result or source location."""

    code: RecognitionWarningCode
    message: str
    location: RecognitionLocation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, RecognitionWarningCode):
            raise TypeError("code must be a RecognitionWarningCode")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        if not self.message.strip():
            raise ValueError("message must not be empty")
        if self.location is not None and not isinstance(
            self.location, RecognitionLocation
        ):
            raise TypeError("location must be a RecognitionLocation or None")


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """Complete provider-independent output of a recognition operation."""

    pages: tuple[RecognizedPage, ...]
    title: str | None = None
    warnings: tuple[RecognitionWarning, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.pages, tuple):
            raise TypeError("pages must be a tuple")
        if not self.pages:
            raise ValueError("pages must contain at least one page")
        if not all(isinstance(page, RecognizedPage) for page in self.pages):
            raise TypeError("pages must contain only RecognizedPage instances")
        page_numbers = tuple(page.page_number for page in self.pages)
        if len(set(page_numbers)) != len(page_numbers):
            raise ValueError("page_number values must be unique")
        if any(
            current >= following
            for current, following in zip(page_numbers, page_numbers[1:])
        ):
            raise ValueError("pages must be in strictly increasing page_number order")
        if self.title is not None:
            if not isinstance(self.title, str):
                raise TypeError("title must be a string or None")
            if not self.title.strip():
                raise ValueError("title must not be empty")
        if not isinstance(self.warnings, tuple):
            raise TypeError("warnings must be a tuple")
        if not all(
            isinstance(warning, RecognitionWarning) for warning in self.warnings
        ):
            raise TypeError("warnings must contain only RecognitionWarning instances")
