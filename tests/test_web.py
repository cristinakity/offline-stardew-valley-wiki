from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from starlette.requests import Request

from wiki_updater import __version__
from wiki_updater.web import DASHBOARD, app, db, list_local_builds, oauth_callback, settings


async def test_production_health_has_session_available(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(db, "one", lambda *_args, **_kwargs: {"ok": 1})
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="https://updater.test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_production_private_api_requires_authentication(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="https://updater.test") as client:
        response = await client.get("/api/runs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}


async def test_production_oauth_callback_is_always_https(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://wikiupdater.kity.dev") as client:
        response = await client.get("/auth/login", follow_redirects=False)

    assert response.status_code == 303
    authorization = urlparse(response.headers["location"])
    callback = parse_qs(authorization.query)["redirect_uri"]
    assert callback == ["https://wikiupdater.kity.dev/auth/callback"]


async def test_oauth_token_exchange_reuses_https_callback(monkeypatch) -> None:
    posted: dict[str, str] = {}

    class Response:
        def __init__(self, payload: dict[str, str]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return self.payload

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, _url, *, headers, data):
            posted.update(data)
            return Response({"access_token": "token"})

        async def get(self, _url, *, headers):
            return Response({"login": "cristinakity"})

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "oauth_allowed_users", ("cristinakity",))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(db, "audit", lambda *_args, **_kwargs: None)
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/auth/callback", "raw_path": b"/auth/callback", "query_string": b"",
        "root_path": "", "headers": [], "client": ("127.0.0.1", 1),
        "server": ("wikiupdater.kity.dev", 80), "router": app.router,
        "session": {"oauth_state": "state"},
    }
    starlette_request = Request(scope)
    response = await oauth_callback(starlette_request, code="code", state="state")

    assert response.status_code == 303
    assert posted["redirect_uri"] == "https://wikiupdater.kity.dev/auth/callback"


def test_dashboard_javascript_keeps_escaped_newlines() -> None:
    assert ".join('\\n')" in DASHBOARD
    assert ".join('\n')" not in DASHBOARD
    assert r"sample'?'\n\nEste sample" in DASHBOARD


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
    assert "Create candidate from this run" in DASHBOARD
    assert "createCandidateFromRun" in DASHBOARD
    assert "sample es sólo para pruebas" in DASHBOARD
    assert "Bootstrap mode / Worker disabled" in DASHBOARD
    source = (Path(__file__).parents[1] / "wiki_updater" / "web.py").read_text()
    assert "Crawler worker is disabled" in source
    assert "Package builder is disabled" in source


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


def test_candidate_build_queue_controls_are_manual_and_reproducible() -> None:
    assert "Generate builds" in DASHBOARD
    assert "All — multilingual + 12 idiomas" in DASHBOARD
    assert "Linux — ZIP + DEB + RPM" in DASHBOARD
    assert "async function generateBuild" in DASHBOARD
    assert "async function rebuildBuild" in DASHBOARD
    assert "Logs y eventos" in DASHBOARD
    assert "progress_current" in DASHBOARD
    assert "pulsa <b>Refresh</b> para leer el progreso" in DASHBOARD


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
