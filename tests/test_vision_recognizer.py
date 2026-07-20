"""Tests for the page-level vision recognizer contract and OpenAI backend."""

import asyncio
import base64
import inspect
import json
from collections.abc import Mapping
from email.message import Message
from typing import Any
from urllib.error import HTTPError

import pytest

import drum_score_converter._openai_vision_transport as transport_module
from drum_score_converter.openai_vision_recognizer import (
    OpenAIConfig,
    OpenAIVisionRecognizer,
    build_openai_prompt,
    build_openai_request,
    convert_openai_data,
    parse_openai_response,
)
from drum_score_converter.page_renderer import RenderedPage
from drum_score_converter.recognition_model import (
    RecognitionResult,
    RecognitionWarningCode,
    RecognizedNote,
    RecognizedRest,
)
from drum_score_converter.vision_recognizer import (
    AuthenticationError,
    CommunicationError,
    ConfigurationError,
    InternalRecognitionError,
    ProviderResponseError,
    RecognitionConversionError,
    VisionRecognizer,
)

API_KEY = "test-secret-api-key"
IMAGE_BYTES = b"\x89PNG\r\n\x1a\nprivate-image-content"


class StubTransport:
    def __init__(
        self,
        response: Mapping[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[Mapping[str, object]] = []

    async def send(
        self,
        config: OpenAIConfig,
        request_body: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.requests.append(request_body)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("Stub response was not configured")
        return self.response


def _config() -> OpenAIConfig:
    return OpenAIConfig(api_key=API_KEY, model="vision-model")


def _page(page_number: int = 3) -> RenderedPage:
    return RenderedPage(
        page_number=page_number,
        content=IMAGE_BYTES,
        width=100,
        height=200,
        dpi=300,
    )


def _provider_data(page_number: int = 3) -> dict[str, object]:
    return {
        "page_number": page_number,
        "title": "Recognized Drums",
        "parts": [
            {
                "name": "Drum Kit",
                "measures": [
                    {
                        "number": 1,
                        "time_signature": {
                            "numerator": 4,
                            "denominator": 4,
                            "confidence": 0.9,
                        },
                        "events": [
                            {
                                "type": "note",
                                "instrument": {
                                    "value": "unknown-stack-cymbal",
                                    "confidence": 0.4,
                                },
                                "offset": {"numerator": 0, "denominator": 1},
                                "duration": {"numerator": 1, "denominator": 4},
                                "velocity": None,
                                "accent": None,
                                "ghost": False,
                                "confidence": 0.45,
                            },
                            {
                                "type": "rest",
                                "offset": {"numerator": 1, "denominator": 4},
                                "duration": {"numerator": 3, "denominator": 4},
                                "confidence": 0.8,
                            },
                        ],
                        "tempo_bpm": 120,
                        "confidence": 0.7,
                    }
                ],
                "confidence": 0.75,
            }
        ],
        "warnings": [
            {
                "code": "ambiguous_instrument",
                "message": "Instrument label is ambiguous",
                "location": {
                    "page_number": page_number,
                    "part_index": 0,
                    "measure_index": 0,
                    "event_index": 0,
                },
            }
        ],
        "confidence": 0.65,
    }


def _openai_response(data: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps(data)}
                ],
            }
        ],
    }


def test_vision_recognizer_protocol_has_async_page_contract() -> None:
    transport = StubTransport(_openai_response(_provider_data()))
    recognizer: VisionRecognizer = OpenAIVisionRecognizer(
        _config(), transport=transport
    )

    assert inspect.iscoroutinefunction(VisionRecognizer.recognize)
    assert inspect.iscoroutinefunction(recognizer.recognize)
    assert isinstance(recognizer, VisionRecognizer)


