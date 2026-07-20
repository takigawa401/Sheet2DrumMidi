"""Official command-line interface for PDF-to-MIDI conversion."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from drum_score_converter.midi_exporter import MIDIExporter, MIDIExportError
from drum_score_converter.musicxml_exporter import (
    MusicXMLExporter,
    MusicXMLExportError,
)
from drum_score_converter.openai_vision_recognizer import (
    OpenAIConfig,
    OpenAIVisionRecognizer,
)
from drum_score_converter.recognition_pipeline import (
    RecognitionPipeline,
    RecognitionPipelineError,
)
from drum_score_converter.vision_recognizer import RecognitionError

_API_KEY_ERROR = """OpenAI API key not found.

Specify one of:

- --api-key
- OPENAI_API_KEY
- .env"""


@dataclass(frozen=True, slots=True)
class _CLIArguments:
    input_path: Path
    output_path: Path
    musicxml_path: Path | None
    password: str | None
    api_key: str | None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sheet2drummidi",
        description="Convert a drum-score PDF to Standard MIDI File.",
    )
    parser.add_argument("input", type=Path, metavar="INPUT.pdf")
    parser.add_argument("--output", type=Path, help="MIDI output path")
    parser.add_argument("--musicxml", type=Path, help="optional MusicXML output path")
    parser.add_argument("--password", help="PDF password")
    parser.add_argument("--api-key", help="OpenAI API key")
    return parser


def _parse_args(argv: Sequence[str] | None) -> _CLIArguments:
    parser = _build_parser()
    namespace = parser.parse_args(argv)
    input_path: Path = namespace.input
    if input_path.suffix.casefold() != ".pdf":
        parser.error("INPUT must be a PDF file.")
    output_path: Path = namespace.output or input_path.with_suffix(".mid")
    return _CLIArguments(
        input_path=input_path,
        output_path=output_path,
        musicxml_path=namespace.musicxml,
        password=namespace.password,
        api_key=namespace.api_key,
    )


def _resolve_api_key(command_line_key: str | None) -> str | None:
    key = _non_blank(command_line_key)
    if key is not None:
        return key

    key = _non_blank(os.environ.get("OPENAI_API_KEY"))
    if key is not None:
        return key

    values = dotenv_values(Path.cwd() / ".env")
    return _non_blank(values.get("OPENAI_API_KEY"))


def _non_blank(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


async def _convert(arguments: _CLIArguments, api_key: str) -> None:
    recognizer = OpenAIVisionRecognizer(OpenAIConfig(api_key=api_key))
    score = await RecognitionPipeline(recognizer).process(
        arguments.input_path,
        password=arguments.password,
    )

    arguments.output_path.parent.mkdir(parents=True, exist_ok=True)
    MIDIExporter().write(score, arguments.output_path)
    if arguments.musicxml_path is not None:
        arguments.musicxml_path.parent.mkdir(parents=True, exist_ok=True)
        MusicXMLExporter().write(score, arguments.musicxml_path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI using explicit arguments or the process command line."""
    arguments = _parse_args(argv)
    api_key = _resolve_api_key(arguments.api_key)
    if api_key is None:
        print(_API_KEY_ERROR, file=sys.stderr)
        return 2

    try:
        asyncio.run(_convert(arguments, api_key))
    except RecognitionPipelineError as error:
        context = f" on page {error.page_number}" if error.page_number else ""
        print(
            f"Conversion failed during {error.stage}{context}: {error}",
            file=sys.stderr,
        )
        if error.__cause__ is not None:
            print(f"Cause: {error.__cause__}", file=sys.stderr)
        return 1
    except (RecognitionError, MIDIExportError, MusicXMLExportError, OSError) as error:
        print(f"Conversion failed: {error}", file=sys.stderr)
        return 1

    print(f"MIDI written to: {arguments.output_path}")
    if arguments.musicxml_path is not None:
        print(f"MusicXML written to: {arguments.musicxml_path}")
    return 0
