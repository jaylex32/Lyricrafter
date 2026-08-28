# Lyricrafter Studio v0.1.0

The first public release of Lyricrafter Studio delivers a local AI workflow for generating, repairing, translating, and exporting synchronized song lyrics.

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

`SHA256SUMS.txt` is provided for integrity verification.

The application and CUDA-capable AI runtime are included. Whisper, translation, and separation model weights are downloaded from inside Lyricrafter as needed.

## Verification

- 76 automated tests pass.
- Frozen Windows GUI startup verified.
- Bundled FFmpeg and native AI dependencies verified.
- A real Whisper model was downloaded by the frozen executable, loaded for CPU inference, and deleted successfully.

## Notes

- Windows and macOS packages are unsigned in this release.
- AI transcription can still mishear words in dense mixes, unusual vocals, or low-quality recordings. The lyric-source alignment and editor tools are provided for correction.
- Large models require several gigabytes of disk space and substantially more RAM/VRAM than smaller models.
