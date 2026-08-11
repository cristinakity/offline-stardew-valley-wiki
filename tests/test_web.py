from wiki_updater import __version__
from wiki_updater.web import DASHBOARD


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


def test_dashboard_uses_tabs_and_bounded_scroll_regions() -> None:
    for tab in ("overview", "crawler", "runs", "candidates", "storage", "audit", "help"):
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
