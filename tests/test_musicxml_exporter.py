"""Tests for MusicXML export."""

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

from drum_score_converter.musicxml_exporter import (
    INSTRUMENT_MAPPING,
    MusicXMLExporter,
    MusicXMLExportError,
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


def _example_score() -> Score:
    events = (
        Note(DrumInstrument.KICK, Fraction(0), Fraction(1), accent=True),
        Note(DrumInstrument.CLOSED_HI_HAT, Fraction(0), Fraction(1)),
        Rest(Fraction(1), Fraction(1)),
        Note(DrumInstrument.SNARE, Fraction(3), Fraction(1), ghost=True),
    )
    measure = Measure(1, TimeSignature(4, 4), events, Tempo(120))
    return Score((Part("Drums & Percussion", (measure,)),), title="練習曲")


def test_to_string_creates_parseable_partwise_musicxml() -> None:
    xml = MusicXMLExporter().to_string(_example_score())
    root = ET.fromstring(xml)

    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert root.tag == "score-partwise"
    assert root.get("version") == "4.0"
    assert root.findtext("movement-title") == "練習曲"
    assert root.findtext("part-list/score-part/part-name") == "Drums & Percussion"
    assert root.find("part-list/score-part").get("id") == "P1"
    assert root.find("part").get("id") == "P1"


def test_exporter_outputs_measure_attributes_tempo_and_timing() -> None:
    root = ET.fromstring(MusicXMLExporter().to_string(_example_score()))
    measure = root.find("part/measure")

    assert measure.get("number") == "1"
    assert measure.findtext("attributes/divisions") == "1"
    assert measure.findtext("attributes/time/beats") == "4"
    assert measure.findtext("attributes/time/beat-type") == "4"
    assert measure.findtext("attributes/clef/sign") == "percussion"
    assert measure.findtext("direction/direction-type/metronome/per-minute") == "120"
    assert measure.find("direction/sound").get("tempo") == "120"
    assert measure.findtext("forward/duration") == "1"


def test_same_offset_notes_are_encoded_as_a_chord() -> None:
    root = ET.fromstring(MusicXMLExporter().to_string(_example_score()))
    notes = root.findall("part/measure/note")

    assert notes[0].find("chord") is None
    assert notes[1].find("chord") is not None
    assert notes[0].findtext("duration") == "1"
    assert notes[1].findtext("duration") == "1"
    assert notes[0].find("notations/articulations/accent") is not None
    assert notes[3].find("notehead").get("parentheses") == "yes"


def test_notes_reference_explicit_percussion_instruments() -> None:
    root = ET.fromstring(MusicXMLExporter().to_string(_example_score()))
    score_instruments = root.findall("part-list/score-part/score-instrument")
    definitions = {
        element.get("id"): element.findtext("instrument-name")
        for element in score_instruments
    }
    references = {
        element.get("id")
        for element in root.findall("part/measure/note/instrument")
    }

    assert set(INSTRUMENT_MAPPING) == set(DrumInstrument)
    assert references <= definitions.keys()
    assert set(definitions.values()) == {"Kick Drum", "Snare Drum", "Closed Hi-Hat"}
    assert root.findtext("part/measure/note/unpitched/display-step") == "F"


def test_rest_is_encoded_as_a_musicxml_rest() -> None:
    root = ET.fromstring(MusicXMLExporter().to_string(_example_score()))
    rest_note = root.findall("part/measure/note")[2]

    assert rest_note.find("rest") is not None
    assert rest_note.findtext("duration") == "1"
    assert rest_note.find("instrument") is None


def test_write_saves_utf8_musicxml(tmp_path: Path) -> None:
    path = tmp_path / "練習曲.musicxml"
    MusicXMLExporter().write(_example_score(), path)

    data = path.read_bytes()
    assert "練習曲" in data.decode("utf-8")
    assert data == MusicXMLExporter().to_string(_example_score()).encode("utf-8")


def test_exporter_rejects_overlapping_event_groups() -> None:
    measure = Measure(
        1,
        TimeSignature(4, 4),
        (
            Note(DrumInstrument.KICK, Fraction(0), Fraction(2)),
            Note(DrumInstrument.SNARE, Fraction(1), Fraction(1)),
        ),
    )

    with pytest.raises(MusicXMLExportError, match="overlapping"):
        MusicXMLExporter().to_string(Score((Part("Drums", (measure,)),)))


def test_exporter_rejects_note_and_rest_at_the_same_offset() -> None:
    measure = Measure(
        1,
        TimeSignature(4, 4),
        (
            Note(DrumInstrument.KICK, Fraction(0), Fraction(1)),
            Rest(Fraction(0), Fraction(1)),
        ),
    )

    with pytest.raises(MusicXMLExportError, match="mixes notes and rests"):
        MusicXMLExporter().to_string(Score((Part("Drums", (measure,)),)))


def test_exporter_rejects_excessive_divisions() -> None:
    note = Note(
        DrumInstrument.KICK,
        Fraction(0),
        Fraction(1, 16_384),
    )
    measure = Measure(1, TimeSignature(4, 4), (note,))

    with pytest.raises(MusicXMLExportError, match="maximum supported"):
        MusicXMLExporter().to_string(Score((Part("Drums", (measure,)),)))
