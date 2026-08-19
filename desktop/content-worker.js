const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const https = require('node:https');
const path = require('node:path');
const { Transform } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');
const { createZstdDecompress } = require('node:zlib');
const { parentPort, workerData } = require('node:worker_threads');
const tar = createRequire(path.join(workerData.appPath, 'package.json'))('tar');

const control = new Int32Array(workerData.controlBuffer);
const post = value => parentPort.postMessage(value);

function checkpoint() {
  if (Atomics.load(control, 0)) throw new Error('Installation cancelled.');
  while (Atomics.load(control, 1)) {
    post({ phase: 'paused' });
    Atomics.wait(control, 1, 1, 500);
    if (Atomics.load(control, 0)) throw new Error('Installation cancelled.');
  }
}

function request(url, headers = {}, redirects = 0) {
  if (redirects > 8) return Promise.reject(new Error('Too many download redirects.'));
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https:') ? https : http;
    const req = client.get(url, { headers: { 'User-Agent': 'OfflineStardewValleyWiki/1.3', ...headers } }, response => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode) && response.headers.location) {
        response.resume();
        request(new URL(response.headers.location, url).href, headers, redirects + 1).then(resolve, reject);
        return;
      }
      resolve(response);
    });
    req.on('error', reject);
  });
}

async function download(url, target, expectedBytes) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  let existing = fs.statSync(target, { throwIfNoEntry: false })?.size || 0;
  if (existing > expectedBytes) { fs.rmSync(target); existing = 0; }
  if (existing === expectedBytes) {
    post({ phase: 'downloading', current: existing, total: expectedBytes });
    return;
  }
  checkpoint();
  const response = await request(url, existing ? { Range: `bytes=${existing}-` } : {});
  if (![200, 206].includes(response.statusCode)) throw new Error(`Download failed with HTTP ${response.statusCode}.`);
  if (existing && response.statusCode === 200) { fs.rmSync(target, { force: true }); existing = 0; }
  let current = existing;
  const progress = new Transform({
    transform(chunk, _encoding, callback) {
      try {
        checkpoint();
        current += chunk.length;
        post({ phase: 'downloading', current, total: expectedBytes });
        callback(null, chunk);
      } catch (error) { callback(error); }
    },
  });
  await pipeline(response, progress, fs.createWriteStream(target, { flags: existing ? 'a' : 'w' }));
  if (current !== expectedBytes) throw new Error(`Downloaded ${current} bytes; expected ${expectedBytes}.`);
}

async function sha256(target) {
  const total = fs.statSync(target).size;
  let current = 0;
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(target)) {
    checkpoint();
    hash.update(chunk);
    current += chunk.length;
    post({ phase: 'verifying', current, total });
  }
  return hash.digest('hex');
}

async function extract(archive, target) {
  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(target, { recursive: true });
  const total = fs.statSync(archive).size;
  let current = 0;
  const progress = new Transform({
    transform(chunk, _encoding, callback) {
      try {
        checkpoint();
        current += chunk.length;
        post({ phase: 'extracting', current, total });
        callback(null, chunk);
      } catch (error) { callback(error); }
    },
  });
  await pipeline(
    fs.createReadStream(archive),
    progress,
    createZstdDecompress(),
    tar.x({ cwd: target, strict: true, preservePaths: false }),
  );
}

function atomicJson(target, value) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, target);
}

async function run() {
  const { root, manifest, languages, retainArchive } = workerData;
  fs.mkdirSync(root, { recursive: true });
  const downloads = path.join(root, 'downloads');
  const retained = path.join(downloads, manifest.archive_name);
  const partial = `${retained}.part`;
  let archive = workerData.archivePath ? path.resolve(workerData.archivePath) : retained;
  if (!workerData.archivePath && !fs.existsSync(retained)) {
    await download(process.env.WIKI_CONTENT_URL || manifest.download_url, partial, manifest.archive_bytes);
    fs.renameSync(partial, retained);
  }
  checkpoint();
  const actualHash = await sha256(archive);
  if (actualHash !== manifest.archive_sha256) {
    if (!workerData.archivePath) fs.rmSync(archive, { force: true });
    throw new Error('The snapshot checksum does not match the approved release.');
  }
  const work = path.join(root, 'staging');
  const source = path.join(work, 'source');
  const selected = path.join(work, 'selected', 'content');
  await extract(archive, source);
  const sourceContent = path.join(source, 'content');
  if (!fs.statSync(sourceContent, { throwIfNoEntry: false })?.isDirectory()) throw new Error('Snapshot content directory is missing.');
  const { prepareEdition } = await import(pathToFileURL(workerData.editionModule).href);
  const edition = prepareEdition(sourceContent, selected, languages.join(','), {
    control: checkpoint,
    onProgress: progress => post(progress),
  });
  checkpoint();
  for (const language of languages) {
    if (!fs.existsSync(path.join(selected, language, 'pages')) || !fs.existsSync(path.join(selected, 'search', `${language}.json`))) {
      throw new Error(`Installed content validation failed for ${language}.`);
    }
  }
  const directory = path.join('versions', `${manifest.snapshot_id}-${languages.join('-')}`);
  const destination = path.join(root, directory);
  fs.rmSync(destination, { recursive: true, force: true });
  fs.mkdirSync(destination, { recursive: true });
  fs.renameSync(selected, path.join(destination, 'content'));
  let previous = null;
  try { previous = JSON.parse(fs.readFileSync(path.join(root, 'state.json'), 'utf8')); } catch {}
  atomicJson(path.join(root, 'state.json'), {
    schema: 1,
    snapshot_id: manifest.snapshot_id,
    version: manifest.version,
    languages,
    directory,
    installed_at: new Date().toISOString(),
    edition,
  });
  if (previous?.directory && previous.directory !== directory) {
    const old = path.resolve(root, previous.directory);
    if (path.relative(root, old) && !path.relative(root, old).startsWith('..')) fs.rmSync(old, { recursive: true, force: true });
  }
  fs.rmSync(work, { recursive: true, force: true });
  if (!retainArchive && archive === retained) fs.rmSync(retained, { force: true });
  post({ phase: 'completed', languages, edition });
}

run().catch(error => {
  post({ phase: Atomics.load(control, 0) ? 'cancelled' : 'failed', error: error.message });
});
