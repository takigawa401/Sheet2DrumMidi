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

## Documentation

詳細な仕様と実装方針は
[CODEX_INSTRUCTIONS.md](./CODEX_INSTRUCTIONS.md)
を参照してください。


- [Recognition Pipeline](docs/architecture/recognition_pipeline.md)

## License

MIT License