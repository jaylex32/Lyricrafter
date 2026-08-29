# Lyricrafter Studio v0.1.3

The first public release of Lyricrafter Studio delivers a local AI workflow for generating, repairing, translating, and exporting synchronized song lyrics.

## Fixed in 0.1.3

- Fixed frozen Windows NLLB translation failing to instantiate its tokenizer from symbolic-link model files.
- Applied the Windows-safe hard-linked runtime view to tokenizer, SentencePiece, and translation weight files.
- Added a packaged translation gate that loads the existing NLLB model and translates a real Spanish line to English.

## Fixed in 0.1.2

- Fixed frozen Windows transcription failing to open Hugging Face `model.bin` files stored as symbolic-link reparse points.
- Lyricrafter now creates a Windows-safe hard-linked runtime view of downloaded faster-whisper models without duplicating model data.
- Added a packaged-runtime check that loads an existing external-drive model through CTranslate2.

## Fixed in 0.1.1

- Prevented startup crashes when a configured model directory contains an inaccessible Windows mount point, junction, or stale external-drive entry.
- Model inventory now skips unreadable files and snapshots while continuing to detect healthy downloaded models.

## Included

- Single-track and batch transcription through faster-whisper.
- Local CPU and NVIDIA CUDA processing with automatic CPU fallback.
- Line-timed LRC plus TXT, SRT, and VTT exports.
- Professional waveform editor with playback synchronization and draggable timing markers.
- Song Map structure detection and repeated-section repair.
- Optional Demucs vocal isolation.
- Local NLLB translation and bilingual lyrics.
- LRCLIB, local, caption, synced lyric, and plain-text alignment workflows.
- URL audio downloads, source metadata, artwork, and metadata enrichment.
- Audio metadata lyric embedding.
- Downloadable and removable Whisper model library.
- Recommended `small`, `medium`, and `large-v2` model tiers.

## Windows Download

Download the setup executable and **all** `.bin` files into the same directory, then run:

`Lyricrafter-Windows-x64-Setup.exe`

Required files:

- `Lyricrafter-Windows-x64-Setup.exe`
- `Lyricrafter-Windows-x64-Setup-1.bin`
- `Lyricrafter-Windows-x64-Setup-2.bin`

Keep all three files together. The installer is split because the bundled NVIDIA
CUDA runtime makes the compressed Windows payload larger than GitHub's 2 GiB
per-file release limit. The `.bin` files are installer data, not separate apps.

The application and CUDA-capable AI runtime are included. Whisper, translation, and separation model weights are downloaded from inside Lyricrafter as needed.

## macOS Download

- Apple Silicon (M1 or newer): `Lyricrafter-macOS-arm64.zip`
- Intel: `Lyricrafter-macOS-x86_64.zip`

Extract the ZIP and open `Lyricrafter.app`. These packages use Apple's native
CPU/MPS runtime and therefore do not contain the Windows NVIDIA CUDA libraries.

## Linux Download

- x86-64: `Lyricrafter-Linux-x64.tar.gz`

Extract the archive and run `Lyricrafter/Lyricrafter`. The Linux release uses a
portable CPU runtime; CUDA remains available when running the Python source with
a compatible CUDA-enabled environment.

`SHA256SUMS.txt` contains integrity hashes for every release file.

## Verification

- 77 automated tests pass.
- Windows x64, Linux x64, macOS Apple Silicon, and macOS Intel builds pass the frozen package and UI checks.
- Bundled FFmpeg, translation runtime, writable model storage, model catalog, and native AI dependencies are verified on all four targets.
- A real Whisper model was downloaded, loaded for CPU inference, and deleted by the frozen Windows, Linux, and Apple Silicon packages.
- The Windows installer was installed to an isolated directory, launched, validated, and uninstalled successfully.

## Notes

- Windows and macOS packages are unsigned in this release.
- AI transcription can still mishear words in dense mixes, unusual vocals, or low-quality recordings. The lyric-source alignment and editor tools are provided for correction.
- Large models require several gigabytes of disk space and substantially more RAM/VRAM than smaller models.