def test_recognize_returns_exactly_one_matching_page_without_live_api() -> None:
    transport = StubTransport(_openai_response(_provider_data()))
    recognizer = OpenAIVisionRecognizer(_config(), transport=transport)

    result = asyncio.run(recognizer.recognize(_page()))

    assert isinstance(result, RecognitionResult)
    assert len(result.pages) == 1
    assert result.pages[0].page_number == _page().page_number
    assert len(transport.requests) == 1
    note = result.pages[0].parts[0].measures[0].events[0]
    rest = result.pages[0].parts[0].measures[0].events[1]
    assert isinstance(note, RecognizedNote)
    assert note.instrument.value == "unknown-stack-cymbal"
    assert isinstance(rest, RecognizedRest)
    assert result.warnings[0].code is RecognitionWarningCode.AMBIGUOUS_INSTRUMENT


def test_same_recognizer_instance_can_be_reused_for_separate_pages() -> None:
    transport = StubTransport(_openai_response(_provider_data(page_number=1)))
    recognizer = OpenAIVisionRecognizer(_config(), transport=transport)

    first = asyncio.run(recognizer.recognize(_page(page_number=1)))
    transport.response = _openai_response(_provider_data(page_number=2))
    second = asyncio.run(recognizer.recognize(_page(page_number=2)))

    assert first.pages[0].page_number == 1
    assert second.pages[0].page_number == 2
    assert len(transport.requests) == 2


def test_prompt_and_request_building_are_independently_testable() -> None:
    page = _page()

    prompt = build_openai_prompt(page.page_number)
    request = build_openai_request(page, _config())
    request_text = json.dumps(request)

    assert str(page.page_number) in prompt
    assert "Do not map instruments" in prompt
    assert "quarter-note units" in prompt
    assert "4/4 measure has capacity 4" in prompt
    assert request["model"] == "vision-model"
    encoded = base64.b64encode(page.content).decode("ascii")
    assert f"data:image/png;base64,{encoded}" in request_text
    assert '"type": "json_schema"' in request_text
    assert "quarter-note units" in request_text


def test_provider_response_parsing_is_independently_testable() -> None:
    data = _provider_data()

    parsed = parse_openai_response(_openai_response(data))

    assert parsed == data


def test_provider_data_conversion_is_independently_testable() -> None:
    result = convert_openai_data(_provider_data(), expected_page_number=3)

    assert result.pages[0].page_number == 3
    assert result.title == "Recognized Drums"
    assert result.pages[0].confidence == 0.65


def test_musically_incomplete_but_structural_data_is_preserved() -> None:
    data: dict[str, object] = {
        "page_number": 3,
        "title": None,
        "parts": [
            {
                "name": None,
                "measures": [
                    {
                        "number": None,
                        "time_signature": None,
                        "events": [
                            {
                                "type": "note",
                                "instrument": {
                                    "value": "never-seen-instrument",
                                    "confidence": 0.1,
                                },
                                "offset": {"numerator": 10, "denominator": 1},
                                "duration": {"numerator": 3, "denominator": 1},
                                "velocity": None,
                                "accent": None,
                                "ghost": None,
                                "confidence": 0.1,
                            }
                        ],
                        "tempo_bpm": None,
                        "confidence": 0.1,
                    }
                ],
                "confidence": None,
            },
            {"name": None, "measures": [], "confidence": None},
        ],
        "warnings": [
            {
                "code": "low_confidence",
                "message": "Recognition confidence is low",
                "location": None,
            }
        ],
        "confidence": 0.1,
    }

    result = convert_openai_data(data, expected_page_number=3)

    measure = result.pages[0].parts[0].measures[0]
    assert result.pages[0].parts[0].name is None
    assert result.pages[0].parts[1].measures == ()
    assert measure.number is None
    assert measure.time_signature is None
    assert measure.events[0].offset.numerator == 10


def test_empty_recognized_page_is_accepted() -> None:
    data: dict[str, object] = {
        "page_number": 3,
        "title": None,
        "parts": [],
        "warnings": [],
        "confidence": None,
    }

    result = convert_openai_data(data, expected_page_number=3)

    assert result.pages[0].parts == ()


@pytest.mark.parametrize(
    "config",
    [
        None,
        object(),
    ],
)
def test_missing_or_wrong_config_is_configuration_error(config: Any) -> None:
    with pytest.raises(ConfigurationError):
        OpenAIVisionRecognizer(config)


def test_omitted_config_is_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        OpenAIVisionRecognizer()


