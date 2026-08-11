from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from .config import LANGUAGES, Settings
from .database import Database
from .fixture import PIXEL_PNG, fixture_pages
from .jobs import control_checkpoint, control_checkpoint_sync
from .storage import Storage, sha256_bytes
from .translations import build_translation_index


INTERNAL_HOSTS = {"stardewvalleywiki.com", "www.stardewvalleywiki.com"} | {
    f"{language}.stardewvalleywiki.com" for language in LANGUAGES if language != "en"
}
SPECIAL_PREFIXES = ("Special:", "Help:", "MediaWiki:", "User:", "Talk:", "File:", "Category:")
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
CSS_IMPORT_RE = re.compile(r"@import\s+(?:url\([^)]*\)|['\"][^'\"]+['\"])[^;]*;", re.IGNORECASE)


def language_host(language: str) -> str:
    return "stardewvalleywiki.com" if language == "en" else f"{language}.stardewvalleywiki.com"


def language_from_host(host: str) -> str:
    host = host.lower().split(":", 1)[0]
    if host in {"stardewvalleywiki.com", "www.stardewvalleywiki.com"}:
        return "en"
    prefix = host.split(".", 1)[0]
    return prefix if prefix in LANGUAGES else "en"


def title_key(value: str) -> str:
    return unquote(value).replace("_", " ").strip(" / ").casefold()


def extension_for(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
    return guessed or ".bin"


def searchable_text(source: bytes | str) -> str:
    """Extract useful article text for the per-language offline index."""
    soup = BeautifulSoup(source, "html.parser")
    root = soup.select_one("#mw-content-text") or soup.select_one(".mw-parser-output") or soup.body or soup
    for element in root.select(
        "script,style,noscript,.mw-editsection,.navbox,.vertical-navbox,.metadata,.printfooter"
    ):
        element.decompose()
    return re.sub(r"\s+", " ", root.get_text(" ", strip=True)).strip()


@dataclass
class Asset:
    url: str
    relative_path: str
    created: bool
    size: int


class MediaWikiClient:
    def __init__(self, settings: Settings, checkpoint: Callable[[], Awaitable[None]] | None = None):
        self.settings = settings
        self.checkpoint = checkpoint
        self.semaphore = asyncio.Semaphore(settings.http_concurrency)
        self.client = httpx.AsyncClient(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en"},
            follow_redirects=True,
            timeout=httpx.Timeout(60, connect=20),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(5):
            if self.checkpoint:
                await self.checkpoint()
            try:
                async with self.semaphore:
                    response = await self.client.get(url, **kwargs)
                if response.status_code == 429:
                    await asyncio.sleep(float(response.headers.get("Retry-After", 2 ** (attempt + 1))))
                    continue
                if 400 <= response.status_code < 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise RuntimeError(f"Asset is unavailable ({exc.response.status_code}): {url}") from exc
                last_error = exc
                await asyncio.sleep(min(2 ** attempt, 16))
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                await asyncio.sleep(min(2 ** attempt, 16))
        raise RuntimeError(f"Failed to download {url}: {last_error}")

    async def api(self, language: str, parameters: dict[str, Any]) -> dict[str, Any]:
        defaults = {"format": "json", "formatversion": 2}
        response = await self.get(
            f"https://{language_host(language)}/mediawiki/api.php",
            params={**defaults, **parameters},
        )
        return response.json()

    async def all_pages(self, language: str, limit: int | None = None) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        continuation: dict[str, Any] = {}
        while True:
            payload = await self.api(
                language,
                {"action": "query", "list": "allpages", "apnamespace": 0, "aplimit": "max", **continuation},
            )
            pages.extend(payload["query"]["allpages"])
            if limit and len(pages) >= limit:
                return pages[:limit]
            if "continue" not in payload:
                return pages
            continuation = payload["continue"]

    async def main_page(self, language: str) -> dict[str, Any]:
        site_info = await self.api(language, {"action": "query", "meta": "siteinfo", "siprop": "general"})
        title = str(site_info["query"]["general"]["mainpage"])
        payload = await self.api(language, {"action": "query", "titles": title})
        page = payload["query"]["pages"][0]
        if page.get("missing"):
            raise RuntimeError(f"The {language} main page is unavailable: {title}")
        return {"pageid": int(page["pageid"]), "title": str(page["title"]), "home": True}

    async def revisions(self, language: str, pages: list[dict[str, Any]]) -> None:
        for offset in range(0, len(pages), 50):
            batch = pages[offset : offset + 50]
            payload = await self.api(
                language,
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "ids|timestamp",
                    "pageids": "|".join(str(page["pageid"]) for page in batch),
                },
            )
            metadata = {page["pageid"]: page for page in payload.get("query", {}).get("pages", [])}
            for page in batch:
                revisions = metadata.get(page["pageid"], {}).get("revisions", [])
                if revisions:
                    page["revid"] = revisions[0].get("revid")
                    page["timestamp"] = revisions[0].get("timestamp")

    async def rendered_page(self, language: str, title: str) -> str:
        path = quote(title.replace(" ", "_"), safe="/()!$&'*,;=:@~-")
        response = await self.get(f"https://{language_host(language)}/{path}")
        return response.text


class Normalizer:
    def __init__(self, client: MediaWikiClient | None, storage: Storage, content_root: Path,
                 title_maps: dict[str, dict[str, int]], fixture: bool = False):
        self.client = client
        self.storage = storage
        self.content_root = content_root
        self.title_maps = title_maps
        self.fixture = fixture
        self.asset_cache: dict[str, Asset] = {}
        self.stylesheet_cache: dict[str, Asset] = {}
        self.asset_locks: dict[str, asyncio.Lock] = {}
        self.stylesheet_locks: dict[str, asyncio.Lock] = {}
        self.asset_failures: list[dict[str, Any]] = []

    def record_asset_failure(
        self,
        language: str,
        page: dict[str, Any] | None,
        attribute: str,
        url: str,
        error: Exception,
    ) -> None:
        self.asset_failures.append({
            "language": language,
            "page_id": int(page["pageid"]) if page and page.get("pageid") is not None else None,
            "page_title": str(page.get("title", "")) if page else None,
            "attribute": attribute,
            "url": self.absolute_asset_url(url, language) or url,
            "error": str(error),
        })

    def internal_reference(self, href: str, current_language: str) -> tuple[str, str, str] | None:
        """Classify a link as belonging to one of the Stardew Valley wikis.

        This intentionally does not require the page to be present in the
        current snapshot. Sample snapshots only contain a small subset of the
        wiki, but links to the remaining articles are still internal links and
        must never be handed to the system browser as if they were external.
        """
        parsed = urlparse(href)
        if parsed.scheme not in {"", "http", "https", "file"}:
            return None
        if parsed.netloc and parsed.netloc.lower() not in INTERNAL_HOSTS:
            return None
        target_language = language_from_host(parsed.netloc) if parsed.netloc else current_language
        path = parsed.path
        if "/mediawiki/index.php" in path:
            title = parse_qs(parsed.query).get("title", [""])[0]
        else:
            title = unquote(path.lstrip("/"))
        if not title or title.startswith("#"):
            return None
        return target_language, title, parsed.fragment

    def internal_target(self, href: str, current_language: str) -> tuple[str, int, str] | None:
        reference = self.internal_reference(href, current_language)
        if not reference:
            return None
        target_language, title, fragment = reference
        if title.startswith(SPECIAL_PREFIXES):
            return None
        pageid = self.title_maps.get(target_language, {}).get(title_key(title))
        return (target_language, pageid, fragment) if pageid else None

    @staticmethod
    def absolute_asset_url(value: str, language: str) -> str | None:
        value = html.unescape(value.strip())
        if not value or value.startswith(("data:", "javascript:", "#")):
            return None
        if value.startswith("//"):
            return "https:" + value
        return urljoin(f"https://{language_host(language)}/", value)

    async def asset(self, url: str, language: str) -> Asset:
        absolute = self.absolute_asset_url(url, language)
        if not absolute:
            raise ValueError(f"Not a downloadable asset URL: {url}")
        if absolute in self.asset_cache:
            cached = self.asset_cache[absolute]
            return Asset(cached.url, cached.relative_path, False, cached.size)
        lock = self.asset_locks.setdefault(absolute, asyncio.Lock())
        async with lock:
            if absolute in self.asset_cache:
                cached = self.asset_cache[absolute]
                return Asset(cached.url, cached.relative_path, False, cached.size)
            if self.fixture and urlparse(absolute).path.endswith(("test.png", "test@2x.png")):
                payload, content_type = PIXEL_PNG, "image/png"
            else:
                assert self.client is not None
                response = await self.client.get(absolute)
                payload = response.content
                content_type = response.headers.get("Content-Type", "application/octet-stream")
            suffix = extension_for(absolute, content_type)
            digest, blob, created = self.storage.put_blob(payload, suffix)
            relative = f"assets/{digest[:2]}/{digest}{suffix}"
            self.storage.link_blob(blob, self.content_root / relative)
            asset = Asset(absolute, relative, created, len(payload))
            self.asset_cache[absolute] = asset
            return asset

    async def rewrite_css(self, source: str, base_url: str, language: str, *, from_stylesheet: bool) -> str:
        source = CSS_IMPORT_RE.sub("", source)
        replacements: dict[str, str] = {}
        for match in CSS_URL_RE.finditer(source):
            value = html.unescape(match.group(2).strip())
            if not value or value.startswith(("data:", "#")) or value in replacements:
                continue
            try:
                asset = await self.asset(urljoin(base_url, value), language)
                replacements[value] = (
                    f"../{asset.relative_path.removeprefix('assets/')}"
                    if from_stylesheet else f"../../{asset.relative_path}"
                )
            except (RuntimeError, httpx.HTTPError, ValueError):
                # Site CSS often retains references for long-removed optional
                # decorations. Keep the rest of the theme instead of dropping
                # the complete stylesheet because one legacy image is gone.
                replacements[value] = "data:,"
        return CSS_URL_RE.sub(
            lambda match: f"url('{replacements.get(html.unescape(match.group(2).strip()), match.group(2))}')",
            source,
        )

    async def stylesheet(self, url: str, language: str) -> Asset:
        absolute = self.absolute_asset_url(url, language)
        if not absolute:
            raise ValueError(f"Not a downloadable stylesheet URL: {url}")
        if absolute in self.stylesheet_cache:
            return self.stylesheet_cache[absolute]
        lock = self.stylesheet_locks.setdefault(absolute, asyncio.Lock())
        async with lock:
            if absolute in self.stylesheet_cache:
                return self.stylesheet_cache[absolute]
            assert self.client is not None
            response = await self.client.get(absolute)
            rewritten = await self.rewrite_css(response.text, absolute, language, from_stylesheet=True)
            payload = rewritten.encode("utf-8")
            digest, blob, created = self.storage.put_blob(payload, ".css")
            relative = f"assets/{digest[:2]}/{digest}.css"
            self.storage.link_blob(blob, self.content_root / relative)
            asset = Asset(absolute, relative, created, len(payload))
            self.stylesheet_cache[absolute] = asset
            return asset

    async def normalize(
        self,
        language: str,
        source: str,
        page: dict[str, Any] | None = None,
    ) -> tuple[bytes, dict[str, int]]:
        soup = BeautifulSoup(source, "html.parser")
        for element in soup.select("script, iframe, form, object, embed, noscript"):
            element.decompose()
        has_site_styles = any(
            "modules=site.styles" in str(link.get("href", ""))
            for link in soup.find_all("link")
        )
        for link in list(soup.find_all("link")):
            rel = {str(item).casefold() for item in link.get("rel", [])}
            href = str(link.get("href", ""))
            if "stylesheet" not in rel or not href or self.fixture:
                link.decompose()
                continue
            try:
                stylesheet = await self.stylesheet(href, language)
                link["href"] = f"../../{stylesheet.relative_path}"
            except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                self.record_asset_failure(language, page, "stylesheet", href, exc)
                link.decompose()

        # MediaWiki may omit site.styles from the rendered HTML even though it
        # contains the Stardew-specific background, menu borders and colors.
        # Fetch it explicitly so an offline page retains the wiki's identity.
        if not self.fixture and not has_site_styles:
            site_styles_url = (
                f"https://{language_host(language)}/mediawiki/load.php"
                f"?lang={language}&modules=site.styles&only=styles&skin=vector"
            )
            try:
                site_styles = await self.stylesheet(site_styles_url, language)
                site_link = soup.new_tag("link", rel="stylesheet", href=f"../../{site_styles.relative_path}")
                (soup.head or soup).append(site_link)
            except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                self.record_asset_failure(language, page, "stylesheet", site_styles_url, exc)
                # Validation still catches missing assets from stylesheets that
                # were successfully downloaded; a wiki without site.styles can
                # continue using its skin CSS.
                pass

        for span in list(soup.select("span[data-src]")):
            image = soup.new_tag("img")
            image["src"] = span.get("data-src", "")
            for source_key, target_key in (("data-alt", "alt"), ("data-width", "width"), ("data-height", "height")):
                if span.get(source_key):
                    image[target_key] = span[source_key]
            span.replace_with(image)

        asset_count = 0
        asset_bytes = 0
        asset_errors = 0
        for element in list(soup.select("[src], [data-src], [srcset]")):
            usable = False
            source = element.get("data-src") or element.get("src")
            if source:
                try:
                    asset = await self.asset(str(source), language)
                    element["src"] = f"../../{asset.relative_path}"
                    asset_count += int(asset.created)
                    asset_bytes += asset.size if asset.created else 0
                    usable = True
                except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                    asset_errors += 1
                    self.record_asset_failure(language, page, "src", str(source), exc)
                    element.attrs.pop("src", None)
            element.attrs.pop("data-src", None)

            if element.get("srcset"):
                rewritten_sources = []
                for entry in str(element["srcset"]).split(","):
                    parts = entry.strip().split()
                    if not parts:
                        continue
                    try:
                        asset = await self.asset(parts[0], language)
                        rewritten_sources.append(" ".join([f"../../{asset.relative_path}", *parts[1:]]))
                        asset_count += int(asset.created)
                        asset_bytes += asset.size if asset.created else 0
                        usable = True
                    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                        asset_errors += 1
                        self.record_asset_failure(language, page, "srcset", parts[0], exc)
                if rewritten_sources:
                    element["srcset"] = ", ".join(rewritten_sources)
                else:
                    element.attrs.pop("srcset", None)
            if not usable and element.name in {"img", "source"}:
                element.decompose()

        page_base = f"https://{language_host(language)}/"
        for style in soup.find_all("style"):
            try:
                style.string = await self.rewrite_css(style.get_text(), page_base, language, from_stylesheet=False)
            except (RuntimeError, httpx.HTTPError, ValueError):
                asset_errors += 1
                style.decompose()
        for element in soup.select("[style]"):
            try:
                element["style"] = await self.rewrite_css(
                    str(element["style"]), page_base, language, from_stylesheet=False
                )
            except (RuntimeError, httpx.HTTPError, ValueError):
                asset_errors += 1
                element.attrs.pop("style", None)

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if href.startswith("#"):
                continue
            reference = self.internal_reference(href, language)
            target = self.internal_target(href, language)
            if target:
                target_language, pageid, fragment = target
                anchor["href"] = f"../../{target_language}/pages/{pageid}.html" + (f"#{fragment}" if fragment else "")
                anchor.attrs.pop("target", None)
            elif reference:
                target_language, title, _fragment = reference
                anchor["href"] = "#"
                anchor["data-missing-local-title"] = title.replace("_", " ")
                anchor["data-missing-local-language"] = target_language
                if title.startswith(SPECIAL_PREFIXES):
                    anchor["data-offline-link-status"] = "excluded"
                else:
                    anchor["data-offline-link-status"] = "missing"
                anchor.attrs.pop("title", None)
                anchor.attrs.pop("target", None)
            else:
                absolute = urljoin(f"https://{language_host(language)}/", href)
                if urlparse(absolute).scheme in {"http", "https"}:
                    anchor["href"] = "#"
                    anchor["data-external-url"] = absolute
                else:
                    anchor["href"] = "#"

        head = soup.head
        if head is None:
            head = soup.new_tag("head")
            if soup.html:
                soup.html.insert(0, head)
        if head:
            stylesheet = soup.new_tag("link", rel="stylesheet", href="../../offline.css")
            head.append(stylesheet)
            charset = soup.new_tag("meta", charset="utf-8")
            head.insert(0, charset)
            policy = soup.new_tag("meta")
            policy["http-equiv"] = "Content-Security-Policy"
            policy["content"] = (
                "default-src 'none'; img-src 'self' file: data:; style-src 'self' file: 'unsafe-inline'; "
                "font-src 'self' file: data:; media-src 'self' file: data:"
            )
            head.insert(1, policy)
        if soup.html:
            soup.html["data-offline-wiki"] = "true"
            soup.html["lang"] = language
        return str(soup).encode("utf-8"), {
            "assets_written": asset_count,
            "bytes_written": asset_bytes,
            "asset_errors": asset_errors,
        }


OFFLINE_CSS = """
.mw-editsection,.printfooter{display:none!important}
a[data-offline-link-status="excluded"]{text-decoration-style:dashed!important;cursor:not-allowed!important}
a[data-offline-link-status="missing"]{text-decoration-style:dashed!important;cursor:help!important}
""".strip()


def atomic_write_text(path: Path, content: str) -> None:
    """Replace a file without modifying an inherited hard-linked snapshot file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def repair_deferred_internal_links(
    storage: Storage,
    content_root: Path,
    title_maps: dict[str, dict[str, int]],
    language: str,
    checkpoint: Callable[[], None] | None = None,
) -> dict[int, tuple[str, str]]:
    """Resolve links previously marked missing by a smaller base snapshot."""
    repaired: dict[int, tuple[str, str]] = {}
    for page_path in (content_root / language / "pages").glob("*.html"):
        if checkpoint:
            checkpoint()
        source = page_path.read_bytes()
        if b'data-offline-link-status="missing"' not in source:
            continue
        soup = BeautifulSoup(source, "html.parser")
        changed = False
        for anchor in soup.select('a[data-offline-link-status="missing"][data-missing-local-title]'):
            target_language = str(anchor.get("data-missing-local-language", language))
            title = str(anchor.get("data-missing-local-title", ""))
            target_id = title_maps.get(target_language, {}).get(title_key(title))
            if not target_id:
                continue
            anchor["href"] = f"../../{target_language}/pages/{target_id}.html"
            for attribute in (
                "data-missing-local-title",
                "data-missing-local-language",
                "data-offline-link-status",
            ):
                anchor.attrs.pop(attribute, None)
            changed = True
        if changed:
            normalized = str(soup).encode("utf-8")
            digest, blob, _created = storage.put_blob(normalized, ".html")
            storage.link_blob(blob, page_path)
            repaired[int(page_path.stem)] = (digest, searchable_text(normalized))
    return repaired


async def synchronize(settings: Settings, db: Database, run_id: int, profile: str) -> tuple[str, dict[str, Any]]:
    storage = Storage(settings)
    storage.ensure_capacity()
    work = settings.data_dir / "work" / str(run_id)
    if work.exists():
        shutil.rmtree(work)
    content_root = work / "content"
    previous_documents: dict[str, dict[int, dict[str, Any]]] = {}
    current = storage.current()
    incremental = profile == "incremental" and current is not None
    if incremental:
        current_content = Path(current["path"]) / "content"
        shutil.copytree(current_content, content_root, copy_function=os.link)
        for language in settings.enabled_languages:
            index_path = current_content / "search" / f"{language}.json"
            if index_path.exists():
                previous_documents[language] = {
                    int(item["id"]): item for item in json.loads(index_path.read_text(encoding="utf-8"))
                }
    else:
        content_root.mkdir(parents=True)
    atomic_write_text(content_root / "offline.css", OFFLINE_CSS + "\n")

    is_fixture = profile == "fixture"
    async def checkpoint() -> None:
        await control_checkpoint(db, run_id)

    client = None if is_fixture else MediaWikiClient(settings, checkpoint)
    pages_by_language: dict[str, list[dict[str, Any]]] = {}
    try:
        if is_fixture:
            await checkpoint()
            fixture = fixture_pages()
            pages_by_language = {language: fixture[language] for language in settings.enabled_languages}
        else:
            assert client is not None
            for language in settings.enabled_languages:
                await checkpoint()
                db.event(run_id, f"Enumerating {language} pages.", language=language)
                home = await client.main_page(language)
                pages = await client.all_pages(language, 25 if profile == "sample" else None)
                existing_home = next(
                    (page for page in pages if int(page["pageid"]) == int(home["pageid"])),
                    None,
                )
                if existing_home:
                    existing_home["home"] = True
                else:
                    pages.insert(0, home)
                    if profile == "sample":
                        pages = pages[:25]
                await client.revisions(language, pages)
                pages_by_language[language] = pages

        db.event(
            run_id,
            "Discovery complete. Starting page downloads and offline normalization.",
            languages=len(pages_by_language),
            pages=sum(len(pages) for pages in pages_by_language.values()),
        )

        title_maps = {
            language: {title_key(str(page["title"])): int(page["pageid"]) for page in pages}
            for language, pages in pages_by_language.items()
        }
        normalizer = Normalizer(client, storage, content_root, title_maps, fixture=is_fixture)
        language_stats: dict[str, Any] = {}
        search_root = content_root / "search"
        search_root.mkdir(exist_ok=True)

        for language, pages in pages_by_language.items():
            await checkpoint()
            db.execute(
                "INSERT OR REPLACE INTO run_languages(run_id,language,status,pages_total) VALUES(?,?,?,?)",
                (run_id, language, "running", len(pages)),
            )
            written = assets = bytes_written = asset_errors = 0
            previous = previous_documents.get(language, {})
            current_ids = {int(page["pageid"]) for page in pages}
            if incremental:
                for deleted_id in set(previous) - current_ids:
                    (content_root / language / "pages" / f"{deleted_id}.html").unlink(missing_ok=True)
            pages_to_process = [
                page for page in pages
                if not incremental
                or int(page["pageid"]) not in previous
                or previous[int(page["pageid"])].get("revision") != page.get("revid")
                or previous[int(page["pageid"])].get("title") != page.get("title")
            ]
            db.event(
                run_id,
                f"{language}: downloading and normalizing {len(pages_to_process)} pages "
                f"with {settings.page_concurrency} parallel page slot(s).",
                language=language,
                pages_total=len(pages),
                pages_changed=len(pages_to_process),
                page_concurrency=settings.page_concurrency,
                http_concurrency=settings.http_concurrency,
            )
            updated_digests: dict[int, str] = {}
            page_slots = asyncio.Semaphore(settings.page_concurrency)

            async def process_page(page: dict[str, Any]) -> tuple[dict[str, Any], str, int, dict[str, int], str]:
                async with page_slots:
                    await checkpoint()
                    source = (
                        str(page.get("html"))
                        if is_fixture
                        else await client.rendered_page(language, str(page["title"]))
                    )
                    normalized, stats = await normalizer.normalize(language, source, page)
                    await checkpoint()
                    digest, blob, _created = storage.put_blob(normalized, ".html")
                    destination = content_root / language / "pages" / f"{page['pageid']}.html"
                    storage.link_blob(blob, destination)
                    return page, digest, len(normalized), stats, searchable_text(normalized)

            page_tasks = [asyncio.create_task(process_page(page)) for page in pages_to_process]
            try:
                for completed in asyncio.as_completed(page_tasks):
                    page, digest, normalized_size, stats, search_text = await completed
                    updated_digests[int(page["pageid"])] = digest
                    page["search_text"] = search_text
                    written += 1
                    assets += stats["assets_written"]
                    bytes_written += normalized_size + stats["bytes_written"]
                    asset_errors += stats["asset_errors"]
                    if written % 5 == 0 or written == len(pages_to_process):
                        db.execute(
                            "UPDATE run_languages SET pages_written=?,assets_written=?,bytes_written=? "
                            "WHERE run_id=? AND language=?",
                            (written, assets, bytes_written, run_id, language),
                        )
                        db.event(
                            run_id,
                            f"{language}: processed {written}/{len(pages_to_process)} changed pages.",
                            language=language,
                        )
            except BaseException:
                for task in page_tasks:
                    task.cancel()
                await asyncio.gather(*page_tasks, return_exceptions=True)
                raise
            repaired_links = repair_deferred_internal_links(
                storage,
                content_root,
                title_maps,
                language,
                checkpoint=lambda: control_checkpoint_sync(db, run_id),
            )
            for page_id, (digest, search_text) in repaired_links.items():
                updated_digests[page_id] = digest
                page = next(item for item in pages if int(item["pageid"]) == page_id)
                page["search_text"] = search_text
            repaired_existing = len(set(repaired_links) - {int(page["pageid"]) for page in pages_to_process})
            if repaired_links:
                written += repaired_existing
                db.event(
                    run_id,
                    f"{language}: repaired deferred links in {len(repaired_links)} pages.",
                    language=language,
                    pages_repaired=len(repaired_links),
                )
            search_documents = [
                {
                    "id": int(page["pageid"]),
                    "title": str(page["title"]),
                    "url": f"{language}/pages/{page['pageid']}.html",
                    "revision": page.get("revid"),
                    "digest": updated_digests.get(int(page["pageid"]), previous.get(int(page["pageid"]), {}).get("digest")),
                    "text": page.get("search_text", previous.get(int(page["pageid"]), {}).get("text", "")),
                    "home": bool(page.get("home")),
                }
                for page in pages
            ]
            atomic_write_text(
                search_root / f"{language}.json",
                json.dumps(search_documents, ensure_ascii=False, separators=(",", ":")) + "\n",
            )
            revision_values = [str(page.get("timestamp", "")) for page in pages if page.get("timestamp")]
            db.execute(
                "UPDATE run_languages SET status='completed',pages_written=?,assets_written=?,bytes_written=?,revision_start=?,revision_end=? "
                "WHERE run_id=? AND language=?",
                (
                    written,
                    assets,
                    bytes_written,
                    min(revision_values, default=None),
                    max(revision_values, default=None),
                    run_id,
                    language,
                ),
            )
            language_stats[language] = {
                "pages": len(pages),
                "pages_updated": written,
                "assets_added": assets,
                "asset_errors": asset_errors,
                "bytes_written": bytes_written,
                "revision_start": min(revision_values, default=None),
                "revision_end": max(revision_values, default=None),
            }

        translation_index = build_translation_index(content_root)
        db.event(
            run_id,
            f"Translation index generated for {translation_index['mapped_pages']} pages.",
            translations=translation_index["links"],
        )
        expected_validation_pages = sum(len(pages) for pages in pages_by_language.values())
        db.event(
            run_id,
            f"Starting final offline validation of {expected_validation_pages} pages.",
            phase="validation",
            pages_total=expected_validation_pages,
        )

        def validation_progress(processed: int, expected: int) -> None:
            control_checkpoint_sync(db, run_id)
            if processed % 1000 == 0 or processed == expected:
                db.event(
                    run_id,
                    f"Offline validation: checked {processed}/{expected} pages.",
                    phase="validation",
                    pages_checked=processed,
                    pages_total=expected,
                )

        validation = validate_content(content_root, pages_by_language, progress=validation_progress)
        validation["asset_download_errors"] = sum(item["asset_errors"] for item in language_stats.values())
        for failure in normalizer.asset_failures:
            db.event(
                run_id,
                f"{failure['language']}: optional asset unavailable on {failure['page_title'] or 'unknown page'}.",
                level="warning",
                **failure,
            )
        db.event(
            run_id,
            "Offline validation complete.",
            **validation,
        )
        if any(validation[key] for key in ("broken_links", "missing_assets", "remote_resources")):
            raise RuntimeError(f"Offline validation failed: {validation}")
        generated = datetime.now(timezone.utc)
        manifest = {
            "schema": 1,
            "generated_at": generated.isoformat(),
            "profile": profile,
            "page_concurrency": settings.page_concurrency,
            "http_concurrency": settings.http_concurrency,
            "languages": language_stats,
            "validation": validation,
            "warnings": ([{
                "code": "asset_download_errors",
                "count": validation["asset_download_errors"],
                "message": (
                    f"{validation['asset_download_errors']} optional assets remained unavailable after automatic retries."
                ),
            }] if validation["asset_download_errors"] else []),
            "asset_failures": normalizer.asset_failures,
        }
        digest = sha256_bytes(json.dumps(manifest, sort_keys=True).encode())
        snapshot_id = f"{generated:%Y%m%dT%H%M%SZ}-{digest[:12]}"
        manifest["snapshot_id"] = snapshot_id
        manifest["digest"] = digest
        storage.promote(snapshot_id, content_root, manifest)
        shutil.rmtree(work, ignore_errors=True)
        return snapshot_id, manifest
    except asyncio.CancelledError:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    finally:
        if client:
            await client.close()


def validate_content(
    content_root: Path,
    pages_by_language: dict[str, list[dict[str, Any]]],
    *,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    broken_links = missing_assets = remote_resources = 0
    page_count = 0
    expected = sum(len(pages) for pages in pages_by_language.values())

    def validate_resource(value: str, base: Path) -> None:
        nonlocal missing_assets, remote_resources
        value = html.unescape(value.strip().strip("'\""))
        if not value or value.startswith(("data:", "#")):
            return
        if value.startswith(("http://", "https://", "//")):
            remote_resources += 1
        elif not (base / unquote(value.split("#", 1)[0].split("?", 1)[0])).resolve().exists():
            missing_assets += 1

    for page in content_root.glob("*/pages/*.html"):
        page_count += 1
        soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if href.startswith(("#", "http://", "https://")):
                if href.startswith(("http://", "https://")):
                    remote_resources += 1
                continue
            target = (page.parent / unquote(href.split("#", 1)[0])).resolve()
            if not target.exists():
                broken_links += 1
        for element in soup.find_all(src=True):
            validate_resource(str(element["src"]), page.parent)
        for element in soup.find_all(srcset=True):
            for entry in str(element["srcset"]).split(","):
                parts = entry.strip().split()
                if parts:
                    validate_resource(parts[0], page.parent)
        for link in soup.find_all("link", href=True):
            validate_resource(str(link["href"]), page.parent)
        for style in soup.find_all("style"):
            for match in CSS_URL_RE.finditer(style.get_text()):
                validate_resource(match.group(2), page.parent)
        for element in soup.select("[style]"):
            for match in CSS_URL_RE.finditer(str(element["style"])):
                validate_resource(match.group(2), page.parent)
        if progress:
            progress(page_count, expected)
    for stylesheet in content_root.glob("assets/*/*.css"):
        source = stylesheet.read_text(encoding="utf-8", errors="replace")
        for match in CSS_URL_RE.finditer(source):
            validate_resource(match.group(2), stylesheet.parent)
    if page_count != expected:
        broken_links += abs(expected - page_count)
    return {
        "pages": page_count,
        "expected_pages": expected,
        "broken_links": broken_links,
        "missing_assets": missing_assets,
        "remote_resources": remote_resources,
    }
