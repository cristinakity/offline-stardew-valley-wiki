from __future__ import annotations

import asyncio
import json
import re
import secrets
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .builds import build_job, enqueue_build, enqueue_rebuild, list_build_jobs
from .candidates import candidate, create_candidate, delete_candidate, set_candidate_status
from .config import LANGUAGES, get_settings
from .database import Database
from .jobs import enqueue, request_cancel, request_pause, request_resume
from .recovery import recoverable_failure
from .storage import Storage


settings = get_settings()
db = Database(settings)
app = FastAPI(title="Offline Stardew Valley Wiki Updater", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.app_env != "local",
    same_site="lax",
    max_age=8 * 60 * 60,
)

BUILD_ID_RE = re.compile(r"^(?:\d{8}T\d{6}Z|job-\d{6})$")
BUILD_ASSET_SUFFIXES = {".zip", ".deb", ".rpm"}


def list_local_builds(data_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    builds_root = data_dir / "builds"
    if not builds_root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for directory in sorted(builds_root.iterdir(), key=lambda item: item.name, reverse=True):
        if not directory.is_dir() or not BUILD_ID_RE.fullmatch(directory.name):
            continue
        assets = [
            {"name": asset.name, "size": asset.stat().st_size}
            for asset in sorted(directory.iterdir())
            if not asset.is_symlink()
            and asset.is_file()
            and (asset.suffix.casefold() in BUILD_ASSET_SUFFIXES or asset.name == "SHA256SUMS")
        ]
        if not assets:
            continue
        editions = []
        searchable_names = " ".join(asset["name"].casefold() for asset in assets)
        for language in LANGUAGES:
            if re.search(rf"(?:^|[-_.(]){re.escape(language)}(?:[-_. )]|$)", searchable_names):
                editions.append(language)
        if len(assets) and not editions:
            editions.append("multilingual")
        result.append({"id": directory.name, "latest": not result, "editions": editions, "assets": assets})
        if len(result) >= min(max(limit, 1), 100):
            break
    return result


@app.middleware("http")
async def authenticate(request: Request, call_next):
    public = request.url.path in {"/api/health", "/auth/login", "/auth/callback"}
    if settings.app_env == "local":
        request.state.user = settings.local_auth_user
    else:
        request.state.user = request.session.get("github_user")
        if not public and not request.state.user:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Authentication required."}, status_code=401)
            return RedirectResponse("/auth/login", status_code=303)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'"
    )
    return response


def actor(request: Request) -> str:
    return str(request.state.user or "unknown")


@app.get("/auth/login")
async def login(request: Request):
    if settings.app_env == "local":
        return RedirectResponse("/", status_code=303)
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    callback = str(request.url_for("oauth_callback"))
    query = urlencode({"client_id": settings.github_oauth_client_id, "redirect_uri": callback, "scope": "read:user", "state": state})
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{query}", status_code=303)


@app.get("/auth/callback", name="oauth_callback")
async def oauth_callback(request: Request, code: str, state: str):
    expected = request.session.pop("oauth_state", "")
    if not expected or not secrets.compare_digest(expected, state):
        raise HTTPException(400, "Invalid OAuth state.")
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
            },
        )
        token_response.raise_for_status()
        token = token_response.json().get("access_token")
        if not token:
            raise HTTPException(401, "GitHub did not return an access token.")
        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        user_response.raise_for_status()
        github_user = str(user_response.json()["login"])
    if github_user.casefold() not in {item.casefold() for item in settings.github_allowed_users}:
        db.audit(github_user, "auth.denied")
        raise HTTPException(403, "This GitHub user is not authorized.")
    request.session["github_user"] = github_user
    db.audit(github_user, "auth.login")
    return RedirectResponse("/", status_code=303)


@app.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=303)


@app.get("/api/health")
def health() -> dict[str, Any]:
    database_ok = db.one("SELECT 1 AS ok") is not None
    return {"status": "ok" if database_ok else "error", "environment": settings.app_env, "version": __version__}


def decode_run(item: dict[str, Any]) -> dict[str, Any]:
    item["summary"] = json.loads(item.pop("summary_json", "{}"))
    item["cancel_requested"] = bool(item["cancel_requested"])
    item["pause_requested"] = bool(item["pause_requested"])
    item["recoverable"] = recoverable_failure(item)
    return item


@app.get("/api/runs")
def runs(limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 200)
    return [decode_run(item) for item in db.all("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int) -> dict[str, Any]:
    item = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not item:
        raise HTTPException(404, "Run not found.")
    item = decode_run(item)
    item["languages"] = db.all("SELECT * FROM run_languages WHERE run_id=? ORDER BY language", (run_id,))
    item["events"] = db.all("SELECT * FROM run_events WHERE run_id=? ORDER BY id", (run_id,))
    for event in item["events"]:
        event["detail"] = json.loads(event.pop("detail_json", "{}"))
    return item


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: int) -> StreamingResponse:
    if not db.one("SELECT id FROM runs WHERE id=?", (run_id,)):
        raise HTTPException(404, "Run not found.")

    async def stream() -> AsyncIterator[str]:
        last_id = 0
        while True:
            events = db.all("SELECT * FROM run_events WHERE run_id=? AND id>? ORDER BY id", (run_id, last_id))
            for event in events:
                last_id = event["id"]
                yield f"id: {last_id}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            run = db.one("SELECT status FROM runs WHERE id=?", (run_id,))
            if not run or run["status"] not in {"queued", "running", "paused"}:
                yield "event: complete\ndata: {}\n\n"
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/runs/sync")
async def start_sync(request: Request) -> dict[str, Any]:
    payload = await request.json()
    profile = payload.get("profile", "fixture")
    if profile not in {"fixture", "sample", "incremental", "full"}:
        raise HTTPException(400, "Invalid profile.")
    try:
        run_id = enqueue(db, "manual_sync", profile, actor(request))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id, "status": "queued"}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: int, request: Request) -> dict[str, str]:
    try:
        request_cancel(db, run_id, actor(request))
    except KeyError as exc:
        raise HTTPException(404, "Run not found.") from exc
    return {"status": "cancellation_requested"}


