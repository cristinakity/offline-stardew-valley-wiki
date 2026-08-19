const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('offlineWiki', {
  shellAssets: () => ipcRenderer.invoke('wiki:shell-assets'),
  available: () => ipcRenderer.invoke('wiki:available'),
  availableLanguages: () => ipcRenderer.invoke('wiki:available-languages'),
  loadIndex: language => ipcRenderer.invoke('wiki:load-index', language),
  loadTranslations: () => ipcRenderer.invoke('wiki:load-translations'),
  pageUrl: relativePath => ipcRenderer.invoke('wiki:page-url', relativePath),
  openExternal: url => ipcRenderer.invoke('wiki:open-external', url),
  loadReaderState: () => ipcRenderer.invoke('wiki:load-reader-state'),
  saveReaderState: state => ipcRenderer.invoke('wiki:save-reader-state', state),
  setLanguage: language => ipcRenderer.invoke('wiki:set-language', language),
  contentStatus: () => ipcRenderer.invoke('wiki:content-status'),
  checkContentUpdate: () => ipcRenderer.invoke('wiki:content-check-update'),
  startContentInstall: options => ipcRenderer.invoke('wiki:content-start', options),
  pauseContentInstall: () => ipcRenderer.invoke('wiki:content-pause'),
  resumeContentInstall: () => ipcRenderer.invoke('wiki:content-resume'),
  cancelContentInstall: () => ipcRenderer.invoke('wiki:content-cancel'),
  chooseContentArchive: () => ipcRenderer.invoke('wiki:content-choose-archive'),
  onContentProgress: callback => {
    const listener = (_event, progress) => callback(progress);
    ipcRenderer.on('wiki:content-progress', listener);
    return () => ipcRenderer.removeListener('wiki:content-progress', listener);
  },
});
