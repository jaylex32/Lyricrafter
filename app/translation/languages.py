from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationLanguage:
    name: str
    iso: str
    nllb: str


LANGUAGES = [
    TranslationLanguage("Auto detect from transcription", "auto", ""),
    TranslationLanguage("English", "en", "eng_Latn"),
    TranslationLanguage("Spanish", "es", "spa_Latn"),
    TranslationLanguage("French", "fr", "fra_Latn"),
    TranslationLanguage("German", "de", "deu_Latn"),
    TranslationLanguage("Portuguese", "pt", "por_Latn"),
    TranslationLanguage("Italian", "it", "ita_Latn"),
    TranslationLanguage("Japanese", "ja", "jpn_Jpan"),
    TranslationLanguage("Korean", "ko", "kor_Hang"),
    TranslationLanguage("Chinese Simplified", "zh", "zho_Hans"),
    TranslationLanguage("Hindi", "hi", "hin_Deva"),
    TranslationLanguage("Arabic", "ar", "arb_Arab"),
    TranslationLanguage("Russian", "ru", "rus_Cyrl"),
]

ISO_TO_NLLB = {language.iso: language.nllb for language in LANGUAGES if language.nllb}

NLLB_MODELS = {
    "NLLB Local - Fast / 600M": "facebook/nllb-200-distilled-600M",
    "NLLB Local - Better / 1.3B": "facebook/nllb-200-1.3B",
    "NLLB Local - Best / 3.3B": "facebook/nllb-200-3.3B",
}

TRANSLATION_ENGINES = [
    *NLLB_MODELS.keys(),
    "DeepL API - Cloud Quality",
    "Whisper Translate - English Only",
]


def language_names(include_auto: bool = True) -> list[str]:
    return [language.name for language in LANGUAGES if include_auto or language.iso != "auto"]


def nllb_code_for_name(name: str) -> str:
    for language in LANGUAGES:
        if language.name == name:
            return language.nllb
    raise KeyError(name)


def nllb_code_for_iso(iso: str | None, fallback: str = "eng_Latn") -> str:
    if not iso:
        return fallback
    return ISO_TO_NLLB.get(iso.lower(), fallback)


def model_id_for_engine(engine: str) -> str:
    return NLLB_MODELS[engine]
