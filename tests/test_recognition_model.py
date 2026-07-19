"""Tests for provider-independent recognition result models."""

from dataclasses import FrozenInstanceError
from typing import Any

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


def _note(*, confidence: float | None = None) -> RecognizedNote:
    return RecognizedNote(
        instrument=RecognizedInstrument("snare"),
        offset=RecognizedFraction(0, 1),
        duration=RecognizedFraction(1, 4),
        velocity=100,
        accent=False,
        ghost=None,
        confidence=confidence,
    )


def _result() -> RecognitionResult:
    warning = RecognitionWarning(
        RecognitionWarningCode.LOW_CONFIDENCE,
        "Check the first event",
        RecognitionLocation(1, 0, 0, 0),
    )
    measure = RecognizedMeasure(
        number=1,
        time_signature=RecognizedTimeSignature(4, 4, 0.9),
        events=(_note(confidence=0.8), RecognizedRest(
            RecognizedFraction(1, 4), RecognizedFraction(3, 4)
        )),
        tempo_bpm=120,
        confidence=0.75,
    )
    part = RecognizedPart("Drum Kit", (measure,), confidence=0.7)
    return RecognitionResult(
        (RecognizedPage(1, (part,), confidence=0.6),),
        title="Recognized Score",
        warnings=(warning,),
    )


def test_complete_recognition_result_retains_provider_independent_data() -> None:
    result = _result()

    assert result.title == "Recognized Score"
    assert result.pages[0].parts[0].measures[0].tempo_bpm == 120.0
    assert result.pages[0].parts[0].measures[0].events[0] == _note(
        confidence=0.8
    )
    assert result.warnings[0].location == RecognitionLocation(1, 0, 0, 0)


def test_unknown_instrument_name_is_retained_without_mapping() -> None:
    instrument = RecognizedInstrument("vendor-specific splash stack", 1)

    assert instrument.value == "vendor-specific splash stack"
    assert instrument.confidence == 1.0


@pytest.mark.parametrize("confidence", [None, 0.0, 1.0, 1])
def test_confidence_accepts_none_and_inclusive_range(
    confidence: float | None,
) -> None:
    instrument = RecognizedInstrument("snare", confidence)

    expected = None if confidence is None else float(confidence)
    assert instrument.confidence == expected


@pytest.mark.parametrize(
    "confidence",
    [-0.01, 1.01, float("nan"), float("inf"), float("-inf")],
)
def test_confidence_rejects_out_of_range_or_non_finite_values(
    confidence: float,
) -> None:
    with pytest.raises(ValueError):
        RecognizedInstrument("snare", confidence)


@pytest.mark.parametrize("confidence", [True, False, "0.5"])
def test_confidence_rejects_bool_and_non_numeric_values(confidence: Any) -> None:
    with pytest.raises(TypeError):
        RecognizedInstrument("snare", confidence)


