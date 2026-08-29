# Lyricrafter Studio v0.1.7

Lyricrafter Studio v0.1.7 fixes model downloads from the normal console-free Windows desktop app. It also includes the CPU quality, performance controls, and navigation refresh introduced in v0.1.6.

## Model Download Fix

- Fixed Hugging Face model downloads failing with `[Errno 22] Invalid argument` or stream write errors when Lyricrafter is launched normally from Windows.
- Added runtime handling for both missing and unusable PyInstaller GUI output streams.
- Disabled redundant terminal progress bars while preserving Lyricrafter's in-app model download percentages.
- Added regression coverage for invalid Windows GUI streams.
- Added a console-free Windows model download, inference, and deletion gate to release builds.

## CPU Quality

- Changed automatic CPU transcription from quantized INT8 to full-precision FP32.
- Kept CUDA automatic processing on FP16, which delivers comparable Whisper accuracy with substantially higher speed on compatible NVIDIA GPUs.
- Changed CUDA failure fallback to CPU FP32 so losing GPU acceleration no longer silently lowers recognition precision.
- Preserved explicit INT8 and mixed-precision options for users who prioritize memory usage or throughput.
- Added the resolved device, precision, and CPU thread count to job activity messages.

## Performance Controls

- Added CPU profiles under Settings: Auto, Background, Balanced, Maximum, and Custom.
- Added an exact CPU thread slider with detected logical-processor limits.
- Persisted performance choices between launches.
- Reloaded faster-whisper only when a model, device, precision, or CPU thread configuration changes.
- Auto uses 60% of available logical processors, leaving capacity for the interface and media processing.

## Interface

- Replaced generic workspace icons with the supplied Queue, Editor, Models, History, and Settings artwork.
- Added packaged-resource verification for every navigation icon.
- Made the Settings surface vertically scrollable at compact window sizes.
- Added clearer compute-mode guidance in Advanced Processing settings.

## Verification

- 91 automated tests pass in both the standard and CPU-only Python environments.
- Frozen package and UI smoke-test paths include the new navigation resources.
- A controlled 90-second `large-v2` test produced essentially matching text on CPU FP32 and CUDA FP16; CPU INT8 produced additional recognition differences.
- Windows x64, Linux x64, macOS Apple Silicon, and macOS Intel packages are built and tested by GitHub Actions.

## Downloads

- Windows x64: `Lyricrafter-Windows-x64-Setup.exe`
- Linux x64: `Lyricrafter-Linux-x64.tar.gz`
- macOS Apple Silicon: `Lyricrafter-macOS-arm64.zip`
- macOS Intel: `Lyricrafter-macOS-x86_64.zip`

The Windows installer is CPU-ready. Compatible NVIDIA users can install the optional CUDA runtime from inside Lyricrafter. Whisper, translation, and separation model weights remain separate user-managed downloads.

`SHA256SUMS.txt` contains integrity hashes for the release files.

## Notes

- Windows and macOS packages are unsigned.
- CPU FP32 favors recognition quality and may take longer than INT8 on some processors.
- AI transcription can still mishear words in dense mixes, unusual vocals, or low-quality recordings. Lyric sources, alignment, and editor tools remain available for correction.
