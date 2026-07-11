# Drum Score Converter

ドラム譜PDFを画像認識し、MusicXMLおよびMIDIへ変換するPythonライブラリです。

## Status

現在開発中です。

## Planned Features

- 通常PDFおよびパスワード付きPDFの読み込み
- PDFページの画像化
- Vision AIによるドラム譜認識
- MusicXML出力
- Standard MIDI File出力
- Cubase / EZdrummer 3で利用可能なMIDI生成

## Pipeline

PDF
→ Page Images
→ Vision Recognition
→ MusicXML
→ MIDI
→ Cubase / EZdrummer 3

## Requirements

- Python 3.12以上

## Documentation

詳細な仕様と実装方針は
[CODEX_INSTRUCTIONS.md](./CODEX_INSTRUCTIONS.md)
を参照してください。

## License

未定