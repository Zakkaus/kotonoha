from kotonoha import strings


def test_each_language():
    translator = strings.Translator("en")
    assert translator.text("tray.quit") == "Quit"
    translator.set_language("zh-Hans")
    assert translator.text("tray.quit") == "退出"
    translator.set_language("zh-Hant")
    assert translator.text("tray.quit") == "結束"
    translator.set_language("ja")
    assert translator.text("tray.quit") == "終了"


def test_unknown_key_returns_key():
    assert strings.Translator("en").text("nope.nope") == "nope.nope"


def test_translators_keep_language_state_local_to_their_ui_graph():
    english = strings.Translator("en")
    japanese = strings.Translator("ja")

    english.set_language("zh-Hans")

    assert english.text("tray.quit") == "退出"
    assert japanese.text("tray.quit") == "終了"


def test_resolve_ui_language():
    assert strings.resolve_ui_language("zh_TW") == "zh-Hant"
    assert strings.resolve_ui_language("ja_JP") == "ja"
    assert strings.resolve_ui_language("ko") == "en"  # unsupported -> fallback
    assert strings.resolve_ui_language("fr_FR") == "en"
    assert strings.resolve_ui_language("zh_CN") == "zh-Hans"


def test_auto_is_supported():
    assert strings.Translator("auto").language in ("en", "zh-Hans", "zh-Hant", "ja")


def test_all_keys_have_all_languages():
    langs = ("en", "zh-Hans", "zh-Hant", "ja")
    for key, entry in strings.STRINGS.items():
        for lang in langs:
            assert entry.get(lang), f"missing {lang} for {key}"
