const languages = [
  ['en','English'],['es','Español'],['de','Deutsch'],['fr','Français'],
  ['it','Italiano'],['ja','日本語'],['ko','한국어'],['hu','Magyar'],
  ['pt','Português'],['ru','Русский'],['tr','Türkçe'],['zh','中文'],
];
const interfaceText = {
  en: { home: 'Go to Main Wiki page', back: 'Back', forward: 'Forward', search: 'Search', results: 'Search Results', resultsFor: 'results for', noResults: 'No results', loading: 'Loading search…' },
  es: { home: 'Ir a la página principal', back: 'Atrás', forward: 'Adelante', search: 'Buscar', results: 'Resultados de búsqueda', resultsFor: 'resultados para', noResults: 'Sin resultados', loading: 'Cargando búsqueda…' },
  de: { home: 'Zur Wiki-Hauptseite', back: 'Zurück', forward: 'Vorwärts', search: 'Suchen', results: 'Suchergebnisse', resultsFor: 'Ergebnisse für', noResults: 'Keine Ergebnisse', loading: 'Suche wird geladen…' },
  fr: { home: 'Aller à la page principale', back: 'Retour', forward: 'Suivant', search: 'Rechercher', results: 'Résultats de recherche', resultsFor: 'résultats pour', noResults: 'Aucun résultat', loading: 'Chargement de la recherche…' },
  it: { home: 'Vai alla pagina principale', back: 'Indietro', forward: 'Avanti', search: 'Cerca', results: 'Risultati della ricerca', resultsFor: 'risultati per', noResults: 'Nessun risultato', loading: 'Caricamento ricerca…' },
  ja: { home: 'Wikiのメインページへ', back: '戻る', forward: '進む', search: '検索', results: '検索結果', resultsFor: '件の検索結果:', noResults: '結果なし', loading: '検索を読み込み中…' },
  ko: { home: '위키 메인 페이지로', back: '뒤로', forward: '앞으로', search: '검색', results: '검색 결과', resultsFor: '개 검색 결과:', noResults: '결과 없음', loading: '검색 로드 중…' },
  hu: { home: 'Ugrás a wiki főoldalára', back: 'Vissza', forward: 'Előre', search: 'Keresés', results: 'Keresési eredmények', resultsFor: 'találat:', noResults: 'Nincs találat', loading: 'Keresés betöltése…' },
  pt: { home: 'Ir para a página principal', back: 'Voltar', forward: 'Avançar', search: 'Pesquisar', results: 'Resultados da pesquisa', resultsFor: 'resultados para', noResults: 'Nenhum resultado', loading: 'Carregando pesquisa…' },
  ru: { home: 'На главную страницу вики', back: 'Назад', forward: 'Вперёд', search: 'Поиск', results: 'Результаты поиска', resultsFor: 'результатов для', noResults: 'Нет результатов', loading: 'Загрузка поиска…' },
  tr: { home: 'Wiki ana sayfasına git', back: 'Geri', forward: 'İleri', search: 'Ara', results: 'Arama sonuçları', resultsFor: 'sonuç:', noResults: 'Sonuç yok', loading: 'Arama yükleniyor…' },
  zh: { home: '前往Wiki主页', back: '后退', forward: '前进', search: '搜索', results: '搜索结果', resultsFor: '条结果：', noResults: '没有结果', loading: '正在加载搜索…' },
};
const frame = document.querySelector('#page');
const empty = document.querySelector('#empty');
const results = document.querySelector('#results');
const notice = document.querySelector('#notice');
const searchPage = document.querySelector('#searchPage');
const searchSummary = document.querySelector('#searchSummary');
const searchList = document.querySelector('#searchList');
const imageViewer = document.querySelector('#imageViewer');
const imageViewerCanvas = document.querySelector('#imageViewerCanvas');
const imageViewerImage = document.querySelector('#imageViewerImage');
const imageViewerTitle = document.querySelector('#imageViewerTitle');
const contentSetup = document.querySelector('#contentSetup');
const setupClose = document.querySelector('#setupClose');
const languageChoices = document.querySelector('#languageChoices');
const setupProgress = document.querySelector('#setupProgress');
const contentProgress = document.querySelector('#contentProgress');
const contentStatus = document.querySelector('#contentStatus');
const setupError = document.querySelector('#setupError');
const downloadContent = document.querySelector('#downloadContent');
const importContent = document.querySelector('#importContent');
const pauseContent = document.querySelector('#pauseContent');
const resumeContent = document.querySelector('#resumeContent');
const cancelContent = document.querySelector('#cancelContent');
let documents = [];
let documentsById = new Map();
let searchIndex;
let currentLanguage = 'en';
let currentDocument = null;
let availableLanguageCodes = languages.map(([code]) => code);
let translationData = { pages: {}, navigation: {} };
const languageCache = new Map();
const languagePromises = new Map();
let noticeTimer;
let imageZoom = 1;
let installedContent = false;
let setupBusy = false;
const unavailableMessages = {
  en: title => `“${title}” is not available in the offline version.`,
  es: title => `“${title}” no está disponible en la versión offline.`,
  de: title => `„${title}“ ist in der Offline-Version nicht verfügbar.`,
  fr: title => `« ${title} » n’est pas disponible dans la version hors ligne.`,
  it: title => `“${title}” non è disponibile nella versione offline.`,
  ja: title => `「${title}」はオフライン版では利用できません。`,
  ko: title => `‘${title}’ 문서는 오프라인 버전에서 사용할 수 없습니다.`,
  hu: title => `„${title}” nem érhető el az offline verzióban.`,
  pt: title => `“${title}” não está disponível na versão offline.`,
  ru: title => `Страница «${title}» недоступна в офлайн-версии.`,
  tr: title => `“${title}” çevrimdışı sürümde kullanılamıyor.`,
  zh: title => `“${title}”在离线版本中不可用。`,
};
const pendingMessages = {
  en: title => `“${title}” has not been downloaded or updated in this offline version yet.`,
  es: title => `“${title}” todavía no se ha descargado o actualizado en esta versión offline.`,
  de: title => `„${title}“ wurde in dieser Offline-Version noch nicht heruntergeladen oder aktualisiert.`,
  fr: title => `« ${title} » n’a pas encore été téléchargée ou mise à jour dans cette version hors ligne.`,
  it: title => `“${title}” non è stata ancora scaricata o aggiornata in questa versione offline.`,
  ja: title => `「${title}」は、このオフライン版ではまだダウンロードまたは更新されていません。`,
  ko: title => `‘${title}’ 문서는 이 오프라인 버전에 아직 다운로드되거나 업데이트되지 않았습니다.`,
  hu: title => `„${title}” még nincs letöltve vagy frissítve ebben az offline verzióban.`,
  pt: title => `“${title}” ainda não foi baixada ou atualizada nesta versão offline.`,
  ru: title => `Страница «${title}» ещё не загружена или не обновлена в этой офлайн-версии.`,
  tr: title => `“${title}” bu çevrimdışı sürümde henüz indirilmedi veya güncellenmedi.`,
  zh: title => `“${title}”尚未在此离线版本中下载或更新。`,
};