@app.post("/api/runs/{run_id}/pause")
def pause_run(run_id: int, request: Request) -> dict[str, str]:
    try:
        request_pause(db, run_id, actor(request))
    except KeyError as exc:
        raise HTTPException(404, "Run not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "pause_requested"}


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: int, request: Request) -> dict[str, str]:
    try:
        request_resume(db, run_id, actor(request))
    except KeyError as exc:
        raise HTTPException(404, "Run not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "running"}


@app.post("/api/runs/{run_id}/recover")
def recover_run(run_id: int, request: Request) -> dict[str, Any]:
    source = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not source:
        raise HTTPException(404, "Run not found.")
    if not recoverable_failure(source):
        raise HTTPException(409, "This failed run is not safely recoverable.")
    try:
        recovery_run_id = enqueue(db, "recovery", f"recover-{run_id}", actor(request))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.audit(actor(request), "run.recovery.enqueue", str(run_id), recovery_run_id=recovery_run_id)
    return {"run_id": recovery_run_id, "source_run_id": run_id, "status": "queued"}


@app.get("/api/candidates")
def candidates() -> list[dict[str, Any]]:
    result = []
    for row in db.all("SELECT id FROM candidates ORDER BY id DESC"):
        item = candidate(db, row["id"])
        if item:
            result.append(item)
    return result


@app.get("/api/builds")
def local_builds(limit: int = 20) -> list[dict[str, Any]]:
    jobs = list_build_jobs(db, limit)
    known_directories = {
        Path(str(job["output_directory"])).name
        for job in jobs if job.get("output_directory")
    }
    legacy = [
        {**item, "legacy": True, "status": "legacy", "events": []}
        for item in list_local_builds(settings.data_dir, limit)
        if item["id"] not in known_directories
    ]
    return [{**job, "legacy": False} for job in jobs] + legacy


@app.get("/api/builds/{build_id}/{asset_name}")
def local_build_asset(build_id: str, asset_name: str) -> FileResponse:
    if not BUILD_ID_RE.fullmatch(build_id) or Path(asset_name).name != asset_name:
        raise HTTPException(404, "Build asset not found.")
    builds_root = (settings.data_dir / "builds").resolve()
    target = (builds_root / build_id / asset_name).resolve()
    if (
        target.parent.parent != builds_root
        or not target.is_file()
        or target.is_symlink()
        or not (target.suffix.casefold() in BUILD_ASSET_SUFFIXES or target.name == "SHA256SUMS")
    ):
        raise HTTPException(404, "Build asset not found.")
    return FileResponse(target, filename=asset_name)


@app.post("/api/candidates/{candidate_id}/builds")
async def make_candidate_build(candidate_id: int, request: Request) -> dict[str, Any]:
    payload = await request.json()
    try:
        job_id = enqueue_build(
            db,
            candidate_id,
            str(payload.get("edition", "multilingual")),
            str(payload.get("platform", "linux")),
            actor(request),
        )
    except KeyError as exc:
        raise HTTPException(404, "Candidate not found.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return build_job(db, job_id) or {}


@app.post("/api/builds/{job_id}/rebuild")
def rebuild_candidate(job_id: int, request: Request) -> dict[str, Any]:
    try:
        rebuild_id = enqueue_rebuild(db, job_id, actor(request))
    except KeyError as exc:
        raise HTTPException(404, "Build not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return build_job(db, rebuild_id) or {}


@app.post("/api/candidates")
async def make_candidate(request: Request) -> dict[str, Any]:
    payload = await request.json()
    try:
        return create_candidate(settings, db, str(payload.get("version", "v1.3.0")), actor(request))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/candidates/{candidate_id}/{action}")
def candidate_action(candidate_id: int, action: str, request: Request) -> dict[str, Any]:
    status = {"publish": "published", "reject": "rejected", "reopen": "ready_for_review"}.get(action)
    if not status:
        raise HTTPException(404, "Unknown candidate action.")
    try:
        return set_candidate_status(settings, db, candidate_id, status, actor(request))
    except KeyError as exc:
        raise HTTPException(404, "Candidate not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.delete("/api/candidates/{candidate_id}")
def remove_candidate(candidate_id: int, request: Request) -> dict[str, str]:
    try:
        delete_candidate(settings, db, candidate_id, actor(request))
    except KeyError as exc:
        raise HTTPException(404, "Candidate not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "deleted"}


@app.get("/api/candidates/{candidate_id}/assets/{asset_name}")
def candidate_asset(candidate_id: int, asset_name: str):
    item = candidate(db, candidate_id)
    if not item:
        raise HTTPException(404, "Candidate not found.")
    available = {asset["name"] for asset in item["assets"]}
    if asset_name not in available or Path(asset_name).name != asset_name:
        raise HTTPException(404, "Asset not found.")
    return FileResponse(Path(item["directory"]) / asset_name, filename=asset_name)


@app.get("/api/settings")
def read_settings() -> dict[str, Any]:
    return {
        "enabled": db.setting("enabled", settings.enabled),
        "enabled_languages": db.setting("enabled_languages", list(settings.enabled_languages)),
        "page_concurrency": db.setting("page_concurrency", settings.page_concurrency),
        "storage_limit_gb": settings.storage_limit_gb,
        "min_free_gb": settings.min_free_gb,
        "snapshot_retention": settings.snapshot_retention,
        "timezone": settings.timezone,
    }


@app.put("/api/settings")
async def update_settings(request: Request) -> dict[str, Any]:
    payload = await request.json()
    enabled = bool(payload.get("enabled", True))
    languages = payload.get("enabled_languages", list(settings.enabled_languages))
    try:
        page_concurrency = int(payload.get("page_concurrency", settings.page_concurrency))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Page concurrency must be 1, 2 or 4.") from exc
    if not isinstance(languages, list) or not languages or set(languages) - set(LANGUAGES):
        raise HTTPException(400, "At least one supported language is required.")
    if page_concurrency not in {1, 2, 4}:
        raise HTTPException(400, "Page concurrency must be 1, 2 or 4.")
    db.set_setting("enabled", enabled)
    db.set_setting("enabled_languages", languages)
    db.set_setting("page_concurrency", page_concurrency)
    db.audit(
        actor(request), "settings.update", enabled=enabled, languages=languages,
        page_concurrency=page_concurrency,
    )
    return read_settings()


@app.get("/api/status")
def status() -> dict[str, Any]:
    storage = Storage(settings)
    return {
        "environment": settings.app_env,
        "current": storage.current(),
        "storage_used_bytes": storage.usage_bytes(),
        "storage_limit_bytes": settings.storage_limit_gb * 1024**3,
        "settings": read_settings(),
        "active_run": db.one("SELECT id,status,profile FROM runs WHERE status IN ('queued','running','paused') ORDER BY id LIMIT 1"),
    }


@app.get("/api/storage")
def storage_status() -> dict[str, Any]:
    return Storage(settings).usage_breakdown()


@app.post("/api/storage/purge")
async def purge_storage(request: Request) -> dict[str, Any]:
    if db.one("SELECT id FROM runs WHERE status IN ('queued','running','paused') LIMIT 1"):
        raise HTTPException(409, "Storage cannot be purged while a job is active.")
    payload = await request.json()
    target = str(payload.get("target", ""))
    storage = Storage(settings)
    before = storage.usage_bytes()
    detail: dict[str, Any] = {}
    if target == "cache":
        storage.purge_work()
        storage.prune_unreferenced_blobs()
    elif target == "builds":
        storage.purge_builds()
    elif target == "old_snapshots":
        detail["snapshots_deleted"] = storage.keep_current_snapshot_only()
    else:
        raise HTTPException(400, "Unknown storage purge target.")
    after = storage.usage_bytes()
    freed = max(0, before - after)
    db.audit(actor(request), f"storage.purge.{target}", freed_bytes=freed, **detail)
    return {"target": target, "before_bytes": before, "after_bytes": after, "freed_bytes": freed, **detail}


@app.get("/api/audit")
def audit_events(limit: int = 100) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 500)
    events = db.all("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
    for event in events:
        event["detail"] = json.loads(event.pop("detail_json", "{}"))
    return events


DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline Wiki Updater</title><style>
:root{color-scheme:dark;--bg:#091528;--card:#10243f;--line:#284565;--text:#e4efff;--muted:#9ab0c9;--good:#35c78a;--bad:#ff6b6b;--warning:#f2bf5b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:18px 24px 24px}
h1,h2,h3{margin:.2rem 0 1rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
button,input,select{font:inherit;padding:9px 12px;border-radius:7px;border:1px solid var(--line);background:#0b1a2d;color:var(--text)}button{cursor:pointer;background:#1767a6}button.danger{background:#8f3030}button.secondary{background:#253d58}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#294563}.ok{color:var(--good)}.bad{color:var(--bad)}.warning{color:var(--warning)}.muted,small{color:var(--muted)}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid var(--line)}th{position:sticky;top:0;z-index:1;background:#10243f}a{color:#6bbcff}pre{white-space:pre-wrap}.languages label{display:inline-flex;gap:4px;margin:4px}
.help-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}.help-item{background:#0b1a2d;border:1px solid var(--line);border-radius:9px;padding:12px}.help-item h3{font-size:16px;margin-bottom:6px}.help-item p{margin:.35rem 0;color:#c4d5ea}.profile-help{min-height:42px;margin-top:12px;color:#c4d5ea}
.activity-head{display:flex;justify-content:space-between;gap:12px;align-items:start;flex-wrap:wrap}.progress-summary{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));gap:10px;margin:12px 0}.metric{background:#0b1a2d;border-radius:8px;padding:10px}.metric strong{display:block;font-size:20px}.progressbar{width:100%;height:14px;accent-color:var(--good)}.language-progress{font-variant-numeric:tabular-nums}.event-log{background:#07111f;border:1px solid var(--line);border-radius:8px;padding:10px;max-height:260px;overflow:auto}.event-line{padding:5px 0;border-bottom:1px solid #1d3551}.event-line:last-child{border:0}@media(max-width:700px){.progress-summary{grid-template-columns:repeat(2,1fr)}main{padding:14px}}
.topbar{display:flex;justify-content:space-between;align-items:start;gap:16px}.crawler-version{white-space:nowrap;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:5px 10px}
.tabbar{position:sticky;top:0;z-index:20;display:flex;gap:6px;overflow-x:auto;margin:0 -24px 18px;padding:10px 24px;background:rgba(9,21,40,.97);border-block:1px solid var(--line);scrollbar-width:thin}.tabbar button{flex:0 0 auto;background:transparent;border-color:transparent;color:var(--muted)}.tabbar button:hover{background:#172d49;color:var(--text)}.tabbar button[aria-selected="true"]{background:#1767a6;color:white}.tabbar .refresh-button{margin-left:auto;color:#cfe8ff;border-color:var(--line)}.tabbar .refresh-button:disabled{opacity:.55;cursor:wait}.tabbar .help-button{min-width:42px;font-weight:800}.tab-panel{display:none}.tab-panel.active{display:block}.table-scroll,.list-scroll,.audit-scroll{max-height:min(65vh,620px);overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;border:1px solid var(--line);border-radius:8px}.table-scroll table{min-width:760px}.table-scroll.compact{max-height:310px}.list-scroll{padding:12px}.list-scroll>.card:last-child{margin-bottom:0}.audit-scroll{margin:0;padding:14px;background:#07111f;min-height:180px}.section-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.section-heading h2{margin:0}.tab-hint{color:var(--muted);margin-top:0}@media(max-width:700px){.tabbar{margin-inline:-14px;padding-inline:14px}.tabbar .refresh-button{margin-left:0}.topbar h1{font-size:24px}}
.selected-run td{background:rgba(23,103,166,.22)}.run-link[aria-current="true"]{color:#fff;font-weight:700;text-decoration-thickness:2px}
.build-card.latest{border-color:#3d9fd9;box-shadow:inset 3px 0 #3d9fd9}.build-assets{margin:.7rem 0;line-height:1.65}.edition-pill{display:inline-block;margin:2px 3px 2px 0;padding:2px 7px;border-radius:999px;background:#254968;color:#cfe8ff;text-transform:uppercase;font-size:12px}
.build-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:5px 14px;margin:.65rem 0;color:#c4d5ea}.build-log{max-height:170px;overflow:auto;margin:.7rem 0;padding:9px;background:#07111f;border:1px solid var(--line);border-radius:7px;font:12px ui-monospace,monospace;white-space:pre-wrap}.build-controls{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
</style></head><body><main>
<div class="topbar"><div><h1>Offline Stardew Valley Wiki Updater</h1><p>Local-first synchronization, validation and release candidates.</p></div><span class="crawler-version">Crawler v__UPDATER_VERSION__</span></div>
<nav class="tabbar" aria-label="Secciones"><button type="button" data-tab="overview" aria-selected="true" onclick="showTab('overview')">Resumen</button><button type="button" data-tab="crawler" aria-selected="false" onclick="showTab('crawler')">Crawler</button><button type="button" data-tab="runs" aria-selected="false" onclick="showTab('runs')">Runs</button><button type="button" data-tab="candidates" aria-selected="false" onclick="showTab('candidates')">Candidatos</button><button type="button" data-tab="builds" aria-selected="false" onclick="showTab('builds')">Builds</button><button type="button" data-tab="storage" aria-selected="false" onclick="showTab('storage')">Almacenamiento</button><button type="button" data-tab="audit" aria-selected="false" onclick="showTab('audit')">Auditoría</button><button id="refreshButton" type="button" class="refresh-button" title="Actualizar únicamente esta sección" onclick="manualRefresh()">↻ Refresh</button><button type="button" class="help-button" data-tab="help" aria-selected="false" aria-label="Ayuda" title="Ayuda" onclick="showTab('help')">?</button></nav>
<section class="tab-panel active" data-panel="overview"><section class="card"><b>This is the updater, not the wiki reader.</b> It downloads and validates content. To open the desktop wiki, run <code>npm start</code> on the host from the repository directory.</section></section>
<section id="tab-help" class="tab-panel" data-panel="help"><section class="card"><div class="section-heading"><h2>Ayuda: cómo usar esta aplicación</h2><button class="secondary" onclick="showTab('overview')">Cerrar ayuda</button></div>
<div class="help-grid">
<div class="help-item"><h3>1. fixture — prueba sin Internet</h3><p>Genera dos páginas artificiales por idioma. Sirve para comprobar Podman, SQLite, jobs y validación. <b>No descarga la wiki real.</b></p></div>
<div class="help-item"><h3>2. sample — prueba rápida real</h3><p>Descarga la portada y unas 24 páginas adicionales por idioma. Úsalo para revisar diseño, imágenes, enlaces, búsqueda y los 12 idiomas antes de una descarga completa.</p></div>
<div class="help-item"><h3>3. incremental — actualización habitual</h3><p>Compara revisiones de MediaWiki contra el snapshot actual. Sólo vuelve a procesar páginas nuevas o modificadas y elimina las borradas. Conviene usarlo después de tener un snapshot <code>full</code>.</p></div>
<div class="help-item"><h3>4. full — reconciliación completa</h3><p>Enumera y descarga todas las páginas de los idiomas habilitados. Es el proceso más lento y el que más espacio utiliza. Comprueba que el mirror coincida con MediaWiki.</p></div>
<div class="help-item"><h3>Scheduler, idiomas y velocidad</h3><p><b>Enabled</b> permite la ejecución automática. <b>Parallel pages</b> controla cuántas páginas se preparan a la vez. El límite hacia la wiki siempre permanece en dos requests simultáneos.</p></div>
<div class="help-item"><h3>Create candidate</h3><p>Congela el snapshot aprobado en una versión, genera manifiesto, checksums y archivos descargables. Hazlo únicamente después de revisar el resultado local. No publica en GitHub por sí solo.</p></div>
<div class="help-item"><h3>Recover failed full</h3><p>Si todas las páginas terminaron y sólo fallaron recursos opcionales, <b>Recover</b> reconstruye el snapshot desde los blobs locales y vuelve a validarlo sin descargar toda la wiki. El candidato quedará marcado con advertencias.</p></div>
<div class="help-item"><h3>Pausar, continuar y cancelar</h3><p>En <b>Crawler</b>, <b>Pausar</b> termina las solicitudes que ya están en vuelo y se detiene antes de iniciar la siguiente. <b>Continuar</b> reanuda el mismo run y conserva su progreso. <b>Cancelar</b> descarta solamente el workspace incompleto; no reemplaza el snapshot aprobado.</p></div>
<div class="help-item"><h3>Runs, Candidates y Audit</h3><p><b>Runs</b> conserva cada intento. Pulsa su ID para inspeccionarlo. <b>Candidates</b> contiene artefactos de revisión. <b>Audit</b> registra quién ejecutó o cambió algo.</p></div>
<div class="help-item"><h3>Builds por candidato</h3><p>En <b>Candidates</b>, selecciona una edición y pulsa <b>Generate builds</b>. Un worker separado extrae el <code>.tar.zst</code> inmutable de ese candidato y genera ZIP, DEB y RPM. <b>All editions</b> produce la multilingüe y las 12 individuales. <b>Rebuild</b> repite exactamente la fuente y parámetros de un job terminado sin sobrescribirlo.</p></div>
<div class="help-item"><h3>Abrir la wiki</h3><p>Este panel sólo administra el crawler. Abre el lector desde el host con <code>env -u ELECTRON_RUN_AS_NODE npm start</code>. El contenido se lee desde <code>.local-data</code>.</p></div>
</div></section></section>
<section class="tab-panel active" data-panel="overview"><div class="grid"><section class="card"><h2>Status</h2><div id="status">Loading…</div></section>
<section class="card"><h2>Run synchronization</h2><div class="row"><select id="profile" onchange="showProfileHelp()"><option>fixture</option><option>sample</option><option>incremental</option><option>full</option></select><button onclick="startRun()">Start</button></div><div id="profileHelp" class="profile-help"></div><p><small>Sólo puede existir una ejecución activa. Puedes pausarla, continuarla o cancelarla desde Crawler.</small></p></section>
<section class="card"><h2>Create candidate</h2><div class="row"><input id="version" value="v1.3.0" pattern="v?[0-9]+\\.[0-9]+\\.[0-9]+"><button onclick="createCandidate()">Create</button></div></section></div>
</section>
<section id="tab-storage" class="tab-panel" data-panel="storage"><section class="card"><h2>Storage</h2><p id="storageSummary" class="muted">Calculando uso real…</p><div id="storageBreakdown" class="table-scroll compact"></div><p><small>Los tamaños por categoría pueden compartir hardlinks y no deben sumarse. “Uso real” cuenta cada inode una sola vez.</small></p><div class="row"><button class="secondary" onclick="purgeStorage('cache')">Purge temporary cache</button><button class="danger" onclick="purgeStorage('builds')">Delete build outputs</button><button class="danger" onclick="purgeStorage('old_snapshots')">Keep current snapshot only</button></div><p><small>La caché elimina temporales y blobs no referenciados; los runs fallidos podrían dejar de ser recuperables. Los candidatos se eliminan individualmente en Candidates.</small></p></section></section>
<section class="tab-panel active" data-panel="overview"><section class="card"><h2>Scheduler and languages</h2><div class="row"><label><input type="checkbox" id="enabled"> Enabled</label><label>Parallel pages <select id="pageConcurrency"><option value="1">1 — Sequential</option><option value="2">2 — Balanced</option><option value="4">4 — Fast local</option></select></label><button class="secondary" onclick="saveSettings()">Save</button></div><p><small>Se aplica al siguiente job. Incluso en modo 4, nunca se hacen más de 2 requests simultáneos hacia la wiki.</small></p><div class="languages" id="languages"></div></section></section>
<section id="tab-crawler" class="tab-panel" data-panel="crawler"><section class="card"><div class="activity-head"><div><h2>Actividad del crawler</h2><div id="activityTitle" class="muted">Esperando datos…</div></div><span id="activityState" class="pill">idle</span></div><div id="activity"><p class="muted">Selecciona un Run o inicia una sincronización.</p></div></section></section>
<section id="tab-runs" class="tab-panel" data-panel="runs"><section class="card"><div class="section-heading"><h2>Runs</h2><span class="muted">Lista con scroll</span></div><p class="tab-hint"><small>Pulsa un ID para mostrar su progreso e historial en Crawler.</small></p><div class="table-scroll"><table><thead><tr><th>ID</th><th>Profile</th><th>Status</th><th>Created</th><th>Snapshot</th><th></th></tr></thead><tbody id="runs"></tbody></table></div></section></section>
<section id="tab-candidates" class="tab-panel" data-panel="candidates"><section class="card"><div class="section-heading"><h2>Candidates</h2><span class="muted">Lista con scroll</span></div><div id="candidates" class="list-scroll"></div></section></section>
<section id="tab-builds" class="tab-panel" data-panel="builds"><section class="card"><div class="section-heading"><div><h2>Builds locales</h2><small>Preversiones Linux generadas desde el snapshot aprobado. No se publican en GitHub automáticamente.</small></div><span class="muted">Más reciente primero</span></div><div id="builds" class="list-scroll"><small>Cargando builds…</small></div></section></section>
<section id="tab-audit" class="tab-panel" data-panel="audit"><section class="card"><div class="section-heading"><h2>Audit history</h2><span class="muted">Últimos 25 eventos</span></div><pre id="audit" class="audit-scroll"></pre></section></section>
</main><script>
const langs=['en','es','de','fr','it','ja','ko','hu','pt','ru','tr','zh'];
const buildEditions=['all','multilingual',...langs];
const profileDescriptions={fixture:'Prueba controlada sin Internet: 2 páginas artificiales por idioma.',sample:'Prueba real rápida: portada + aproximadamente 24 páginas por idioma.',incremental:'Compara revisiones y procesa sólo cambios respecto al snapshot actual.',full:'Descarga y reconcilia todas las páginas de los idiomas habilitados.'};
let selectedRunId=null;let activeTab='overview';let manualRefreshRunning=false;
const validTabs=new Set(['overview','crawler','runs','candidates','builds','storage','audit','help']);
function showTab(name,refreshNow=true){if(!validTabs.has(name))name='overview';activeTab=name;document.querySelectorAll('[data-panel]').forEach(panel=>panel.classList.toggle('active',panel.dataset.panel===name));document.querySelectorAll('[data-tab]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.tab===name)));localStorage.setItem('updater.activeTab',name);window.scrollTo({top:0,behavior:'smooth'});if(refreshNow)void refreshTab(name)}
async function api(url,options={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...options});if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json()}
function bytes(v){return(v/1024/1024/1024).toFixed(2)+' GiB'}
function compactBytes(v){if(v>=1073741824)return(v/1073741824).toFixed(2)+' GiB';if(v>=1048576)return(v/1048576).toFixed(1)+' MiB';if(v>=1024)return(v/1024).toFixed(1)+' KiB';return v+' B'}
function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function buildEditionOptions(){return buildEditions.map(edition=>`<option value="${edition}">${edition==='all'?'All — multilingual + 12 idiomas':edition==='multilingual'?'Multilingual':edition.toUpperCase()}</option>`).join('')}
function showProfileHelp(){document.querySelector('#profileHelp').textContent=profileDescriptions[document.querySelector('#profile').value]}
function activityControls(x){if(!['queued','running','paused'].includes(x.status))return'';if(x.cancel_requested)return'<div class="row"><button disabled>Cancelando de forma segura…</button></div>';const resume=x.status==='paused'||x.pause_requested;return`<div class="row">${x.kind!=='recovery'?`<button class="secondary" onclick="controlRun(${x.id},'${resume?'resume':'pause'}')">${resume?'Continuar':'Pausar'}</button>`:''}<button class="danger" onclick="cancelRun(${x.id})">Cancelar</button></div>`}
function renderActivity(x){const ls=x.languages||[];const total=ls.reduce((n,l)=>n+l.pages_total,0);const written=ls.reduce((n,l)=>n+l.pages_written,0);const assets=ls.reduce((n,l)=>n+l.assets_written,0);const size=ls.reduce((n,l)=>n+l.bytes_written,0);const isRecovery=x.kind==='recovery';const validation=[...(x.events||[])].reverse().find(e=>e.detail?.phase==='validation');const restoredAssets=[...(x.events||[])].reverse().find(e=>Number.isFinite(e.detail?.assets));let percent=total?Math.round(written/total*100):0;if(isRecovery){const restoredPercent=total?written/total:0;percent=validation?50+Math.round((validation.detail.pages_checked||0)/(validation.detail.pages_total||total||1)*50):Math.round(restoredPercent*50)}const last=x.events?.at(-1);const displayedState=x.cancel_requested?'cancelling':x.pause_requested&&x.status==='running'?'pausing':x.status;document.querySelector('#activityTitle').textContent=`Run #${x.id} · ${x.profile} · ${last?.message||'sin eventos'}`;document.querySelector('#activityState').textContent=displayedState;document.querySelector('#activityState').className=`pill ${x.status==='completed'?'ok':x.status==='completed_with_warnings'?'warning':x.status==='failed'?'bad':''}`;
document.querySelector('#activity').innerHTML=`${activityControls(x)}<div class="progress-summary"><div class="metric"><small>Progreso total</small><strong>${percent}%</strong></div><div class="metric"><small>${isRecovery?'Páginas restauradas':'Páginas procesadas'}</small><strong>${written} / ${total||'?'}</strong></div><div class="metric"><small>${isRecovery?'Assets reutilizados':'Assets nuevos'}</small><strong>${isRecovery?(restoredAssets?.detail.assets??'Enlazando…'):assets}</strong></div><div class="metric"><small>${isRecovery?'Transferencia de red':'Datos escritos'}</small><strong>${isRecovery?'0 B (sólo local)':compactBytes(size)}</strong></div></div><progress class="progressbar" max="100" value="${percent}"></progress>${x.error?`<p class="bad"><b>Error:</b> ${x.error}</p>`:''}<div class="table-scroll compact"><table class="language-progress"><thead><tr><th>Idioma</th><th>Estado</th><th>Páginas</th><th>${isRecovery?'Assets nuevos':'Assets'}</th><th>${isRecovery?'Red':'Datos'}</th><th>Revisión final</th></tr></thead><tbody>${ls.map(l=>`<tr><td>${l.language}</td><td>${l.status}</td><td>${l.pages_written}/${l.pages_total}</td><td>${l.assets_written}</td><td>${isRecovery?'0 B':compactBytes(l.bytes_written)}</td><td>${l.revision_end||'—'}</td></tr>`).join('')||'<tr><td colspan="6">Preparando contenido local…</td></tr>'}</tbody></table></div><h3>Eventos recientes</h3><div class="event-log">${(x.events||[]).slice(-30).reverse().map(e=>`<div class="event-line"><small>${new Date(e.created_at).toLocaleString()}</small> <span class="${e.level==='error'?'bad':''}">[${e.level}] ${e.message}</span></div>`).join('')||'<span class="muted">Todavía no hay eventos.</span>'}</div>`}
function renderStatus(s){document.querySelector('#status').innerHTML=`Environment: <b>${s.environment}</b><br>Storage real: ${bytes(s.storage_used_bytes)} / ${bytes(s.storage_limit_bytes)}<br>Snapshot: ${s.current?.snapshot_id||'none'}<br>Active: ${s.active_run?.id||'none'}`}
function renderSettings(conf){document.querySelector('#enabled').checked=conf.enabled;document.querySelector('#pageConcurrency').value=String(conf.page_concurrency);document.querySelector('#languages').innerHTML=langs.map(l=>`<label><input type="checkbox" data-lang="${l}" ${conf.enabled_languages.includes(l)?'checked':''}>${l}</label>`).join('')}
async function refreshStatus(){renderStatus(await api('/api/status'))}
async function refreshOverview(){const [s,conf]=await Promise.all([api('/api/status'),api('/api/settings')]);renderStatus(s);renderSettings(conf)}
async function refreshRuns(){const r=await api('/api/runs');document.querySelector('#runs').innerHTML=r.map(x=>`<tr data-run-id="${x.id}" class="${selectedRunId===x.id?'selected-run':''}"><td><a class="run-link" aria-current="${selectedRunId===x.id?'true':'false'}" href="#" onclick="detail(${x.id});return false">${x.id}</a></td><td>${x.profile}</td><td>${x.cancel_requested?'cancelling':x.pause_requested&&x.status==='running'?'pausing':x.status}</td><td>${x.created_at}</td><td>${x.snapshot_id||''}</td><td>${['queued','running','paused'].includes(x.status)?activityControls(x):x.recoverable?`<button class="secondary" onclick="recoverRun(${x.id})">Recover</button>`:''}</td></tr>`).join('')}
async function refreshCandidates(){const c=await api('/api/candidates');document.querySelector('#candidates').innerHTML=c.map(x=>`<div class="card"><b>${escapeHtml(x.version)}</b> <span class="pill ${x.status==='ready_with_warnings'?'warning':''}">${escapeHtml(x.status)}</span>${x.status==='ready_with_warnings'?'<p class="warning"><b>Advertencia:</b> el contenido pasó la validación offline, pero contiene recursos opcionales no disponibles.</p>':''}<br>${x.assets.map(a=>`<a href="/api/candidates/${x.id}/assets/${encodeURIComponent(a.name)}">${escapeHtml(a.name)}</a> (${compactBytes(a.size)})`).join('<br>')}<div class="build-controls"><b>Generar paquetes desde este candidato</b><div class="row"><label>Edición <select id="build-edition-${x.id}">${buildEditionOptions()}</select></label><label>Plataforma <select id="build-platform-${x.id}"><option value="linux">Linux — ZIP + DEB + RPM</option></select></label><button onclick="generateBuild(${x.id})">Generate builds</button></div><small>Se usará el archivo .tar.zst de ${escapeHtml(x.version)}, aunque el snapshot actual cambie después.</small></div><div class="row">${['ready_for_review','ready_with_warnings'].includes(x.status)?`<button onclick="candidateAction(${x.id},'publish','${x.status}')">${x.status==='ready_with_warnings'?'Publish with warnings':'Publish locally'}</button><button class="danger" onclick="candidateAction(${x.id},'reject','${x.status}')">Reject</button>`:''}<button class="danger" onclick="deleteCandidate(${x.id},'${escapeHtml(x.version)}')">Delete</button></div></div>`).join('')||'<small>No candidates yet.</small>'}
async function refreshBuilds(){const builds=await api('/api/builds');document.querySelector('#builds').innerHTML=builds.map((build,index)=>{if(build.legacy)return`<div class="card build-card"><div><b>Legacy build ${escapeHtml(build.id)}</b> <span class="pill">legacy</span></div><div>${(build.editions||[]).map(edition=>`<span class="edition-pill">${escapeHtml(edition)}</span>`).join('')}</div><div class="build-assets">${build.assets.map(asset=>`<a href="/api/builds/${encodeURIComponent(build.id)}/${encodeURIComponent(asset.name)}">${escapeHtml(asset.name)}</a> (${compactBytes(asset.size)})`).join('<br>')}</div></div>`;const directory=build.output_directory?.split('/').at(-1);const percent=build.progress_total?Math.round(build.progress_current/build.progress_total*100):0;const events=(build.events||[]).map(event=>`${event.created_at} [${event.level}] ${event.message}`).join('\n');return`<div class="card build-card ${index===0?'latest':''}"><div><b>Build #${build.id} · ${escapeHtml(build.version)}</b> <span class="pill ${build.status==='completed'?'ok':build.status==='failed'?'bad':''}">${escapeHtml(build.status)}</span> ${index===0?'<span class="pill ok">Más reciente</span>':''}</div><div class="build-meta"><span>Candidato: <b>#${build.candidate_id??'eliminado'}</b></span><span>Snapshot: <b>${escapeHtml(build.snapshot_id)}</b></span><span>Edición: <b>${escapeHtml(build.edition)}</b></span><span>Plataforma: <b>${escapeHtml(build.platform)}</b></span><span>Creado: <b>${escapeHtml(build.created_at)}</b></span><span>Progreso: <b>${build.progress_current}/${build.progress_total}</b></span></div><progress class="progressbar" max="100" value="${percent}"></progress>${build.error?`<p class="bad"><b>Error:</b> ${escapeHtml(build.error)}</p>`:''}<div class="build-assets">${directory&&build.assets.length?build.assets.map(asset=>`<a href="/api/builds/${encodeURIComponent(directory)}/${encodeURIComponent(asset.name)}">${escapeHtml(asset.name)}</a> (${compactBytes(asset.size)})`).join('<br>'):'<small>Los artefactos aparecerán al terminar.</small>'}</div><details ${['queued','building','failed'].includes(build.status)?'open':''}><summary>Logs y eventos</summary><div class="build-log">${escapeHtml(events||'Todavía no hay eventos.')}</div></details>${['completed','failed'].includes(build.status)?`<button class="secondary" onclick="rebuildBuild(${build.id})">Rebuild</button>`:''}</div>`}).join('')||'<small>Todavía no hay builds. Genéralos desde un candidato.</small>'}
async function refreshStorage(){const [s,space]=await Promise.all([api('/api/status'),api('/api/storage')]);document.querySelector('#storageSummary').innerHTML=`Uso físico real: <b>${compactBytes(space.physical_bytes)}</b> de ${bytes(s.storage_limit_bytes)}`;document.querySelector('#storageBreakdown').innerHTML=`<table><thead><tr><th>Categoría</th><th>Espacio asignado</th><th>Archivos</th></tr></thead><tbody>${Object.entries(space.categories).map(([name,value])=>`<tr><td>${name}</td><td>${compactBytes(value.allocated_bytes)}</td><td>${value.files}</td></tr>`).join('')}</tbody></table>`}
async function refreshAudit(){const audit=await api('/api/audit?limit=25');document.querySelector('#audit').textContent=audit.map(x=>`${x.created_at} ${x.actor} ${x.action} ${x.target||''}`).join('\\n')}
async function refreshCrawler(){const s=await api('/api/status');renderStatus(s);let activityId=selectedRunId||s.active_run?.id;if(!activityId){const r=await api('/api/runs');activityId=r[0]?.id}if(activityId){const activity=await api(`/api/runs/${activityId}`);if(selectedRunId===null||selectedRunId===activityId)renderActivity(activity)}}
async function refreshTab(name=activeTab){try{if(name==='overview')await refreshOverview();else if(name==='crawler')await refreshCrawler();else if(name==='runs')await refreshRuns();else if(name==='candidates')await refreshCandidates();else if(name==='builds')await refreshBuilds();else if(name==='storage')await refreshStorage();else if(name==='audit')await refreshAudit()}catch(e){console.error(`Unable to refresh ${name}:`,e);if(name==='overview')document.querySelector('#status').innerHTML=`<span class="bad">${e}</span>`}}
async function refresh(){return refreshTab(activeTab)}
async function manualRefresh(){if(manualRefreshRunning)return;manualRefreshRunning=true;const button=document.querySelector('#refreshButton');button.disabled=true;button.textContent='↻ Refreshing…';try{await refresh()}finally{manualRefreshRunning=false;button.disabled=false;button.textContent='↻ Refresh'}}
async function startRun(){try{const job=await api('/api/runs/sync',{method:'POST',body:JSON.stringify({profile:document.querySelector('#profile').value})});selectedRunId=job.run_id;showTab('crawler')}catch(e){alert(e)}}
async function controlRun(id,action){try{await api(`/api/runs/${id}/${action}`,{method:'POST'});selectedRunId=id;await refresh()}catch(e){alert(e)}}
async function cancelRun(id){if(!confirm(`¿Cancelar el run #${id}? Se conservará el snapshot aprobado anterior.`))return;try{await api(`/api/runs/${id}/cancel`,{method:'POST'});selectedRunId=id;await refresh()}catch(e){alert(e)}}
async function recoverRun(id){if(!confirm(`¿Recuperar el run #${id} desde los blobs locales? No volverá a descargar toda la wiki.`))return;try{const job=await api(`/api/runs/${id}/recover`,{method:'POST'});await detail(job.run_id)}catch(e){alert(e)}}
async function createCandidate(){try{await api('/api/candidates',{method:'POST',body:JSON.stringify({version:document.querySelector('#version').value})});refresh()}catch(e){alert(e)}}
async function generateBuild(candidateId){const edition=document.querySelector(`#build-edition-${candidateId}`).value;const platform=document.querySelector(`#build-platform-${candidateId}`).value;const description=edition==='all'?'la edición multilingüe y las 12 individuales':edition;if(!confirm(`¿Encolar ${description} para Linux desde este candidato?`))return;try{await api(`/api/candidates/${candidateId}/builds`,{method:'POST',body:JSON.stringify({edition,platform})});showTab('builds')}catch(e){alert(e)}}
async function rebuildBuild(jobId){if(!confirm(`¿Repetir exactamente el build #${jobId}? Se conservarán sus artefactos actuales.`))return;try{await api(`/api/builds/${jobId}/rebuild`,{method:'POST'});await refreshBuilds()}catch(e){alert(e)}}
async function candidateAction(id,action,status){const message=action==='publish'&&status==='ready_with_warnings'?'Este candidato pasó la validación offline, pero contiene recursos opcionales no disponibles. ¿Publicar localmente con advertencias?':`${action} candidate?`;if(!confirm(message))return;await api(`/api/candidates/${id}/${action}`,{method:'POST'});refresh()}
async function deleteCandidate(id,version){if(!confirm(`¿Eliminar ${version}? Esta acción borrará permanentemente sus archivos locales. El snapshot y GitHub no se modificarán.`))return;try{await api(`/api/candidates/${id}`,{method:'DELETE'});refresh()}catch(e){alert(e)}}
async function purgeStorage(target){const messages={cache:'Esto elimina temporales y blobs no referenciados. Los runs fallidos podrían dejar de ser recuperables. ¿Continuar?',builds:'Esto elimina ZIP, DEB y RPM generados localmente. Podrán reconstruirse. ¿Continuar?',old_snapshots:'Esto elimina todos los snapshots excepto el activo. No se puede deshacer. ¿Continuar?'};if(!confirm(messages[target]))return;try{const result=await api('/api/storage/purge',{method:'POST',body:JSON.stringify({target})});alert(`Purge complete: ${compactBytes(result.freed_bytes)} freed.`);refresh()}catch(e){alert(e)}}
function markSelectedRun(){document.querySelectorAll('[data-run-id]').forEach(row=>row.classList.toggle('selected-run',Number(row.dataset.runId)===selectedRunId));document.querySelectorAll('.run-link').forEach(link=>link.setAttribute('aria-current',String(Number(link.closest('[data-run-id]').dataset.runId)===selectedRunId)))}
async function detail(id){selectedRunId=id;markSelectedRun();showTab('crawler',false);document.querySelector('#activityTitle').textContent=`Run #${id} · cargando historial…`;document.querySelector('#activityState').textContent='loading';document.querySelector('#activityState').className='pill';try{const activity=await api(`/api/runs/${id}`);if(selectedRunId===id)renderActivity(activity)}catch(e){if(selectedRunId===id){document.querySelector('#activityState').textContent='error';document.querySelector('#activityState').className='pill bad';document.querySelector('#activity').innerHTML=`<p class="bad">No se pudo cargar el run #${id}: ${e}</p>`}}}
async function saveSettings(){const enabled_languages=[...document.querySelectorAll('[data-lang]:checked')].map(x=>x.dataset.lang);const page_concurrency=Number(document.querySelector('#pageConcurrency').value);await api('/api/settings',{method:'PUT',body:JSON.stringify({enabled:document.querySelector('#enabled').checked,enabled_languages,page_concurrency})});refresh()}
showTab(localStorage.getItem('updater.activeTab')||'overview');showProfileHelp();
</script></body></html>""".replace("__UPDATER_VERSION__", __version__)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD
