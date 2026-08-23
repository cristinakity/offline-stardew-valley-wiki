const fs = require('node:fs');
const https = require('node:https');
const path = require('node:path');
const { Worker } = require('node:worker_threads');

const LANGUAGE_PATTERN = /^[a-z]{2}$/;

function readJson(target, fallback = null) {
  try { return JSON.parse(fs.readFileSync(target, 'utf8')); } catch { return fallback; }
}

function fetchJson(url, redirects = 0) {
  if (redirects > 5) return Promise.reject(new Error('Too many update redirects.'));
  return new Promise((resolve, reject) => {
    const request = https.get(url, { headers: { 'User-Agent': 'OfflineStardewValleyWiki/1.3' } }, response => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode) && response.headers.location) {
        response.resume();
        fetchJson(new URL(response.headers.location, url).href, redirects + 1).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`Content update check failed with HTTP ${response.statusCode}.`));
        return;
      }
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 1024 * 1024) response.destroy(new Error('Content manifest is too large.'));
      });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch { reject(new Error('Content update manifest is invalid.')); }
      });
    });
    request.on('error', reject);
  });
}

function validRemoteManifest(manifest) {
  try {
    const download = new URL(manifest.download_url);
    const latest = new URL(manifest.latest_manifest_url);
    return manifest.schema === 1
      && /^[A-Za-z0-9._-]+$/.test(manifest.version)
      && /^[A-Za-z0-9._-]+$/.test(manifest.snapshot_id)
      && manifest.archive_name === path.basename(manifest.archive_name)
      && manifest.archive_name.endsWith('.tar.zst')
      && /^[0-9a-f]{64}$/.test(manifest.archive_sha256)
      && Number.isSafeInteger(manifest.archive_bytes) && manifest.archive_bytes > 0
      && Number.isSafeInteger(manifest.required_free_bytes) && manifest.required_free_bytes > 0
      && Array.isArray(manifest.languages) && manifest.languages.length > 0
      && manifest.languages.every(language => LANGUAGE_PATTERN.test(language))
      && download.protocol === 'https:' && download.hostname === 'github.com'
      && download.pathname.startsWith('/cristinakity/offline-stardew-valley-wiki/releases/download/')
      && latest.protocol === 'https:' && latest.hostname === 'github.com'
      && latest.pathname === '/cristinakity/offline-stardew-valley-wiki/releases/latest/download/content-release.json';
  } catch { return false; }
}

class ContentManager {
  constructor({ userData, resourcesPath, appPath, packaged, onProgress }) {
    this.root = path.join(userData, 'wiki-content');
    this.statePath = path.join(this.root, 'state.json');
    this.manifestPath = packaged
      ? path.join(resourcesPath, 'content-release.json')
      : path.join(__dirname, 'content-release.json');
    this.manifest = readJson(this.manifestPath);
    if (!validRemoteManifest(this.manifest)) throw new Error('Invalid bundled content manifest.');
    this.onProgress = onProgress;
    this.appPath = appPath || path.join(__dirname, '..');
    this.workerPath = packaged ? path.join(resourcesPath, 'content-worker.js') : path.join(__dirname, 'content-worker.js');
    this.editionModule = packaged ? path.join(resourcesPath, 'prepare-edition.mjs') : path.join(__dirname, '..', 'scripts', 'prepare-edition.mjs');
    this.worker = null;
    this.control = null;
    this.terminalReceived = false;
  }

  state() { return readJson(this.statePath); }

  contentRoot() {
    const state = this.state();
    if (!state?.directory) return '';
    const target = path.resolve(this.root, state.directory, 'content');
    const relative = path.relative(this.root, target);
    return relative && !relative.startsWith('..') && fs.existsSync(target) ? target : '';
  }

  status() {
    fs.mkdirSync(this.root, { recursive: true });
    const state = this.state();
    const archive = path.join(this.root, 'downloads', this.manifest.archive_name);
    let freeBytes = null;
    try { freeBytes = fs.statfsSync(this.root).bavail * fs.statfsSync(this.root).bsize; } catch {}
    return {
      manifest: this.manifest,
      installed: Boolean(this.contentRoot()),
      installedLanguages: state?.languages || [],
      installedVersion: state?.version || (state?.snapshot_id === this.manifest.snapshot_id ? this.manifest.version : null),
      installedSnapshotId: state?.snapshot_id || null,
      installedAt: state?.installed_at || null,
      archiveRetained: fs.existsSync(archive),
      freeBytes,
      busy: Boolean(this.worker),
    };
  }

  async checkForUpdates() {
    if (this.worker) throw new Error('Wait for the current content operation to finish.');
    const remote = await fetchJson(this.manifest.latest_manifest_url);
    if (!validRemoteManifest(remote)) throw new Error('The published content manifest failed validation.');
    const current = this.state()?.snapshot_id || null;
    const updateAvailable = current !== remote.snapshot_id;
    if (updateAvailable) this.manifest = remote;
    return { updateAvailable, currentSnapshotId: current, availableSnapshotId: remote.snapshot_id };
  }

  start({ languages, archivePath = null, retainArchive = false }) {
    if (this.worker) throw new Error('A content operation is already running.');
    const selected = [...new Set(languages || [])].sort();
    if (!selected.length || selected.some(code => !LANGUAGE_PATTERN.test(code) || !this.manifest.languages.includes(code))) {
      throw new Error('Select at least one supported language.');
    }
    fs.mkdirSync(this.root, { recursive: true });
    const disk = fs.statfsSync(this.root);
    if (disk.bavail * disk.bsize < this.manifest.required_free_bytes) {
      throw new Error('There is not enough temporary disk space to install this snapshot.');
    }
    this.control = new Int32Array(new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT * 2));
    this.terminalReceived = false;
    this.worker = new Worker(this.workerPath, {
      workerData: {
        root: this.root,
        manifest: this.manifest,
        languages: selected,
        archivePath,
        retainArchive,
        controlBuffer: this.control.buffer,
        editionModule: this.editionModule,
        appPath: this.appPath,
      },
    });
    this.worker.on('message', message => {
      if (['completed', 'cancelled', 'failed'].includes(message.phase)) this.terminalReceived = true;
      this.onProgress?.(message);
    });
    this.worker.on('error', error => {
      this.terminalReceived = true;
      this.onProgress?.({ phase: 'failed', error: error.message });
    });
    this.worker.on('exit', code => {
      if (code && code !== 0 && !this.terminalReceived) {
        this.onProgress?.({ phase: 'failed', error: `Content worker exited with code ${code}.` });
      }
      this.worker = null;
      this.control = null;
      this.terminalReceived = false;
    });
    return { started: true, languages: selected };
  }

  pause() {
    if (!this.control) return false;
    Atomics.store(this.control, 1, 1);
    return true;
  }

  resume() {
    if (!this.control) return false;
    Atomics.store(this.control, 1, 0);
    Atomics.notify(this.control, 1);
    return true;
  }

  cancel() {
    if (!this.control) return false;
    Atomics.store(this.control, 0, 1);
    Atomics.store(this.control, 1, 0);
    Atomics.notify(this.control, 1);
    return true;
  }
}

module.exports = { ContentManager };
