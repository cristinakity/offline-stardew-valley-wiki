const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('offlineWiki', {
  shellAssets: () => ipcRenderer.invoke('wiki:shell-assets'),
  available: () => ipcRenderer.invoke('wiki:available'),
  loadIndex: language => ipcRenderer.invoke('wiki:load-index', language),
  pageUrl: relativePath => ipcRenderer.invoke('wiki:page-url', relativePath),
  openExternal: url => ipcRenderer.invoke('wiki:open-external', url),
});