function formatBytes(value) {
  if (!Number.isFinite(value)) return 'Unknown';
  const units = ['B', 'KiB', 'MiB', 'GiB'];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function selectedContentLanguages() {
  return [...languageChoices.querySelectorAll('input:checked')].map(input => input.value);
}

function setSetupBusy(busy) {
  setupBusy = busy;
  for (const input of languageChoices.querySelectorAll('input')) input.disabled = busy;
  downloadContent.disabled = busy;
  importContent.disabled = busy;
  document.querySelector('#retainArchive').disabled = busy;
  document.querySelector('#checkContentUpdate').disabled = busy || !installedContent;
  document.querySelector('#selectAllLanguages').disabled = busy;
  document.querySelector('#clearLanguages').disabled = busy;
  setupClose.disabled = busy || !installedContent;
  setupProgress.hidden = !busy;
  pauseContent.disabled = !busy;
  resumeContent.disabled = !busy;
  cancelContent.disabled = !busy;
}

function showSetupError(message) {
  setupError.textContent = message;
  setupError.hidden = !message;
}

function progressLabel(progress) {
  const labels = {
    downloading: 'Downloading the approved multilingual snapshot…',
    verifying: 'Verifying the snapshot checksum…',
    extracting: 'Extracting the snapshot…',
    selecting: `Keeping selected languages… ${progress.pages || 0} pages, ${progress.assets || 0} assets`,
    validating: 'Validating the installed offline content…',
    paused: 'Paused. You can resume without losing download progress.',
    cancelled: 'Installation cancelled. A partial download can be resumed later.',
    completed: 'Offline content is ready. Opening the wiki…',
    failed: 'Content installation failed.',
  };
  return labels[progress.phase] || 'Preparing offline content…';
}

function handleContentProgress(progress) {
  setupProgress.hidden = false;
  contentStatus.textContent = progressLabel(progress);
  if (Number.isFinite(progress.current) && Number.isFinite(progress.total) && progress.total > 0) {
    contentProgress.value = Math.min(100, progress.current / progress.total * 100);
  } else {
    contentProgress.removeAttribute('value');
  }
  const paused = progress.phase === 'paused';
  pauseContent.hidden = paused;
  resumeContent.hidden = !paused;
  if (progress.phase === 'failed') {
    setSetupBusy(false);
    showSetupError(progress.error || 'Try again or import the approved snapshot from a local file.');
  }
  if (progress.phase === 'cancelled') {
    setSetupBusy(false);
    showSetupError('The operation was cancelled safely.');
  }
  if (progress.phase === 'completed') {
    installedContent = true;
    showSetupError('');
    setTimeout(() => window.location.reload(), 700);
  }
}

async function openContentSetup() {
  const status = await window.offlineWiki.contentStatus();
  installedContent = status.installed;
  languageChoices.innerHTML = '';
  const browserLanguage = String(navigator.language || 'en').slice(0, 2).toLowerCase();
  const preferred = status.installedLanguages.length
    ? status.installedLanguages
    : [status.manifest.languages.includes(browserLanguage) ? browserLanguage : 'en'];
  for (const [code, name] of languages.filter(([code]) => status.manifest.languages.includes(code))) {
    const label = document.createElement('label');
    label.className = 'languageChoice';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = code;
    input.checked = preferred.includes(code);
    label.append(input, document.createTextNode(`${name} (${code.toUpperCase()})`));
    languageChoices.appendChild(label);
  }
  document.querySelector('#downloadSize').textContent = formatBytes(status.manifest.archive_bytes);
  document.querySelector('#requiredSpace').textContent = formatBytes(status.manifest.required_free_bytes);
  document.querySelector('#availableSpace').textContent = formatBytes(status.freeBytes);
  document.querySelector('#retainArchive').checked = status.archiveRetained;
  setupClose.hidden = !status.installed;
  setSetupBusy(status.busy);
  showSetupError(status.freeBytes !== null && status.freeBytes < status.manifest.required_free_bytes
    ? 'There may not be enough temporary disk space for installation.' : '');
  contentSetup.hidden = false;
}

async function startContentSetup(archivePath = null) {
  const selected = selectedContentLanguages();
  if (!selected.length) { showSetupError('Select at least one language.'); return; }
  showSetupError('');
  setSetupBusy(true);
  contentProgress.removeAttribute('value');
  contentStatus.textContent = archivePath ? 'Reading the local snapshot…' : 'Starting download…';
  try {
    await window.offlineWiki.startContentInstall({
      languages: selected,
      archivePath,
      retainArchive: document.querySelector('#retainArchive').checked,
    });
  } catch (error) {
    setSetupBusy(false);
    showSetupError(error.message);
  }
}

window.offlineWiki.onContentProgress(handleContentProgress);
document.querySelector('#contentSettings').addEventListener('click', () => openContentSetup().catch(error => showNotice(error.message)));
setupClose.addEventListener('click', () => { if (!setupBusy && installedContent) contentSetup.hidden = true; });
document.querySelector('#selectAllLanguages').addEventListener('click', () => {
  for (const input of languageChoices.querySelectorAll('input')) input.checked = true;
});
document.querySelector('#clearLanguages').addEventListener('click', () => {
  for (const input of languageChoices.querySelectorAll('input')) input.checked = false;
});
downloadContent.addEventListener('click', () => startContentSetup());
importContent.addEventListener('click', async () => {
  const archivePath = await window.offlineWiki.chooseContentArchive();
  if (archivePath) await startContentSetup(archivePath);
});
document.querySelector('#checkContentUpdate').addEventListener('click', async () => {
  showSetupError('');
  contentStatus.textContent = 'Checking for approved content updates…';
  setupProgress.hidden = false;
  contentProgress.removeAttribute('value');
  try {
    const result = await window.offlineWiki.checkContentUpdate();
    if (result.updateAvailable) {
      await openContentSetup();
      showSetupError(`A newer approved snapshot is available: ${result.availableSnapshotId}. Choose languages and install it.`);
    } else {
      setupProgress.hidden = true;
      showSetupError('Your installed content is up to date.');
    }
  } catch (error) {
    setupProgress.hidden = true;
    showSetupError(error.message);
  }
});
pauseContent.addEventListener('click', async () => { await window.offlineWiki.pauseContentInstall(); });
resumeContent.addEventListener('click', async () => {
  await window.offlineWiki.resumeContentInstall();
  pauseContent.hidden = false;
  resumeContent.hidden = true;
});
cancelContent.addEventListener('click', async () => {
  cancelContent.disabled = true;
  contentStatus.textContent = 'Cancelling safely…';
  await window.offlineWiki.cancelContentInstall();
});

function offlineLinkMessage(title, language, status) {
  const messages = status === 'excluded' ? unavailableMessages : pendingMessages;
  return (messages[language] || messages.en)(title);
}

function showNotice(message) {
  clearTimeout(noticeTimer);
  notice.textContent = message;
  notice.hidden = false;
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 7000);
}

