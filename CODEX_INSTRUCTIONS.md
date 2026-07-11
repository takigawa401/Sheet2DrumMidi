# Codex 作業指示書: Drum Score PDF to MusicXML / MIDI Converter

## 1. Project Overview

パスワード付きPDFを含むドラム譜PDFを読み込み、ページ画像化したうえで Vision AI により楽譜情報を認識し、MusicXML および Standard MIDI File を出力する Python ライブラリ / CLI ツールを開発する。

最終的な利用想定は、生成された MIDI を Cubase に読み込み、EZdrummer 3 を音源としてドラム音を再生し、必要に応じて Cubase 側で WAV / MP3 に書き出すことである。

## 2. Goals

* パスワード付きPDFを読み込めること
* PDF各ページを画像化できること
* Vision AI に渡しやすい画像を生成できること
* ドラム譜から以下の情報を認識できること

  * 小節
  * 拍子
  * テンポ
  * 音符
  * 休符
  * キック
  * スネア
  * ハイハット
  * オープンハイハット
  * ペダルハイハット
  * ライド
  * クラッシュ
  * タム
  * アクセント
  * ゴーストノート
  * リピート記号
* 認識結果から MusicXML を出力できること
* 認識結果から MIDI を出力できること
* Cubase + EZdrummer 3 で読み込みやすい MIDI を生成できること
* GitHub公開を前提に、汎用的なライブラリとして設計すること

## 3. Non-Goals

以下は対象外とする。

* Cubase プロジェクトファイル `.cpr` の直接生成
* EZdrummer 3 専用プロジェクトファイルの生成
* Python単体での最終WAV / MP3レンダリング
* 特定の出版社・特定の譜面だけに依存した専用実装
* 独自のドラム専用JSONフォーマットを公開仕様として設計すること

## 4. Target Pipeline

Primary pipeline:

```text
PDF
  ↓
PDF page images
  ↓
Vision AI recognition
  ↓
MusicXML
  ↓
MIDI
```

Final user workflow:

```text
Generated MIDI
  ↓
Cubase
  ↓
EZdrummer 3
  ↓
Audio playback
  ↓
WAV / MP3 export from Cubase
```

## 5. Output Policy

このツールの主要成果物は以下とする。

### Required Outputs

* `.musicxml`
* `.mid`

### Optional Outputs

* ページ画像 `.png`
* 認識ログ `.txt` または `.md`
* デバッグ用の画像認識結果オーバーレイ画像

### Out of Scope Outputs

* `.cpr`
* EZdrummer 3 独自形式
* `.wav`
* `.mp3`

## 6. Recommended Repository Structure

```text
drum-score-converter/
├── README.md
├── CODEX_INSTRUCTIONS.md
├── pyproject.toml
├── src/
│   └── drum_score_converter/
│       ├── __init__.py
│       ├── cli.py
│       ├── pdf_loader.py
│       ├── page_renderer.py
│       ├── image_preprocessor.py
│       ├── vision_client.py
│       ├── score_model.py
│       ├── musicxml_exporter.py
│       ├── midi_exporter.py
│       └── ezdrummer_mapping.py
├── tests/
│   ├── test_pdf_loader.py
│   ├── test_musicxml_exporter.py
│   └── test_midi_exporter.py
└── examples/
    └── README.md
```

## 7. Core Modules

### pdf_loader.py

Responsibilities:

* PDFを開く
* パスワード付きPDFに対応する
* ページ数を取得する
* PDFメタ情報を取得する

候補ライブラリ:

* PyMuPDF / fitz
* pypdf

### page_renderer.py

Responsibilities:

* PDF各ページを画像化する
* 解像度を指定可能にする
* Vision AIに渡しやすいPNGを生成する

CLI例:

```bash
drum-score-converter render input.pdf --password "xxxxx" --out ./pages
```

### image_preprocessor.py

Responsibilities:

* 傾き補正
* コントラスト調整
* 余白除去
* ページ分割補助
* デバッグ用画像出力

候補ライブラリ:

* Pillow
* OpenCV

### vision_client.py

Responsibilities:

* ページ画像をVision AIへ渡す
* 楽譜情報を構造化して取得する
* 認識結果を内部モデルへ変換する

注意:

* Vision AIの応答をそのまま信用しない
* 小節数、拍数、拍子との整合性チェックを行う
* 不確実な箇所は warning として記録する

### score_model.py

Responsibilities:

* 楽譜情報の内部表現を定義する
* ただし、独自JSONフォーマットを公開仕様として固定しない
* MusicXML / MIDI 生成のためのPython内部モデルとして扱う

想定クラス:

```python
Score
Part
Measure
NoteEvent
RestEvent
Tempo
TimeSignature
RepeatMark
DrumInstrument
```

### musicxml_exporter.py

Responsibilities:

* 内部モデルから MusicXML を生成する
* ドラム譜として適切な percussion 表現を使う
* MuseScore / Cubase で開けるMusicXMLを目指す

