"""Standard MIDI File export for the drum score domain model."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

import mido

from drum_score_converter.count_in_generator import COUNT_IN_NOTE
from drum_score_converter.score_model import (
    DEFAULT_TEMPO_BPM,
    DrumInstrument,
    Note,
    Part,
    Score,
    Tempo,
    TimeSignature,
)

DRUM_CHANNEL: Final = 9
BASE_TICKS_PER_QUARTER: Final = 480
_MAX_TICKS_PER_QUARTER: Final = 0x7FFF
_MAX_MIDI_TEMPO: Final = 0xFFFFFF

GM_PERCUSSION_MAPPING: Final[Mapping[DrumInstrument, int]] = MappingProxyType(
    {
        DrumInstrument.KICK: 36,
        DrumInstrument.SIDE_STICK: COUNT_IN_NOTE,
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
)


class MIDIExportError(ValueError):
    """Raised when a valid domain score cannot be represented as MIDI."""


@dataclass(frozen=True, slots=True)
class _NoteEvent:
    tick: int
    priority: int
    order: int
    kind: Literal["note_on", "note_off"]
    note_number: int
    velocity: int


class MIDIExporter:
    """Convert a Score into a synchronous Standard MIDI File (SMF Type 1)."""

    def to_bytes(self, score: Score) -> bytes:
        """Return the complete Standard MIDI File as bytes."""
        if not isinstance(score, Score):
            raise TypeError("score must be a Score")

        _validate_part_layout(score)
        ticks_per_quarter = _ticks_per_quarter(score)
        midi = mido.MidiFile(
            type=1,
            ticks_per_beat=ticks_per_quarter,
            charset="utf8",
        )
        self._append_conductor_track(midi, score, ticks_per_quarter)
        for part in score.parts:
            self._append_part_track(midi, part, ticks_per_quarter)

        output = BytesIO()
        midi.save(file=output)
        return output.getvalue()

    def write(self, score: Score, path: str | Path) -> None:
        """Write a Standard MIDI File to path."""
        Path(path).write_bytes(self.to_bytes(score))

    @staticmethod
    def _append_conductor_track(
        midi: mido.MidiFile, score: Score, ticks_per_quarter: int
    ) -> None:
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(
            mido.MetaMessage(
                "track_name",
                name=score.title or "Conductor",
                time=0,
            )
        )

        reference_part = score.parts[0]
        measure_starts = _measure_starts(reference_part)
        last_tick = 0
        previous_signature: TimeSignature | None = None
        previous_tempo: float | None = None

        for measure_index, (measure, start) in enumerate(
            zip(reference_part.measures, measure_starts)
        ):
            tick = _to_ticks(start, ticks_per_quarter)
            signature = measure.time_signature
            if signature != previous_signature:
                _validate_time_signature(signature, measure.number)
                track.append(
                    mido.MetaMessage(
                        "time_signature",
                        numerator=signature.numerator,
                        denominator=signature.denominator,
                        time=tick - last_tick,
                    )
                )
                last_tick = tick
                previous_signature = signature

            tempo = _tempo_for_measure(score, measure_index)
            if measure_index == 0 and tempo is None:
                tempo = Tempo(DEFAULT_TEMPO_BPM)
            if tempo is not None and tempo.bpm != previous_tempo:
                track.append(
                    mido.MetaMessage(
                        "set_tempo",
                        tempo=_tempo_to_microseconds(tempo, measure.number),
                        time=tick - last_tick,
                    )
                )
                last_tick = tick
                previous_tempo = tempo.bpm

        total_ticks = _to_ticks(_part_duration(reference_part), ticks_per_quarter)
        track.append(mido.MetaMessage("end_of_track", time=total_ticks - last_tick))

    @staticmethod
    def _append_part_track(
        midi: mido.MidiFile, part: Part, ticks_per_quarter: int
    ) -> None:
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name=part.name, time=0))
        track.append(mido.MetaMessage("instrument_name", name="Drum Kit", time=0))

        events = _part_note_events(part, ticks_per_quarter)
        last_tick = 0
        for event in events:
            track.append(
                mido.Message(
                    event.kind,
                    channel=DRUM_CHANNEL,
                    note=event.note_number,
                    velocity=event.velocity,
                    time=event.tick - last_tick,
                )
            )
            last_tick = event.tick

        total_ticks = _to_ticks(_part_duration(part), ticks_per_quarter)
        track.append(mido.MetaMessage("end_of_track", time=total_ticks - last_tick))


def _part_note_events(part: Part, ticks_per_quarter: int) -> list[_NoteEvent]:
    events: list[_NoteEvent] = []
    measure_start = Fraction(0)
    order = 0
    for measure in part.measures:
        for event in measure.events:
            if not isinstance(event, Note):
                continue
            start_tick = _to_ticks(
                measure_start + event.offset,
                ticks_per_quarter,
            )
            end_tick = _to_ticks(
                measure_start + event.offset + event.duration,
                ticks_per_quarter,
            )
            note_number = GM_PERCUSSION_MAPPING[event.instrument]
            events.append(
                _NoteEvent(
                    start_tick,
                    1,
                    order,
                    "note_on",
                    note_number,
                    event.velocity,
                )
            )
            events.append(
                _NoteEvent(end_tick, 0, order, "note_off", note_number, 0)
            )
            order += 1
        measure_start += measure.duration

    events.sort(key=lambda event: (event.tick, event.priority, event.order))
    return events


def _ticks_per_quarter(score: Score) -> int:
    denominators = [BASE_TICKS_PER_QUARTER]
    for part in score.parts:
        for measure in part.measures:
            denominators.append(measure.duration.denominator)
            for event in measure.events:
                denominators.extend(
                    (event.offset.denominator, event.duration.denominator)
                )

    ticks_per_quarter = math.lcm(*denominators)
    if ticks_per_quarter > _MAX_TICKS_PER_QUARTER:
        raise MIDIExportError(
            f"score requires {ticks_per_quarter} ticks per quarter note; "
            f"maximum supported is {_MAX_TICKS_PER_QUARTER}"
        )
    return ticks_per_quarter


def _to_ticks(value: Fraction, ticks_per_quarter: int) -> int:
    converted = value * ticks_per_quarter
    if converted.denominator != 1:
        raise MIDIExportError("musical position cannot be represented exactly in ticks")
    return converted.numerator


def _measure_starts(part: Part) -> tuple[Fraction, ...]:
    starts: list[Fraction] = []
    position = Fraction(0)
    for measure in part.measures:
        starts.append(position)
        position += measure.duration
    return tuple(starts)


def _part_duration(part: Part) -> Fraction:
    return sum((measure.duration for measure in part.measures), start=Fraction(0))


def _tempo_for_measure(score: Score, measure_index: int) -> Tempo | None:
    tempos: set[float] = set()
    for part in score.parts:
        tempo = part.measures[measure_index].tempo
        if tempo is not None:
            tempos.add(tempo.bpm)
    if len(tempos) > 1:
        measure_number = score.parts[0].measures[measure_index].number
        raise MIDIExportError(f"measure {measure_number} has conflicting tempos")
    if not tempos:
        return None
    return Tempo(tempos.pop())


def _validate_part_layout(score: Score) -> None:
    reference = score.parts[0].measures
    for part in score.parts[1:]:
        if len(part.measures) != len(reference):
            raise MIDIExportError("all parts must contain the same number of measures")
        for expected, actual in zip(reference, part.measures):
            if actual.number != expected.number:
                raise MIDIExportError("measure numbers must match across all parts")
            if actual.time_signature != expected.time_signature:
                raise MIDIExportError(
                    f"measure {expected.number} has conflicting time signatures"
                )

    for measure_index in range(len(reference)):
        _tempo_for_measure(score, measure_index)


def _validate_time_signature(signature: TimeSignature, measure_number: int) -> None:
    if signature.numerator > 0xFF:
        raise MIDIExportError(
            f"measure {measure_number} time-signature numerator exceeds 255"
        )
    denominator_power = signature.denominator.bit_length() - 1
    if denominator_power > 0xFF:
        raise MIDIExportError(
            f"measure {measure_number} time-signature denominator is too large"
        )


def _tempo_to_microseconds(tempo: Tempo, measure_number: int) -> int:
    microseconds = round(60_000_000 / tempo.bpm)
    if not 1 <= microseconds <= _MAX_MIDI_TEMPO:
        raise MIDIExportError(f"measure {measure_number} tempo is outside MIDI range")
    return microseconds
