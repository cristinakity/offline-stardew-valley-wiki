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
    assert 'candidate_archive="${CANDIDATE_ARCHIVE:-}"' in builder
    assert 'tar --zstd -xf "$candidate_archive"' in builder
    assert "current.json" not in builder


def test_release_builds_multilingual_and_every_language() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-candidate.yml").read_text(
        encoding="utf-8"
    )
    editions = f"edition: [multilingual, {LANGUAGE_EDITIONS.replace(' ', ', ')}]"
    assert workflow.count(editions) == 2
    assert "gh release upload" in workflow
    assert "actions/upload-artifact" not in workflow
    assert "SHA256SUMS-linux-$WIKI_EDITION" in workflow
    assert "SHA256SUMS-windows-$env:WIKI_EDITION" in workflow
    assert "test \"$(wc -l < SHA256SUMS)\" -eq 65" in workflow
    assert "build_scope:" in workflow
    assert "Reusing existing draft release" in workflow
    assert "7z a -tzip" in workflow
    assert "Compress-Archive" not in workflow


def test_forge_gives_single_language_apps_distinct_identities() -> None:
    forge = (ROOT / "forge.config.js").read_text(encoding="utf-8")
    assert "const appSlug = `offline-stardew-valley-wiki${editionSuffix}`" in forge
    assert "const productName" in forge
    assert "WIKI_EDITION" in forge


def test_compose_has_separate_persistent_builder_worker() -> None:
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    local = (ROOT / "compose.local.yml").read_text(encoding="utf-8")
    production = (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    assert "builder-worker:" in compose
    assert '["wiki-updater", "build-worker"]' in compose
    assert "builder-worker:" in local
    assert "builder-worker:" in production
    assert "podman.sock" not in compose + local + production
