"""Unit tests for the Sheet2DrumMidi command-line interface."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

import sheet2drummidi.cli as cli
from drum_score_converter.recognition_pipeline import (
    RecognitionPipeline,
    RecognitionPipelineError,
)
from drum_score_converter.score_model import (
    DrumInstrument,
    Measure,
    Note,
    Part,
    Score,
    TimeSignature,
)


def _score() -> Score:
    note = Note(
        DrumInstrument.SNARE,
        Fraction(0),
        Fraction(1),
    )
    measure = Measure(1, TimeSignature(4, 4), (note,))
    return Score((Part("Drums", (measure,)),), title="CLI Test")


def _without_environment_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_main_parses_supported_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[cli._CLIArguments, str]] = []
    input_path = tmp_path / "score.pdf"
    midi_path = tmp_path / "midi" / "score.mid"
    musicxml_path = tmp_path / "xml" / "score.musicxml"

    async def capture_conversion(
        arguments: cli._CLIArguments,
        api_key: str,
    ) -> None:
        captured.append((arguments, api_key))

    monkeypatch.setattr(cli, "_convert", capture_conversion)

    result = cli.main(
        [
            str(input_path),
            "--output",
            str(midi_path),
            "--musicxml",
            str(musicxml_path),
            "--password",
            "pdf-secret",
            "--api-key",
            "command-line-key",
        ]
    )

    assert result == 0
    assert captured == [
        (
            cli._CLIArguments(
                input_path,
                midi_path,
                musicxml_path,
                "pdf-secret",
                "command-line-key",
            ),
            "command-line-key",
        )
    ]


def test_output_defaults_to_input_path_with_mid_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[cli._CLIArguments] = []
    input_path = tmp_path / "score.pdf"

    async def capture_conversion(
        arguments: cli._CLIArguments,
        api_key: str,
    ) -> None:
        captured.append(arguments)

    monkeypatch.setattr(cli, "_convert", capture_conversion)

    assert cli.main([str(input_path), "--api-key", "key"]) == 0
    assert captured[0].output_path == tmp_path / "score.mid"
    assert captured[0].musicxml_path is None


def test_command_line_api_key_has_highest_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")

    assert cli._resolve_api_key("command-line-key") == "command-line-key"


def test_environment_api_key_has_priority_over_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")

    assert cli._resolve_api_key(None) == "environment-key"


def test_api_key_is_loaded_from_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _without_environment_key(monkeypatch)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")

    assert cli._resolve_api_key(None) == "dotenv-key"


def test_missing_api_key_returns_clear_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _without_environment_key(monkeypatch)

    result = cli.main(["score.pdf"])

    assert result == 2
    error = capsys.readouterr().err
    assert "OpenAI API key not found." in error
    assert "--api-key" in error
    assert "OPENAI_API_KEY" in error
    assert ".env" in error


def test_conversion_creates_output_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "arbitrary" / "score.pdf"
    midi_path = tmp_path / "new" / "midi" / "score.mid"
    musicxml_path = tmp_path / "new" / "xml" / "score.musicxml"
    arguments = cli._CLIArguments(
        input_path,
        midi_path,
        musicxml_path,
        "pdf-secret",
        None,
    )

    async def fake_process(
        pipeline: RecognitionPipeline,
        pdf_path: str | Path,
        *,
        password: str | None = None,
    ) -> Score:
        assert Path(pdf_path) == input_path
        assert password == "pdf-secret"
        return _score()

    monkeypatch.setattr(RecognitionPipeline, "process", fake_process)

    asyncio.run(cli._convert(arguments, "api-key"))

    assert midi_path.read_bytes().startswith(b"MThd")
    assert musicxml_path.read_text(encoding="utf-8").startswith("<?xml")


def test_pipeline_error_is_reported_with_stage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail_conversion(
        arguments: cli._CLIArguments,
        api_key: str,
    ) -> None:
        raise RecognitionPipelineError(
            "Recognition failed.",
            stage="recognition",
            page_number=2,
        )

    monkeypatch.setattr(cli, "_convert", fail_conversion)

    result = cli.main(["score.pdf", "--api-key", "key"])

    assert result == 1
    error = capsys.readouterr().err
    assert "recognition" in error
    assert "page 2" in error
    assert "Recognition failed." in error


def test_package_can_be_executed_as_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sheet2drummidi", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert result.returncode == 0
    assert "INPUT.pdf" in result.stdout