function bestLocalImageSource(image) {
  const baseWidth = Number(image.getAttribute('width')) || image.naturalWidth || 1;
  const candidates = [{ source: image.currentSrc || image.src, score: baseWidth }];
  for (const entry of String(image.getAttribute('srcset') || '').split(',')) {
    const [source, descriptor = '1x'] = entry.trim().split(/\s+/u);
    if (!source) continue;
    const amount = Number.parseFloat(descriptor) || 1;
    const score = descriptor.endsWith('w') ? amount : amount * baseWidth;
    try {
      candidates.push({ source: new URL(source, frame.contentWindow.location.href).href, score });
    } catch (_) {}
  }
  return candidates
    .filter(candidate => candidate.source?.startsWith('file:') || candidate.source?.startsWith('data:'))
    .sort((left, right) => right.score - left.score)[0]?.source || '';
}

function applyImageZoom() {
  if (!imageViewerImage.naturalWidth) return;
  imageViewerImage.style.width = `${Math.round(imageViewerImage.naturalWidth * imageZoom)}px`;
  imageViewerImage.style.height = 'auto';
}

function fitImageViewer() {
  if (!imageViewerImage.naturalWidth || !imageViewerImage.naturalHeight) return;
  const availableWidth = Math.max(100, imageViewerCanvas.clientWidth - 40);
  const availableHeight = Math.max(100, imageViewerCanvas.clientHeight - 40);
  const fit = Math.min(
    availableWidth / imageViewerImage.naturalWidth,
    availableHeight / imageViewerImage.naturalHeight,
  );
  imageZoom = Math.min(4, fit);
  applyImageZoom();
}

