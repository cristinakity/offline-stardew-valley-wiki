const { app, BrowserWindow, ipcMain, session, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');

if (require('electron-squirrel-startup')) app.quit();

function contentRoot() {
  if (process.env.WIKI_CONTENT_PATH) return path.resolve(process.env.WIKI_CONTENT_PATH);
  if (app.isPackaged) return path.join(process.resourcesPath, 'content');
  const currentPath = path.join(__dirname, '..', '.local-data', 'current.json');
  if (fs.existsSync(currentPath)) {
    const current = JSON.parse(fs.readFileSync(currentPath, 'utf8'));
    const containerPath = path.join(current.path, 'content');
    if (fs.existsSync(containerPath)) return containerPath;
    return path.join(__dirname, '..', '.local-data', 'snapshots', current.snapshot_id, 'content');
  }
  return '';
}

function allowedLocalNavigation(target) {
  if (!target.startsWith('file:')) return false;
  try {
    const decoded = decodeURIComponent(new URL(target).pathname);
    return decoded.startsWith(contentRoot()) || decoded.startsWith(__dirname);
  } catch {
    return false;
  }
}

function pathInsideContent(relativePath) {
  const root = contentRoot();
  const target = path.resolve(root, relativePath);
  const relative = path.relative(root, target);
  if (!root || !relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error('Path escaped the content root.');
  }
  return target;
}

function shellAssets() {
  const sourceRoot = app.isPackaged
    ? process.resourcesPath
    : path.join(__dirname, '..', 'src');
  const themePath = app.isPackaged
    ? path.join(sourceRoot, 'stardewbackground.png')
    : path.join(
      sourceRoot,
      'stardewvalleywiki.com',
      'mediawiki',
      'extensions',
      'StardewValley',
      'images',
      'stardewbackground.png',
    );
  const flagRoot = path.join(sourceRoot, 'flags');
  const flags = {
    en: 'usa-flag.png', es: 'mexico-flag.png', de: 'germany-flag.png', fr: 'france-flag.png',
    it: 'italy-flag.png', ja: 'japan-flag.png', ko: 'south-korea-flag.png', hu: 'hungary-flag.png',
    pt: 'brazil-flag.png', ru: 'russia-flag.png', tr: 'tuerkey-flag.png', zh: 'china-flag.png',
  };
  return {
    background: pathToFileURL(themePath).href,
    flags: Object.fromEntries(
      Object.entries(flags).map(([language, filename]) => [language, pathToFileURL(path.join(flagRoot, filename)).href]),
    ),
  };
}

function registerContentApi() {
  ipcMain.handle('wiki:shell-assets', () => shellAssets());
  ipcMain.handle('wiki:available', () => {
    const root = contentRoot();
    return Boolean(root && fs.existsSync(root));
  });
  ipcMain.handle('wiki:load-index', (_event, language) => {
    if (!/^[a-z]{2}$/.test(language)) throw new Error('Invalid language.');
    const target = pathInsideContent(path.join('search', `${language}.json`));
    const indexedDocuments = JSON.parse(fs.readFileSync(target, 'utf8'));
    const documents = indexedDocuments.filter(document => {
      try {
        return typeof document.url === 'string' && fs.statSync(pathInsideContent(document.url)).isFile();
      } catch {
        return false;
      }
    });
    const removed = indexedDocuments.length - documents.length;
    console.info(
      `Loaded ${documents.length} ${language} search documents from ${target}`
      + (removed ? `; ignored ${removed} entries without a local page` : ''),
    );
    return documents;
  });
  ipcMain.handle('wiki:page-url', (_event, relativePath) => {
    console.info(`Resolving offline page ${relativePath}`);
    const target = pathInsideContent(relativePath);
    if (!fs.existsSync(target)) throw new Error('Page is unavailable.');
    const url = pathToFileURL(target).href;
    console.info(`Resolved offline page to ${url}`);
    return url;
  });
  ipcMain.handle('wiki:open-external', (_event, url) => {
    const parsed = new URL(url);
    if (!['https:', 'http:'].includes(parsed.protocol)) throw new Error('Unsupported external URL.');
    return shell.openExternal(parsed.href);
  });
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: '#07172f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  window.loadFile(path.join(__dirname, 'shell.html'));
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (!allowedLocalNavigation(url)) {
      event.preventDefault();
      if (url.startsWith('https://') || url.startsWith('http://')) shell.openExternal(url);
    }
  });
}

app.whenReady().then(() => {
  session.defaultSession.webRequest.onBeforeRequest(
    { urls: ['http://*/*', 'https://*/*'] },
    (_details, callback) => callback({ cancel: true }),
  );
  registerContentApi();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
