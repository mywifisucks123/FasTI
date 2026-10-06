import { api } from './api.js';
import { player } from './player.js';
import { debounce, esc, fmtDuration, fmtTime, html, icons, img, toast, toFragment } from './ui.js';

// ---------------------------------------------------------------------------
// Register: Listen (für Wiedergabe per Tipp) und Items (für Favoriten-Buttons)
// ---------------------------------------------------------------------------

export const lists = new Map();
export const items = new Map();
let listSeq = 0;

export function registerList(tracks) {
  const id = `l${++listSeq}`;
  lists.set(id, tracks);
  if (lists.size > 300) lists.delete(lists.keys().next().value);
  return id;
}

export const favKey = (type, item) => `${type}:${item.source}:${item.id}`;

// ---------------------------------------------------------------------------
// Favoriten
// ---------------------------------------------------------------------------

export const favs = { tracks: [], albums: [], keys: new Set() };

function setFavs(data) {
  favs.tracks = data.tracks ?? [];
  favs.albums = data.albums ?? [];
  favs.keys = new Set([
    ...favs.tracks.map((t) => favKey('track', t)),
    ...favs.albums.map((a) => favKey('album', a)),
  ]);
}

export async function loadFavorites() {
  try {
    setFavs(await api.favorites());
  } catch {}
}

export const isFav = (type, item) => favs.keys.has(favKey(type, item));

function slim(item) {
  // Nur die Felder speichern, die wir zum Anzeigen/Abspielen brauchen
  const { tracks, top, albums, ...rest } = item;
  return rest;
}

export async function toggleFavorite(type, item) {
  const key = favKey(type, item);
  const on = !favs.keys.has(key);
  on ? favs.keys.add(key) : favs.keys.delete(key);
  paintFav(key, on);
  try {
    const data = on ? await api.addFavorite(type, slim(item)) : await api.removeFavorite(type, item);
    setFavs(data);
    if (on) {
      const what = type === 'album' ? 'Album' : 'Song';
      toast(item.source === 'dz' ? `${what} gemerkt – wird in die Bibliothek geladen` : `${what} gemerkt`);
    }
  } catch (err) {
    on ? favs.keys.delete(key) : favs.keys.add(key);
    paintFav(key, !on);
    toast(`Fehler: ${err.message}`);
  }
  document.dispatchEvent(new CustomEvent('favorites'));
}

function paintFav(key, on) {
  for (const el of document.querySelectorAll(`[data-fav-key="${CSS.escape(key)}"]`)) {
    el.classList.toggle('on', on);
    el.innerHTML = on ? icons.heartFill : icons.heart;
    if (on) {
      el.classList.remove('pop');
      void el.offsetWidth;
      el.classList.add('pop');
    }
  }
}

// ---------------------------------------------------------------------------
// Bausteine
// ---------------------------------------------------------------------------

function favButton(type, item, cls = 'row-fav') {
  const key = favKey(type, item);
  items.set(key, item);
  const on = favs.keys.has(key);
  return `<button class="${cls} ${on ? 'on' : ''}" data-fav="${type}" data-fav-key="${esc(key)}" aria-label="Favorit">${on ? icons.heartFill : icons.heart}</button>`;
}

export function trackRows(tracks, { numbered = false, sub } = {}) {
  const listId = registerList(tracks);
  return tracks
    .map((t, i) => {
      const subline = sub ? sub(t) : [t.artist, t.album].filter(Boolean).join(' · ');
      return html`<div class="row ${numbered ? 'numbered' : ''}" data-list="${listId}" data-idx="${i}" data-track="${esc(`${t.source}:${t.id}`)}">
        ${numbered ? `<div class="row-num">${i + 1}</div>` : img(t.coverSmall ?? t.cover, 'row-art')}
        <div class="row-meta">
          <div class="row-title">${esc(t.title)}</div>
          <div class="row-sub">${t.explicit ? '<span class="badge-e">E</span>' : ''}${
            t.local && t.source === 'dz' ? `<span class="local-dot" title="In deiner Bibliothek">${icons.laptop}</span>` : ''
          }<span>${esc(subline)}</span></div>
        </div>
        ${favButton('track', t)}
      </div>`;
    })
    .join('');
}

function albumCard(a) {
  const href = a.source === 'jf' ? `#/jf-album/${a.id}` : `#/album/${a.id}`;
  const sub = [a.artist, a.year].filter(Boolean).join(' · ');
  return html`<a class="card" href="${href}">${img(a.coverSmall ?? a.cover, 'card-art')}
    <div class="card-title">${esc(a.title)}</div><div class="card-sub">${esc(sub)}</div></a>`;
}

