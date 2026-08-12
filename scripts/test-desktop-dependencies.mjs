import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const shellPath = path.join(root, 'desktop', 'shell.html');
const miniSearchPath = path.join(root, 'node_modules', 'minisearch', 'dist', 'umd', 'index.js');
const miniSearchReference = '../node_modules/minisearch/dist/umd/index.js';

const shell = fs.readFileSync(shellPath, 'utf8');
assert.match(shell, new RegExp(miniSearchReference.replaceAll('.', '\\.')));
assert.equal(
  fs.existsSync(miniSearchPath),
  true,
  `MiniSearch browser bundle is missing: ${miniSearchPath}. Run npm ci before testing.`,
);
