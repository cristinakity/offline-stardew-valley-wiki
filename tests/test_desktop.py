from pathlib import Path
import hashlib


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_search_library_exists() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "../node_modules/minisearch/dist/umd/index.js" in shell
    assert (ROOT / "node_modules" / "minisearch" / "dist" / "umd" / "index.js").is_file()


def test_desktop_keeps_original_language_toolbar() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "Go to Main Wiki page" in shell
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert all(code in renderer for code in ("'en'", "'es'", "'ja'", "'zh'"))


def test_desktop_uses_exact_legacy_background_and_flag_images() -> None:
    background = (
        ROOT
        / "src"
        / "stardewvalleywiki.com"
        / "mediawiki"
        / "extensions"
        / "StardewValley"
        / "images"
        / "stardewbackground.png"
    )
    assert hashlib.sha256(background.read_bytes()).hexdigest() == (
        "f714621f8ee63e3808a6288145e16cbc754c7a5a6b5ceecfc06852ab2c222589"
    )
    assert (ROOT / "src" / "flags" / "usa-flag.png").is_file()
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    assert "stardewbackground.png" in main
    assert "usa-flag.png" in main
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "stardewbackground.png" in shell
    assert "radial-gradient" not in shell


def test_hidden_loading_screen_cannot_cover_loaded_wiki() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "[hidden]{display:none!important}" in shell


def test_unavailable_page_message_exists_for_every_supported_language() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    for language in ("en", "es", "de", "fr", "it", "ja", "ko", "hu", "pt", "ru", "tr", "zh"):
        assert f"  {language}: title =>" in renderer


def test_desktop_searches_titles_and_article_text() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert "fields: ['title', 'text']" in renderer
    assert "showTitleSuggestions" in renderer
    assert "snippetFor" in renderer
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert 'id="searchPage"' in shell