function artistCard(a) {
  return html`<a class="card round" href="#/artist/${a.id}">${img(a.pictureSmall ?? a.picture, 'card-art')}
    <div class="card-title">${esc(a.name)}</div></a>`;
}

function section(title, body, more = '') {
  return html`<section class="section"><div class="section-head"><h2>${esc(title)}</h2>${more}</div>${body}</section>`;
}

function skeleton(rows = 8) {
  return Array.from({ length: rows }, () => '<div class="skel-row"><div class="skel a"></div><div class="skel b"></div></div>').join('');
}

function errorBox(err) {
  return html`<div class="empty">${icons.note}<h3>Das hat nicht geklappt</h3><p>${esc(err.message)}</p></div>`;
}

function view(markup, cls = '') {
  const el = document.createElement('div');
  el.className = `view ${cls}`;
  el.append(toFragment(markup));
  return el;
}

const backButton = () => `<button class="back-btn" data-action="back" aria-label="Zurück">${icons.back}</button>`;

/** Markiert den laufenden Titel in allen sichtbaren Listen. */
export function markPlaying() {
  const t = player.current;
  const key = t ? `${t.source}:${t.id}` : '';
  document.body.classList.toggle('paused', !player.playing);
  for (const row of document.querySelectorAll('.row.playing')) {
    if (row.dataset.track !== key) {
      row.classList.remove('playing');
      row.querySelector('.eq')?.remove();
    }
  }
  if (!key) return;
  for (const row of document.querySelectorAll(`.row[data-track="${CSS.escape(key)}"]`)) {
    if (row.classList.contains('playing')) continue;
    row.classList.add('playing');
    row.querySelector('.row-sub')?.prepend(toFragment('<span class="eq"><i></i><i></i><i></i></span>'));
  }
}

// ---------------------------------------------------------------------------
// Suche (bleibt im Speicher, damit Eingabe und Scrollposition erhalten bleiben)
// ---------------------------------------------------------------------------

let searchEl;
const searchState = { q: '', filter: 'all', results: null, controller: null };

export function searchView() {
  if (searchEl) return { el: searchEl, keep: true };

  searchEl = view(html`
    <header class="page-head">
      <h1 class="large-title">Suchen</h1>
      <label class="searchbar">
        ${icons.search}
        <input type="search" placeholder="Songs, Alben, Künstler" enterkeyhint="search" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
        <button class="search-clear hidden" type="button" aria-label="Leeren">${icons.close}</button>
      </label>
      <div class="segmented hidden">
        <button data-filter="all" class="on">Alle</button>
        <button data-filter="tracks">Songs</button>
        <button data-filter="albums">Alben</button>
        <button data-filter="artists">Künstler</button>
      </div>
    </header>
    <div class="search-body"></div>
  `);

  const input = searchEl.querySelector('input');
  const clear = searchEl.querySelector('.search-clear');
  const seg = searchEl.querySelector('.segmented');
  const body = searchEl.querySelector('.search-body');

  const run = debounce(async (q) => {
    searchState.controller?.abort();
    if (!q) {
      searchState.results = null;
      renderHome(body);
      return;
    }
    const controller = new AbortController();
    searchState.controller = controller;
    if (!searchState.results) body.innerHTML = skeleton();
    try {
      const results = await api.search(q, controller.signal);
      if (controller.signal.aborted) return;
      searchState.results = results;
      renderResults(body);
      api.prefetch(results.tracks.filter((t) => !t.local).slice(0, 6).map((t) => t.id));
    } catch (err) {
      if (err.name !== 'AbortError') body.innerHTML = errorBox(err);
    }
  }, 280);

  input.addEventListener('input', () => {
    const q = input.value.trim();
    searchState.q = q;
    clear.classList.toggle('hidden', !input.value);
    seg.classList.toggle('hidden', !q);
    run(q);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') input.blur();
  });
  clear.addEventListener('click', (e) => {
    e.preventDefault();
    input.value = '';
    input.dispatchEvent(new Event('input'));
    input.focus();
  });
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-filter]');
    if (!b) return;
    setFilter(b.dataset.filter);
  });
  body.addEventListener('click', (e) => {
    const more = e.target.closest('[data-show]');
    if (more) {
      e.preventDefault();
      setFilter(more.dataset.show);
    }
  });

  function setFilter(filter) {
    searchState.filter = filter;
    for (const b of seg.querySelectorAll('button')) b.classList.toggle('on', b.dataset.filter === filter);
    renderResults(body);
    window.scrollTo({ top: 0 });
  }

  renderHome(body);
  return { el: searchEl };
}