function openImageViewer(image, title) {
  const source = bestLocalImageSource(image);
  if (!source) return false;
  clearTimeout(noticeTimer);
  notice.hidden = true;
  imageViewerTitle.textContent = title || image.alt || 'Image';
  imageViewerImage.alt = title || image.alt || '';
  imageViewerImage.onload = fitImageViewer;
  imageViewerImage.src = source;
  imageViewer.hidden = false;
  document.querySelector('#imageViewerClose').focus();
  return true;
}

function closeImageViewer() {
  imageViewer.hidden = true;
  imageViewerImage.removeAttribute('src');
  imageViewerImage.style.removeProperty('width');
}

document.querySelector('#imageZoomOut').addEventListener('click', () => {
  imageZoom = Math.max(0.1, imageZoom / 1.25);
  applyImageZoom();
});
document.querySelector('#imageZoomReset').addEventListener('click', () => {
  imageZoom = 1;
  applyImageZoom();
});
document.querySelector('#imageZoomIn').addEventListener('click', () => {
  imageZoom = Math.min(8, imageZoom * 1.25);
  applyImageZoom();
});
document.querySelector('#imageViewerClose').addEventListener('click', closeImageViewer);
imageViewerCanvas.addEventListener('click', event => {
  if (event.target === imageViewerCanvas) closeImageViewer();
});
window.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !imageViewer.hidden) closeImageViewer();
});

