"""Convert provider-independent recognition results into the score domain."""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Final

from drum_score_converter.recognition_model import (
    RecognitionLocation,
    RecognitionResult,
    RecognizedFraction,
    RecognizedMeasure,
    RecognizedNote,
    RecognizedPart,
    RecognizedRest,
)
from drum_score_converter.score_model import (
    DrumInstrument,
    Measure,
    Note,
    Part,
    Rest,
    Score,
    Tempo,
    TimeSignature,
)


class ScoreBuildError(ValueError):
    """Base class for failures while converting recognition data to a score."""

    def __init__(
        self,
        message: str,
        *,
        location: RecognitionLocation | None = None,
    ) -> None:
        super().__init__(message)
        self.location = location


class MissingScoreDataError(ScoreBuildError):
    """Raised when data required by the score domain is missing."""


class InstrumentMappingError(ScoreBuildError):
    """Raised when an instrument label cannot be mapped unambiguously."""


class UnsupportedNotationError(ScoreBuildError):
    """Raised when recognized notation is unsupported by the score domain."""


class InconsistentRecognitionError(ScoreBuildError):
    """Raised when recognition data violates musical domain invariants."""


class ScoreConstructionError(ScoreBuildError):
    """Raised when validated values unexpectedly fail to construct a Score."""


_INSTRUMENT_LABELS: Final[dict[str, DrumInstrument]] = {
    "kick": DrumInstrument.KICK,
    "bass drum": DrumInstrument.KICK,
    "bass drum 1": DrumInstrument.KICK,
    "bd": DrumInstrument.KICK,
    "side stick": DrumInstrument.SIDE_STICK,
    "sidestick": DrumInstrument.SIDE_STICK,
    "cross stick": DrumInstrument.SIDE_STICK,
    "rim click": DrumInstrument.SIDE_STICK,
    "snare": DrumInstrument.SNARE,
    "snare drum": DrumInstrument.SNARE,
    "acoustic snare": DrumInstrument.SNARE,
    "closed hi hat": DrumInstrument.CLOSED_HI_HAT,
    "closed hihat": DrumInstrument.CLOSED_HI_HAT,
    "open hi hat": DrumInstrument.OPEN_HI_HAT,
    "open hihat": DrumInstrument.OPEN_HI_HAT,
    "pedal hi hat": DrumInstrument.PEDAL_HI_HAT,
    "pedal hihat": DrumInstrument.PEDAL_HI_HAT,
    "ride": DrumInstrument.RIDE,
    "ride cymbal": DrumInstrument.RIDE,
    "crash": DrumInstrument.CRASH,
    "crash cymbal": DrumInstrument.CRASH,
    "high tom": DrumInstrument.HIGH_TOM,
    "mid tom": DrumInstrument.MID_TOM,
    "middle tom": DrumInstrument.MID_TOM,
    "floor tom": DrumInstrument.FLOOR_TOM,
}


class ScoreBuilder:
    """Build an immutable Score from one page of recognized notation."""

    def build(self, result: RecognitionResult) -> Score:
        """Convert one recognized page without mutating the input models."""
        if not isinstance(result, RecognitionResult):
            error = TypeError("result must be a RecognitionResult")
            raise ScoreConstructionError(
                "Recognition data cannot be used to construct a score."
            ) from error
        if len(result.pages) != 1:
            raise InconsistentRecognitionError(
                "ScoreBuilder requires exactly one recognized page."
            )

        page = result.pages[0]
        page_location = RecognitionLocation(page.page_number)
        if not page.parts:
            raise MissingScoreDataError(
                "The recognized page must contain at least one part.",
                location=page_location,
            )

        parts = tuple(
            _convert_part(part, page.page_number, part_index)
            for part_index, part in enumerate(page.parts)
        )
        try:
            return Score(parts=parts, title=result.title)
        except (TypeError, ValueError) as error:
            raise ScoreConstructionError(
                "The converted values could not construct a score.",
                location=page_location,
            ) from error


