import asyncio
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from wiki_updater.config import Settings
from wiki_updater.crawler import (
    OFFLINE_CSS,
    MediaWikiClient,
    Normalizer,
    atomic_write_text,
    repair_deferred_internal_links,
    searchable_text,
    title_key,
    validate_content,
)
from wiki_updater.storage import Storage


def test_title_key_normalizes_encoded_titles() -> None:
    assert title_key("Getting_Started") == "getting started"
    assert title_key("Oto%C3%B1o") == "otoño"


def test_searchable_text_keeps_article_content_and_removes_navigation() -> None:
    source = (
        "<html><body><nav class='navbox'>Navigation text</nav>"
        "<main id='mw-content-text'><h1>Boat</h1><p>Boat is a piece of furniture.</p>"
        "<style>.hidden{display:none}</style></main></body></html>"
    )
    assert searchable_text(source) == "Boat Boat is a piece of furniture."


def test_atomic_write_does_not_modify_hard_linked_snapshot(tmp_path: Path) -> None:
    snapshot_index = tmp_path / "snapshot" / "search" / "en.json"
    snapshot_index.parent.mkdir(parents=True)
    snapshot_index.write_text('[{"id":1}]\n', encoding="utf-8")
    work_index = tmp_path / "work" / "search" / "en.json"
    work_index.parent.mkdir(parents=True)
    work_index.hardlink_to(snapshot_index)

    atomic_write_text(work_index, '[{"id":1},{"id":2}]\n')

    assert snapshot_index.read_text(encoding="utf-8") == '[{"id":1}]\n'
    assert work_index.read_text(encoding="utf-8") == '[{"id":1},{"id":2}]\n'
    assert snapshot_index.stat().st_ino != work_index.stat().st_ino


def test_repair_deferred_links_uses_complete_title_map(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    storage = Storage(settings)
    page = tmp_path / "content" / "en" / "pages" / "4.html"
    page.parent.mkdir(parents=True)
    page.write_text(
        '<html><body><a href="#" data-missing-local-title="Villagers" '
        'data-missing-local-language="en" data-offline-link-status="missing">Villagers</a>'
        '<a href="#" data-missing-local-title="Unknown" data-missing-local-language="en" '
        'data-offline-link-status="missing">Unknown</a></body></html>',
        encoding="utf-8",
    )

    repaired = repair_deferred_internal_links(
        storage,
        tmp_path / "content",
        {"en": {"villagers": 99}},
        "en",
    )

    result = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
    assert repaired[4][0]
    assert result.find("a", string="Villagers")["href"] == "../../en/pages/99.html"
    assert result.find("a", string="Unknown")["data-offline-link-status"] == "missing"


def test_internal_target_handles_languages(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    storage = Storage(settings)
    normalizer = Normalizer(
        None,
        storage,
        tmp_path / "content",
        {"en": {"abigail": 10}, "es": {"abigail": 20}},
        fixture=True,
    )
    assert normalizer.internal_target("/Abigail", "en") == ("en", 10, "")
    assert normalizer.internal_target("https://es.stardewvalleywiki.com/Abigail#Regalos", "en") == (
        "es", 20, "Regalos"
    )
    assert normalizer.internal_target("https://example.com/Abigail", "en") is None


def test_internal_reference_does_not_require_page_in_sample(tmp_path: Path) -> None:
    normalizer = Normalizer(
        None,
        Storage(Settings(data_dir=tmp_path, min_free_gb=0)),
        tmp_path / "content",
        {"en": {}},
        fixture=True,
    )
    assert normalizer.internal_reference("/Getting_Started#Controls", "en") == (
        "en", "Getting_Started", "Controls"
    )
    assert normalizer.internal_reference("https://example.com/Getting_Started", "en") is None


def test_cached_asset_is_not_counted_as_a_new_download(tmp_path: Path) -> None:
    async def exercise() -> tuple[bool, bool]:
        normalizer = Normalizer(
            None,
            Storage(Settings(data_dir=tmp_path, min_free_gb=0)),
            tmp_path / "content",
            {"en": {}},
            fixture=True,
        )
        first = await normalizer.asset("/mediawiki/images/test.png", "en")
        second = await normalizer.asset("/mediawiki/images/test.png", "en")
        return first.created, second.created

    assert asyncio.run(exercise()) == (True, False)


def test_normalizer_marks_missing_internal_pages_without_making_them_external(tmp_path: Path) -> None:
    async def exercise() -> BeautifulSoup:
        normalizer = Normalizer(
            None,
            Storage(Settings(data_dir=tmp_path, min_free_gb=0)),
            tmp_path / "content",
            {"en": {}},
            fixture=True,
        )
        result, _stats = await normalizer.normalize(
            "en",
            "<html><body><a id='missing' href='/Getting_Started'>Guide</a>"
            "<a id='excluded' href='/Special:CreateAccount'>Create account</a>"
            "<a id='external' href='https://example.com/help'>External</a></body></html>",
        )
        return BeautifulSoup(result, "html.parser")

    soup = asyncio.run(exercise())
    missing = soup.select_one("#missing")
    excluded = soup.select_one("#excluded")
    external = soup.select_one("#external")
    assert missing is not None and missing["data-missing-local-title"] == "Getting Started"
    assert missing["data-offline-link-status"] == "missing"
    assert "data-external-url" not in missing.attrs
    assert excluded is not None and excluded["data-offline-link-status"] == "excluded"
    assert external is not None and external["data-external-url"] == "https://example.com/help"


def test_validator_reports_missing_asset(tmp_path: Path) -> None:
    page = tmp_path / "content" / "en" / "pages" / "1.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html><body><img src='../../assets/missing.png'></body></html>", encoding="utf-8")
    result = validate_content(tmp_path / "content", {"en": [{"pageid": 1}]})
    assert result["missing_assets"] == 1


def test_validator_reports_page_progress(tmp_path: Path) -> None:
    page = tmp_path / "content" / "en" / "pages" / "1.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html><body>Ready</body></html>", encoding="utf-8")
    progress = []

    validate_content(
        tmp_path / "content",
        {"en": [{"pageid": 1}]},
        progress=lambda processed, expected: progress.append((processed, expected)),
    )

    assert progress == [(1, 1)]


