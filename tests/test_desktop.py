from pathlib import Path
import hashlib


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_search_library_exists() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "../node_modules/minisearch/dist/umd/index.js" in shell


def test_desktop_keeps_original_language_toolbar() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "Go to Main Wiki page" in shell
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert all(code in renderer for code in ("'en'", "'es'", "'ja'", "'zh'"))


def test_desktop_translates_reader_and_native_menu() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "preload.js").read_text(encoding="utf-8")
    assert "const interfaceText" in renderer
    assert "function updateInterfaceLanguage" in renderer
    assert "Ir a la página principal" in renderer
    assert "Resultados de búsqueda" in renderer
    assert "window.offlineWiki.setLanguage(language)" in renderer
    assert "const menuLabels" in main
    assert "['Archivo', 'Editar', 'Ver', 'Ventana']" in main
    assert "wiki:set-language" in main
    assert "setLanguage" in preload


def test_desktop_only_shows_languages_in_the_package() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "preload.js").read_text(encoding="utf-8")
    assert "wiki:available-languages" in main
    assert "availableLanguages" in preload
    assert "availableLanguageCodes = await window.offlineWiki.availableLanguages()" in renderer
    assert "button.hidden = !availableLanguageCodes.includes" in renderer


def test_desktop_uses_exact_legacy_background_and_flag_images() -> None:
    background = ROOT / "desktop" / "assets" / "stardewbackground.png"
    assert hashlib.sha256(background.read_bytes()).hexdigest() == (
        "f714621f8ee63e3808a6288145e16cbc754c7a5a6b5ceecfc06852ab2c222589"
    )
    assert (ROOT / "desktop" / "assets" / "flags" / "usa-flag.png").is_file()
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    assert "stardewbackground.png" in main
    assert "usa-flag.png" in main
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "stardewbackground.png" in shell
    assert "radial-gradient" not in shell


def test_hidden_loading_screen_cannot_cover_loaded_wiki() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert "[hidden]{display:none!important}" in shell


def test_first_run_installer_selects_and_manages_languages() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    worker = (ROOT / "desktop" / "content-worker.js").read_text(encoding="utf-8")
    assert 'id="contentSetup"' in shell
    assert 'id="languageChoices"' in shell
    assert "download and install" in shell.lower()
    assert "Import from file / USB" in shell
    assert "navigator.language" in renderer
    assert "onContentProgress" in renderer
    assert "checkContentUpdate" in renderer
    assert "pauseContentInstall" in renderer
    assert "wiki:content-start" in main
    assert "createZstdDecompress" in worker
    assert "manifest.archive_sha256" in worker
    assert "prepareEdition" in worker


def test_content_setup_can_change_its_interface_language() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert 'id="setupInterfaceLanguage"' in shell
    assert "const setupText" in renderer
    assert "Preparar la wiki sin conexión" in renderer
    assert "オフラインWikiの準備" in renderer
    assert "function changeInterfaceLanguage" in renderer
    assert "offlineWiki.interfaceLanguage" in renderer
    assert "updateInterfaceLanguage(interfaceLanguage)" in renderer
    assert "Todavía no existe un release de contenido publicado" in renderer


def test_about_dialog_identifies_creator_and_release_links() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "preload.js").read_text(encoding="utf-8")
    assert 'id="aboutDialog"' in shell
    assert 'id="contentAbout"' in shell
    assert "Cristina Carrasco" in shell
    assert "const aboutText" in renderer
    assert "proyecto comunitario de código abierto" in renderer
    assert '<a id="aboutSourceLink"' in shell
    assert '<a id="aboutDownloadsLink"' in shell
    assert '<a id="aboutLicenseLink"' in shell
    assert "offline-stardew-valley-wiki/releases/latest" in shell
    assert "offline-stardew-valley-wiki/blob/master/LICENSE" in shell
    assert 'target="_blank"' in shell
    assert "setWindowOpenHandler" in main
    assert "openExternalWithFeedback" in main
    assert "Unable to open link" in main
    assert "const helpLabels" in main
    assert "wiki:open-about" in main
    assert "wiki:app-version" in main
    assert "onOpenAbout" in preload
    assert "appVersion" in preload


