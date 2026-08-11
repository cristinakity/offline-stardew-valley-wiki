import json
from pathlib import Path

from wiki_updater.translations import build_translation_index, page_translations


def test_page_translations_ignores_tools_and_reads_language_links() -> None:
    source = (
        b'<a data-missing-local-language="en" data-missing-local-title="Special:Upload" href="#">Upload</a>'
        b'<a class="interlanguage-link-target" href="../../en/pages/1431.html" hreflang="en">English</a>'
        b'<a class="extiw" href="../../es/pages/22.html" title="es:Algo">Espanol</a>'
    )
    assert page_translations(source) == {"en": 1431, "es": 22}


def test_build_translation_index_writes_compact_bidirectional_map(tmp_path: Path) -> None:
    en = tmp_path / "en" / "pages" / "1.html"
    es = tmp_path / "es" / "pages" / "2.html"
    en.parent.mkdir(parents=True)
    es.parent.mkdir(parents=True)
    en.write_text(
        '<a class="interlanguage-link-target" href="../../es/pages/2.html" hreflang="es">ES</a>',
        encoding="utf-8",
    )
    es.write_text("<p>Sin enlace inverso</p>", encoding="utf-8")

    payload = build_translation_index(tmp_path)

    assert payload["pages"]["en"]["1"]["es"] == 2
    assert payload["pages"]["es"]["2"]["en"] == 1
    saved = json.loads((tmp_path / "translations.json").read_text(encoding="utf-8"))
    assert saved == payload
