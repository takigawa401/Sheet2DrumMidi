"""Tests for Standard MIDI File export."""

from fractions import Fraction
from io import BytesIO
from pathlib import Path

import mido
import pytest

from drum_score_converter.midi_exporter import (
    DRUM_CHANNEL,
    GM_PERCUSSION_MAPPING,
    MIDIExporter,
    MIDIExportError,
)
from drum_score_converter.score_model import (
    DrumInstrument,
    Measure,
    Note,
    Part,
    Score,
    Tempo,
    TimeSignature,
)


def _example_score() -> Score:
    measure = Measure(
        1,
        TimeSignature(4, 4),
        (
            Note(
                DrumInstrument.KICK,
                Fraction(0),
                Fraction(1),
                velocity=110,
            ),
            Note(
                DrumInstrument.CLOSED_HI_HAT,
                Fraction(0),
                Fraction(1, 2),
                velocity=90,
            ),
            Note(
                DrumInstrument.SNARE,
                Fraction(1),
                Fraction(1, 2),
                velocity=77,
            ),
        ),
        Tempo(120),
    )
    return Score((Part("Drum Kit", (measure,)),), title="Example")


def _read_midi(data: bytes) -> mido.MidiFile:
    return mido.MidiFile(file=BytesIO(data), charset="utf8")


def test_to_bytes_creates_parseable_type_one_midi() -> None:
    data = MIDIExporter().to_bytes(_example_score())
    midi = _read_midi(data)

    assert data.startswith(b"MThd")
    assert midi.type == 1
    assert midi.ticks_per_beat == 480
    assert len(midi.tracks) == 2
    assert midi.tracks[0].name == "Example"
    assert midi.tracks[1].name == "Drum Kit"


def test_conductor_track_contains_tempo_and_time_signature() -> None:
    midi = _read_midi(MIDIExporter().to_bytes(_example_score()))
    conductor = midi.tracks[0]
    tempo_messages = [message for message in conductor if message.type == "set_tempo"]
    signature_messages = [
        message for message in conductor if message.type == "time_signature"
    ]

    assert len(tempo_messages) == 1
    assert tempo_messages[0].tempo == 500_000
    assert tempo_messages[0].time == 0
    assert len(signature_messages) == 1
    assert signature_messages[0].numerator == 4
    assert signature_messages[0].denominator == 4
    assert signature_messages[0].time == 0


def test_note_events_use_drum_channel_mapping_velocity_and_duration() -> None:
    midi = _read_midi(MIDIExporter().to_bytes(_example_score()))
    absolute_tick = 0
    events: list[tuple[int, str, int, int, int]] = []
    for message in midi.tracks[1]:
        absolute_tick += message.time
        if message.type in {"note_on", "note_off"}:
            events.append(
                (
                    absolute_tick,
                    message.type,
                    message.note,
                    message.velocity,
                    message.channel,
                )
            )

    assert events == [
        (0, "note_on", 36, 110, DRUM_CHANNEL),
        (0, "note_on", 42, 90, DRUM_CHANNEL),
        (240, "note_off", 42, 0, DRUM_CHANNEL),
        (480, "note_off", 36, 0, DRUM_CHANNEL),
        (480, "note_on", 38, 77, DRUM_CHANNEL),
        (720, "note_off", 38, 0, DRUM_CHANNEL),
    ]


def test_gm_percussion_mapping_is_explicit_and_complete() -> None:
    assert dict(GM_PERCUSSION_MAPPING) == {
        DrumInstrument.KICK: 36,
        DrumInstrument.SNARE: 38,
        DrumInstrument.CLOSED_HI_HAT: 42,
        DrumInstrument.PEDAL_HI_HAT: 44,
        DrumInstrument.OPEN_HI_HAT: 46,
        DrumInstrument.CRASH: 49,
        DrumInstrument.HIGH_TOM: 50,
        DrumInstrument.RIDE: 51,
        DrumInstrument.MID_TOM: 47,
        DrumInstrument.FLOOR_TOM: 43,
    }


def test_fractional_timing_increases_resolution_for_exact_ticks() -> None:
    measure = Measure(
        1,
        TimeSignature(4, 4),
        (
            Note(
                DrumInstrument.KICK,
                Fraction(1, 7),
                Fraction(1, 7),
            ),
        ),
    )
    score = Score((Part("Drum Kit", (measure,)),))
    midi = _read_midi(MIDIExporter().to_bytes(score))

    assert midi.ticks_per_beat == 3_360
    note_messages = [
        message
        for message in midi.tracks[1]
        if message.type in {"note_on", "note_off"}
    ]
    assert note_messages[0].time == 480
    assert note_messages[1].time == 480


def test_write_saves_the_generated_bytes(tmp_path: Path) -> None:
    path = tmp_path / "example.mid"
    MIDIExporter().write(_example_score(), path)

    assert path.read_bytes() == MIDIExporter().to_bytes(_example_score())
    assert _read_midi(path.read_bytes()).type == 1


def test_exporter_emits_changes_at_measure_boundaries() -> None:
    first = Measure(1, TimeSignature(4, 4), tempo=Tempo(120))
    second = Measure(2, TimeSignature(3, 4), tempo=Tempo(90))
    score = Score((Part("Drum Kit", (first, second)),))
    midi = _read_midi(MIDIExporter().to_bytes(score))

    absolute_tick = 0
    changes: list[tuple[int, str]] = []
    for message in midi.tracks[0]:
        absolute_tick += message.time
        if message.type in {"set_tempo", "time_signature"}:
            changes.append((absolute_tick, message.type))

    assert changes == [
        (0, "time_signature"),
        (0, "set_tempo"),
        (1_920, "time_signature"),
        (1_920, "set_tempo"),
    ]


def test_exporter_rejects_conflicting_part_layouts() -> None:
    first_part = Part("Drums 1", (Measure(1, TimeSignature(4, 4)),))
    second_part = Part("Drums 2", (Measure(1, TimeSignature(3, 4)),))

    with pytest.raises(MIDIExportError, match="conflicting time signatures"):
        MIDIExporter().to_bytes(Score((first_part, second_part)))


def test_exporter_rejects_resolution_above_midi_limit() -> None:
    note = Note(
        DrumInstrument.KICK,
        Fraction(0),
        Fraction(1, 32_768),
    )
    score = Score(
        (Part("Drum Kit", (Measure(1, TimeSignature(4, 4), (note,)),)),)
    )

    with pytest.raises(MIDIExportError, match="maximum supported"):
        MIDIExporter().to_bytes(score)


def test_exporter_rejects_tempo_outside_midi_range() -> None:
    measure = Measure(1, TimeSignature(4, 4), tempo=Tempo(1))
    score = Score((Part("Drum Kit", (measure,)),))

    with pytest.raises(MIDIExportError, match="outside MIDI range"):
        MIDIExporter().to_bytes(score)