function updateInterfaceLanguage(language) {
  const text = interfaceText[language] || interfaceText.en;
  const home = document.querySelector('#home');
  const back = document.querySelector('#back');
  const forward = document.querySelector('#forward');
  const search = document.querySelector('#search');
  home.textContent = text.home;
  home.title = text.home;
  back.title = text.back;
  back.setAttribute('aria-label', text.back);
  forward.title = text.forward;
  forward.setAttribute('aria-label', text.forward);
  search.placeholder = text.search;
  document.querySelector('#searchButton').textContent = text.search;
  document.querySelector('.searchPage h1').textContent = text.results;
  document.documentElement.lang = language;
  window.offlineWiki.setLanguage(language).catch(error => console.warn('Unable to translate app menu:', error));
}

for (const [code, name] of languages) {
  const button = document.createElement('button');
  button.className = 'flag';
  button.dataset.language = code;
  button.title = name;
  const image = document.createElement('img');
  image.alt = name;
  button.appendChild(image);
  button.setAttribute('aria-label', name);
  button.addEventListener('click', () => switchLanguage(code));
  document.querySelector('#languages').appendChild(button);
}

function normalizedTitle(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\s+/gu, ' ').trim().toLocaleLowerCase();
}

function documentByTitle(title) {
  const wanted = normalizedTitle(title);
  return documents.find(item => normalizedTitle(item.title) === wanted);
}

function pageIdentity(url) {
  try {
    const path = decodeURIComponent(new URL(url).pathname);
    const match = path.match(/\/([a-z]{2})\/pages\/(\d+)\.html$/u);
    return match ? { language: match[1], pageId: Number(match[2]) } : null;
  } catch {
    return null;
  }
}

async function rememberDocument(item) {
  currentDocument = item;
  try {
    await window.offlineWiki.saveReaderState({
      language: currentLanguage,
      pageId: Number(item.id),
      title: item.title,
    });
  } catch (error) {
    console.warn('Unable to save reader position:', error);
  }
}

async function openDocument(item) {
  clearTimeout(noticeTimer);
  notice.hidden = true;
  notice.textContent = '';
  frame.src = await window.offlineWiki.pageUrl(item.url);
  await rememberDocument(item);
  frame.hidden = false;
  empty.hidden = true;
  searchPage.hidden = true;
  results.style.display = 'none';
}

async function languageData(code) {
  if (languageCache.has(code)) return languageCache.get(code);
  if (languagePromises.has(code)) return languagePromises.get(code);
  const promise = (async () => {
    const loadedDocuments = (await window.offlineWiki.loadIndex(code)).map(document => ({
      ...document,
      text: document.text || '',
    }));
    if (typeof MiniSearch !== 'function') throw new Error('The offline search library could not be loaded.');
    const loadedSearchIndex = new MiniSearch({ fields: ['title', 'text'], storeFields: ['title', 'url'] });
    loadedSearchIndex.addAll(loadedDocuments);
    const data = {
      documents: loadedDocuments,
      documentsById: new Map(loadedDocuments.map(document => [String(document.id), document])),
      searchIndex: loadedSearchIndex,
    };
    languageCache.set(code, data);
    return data;
  })();
  languagePromises.set(code, promise);
  try {
    return await promise;
  } finally {
    languagePromises.delete(code);
  }
}

function navigationDocuments(code) {
  const navigation = translationData.navigation?.[code];
  if (!navigation?.pages) return null;
  return navigation.pages.map(([id, title]) => ({
    id,
    title,
    url: `${code}/pages/${id}.html`,
    text: '',
    home: Number(id) === Number(navigation.home),
  }));
}

