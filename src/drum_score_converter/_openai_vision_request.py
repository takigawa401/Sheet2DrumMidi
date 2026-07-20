"""Prompt, request, and structured-output schema for OpenAI vision."""

from __future__ import annotations

import base64
from typing import Final

from drum_score_converter._openai_vision_transport import OpenAIConfig
from drum_score_converter.page_renderer import RenderedPage
from drum_score_converter.recognition_model import RecognitionWarningCode
from drum_score_converter.vision_recognizer import RecognitionConversionError


def build_openai_prompt(page_number: int) -> str:
    """Build the provider prompt independently from API communication."""
    if isinstance(page_number, bool) or not isinstance(page_number, int):
        raise RecognitionConversionError("Rendered page number must be an integer.")
    if page_number <= 0:
        raise RecognitionConversionError("Rendered page number must be positive.")
    return (
        "Recognize the drum notation on this single rendered score page. "
        f"Return page_number {page_number} exactly. Preserve unknown instrument "
        "labels, missing names, missing measure numbers, missing time signatures, "
        "empty structures, unsorted events, non-standard meters, and uncertain "
        "values when structurally representable. Do not map instruments to a "
        "domain enum, normalize event order, enforce measure capacity, or invent "
        "missing musical data. Express every offset and duration in quarter-note "
        "units: quarter note = 1, eighth note = 1/2, sixteenth note = 1/4, "
        "and a 4/4 measure has capacity 4. Include explicit warnings supplied by "
        "the observed ambiguities."
    )


def build_openai_request(
    page: RenderedPage,
    config: OpenAIConfig,
) -> dict[str, object]:
    """Build an OpenAI Responses API request for one rendered page."""
    if not isinstance(page, RenderedPage):
        raise RecognitionConversionError("page must be a RenderedPage.")
    if not page.content:
        raise RecognitionConversionError("Rendered page content must not be empty.")
    if not isinstance(page.media_type, str) or not page.media_type.startswith("image/"):
        raise RecognitionConversionError("Rendered page media type must be an image.")
    encoded_image = base64.b64encode(page.content).decode("ascii")
    return {
        "model": config.model,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": build_openai_prompt(page.page_number),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{page.media_type};base64,{encoded_image}",
                    },
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "drum_score_recognition",
                "strict": True,
                "schema": _OPENAI_RECOGNITION_SCHEMA,
            }
        },
    }


_CONFIDENCE_SCHEMA: Final[dict[str, object]] = {
    "anyOf": [
        {"type": "number", "minimum": 0, "maximum": 1},
        {"type": "null"},
    ]
}
_FRACTION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "description": (
        "An exact offset or duration in quarter-note units: quarter note = 1, "
        "eighth note = 1/2, sixteenth note = 1/4."
    ),
    "properties": {
        "numerator": {"type": "integer", "minimum": 0},
        "denominator": {"type": "integer", "minimum": 1},
    },
    "required": ["numerator", "denominator"],
    "additionalProperties": False,
}
_TIME_SIGNATURE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "numerator": {"type": "integer", "minimum": 1},
        "denominator": {"type": "integer", "minimum": 1},
        "confidence": _CONFIDENCE_SCHEMA,
    },
    "required": ["numerator", "denominator", "confidence"],
    "additionalProperties": False,
}
_LOCATION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "page_number": {"type": "integer", "minimum": 1},
        "part_index": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        "measure_index": {
            "anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]
        },
        "event_index": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
    },
    "required": ["page_number", "part_index", "measure_index", "event_index"],
    "additionalProperties": False,
}
_INSTRUMENT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"value": {"type": "string"}, "confidence": _CONFIDENCE_SCHEMA},
    "required": ["value", "confidence"],
    "additionalProperties": False,
}
_EVENT_COMMON_PROPERTIES: Final[dict[str, object]] = {
    "offset": _FRACTION_SCHEMA,
    "duration": _FRACTION_SCHEMA,
    "confidence": _CONFIDENCE_SCHEMA,
}
_NOTE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "type": {"const": "note"},
        "instrument": _INSTRUMENT_SCHEMA,
        **_EVENT_COMMON_PROPERTIES,
        "velocity": {
            "anyOf": [
                {"type": "integer", "minimum": 0, "maximum": 127},
                {"type": "null"},
            ]
        },
        "accent": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        "ghost": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
    },
    "required": [
        "type", "instrument", "offset", "duration", "velocity", "accent",
        "ghost", "confidence",
    ],
    "additionalProperties": False,
}
_REST_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"type": {"const": "rest"}, **_EVENT_COMMON_PROPERTIES},
    "required": ["type", "offset", "duration", "confidence"],
    "additionalProperties": False,
}
_MEASURE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "number": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
        "time_signature": {"anyOf": [_TIME_SIGNATURE_SCHEMA, {"type": "null"}]},
        "events": {"type": "array", "items": {"anyOf": [_NOTE_SCHEMA, _REST_SCHEMA]}},
        "tempo_bpm": {
            "anyOf": [
                {"type": "number", "exclusiveMinimum": 0},
                {"type": "null"},
            ]
        },
        "confidence": _CONFIDENCE_SCHEMA,
    },
    "required": ["number", "time_signature", "events", "tempo_bpm", "confidence"],
    "additionalProperties": False,
}
_PART_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "measures": {"type": "array", "items": _MEASURE_SCHEMA},
        "confidence": _CONFIDENCE_SCHEMA,
    },
    "required": ["name", "measures", "confidence"],
    "additionalProperties": False,
}
_WARNING_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "enum": [code.value for code in RecognitionWarningCode],
        },
        "message": {"type": "string"},
        "location": {"anyOf": [_LOCATION_SCHEMA, {"type": "null"}]},
    },
    "required": ["code", "message", "location"],
    "additionalProperties": False,
}
_OPENAI_RECOGNITION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "page_number": {"type": "integer", "minimum": 1},
        "title": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "parts": {"type": "array", "items": _PART_SCHEMA},
        "warnings": {"type": "array", "items": _WARNING_SCHEMA},
        "confidence": _CONFIDENCE_SCHEMA,
    },
    "required": ["page_number", "title", "parts", "warnings", "confidence"],
    "additionalProperties": False,
}
