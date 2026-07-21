"""OpenAI implementation of page-level vision recognition."""

from __future__ import annotations

from urllib.error import HTTPError, URLError

from drum_score_converter._openai_vision_request import (
    build_openai_prompt,
    build_openai_request,
)
from drum_score_converter._openai_vision_response import (
    convert_openai_data,
    parse_openai_response,
)
from drum_score_converter._openai_vision_segments import (
    merge_openai_segments,
    split_openai_page,
)
from drum_score_converter._openai_vision_transport import (
    DEFAULT_OPENAI_ENDPOINT,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    OpenAIConfig,
    OpenAITransport,
    _OpenAIHTTPTransport,
    _ProviderAuthenticationFailure,
    _ProviderCommunicationFailure,
    _ProviderPayloadFailure,
)
from drum_score_converter.page_renderer import RenderedPage
from drum_score_converter.recognition_model import RecognitionResult
from drum_score_converter.vision_recognizer import (
    AuthenticationError,
    CommunicationError,
    ConfigurationError,
    InternalRecognitionError,
    ProviderResponseError,
    RecognitionError,
    VisionRecognizer,
)

__all__ = [
    "DEFAULT_OPENAI_ENDPOINT",
    "DEFAULT_OPENAI_TIMEOUT_SECONDS",
    "OpenAIConfig",
    "OpenAITransport",
    "OpenAIVisionRecognizer",
    "build_openai_prompt",
    "build_openai_request",
    "convert_openai_data",
    "parse_openai_response",
]


class OpenAIVisionRecognizer(VisionRecognizer):
    """Recognize one rendered page through the OpenAI Responses API."""

    def __init__(
        self,
        config: OpenAIConfig | None = None,
        *,
        transport: OpenAITransport | None = None,
    ) -> None:
        if not isinstance(config, OpenAIConfig):
            raise ConfigurationError("config must be an OpenAIConfig.")
        self._config = config
        self._transport = transport if transport is not None else _OpenAIHTTPTransport()

    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        """Recognize one page without retaining page-specific state."""
        try:
            segment_results = []
            for segment in split_openai_page(page):
                request_body = build_openai_request(segment, self._config)
                response = await self._transport.send(self._config, request_body)
                parsed = parse_openai_response(response)
                segment_results.append(
                    convert_openai_data(
                        parsed,
                        expected_page_number=page.page_number,
                    )
                )
            return merge_openai_segments(segment_results)
        except RecognitionError:
            raise
        except _ProviderAuthenticationFailure as error:
            raise AuthenticationError(
                "OpenAI authentication failed during vision recognition."
            ) from error
        except _ProviderCommunicationFailure as error:
            raise CommunicationError(
                f"OpenAI communication failed for page {page.page_number}."
            ) from error
        except _ProviderPayloadFailure as error:
            raise ProviderResponseError(
                f"OpenAI returned an invalid response for page {page.page_number}."
            ) from error
        except HTTPError as error:
            if error.code in {401, 403}:
                raise AuthenticationError(
                    "OpenAI authentication failed during vision recognition."
                ) from error
            raise CommunicationError(
                f"OpenAI communication failed for page {page.page_number}."
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise CommunicationError(
                f"OpenAI communication failed for page {page.page_number}."
            ) from error
        except Exception as error:
            raise InternalRecognitionError(
                "Unexpected error during vision recognition."
            ) from error
