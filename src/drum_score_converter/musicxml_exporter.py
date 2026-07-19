"""MusicXML export for the drum score domain model."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Final

from drum_score_converter.score_model import (
    DrumInstrument,
    Measure,
    Note,
    Part,
    Rest,
    Score,
)

_MUSICXML_VERSION: Final = "4.0"
_MAX_DIVISIONS: Final = 16_383
_XML_DECLARATION: Final = '<?xml version="1.0" encoding="UTF-8"?>'
_DOCTYPE: Final = (
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
    '"http://www.musicxml.org/dtds/partwise.dtd">'
)


@dataclass(frozen=True, slots=True)
class MusicXMLInstrument:
    """MusicXML notation details for one domain instrument."""

    name: str
    display_step: str
    display_octave: int
    notehead: str


INSTRUMENT_MAPPING: Final[Mapping[DrumInstrument, MusicXMLInstrument]] = (
    MappingProxyType(
        {
            DrumInstrument.KICK: MusicXMLInstrument("Kick Drum", "F", 4, "normal"),
            DrumInstrument.SIDE_STICK: MusicXMLInstrument(
                "Side Stick", "C", 5, "x"
            ),
            DrumInstrument.SNARE: MusicXMLInstrument("Snare Drum", "C", 5, "normal"),
            DrumInstrument.CLOSED_HI_HAT: MusicXMLInstrument(
                "Closed Hi-Hat", "G", 5, "x"
            ),
            DrumInstrument.OPEN_HI_HAT: MusicXMLInstrument(
                "Open Hi-Hat", "G", 5, "circle-x"
            ),
            DrumInstrument.PEDAL_HI_HAT: MusicXMLInstrument(
                "Pedal Hi-Hat", "D", 5, "x"
            ),
            DrumInstrument.RIDE: MusicXMLInstrument("Ride Cymbal", "F", 5, "x"),
            DrumInstrument.CRASH: MusicXMLInstrument("Crash Cymbal", "A", 5, "x"),
            DrumInstrument.HIGH_TOM: MusicXMLInstrument(
                "High Tom", "E", 5, "normal"
            ),
            DrumInstrument.MID_TOM: MusicXMLInstrument(
                "Mid Tom", "D", 5, "normal"
            ),
            DrumInstrument.FLOOR_TOM: MusicXMLInstrument(
                "Floor Tom", "A", 4, "normal"
            ),
        }
    )
)


class MusicXMLExportError(ValueError):
    """Raised when a valid domain score cannot be represented by this exporter."""


class MusicXMLExporter:
    """Convert a Score into a partwise MusicXML 4.0 document."""

    def to_string(self, score: Score) -> str:
        """Return a complete UTF-8-declared MusicXML document as text."""
        if not isinstance(score, Score):
            raise TypeError("score must be a Score")

        root = ET.Element("score-partwise", version=_MUSICXML_VERSION)
        if score.title is not None:
            ET.SubElement(root, "movement-title").text = score.title

        part_list = ET.SubElement(root, "part-list")
        for part_index, part in enumerate(score.parts, start=1):
            self._append_score_part(part_list, part, part_index)

        for part_index, part in enumerate(score.parts, start=1):
            self._append_part(root, part, part_index)

        ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
        return f"{_XML_DECLARATION}\n{_DOCTYPE}\n{body}\n"

    def write(self, score: Score, path: str | Path) -> None:
        """Write a MusicXML document to path using UTF-8 and LF newlines."""
        Path(path).write_text(
            self.to_string(score),
            encoding="utf-8",
            newline="\n",
        )

    def _append_score_part(
        self, part_list: ET.Element, part: Part, part_index: int
    ) -> None:
        score_part = ET.SubElement(part_list, "score-part", id=_part_id(part_index))
        ET.SubElement(score_part, "part-name").text = part.name

        for instrument in _used_instruments(part):
            score_instrument = ET.SubElement(
                score_part,
                "score-instrument",
                id=_instrument_id(part_index, instrument),
            )
            ET.SubElement(score_instrument, "instrument-name").text = (
                INSTRUMENT_MAPPING[instrument].name
            )

    def _append_part(self, root: ET.Element, part: Part, part_index: int) -> None:
        part_element = ET.SubElement(root, "part", id=_part_id(part_index))
        for measure in part.measures:
            self._append_measure(part_element, measure, part_index)

    def _append_measure(
        self, part_element: ET.Element, measure: Measure, part_index: int
    ) -> None:
        divisions = _measure_divisions(measure)
        measure_element = ET.SubElement(
            part_element,
            "measure",
            number=str(measure.number),
        )
        self._append_attributes(measure_element, measure, divisions)

        if measure.tempo is not None:
            self._append_tempo(measure_element, measure.tempo.bpm)

        groups: dict[Fraction, list[Note | Rest]] = {}
        for event in measure.events:
            groups.setdefault(event.offset, []).append(event)

        position = Fraction(0)
        for offset in sorted(groups):
            if offset < position:
                raise MusicXMLExportError(
                    f"measure {measure.number} has overlapping event groups"
                )
            if offset > position:
                self._append_forward(
                    measure_element,
                    _to_divisions(offset - position, divisions),
                )
                position = offset

            group = groups[offset]
            notes = [event for event in group if isinstance(event, Note)]
            rests = [event for event in group if isinstance(event, Rest)]
            if notes and rests:
                raise MusicXMLExportError(
                    f"measure {measure.number} mixes notes and rests at one offset"
                )
            if len(rests) > 1:
                raise MusicXMLExportError(
                    f"measure {measure.number} has multiple rests at one offset"
                )

            if notes:
                notes.sort(key=lambda note: note.duration, reverse=True)
                for note_index, note in enumerate(notes):
                    self._append_note(
                        measure_element,
                        note,
                        divisions,
                        part_index,
                        is_chord=note_index > 0,
                    )
                position += notes[0].duration
            else:
                rest = rests[0]
                self._append_rest(measure_element, rest, divisions)
                position += rest.duration

        if position < measure.duration:
            self._append_forward(
                measure_element,
                _to_divisions(measure.duration - position, divisions),
            )

    @staticmethod
    def _append_attributes(
        measure_element: ET.Element, measure: Measure, divisions: int
    ) -> None:
        attributes = ET.SubElement(measure_element, "attributes")
        ET.SubElement(attributes, "divisions").text = str(divisions)
        time = ET.SubElement(attributes, "time")
        ET.SubElement(time, "beats").text = str(measure.time_signature.numerator)
        ET.SubElement(time, "beat-type").text = str(
            measure.time_signature.denominator
        )
        clef = ET.SubElement(attributes, "clef")
        ET.SubElement(clef, "sign").text = "percussion"
        ET.SubElement(clef, "line").text = "2"

    @staticmethod
    def _append_tempo(measure_element: ET.Element, bpm: float) -> None:
        tempo = format(bpm, ".15g")
        direction = ET.SubElement(measure_element, "direction", placement="above")
        direction_type = ET.SubElement(direction, "direction-type")
        metronome = ET.SubElement(direction_type, "metronome")
        ET.SubElement(metronome, "beat-unit").text = "quarter"
        ET.SubElement(metronome, "per-minute").text = tempo
        ET.SubElement(direction, "sound", tempo=tempo)

    @staticmethod
    def _append_note(
        measure_element: ET.Element,
        note: Note,
        divisions: int,
        part_index: int,
        *,
        is_chord: bool,
    ) -> None:
        note_element = ET.SubElement(measure_element, "note")
        if is_chord:
            ET.SubElement(note_element, "chord")

        notation = INSTRUMENT_MAPPING[note.instrument]
        unpitched = ET.SubElement(note_element, "unpitched")
        ET.SubElement(unpitched, "display-step").text = notation.display_step
        ET.SubElement(unpitched, "display-octave").text = str(
            notation.display_octave
        )
        ET.SubElement(note_element, "duration").text = str(
            _to_divisions(note.duration, divisions)
        )
        ET.SubElement(
            note_element,
            "instrument",
            id=_instrument_id(part_index, note.instrument),
        )
        ET.SubElement(note_element, "voice").text = "1"
        notehead_attributes = {"parentheses": "yes"} if note.ghost else {}
        ET.SubElement(
            note_element,
            "notehead",
            notehead_attributes,
        ).text = notation.notehead

        if note.accent:
            notations = ET.SubElement(note_element, "notations")
            articulations = ET.SubElement(notations, "articulations")
            ET.SubElement(articulations, "accent")

    @staticmethod
    def _append_rest(
        measure_element: ET.Element, rest: Rest, divisions: int
    ) -> None:
        note_element = ET.SubElement(measure_element, "note")
        ET.SubElement(note_element, "rest")
        ET.SubElement(note_element, "duration").text = str(
            _to_divisions(rest.duration, divisions)
        )
        ET.SubElement(note_element, "voice").text = "1"

    @staticmethod
    def _append_forward(measure_element: ET.Element, duration: int) -> None:
        forward = ET.SubElement(measure_element, "forward")
        ET.SubElement(forward, "duration").text = str(duration)
        ET.SubElement(forward, "voice").text = "1"


def _part_id(part_index: int) -> str:
    return f"P{part_index}"


def _instrument_id(part_index: int, instrument: DrumInstrument) -> str:
    instrument_index = tuple(DrumInstrument).index(instrument) + 1
    return f"P{part_index}-I{instrument_index}"


def _used_instruments(part: Part) -> tuple[DrumInstrument, ...]:
    used = {
        event.instrument
        for measure in part.measures
        for event in measure.events
        if isinstance(event, Note)
    }
    return tuple(instrument for instrument in DrumInstrument if instrument in used)


def _measure_divisions(measure: Measure) -> int:
    values = [
        measure.duration,
        *(event.offset for event in measure.events),
        *(event.duration for event in measure.events),
    ]
    divisions = math.lcm(*(value.denominator for value in values))
    if divisions > _MAX_DIVISIONS:
        message = (
            f"measure {measure.number} requires {divisions} divisions "
            "per quarter note; "
            f"maximum supported is {_MAX_DIVISIONS}"
        )
        raise MusicXMLExportError(message)
    return divisions


def _to_divisions(value: Fraction, divisions: int) -> int:
    converted = value * divisions
    if converted.denominator != 1:
        raise MusicXMLExportError("duration cannot be represented exactly")
    return converted.numerator
