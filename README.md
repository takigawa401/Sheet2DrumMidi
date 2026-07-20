# Drum Score Converter

ドラム譜PDFを画像認識し、MusicXMLおよびMIDIへ変換するPythonライブラリです。

## Project Status

🚧 Under active development

### Completed
- ✅ Project initialization
- ✅ Score domain model
- ✅ MusicXML export

### Planned
- MIDI export
- PDF loading
- Page rendering
- OCR

## Features

### Implemented
- ✅ MusicXML export

### Planned
- PDF loading
- Page rendering
- Vision AI recognition
- MIDI export

## Pipeline

PDF
 ↓
Page Images
 ↓
Vision Recognition
 ↓
Score Domain Model
 ├── MusicXML
 └── MIDI
        ↓
Cubase / EZdrummer 3

## Requirements

- Python 3.12以上

## Command-Line Usage

Install the project into its virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

Convert a PDF to MIDI and optionally MusicXML:

```powershell
sheet2drummidi input\score.pdf `
    --output output\score.mid `
    --musicxml output\score.musicxml
```

The module entry point provides the same command. When `--output` is omitted,
the MIDI file is written next to the input PDF with a `.mid` suffix.

```powershell
.\.venv\Scripts\python.exe -m sheet2drummidi input\score.pdf
```

Password-protected PDFs and an explicit API key are supported:

```powershell
sheet2drummidi D:\scores\score.pdf `
    --output D:\converted\score.mid `
    --password "pdf-password" `
    --api-key "OpenAI-api-key"
```

The OpenAI API key is resolved in this order:

1. `--api-key`
2. `OPENAI_API_KEY`
3. `OPENAI_API_KEY` in `.env` in the current directory

For example, `.env` may contain:

```dotenv
OPENAI_API_KEY=your-api-key
```

Output directories are created automatically. The recognition pipeline
processes PDF pages sequentially and merges page-level scores in
page order. It does not renumber, reorder, deduplicate, or repair measures.

## Documentation

詳細な仕様と実装方針は
[CODEX_INSTRUCTIONS.md](./CODEX_INSTRUCTIONS.md)
を参照してください。


- [Recognition Pipeline](docs/architecture/recognition_pipeline.md)

## Tests

Install the development dependencies and run the complete test suite with the
project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The deterministic PDF-to-MusicXML/MIDI integration tests can be run on their
own:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recognition_pipeline_integration.py
```

These tests use the project-owned PDF under `tests/fixtures` and a fake
`VisionRecognizer`. They require no API key or network access, and write
generated MusicXML and MIDI artifacts only to pytest temporary directories.

## License

MIT License
