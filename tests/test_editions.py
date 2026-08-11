from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


LANGUAGE_EDITIONS = "en es de fr it ja ko hu pt ru tr zh"


def test_linux_builder_supports_full_and_every_language_edition() -> None:
    builder = (ROOT / "scripts" / "build-linux.sh").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    assert "WIKI_EDITION:-multilingual" in builder
    assert 'all) editions=(multilingual "${supported_languages[@]}")' in builder
    assert f"supported_languages=({LANGUAGE_EDITIONS})" in builder
    assert "prepare-edition.mjs" in builder
    assert "WIKI_EDITION: ${WIKI_EDITION:-multilingual}" in compose
    assert 'entrypoint: ["bash", "/workspace/scripts/build-linux.sh"]' in compose


def test_release_builds_multilingual_and_every_language() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-candidate.yml").read_text(
        encoding="utf-8"
    )
    editions = f"edition: [multilingual, {LANGUAGE_EDITIONS.replace(' ', ', ')}]"
    assert workflow.count(editions) == 2
    assert "linux-${{ matrix.edition }}" in workflow
    assert "windows-${{ matrix.edition }}" in workflow


def test_forge_gives_single_language_apps_distinct_identities() -> None:
    forge = (ROOT / "forge.config.js").read_text(encoding="utf-8")
    assert "const appSlug = `offline-stardew-valley-wiki${editionSuffix}`" in forge
    assert "const productName" in forge
    assert "WIKI_EDITION" in forge