def _convert_part(
    part: RecognizedPart,
    page_number: int,
    part_index: int,
) -> Part:
    location = RecognitionLocation(page_number, part_index)
    if part.name is None:
        raise MissingScoreDataError(
            "A part name is required to construct a score.",
            location=location,
        )
    if not part.measures:
        raise MissingScoreDataError(
            "A part must contain at least one measure.",
            location=location,
        )

    _validate_measure_numbers(part, page_number, part_index)
    measures = tuple(
        _convert_measure(measure, page_number, part_index, measure_index)
        for measure_index, measure in enumerate(part.measures)
    )
    try:
        return Part(name=part.name, measures=measures)
    except (TypeError, ValueError) as error:
        raise InconsistentRecognitionError(
            "The recognized part violates score domain invariants.",
            location=location,
        ) from error


def _validate_measure_numbers(
    part: RecognizedPart,
    page_number: int,
    part_index: int,
) -> None:
    previous: int | None = None
    for measure_index, measure in enumerate(part.measures):
        location = RecognitionLocation(page_number, part_index, measure_index)
        if measure.number is None:
            raise MissingScoreDataError(
                "A measure number is required to construct a score.",
                location=location,
            )
        if previous is not None and measure.number <= previous:
            raise InconsistentRecognitionError(
                "Measure numbers must be strictly increasing within a part.",
                location=location,
            )
        previous = measure.number


def _convert_measure(
    measure: RecognizedMeasure,
    page_number: int,
    part_index: int,
    measure_index: int,
) -> Measure:
    location = RecognitionLocation(page_number, part_index, measure_index)
    if measure.number is None:
        raise MissingScoreDataError(
            "A measure number is required to construct a score.",
            location=location,
        )
    if measure.time_signature is None:
        raise MissingScoreDataError(
            "A time signature is required to construct a score.",
            location=location,
        )

    try:
        signature = TimeSignature(
            measure.time_signature.numerator,
            measure.time_signature.denominator,
        )
        tempo = None if measure.tempo_bpm is None else Tempo(measure.tempo_bpm)
    except (TypeError, ValueError) as error:
        raise InconsistentRecognitionError(
            "Measure metadata violates score domain invariants.",
            location=location,
        ) from error

    converted_events = [
        (
            event_index,
            _convert_event(
                event,
                page_number,
                part_index,
                measure_index,
                event_index,
            ),
        )
        for event_index, event in enumerate(measure.events)
    ]
    converted_events.sort(key=lambda item: item[1].offset)
    events = tuple(event for _, event in converted_events)

    try:
        return Measure(
            number=measure.number,
            time_signature=signature,
            events=events,
            tempo=tempo,
        )
    except (TypeError, ValueError) as error:
        raise InconsistentRecognitionError(
            "Recognized events do not fit the measure.",
            location=location,
        ) from error


def _convert_event(
    event: RecognizedNote | RecognizedRest,
    page_number: int,
    part_index: int,
    measure_index: int,
    event_index: int,
) -> Note | Rest:
    location = RecognitionLocation(
        page_number,
        part_index,
        measure_index,
        event_index,
    )
    try:
        offset = _convert_fraction(event.offset)
        duration = _convert_fraction(event.duration)
        if isinstance(event, RecognizedRest):
            return Rest(offset=offset, duration=duration)
        if isinstance(event, RecognizedNote):
            return Note(
                instrument=_map_instrument(event.instrument.value, location),
                offset=offset,
                duration=duration,
                velocity=100 if event.velocity is None else event.velocity,
                accent=False if event.accent is None else event.accent,
                ghost=False if event.ghost is None else event.ghost,
            )
    except ScoreBuildError:
        raise
    except (TypeError, ValueError) as error:
        raise InconsistentRecognitionError(
            "The recognized event violates score domain invariants.",
            location=location,
        ) from error

    raise UnsupportedNotationError(
        "The recognized event type is not supported.",
        location=location,
    )


def _convert_fraction(value: RecognizedFraction) -> Fraction:
    """Preserve a recognized value expressed in quarter-note units."""
    return Fraction(value.numerator, value.denominator)


def _map_instrument(
    label: str,
    location: RecognitionLocation,
) -> DrumInstrument:
    normalized = re.sub(r"[\s_-]+", " ", label.strip().casefold())
    instrument = _INSTRUMENT_LABELS.get(normalized)
    if instrument is None:
        raise InstrumentMappingError(
            f"Unsupported drum instrument label: {label!r}.",
            location=location,
        )
    return instrument