function installHint() {
  const standalone = navigator.standalone || matchMedia('(display-mode: standalone)').matches;
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
  let dismissed = false;
  try {
    dismissed = localStorage.getItem('tonspur:hint') === '1';
  } catch {}
  if (standalone || !ios || dismissed) return '';
  return html`<div class="status-grid" style="margin-top:8px"><div class="status-item" data-action="dismiss-hint">
    <span class="dot ok"></span><span>Als App installieren: <b>Teilen</b> → <b>Zum Home-Bildschirm</b></span>
    <span class="detail">${icons.close.replace('<svg', '<svg width="14" height="14"')}</span></div></div>`;
}

async function renderHome(body) {
  body.innerHTML = installHint() + skeleton(6);
  try {
    const c = await api.charts();
    if (searchState.q) return;
    body.innerHTML =
      installHint() +
      section('Top Songs', `<div class="list">${trackRows(c.tracks.slice(0, 12))}</div>`) +
      section('Top Alben', `<div class="shelf">${c.albums.map(albumCard).join('')}</div>`) +
      section('Künstler', `<div class="shelf artists">${c.artists.map(artistCard).join('')}</div>`);
    markPlaying();
    api.prefetch(c.tracks.slice(0, 4).map((t) => t.id));
  } catch (err) {
    body.innerHTML = errorBox(err);
  }
}

function renderResults(body) {
  const r = searchState.results;
  if (!r) return;
  const { filter } = searchState;
  const empty = !r.tracks.length && !r.albums.length && !r.artists.length && !r.local.length;
  if (empty) {
    body.innerHTML = html`<div class="empty">${icons.search}<h3>Keine Treffer</h3><p>„${esc(searchState.q)}“ gibt es weder bei Deezer noch auf dem Mac Mini.</p></div>`;
    return;
  }

  let out = '';
  if (filter === 'all') {
    if (r.tracks.length) {
      out += section(
        'Songs',
        `<div class="list">${trackRows(r.tracks.slice(0, 6))}</div>`,
        r.tracks.length > 6 ? '<a class="more" href="#" data-show="tracks">Alle</a>' : '',
      );
    }
    if (r.artists.length) out += section('Künstler', `<div class="shelf artists">${r.artists.map(artistCard).join('')}</div>`);
    if (r.albums.length) out += section('Alben', `<div class="shelf">${r.albums.map(albumCard).join('')}</div>`);
    if (r.local.length) out += section('Auf deinem Mac Mini', `<div class="list">${trackRows(r.local)}</div>`);
  } else if (filter === 'tracks') {
    out = `<div class="list" style="margin-top:8px">${trackRows(r.tracks)}</div>`;
  } else if (filter === 'albums') {
    out = `<div class="grid" style="margin-top:12px">${r.albums.map(albumCard).join('')}</div>`;
  } else if (filter === 'artists') {
    out = `<div class="grid" style="margin-top:12px">${r.artists.map(artistCard).join('')}</div>`;
  }
  body.innerHTML = out;
  markPlaying();
}

// ---------------------------------------------------------------------------
// Album
// ---------------------------------------------------------------------------

function albumMarkup(a, { downloadable }) {
  const total = a.tracks.reduce((s, t) => s + (t.duration || 0), 0);
  const listId = registerList(a.tracks);
  const meta = [a.recordType === 'single' ? 'Single' : a.recordType === 'ep' ? 'EP' : 'Album', a.year, `${a.tracks.length} Titel`, total ? fmtDuration(total) : null]
    .filter(Boolean)
    .join(' · ');
  const artistLink = a.artistId
    ? `<a class="hero-sub" href="#/artist/${a.artistId}">${esc(a.artist)}</a>`
    : `<div class="hero-sub">${esc(a.artist)}</div>`;

  return html`
    ${backButton()}
    <div class="hero">
      <div class="hero-glow">${img(a.coverSmall ?? a.cover, '')}</div>
      ${img(a.cover, 'hero-art', a.title)}
      <h1>${esc(a.title)}</h1>
      ${artistLink}
      <div class="hero-meta">${esc(meta)}</div>
    </div>
    <div class="actions">
      <button class="btn" data-play-list="${listId}">${icons.play} Abspielen</button>
      <button class="btn" data-shuffle-list="${listId}">${icons.shuffle} Zufall</button>
      ${favButton('album', a, 'btn fav')}
      ${downloadable ? `<button class="btn fav" data-download-album="${a.id}" aria-label="Album laden">${icons.download}</button>` : ''}
    </div>
    <div class="list">${trackRows(a.tracks, { numbered: true, sub: (t) => [t.artist !== a.artist ? t.artist : '', fmtTime(t.duration)].filter(Boolean).join(' · ') })}</div>
    ${a.label ? `<div class="footnote">${esc(a.label)}</div>` : ''}
  `;
}