### midi_exporter.py

Responsibilities:

* 内部モデルから Standard MIDI File を生成する
* SMF Format 1 を基本とする
* テンポ、拍子、ノート、ベロシティを反映する
* Cubaseで読み込みやすい構成にする

候補ライブラリ:

* mido
* pretty_midi

### ezdrummer_mapping.py

Responsibilities:

* 認識されたドラム楽器をMIDIノート番号へ変換する
* General MIDIを基本としつつ、EZdrummer 3で扱いやすいマッピングを用意する

例:

```text
Kick              -> 36
Snare             -> 38
Closed Hi-Hat     -> 42
Pedal Hi-Hat      -> 44
Open Hi-Hat       -> 46
Crash Cymbal      -> 49
Ride Cymbal       -> 51
High Tom          -> 50
Mid Tom           -> 47
Floor Tom         -> 43
```

## 8. CLI Specification

### Convert PDF to MusicXML and MIDI

```bash
drum-score-converter convert input.pdf \
  --password "xxxxx" \
  --out ./dist \
  --format both
```

### Output only MusicXML

```bash
drum-score-converter convert input.pdf \
  --password "xxxxx" \
  --out ./dist \
  --format musicxml
```

### Output only MIDI

```bash
drum-score-converter convert input.pdf \
  --password "xxxxx" \
  --out ./dist \
  --format midi
```

### Render pages only

```bash
drum-score-converter render input.pdf \
  --password "xxxxx" \
  --out ./pages
```

## 9. Implementation Steps

### Milestone 1: Project Setup

* Pythonプロジェクトを作成
* `pyproject.toml` を作成
* CLIエントリポイントを作成
* READMEを作成
* 最小テスト環境を整備

### Milestone 2: PDF Loading

* 通常PDF読込
* パスワード付きPDF読込
* ページ数取得
* エラーハンドリング

### Milestone 3: Page Rendering

* PDFページをPNG化
* DPI指定対応
* 出力ディレクトリ指定対応

### Milestone 4: Internal Score Model

* Score / Measure / NoteEvent 等を定義
* ドラム楽器種別を定義
* 拍子・テンポを保持できるようにする

### Milestone 5: MusicXML Export

* 最小構成のMusicXMLを出力
* 4/4、1小節、キック・スネア・ハイハットのテストを作成
* MuseScore等で開けることを確認

### Milestone 6: MIDI Export

* 最小構成のMIDIを出力
* キック・スネア・ハイハットのMIDIノートを生成
* Cubaseで読み込めるMIDIを目指す

### Milestone 7: Vision AI Integration

* ページ画像をVision AIへ渡す
* 認識結果から内部モデルを生成する
* 不確実な認識結果を warning として出す

### Milestone 8: Validation

* 小節内の拍数が拍子と一致するか確認
* 未知の楽器記号を検出
* リピートやテンポ変更の扱いを検証

### Milestone 9: Documentation

* README整備
* 使用例追加
* Cubase + EZdrummer 3 での読み込み手順を書く
* 著作権に関する注意を書く

## 10. Copyright / Usage Notes

このツールは、ユーザーが正当に利用権を持つ譜面、または自作譜面を対象とする。

READMEには以下を明記する。

* 著作権で保護された楽譜を権利者の許諾なく変換・配布しないこと
* 生成されたMusicXML / MIDIの扱いも原譜の権利関係に従うこと
* このツールは権利侵害を目的としないこと

## 11. First Implementation Target

最初の実装対象は、Vision AI統合より前に、手動で作成した内部モデルから MusicXML と MIDI を出力できる状態にする。

最初のテストケース:

```text
Tempo: 120
Time Signature: 4/4
Measure 1:
  Beat 1: Kick + Closed Hi-Hat
  Beat 2: Snare + Closed Hi-Hat
  Beat 3: Kick + Closed Hi-Hat
  Beat 4: Snare + Closed Hi-Hat
```

期待成果物:

* `example.musicxml`
* `example.mid`

これにより、PDF認識より前に出力系の正しさを検証できる。

## 12. Development Principle

実装順序は以下を優先する。

```text
出力できる最小モデル
  ↓
MusicXML出力
  ↓
MIDI出力
  ↓
PDF読込
  ↓
画像化
  ↓
Vision AI認識
  ↓
実譜面対応
```

理由:

* Vision認識は不確実性が高い
* MusicXML / MIDI 出力が先に安定していないと検証できない
* 出力系を先に固めることで、認識処理のテストがしやすくなる

## 13. Final Expected Usage

```bash
drum-score-converter convert "score.pdf" \
  --password "password" \
  --out "./dist" \
  --format both
```

出力:

```text
dist/
├── score.musicxml
├── score.mid
├── recognition_report.md
└── pages/
    ├── page_001.png
    ├── page_002.png
    └── page_003.png
```

ユーザーは `score.mid` を Cubase に読み込み、EZdrummer 3 をアサインしてドラム音源として再生する。
