// Öffentliche Deezer-API (ohne Login) für Suche, Metadaten, Charts und 30-s-Vorschauen.
import { HttpError, TtlCache } from './util.js';

// DEEZER_API_URL nur zum Testen gegen einen Mock
const API = (process.env.DEEZER_API_URL || 'https://api.deezer.com').replace(/\/+$/, '');
const cache = new TtlCache(10 * 60 * 1000, 1000);

async function dz(path) {
  const res = await fetch(API + path, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new HttpError(502, `Deezer ${res.status}`);
  const json = await res.json();
  if (json.error) {
    const status = json.error.code === 800 ? 404 : 502;
    throw new HttpError(status, `Deezer: ${json.error.message}`);
  }
  return json;
}

const cached = (path, ttl) => cache.wrap(path, () => dz(path), ttl);

export function mapTrack(t, album) {
  const a = t.album ?? album ?? {};
  return {
    id: String(t.id),
    source: 'dz',
    title: t.title,
    artist: t.artist?.name ?? '',
    artistId: t.artist?.id ? String(t.artist.id) : null,
    album: a.title ?? '',
    albumId: a.id ? String(a.id) : null,
    cover: a.cover_xl ?? a.cover_big ?? null,
    coverSmall: a.cover_medium ?? a.cover_small ?? null,
    duration: t.duration ?? 0,
    preview: t.preview || null,
    explicit: Boolean(t.explicit_lyrics),
    isrc: t.isrc ?? null,
  };
}

export function mapAlbum(a) {
  return {
    id: String(a.id),
    source: 'dz',
    title: a.title,
    artist: a.artist?.name ?? '',
    artistId: a.artist?.id ? String(a.artist.id) : null,
    cover: a.cover_xl ?? a.cover_big ?? null,
    coverSmall: a.cover_medium ?? null,
    year: a.release_date ? a.release_date.slice(0, 4) : null,
    recordType: a.record_type ?? null,
    trackCount: a.nb_tracks ?? null,
  };
}

export function mapArtist(a) {
  return {
    id: String(a.id),
    source: 'dz',
    name: a.name,
    picture: a.picture_xl ?? a.picture_big ?? null,
    pictureSmall: a.picture_medium ?? null,
    fans: a.nb_fan ?? null,
  };
}

export async function search(q) {
  const term = encodeURIComponent(q);
  const [tracks, albums, artists] = await Promise.all([
    cached(`/search?q=${term}&limit=30`, 5 * 60 * 1000),
    cached(`/search/album?q=${term}&limit=15`, 5 * 60 * 1000),
    cached(`/search/artist?q=${term}&limit=10`, 5 * 60 * 1000),
  ]);
  return {
    tracks: tracks.data.map((t) => mapTrack(t)),
    albums: albums.data.map(mapAlbum),
    artists: artists.data.map(mapArtist),
  };
}

export async function chart() {
  const c = await cached('/chart/0?limit=30', 60 * 60 * 1000);
  return {
    tracks: c.tracks.data.map((t) => mapTrack(t)),
    albums: c.albums.data.map(mapAlbum),
    artists: c.artists.data.map(mapArtist),
  };
}

export async function track(id) {
  return mapTrack(await cached(`/track/${encodeURIComponent(id)}`, 60 * 60 * 1000));
}

export async function album(id) {
  const a = await cached(`/album/${encodeURIComponent(id)}`, 60 * 60 * 1000);
  let tracks = a.tracks?.data ?? [];
  if (a.nb_tracks > tracks.length) {
    const all = await cached(`/album/${encodeURIComponent(id)}/tracks?limit=500`, 60 * 60 * 1000);
    tracks = all.data;
  }
  return {
    ...mapAlbum(a),
    label: a.label ?? null,
    duration: a.duration ?? null,
    tracks: tracks.map((t) => mapTrack(t, a)),
  };
}

export async function artist(id) {
  const key = encodeURIComponent(id);
  const [a, top, albums] = await Promise.all([
    cached(`/artist/${key}`, 60 * 60 * 1000),
    cached(`/artist/${key}/top?limit=10`, 60 * 60 * 1000),
    cached(`/artist/${key}/albums?limit=100`, 60 * 60 * 1000),
  ]);
  return {
    ...mapArtist(a),
    top: top.data.map((t) => mapTrack(t)),
    albums: albums.data
      .map((al) => mapAlbum({ ...al, artist: al.artist ?? a }))
      .sort((x, y) => (y.year ?? '').localeCompare(x.year ?? '')),
  };
}
