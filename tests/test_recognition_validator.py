"""Tests for semantic validation of recognition results."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

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
from drum_score_converter.recognition_validator import (
    RecognitionValidationError,
    RecognitionValidationErrorCode,
    RecognitionValidationWarning,
    RecognitionValidationWarningCode,
    RecognitionValidator,
)
from drum_score_converter.score_builder import ScoreBuilder


def _fraction(numerator: int, denominator: int = 1) -> RecognizedFraction:
    return RecognizedFraction(numerator, denominator)


def _note(
    instrument: str = "snare",
    *,
    offset: RecognizedFraction | None = None,
    duration: RecognizedFraction | None = None,
    velocity: int | None = 90,
    accent: bool | None = False,
    ghost: bool | None = False,
    confidence: float | None = None,
    instrument_confidence: float | None = None,
) -> RecognizedNote:
    return RecognizedNote(
        RecognizedInstrument(instrument, instrument_confidence),
        _fraction(0) if offset is None else offset,
        _fraction(1) if duration is None else duration,
        velocity,
        accent,
        ghost,
        confidence,
    )


def _measure(
    *,
    number: int | None = 1,
    signature: RecognizedTimeSignature | None = None,
    events: tuple[RecognizedNote | RecognizedRest, ...] = (),
) -> RecognizedMeasure:
    return RecognizedMeasure(
        number,
        RecognizedTimeSignature(4, 4) if signature is None else signature,
        events,
    )


def _result(
    measures: tuple[RecognizedMeasure, ...],
    *,
    warnings: tuple[RecognitionWarning, ...] = (),
) -> RecognitionResult:
    part = RecognizedPart("Drums", measures)
    return RecognitionResult(
        (RecognizedPage(1, (part,)),),
        warnings=warnings,
    )


def _assert_error(
    result: RecognitionResult,
    code: RecognitionValidationErrorCode,
    location: RecognitionLocation,
) -> RecognitionValidationError:
    with pytest.raises(RecognitionValidationError) as caught:
        RecognitionValidator().validate(result)
    assert caught.value.code is code
    assert caught.value.location == location
    assert str(caught.value)
    return caught.value


def test_valid_notes_rests_chords_adjacency_and_measure_gaps() -> None:
    events = (
        _note("kick", duration=_fraction(1, 2)),
        _note("closed hi-hat", duration=_fraction(1, 2)),
        RecognizedRest(_fraction(1, 2), _fraction(1, 2)),
        _note("snare", offset=_fraction(3), duration=_fraction(1)),
    )
    result = _result((_measure(events=events),))

    assert RecognitionValidator().validate(result) == ()
    assert ScoreBuilder().build(result).parts[0].measures[0].number == 1


def test_multiple_pages_and_parts_are_checked_in_input_order() -> None:
    valid_part = RecognizedPart("First", (_measure(),))
    invalid_part = RecognizedPart(
        "Second",
        (_measure(number=2), _measure(number=1)),
    )
    result = RecognitionResult(
        (
            RecognizedPage(1, (valid_part, valid_part)),
            RecognizedPage(2, (valid_part, invalid_part)),
        )
    )

    _assert_error(
        result,
        RecognitionValidationErrorCode.DESCENDING_MEASURE_NUMBER,
        RecognitionLocation(2, 1, 1),
    )


def test_validation_does_not_mutate_the_result() -> None:
    events = (
        _note("kick", offset=_fraction(2)),
        _note("snare", offset=_fraction(0)),
    )
    result = _result((_measure(events=events),))
    original_events = result.pages[0].parts[0].measures[0].events

    warnings = RecognitionValidator().validate(result)

    assert warnings
    assert result.pages[0].parts[0].measures[0].events is original_events
    assert result.pages[0].parts[0].measures[0].events == events


@pytest.mark.parametrize(
    ("measures", "code", "location"),
    [
        (
            (_measure(number=None),),
            RecognitionValidationErrorCode.MISSING_MEASURE_NUMBER,
            RecognitionLocation(1, 0, 0),
        ),
        (
            (_measure(number=1), _measure(number=1)),
            RecognitionValidationErrorCode.DUPLICATE_MEASURE_NUMBER,
            RecognitionLocation(1, 0, 1),
        ),
        (
            (_measure(number=2), _measure(number=1)),
            RecognitionValidationErrorCode.DESCENDING_MEASURE_NUMBER,
            RecognitionLocation(1, 0, 1),
        ),
    ],
)
def test_invalid_measure_numbering_is_fatal(
    measures: tuple[RecognizedMeasure, ...],
    code: RecognitionValidationErrorCode,
    location: RecognitionLocation,
) -> None:
    _assert_error(_result(measures), code, location)


def test_missing_time_signature_is_fatal() -> None:
    result = _result((RecognizedMeasure(1, None),))

    _assert_error(
        result,
        RecognitionValidationErrorCode.MISSING_TIME_SIGNATURE,
        RecognitionLocation(1, 0, 0),
    )


def test_non_power_of_two_time_signature_denominator_is_fatal() -> None:
    result = _result((_measure(signature=RecognizedTimeSignature(4, 3)),))

    _assert_error(
        result,
        RecognitionValidationErrorCode.UNSUPPORTED_TIME_SIGNATURE,
        RecognitionLocation(1, 0, 0),
    )


def test_event_may_end_at_but_not_beyond_measure_capacity() -> None:
    boundary = _result(
        (_measure(events=(_note(offset=_fraction(3), duration=_fraction(1)),)),)
    )
    assert RecognitionValidator().validate(boundary) == ()

    overrun = _result(
        (
            _measure(
                events=(_note(offset=_fraction(7, 2), duration=_fraction(1)),)
            ),
        )
    )
    _assert_error(
        overrun,
        RecognitionValidationErrorCode.EVENT_OUTSIDE_MEASURE,
        RecognitionLocation(1, 0, 0, 0),
    )


def test_note_duplicates_ignore_recognition_confidence() -> None:
    first = _note(confidence=0.2, instrument_confidence=0.3)
    duplicate = _note(confidence=0.9, instrument_confidence=0.8)

    _assert_error(
        _result((_measure(events=(first, duplicate)),)),
        RecognitionValidationErrorCode.DUPLICATE_EVENT,
        RecognitionLocation(1, 0, 0, 1),
    )


def test_note_defaults_are_normalized_before_duplicate_comparison() -> None:
    unspecified = _note(velocity=None, accent=None, ghost=None)
    explicit_defaults = _note(velocity=100, accent=False, ghost=False)

    _assert_error(
        _result((_measure(events=(unspecified, explicit_defaults)),)),
        RecognitionValidationErrorCode.DUPLICATE_EVENT,
        RecognitionLocation(1, 0, 0, 1),
    )


def test_note_value_different_from_default_remains_contradictory() -> None:
    unspecified = _note(velocity=None, accent=None, ghost=None)
    different = _note(velocity=99, accent=False, ghost=False)

    _assert_error(
        _result((_measure(events=(unspecified, different)),)),
        RecognitionValidationErrorCode.CONTRADICTORY_NOTE,
        RecognitionLocation(1, 0, 0, 1),
    )


@pytest.mark.parametrize(
    "changed",
    [
        _note(duration=_fraction(1, 2)),
        _note(velocity=50),
        _note(accent=True),
        _note(ghost=True),
    ],
)
def test_notes_at_same_instrument_and_offset_must_not_contradict(
    changed: RecognizedNote,
) -> None:
    _assert_error(
        _result((_measure(events=(_note(), changed)),)),
        RecognitionValidationErrorCode.CONTRADICTORY_NOTE,
        RecognitionLocation(1, 0, 0, 1),
    )


def test_note_time_overlap_alone_is_valid() -> None:
    events = (
        _note("snare", duration=_fraction(2)),
        _note("snare", offset=_fraction(1), duration=_fraction(2)),
    )

    assert RecognitionValidator().validate(_result((_measure(events=events),))) == ()


def test_overlapping_rests_are_fatal_but_adjacent_rests_are_valid() -> None:
    adjacent = (
        RecognizedRest(_fraction(0), _fraction(1)),
        RecognizedRest(_fraction(1), _fraction(1)),
    )
    assert RecognitionValidator().validate(
        _result((_measure(events=adjacent),))
    ) == ()

    overlapping = adjacent + (RecognizedRest(_fraction(3, 2), _fraction(1)),)
    _assert_error(
        _result((_measure(events=overlapping),)),
        RecognitionValidationErrorCode.OVERLAPPING_RESTS,
        RecognitionLocation(1, 0, 0, 2),
    )


def test_rest_and_note_intervals_must_not_overlap() -> None:
    events = (
        RecognizedRest(_fraction(0), _fraction(2)),
        _note(offset=_fraction(1), duration=_fraction(1)),
    )

    _assert_error(
        _result((_measure(events=events),)),
        RecognitionValidationErrorCode.REST_NOTE_CONFLICT,
        RecognitionLocation(1, 0, 0, 1),
    )


def test_unsorted_events_return_warning_without_reordering() -> None:
    events = (
        _note("kick", offset=_fraction(2)),
        _note("snare", offset=_fraction(0)),
        _note("ride", offset=_fraction(0)),
    )
    result = _result((_measure(events=events),))

    warnings = RecognitionValidator().validate(result)

    assert warnings == (
        RecognitionValidationWarning(
            RecognitionValidationWarningCode.UNSORTED_EVENTS,
            "Recognized events are not in ascending offset order.",
            RecognitionLocation(1, 0, 0),
        ),
    )
    assert result.pages[0].parts[0].measures[0].events == events


def test_provider_warning_is_not_modified_or_replaced() -> None:
    provider_warning = RecognitionWarning(
        RecognitionWarningCode.LOW_CONFIDENCE,
        "Review this measure.",
        RecognitionLocation(1, 0, 0),
    )
    result = _result((_measure(),), warnings=(provider_warning,))

    assert RecognitionValidator().validate(result) == ()
    assert result.warnings == (provider_warning,)
    assert result.warnings[0] is provider_warning


def test_validation_warning_is_immutable() -> None:
    warning = RecognitionValidationWarning(
        RecognitionValidationWarningCode.UNSORTED_EVENTS,
        "Events are unsorted.",
    )

    with pytest.raises(FrozenInstanceError):
        setattr(warning, "message", "changed")


def test_error_message_does_not_include_unrelated_sensitive_input() -> None:
    secret = "api-key-secret-full-provider-response"
    warning = RecognitionWarning(RecognitionWarningCode.LOW_CONFIDENCE, secret)
    result = _result(
        (_measure(events=(_note(), _note())),),
        warnings=(warning,),
    )

    error = _assert_error(
        result,
        RecognitionValidationErrorCode.DUPLICATE_EVENT,
        RecognitionLocation(1, 0, 0, 1),
    )
    assert secret not in str(error)


def test_public_validation_types_are_exported() -> None:
    from drum_score_converter import (
        RecognitionValidationError as PublicError,
    )
    from drum_score_converter import (
        RecognitionValidationErrorCode as PublicErrorCode,
    )
    from drum_score_converter import (
        RecognitionValidationWarning as PublicWarning,
    )
    from drum_score_converter import (
        RecognitionValidationWarningCode as PublicWarningCode,
    )
    from drum_score_converter import RecognitionValidator as PublicValidator

    assert PublicValidator is RecognitionValidator
    assert PublicError is RecognitionValidationError
    assert PublicErrorCode is RecognitionValidationErrorCode
    assert PublicWarning is RecognitionValidationWarning
    assert PublicWarningCode is RecognitionValidationWarningCode
