from pathlib import Path

from wiki_updater import __version__
from wiki_updater.web import DASHBOARD, list_local_builds


def test_dashboard_javascript_keeps_escaped_newlines() -> None:
    assert ".join('\\n')" in DASHBOARD
    assert ".join('\n')" not in DASHBOARD


def test_dashboard_explains_profiles_and_shows_crawler_activity() -> None:
    assert "Ayuda: cómo usar esta aplicación" in DASHBOARD
    assert "fixture — prueba sin Internet" in DASHBOARD
    assert "sample — prueba rápida real" in DASHBOARD
    assert "incremental — actualización habitual" in DASHBOARD
    assert "full — reconciliación completa" in DASHBOARD
    assert 'id="activity"' in DASHBOARD
    assert "Eventos recientes" in DASHBOARD
    assert "renderActivity" in DASHBOARD
    assert 'id="pageConcurrency"' in DASHBOARD
    assert "nunca se hacen más de 2 requests simultáneos" in DASHBOARD
    assert f"Crawler v{__version__}" in DASHBOARD
    assert "deleteCandidate" in DASHBOARD
    assert "El snapshot y GitHub no se modificarán" in DASHBOARD
    assert "Recover failed full" in DASHBOARD
    assert "recoverRun" in DASHBOARD
    assert "Publish with warnings" in DASHBOARD
    assert "selectedRunId=job.run_id" in DASHBOARD
    assert "Assets reutilizados" in DASHBOARD
    assert "0 B (sólo local)" in DASHBOARD
    assert "Purge temporary cache" in DASHBOARD
    assert "Keep current snapshot only" in DASHBOARD
    assert "Uso físico real" in DASHBOARD
    assert "Pausar" in DASHBOARD
    assert "Continuar" in DASHBOARD
    assert "Cancelar" in DASHBOARD
    assert "controlRun" in DASHBOARD


def test_dashboard_uses_tabs_and_bounded_scroll_regions() -> None:
    for tab in ("overview", "crawler", "runs", "candidates", "builds", "storage", "audit", "help"):
        assert f'data-tab="{tab}"' in DASHBOARD
        assert f"'{tab}'" in DASHBOARD
    assert "function showTab" in DASHBOARD
    assert "updater.activeTab" in DASHBOARD
    assert 'aria-label="Ayuda"' in DASHBOARD
    assert 'id="tab-runs"' in DASHBOARD
    assert 'id="candidates" class="list-scroll"' in DASHBOARD
    assert 'id="audit" class="audit-scroll"' in DASHBOARD
    assert "max-height:min(65vh,620px)" in DASHBOARD
    assert "showTab('crawler')" in DASHBOARD


def test_run_detail_switches_immediately_and_is_not_replaced_by_active_run() -> None:
    assert "let activityId=selectedRunId||s.active_run?.id" in DASHBOARD
    assert "selectedRunId=id;markSelectedRun();showTab('crawler',false)" in DASHBOARD
    assert "Run #${id} · cargando historial…" in DASHBOARD
    assert "if(selectedRunId===id)renderActivity(activity)" in DASHBOARD
    assert "selected-run" in DASHBOARD


def test_dashboard_refreshes_only_on_navigation_or_manual_request() -> None:
    assert 'id="refreshButton"' in DASHBOARD
    assert "async function manualRefresh()" in DASHBOARD
    assert "await refresh()" in DASHBOARD
    assert "setInterval(" not in DASHBOARD
    assert "periodicRefresh" not in DASHBOARD
    assert "Promise.all([api('/api/status'),api('/api/runs'),api('/api/candidates')" not in DASHBOARD


def test_candidate_assets_use_adaptive_file_sizes() -> None:
    assert "compactBytes(a.size)" in DASHBOARD
    assert "(a.size/1024/1024).toFixed(1)" not in DASHBOARD


def test_dashboard_lists_builds_without_polling_them(tmp_path: Path) -> None:
    older = tmp_path / "builds" / "20260810T021704Z"
    latest = tmp_path / "builds" / "20260811T050000Z"
    ignored = tmp_path / "builds" / ".editions"
    for directory in (older, latest, ignored):
        directory.mkdir(parents=True)
    (older / "Offline-Stardew-Valley-Wiki-linux-x64-1.3.0.zip").write_bytes(b"full")
    (latest / "offline-stardew-valley-wiki-en-1.3.0.zip").write_bytes(b"english")
    (latest / "offline-stardew-valley-wiki-es-1.3.0.zip").write_bytes(b"spanish")
    (latest / "SHA256SUMS").write_text("checksums\n", encoding="utf-8")
    (ignored / "temporary.zip").write_bytes(b"ignored")

    builds = list_local_builds(tmp_path)

    assert [build["id"] for build in builds] == ["20260811T050000Z", "20260810T021704Z"]
    assert builds[0]["latest"] is True
    assert builds[0]["editions"] == ["en", "es"]
    assert builds[1]["editions"] == ["multilingual"]
    assert 'data-tab="builds"' in DASHBOARD
    assert "async function refreshBuilds()" in DASHBOARD
    assert "activeTab==='builds'" not in DASHBOARD
