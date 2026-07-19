"""Tests for optional count-in generation and exporter integration."""

import xml.etree.ElementTree as ET
from dataclasses import FrozenInstanceError
from fractions import Fraction
from io import BytesIO
from typing import Any

import mido
import pytest

from drum_score_converter.count_in_generator import (
    COUNT_IN_BEATS,
    COUNT_IN_NOTE,
    COUNT_IN_VELOCITY,
    CountInConfig,
    CountInError,
    CountInGenerator,
)
from drum_score_converter.midi_exporter import (
    DRUM_CHANNEL,
    GM_PERCUSSION_MAPPING,
    MIDIExporter,
)
from drum_score_converter.musicxml_exporter import MusicXMLExporter
from drum_score_converter.score_model import (
    DEFAULT_TEMPO_BPM,
    DrumInstrument,
    Measure,
    Note,
    Part,
    Score,
    Tempo,
    TimeSignature,
)


def _score(*, initial_tempo: Tempo | None = Tempo(90)) -> Score:
    first = Measure(
        1,
        TimeSignature(3, 4),
        (Note(DrumInstrument.KICK, Fraction(0), Fraction(1), velocity=110),),
        initial_tempo,
    )
    second = Measure(
        2,
        TimeSignature(4, 4),
        (Note(DrumInstrument.SNARE, Fraction(0), Fraction(1), velocity=90),),
        Tempo(120),
    )
    return Score((Part("Drum Kit", (first, second)),), title="Count-in Test")


def _read_midi(data: bytes) -> mido.MidiFile:
    return mido.MidiFile(file=BytesIO(data), charset="utf8")


def _absolute_messages(track: mido.MidiTrack) -> list[tuple[int, mido.Message]]:
    absolute_tick = 0
    messages: list[tuple[int, mido.Message]] = []
    for message in track:
        absolute_tick += message.time
        messages.append((absolute_tick, message))
    return messages


def test_disabled_count_in_returns_original_and_preserves_export_output() -> None:
    score = _score()
    generator = CountInGenerator()

    result = generator.apply(score)

    assert result is score
    assert MusicXMLExporter().to_string(result) == MusicXMLExporter().to_string(score)
    assert MIDIExporter().to_bytes(result) == MIDIExporter().to_bytes(score)


def test_enabled_count_in_is_non_destructive_and_prepends_one_measure() -> None:
    score = _score()
    original_measures = score.parts[0].measures

    result = CountInGenerator(CountInConfig(enabled=True)).apply(score)

    assert result is not score
    assert score.parts[0].measures is original_measures
    assert tuple(measure.number for measure in score.parts[0].measures) == (1, 2)
    assert tuple(measure.number for measure in result.parts[0].measures) == (1, 2, 3)
    assert len(result.parts[0].measures) == len(original_measures) + 1
    assert result.parts[0].measures[1].events == original_measures[0].events
    assert result.parts[0].measures[2].tempo == original_measures[1].tempo


def test_count_in_contains_four_side_sticks_at_quarter_note_offsets() -> None:
    result = CountInGenerator(CountInConfig(enabled=True)).apply(_score())
    measure = result.parts[0].measures[0]
    notes = tuple(event for event in measure.events if isinstance(event, Note))

    assert COUNT_IN_BEATS == 4
    assert measure.time_signature == TimeSignature(4, 4)
    assert measure.duration == Fraction(4)
    assert len(notes) == 4
    assert tuple(note.offset for note in notes) == tuple(
        Fraction(beat) for beat in range(4)
    )
    assert all(note.instrument is DrumInstrument.SIDE_STICK for note in notes)
    assert all(note.duration == Fraction(1) for note in notes)
    assert all(note.velocity == COUNT_IN_VELOCITY for note in notes)
    assert GM_PERCUSSION_MAPPING[DrumInstrument.SIDE_STICK] == COUNT_IN_NOTE == 37


def test_count_in_uses_initial_tempo_or_existing_default() -> None:
    generator = CountInGenerator(CountInConfig(enabled=True))

    explicit = generator.apply(_score(initial_tempo=Tempo(87)))
    defaulted = generator.apply(_score(initial_tempo=None))

    assert explicit.parts[0].measures[0].tempo == Tempo(87)
    assert defaulted.parts[0].measures[0].tempo == Tempo(DEFAULT_TEMPO_BPM)
    default_midi = _read_midi(MIDIExporter().to_bytes(defaulted))
    default_tempos = [
        message.tempo
        for message in default_midi.tracks[0]
        if message.type == "set_tempo"
    ]
    assert default_tempos[0] == 500_000