async function loadLanguage(code, requested = null) {
  try {
    currentLanguage = code;
    updateInterfaceLanguage(code);
    const cached = languageCache.get(code);
    documents = cached?.documents || navigationDocuments(code) || (await languageData(code)).documents;
    documentsById = cached?.documentsById
      || new Map(documents.map(document => [String(document.id), document]));
    searchIndex = cached?.searchIndex;
    document.querySelector('#search').placeholder = interfaceText[code]?.search || interfaceText.en.search;
    for (const button of document.querySelectorAll('.flag')) {
      button.setAttribute('aria-pressed', String(button.dataset.language === code));
    }
    const home = documents.find(item => item.home) || documents.find(item => item.title === 'Stardew Valley Wiki') || documents[0];
    const requestedPage = requested && (
      documentsById.get(String(requested.pageId || '')) || documentByTitle(requested.title)
    );
    const target = requestedPage || home;
    empty.querySelector('p').textContent = target ? `Opening ${target.title}…` : 'This language has no downloaded pages.';
    if (target) await openDocument(target);
    if (requested && !requestedPage && requested.title) {
      showNotice(offlineLinkMessage(requested.title, code, 'missing'));
    }
  } catch (error) {
    frame.hidden = true;
    empty.hidden = false;
    empty.querySelector('p').textContent = error.message;
  }
}

function translationFor(language) {
  try {
    const indexedPageId = translationData.pages?.[currentLanguage]?.[String(currentDocument?.id)]?.[language];
    if (Number.isSafeInteger(indexedPageId) && indexedPageId > 0) {
      return { language, pageId: indexedPageId };
    }
    const anchors = [...frame.contentDocument.querySelectorAll('a')];
    const translated = anchors.find(anchor => {
      const title = anchor.getAttribute('title') || '';
      const mediaWikiLanguageLink = anchor.getAttribute('hreflang') === language
        && anchor.classList.contains('interlanguage-link-target');
      const legacyLanguageLink = anchor.classList.contains('extiw')
        && (
          anchor.dataset.missingLocalLanguage === language
          || title.toLocaleLowerCase().startsWith(`${language}:`)
        );
      return mediaWikiLanguageLink || legacyLanguageLink;
    });
    if (!translated) return null;
    const identity = pageIdentity(translated.href);
    if (identity?.language === language) return identity;
    const title = translated.dataset.missingLocalTitle
      || (translated.getAttribute('title') || '').replace(new RegExp(`^${language}:`, 'iu'), '');
    return title ? { language, title } : null;
  } catch {
    return null;
  }
}

async function switchLanguage(code) {
  if (code === currentLanguage || !availableLanguageCodes.includes(code)) return;
  const requested = translationFor(code) || (currentDocument ? { title: currentDocument.title } : null);
  await loadLanguage(code, requested);
}

async function openKnownTitle(title, language) {
  if (language !== currentLanguage) {
    await loadLanguage(language, { title });
    return currentDocument && normalizedTitle(currentDocument.title) === normalizedTitle(title);
  }
  const target = documentByTitle(title);
  if (!target) return false;
  await openDocument(target);
  return true;
}

function matchingTerms(query) {
  return [...new Set(query.trim().split(/\s+/u).filter(Boolean))];
}

function appendHighlightedText(parent, text, query) {
  const terms = matchingTerms(query).sort((left, right) => right.length - left.length);
  if (!terms.length) {
    parent.textContent = text;
    return;
  }
  const escaped = terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'giu');
  for (const part of text.split(pattern)) {
    const node = terms.some(term => term.toLocaleLowerCase() === part.toLocaleLowerCase())
      ? document.createElement('mark')
      : document.createTextNode(part);
    if (node.nodeType === 1) node.textContent = part;
    parent.appendChild(node);
  }
}

function snippetFor(text, query) {
  const normalized = String(text || '').replace(/\s+/gu, ' ').trim();
  if (!normalized) return '';
  const lower = normalized.toLocaleLowerCase();
  const positions = matchingTerms(query)
    .map(term => lower.indexOf(term.toLocaleLowerCase()))
    .filter(position => position >= 0);
  const matchAt = positions.length ? Math.min(...positions) : 0;
  const start = Math.max(0, matchAt - 90);
  const end = Math.min(normalized.length, start + 320);
  return `${start ? '…' : ''}${normalized.slice(start, end)}${end < normalized.length ? '…' : ''}`;
}

