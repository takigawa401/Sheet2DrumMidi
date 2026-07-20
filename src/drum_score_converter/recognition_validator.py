"""Deterministic semantic validation for recognition results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from drum_score_converter.recognition_model import (
    RecognitionLocation,
    RecognitionResult,
    RecognizedFraction,
    RecognizedMeasure,
    RecognizedNote,
    RecognizedRest,
)


class RecognitionValidationErrorCode(StrEnum):
    """Machine-readable fatal semantic validation failures."""

    MISSING_MEASURE_NUMBER = "missing_measure_number"
    DUPLICATE_MEASURE_NUMBER = "duplicate_measure_number"
    DESCENDING_MEASURE_NUMBER = "descending_measure_number"
    MISSING_TIME_SIGNATURE = "missing_time_signature"
    UNSUPPORTED_TIME_SIGNATURE = "unsupported_time_signature"
    EVENT_OUTSIDE_MEASURE = "event_outside_measure"
    DUPLICATE_EVENT = "duplicate_event"
    CONTRADICTORY_NOTE = "contradictory_note"
    OVERLAPPING_RESTS = "overlapping_rests"
    REST_NOTE_CONFLICT = "rest_note_conflict"


class RecognitionValidationWarningCode(StrEnum):
    """Machine-readable recoverable semantic validation warnings."""

    UNSORTED_EVENTS = "unsorted_events"


@dataclass(frozen=True, slots=True)
class RecognitionValidationWarning:
    """A recoverable issue found without changing recognition data."""

    code: RecognitionValidationWarningCode
    message: str
    location: RecognitionLocation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, RecognitionValidationWarningCode):
            raise TypeError("code must be a RecognitionValidationWarningCode")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        if not self.message.strip():
            raise ValueError("message must not be empty")
        if self.location is not None and not isinstance(
            self.location, RecognitionLocation
        ):
            raise TypeError("location must be a RecognitionLocation or None")


class RecognitionValidationError(ValueError):
    """A fatal semantic inconsistency in a recognition result."""

    def __init__(
        self,
        message: str,
        *,
        code: RecognitionValidationErrorCode,
        location: RecognitionLocation | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.location = location


class RecognitionValidator:
    """Validate recognition semantics without modifying the input."""

    def validate(
        self,
        result: RecognitionResult,
    ) -> tuple[RecognitionValidationWarning, ...]:
        """Return recoverable warnings or raise the first fatal error."""
        if not isinstance(result, RecognitionResult):
            raise TypeError("result must be a RecognitionResult")

        warnings: list[RecognitionValidationWarning] = []
        for page in result.pages:
            for part_index, part in enumerate(page.parts):
                seen_numbers: set[int] = set()
                previous_number: int | None = None
                for measure_index, measure in enumerate(part.measures):
                    location = RecognitionLocation(
                        page.page_number,
                        part_index,
                        measure_index,
                    )
                    number = measure.number
                    if number is None:
                        raise RecognitionValidationError(
                            "A measure number is required for semantic validation.",
                            code=(
                                RecognitionValidationErrorCode.MISSING_MEASURE_NUMBER
                            ),
                            location=location,
                        )
                    if number in seen_numbers:
                        raise RecognitionValidationError(
                            "Measure numbers must not be duplicated within a part.",
                            code=(
                                RecognitionValidationErrorCode.DUPLICATE_MEASURE_NUMBER
                            ),
                            location=location,
                        )
                    if previous_number is not None and number < previous_number:
                        raise RecognitionValidationError(
                            "Measure numbers must not descend within a part.",
                            code=(
                                RecognitionValidationErrorCode.DESCENDING_MEASURE_NUMBER
                            ),
                            location=location,
                        )
                    seen_numbers.add(number)
                    previous_number = number
                    warnings.extend(
                        _validate_measure(
                            measure,
                            page.page_number,
                            part_index,
                            measure_index,
                        )
                    )
        return tuple(warnings)


def _validate_measure(
    measure: RecognizedMeasure,
    page_number: int,
    part_index: int,
    measure_index: int,
) -> tuple[RecognitionValidationWarning, ...]:
    location = RecognitionLocation(page_number, part_index, measure_index)
    signature = measure.time_signature
    if signature is None:
        raise RecognitionValidationError(
            "A time signature is required for semantic validation.",
            code=RecognitionValidationErrorCode.MISSING_TIME_SIGNATURE,
            location=location,
        )
    if signature.denominator & (signature.denominator - 1):
        raise RecognitionValidationError(
            "The time-signature denominator must be a positive power of two.",
            code=RecognitionValidationErrorCode.UNSUPPORTED_TIME_SIGNATURE,
            location=location,
        )

    capacity = Fraction(signature.numerator * 4, signature.denominator)
    for event_index, event in enumerate(measure.events):
        if _fraction(event.offset) + _fraction(event.duration) > capacity:
            raise RecognitionValidationError(
                "A recognized event extends beyond the measure capacity.",
                code=RecognitionValidationErrorCode.EVENT_OUTSIDE_MEASURE,
                location=RecognitionLocation(
                    page_number,
                    part_index,
                    measure_index,
                    event_index,
                ),
            )

    warnings: tuple[RecognitionValidationWarning, ...] = ()
    offsets = tuple(_fraction(event.offset) for event in measure.events)
    if any(current > following for current, following in zip(offsets, offsets[1:])):
        warnings = (
            RecognitionValidationWarning(
                RecognitionValidationWarningCode.UNSORTED_EVENTS,
                "Recognized events are not in ascending offset order.",
                location,
            ),
        )

    _validate_event_relationships(
        measure,
        page_number,
        part_index,
        measure_index,
    )
    return warnings


def _validate_event_relationships(
    measure: RecognizedMeasure,
    page_number: int,
    part_index: int,
    measure_index: int,
) -> None:
    events = measure.events

    for later_index, later in enumerate(events):
        for earlier in events[:later_index]:
            if _event_identity(earlier) == _event_identity(later):
                _raise_event_error(
                    "A measure contains a completely duplicate event.",
                    RecognitionValidationErrorCode.DUPLICATE_EVENT,
                    page_number,
                    part_index,
                    measure_index,
                    later_index,
                )

    notes = tuple(
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, RecognizedNote)
    )
    rests = tuple(
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, RecognizedRest)
    )

    for later_position, (later_index, later) in enumerate(notes):
        for _, earlier in notes[:later_position]:
            if (
                _instrument_identity(earlier) == _instrument_identity(later)
                and earlier.offset == later.offset
            ):
                _raise_event_error(
                    "Notes for one instrument at one offset have conflicting values.",
                    RecognitionValidationErrorCode.CONTRADICTORY_NOTE,
                    page_number,
                    part_index,
                    measure_index,
                    later_index,
                )

    for later_position, (later_index, later) in enumerate(rests):
        for _, earlier in rests[:later_position]:
            if _overlaps(earlier, later):
                _raise_event_error(
                    "Rest intervals must not overlap within a measure.",
                    RecognitionValidationErrorCode.OVERLAPPING_RESTS,
                    page_number,
                    part_index,
                    measure_index,
                    later_index,
                )

    for rest_index, rest in rests:
        for note_index, note in notes:
            if _overlaps(rest, note):
                _raise_event_error(
                    "A rest interval conflicts with a note interval.",
                    RecognitionValidationErrorCode.REST_NOTE_CONFLICT,
                    page_number,
                    part_index,
                    measure_index,
                    max(rest_index, note_index),
                )


def _event_identity(
    event: RecognizedNote | RecognizedRest,
) -> tuple[object, ...]:
    if isinstance(event, RecognizedRest):
        return ("rest", event.offset, event.duration)
    return (
        "note",
        _instrument_identity(event),
        event.offset,
        event.duration,
        100 if event.velocity is None else event.velocity,
        False if event.accent is None else event.accent,
        False if event.ghost is None else event.ghost,
    )


def _instrument_identity(note: RecognizedNote) -> str:
    label = note.instrument.value.strip().casefold()
    return re.sub(r"[\s_-]+", " ", label)


def _fraction(value: RecognizedFraction) -> Fraction:
    return Fraction(value.numerator, value.denominator)


def _overlaps(
    first: RecognizedNote | RecognizedRest,
    second: RecognizedNote | RecognizedRest,
) -> bool:
    first_start = _fraction(first.offset)
    first_end = first_start + _fraction(first.duration)
    second_start = _fraction(second.offset)
    second_end = second_start + _fraction(second.duration)
    return first_start < second_end and second_start < first_end


def _raise_event_error(
    message: str,
    code: RecognitionValidationErrorCode,
    page_number: int,
    part_index: int,
    measure_index: int,
    event_index: int,
) -> None:
    raise RecognitionValidationError(
        message,
        code=code,
        location=RecognitionLocation(
            page_number,
            part_index,
            measure_index,
            event_index,
        ),
    )
