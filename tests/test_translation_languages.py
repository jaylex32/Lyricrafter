from app.translation.languages import nllb_code_for_iso, nllb_code_for_name


def test_language_code_mapping() -> None:
    assert nllb_code_for_iso("es") == "spa_Latn"
    assert nllb_code_for_iso("unknown") == "eng_Latn"
    assert nllb_code_for_name("English") == "eng_Latn"
    assert nllb_code_for_name("Japanese") == "jpn_Jpan"
