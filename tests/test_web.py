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