def test_missing_credentials_are_authentication_error() -> None:
    with pytest.raises(AuthenticationError, match="credentials"):
        OpenAIConfig(api_key=" ", model="vision-model")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": ""},
        {"model": "vision-model", "endpoint": "http://insecure.example/v1"},
        {"model": "vision-model", "timeout_seconds": 0},
    ],
)
def test_invalid_provider_settings_are_configuration_error(
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(ConfigurationError):
        OpenAIConfig(api_key=API_KEY, **kwargs)


def test_provider_authentication_failure_is_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise HTTPError(
            "https://api.openai.com",
            401,
            "Unauthorized",
            Message(),
            None,
        )

    monkeypatch.setattr(transport_module, "urlopen", reject)

    with pytest.raises(AuthenticationError) as captured:
        asyncio.run(OpenAIVisionRecognizer(_config()).recognize(_page()))

    assert API_KEY not in str(captured.value)
    assert base64.b64encode(IMAGE_BYTES).decode("ascii") not in str(captured.value)


def test_provider_timeout_is_communication_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(transport_module, "urlopen", timeout)

    with pytest.raises(CommunicationError, match="page 3"):
        asyncio.run(OpenAIVisionRecognizer(_config()).recognize(_page()))


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "failed", "output": []},
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "not-json"}],
                }
            ],
        },
    ],
)
def test_invalid_provider_response_is_provider_response_error(
    response: Mapping[str, object],
) -> None:
    with pytest.raises(ProviderResponseError):
        parse_openai_response(response)


def test_conversion_failure_is_recognition_conversion_error() -> None:
    data = _provider_data()
    data["confidence"] = 2.0

    with pytest.raises(RecognitionConversionError):
        convert_openai_data(data, expected_page_number=3)


def test_page_number_mismatch_is_recognition_conversion_error() -> None:
    with pytest.raises(RecognitionConversionError, match="does not match"):
        convert_openai_data(_provider_data(page_number=4), expected_page_number=3)


def test_unexpected_error_becomes_internal_error_with_original_cause() -> None:
    original = RuntimeError("unexpected provider failure")
    recognizer = OpenAIVisionRecognizer(
        _config(), transport=StubTransport(error=original)
    )

    with pytest.raises(InternalRecognitionError) as captured:
        asyncio.run(recognizer.recognize(_page()))

    assert captured.value.__cause__ is original


def test_existing_recognition_error_is_not_rewrapped() -> None:
    original = ProviderResponseError("safe provider response error")
    recognizer = OpenAIVisionRecognizer(
        _config(), transport=StubTransport(error=original)
    )

    with pytest.raises(ProviderResponseError) as captured:
        asyncio.run(recognizer.recognize(_page()))

    assert captured.value is original


def test_secrets_are_not_in_public_internal_error_message() -> None:
    unsafe_message = f"{API_KEY}:{base64.b64encode(IMAGE_BYTES).decode('ascii')}"
    recognizer = OpenAIVisionRecognizer(
        _config(), transport=StubTransport(error=RuntimeError(unsafe_message))
    )

    with pytest.raises(InternalRecognitionError) as captured:
        asyncio.run(recognizer.recognize(_page()))

    message = str(captured.value)
    assert API_KEY not in message
    assert base64.b64encode(IMAGE_BYTES).decode("ascii") not in message
    assert API_KEY not in repr(_config())


def test_public_recognizer_api_uses_project_owned_types() -> None:
    from drum_score_converter import (
        AuthenticationError as PublicAuthenticationError,
    )
    from drum_score_converter import OpenAIConfig as PublicOpenAIConfig
    from drum_score_converter import (
        OpenAIVisionRecognizer as PublicOpenAIVisionRecognizer,
    )
    from drum_score_converter import RecognitionError as PublicRecognitionError
    from drum_score_converter import VisionRecognizer as PublicVisionRecognizer

    assert PublicVisionRecognizer is VisionRecognizer
    assert PublicOpenAIConfig is OpenAIConfig
    assert PublicOpenAIVisionRecognizer is OpenAIVisionRecognizer
    assert issubclass(PublicAuthenticationError, PublicRecognitionError)
