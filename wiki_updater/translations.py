from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ANCHOR_RE = re.compile(rb"<a\b[^>]*>", re.IGNORECASE)
ATTRIBUTE_RE = re.compile(
    rb"([:\w-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')",
    re.IGNORECASE,
)
LOCAL_PAGE_RE = re.compile(r"(?:\.\./)+([a-z]{2})/pages/(\d+)\.html(?:[#?].*)?$", re.IGNORECASE)


def page_translations(source: bytes) -> dict[str, int]:
    """Extract normalized MediaWiki language links without parsing the whole page DOM."""
    result: dict[str, int] = {}
    for tag in ANCHOR_RE.findall(source):
        attributes = {
            match.group(1).decode("ascii", "ignore").lower(): (
                match.group(2) or match.group(3) or b""
            ).decode("utf-8", "ignore")
            for match in ATTRIBUTE_RE.finditer(tag)
        }
        classes = set(attributes.get("class", "").split())
        if not ({"interlanguage-link-target", "extiw"} & classes):
            continue
        target = LOCAL_PAGE_RE.search(attributes.get("href", ""))
        if not target:
            continue
        language = attributes.get("hreflang") or target.group(1).lower()
        if re.fullmatch(r"[a-z]{2}", language):
            result[language] = int(target.group(2))
    return result


def build_translation_index(content_root: Path) -> dict[str, Any]:
    """Create a compact page-id translation map for the desktop reader."""
    pages: dict[str, dict[str, dict[str, int]]] = {}
    for language_root in sorted(content_root.glob("[a-z][a-z]/pages")):
        language = language_root.parent.name
        for page_path in sorted(language_root.glob("*.html")):
            targets = {
                target_language: target_id
                for target_language, target_id in page_translations(page_path.read_bytes()).items()
                if (content_root / target_language / "pages" / f"{target_id}.html").is_file()
            }
            if targets:
                pages.setdefault(language, {})[page_path.stem] = targets

    # A language page normally contains its reverse link, but filling missing
    # reverse edges makes older or partially rendered wiki pages deterministic.
    for source_language, language_pages in list(pages.items()):
        for source_id, targets in list(language_pages.items()):
            for target_language, target_id in targets.items():
                pages.setdefault(target_language, {}).setdefault(str(target_id), {}).setdefault(
                    source_language, int(source_id)
                )

    navigation: dict[str, dict[str, Any]] = {}
    for index_path in sorted((content_root / "search").glob("*.json")):
        documents = json.loads(index_path.read_text(encoding="utf-8"))
        navigation[index_path.stem] = {
            "home": next((int(item["id"]) for item in documents if item.get("home")), None),
            "pages": [[int(item["id"]), str(item["title"])] for item in documents],
        }

    payload: dict[str, Any] = {
        "schema": 1,
        "pages": pages,
        "navigation": navigation,
        "mapped_pages": sum(len(language_pages) for language_pages in pages.values()),
        "links": sum(
            len(targets)
            for language_pages in pages.values()
            for targets in language_pages.values()
        ),
    }
    target = content_root / "translations.json"
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(target)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the compact offline translation index.")
    parser.add_argument("content_root", type=Path)
    arguments = parser.parse_args()
    payload = build_translation_index(arguments.content_root.resolve())
    print(json.dumps({key: payload[key] for key in ("mapped_pages", "links")}))


if __name__ == "__main__":
    main()