def test_about_dialog_shows_application_and_installed_content_versions() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    manager = (ROOT / "desktop" / "content-manager.js").read_text(encoding="utf-8")
    assert 'id="headerAppVersion"' in shell
    assert 'id="aboutContentVersionValue"' in shell
    assert 'id="aboutSnapshotDateValue"' in shell
    assert 'id="aboutSnapshotIdValue"' in shell
    assert 'id="aboutLanguagesValue"' in shell
    assert "const versionInfoText" in renderer
    assert "function snapshotTimestamp" in renderer
    assert "installedVersion" in manager
    assert "installedSnapshotId" in manager
    assert "installedAt" in manager


def test_flag_selection_changes_wiki_and_interface_language() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert "changeInterfaceLanguage(code);" in renderer
    assert "switchLanguage(code).catch" in renderer


def test_help_dialog_explains_first_setup_and_content_management() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "preload.js").read_text(encoding="utf-8")
    assert 'id="contentHelp"' in shell
    assert 'id="helpDialog"' in shell
    assert "const helpText" in renderer
    assert "Ayuda y primeros pasos" in renderer
    assert "Download and install" in renderer
    assert "Import from file / USB" in renderer
    assert '<a id="helpDownloadsLink"' in shell
    assert '<a id="helpSupportLink"' in shell
    assert "offline-stardew-valley-wiki/issues" in shell
    assert "wiki:open-help" in main
    assert "onOpenHelp" in preload


def test_unavailable_page_message_exists_for_every_supported_language() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    for language in ("en", "es", "de", "fr", "it", "ja", "ko", "hu", "pt", "ru", "tr", "zh"):
        assert f"  {language}: title =>" in renderer
    assert "status === 'excluded' ? unavailableMessages : pendingMessages" in renderer
    assert "todavía no se ha descargado o actualizado" in renderer


def test_desktop_searches_titles_and_article_text() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert "fields: ['title', 'text']" in renderer
    assert "showTitleSuggestions" in renderer
    assert "snippetFor" in renderer
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    assert 'id="searchPage"' in shell


def test_desktop_filters_search_entries_without_local_pages() -> None:
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    assert "indexedDocuments.filter" in main
    assert "ignored ${removed} entries without a local page" in main


def test_desktop_remembers_language_and_last_page() -> None:
    main = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "preload.js").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert "reader-state.json" in main
    assert "wiki:load-reader-state" in main
    assert "wiki:save-reader-state" in main
    assert "loadReaderState" in preload
    assert "saveReaderState" in preload
    assert "rememberDocument" in renderer
    assert "availableLanguageCodes.includes(saved?.language)" in renderer


def test_desktop_resolves_deferred_links_and_language_equivalents() -> None:
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert "openKnownTitle" in renderer
    assert "status !== 'excluded'" in renderer
    assert "translationFor" in renderer
    assert "anchor.getAttribute('hreflang') === language" in renderer
    assert "anchor.classList.contains('interlanguage-link-target')" in renderer
    assert "return mediaWikiLanguageLink || legacyLanguageLink" in renderer
    assert "anchor.removeAttribute('data-missing-local-title')" in renderer
    assert "../../${language}/pages/${localTarget.id}.html" in renderer
    assert "loadTranslations" in renderer
    assert "translationData.pages?.[currentLanguage]?.[String(currentDocument?.id)]?.[language]" in renderer
    assert "const languageCache = new Map()" in renderer
    assert "if (languageCache.has(code))" in renderer
    assert "function navigationDocuments" in renderer
    assert "async function ensureSearchIndex" in renderer
    assert "interfaceText[language]?.loading" in renderer


def test_desktop_notice_does_not_cover_toolbar() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert ".notice{position:static" in shell
    assert "body{margin:0;height:100vh;display:flex;flex-direction:column" in shell
    assert "notice.hidden = true" in renderer
    assert "header{position:relative;z-index:40" in shell
    assert ".results{position:absolute;z-index:30" in shell
    assert ".notice{position:static;z-index:5" in shell


def test_desktop_opens_downloaded_images_in_local_viewer() -> None:
    shell = (ROOT / "desktop" / "shell.html").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop" / "renderer.js").read_text(encoding="utf-8")
    assert 'id="imageViewer"' in shell
    assert 'id="imageZoomIn"' in shell
    assert "function bestLocalImageSource" in renderer
    assert "function openImageViewer" in renderer
    assert "a.image, a.mw-file-description" in renderer
    assert "imageLink?.querySelector('img')" in renderer
    assert "imageZoom = Math.min(8" in renderer