def test_only_first_part_contains_count_notes() -> None:
    score = _score()
    second_part = Part("Second Kit", score.parts[0].measures)
    multi_part_score = Score((score.parts[0], second_part), title=score.title)

    result = CountInGenerator(CountInConfig(enabled=True)).apply(multi_part_score)

    assert len(result.parts[0].measures[0].events) == 4
    assert result.parts[1].measures[0].events == ()
    assert result.parts[0].measures[0].tempo == result.parts[1].measures[0].tempo


def test_conflicting_initial_tempos_are_rejected() -> None:
    score = _score()
    conflicting = Part(
        "Second Kit",
        (
            Measure(1, TimeSignature(3, 4), tempo=Tempo(100)),
            score.parts[0].measures[1],
        ),
    )

    with pytest.raises(CountInError, match="conflicting initial tempos"):
        CountInGenerator(CountInConfig(enabled=True)).apply(
            Score((score.parts[0], conflicting))
        )


def test_musicxml_contains_parseable_count_in_before_original_music() -> None:
    result = CountInGenerator(CountInConfig(enabled=True)).apply(_score())

    root = ET.fromstring(MusicXMLExporter().to_string(result))
    measures = root.findall("part/measure")
    count_notes = measures[0].findall("note")
    instrument_names = {
        instrument.get("id"): instrument.findtext("instrument-name")
        for instrument in root.findall("part-list/score-part/score-instrument")
    }
    count_instrument_ids = {
        instrument.get("id")
        for instrument in measures[0].findall("note/instrument")
    }

    assert tuple(measure.get("number") for measure in measures) == ("1", "2", "3")
    assert measures[0].findtext("attributes/time/beats") == "4"
    assert measures[0].findtext("attributes/time/beat-type") == "4"
    assert measures[0].findtext(
        "direction/direction-type/metronome/per-minute"
    ) == "90"
    assert len(count_notes) == 4
    assert all(note.find("instrument") is not None for note in count_notes)
    assert {instrument_names[id_] for id_ in count_instrument_ids} == {"Side Stick"}
    assert measures[1].findtext("attributes/time/beats") == "3"
    assert measures[1].findtext("attributes/time/beat-type") == "4"


def test_midi_shifts_music_and_preserves_tempo_and_signature_changes() -> None:
    result = CountInGenerator(CountInConfig(enabled=True)).apply(_score())
    midi = _read_midi(MIDIExporter().to_bytes(result))

    conductor = _absolute_messages(midi.tracks[0])
    signatures = [
        (tick, message.numerator, message.denominator)
        for tick, message in conductor
        if message.type == "time_signature"
    ]
    tempos = [
        (tick, message.tempo)
        for tick, message in conductor
        if message.type == "set_tempo"
    ]
    part_messages = _absolute_messages(midi.tracks[1])
    note_ons = [
        (tick, message.note, message.channel)
        for tick, message in part_messages
        if message.type == "note_on"
    ]
    side_stick_offs = [
        tick
        for tick, message in part_messages
        if message.type == "note_off" and message.note == COUNT_IN_NOTE
    ]

    assert signatures == [(0, 4, 4), (1_920, 3, 4), (3_360, 4, 4)]
    assert tempos == [(0, 666_667), (3_360, 500_000)]
    assert note_ons[:4] == [
        (0, COUNT_IN_NOTE, DRUM_CHANNEL),
        (480, COUNT_IN_NOTE, DRUM_CHANNEL),
        (960, COUNT_IN_NOTE, DRUM_CHANNEL),
        (1_440, COUNT_IN_NOTE, DRUM_CHANNEL),
    ]
    assert side_stick_offs == [480, 960, 1_440, 1_920]
    assert note_ons[4:] == [
        (1_920, GM_PERCUSSION_MAPPING[DrumInstrument.KICK], DRUM_CHANNEL),
        (3_360, GM_PERCUSSION_MAPPING[DrumInstrument.SNARE], DRUM_CHANNEL),
    ]


def test_count_in_config_is_immutable_and_validates_enabled() -> None:
    config = CountInConfig(enabled=True)

    with pytest.raises(FrozenInstanceError):
        setattr(config, "enabled", False)

    invalid: Any = 1
    with pytest.raises(TypeError, match="boolean"):
        CountInConfig(enabled=invalid)