def test_validator_checks_css_urls(tmp_path: Path) -> None:
    page = tmp_path / "content" / "en" / "pages" / "1.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html><style>body{background:url('https://example.com/a.png')}</style></html>", encoding="utf-8")
    result = validate_content(tmp_path / "content", {"en": [{"pageid": 1}]})
    assert result["remote_resources"] == 1


def test_client_does_not_retry_missing_assets(tmp_path: Path) -> None:
    requests = 0

    def missing(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(404, request=request)

    async def exercise() -> None:
        client = MediaWikiClient(Settings(data_dir=tmp_path, min_free_gb=0))
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(missing))
        with pytest.raises(RuntimeError, match="404"):
            await client.get("https://example.test/missing.png")
        await client.close()

    asyncio.run(exercise())
    assert requests == 1


def test_blob_gc_preserves_linked_content(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    storage = Storage(settings)
    _digest, orphan, _ = storage.put_blob(b"orphan", ".bin")
    _digest, retained, _ = storage.put_blob(b"retained", ".bin")
    Storage.link_blob(retained, tmp_path / "snapshots" / "one" / "content" / "asset.bin")
    storage.prune_unreferenced_blobs()
    assert not orphan.exists()
    assert retained.exists()


def test_rendered_subpage_keeps_path_separator(tmp_path: Path) -> None:
    requested_path = ""

    def page(request: httpx.Request) -> httpx.Response:
        nonlocal requested_path
        requested_path = request.url.path
        return httpx.Response(200, request=request, text="<html></html>")

    async def exercise() -> None:
        client = MediaWikiClient(Settings(data_dir=tmp_path, min_free_gb=0))
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(page))
        await client.rendered_page("ja", "Combat/Skill")
        await client.close()

    asyncio.run(exercise())
    assert requested_path == "/Combat/Skill"


def test_main_page_uses_localized_site_info(tmp_path: Path) -> None:
    def api(request: httpx.Request) -> httpx.Response:
        parameters = dict(request.url.params)
        if parameters.get("meta") == "siteinfo":
            return httpx.Response(
                200,
                request=request,
                json={"query": {"general": {"mainpage": "Página principal"}}},
            )
        assert parameters.get("titles") == "Página principal"
        return httpx.Response(
            200,
            request=request,
            json={"query": {"pages": [{"pageid": 42, "title": "Página principal"}]}},
        )

    async def exercise() -> dict[str, object]:
        client = MediaWikiClient(Settings(data_dir=tmp_path, min_free_gb=0))
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(api))
        result = await client.main_page("es")
        await client.close()
        return result

    assert asyncio.run(exercise()) == {"pageid": 42, "title": "Página principal", "home": True}


def test_offline_css_does_not_override_wiki_identity() -> None:
    assert "body{" not in OFFLINE_CSS
    assert "table{" not in OFFLINE_CSS


def test_stylesheet_keeps_theme_when_optional_asset_is_missing(tmp_path: Path) -> None:
    def responses(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("theme.css"):
            return httpx.Response(
                200,
                request=request,
                text="body{background:#0A0523 url('/missing.png')} .mw-body{color:#202122}",
                headers={"Content-Type": "text/css"},
            )
        return httpx.Response(404, request=request)

    async def exercise() -> tuple[str, list[dict]]:
        settings = Settings(data_dir=tmp_path, min_free_gb=0)
        storage = Storage(settings)
        client = MediaWikiClient(settings)
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(responses))
        normalizer = Normalizer(client, storage, tmp_path / "content", {"en": {}})
        stylesheet = await normalizer.stylesheet("https://stardewvalleywiki.com/theme.css", "en")
        result = (tmp_path / "content" / stylesheet.relative_path).read_text(encoding="utf-8")
        failures = normalizer.asset_failures
        await client.close()
        return result, failures

    css, failures = asyncio.run(exercise())
    assert "background:#0A0523" in css
    assert "url('data:,')" in css
    assert ".mw-body{color:#202122}" in css
    assert failures == [{
        "language": "en",
        "page_id": None,
        "page_title": None,
        "attribute": "css-url",
        "url": "https://stardewvalleywiki.com/missing.png",
        "http_status": 404,
        "attempts": 1,
        "last_error": "Resource is unavailable (404): https://stardewvalleywiki.com/missing.png",
        "error": "Resource is unavailable (404): https://stardewvalleywiki.com/missing.png",
    }]
