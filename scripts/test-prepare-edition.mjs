import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'wiki-edition-test-'));
const source = path.join(temporary, 'source', 'content');
const target = path.join(temporary, 'target', 'content');
const cssHash = `${'a'.repeat(64)}.css`;
const imageHash = `${'b'.repeat(64)}.png`;
const fontHash = `${'c'.repeat(64)}.woff2`;

try {
  for (const language of ['en', 'es']) {
    fs.mkdirSync(path.join(source, language, 'pages'), { recursive: true });
    fs.mkdirSync(path.join(source, 'search'), { recursive: true });
    fs.writeFileSync(
      path.join(source, language, 'pages', '1.html'),
      `<link href="../../assets/aa/${cssHash}"><img src="../../assets/bb/${imageHash}"><a href="../../es/pages/1.html#section" title="Inicio (Español)">ES</a>`,
    );
    fs.writeFileSync(path.join(source, 'search', `${language}.json`), '[]\n');
  }
  fs.mkdirSync(path.join(source, 'assets', 'aa'), { recursive: true });
  fs.mkdirSync(path.join(source, 'assets', 'bb'), { recursive: true });
  fs.mkdirSync(path.join(source, 'assets', 'cc'), { recursive: true });
  fs.writeFileSync(path.join(source, 'assets', 'aa', cssHash), `url(../cc/${fontHash})`);
  fs.writeFileSync(path.join(source, 'assets', 'bb', imageHash), 'image');
  fs.writeFileSync(path.join(source, 'assets', 'cc', fontHash), 'font');
  fs.writeFileSync(path.join(source, 'offline.css'), 'body{}');
  fs.writeFileSync(path.join(source, 'translations.json'), JSON.stringify({
    schema: 1,
    pages: { en: { 1: { es: 1 } }, es: { 1: { en: 1 } } },
    navigation: {
      en: { home: 1, pages: [[1, 'Home']] },
      es: { home: 1, pages: [[1, 'Inicio']] },
    },
  }));

  const result = spawnSync(
    process.execPath,
    ['scripts/prepare-edition.mjs', source, target, 'en'],
    { cwd: path.resolve(import.meta.dirname, '..'), encoding: 'utf8' },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.existsSync(path.join(target, 'en', 'pages', '1.html')), true);
  assert.equal(fs.existsSync(path.join(target, 'es')), false);
  assert.equal(fs.existsSync(path.join(target, 'search', 'en.json')), true);
  assert.equal(fs.existsSync(path.join(target, 'search', 'es.json')), false);
  assert.equal(fs.existsSync(path.join(target, 'assets', 'aa', cssHash)), true);
  assert.equal(fs.existsSync(path.join(target, 'assets', 'bb', imageHash)), true);
  assert.equal(fs.existsSync(path.join(target, 'assets', 'cc', fontHash)), true);
  const englishPage = fs.readFileSync(path.join(target, 'en', 'pages', '1.html'), 'utf8');
  assert.match(englishPage, /data-missing-local-language="es"/u);
  assert.match(englishPage, /data-offline-link-status="excluded"/u);
  assert.doesNotMatch(englishPage, /\.\.\/\.\.\/es\/pages/u);
  const translations = JSON.parse(fs.readFileSync(path.join(target, 'translations.json'), 'utf8'));
  assert.deepEqual(Object.keys(translations.navigation), ['en']);
  assert.deepEqual(translations.pages, { en: {} });
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(target, 'edition.json'), 'utf8')).languages, ['en']);
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
