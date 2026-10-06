import { api } from './api.js';
import { player } from './player.js';
import { fmtTime, haptic, icons, placeholder, toast } from './ui.js';
import {
  albumView,
  artistView,
  items,
  jfAlbumView,
  libraryView,
  lists,
  loadFavorites,
  markPlaying,
  searchView,
  toggleFavorite,
  isFav,
  favKey,
} from './views.js';

const $ = (sel, root = document) => root.querySelector(sel);
const root = $('#view');

// Icons in statisches Markup setzen
for (const el of document.querySelectorAll('[data-icon]')) el.innerHTML = icons[el.dataset.icon];
$('.mini-next').innerHTML = icons.next;
$('[data-action="prev"]', $('#now')).innerHTML = icons.prev;
$('.controls [data-action="next"]').innerHTML = icons.next;
$('[data-action="shuffle"]').innerHTML = icons.shuffle;
$('[data-action="repeat"]').innerHTML = icons.repeat;
$('[data-action="airplay"]').innerHTML = icons.airplay;

// ---------------------------------------------------------------------------
// Router (Hash-basiert, mit Richtungserkennung für die Slide-Animation)
// ---------------------------------------------------------------------------

history.scrollRestoration = 'manual';

const routes = [
  [/^\/?$/, 'search', () => searchView()],
  [/^\/album\/(\w+)$/, 'search', (m) => albumView(m[1])],
  [/^\/artist\/(\w+)$/, 'search', (m) => artistView(m[1])],
  [/^\/library$/, 'library', () => libraryView()],
  [/^\/jf-album\/(\w+)$/, 'library', (m) => jfAlbumView(m[1])],
];

const stack = [];
const scrollPos = new Map();
let mounted = null;
let navToken = 0;

async function route() {
  const hash = location.hash.slice(1) || '/';
  const token = ++navToken;
  const back = stack.length > 1 && stack[stack.length - 2] === hash;
  if (back) stack.pop();
  else if (stack[stack.length - 1] !== hash) stack.push(hash);
  if (stack.length > 50) stack.shift();

  if (mounted) {
    scrollPos.set(mounted.hash, window.scrollY);
    mounted.cleanup?.();
  }

  const match = routes.find(([re]) => re.test(hash));
  if (!match) {
    location.replace('#/');
    return;
  }
  const [re, tab, factory] = match;
  for (const a of document.querySelectorAll('.tabbar a')) a.classList.toggle('on', a.dataset.tab === tab);

  // Ladezustand nur zeigen, wenn es spürbar dauert
  const spinner = setTimeout(() => {
    if (token === navToken) {
      root.replaceChildren();
      root.insertAdjacentHTML('beforeend', '<div class="empty" style="padding-top:40vh"><div class="spinner" style="margin:auto"></div></div>');
    }
  }, 150);

  let result;
  try {
    result = await factory(hash.match(re));
  } catch (err) {
    result = {
      el: Object.assign(document.createElement('div'), {
        className: 'view',
        innerHTML: `<button class="back-btn" data-action="back">${icons.back}</button><div class="empty" style="padding-top:30vh"><h3>Konnte nicht laden</h3><p>${err.message}</p></div>`,
      }),
    };
  }
  clearTimeout(spinner);
  if (token !== navToken) return;

  result.el.classList.remove('back', 'fade');
  void result.el.offsetWidth;
  result.el.classList.add(back ? 'back' : mounted && tab !== mounted.tab ? 'fade' : 'view');
  root.replaceChildren(result.el);
  mounted = { hash, tab, cleanup: result.cleanup };

  window.scrollTo(0, back || result.keep ? scrollPos.get(hash) ?? 0 : 0);
  markPlaying();
  updateHeads();
}

window.addEventListener('hashchange', route);

function goBack() {
  if (stack.length > 1) history.back();
  else location.hash = '#/';
}

// Kopfzeile bekommt beim Scrollen den Blur-Hintergrund
function updateHeads() {
  const head = root.querySelector('.page-head');
  head?.classList.toggle('scrolled', window.scrollY > 8);
}
window.addEventListener('scroll', updateHeads, { passive: true });

