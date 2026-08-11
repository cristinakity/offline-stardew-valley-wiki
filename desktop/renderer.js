const languages = [
  ['en','English'],['es','Español'],['de','Deutsch'],['fr','Français'],
  ['it','Italiano'],['ja','日本語'],['ko','한국어'],['hu','Magyar'],
  ['pt','Português'],['ru','Русский'],['tr','Türkçe'],['zh','中文'],
];
const frame = document.querySelector('#page');
const empty = document.querySelector('#empty');
const results = document.querySelector('#results');
const notice = document.querySelector('#notice');
const searchPage = document.querySelector('#searchPage');
const searchSummary = document.querySelector('#searchSummary');
const searchList = document.querySelector('#searchList');
let documents = [];
let documentsById = new Map();
let searchIndex;
let currentLanguage = 'en';
let currentDocument = null;
let noticeTimer;
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
  frame.src = await window.offlineWiki.pageUrl(item.url);
  await rememberDocument(item);
  frame.hidden = false;
  empty.hidden = true;
  searchPage.hidden = true;
  results.style.display = 'none';
}

async function loadLanguage(code, requested = null) {
  try {
    currentLanguage = code;
    documents = (await window.offlineWiki.loadIndex(code)).map(document => ({
      ...document,
      text: document.text || '',
    }));
    documentsById = new Map(documents.map(document => [String(document.id), document]));
    empty.querySelector('p').textContent = `Building the ${code.toUpperCase()} offline search index…`;
    if (typeof MiniSearch !== 'function') throw new Error('The offline search library could not be loaded.');
    searchIndex = new MiniSearch({ fields: ['title', 'text'], storeFields: ['title', 'url'] });
    searchIndex.addAll(documents);
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
    const anchors = [...frame.contentDocument.querySelectorAll('a')];
    const translated = anchors.find(anchor => {
      const title = anchor.getAttribute('title') || '';
      return anchor.dataset.missingLocalLanguage === language
        || anchor.getAttribute('hreflang') === language
        || (anchor.classList.contains('extiw') && title.toLocaleLowerCase().startsWith(`${language}:`));
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
  if (code === currentLanguage) return;
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

function fullSearch() {
  const query = document.querySelector('#search').value.trim();
  if (!query || !searchIndex) return;
  const matches = searchIndex.search(query, { prefix: true, fuzzy: 0.2, boost: { title: 4 } }).slice(0, 100);
  results.innerHTML = '';
  results.style.display = 'none';
  frame.hidden = true;
  empty.hidden = true;
  searchPage.hidden = false;
  searchList.innerHTML = '';
  searchSummary.textContent = `${matches.length} result${matches.length === 1 ? '' : 's'} for “${query}”`;
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
    message.textContent = 'No results';
    searchList.appendChild(message);
  }
}

function showTitleSuggestions() {
  const query = document.querySelector('#search').value.trim();
  results.innerHTML = '';
  if (!query || !searchIndex) {
    results.style.display = 'none';
    return;
  }
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
    for (const anchor of frame.contentDocument.querySelectorAll('a[data-missing-local-title]')) {
      const language = anchor.dataset.missingLocalLanguage || currentLanguage;
      anchor.title = offlineLinkMessage(
        anchor.dataset.missingLocalTitle,
        language,
        anchor.dataset.offlineLinkStatus,
      );
    }
    frame.contentDocument.addEventListener('click', event => {
      const element = event.target?.nodeType === 1 ? event.target : event.target?.parentElement;
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
      const saved = await window.offlineWiki.loadReaderState();
      const language = saved?.language || 'en';
      empty.querySelector('p').textContent = `Loading the ${language.toUpperCase()} search index…`;
      await loadLanguage(language, saved);
    } else {
      empty.querySelector('h1').textContent = 'No local snapshot found';
      empty.querySelector('p').textContent = 'Run the Podman fixture, sample or full synchronization first.';
    }
  } catch (error) {
    empty.querySelector('h1').textContent = 'Unable to open the local wiki';
    empty.querySelector('p').textContent = error.message;
    console.error(error);
  }
})();
