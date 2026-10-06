// Dünner Wrapper um das Backend. Lesende Antworten werden kurz im Speicher gehalten,
// damit Zurück-Navigation ohne Ladezeit funktioniert.
const memo = new Map();

async function request(path, { method = 'GET', body, signal } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    signal,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data;
}

function cached(path, ttl = 5 * 60 * 1000, opts) {
  const hit = memo.get(path);
  if (hit && hit.until > Date.now()) return hit.promise;
  const promise = request(path, opts).catch((err) => {
    memo.delete(path);
    throw err;
  });
  memo.set(path, { promise, until: Date.now() + ttl });
  return promise;
}

export const api = {
  search: (q, signal) => request(`/search?q=${encodeURIComponent(q)}`, { signal }),
  charts: () => cached('/charts', 30 * 60 * 1000),
  album: (id) => cached(`/album/${id}`),
  artist: (id) => cached(`/artist/${id}`),
  jfAlbum: (id) => cached(`/jf/album/${id}`, 60 * 1000),
  libraryAlbums: () => request('/library/albums'),
  favorites: () => request('/favorites'),
  addFavorite: (type, item) => request('/favorites', { method: 'POST', body: { type, item } }),
  removeFavorite: (type, item) => request(`/favorites/${type}/${item.source}/${item.id}`, { method: 'DELETE' }),
  download: (type, id, reason = 'manual', force = false) =>
    request('/download', { method: 'POST', body: { type, id, reason, force } }),
  downloads: () => request('/downloads'),
  clearDownloads: () => request('/downloads', { method: 'DELETE' }),
  source: (id) => request(`/source/dz/${id}`),
  prefetch: (ids) => {
    const list = ids.filter(Boolean);
    if (!list.length) return Promise.resolve();
    return request('/prefetch', { method: 'POST', body: { ids: list } }).catch(() => {});
  },
  health: () => request('/health'),
};

export const streamUrl = (track) => `/api/stream/${track.source}/${encodeURIComponent(track.id)}`;
