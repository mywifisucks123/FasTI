// Icons, kleine DOM-Helfer und wiederverwendbare Bausteine.
const svg = (body, viewBox = '0 0 24 24') =>
  `<svg viewBox="${viewBox}" fill="currentColor" aria-hidden="true">${body}</svg>`;

export const icons = {
  play: svg('<path d="M7 4.6v14.8c0 .8.9 1.3 1.6.9l12-7.4a1 1 0 0 0 0-1.8l-12-7.4C7.9 3.3 7 3.8 7 4.6Z"/>'),
  pause: svg('<rect x="5.5" y="4" width="4.5" height="16" rx="1.2"/><rect x="14" y="4" width="4.5" height="16" rx="1.2"/>'),
  next: svg('<path d="M3 6.2v11.6c0 .8.9 1.2 1.5.8l8.3-5.8a1 1 0 0 0 0-1.6L4.5 5.4C3.9 5 3 5.4 3 6.2Zm9 0v11.6c0 .8.9 1.2 1.5.8l8.3-5.8a1 1 0 0 0 0-1.6l-8.3-5.8c-.6-.4-1.5 0-1.5.8Z"/>'),
  prev: svg('<path d="M21 6.2v11.6c0 .8-.9 1.2-1.5.8l-8.3-5.8a1 1 0 0 1 0-1.6l8.3-5.8c.6-.4 1.5 0 1.5.8Zm-9 0v11.6c0 .8-.9 1.2-1.5.8l-8.3-5.8a1 1 0 0 1 0-1.6l8.3-5.8c.6-.4 1.5 0 1.5.8Z"/>'),
  heart: svg('<path fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" d="M12 20.3s-7.8-4.6-9.3-9.6C1.6 7 3.9 3.8 7.3 3.8c2 0 3.6 1.1 4.7 2.8 1.1-1.7 2.7-2.8 4.7-2.8 3.4 0 5.7 3.2 4.6 6.9-1.5 5-9.3 9.6-9.3 9.6Z"/>'),
  heartFill: svg('<path d="M12 20.8c-.2 0-.4 0-.5-.1-.3-.2-8.2-4.9-9.8-10.2C.5 6.4 3.1 2.8 7.3 2.8c1.9 0 3.5.8 4.7 2.2 1.2-1.4 2.8-2.2 4.7-2.2 4.2 0 6.8 3.6 5.6 7.7-1.6 5.3-9.5 10-9.8 10.2-.1.1-.3.1-.5.1Z"/>'),
  search: svg('<path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" d="M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15Zm5.4-2.1L21 21"/>'),
  library: svg('<path d="M4 3.5h2.2v17H4zM8.6 3.5h2.2v17H8.6z"/><path d="m13.2 4.6 2.1-.6 4.7 16-2.1.6z"/>'),
  back: svg('<path fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" d="M15 4.5 7.5 12l7.5 7.5"/>'),
  close: svg('<path fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" d="m6 6 12 12M18 6 6 18"/>'),
  shuffle: svg('<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M3 7h3.5c2 0 3.3 1 4.4 2.7l2.2 4.6c1.1 1.7 2.4 2.7 4.4 2.7H21m0 0-3-3m3 3-3 3M3 17h3.5c1.4 0 2.4-.5 3.3-1.4M21 7h-3.5c-1.4 0-2.4.5-3.3 1.4M21 7l-3-3m3 3-3 3"/>'),
  repeat: svg('<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M17 2.5 20.5 6 17 9.5M3.5 11V9.5A3.5 3.5 0 0 1 7 6h13.5M7 21.5 3.5 18 7 14.5M20.5 13v1.5A3.5 3.5 0 0 1 17 18H3.5"/>'),
  airplay: svg('<path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M6 17H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-1"/><path d="m12 14 5.5 6.5h-11Z"/>'),
  note: svg('<path d="M20 3.2v12.3a3.5 3.5 0 1 1-2-3.2V7.1l-9 2v8.4a3.5 3.5 0 1 1-2-3.2V5.8c0-.5.3-.9.8-1l10.9-2.4c.7-.1 1.3.3 1.3 1Z"/>'),
  check: svg('<path fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" d="m5 12.5 4.5 4.5L19 7.5"/>'),
  download: svg('<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M12 3.5v12m0 0-5-5m5 5 5-5M4.5 20.5h15"/>'),
  laptop: svg('<path d="M5 5.5A1.5 1.5 0 0 1 6.5 4h11A1.5 1.5 0 0 1 19 5.5V15H5V5.5ZM2 16.5h20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Z"/>'),
};

export const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

export function fmtTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function fmtDuration(sec) {
  const min = Math.round(sec / 60);
  return min >= 60 ? `${Math.floor(min / 60)} Std. ${min % 60} Min.` : `${min} Min.`;
}

export function html(strings, ...values) {
  return strings.reduce((out, s, i) => out + s + (i < values.length ? values[i] ?? '' : ''), '');
}

export function toFragment(markup) {
  const t = document.createElement('template');
  t.innerHTML = markup.trim();
  return t.content;
}

const PLACEHOLDER =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#1c1c1e"/><path fill="#3a3a3c" d="M63 30v26a7 7 0 1 1-4-6.3V38l-18 4v18a7 7 0 1 1-4-6.3V36.5c0-1 .7-1.8 1.6-2l21.9-5c1.3-.3 2.5.7 2.5 2Z"/></svg>',
  );
export const placeholder = PLACEHOLDER;

export const img = (src, cls, alt = '') =>
  `<img class="${cls}" src="${esc(src || PLACEHOLDER)}" alt="${esc(alt)}" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${PLACEHOLDER}'">`;

let toastTimer;
export function toast(message) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

export function haptic() {
  // iOS Safari kennt keine Vibration-API; auf Android ein kurzer Tick
  navigator.vibrate?.(8);
}

export function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
