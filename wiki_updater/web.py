from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .candidates import candidate, create_candidate, delete_candidate, set_candidate_status
from .config import LANGUAGES, get_settings
from .database import Database
from .jobs import enqueue, request_cancel
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
            if not run or run["status"] not in {"queued", "running"}:
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
        "active_run": db.one("SELECT id,status,profile FROM runs WHERE status IN ('queued','running') ORDER BY id LIMIT 1"),
    }


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
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:24px}
h1,h2,h3{margin:.2rem 0 1rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
button,input,select{font:inherit;padding:9px 12px;border-radius:7px;border:1px solid var(--line);background:#0b1a2d;color:var(--text)}button{cursor:pointer;background:#1767a6}button.danger{background:#8f3030}button.secondary{background:#253d58}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#294563}.ok{color:var(--good)}.bad{color:var(--bad)}.warning{color:var(--warning)}.muted,small{color:var(--muted)}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid var(--line)}a{color:#6bbcff}pre{white-space:pre-wrap;max-height:320px;overflow:auto}.languages label{display:inline-flex;gap:4px;margin:4px}
details.help{margin-bottom:16px}details.help>summary{cursor:pointer;font-size:20px;font-weight:700;padding:4px}details.help[open]>summary{margin-bottom:16px}.help-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}.help-item{background:#0b1a2d;border:1px solid var(--line);border-radius:9px;padding:12px}.help-item h3{font-size:16px;margin-bottom:6px}.help-item p{margin:.35rem 0;color:#c4d5ea}.profile-help{min-height:42px;margin-top:12px;color:#c4d5ea}
.activity-head{display:flex;justify-content:space-between;gap:12px;align-items:start;flex-wrap:wrap}.progress-summary{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));gap:10px;margin:12px 0}.metric{background:#0b1a2d;border-radius:8px;padding:10px}.metric strong{display:block;font-size:20px}.progressbar{width:100%;height:14px;accent-color:var(--good)}.language-progress{font-variant-numeric:tabular-nums}.event-log{background:#07111f;border:1px solid var(--line);border-radius:8px;padding:10px;max-height:260px;overflow:auto}.event-line{padding:5px 0;border-bottom:1px solid #1d3551}.event-line:last-child{border:0}@media(max-width:700px){.progress-summary{grid-template-columns:repeat(2,1fr)}main{padding:14px}}
.topbar{display:flex;justify-content:space-between;align-items:start;gap:16px}.crawler-version{white-space:nowrap;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:5px 10px}
</style></head><body><main>
<div class="topbar"><div><h1>Offline Stardew Valley Wiki Updater</h1><p>Local-first synchronization, validation and release candidates.</p></div><span class="crawler-version">Crawler v__UPDATER_VERSION__</span></div>
<section class="card"><b>This is the updater, not the wiki reader.</b> It downloads and validates content. To open the desktop wiki, run <code>npm start</code> on the host from the repository directory.</section>
<details class="card help" open><summary>Ayuda: cómo usar esta aplicación</summary>
<div class="help-grid">
<div class="help-item"><h3>1. fixture — prueba sin Internet</h3><p>Genera dos páginas artificiales por idioma. Sirve para comprobar Podman, SQLite, jobs y validación. <b>No descarga la wiki real.</b></p></div>
<div class="help-item"><h3>2. sample — prueba rápida real</h3><p>Descarga la portada y unas 24 páginas adicionales por idioma. Úsalo para revisar diseño, imágenes, enlaces, búsqueda y los 12 idiomas antes de una descarga completa.</p></div>
<div class="help-item"><h3>3. incremental — actualización habitual</h3><p>Compara revisiones de MediaWiki contra el snapshot actual. Sólo vuelve a procesar páginas nuevas o modificadas y elimina las borradas. Conviene usarlo después de tener un snapshot <code>full</code>.</p></div>
<div class="help-item"><h3>4. full — reconciliación completa</h3><p>Enumera y descarga todas las páginas de los idiomas habilitados. Es el proceso más lento y el que más espacio utiliza. Comprueba que el mirror coincida con MediaWiki.</p></div>
<div class="help-item"><h3>Scheduler, idiomas y velocidad</h3><p><b>Enabled</b> permite la ejecución automática. <b>Parallel pages</b> controla cuántas páginas se preparan a la vez. El límite hacia la wiki siempre permanece en dos requests simultáneos.</p></div>
<div class="help-item"><h3>Create candidate</h3><p>Congela el snapshot aprobado en una versión, genera manifiesto, checksums y archivos descargables. Hazlo únicamente después de revisar el resultado local. No publica en GitHub por sí solo.</p></div>
<div class="help-item"><h3>Recover failed full</h3><p>Si todas las páginas terminaron y sólo fallaron recursos opcionales, <b>Recover</b> reconstruye el snapshot desde los blobs locales y vuelve a validarlo sin descargar toda la wiki. El candidato quedará marcado con advertencias.</p></div>
<div class="help-item"><h3>Runs, Candidates y Audit</h3><p><b>Runs</b> conserva cada intento. Pulsa su ID para inspeccionarlo. <b>Candidates</b> contiene artefactos de revisión. <b>Audit</b> registra quién ejecutó o cambió algo.</p></div>
<div class="help-item"><h3>Abrir la wiki</h3><p>Este panel sólo administra el crawler. Abre el lector desde el host con <code>env -u ELECTRON_RUN_AS_NODE npm start</code>. El contenido se lee desde <code>.local-data</code>.</p></div>
</div></details>
<div class="grid"><section class="card"><h2>Status</h2><div id="status">Loading…</div></section>
<section class="card"><h2>Run synchronization</h2><div class="row"><select id="profile" onchange="showProfileHelp()"><option>fixture</option><option>sample</option><option>incremental</option><option>full</option></select><button onclick="startRun()">Start</button></div><div id="profileHelp" class="profile-help"></div><p><small>Sólo puede existir una ejecución activa. Puedes cancelarla desde Runs.</small></p></section>
<section class="card"><h2>Create candidate</h2><div class="row"><input id="version" value="v1.3.0" pattern="v?[0-9]+\\.[0-9]+\\.[0-9]+"><button onclick="createCandidate()">Create</button></div></section></div>
<section class="card"><h2>Scheduler and languages</h2><div class="row"><label><input type="checkbox" id="enabled"> Enabled</label><label>Parallel pages <select id="pageConcurrency"><option value="1">1 — Sequential</option><option value="2">2 — Balanced</option><option value="4">4 — Fast local</option></select></label><button class="secondary" onclick="saveSettings()">Save</button></div><p><small>Se aplica al siguiente job. Incluso en modo 4, nunca se hacen más de 2 requests simultáneos hacia la wiki.</small></p><div class="languages" id="languages"></div></section>
<section class="card"><div class="activity-head"><div><h2>Actividad del crawler</h2><div id="activityTitle" class="muted">Esperando datos…</div></div><span id="activityState" class="pill">idle</span></div><div id="activity"><p class="muted">Selecciona un Run o inicia una sincronización.</p></div></section>
<section class="card"><h2>Runs</h2><p><small>Pulsa un ID para mostrar su progreso e historial en “Actividad del crawler”.</small></p><div style="overflow:auto"><table><thead><tr><th>ID</th><th>Profile</th><th>Status</th><th>Created</th><th>Snapshot</th><th></th></tr></thead><tbody id="runs"></tbody></table></div></section>
<section class="card"><h2>Candidates</h2><div id="candidates"></div></section>
<section class="card"><h2>Audit history</h2><pre id="audit"></pre></section>
</main><script>
const langs=['en','es','de','fr','it','ja','ko','hu','pt','ru','tr','zh'];
const profileDescriptions={fixture:'Prueba controlada sin Internet: 2 páginas artificiales por idioma.',sample:'Prueba real rápida: portada + aproximadamente 24 páginas por idioma.',incremental:'Compara revisiones y procesa sólo cambios respecto al snapshot actual.',full:'Descarga y reconcilia todas las páginas de los idiomas habilitados.'};
let selectedRunId=null;
async function api(url,options={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...options});if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json()}
function bytes(v){return(v/1024/1024/1024).toFixed(2)+' GiB'}
function compactBytes(v){if(v>=1073741824)return(v/1073741824).toFixed(2)+' GiB';if(v>=1048576)return(v/1048576).toFixed(1)+' MiB';if(v>=1024)return(v/1024).toFixed(1)+' KiB';return v+' B'}
function showProfileHelp(){document.querySelector('#profileHelp').textContent=profileDescriptions[document.querySelector('#profile').value]}
function renderActivity(x){const ls=x.languages||[];const total=ls.reduce((n,l)=>n+l.pages_total,0);const written=ls.reduce((n,l)=>n+l.pages_written,0);const assets=ls.reduce((n,l)=>n+l.assets_written,0);const size=ls.reduce((n,l)=>n+l.bytes_written,0);const percent=total?Math.round(written/total*100):0;const last=x.events?.at(-1);document.querySelector('#activityTitle').textContent=`Run #${x.id} · ${x.profile} · ${last?.message||'sin eventos'}`;document.querySelector('#activityState').textContent=x.status;document.querySelector('#activityState').className=`pill ${x.status==='completed'?'ok':x.status==='completed_with_warnings'?'warning':x.status==='failed'?'bad':''}`;
document.querySelector('#activity').innerHTML=`<div class="progress-summary"><div class="metric"><small>Progreso</small><strong>${percent}%</strong></div><div class="metric"><small>Páginas procesadas</small><strong>${written} / ${total||'?'}</strong></div><div class="metric"><small>Assets nuevos</small><strong>${assets}</strong></div><div class="metric"><small>Datos escritos</small><strong>${compactBytes(size)}</strong></div></div><progress class="progressbar" max="100" value="${percent}"></progress>${x.error?`<p class="bad"><b>Error:</b> ${x.error}</p>`:''}<div style="overflow:auto"><table class="language-progress"><thead><tr><th>Idioma</th><th>Estado</th><th>Páginas</th><th>Assets</th><th>Datos</th><th>Revisión final</th></tr></thead><tbody>${ls.map(l=>`<tr><td>${l.language}</td><td>${l.status}</td><td>${l.pages_written}/${l.pages_total}</td><td>${l.assets_written}</td><td>${compactBytes(l.bytes_written)}</td><td>${l.revision_end||'—'}</td></tr>`).join('')||'<tr><td colspan="6">Enumerando páginas mediante la API de MediaWiki…</td></tr>'}</tbody></table></div><h3>Eventos recientes</h3><div class="event-log">${(x.events||[]).slice(-30).reverse().map(e=>`<div class="event-line"><small>${new Date(e.created_at).toLocaleString()}</small> <span class="${e.level==='error'?'bad':''}">[${e.level}] ${e.message}</span></div>`).join('')||'<span class="muted">Todavía no hay eventos.</span>'}</div>`}
async function refresh(){try{const [s,r,c,conf,audit]=await Promise.all([api('/api/status'),api('/api/runs'),api('/api/candidates'),api('/api/settings'),api('/api/audit?limit=25')]);
document.querySelector('#status').innerHTML=`Environment: <b>${s.environment}</b><br>Storage: ${bytes(s.storage_used_bytes)} / ${bytes(s.storage_limit_bytes)}<br>Snapshot: ${s.current?.snapshot_id||'none'}<br>Active: ${s.active_run?.id||'none'}`;
document.querySelector('#enabled').checked=conf.enabled;document.querySelector('#pageConcurrency').value=String(conf.page_concurrency);document.querySelector('#languages').innerHTML=langs.map(l=>`<label><input type="checkbox" data-lang="${l}" ${conf.enabled_languages.includes(l)?'checked':''}>${l}</label>`).join('');
document.querySelector('#runs').innerHTML=r.map(x=>`<tr><td><a href="#" onclick="detail(${x.id});return false">${x.id}</a></td><td>${x.profile}</td><td>${x.status}</td><td>${x.created_at}</td><td>${x.snapshot_id||''}</td><td>${['queued','running'].includes(x.status)?`<button class="danger" onclick="cancelRun(${x.id})">Cancel</button>`:x.recoverable?`<button class="secondary" onclick="recoverRun(${x.id})">Recover</button>`:''}</td></tr>`).join('');
document.querySelector('#candidates').innerHTML=c.map(x=>`<div class="card"><b>${x.version}</b> <span class="pill ${x.status==='ready_with_warnings'?'warning':''}">${x.status}</span>${x.status==='ready_with_warnings'?'<p class="warning"><b>Advertencia:</b> el contenido pasó la validación offline, pero algunos recursos originales no estuvieron disponibles.</p>':''}<br>${x.assets.map(a=>`<a href="/api/candidates/${x.id}/assets/${encodeURIComponent(a.name)}">${a.name}</a> (${(a.size/1024/1024).toFixed(1)} MiB)`).join('<br>')}<div class="row">${['ready_for_review','ready_with_warnings'].includes(x.status)?`<button onclick="candidateAction(${x.id},'publish','${x.status}')">${x.status==='ready_with_warnings'?'Publish with warnings':'Publish locally'}</button><button class="danger" onclick="candidateAction(${x.id},'reject','${x.status}')">Reject</button>`:''}<button class="danger" onclick="deleteCandidate(${x.id},'${x.version}')">Delete</button></div></div>`).join('')||'<small>No candidates yet.</small>';
document.querySelector('#audit').textContent=audit.map(x=>`${x.created_at} ${x.actor} ${x.action} ${x.target||''}`).join('\\n');
const activityId=s.active_run?.id||selectedRunId||r[0]?.id;if(activityId)renderActivity(await api(`/api/runs/${activityId}`));
}catch(e){document.querySelector('#status').innerHTML=`<span class="bad">${e}</span>`}}
async function startRun(){try{await api('/api/runs/sync',{method:'POST',body:JSON.stringify({profile:document.querySelector('#profile').value})});refresh()}catch(e){alert(e)}}
async function cancelRun(id){await api(`/api/runs/${id}/cancel`,{method:'POST'});refresh()}
async function recoverRun(id){if(!confirm(`¿Recuperar el run #${id} desde los blobs locales? No volverá a descargar toda la wiki.`))return;try{await api(`/api/runs/${id}/recover`,{method:'POST'});refresh()}catch(e){alert(e)}}
async function createCandidate(){try{await api('/api/candidates',{method:'POST',body:JSON.stringify({version:document.querySelector('#version').value})});refresh()}catch(e){alert(e)}}
async function candidateAction(id,action,status){const message=action==='publish'&&status==='ready_with_warnings'?'Este candidato pasó la validación offline, pero contiene recursos opcionales no disponibles. ¿Publicar localmente con advertencias?':`${action} candidate?`;if(!confirm(message))return;await api(`/api/candidates/${id}/${action}`,{method:'POST'});refresh()}
async function deleteCandidate(id,version){if(!confirm(`¿Eliminar ${version}? Esta acción borrará permanentemente sus archivos locales. El snapshot y GitHub no se modificarán.`))return;try{await api(`/api/candidates/${id}`,{method:'DELETE'});refresh()}catch(e){alert(e)}}
async function detail(id){selectedRunId=id;renderActivity(await api(`/api/runs/${id}`));document.querySelector('#activityTitle').scrollIntoView({behavior:'smooth',block:'center'})}
async function saveSettings(){const enabled_languages=[...document.querySelectorAll('[data-lang]:checked')].map(x=>x.dataset.lang);const page_concurrency=Number(document.querySelector('#pageConcurrency').value);await api('/api/settings',{method:'PUT',body:JSON.stringify({enabled:document.querySelector('#enabled').checked,enabled_languages,page_concurrency})});refresh()}
showProfileHelp();refresh();setInterval(refresh,3000);
</script></body></html>""".replace("__UPDATER_VERSION__", __version__)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD
