from __future__ import annotations

import base64

from .config import LANGUAGES


PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def fixture_pages() -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for index, language in enumerate(LANGUAGES, start=1):
        title = "Stardew Valley Wiki"
        getting_started = f"Getting Started {language.upper()}"
        result[language] = [
            {
                "pageid": index * 1000 + 1,
                "title": title,
                "home": True,
                "revid": index * 10000 + 1,
                "timestamp": "2026-01-01T00:00:00Z",
                "html": (
                    f"<html lang='{language}'><head><title>{title}</title></head><body>"
                    f"<h1>{title}</h1><a href='/{getting_started.replace(' ', '_')}'>Start</a>"
                    "<span class='lazy-image-placeholder' data-src='/mediawiki/images/test.png' "
                    "data-alt='Test image' data-width='1' data-height='1'></span></body></html>"
                ),
            },
            {
                "pageid": index * 1000 + 2,
                "title": getting_started,
                "revid": index * 10000 + 2,
                "timestamp": "2026-01-02T00:00:00Z",
                "html": (
                    f"<html lang='{language}'><head><title>{getting_started}</title></head><body>"
                    f"<h1>{getting_started}</h1><a href='/Stardew_Valley_Wiki'>Home</a>"
                    "<img srcset='/mediawiki/images/test.png 1x, /mediawiki/images/test@2x.png 2x' "
                    "alt='Fixture'></body></html>"
                ),
            },
        ]
    return result