export async function albumView(id) {
  const a = await api.album(id);
  api.prefetch(a.tracks.slice(0, 3).map((t) => t.id));
  return { el: view(albumMarkup(a, { downloadable: true })) };
}

export async function jfAlbumView(id) {
  const a = await api.jfAlbum(id);
  return { el: view(albumMarkup(a, { downloadable: false })) };
}

// ---------------------------------------------------------------------------
// Künstler
// ---------------------------------------------------------------------------

export async function artistView(id) {
  const a = await api.artist(id);
  const albums = a.albums.filter((x) => x.recordType === 'album');
  const singles = a.albums.filter((x) => x.recordType !== 'album');
  const listId = registerList(a.top);
  api.prefetch(a.top.slice(0, 3).map((t) => t.id));

  return {
    el: view(html`
      ${backButton()}
      <div class="artist-hero">${img(a.picture, '', a.name)}<h1>${esc(a.name)}</h1></div>
      <div class="actions">
        <button class="btn" data-play-list="${listId}">${icons.play} Abspielen</button>
        <button class="btn" data-shuffle-list="${listId}">${icons.shuffle} Zufall</button>
      </div>
      ${a.top.length ? section('Beliebte Titel', `<div class="list">${trackRows(a.top, { sub: (t) => t.album })}</div>`) : ''}
      ${albums.length ? section('Alben', `<div class="shelf">${albums.map(albumCard).join('')}</div>`) : ''}
      ${singles.length ? section('Singles & EPs', `<div class="shelf">${singles.map(albumCard).join('')}</div>`) : ''}
    `),
  };
}

// ---------------------------------------------------------------------------
// Bibliothek
// ---------------------------------------------------------------------------

const LIB_TABS = [
  ['songs', 'Songs'],
  ['albums', 'Alben'],
  ['local', 'Mac Mini'],
  ['downloads', 'Downloads'],
  ['status', 'Status'],
];