// Tab erneut antippen → nach oben scrollen bzw. zurück zur Wurzel
document.querySelector('.tabbar').addEventListener('click', (e) => {
  const a = e.target.closest('a');
  if (!a) return;
  const target = a.getAttribute('href');
  if (location.hash === target || (target === '#/' && !location.hash)) {
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
});

// ---------------------------------------------------------------------------
// Globale Klick-Delegation
// ---------------------------------------------------------------------------

document.addEventListener('click', (e) => {
  const t = e.target;

  const fav = t.closest('[data-fav]');
  if (fav) {
    e.stopPropagation();
    const item = items.get(fav.dataset.favKey);
    if (item) {
      haptic();
      toggleFavorite(fav.dataset.fav, item);
    }
    return;
  }

  const playBtn = t.closest('[data-play-list]');
  if (playBtn) {
    player.playList(lists.get(playBtn.dataset.playList) ?? [], 0);
    return;
  }
  const shuffleBtn = t.closest('[data-shuffle-list]');
  if (shuffleBtn) {
    player.playList(lists.get(shuffleBtn.dataset.shuffleList) ?? [], -1, { shuffle: true });
    return;
  }

  const dl = t.closest('[data-download-album]');
  if (dl) {
    api
      .download('album', dl.dataset.downloadAlbum, 'manual')
      .then(() => toast('Album wird in die Bibliothek geladen'))
      .catch((err) => toast(`Fehler: ${err.message}`));
    return;
  }

  const row = t.closest('.row[data-list]');
  if (row) {
    const list = lists.get(row.dataset.list);
    if (list) player.playList(list, Number(row.dataset.idx));
    return;
  }

  const action = t.closest('[data-action]')?.dataset.action;
  if (!action) return;
  switch (action) {
    case 'back':
      goBack();
      break;
    case 'toggle':
      e.stopPropagation();
      player.toggle();
      break;
    case 'next':
      e.stopPropagation();
      player.next();
      break;
    case 'prev':
      player.prev();
      break;
    case 'close-now':
      closeNow();
      break;
    case 'fav-current':
      if (player.current) toggleFavorite('track', player.current);
      break;
    case 'goto-artist':
      if (player.current?.artistId) {
        closeNow();
        location.hash = `#/artist/${player.current.artistId}`;
      }
      break;
    case 'shuffle':
      player.toggleShuffle();
      break;
    case 'repeat':
      player.cycleRepeat();
      break;
    case 'airplay':
      player.audio.webkitShowPlaybackTargetPicker?.();
      break;
    case 'dismiss-hint':
      try {
        localStorage.setItem('tonspur:hint', '1');
      } catch {}
      t.closest('.status-grid')?.remove();
      break;
  }
});

// ---------------------------------------------------------------------------
// Mini-Player & Vollbild-Player
// ---------------------------------------------------------------------------

const mini = $('#mini');
const now = $('#now');
const scrub = $('.scrub');
let scrubbing = false;

mini.addEventListener('click', (e) => {
  if (e.target.closest('button')) return;
  openNow();
});

function openNow() {
  now.classList.add('open');
  now.setAttribute('aria-hidden', 'false');
  now.style.transform = '';
}

function closeNow() {
  now.classList.remove('open');
  now.setAttribute('aria-hidden', 'true');
  now.style.transform = '';
}

// Nach unten wischen schließt den Player
let dragStart = null;
now.addEventListener(
  'touchstart',
  (e) => {
    if (e.target.closest('.scrubber, .controls, .now-foot, button')) return;
    dragStart = { y: e.touches[0].clientY, t: Date.now() };
  },
  { passive: true },
);
now.addEventListener(
  'touchmove',
  (e) => {
    if (!dragStart) return;
    const dy = Math.max(0, e.touches[0].clientY - dragStart.y);
    now.classList.add('dragging');
    now.style.transform = `translateY(${dy}px)`;
  },
  { passive: true },
);
now.addEventListener('touchend', (e) => {
  if (!dragStart) return;
  const dy = e.changedTouches[0].clientY - dragStart.y;
  const fast = dy > 60 && Date.now() - dragStart.t < 250;
  now.classList.remove('dragging');
  dragStart = null;
  if (dy > 140 || fast) closeNow();
  else now.style.transform = '';
});

scrub.addEventListener('input', () => {
  scrubbing = true;
  const d = player.audio.duration;
  const pos = (scrub.value / 1000) * (Number.isFinite(d) ? d : 0);
  scrub.style.setProperty('--p', `${scrub.value / 10}%`);
  $('.t-cur').textContent = fmtTime(pos);
  $('.t-left').textContent = `-${fmtTime((d || 0) - pos)}`;
});
scrub.addEventListener('change', () => {
  const d = player.audio.duration;
  if (Number.isFinite(d)) player.seek((scrub.value / 1000) * d);
  scrubbing = false;
});

function renderTrack() {
  const t = player.current;
  mini.classList.toggle('hidden', !t);
  if (!t) return;
  const art = t.cover ?? t.coverSmall ?? placeholder;
  $('.mini-art').src = t.coverSmall ?? art;
  $('.mini-title').textContent = t.title;
  $('.mini-artist').textContent = t.artist;
  $('.now-art').src = art;
  $('.now-bg img').src = t.coverSmall ?? art;
  $('.now-title').textContent = t.title;
  $('.now-artist').textContent = t.artist;
  renderFav();
  renderSource();
  markPlaying();
}

function renderFav() {
  const t = player.current;
  if (!t) return;
  const btn = $('.now-fav');
  const key = favKey('track', t);
  items.set(key, t);
  btn.dataset.favKey = key;
  const on = isFav('track', t);
  btn.classList.toggle('on', on);
  btn.innerHTML = on ? icons.heartFill : icons.heart;
}

function renderState() {
  const playing = player.playing;
  const icon = playing ? icons.pause : icons.play;
  for (const b of document.querySelectorAll('[data-action="toggle"]')) b.innerHTML = icon;
  now.classList.toggle('playing', playing);
  markPlaying();
}

function renderTime() {
  const a = player.audio;
  const d = Number.isFinite(a.duration) ? a.duration : player.current?.duration ?? 0;
  const pct = d ? (a.currentTime / d) * 100 : 0;
  $('.mini-progress span').style.width = `${pct}%`;
  if (scrubbing) return;
  scrub.value = String(Math.round(pct * 10));
  scrub.style.setProperty('--p', `${pct}%`);
  $('.t-cur').textContent = fmtTime(a.currentTime);
  $('.t-left').textContent = `-${fmtTime(d - a.currentTime)}`;
}

function renderSource() {
  const el = $('.now-source');
  const label = { jellyfin: 'Bibliothek', youtube: 'Stream', preview: 'Vorschau · 30 s', none: 'Nicht verfügbar' }[player.source] ?? '';
  el.textContent = label;
  el.classList.toggle('preview', player.source === 'preview');
}

function renderModes() {
  $('[data-action="shuffle"]').classList.toggle('on', player.shuffle);
  const rep = $('[data-action="repeat"]');
  rep.classList.toggle('on', player.repeat !== 'off');
  rep.innerHTML = player.repeat === 'one' ? icons.repeat.replace('</svg>', '<text x="12" y="15" font-size="7" text-anchor="middle" font-weight="700">1</text></svg>') : icons.repeat;
}

player.addEventListener('track', renderTrack);
player.addEventListener('state', renderState);
player.addEventListener('time', renderTime);
player.addEventListener('source', renderSource);
player.addEventListener('queue', renderModes);
player.addEventListener('error', () => {
  const msg = player.lastError?.name === 'NotAllowedError' ? 'Zum Abspielen einmal auf Play tippen' : player.lastError?.message ?? 'Wiedergabefehler';
  toast(msg);
  renderState();
});
document.addEventListener('favorites', renderFav);

// AirPlay-Button nur zeigen, wenn Safari ein Ziel findet
if (window.WebKitPlaybackTargetAvailabilityEvent) {
  player.audio.addEventListener('webkitplaybacktargetavailabilitychanged', (e) => {
    $('[data-action="airplay"]').classList.toggle('hidden', e.availability !== 'available');
  });
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

await loadFavorites();
renderTrack();
renderState();
renderTime();
renderModes();
route();

if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch((err) => console.warn('SW:', err));
}
