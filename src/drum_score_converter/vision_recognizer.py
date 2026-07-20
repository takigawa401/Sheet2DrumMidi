"""Provider-independent vision recognition contract and errors."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from drum_score_converter.page_renderer import RenderedPage
from drum_score_converter.recognition_model import RecognitionResult


class RecognitionError(Exception):
    """Base class for project-owned vision recognition failures."""


class ConfigurationError(RecognitionError):
    """Raised when recognizer configuration is missing or invalid."""


class AuthenticationError(RecognitionError):
    """Raised when provider credentials are missing or rejected."""


class CommunicationError(RecognitionError):
    """Raised when communication with the provider fails."""


class ProviderResponseError(RecognitionError):
    """Raised when a provider response cannot be structurally parsed."""


class RecognitionConversionError(RecognitionError):
    """Raised when parsed provider data cannot become a recognition result."""


class InternalRecognitionError(RecognitionError):
    """Raised for an unexpected recognizer or dependency failure."""


@runtime_checkable
class VisionRecognizer(Protocol):
    """Stateless page-level vision recognition contract."""

    async def recognize(self, page: RenderedPage) -> RecognitionResult:
        """Recognize exactly one rendered page."""
        ...
