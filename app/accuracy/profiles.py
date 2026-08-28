from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccuracyProfile:
    id: str
    name: str
    description: str
    prefer_vocal_isolation: bool = False
    two_pass: bool = False
    lock_language: bool = True
    condition_previous_text: bool | None = None
    use_metadata_hints: bool = False
    use_initial_prompt: bool = False
    vad_filter: bool = False


ACCURACY_PROFILES: tuple[AccuracyProfile, ...] = (
    AccuracyProfile(
        id="draft",
        name="Draft",
        description="Fast rough lyrics with minimal processing.",
        lock_language=False,
    ),
    AccuracyProfile(
        id="balanced",
        name="Balanced",
        description="Original Lyricrafter transcription behavior.",
        lock_language=False,
    ),
    AccuracyProfile(
        id="clean_vocal",
        name="Clean Vocal",
        description="Uses vocal isolation when possible for cleaner lyrics.",
        prefer_vocal_isolation=True,
        use_metadata_hints=True,
        use_initial_prompt=True,
    ),
    AccuracyProfile(
        id="studio_accurate",
        name="Studio Accurate",
        description="Slow two-pass mode with metadata hints and language lock.",
        prefer_vocal_isolation=True,
        two_pass=True,
        lock_language=True,
        use_metadata_hints=True,
        use_initial_prompt=True,
    ),
    AccuracyProfile(
        id="live_noisy",
        name="Live / Noisy",
        description="Conservative context for live or noisy recordings.",
        prefer_vocal_isolation=True,
        two_pass=True,
        lock_language=True,
        use_metadata_hints=True,
        use_initial_prompt=True,
        condition_previous_text=False,
    ),
)


def profile_by_id(profile_id: str | None) -> AccuracyProfile:
    normalized = (profile_id or "balanced").strip().casefold()
    return next((profile for profile in ACCURACY_PROFILES if profile.id == normalized), ACCURACY_PROFILES[1])
