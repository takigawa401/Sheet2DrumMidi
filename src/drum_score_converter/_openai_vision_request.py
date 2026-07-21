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
        "Recognize every drum-notation measure on this single rendered score page, "
        "reading systems from top to bottom and measures from left to right. "
        "Treat only full-height vertical barlines spanning the staff as measure "
        "boundaries. Note stems, beams, beat divisions, and voice changes are not "
        "barlines. Return exactly one measure per visible space between barlines; "
        "never subdivide one measure into separate beats or notation voices. "
        f"Return page_number {page_number} exactly. Assign measures page-local "
        "sequential numbers starting at 1, even when measure numbers are not "
        "printed. Supply the time signature for every measure when it can be "
        "determined from a visible meter or its continuation on the page. Use a "
        "stable descriptive part name; use Drum Kit for a single drum-set staff. "
        "Interpret standard drum-set notation across all voices: low staff notes "
        "are typically kick, middle notes are snare, vertically placed middle and "
        "upper notes are toms, x-shaped upper noteheads are hi-hat or cymbal hits, "
        "and explicit HH, Ride, Cup, open, or mute markings refine the instrument. "
        "When applicable, prefer these canonical labels: Kick, Side Stick, Snare, "
        "Closed Hi Hat, Open Hi Hat, Pedal Hi Hat, Ride, Crash, High Tom, Mid Tom, "
        "and Floor Tom. "
        "Never emit more than one note for the same canonical instrument at the "
        "same offset. If notation voices duplicate one physical attack, represent "
        "that attack once with one consistent duration and set of attributes. "
        "Treat Cup as ride and other clearly cymbal-shaped accent hits as crash "
        "when no more specific supported label is visible. Emit a separate note "
        "for every visible drum hit, including simultaneous hits at the same "
        "offset. Derive offsets and durations from note values, beams, dots, and "
        "the beat grid. Set accent and ghost from their notation when visible. "
        "A rest in one notation voice does not mean silence when another drum "
        "voice sounds. In any measure containing notes, omit rests and leave "
        "silent intervals as gaps. Emit a rest only for a fully silent measure. "
        "Expand a one-measure repeat sign by repeating the preceding measure's "
        "events when that preceding measure is visible on this page. A genuinely "
        "empty or fully silent measure may contain one full-measure rest, but do "
        "not return an empty measure merely because its notation is complex. "
        "Preserve unknown instrument labels, empty structures, unsorted events, "
        "non-standard meters, and uncertain values when structurally representable. "
        "Do not map instruments to a domain enum, normalize event order, enforce "
        "measure capacity, or invent notes and rests that are not visible. Express "
        "every offset and duration in quarter-note "
        "units: quarter note = 1, eighth note = 1/2, sixteenth note = 1/4, "
        "duration must always be positive, and a 4/4 measure has capacity 4. "
        "Include explicit warnings supplied by the observed ambiguities. Before "
        "returning, verify that each event is present only once, each instrument "
        "appears at most once at an offset, measures with notes contain no rests, "
        "all durations are positive, and every event fits its measure capacity."
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
        "temperature": 0,
        "max_output_tokens": 16_384,
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
                        "detail": "high",
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
_OFFSET_SCHEMA: Final[dict[str, object]] = {
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
_DURATION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "description": "A positive duration in quarter-note units.",
    "properties": {
        "numerator": {"type": "integer", "minimum": 1},
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
    "properties": {
        "value": {"type": "string", "minLength": 1},
        "confidence": _CONFIDENCE_SCHEMA,
    },
    "required": ["value", "confidence"],
    "additionalProperties": False,
}
_EVENT_COMMON_PROPERTIES: Final[dict[str, object]] = {
    "offset": _OFFSET_SCHEMA,
    "duration": _DURATION_SCHEMA,
    "confidence": _CONFIDENCE_SCHEMA,
}
_NOTE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "const": "note"},
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
    "properties": {
        "type": {"type": "string", "const": "rest"},
        **_EVENT_COMMON_PROPERTIES,
    },
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
        "name": {
            "anyOf": [
                {"type": "string", "minLength": 1},
                {"type": "null"},
            ]
        },
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
        "message": {"type": "string", "minLength": 1},
        "location": {"anyOf": [_LOCATION_SCHEMA, {"type": "null"}]},
    },
    "required": ["code", "message", "location"],
    "additionalProperties": False,
}
_OPENAI_RECOGNITION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "page_number": {"type": "integer", "minimum": 1},
        "title": {
            "anyOf": [
                {"type": "string", "minLength": 1},
                {"type": "null"},
            ]
        },
        "parts": {"type": "array", "items": _PART_SCHEMA},
        "warnings": {"type": "array", "items": _WARNING_SCHEMA},
        "confidence": _CONFIDENCE_SCHEMA,
    },
    "required": ["page_number", "title", "parts", "warnings", "confidence"],
    "additionalProperties": False,
}