@pytest.mark.parametrize(
    ("numerator", "denominator", "error"),
    [
        (True, 1, TypeError),
        (1, False, TypeError),
        (1.5, 1, TypeError),
        (1, 1.5, TypeError),
        (-1, 1, ValueError),
        (1, 0, ValueError),
        (1, -1, ValueError),
    ],
)
def test_recognized_fraction_validates_integer_non_negative_ratio(
    numerator: Any,
    denominator: Any,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        RecognizedFraction(numerator, denominator)


def test_recognized_fraction_preserves_unreduced_values() -> None:
    value = RecognizedFraction(2, 4)

    assert (value.numerator, value.denominator) == (2, 4)


def test_recognized_time_signature_allows_non_power_of_two_denominator() -> None:
    signature = RecognizedTimeSignature(5, 3)

    assert signature.denominator == 3


@pytest.mark.parametrize(("numerator", "denominator"), [(0, 4), (4, 0)])
def test_recognized_time_signature_requires_positive_values(
    numerator: int,
    denominator: int,
) -> None:
    with pytest.raises(ValueError):
        RecognizedTimeSignature(numerator, denominator)


@pytest.mark.parametrize("field", ["instrument", "offset", "duration"])
def test_recognized_note_validates_required_field_types(field: str) -> None:
    values: dict[str, Any] = {
        "instrument": RecognizedInstrument("snare"),
        "offset": RecognizedFraction(0, 1),
        "duration": RecognizedFraction(1, 1),
    }
    values[field] = object()

    with pytest.raises(TypeError):
        RecognizedNote(**values)


def test_note_and_rest_require_positive_duration() -> None:
    zero = RecognizedFraction(0, 1)
    offset = RecognizedFraction(0, 1)

    with pytest.raises(ValueError, match="duration"):
        RecognizedNote(RecognizedInstrument("snare"), offset, zero)
    with pytest.raises(ValueError, match="duration"):
        RecognizedRest(offset, zero)


@pytest.mark.parametrize("velocity", [True, -1, 128, 1.5])
def test_recognized_note_validates_optional_velocity(velocity: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        RecognizedNote(
            RecognizedInstrument("snare"),
            RecognizedFraction(0, 1),
            RecognizedFraction(1, 1),
            velocity=velocity,
        )


@pytest.mark.parametrize(("field", "value"), [("accent", 1), ("ghost", "yes")])
def test_recognized_note_validates_optional_booleans(field: str, value: Any) -> None:
    values: dict[str, Any] = {field: value}

    with pytest.raises(TypeError):
        RecognizedNote(
            RecognizedInstrument("snare"),
            RecognizedFraction(0, 1),
            RecognizedFraction(1, 1),
            **values,
        )


def test_measure_allows_missing_metadata_unsorted_events_and_overrun() -> None:
    late = RecognizedNote(
        RecognizedInstrument("snare"),
        RecognizedFraction(10, 1),
        RecognizedFraction(1, 1),
    )
    early = _note()

    measure = RecognizedMeasure(None, None, (late, early))

    assert measure.number is None
    assert measure.time_signature is None
    assert measure.events == (late, early)


@pytest.mark.parametrize("tempo", [True, 0, -1, float("nan"), float("inf")])
def test_measure_rejects_invalid_tempo(tempo: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        RecognizedMeasure(None, None, tempo_bpm=tempo)


def test_empty_part_and_empty_page_are_allowed() -> None:
    part = RecognizedPart(None, ())
    page = RecognizedPage(1, ())

    assert part.measures == ()
    assert page.parts == ()


@pytest.mark.parametrize("field", ["events", "measures", "parts", "pages", "warnings"])
def test_collection_fields_reject_lists(field: str) -> None:
    invalid_list: Any = []

    with pytest.raises(TypeError, match=field):
        if field == "events":
            RecognizedMeasure(None, None, events=invalid_list)
        elif field == "measures":
            RecognizedPart(None, invalid_list)
        elif field == "parts":
            RecognizedPage(1, parts=invalid_list)
        elif field == "pages":
            RecognitionResult(invalid_list)
        else:
            RecognitionResult((RecognizedPage(1),), warnings=invalid_list)


def test_collection_fields_reject_wrong_element_types() -> None:
    invalid: Any = object()

    with pytest.raises(TypeError, match="events"):
        RecognizedMeasure(None, None, (invalid,))
    with pytest.raises(TypeError, match="measures"):
        RecognizedPart(None, (invalid,))
    with pytest.raises(TypeError, match="parts"):
        RecognizedPage(1, (invalid,))
    with pytest.raises(TypeError, match="warnings"):
        RecognitionResult((RecognizedPage(1),), warnings=(invalid,))


@pytest.mark.parametrize("page_number", [True, 0, -1, 1.5])
def test_page_number_must_be_a_positive_non_bool_integer(page_number: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        RecognizedPage(page_number)


def test_recognition_result_requires_pages() -> None:
    with pytest.raises(ValueError, match="at least one"):
        RecognitionResult(())


def test_recognition_result_rejects_duplicate_or_unsorted_page_numbers() -> None:
    with pytest.raises(ValueError, match="unique"):
        RecognitionResult((RecognizedPage(1), RecognizedPage(1)))
    with pytest.raises(ValueError, match="increasing"):
        RecognitionResult((RecognizedPage(2), RecognizedPage(1)))


@pytest.mark.parametrize(
    "location",
    [
        RecognitionLocation(1),
        RecognitionLocation(1, 0),
        RecognitionLocation(1, 0, 0),
        RecognitionLocation(1, 0, 0, 0),
    ],
)
def test_recognition_location_accepts_valid_hierarchy(
    location: RecognitionLocation,
) -> None:
    assert location.page_number == 1


def test_recognition_location_rejects_invalid_hierarchy() -> None:
    with pytest.raises(ValueError, match="part_index"):
        RecognitionLocation(1, measure_index=0)
    with pytest.raises(ValueError, match="part_index and measure_index"):
        RecognitionLocation(1, part_index=0, event_index=0)


@pytest.mark.parametrize("index", [True, -1, 1.5])
def test_recognition_location_validates_indices(index: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        RecognitionLocation(1, part_index=index)


def test_recognition_warning_validates_code_message_and_location() -> None:
    invalid: Any = object()

    with pytest.raises(TypeError, match="code"):
        RecognitionWarning(invalid, "message")
    with pytest.raises(ValueError, match="message"):
        RecognitionWarning(RecognitionWarningCode.LOW_CONFIDENCE, " ")
    with pytest.raises(TypeError, match="location"):
        RecognitionWarning(
            RecognitionWarningCode.LOW_CONFIDENCE,
            "message",
            invalid,
        )


def test_optional_names_and_title_reject_blank_strings() -> None:
    with pytest.raises(ValueError, match="value"):
        RecognizedInstrument(" ")
    with pytest.raises(ValueError, match="name"):
        RecognizedPart(" ", ())
    with pytest.raises(ValueError, match="title"):
        RecognitionResult((RecognizedPage(1),), title=" ")


def test_all_recognition_dataclasses_are_frozen() -> None:
    result = _result()
    objects_and_fields: tuple[tuple[object, str], ...] = (
        (RecognizedFraction(1, 1), "numerator"),
        (RecognizedInstrument("snare"), "value"),
        (RecognizedTimeSignature(4, 4), "numerator"),
        (_note(), "velocity"),
        (RecognizedRest(RecognizedFraction(0, 1), RecognizedFraction(1, 1)), "offset"),
        (RecognizedMeasure(None, None), "number"),
        (RecognizedPart(None, ()), "name"),
        (RecognizedPage(1), "page_number"),
        (RecognitionLocation(1), "page_number"),
        (result.warnings[0], "message"),
        (result, "title"),
    )

    for instance, field_name in objects_and_fields:
        with pytest.raises(FrozenInstanceError):
            setattr(instance, field_name, None)


def test_public_types_are_exported_from_package() -> None:
    from drum_score_converter import (
        RecognitionLocation as PublicRecognitionLocation,
    )
    from drum_score_converter import (
        RecognitionResult as PublicRecognitionResult,
    )
    from drum_score_converter import (
        RecognitionWarning as PublicRecognitionWarning,
    )
    from drum_score_converter import (
        RecognitionWarningCode as PublicRecognitionWarningCode,
    )
    from drum_score_converter import (
        RecognizedFraction as PublicRecognizedFraction,
    )
    from drum_score_converter import (
        RecognizedInstrument as PublicRecognizedInstrument,
    )
    from drum_score_converter import (
        RecognizedMeasure as PublicRecognizedMeasure,
    )
    from drum_score_converter import (
        RecognizedNote as PublicRecognizedNote,
    )
    from drum_score_converter import (
        RecognizedPage as PublicRecognizedPage,
    )
    from drum_score_converter import (
        RecognizedPart as PublicRecognizedPart,
    )
    from drum_score_converter import (
        RecognizedRest as PublicRecognizedRest,
    )
    from drum_score_converter import (
        RecognizedTimeSignature as PublicRecognizedTimeSignature,
    )

    assert PublicRecognizedFraction is RecognizedFraction
    assert PublicRecognizedInstrument is RecognizedInstrument
    assert PublicRecognizedTimeSignature is RecognizedTimeSignature
    assert PublicRecognizedNote is RecognizedNote
    assert PublicRecognizedRest is RecognizedRest
    assert PublicRecognizedMeasure is RecognizedMeasure
    assert PublicRecognizedPart is RecognizedPart
    assert PublicRecognizedPage is RecognizedPage
    assert PublicRecognitionWarningCode is RecognitionWarningCode
    assert PublicRecognitionLocation is RecognitionLocation
    assert PublicRecognitionWarning is RecognitionWarning
    assert PublicRecognitionResult is RecognitionResult
