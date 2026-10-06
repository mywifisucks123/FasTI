// Service Worker: App-Shell offline, Cover-Cache, Audio und API immer live.
const VERSION = 'v1.0.0';
const SHELL = `shell-${VERSION}`;
const IMAGES = 'images-v1';
const API = 'api-v1';
const IMAGE_LIMIT = 400;

const SHELL_FILES = [
  '/',
  '/index.html',
  '/css/app.css',
  '/js/app.js',
  '/js/api.js',
  '/js/player.js',
  '/js/ui.js',
  '/js/views.js',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => ![SHELL, IMAGES, API].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - max))) await cache.delete(key);
}

async function cacheFirst(request) {
  const cache = await caches.open(IMAGES);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok || res.type === 'opaque') {
    cache.put(request, res.clone()).then(() => trim(IMAGES, IMAGE_LIMIT));
  }
  return res;
}

async function networkFirst(request) {
  const cache = await caches.open(API);
  try {
    const res = await fetch(request);
    if (res.ok) cache.put(request, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(request);
    if (hit) return hit;
    throw err;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request, { ignoreSearch: true });
  const update = fetch(request)
    .then((res) => {
      if (res.ok) cache.put(request, res.clone());
      return res;
    })
    .catch(() => hit);
  return hit ?? update;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  // Audio nie anfassen: Range-Requests + Service Worker = Ärger auf iOS
  if (url.pathname.startsWith('/api/stream') || request.destination === 'audio') return;

  // Cover von Deezer und Jellyfin
  if (/dzcdn\.net$/.test(url.hostname) || url.pathname.startsWith('/api/jf/image')) {
    event.respondWith(cacheFirst(request));
    return;
  }

  if (url.origin !== self.location.origin) return;

  // Lesende API-Aufrufe: online frisch, offline aus dem Cache
  if (url.pathname.startsWith('/api/')) {
    if (/^\/api\/(charts|album|artist|favorites|library|jf\/album)/.test(url.pathname)) {
      event.respondWith(networkFirst(request));
    }
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(staleWhileRevalidate(new Request('/index.html')));
    return;
  }

  event.respondWith(staleWhileRevalidate(request));
});