export function libraryView() {
  let tab = 'songs';
  try {
    tab = localStorage.getItem('tonspur:libtab') ?? 'songs';
  } catch {}
  let timer;

  const el = view(html`
    <header class="page-head">
      <h1 class="large-title">Bibliothek</h1>
      <div class="segmented">${LIB_TABS.map(([k, label]) => `<button data-tab="${k}">${label}</button>`).join('')}</div>
    </header>
    <div class="lib-body"></div>
  `);
  const body = el.querySelector('.lib-body');
  const seg = el.querySelector('.segmented');

  async function render() {
    clearInterval(timer);
    for (const b of seg.querySelectorAll('button')) b.classList.toggle('on', b.dataset.tab === tab);
    try {
      localStorage.setItem('tonspur:libtab', tab);
    } catch {}
    const current = tab;
    try {
      if (tab === 'songs') renderSongs();
      else if (tab === 'albums') renderAlbums();
      else if (tab === 'local') {
        body.innerHTML = skeleton(4);
        const albums = await api.libraryAlbums();
        if (current !== tab) return;
        body.innerHTML = albums.length
          ? section('Zuletzt hinzugefügt', `<div class="grid">${albums.map(albumCard).join('')}</div>`)
          : emptyState('Noch nichts auf dem Mac Mini', 'Songs, die du hörst oder likest, landen automatisch hier.');
      } else if (tab === 'downloads') {
        await renderDownloads();
        timer = setInterval(() => renderDownloads().catch(() => {}), 3000);
      } else if (tab === 'status') {
        body.innerHTML = skeleton(3);
        const h = await api.health();
        if (current !== tab) return;
        renderStatus(h);
      }
    } catch (err) {
      if (current === tab) body.innerHTML = errorBox(err);
    }
  }

  const emptyState = (title, text) => html`<div class="empty">${icons.heart}<h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;

  function renderSongs() {
    const tracks = favs.tracks;
    if (!tracks.length) {
      body.innerHTML = emptyState('Noch keine Lieblingssongs', 'Tippe auf das Herz bei einem Song. Er wird dann automatisch in voller Qualität auf den Mac Mini geladen.');
      return;
    }
    const listId = registerList(tracks);
    body.innerHTML = html`<div class="actions">
        <button class="btn" data-play-list="${listId}">${icons.play} Abspielen</button>
        <button class="btn" data-shuffle-list="${listId}">${icons.shuffle} Zufall</button>
      </div><div class="list">${trackRows(tracks)}</div>`;
    markPlaying();
  }

  function renderAlbums() {
    body.innerHTML = favs.albums.length
      ? `<div class="grid" style="margin-top:12px">${favs.albums.map(albumCard).join('')}</div>`
      : emptyState('Noch keine Alben', 'Tippe auf das Herz bei einem Album, um es komplett in die Bibliothek zu laden.');
  }

  async function renderDownloads() {
    const jobs = await api.downloads();
    if (tab !== 'downloads') return;
    if (!jobs.length) {
      body.innerHTML = html`<div class="empty">${icons.download}<h3>Keine Downloads</h3><p>Sobald du einen Song ein paar Sekunden hörst oder likest, erscheint er hier.</p></div>`;
      return;
    }
    const label = { queued: 'Wartet', downloading: 'Lädt', done: 'Fertig', skipped: 'Vorhanden', failed: 'Fehler' };
    body.innerHTML = html`<div class="actions"><button class="btn small" data-action="clear-downloads">Erledigte ausblenden</button></div>
      <div class="list">${jobs
        .map(
          (j) => html`<div class="row" ${j.status === 'failed' ? `data-retry="${j.type}:${j.id}"` : ''}>
          ${img(j.cover, 'row-art')}
          <div class="row-meta">
            <div class="row-title">${esc(j.title)}</div>
            <div class="row-sub"><span>${esc([j.artist, j.type === 'album' ? 'Album' : null, j.error].filter(Boolean).join(' · '))}</span></div>
            ${j.status === 'downloading' ? `<div class="job-bar"><span style="width:${j.progress}%"></span></div>` : ''}
          </div>
          <span class="job-status ${j.status}">${j.status === 'failed' ? 'Erneut' : label[j.status] ?? j.status}</span>
        </div>`,
        )
        .join('')}</div>`;
  }

  function renderStatus(h) {
    const row = (name, s, okText) => html`<div class="status-item"><span class="dot ${s.ok ? 'ok' : 'bad'}"></span><span>${name}</span>
      <span class="detail">${esc(s.ok ? okText : s.error ?? 'nicht erreichbar')}</span></div>`;
    body.innerHTML = html`<div class="status-grid" style="margin-top:12px">
      ${row('Jellyfin', h.jellyfin, `${h.jellyfin.name ?? ''} ${h.jellyfin.version ?? ''}`.trim())}
      ${row('Deemix', h.deemix, h.deemix.loggedIn ? 'eingeloggt' : 'erreichbar')}
      ${row('yt-dlp (Sofort-Stream)', h.ytdlp, h.ytdlp.version ?? '')}
      ${row('Auto-Download beim Hören', { ok: h.autoDownloadOnPlay, error: 'aus' }, 'an')}
      ${row('Service Worker', { ok: Boolean(navigator.serviceWorker?.controller), error: isSecureContext ? 'lädt…' : 'braucht HTTPS' }, 'aktiv')}
    </div>
    <p class="footnote">Ohne yt-dlp spielt die Sofort-Wiedergabe nur 30-Sekunden-Vorschauen, bis der Song in Jellyfin liegt.</p>`;
  }

  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-tab]');
    if (!b || b.dataset.tab === tab) return;
    tab = b.dataset.tab;
    render();
  });

  body.addEventListener('click', async (e) => {
    const retry = e.target.closest('[data-retry]');
    if (retry) {
      const [type, id] = retry.dataset.retry.split(':');
      await api.download(type, id, 'manual', true).catch((err) => toast(err.message));
      renderDownloads();
    }
    if (e.target.closest('[data-action="clear-downloads"]')) {
      await api.clearDownloads();
      renderDownloads();
    }
  });

  const onFavs = () => {
    if (tab === 'songs') renderSongs();
    if (tab === 'albums') renderAlbums();
  };
  document.addEventListener('favorites', onFavs);

  render();
  return {
    el,
    cleanup() {
      clearInterval(timer);
      document.removeEventListener('favorites', onFavs);
    },
  };
}
