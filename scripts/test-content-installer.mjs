import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { createZstdCompress } from 'node:zlib';
import * as tar from 'tar';
import contentManagerModule from '../desktop/content-manager.js';

const { ContentManager } = contentManagerModule;
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'wiki-content-installer-test-'));
const archive = path.join(temporary, 'fixture.tar.zst');
const source = path.join(temporary, 'archive', 'content');
const assetName = `${'a'.repeat(64)}.txt`;

try {
  for (const language of ['en', 'es']) {
    fs.mkdirSync(path.join(source, language, 'pages'), { recursive: true });
    fs.mkdirSync(path.join(source, 'search'), { recursive: true });
    fs.writeFileSync(path.join(source, language, 'pages', '1.html'), `<p>${language}</p><a href="../../assets/aa/${assetName}">asset</a>`);
    fs.writeFileSync(path.join(source, 'search', `${language}.json`), '[]\n');
  }
  fs.mkdirSync(path.join(source, 'assets', 'aa'), { recursive: true });
  fs.writeFileSync(path.join(source, 'assets', 'aa', assetName), 'approved asset');
  fs.writeFileSync(path.join(source, 'offline.css'), 'body{}');
  fs.writeFileSync(path.join(source, 'translations.json'), JSON.stringify({ schema: 1, pages: {}, navigation: {} }));
  await pipeline(
    tar.c({ cwd: path.dirname(source) }, ['content']),
    createZstdCompress(),
    fs.createWriteStream(archive),
  );
  const bytes = fs.readFileSync(archive);
  const hash = crypto.createHash('sha256').update(bytes).digest('hex');
  const completed = new Promise((resolve, reject) => {
    const manager = new ContentManager({
      userData: path.join(temporary, 'user-data'),
      resourcesPath: temporary,
      packaged: false,
      onProgress: progress => {
        if (progress.phase === 'completed') resolve(manager);
        if (progress.phase === 'failed') reject(new Error(progress.error));
      },
    });
    manager.manifest = {
      schema: 1,
      version: 'test',
      snapshot_id: 'fixture',
      archive_name: 'fixture.tar.zst',
      archive_sha256: hash,
      archive_bytes: bytes.length,
      download_url: 'https://example.invalid/fixture.tar.zst',
      required_free_bytes: 1,
      languages: ['en', 'es'],
    };
    manager.start({ languages: ['es'], archivePath: archive, retainArchive: false });
  });
  const manager = await completed;
  const installed = manager.contentRoot();
  assert.equal(fs.existsSync(path.join(installed, 'es', 'pages', '1.html')), true);
  assert.equal(fs.existsSync(path.join(installed, 'en')), false);
  assert.equal(fs.existsSync(path.join(installed, 'assets', 'aa', assetName)), true);
  assert.deepEqual(manager.state().languages, ['es']);
  assert.equal(manager.status().archiveRetained, false);
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