async function ensureSearchIndex() {
  const language = currentLanguage;
  const searchInput = document.querySelector('#search');
  if (languageCache.has(language)) {
    const cached = languageCache.get(language);
    documents = cached.documents;
    documentsById = cached.documentsById;
    searchIndex = cached.searchIndex;
    return true;
  }
  searchInput.placeholder = interfaceText[language]?.loading || interfaceText.en.loading;
  const data = await languageData(language);
  if (currentLanguage !== language) return false;
  documents = data.documents;
  documentsById = data.documentsById;
  searchIndex = data.searchIndex;
  searchInput.placeholder = interfaceText[language]?.search || interfaceText.en.search;
  return true;
}

async function fullSearch() {
  let query = document.querySelector('#search').value.trim();
  if (!query || !(await ensureSearchIndex())) return;
  query = document.querySelector('#search').value.trim();
  if (!query) return;
  const matches = searchIndex.search(query, { prefix: true, fuzzy: 0.2, boost: { title: 4 } }).slice(0, 100);
  results.innerHTML = '';
  results.style.display = 'none';
  frame.hidden = true;
  empty.hidden = true;
  searchPage.hidden = false;
  searchList.innerHTML = '';
  searchSummary.textContent = `${matches.length} ${interfaceText[currentLanguage]?.resultsFor || interfaceText.en.resultsFor} “${query}”`;
  for (const match of matches) {
    const item = documentsById.get(String(match.id)) || match;
    const article = document.createElement('article');
    article.className = 'searchResult';
    const link = document.createElement('a');
    link.href = '#';
    appendHighlightedText(link, item.title, query);
    link.addEventListener('click', event => { event.preventDefault(); openDocument(item); });
    const snippet = document.createElement('p');
    appendHighlightedText(snippet, snippetFor(item.text, query), query);
    article.append(link, snippet);
    searchList.appendChild(article);
  }
  if (!matches.length) {
    const message = document.createElement('p');
    message.className = 'searchEmpty';
    message.textContent = interfaceText[currentLanguage]?.noResults || interfaceText.en.noResults;
    searchList.appendChild(message);
  }
}

async function showTitleSuggestions() {
  let query = document.querySelector('#search').value.trim();
  results.innerHTML = '';
  if (!query) {
    results.style.display = 'none';
    return;
  }
  if (!(await ensureSearchIndex())) return;
  query = document.querySelector('#search').value.trim();
  if (!query) return;
  const matches = searchIndex.search(query, { fields: ['title'], prefix: true, fuzzy: 0.2 }).slice(0, 8);
  for (const match of matches) {
    const item = documentsById.get(String(match.id)) || match;
    const link = document.createElement('a');
    link.href = '#';
    appendHighlightedText(link, item.title, query);
    link.addEventListener('click', event => { event.preventDefault(); openDocument(item); });
    results.appendChild(link);
  }
  results.style.display = matches.length ? 'block' : 'none';
}

