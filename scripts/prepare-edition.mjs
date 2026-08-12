#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const supportedLanguages = new Set(['en', 'es', 'de', 'fr', 'it', 'ja', 'ko', 'hu', 'pt', 'ru', 'tr', 'zh']);
const assetPattern = /(?:assets\/|\.\.\/)([0-9a-f]{2}\/([0-9a-f]{64}\.[a-z0-9]+))/giu;

function fail(message) {
  console.error(message);
  process.exit(1);
}

function usage() {
  fail('Usage: node scripts/prepare-edition.mjs <source-content> <target-content> <language[,language...]>');
}

function safeTarget(source, target) {
  const resolvedSource = path.resolve(source);
  const resolvedTarget = path.resolve(target);
  const root = path.parse(resolvedTarget).root;
  if (resolvedSource === resolvedTarget || resolvedTarget === root || resolvedTarget.split(path.sep).length < 4) {
    fail(`Refusing unsafe edition target: ${resolvedTarget}`);
  }
  return resolvedTarget;
}

function linkOrCopy(source, target) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  try {
    fs.linkSync(source, target);
  } catch (error) {
    if (!['EXDEV', 'EPERM', 'EACCES', 'EMLINK'].includes(error.code)) throw error;
    fs.copyFileSync(source, target);
  }
}

function escapeAttribute(value) {
  return value.replaceAll('"', '&quot;');
}

function rewriteUnavailableLanguages(html, selectedLanguages) {
  const localPageHref = /\bhref=(["'])\.\.\/\.\.\/([a-z]{2})\/pages\/\d+\.html(?:[?#][^"']*)?\1/iu;
  return html.replace(/<a\b[^>]*>/giu, tag => {
    const target = tag.match(localPageHref);
    if (!target || selectedLanguages.has(target[2].toLowerCase())) return tag;
    const language = target[2].toLowerCase();
    const titleMatch = tag.match(/\btitle=(["'])(.*?)\1/iu);
    const title = escapeAttribute(titleMatch?.[2] || `${language.toUpperCase()} translation`);
    return tag
      .replace(localPageHref, 'href="#"')
      .replace(/>$/u, ` data-missing-local-language="${language}" data-missing-local-title="${title}" data-offline-link-status="excluded">`);
  });
}

function copyPages(source, target, selectedLanguages, visit) {
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name);
    const targetPath = path.join(target, entry.name);
    if (entry.isDirectory()) copyPages(sourcePath, targetPath, selectedLanguages, visit);
    if (entry.isFile()) {
      const contents = rewriteUnavailableLanguages(fs.readFileSync(sourcePath, 'utf8'), selectedLanguages);
      fs.mkdirSync(path.dirname(targetPath), { recursive: true });
      fs.writeFileSync(targetPath, contents);
      const sourceTimes = fs.statSync(sourcePath);
      fs.utimesSync(targetPath, sourceTimes.atime, sourceTimes.mtime);
      visit?.(contents);
    }
  }
}

function assetReferences(text) {
  return [...text.matchAll(assetPattern)].map(match => match[1].toLowerCase());
}

const [sourceArgument, targetArgument, languageArgument] = process.argv.slice(2);
if (!sourceArgument || !targetArgument || !languageArgument) usage();

const source = path.resolve(sourceArgument);
const target = safeTarget(source, targetArgument);
const languages = [...new Set(languageArgument.split(',').map(value => value.trim().toLowerCase()).filter(Boolean))].sort();
if (!languages.length || languages.some(language => !supportedLanguages.has(language))) {
  fail(`Unsupported language list: ${languageArgument}`);
}
if (!fs.statSync(source, { throwIfNoEntry: false })?.isDirectory()) fail(`Source content does not exist: ${source}`);

for (const language of languages) {
  if (!fs.statSync(path.join(source, language, 'pages'), { throwIfNoEntry: false })?.isDirectory()) {
    fail(`Source snapshot does not contain ${language} pages.`);
  }
  if (!fs.statSync(path.join(source, 'search', `${language}.json`), { throwIfNoEntry: false })?.isFile()) {
    fail(`Source snapshot does not contain the ${language} search index.`);
  }
}

fs.rmSync(target, { recursive: true, force: true });
fs.mkdirSync(target, { recursive: true });

const pendingAssets = new Set();
let pageCount = 0;
const selected = new Set(languages);
for (const language of languages) {
  copyPages(path.join(source, language, 'pages'), path.join(target, language, 'pages'), selected, contents => {
    pageCount += 1;
    for (const reference of assetReferences(contents)) pendingAssets.add(reference);
  });
  linkOrCopy(path.join(source, 'search', `${language}.json`), path.join(target, 'search', `${language}.json`));
}

const offlineCss = path.join(source, 'offline.css');
if (fs.existsSync(offlineCss)) linkOrCopy(offlineCss, path.join(target, 'offline.css'));

let assetCount = 0;
let assetBytes = 0;
const copiedAssets = new Set();
while (pendingAssets.size) {
  const [relative] = pendingAssets;
  pendingAssets.delete(relative);
  if (copiedAssets.has(relative)) continue;
  const sourceAsset = path.join(source, 'assets', relative);
  if (!fs.statSync(sourceAsset, { throwIfNoEntry: false })?.isFile()) {
    fail(`Referenced asset is absent from the source snapshot: assets/${relative}`);
  }
  linkOrCopy(sourceAsset, path.join(target, 'assets', relative));
  copiedAssets.add(relative);
  assetCount += 1;
  assetBytes += fs.statSync(sourceAsset).size;
  if (relative.endsWith('.css')) {
    for (const dependency of assetReferences(fs.readFileSync(sourceAsset, 'utf8'))) pendingAssets.add(dependency);
  }
}

const translationsPath = path.join(source, 'translations.json');
const sourceTranslations = fs.existsSync(translationsPath)
  ? JSON.parse(fs.readFileSync(translationsPath, 'utf8'))
  : { schema: 1, pages: {}, navigation: {} };
const pages = {};
let mappedPages = 0;
let links = 0;
for (const language of languages) {
  pages[language] = {};
  for (const [pageId, targets] of Object.entries(sourceTranslations.pages?.[language] || {})) {
    const filtered = Object.fromEntries(
      Object.entries(targets).filter(([targetLanguage]) => selected.has(targetLanguage)),
    );
    if (Object.keys(filtered).length) {
      pages[language][pageId] = filtered;
      mappedPages += 1;
      links += Object.keys(filtered).length;
    }
  }
}
const navigation = Object.fromEntries(
  languages
    .filter(language => sourceTranslations.navigation?.[language])
    .map(language => [language, sourceTranslations.navigation[language]]),
);
fs.writeFileSync(
  path.join(target, 'translations.json'),
  `${JSON.stringify({ schema: 1, pages, navigation, mapped_pages: mappedPages, links })}\n`,
);

const edition = languages.length === supportedLanguages.size ? 'multilingual' : languages.join('-');
const manifest = {
  schema: 1,
  edition,
  languages,
  pages: pageCount,
  assets: assetCount,
  asset_bytes: assetBytes,
};
fs.writeFileSync(path.join(target, 'edition.json'), `${JSON.stringify(manifest, null, 2)}\n`);
if (fs.existsSync(translationsPath)) {
  const manifestTime = fs.statSync(translationsPath).mtime;
  fs.utimesSync(path.join(target, 'translations.json'), manifestTime, manifestTime);
  fs.utimesSync(path.join(target, 'edition.json'), manifestTime, manifestTime);
}
console.log(JSON.stringify(manifest, null, 2));
