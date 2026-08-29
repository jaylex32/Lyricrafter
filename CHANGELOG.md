# Changelog

All notable Lyricrafter Studio changes are documented here.

## 0.1.7 - 2026-08-29

### Fixed

- Fixed Whisper and translation model downloads when the Windows app is launched without a console.
- Replaced unusable PyInstaller GUI output handles with valid null streams.
- Disabled redundant Hugging Face terminal progress while preserving Lyricrafter's in-app percentage reporting.
- Added a console-free Windows model lifecycle test to release automation.

## 0.1.6 - 2026-08-29

### Added

- CPU performance profiles and an exact faster-whisper thread control.
- Custom workspace icons for Queue, Editor, Models, History, and Settings.
- Package smoke checks for navigation assets.

### Changed

- CPU automatic compute now uses FP32 for recognition quality comparable to CUDA FP16.
- CUDA fallback now preserves quality with CPU FP32.
- Model activity now reports resolved device, precision, and CPU thread count.
- Settings now scroll cleanly in vertically constrained windows.

### Fixed

- Prevented automatic CPU processing from silently using lower-precision INT8 inference.
- Corrected CPU handling of requested FP16 and INT8-FP16 compute modes.

## 0.1.5 - 2026-08-29

- Fixed startup when model caches contain Windows paths protected as untrusted mount points.

## 0.1.4 - 2026-08-29

- Added the compact CPU-ready Windows installer and optional in-app NVIDIA runtime.

## 0.1.3 - 2026-08-29

- Fixed frozen Windows NLLB translation model and tokenizer materialization.

## 0.1.2 - 2026-08-29

- Fixed frozen Windows faster-whisper model loading from symbolic-link caches.

## 0.1.1 - 2026-08-28

- Prevented inaccessible model paths from crashing model inventory and startup.

## 0.1.0 - 2026-08-28

- Initial public desktop release.