frame.addEventListener('load', async () => {
  try {
    const identity = pageIdentity(frame.contentWindow.location.href);
    if (identity && identity.language !== currentLanguage) {
      await loadLanguage(identity.language, identity);
      return;
    }
    if (identity) {
      const loaded = documentsById.get(String(identity.pageId));
      if (loaded) await rememberDocument(loaded);
    }
    for (const anchor of frame.contentDocument.querySelectorAll('a.image, a.mw-file-description')) {
      if (!anchor.querySelector('img')) continue;
      anchor.style.cursor = 'zoom-in';
      anchor.title = anchor.dataset.missingLocalTitle || anchor.title || 'Open image';
    }
    for (const anchor of frame.contentDocument.querySelectorAll('a[data-missing-local-title]')) {
      if (anchor.matches('a.image, a.mw-file-description') && anchor.querySelector('img')) continue;
      const language = anchor.dataset.missingLocalLanguage || currentLanguage;
      const status = anchor.dataset.offlineLinkStatus;
      const localTarget = status !== 'excluded' && language === currentLanguage
        ? documentByTitle(anchor.dataset.missingLocalTitle)
        : null;
      if (localTarget) {
        anchor.setAttribute('href', `../../${language}/pages/${localTarget.id}.html`);
        anchor.removeAttribute('data-missing-local-title');
        anchor.removeAttribute('data-missing-local-language');
        anchor.removeAttribute('data-offline-link-status');
        anchor.title = localTarget.title;
        continue;
      }
      anchor.style.cursor = status === 'excluded' ? 'not-allowed' : 'help';
      anchor.title = offlineLinkMessage(
        anchor.dataset.missingLocalTitle,
        language,
        status,
      );
    }
    frame.contentDocument.addEventListener('click', event => {
      const element = event.target?.nodeType === 1 ? event.target : event.target?.parentElement;
      const imageLink = element?.closest('a.image, a.mw-file-description');
      const linkedImage = imageLink?.querySelector('img');
      if (linkedImage) {
        event.preventDefault();
        openImageViewer(
          linkedImage,
          imageLink.dataset.missingLocalTitle || linkedImage.alt || imageLink.title,
        );
        return;
      }
      const missing = element?.closest('a[data-missing-local-title]');
      if (missing) {
        event.preventDefault();
        const language = missing.dataset.missingLocalLanguage || currentLanguage;
        const title = missing.dataset.missingLocalTitle;
        const status = missing.dataset.offlineLinkStatus;
        if (status !== 'excluded') {
          openKnownTitle(title, language)
            .then(opened => {
              if (!opened) showNotice(offlineLinkMessage(title, language, status));
            })
            .catch(() => showNotice(offlineLinkMessage(title, language, status)));
        } else {
          showNotice(offlineLinkMessage(title, language, status));
        }
        return;
      }
      const external = element?.closest('a[data-external-url]');
      if (external) {
        event.preventDefault();
        window.offlineWiki.openExternal(external.dataset.externalUrl);
      }
    });
  } catch (_) {}
});
document.querySelector('#searchButton').addEventListener('click', fullSearch);
document.querySelector('#search').addEventListener('input', showTitleSuggestions);
document.querySelector('#search').addEventListener('keydown', event => {
  if (event.key === 'Enter') fullSearch();
  if (event.key === 'Escape') results.style.display = 'none';
});
document.querySelector('#back').addEventListener('click', () => {
  if (!searchPage.hidden) {
    searchPage.hidden = true;
    frame.hidden = false;
    return;
  }
  frame.contentWindow.history.back();
});
document.querySelector('#forward').addEventListener('click', () => frame.contentWindow.history.forward());
document.querySelector('#home').addEventListener('click', () => loadLanguage(currentLanguage));
(async () => {
  try {
    const assets = await window.offlineWiki.shellAssets();
    document.body.style.backgroundImage = `url("${assets.background}")`;
    for (const button of document.querySelectorAll('.flag')) {
      button.querySelector('img').src = assets.flags[button.dataset.language];
    }
    empty.querySelector('p').textContent = 'Checking .local-data/current.json…';
    if (await window.offlineWiki.available()) {
      installedContent = true;
      translationData = await window.offlineWiki.loadTranslations();
      availableLanguageCodes = await window.offlineWiki.availableLanguages();
      for (const button of document.querySelectorAll('.flag')) {
        button.hidden = !availableLanguageCodes.includes(button.dataset.language);
      }
      const saved = await window.offlineWiki.loadReaderState();
      const language = availableLanguageCodes.includes(saved?.language)
        ? saved.language
        : (availableLanguageCodes.includes('en') ? 'en' : availableLanguageCodes[0]);
      if (!language) throw new Error('This package does not contain any language indexes.');
      empty.querySelector('p').textContent = `Opening the ${language.toUpperCase()} offline wiki…`;
      await loadLanguage(language, saved);
    } else {
      empty.querySelector('h1').textContent = 'Offline content is not installed yet';
      empty.querySelector('p').textContent = 'Choose your languages to download the approved wiki snapshot.';
      await openContentSetup();
    }
  } catch (error) {
    empty.querySelector('h1').textContent = 'Unable to open the local wiki';
    empty.querySelector('p').textContent = error.message;
    console.error(error);
  }
})();
