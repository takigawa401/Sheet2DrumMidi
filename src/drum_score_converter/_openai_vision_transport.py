"""OpenAI-specific configuration and HTTP transport."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from drum_score_converter.vision_recognizer import (
    AuthenticationError,
    ConfigurationError,
)

DEFAULT_OPENAI_ENDPOINT: Final = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL: Final = "gpt-4.1"
DEFAULT_OPENAI_TIMEOUT_SECONDS: Final = 300.0


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    """Provider-specific configuration for OpenAI vision recognition."""

    api_key: str = field(repr=False)
    model: str = DEFAULT_OPENAI_MODEL
    endpoint: str = DEFAULT_OPENAI_ENDPOINT
    timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise AuthenticationError("OpenAI API credentials are required.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ConfigurationError("An OpenAI model name is required.")
        if not isinstance(self.endpoint, str):
            raise ConfigurationError("The OpenAI endpoint must be a URL.")
        parsed_endpoint = urlparse(self.endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise ConfigurationError("The OpenAI endpoint must be a valid HTTPS URL.")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise ConfigurationError("The OpenAI timeout must be a number.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ConfigurationError("The OpenAI timeout must be finite and positive.")
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))


class OpenAITransport(Protocol):
    """Provider-specific transport boundary used for testing and communication."""

    async def send(
        self,
        config: OpenAIConfig,
        request_body: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class _ProviderAuthenticationFailure(Exception):
    pass


class _ProviderCommunicationFailure(Exception):
    pass


class _ProviderPayloadFailure(Exception):
    pass


class _OpenAIHTTPTransport:
    async def send(
        self,
        config: OpenAIConfig,
        request_body: Mapping[str, object],
    ) -> Mapping[str, object]:
        return await asyncio.to_thread(self._send_sync, config, request_body)

    @staticmethod
    def _send_sync(
        config: OpenAIConfig,
        request_body: Mapping[str, object],
    ) -> Mapping[str, object]:
        request = Request(
            config.endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            if error.code in {401, 403}:
                raise _ProviderAuthenticationFailure from error
            raise _ProviderCommunicationFailure from error
        except (TimeoutError, URLError, OSError) as error:
            raise _ProviderCommunicationFailure from error

        try:
            return _json_object(body)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise _ProviderPayloadFailure from error


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
