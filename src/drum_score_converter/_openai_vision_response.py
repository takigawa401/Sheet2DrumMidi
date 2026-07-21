"""OpenAI response parsing and provider-independent model conversion."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

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
from drum_score_converter.vision_recognizer import (
    ProviderResponseError,
    RecognitionConversionError,
)


def parse_openai_response(response: Mapping[str, object]) -> dict[str, object]:
    """Extract and parse structured JSON text from an OpenAI response."""
    if not isinstance(response, Mapping):
        raise ProviderResponseError("OpenAI response must be an object.")
    status = response.get("status")
    if status == "incomplete":
        details = response.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, Mapping) else None
        suffix = f" ({reason})" if isinstance(reason, str) else ""
        raise ProviderResponseError(f"OpenAI response was incomplete{suffix}.")
    if status == "failed":
        raise ProviderResponseError("OpenAI response was not completed successfully.")
    output = _require_response_sequence(response.get("output"), "output")
    for item in output:
        item_object = _require_response_mapping(item, "output item")
        if item_object.get("type") != "message":
            continue
        content = _require_response_sequence(
            item_object.get("content"), "message content"
        )
        for content_item in content:
            content_object = _require_response_mapping(content_item, "content item")
            if content_object.get("type") == "refusal":
                raise ProviderResponseError("OpenAI refused the recognition request.")
            if content_object.get("type") != "output_text":
                continue
            text = content_object.get("text")
            if not isinstance(text, str):
                raise ProviderResponseError("OpenAI output text must be a string.")
            try:
                return _json_object(text)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ProviderResponseError(
                    "OpenAI output text is not valid structured JSON."
                ) from error
    raise ProviderResponseError("OpenAI response does not contain output text.")


def convert_openai_data(
    data: Mapping[str, object],
    *,
    expected_page_number: int,
) -> RecognitionResult:
    """Convert parsed provider data into provider-independent models."""
    try:
        page_number = _required_int(data, "page_number")
        if page_number != expected_page_number:
            raise RecognitionConversionError(
                "Provider response page number does not match the rendered page."
            )
        parts = tuple(
            _convert_part(item)
            for item in _require_sequence(data.get("parts"), "parts")
        )
        page = RecognizedPage(
            page_number=page_number,
            parts=parts,
            confidence=_optional_number(data.get("confidence"), "confidence"),
        )
        warnings = tuple(
            _convert_warning(item)
            for item in _require_sequence(data.get("warnings"), "warnings")
        )
        return RecognitionResult(
            pages=(page,),
            title=_optional_string(data.get("title"), "title"),
            warnings=warnings,
        )
    except RecognitionConversionError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise RecognitionConversionError(
            "OpenAI data cannot be converted to a recognition result."
        ) from error


def _convert_part(value: object) -> RecognizedPart:
    data = _require_mapping(value, "part")
    return RecognizedPart(
        name=_optional_string(data.get("name"), "part name"),
        measures=tuple(
            _convert_measure(item)
            for item in _require_sequence(data.get("measures"), "measures")
        ),
        confidence=_optional_number(data.get("confidence"), "confidence"),
    )


def _convert_measure(value: object) -> RecognizedMeasure:
    data = _require_mapping(value, "measure")
    signature_value = data.get("time_signature")
    signature = (
        None
        if signature_value is None
        else _convert_time_signature(signature_value)
    )
    return RecognizedMeasure(
        number=_optional_int(data.get("number"), "measure number"),
        time_signature=signature,
        events=tuple(
            _convert_event(item)
            for item in _require_sequence(data.get("events"), "events")
        ),
        tempo_bpm=_optional_number(data.get("tempo_bpm"), "tempo_bpm"),
        confidence=_optional_number(data.get("confidence"), "confidence"),
    )


def _convert_time_signature(value: object) -> RecognizedTimeSignature:
    data = _require_mapping(value, "time_signature")
    return RecognizedTimeSignature(
        numerator=_required_int(data, "numerator"),
        denominator=_required_int(data, "denominator"),
        confidence=_optional_number(data.get("confidence"), "confidence"),
    )


def _convert_event(value: object) -> RecognizedNote | RecognizedRest:
    data = _require_mapping(value, "event")
    event_type = data.get("type")
    offset = _convert_fraction(data.get("offset"), "offset")
    duration = _convert_fraction(data.get("duration"), "duration")
    confidence = _optional_number(data.get("confidence"), "confidence")
    if event_type == "rest":
        return RecognizedRest(offset, duration, confidence)
    if event_type != "note":
        raise RecognitionConversionError("Event type must be note or rest.")
    instrument_data = _require_mapping(data.get("instrument"), "instrument")
    instrument_value = instrument_data.get("value")
    if not isinstance(instrument_value, str):
        raise RecognitionConversionError("Instrument value must be a string.")
    return RecognizedNote(
        instrument=RecognizedInstrument(
            instrument_value,
            _optional_number(instrument_data.get("confidence"), "confidence"),
        ),
        offset=offset,
        duration=duration,
        velocity=_optional_int(data.get("velocity"), "velocity"),
        accent=_optional_bool(data.get("accent"), "accent"),
        ghost=_optional_bool(data.get("ghost"), "ghost"),
        confidence=confidence,
    )


def _convert_fraction(value: object, field_name: str) -> RecognizedFraction:
    data = _require_mapping(value, field_name)
    return RecognizedFraction(
        _required_int(data, "numerator"),
        _required_int(data, "denominator"),
    )


def _convert_warning(value: object) -> RecognitionWarning:
    data = _require_mapping(value, "warning")
    code = data.get("code")
    message = data.get("message")
    if not isinstance(code, str) or not isinstance(message, str):
        raise RecognitionConversionError("Warning code and message must be strings.")
    location_value = data.get("location")
    location = None if location_value is None else _convert_location(location_value)
    return RecognitionWarning(RecognitionWarningCode(code), message, location)


def _convert_location(value: object) -> RecognitionLocation:
    data = _require_mapping(value, "location")
    return RecognitionLocation(
        page_number=_required_int(data, "page_number"),
        part_index=_optional_int(data.get("part_index"), "part_index"),
        measure_index=_optional_int(data.get("measure_index"), "measure_index"),
        event_index=_optional_int(data.get("event_index"), "event_index"),
    )


def _json_object(text: str) -> dict[str, object]:
    raw: object = json.loads(text)
    if not isinstance(raw, dict):
        raise TypeError("JSON value must be an object")
    result: dict[str, object] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise TypeError("JSON object keys must be strings")
        result[key] = value
    return result


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RecognitionConversionError(f"{field_name} must be an object.")
    if not all(isinstance(key, str) for key in value):
        raise RecognitionConversionError(f"{field_name} keys must be strings.")
    return value


def _require_response_mapping(
    value: object,
    field_name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProviderResponseError(f"OpenAI {field_name} must be an object.")
    if not all(isinstance(key, str) for key in value):
        raise ProviderResponseError(f"OpenAI {field_name} has invalid keys.")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise RecognitionConversionError(f"{field_name} must be an array.")
    return value


def _require_response_sequence(
    value: object,
    field_name: str,
) -> Sequence[object]:
    if not isinstance(value, list):
        raise ProviderResponseError(f"OpenAI {field_name} must be an array.")
    return value


def _required_int(data: Mapping[str, object], field_name: str) -> int:
    if field_name not in data:
        raise RecognitionConversionError(f"{field_name} is required.")
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecognitionConversionError(f"{field_name} must be an integer.")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecognitionConversionError(f"{field_name} must be an integer or null.")
    return value


def _optional_number(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecognitionConversionError(f"{field_name} must be a number or null.")
    return float(value)


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecognitionConversionError(f"{field_name} must be a string or null.")
    return value


def _optional_bool(value: object, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise RecognitionConversionError(f"{field_name} must be a boolean or null.")
    return value
