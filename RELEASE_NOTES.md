# Lyricrafter Studio v0.1.5

Lyricrafter Studio v0.1.5 fixes startup with Hugging Face models stored on Windows volumes that enforce untrusted mount-point protections. It also includes the compact CPU-ready installer and optional NVIDIA acceleration introduced in v0.1.4.

## Startup Fix

- Windows model-cache links are classified without following their targets, preventing WinError 448 during startup on affected external or mounted drives.
- Added a regression test that reproduces the rejected-link traversal before model materialization.

## Windows Packaging

- Replaced the split multi-gigabyte Windows package with one CPU-ready installer.
- Added an optional in-app NVIDIA runtime download for faster-whisper transcription.
- Kept Whisper and translation model weights as separate user-managed downloads.
- Changed automatic transcription device detection to use the CTranslate2 GPU backend directly.

## Reliability

- NVIDIA components are downloaded from pinned official PyPI packages and SHA-256 verified before installation.
- CPU `int8` transcription remains the automatic fallback when NVIDIA acceleration is unavailable.
- Added tests for optional runtime installation, validation, extraction, and removal.

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

Download and run the single setup file:

`Lyricrafter-Windows-x64-Setup.exe`

The installer is CPU-ready and does not require a graphics card. Compatible NVIDIA users can open Models and select `Install NVIDIA Support`; Lyricrafter downloads and verifies the optional CUDA runtime without requiring another setup program. Whisper, translation, and separation model weights remain separate in-app downloads.

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

- 84 automated tests pass in both CUDA and CPU-only Python environments.
- Windows x64, Linux x64, macOS Apple Silicon, and macOS Intel builds pass the frozen package and UI checks.
- Bundled FFmpeg, translation runtime, writable model storage, model catalog, and native AI dependencies are verified on all four targets.
- A real Whisper model was downloaded, loaded for CPU inference, and deleted by the frozen Windows, Linux, and Apple Silicon packages.
- The final 220.1 MB Windows installer was installed, launched, and validated successfully.
- The optional NVIDIA pack was downloaded from the app pipeline, SHA-256 verified, and used to run `large-v2` transcription on CUDA.
- Existing external-drive `large-v2` loading and real Spanish-to-English NLLB translation pass from the installed application.

## Notes

- Windows and macOS packages are unsigned in this release.
- AI transcription can still mishear words in dense mixes, unusual vocals, or low-quality recordings. The lyric-source alignment and editor tools are provided for correction.
- Large models require several gigabytes of disk space and substantially more RAM/VRAM than smaller models.
