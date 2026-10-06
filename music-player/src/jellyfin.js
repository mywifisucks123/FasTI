// Jellyfin: Bibliothek durchsuchen, Songs streamen, Scan anstoßen.
import { config } from './config.js';
import { HttpError, TtlCache, log, norm } from './util.js';

const { url: BASE, apiKey } = config.jellyfin;
const cache = new TtlCache(60 * 1000, 500);

export const isConfigured = () => Boolean(apiKey);

export function authHeaders() {
  return {
    Authorization: `MediaBrowser Client="Tonspur", Device="Mac Mini", DeviceId="tonspur-backend", Version="1.0.0", Token="${apiKey}"`,
  };
}

async function jf(path, { method = 'GET', timeout = 8000 } = {}) {
  if (!apiKey) throw new HttpError(503, 'JELLYFIN_API_KEY fehlt');
  const res = await fetch(BASE + path, {
    method,
    headers: { ...authHeaders(), Accept: 'application/json' },
    signal: AbortSignal.timeout(timeout),
  });
  if (!res.ok) throw new HttpError(res.status === 401 ? 502 : res.status, `Jellyfin ${res.status} ${path}`);
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

let userIdPromise;
export function userId() {
  if (config.jellyfin.userId) return Promise.resolve(config.jellyfin.userId);
  userIdPromise ??= jf('/Users')
    .then((users) => {
      const user = users.find((u) => u.Policy?.IsAdministrator) ?? users[0];
      if (!user) throw new HttpError(502, 'Kein Jellyfin-User gefunden');
      log('jellyfin', `nutze User "${user.Name}"`);
      return user.Id;
    })
    .catch((err) => {
      userIdPromise = undefined;
      throw err;
    });
  return userIdPromise;
}

const FIELDS = 'Fields=PrimaryImageAspectRatio,DateCreated,ProductionYear';

async function items(query) {
  const uid = await userId();
  const res = await jf(`/Items?userId=${uid}&Recursive=true&${FIELDS}&${query}`);
  return res?.Items ?? [];
}

const image = (id) => (id ? `/api/jf/image/${id}` : null);

export function mapTrack(i) {
  const coverId = i.AlbumPrimaryImageTag ? i.AlbumId : i.ImageTags?.Primary ? i.Id : null;
  return {
    id: i.Id,
    source: 'jf',
    title: i.Name,
    artist: i.Artists?.length ? i.Artists.join(', ') : i.AlbumArtist ?? '',
    artistId: null,
    album: i.Album ?? '',
    albumId: i.AlbumId ?? null,
    cover: image(coverId),
    coverSmall: image(coverId),
    duration: i.RunTimeTicks ? Math.round(i.RunTimeTicks / 1e7) : 0,
    preview: null,
    local: true,
  };
}

export function mapAlbum(i) {
  return {
    id: i.Id,
    source: 'jf',
    title: i.Name,
    artist: i.AlbumArtist ?? i.Artists?.join(', ') ?? '',
    artistId: null,
    cover: i.ImageTags?.Primary ? image(i.Id) : null,
    coverSmall: i.ImageTags?.Primary ? image(i.Id) : null,
    year: i.ProductionYear ? String(i.ProductionYear) : null,
  };
}

export async function searchTracks(term, limit = 25) {
  if (!term) return [];
  const list = await items(
    `IncludeItemTypes=Audio&Limit=${limit}&searchTerm=${encodeURIComponent(term)}`,
  );
  return list.map(mapTrack);
}

export async function recentAlbums(limit = 40) {
  const list = await items(
    `IncludeItemTypes=MusicAlbum&SortBy=DateCreated&SortOrder=Descending&Limit=${limit}`,
  );
  return list.map(mapAlbum);
}

export async function album(id) {
  const uid = await userId();
  const [meta, tracks] = await Promise.all([
    jf(`/Items?userId=${uid}&Ids=${encodeURIComponent(id)}&${FIELDS}`),
    items(
      `ParentId=${encodeURIComponent(id)}&IncludeItemTypes=Audio&SortBy=ParentIndexNumber,IndexNumber,SortName`,
    ),
  ]);
  const a = meta?.Items?.[0];
  if (!a) throw new HttpError(404, 'Album nicht gefunden');
  return { ...mapAlbum(a), tracks: tracks.map(mapTrack) };
}

/** Prüft, ob ein Deezer-Track schon in Jellyfin liegt. */
export function matches(dzTrack, jfTrack) {
  const t1 = norm(dzTrack.title);
  const t2 = norm(jfTrack.title);
  if (!t1 || t1 !== t2) return false;
  const artist = norm(dzTrack.artist);
  const artistOk = artist && norm(jfTrack.artist).includes(artist);
  const durOk =
    dzTrack.duration && jfTrack.duration && Math.abs(dzTrack.duration - jfTrack.duration) <= 4;
  return Boolean(artistOk || durOk);
}

export async function findLocal(dzTrack) {
  if (!isConfigured()) return null;
  return cache.wrap(`match:${dzTrack.id}`, async () => {
    const cleaned = dzTrack.title.replace(/\s*[([].*?[)\]]\s*/g, ' ').trim();
    let found = await searchTracks(cleaned, 30);
    if (!found.length) {
      const short = cleaned.split(/\s+/).slice(0, 3).join(' ');
      if (short !== cleaned) found = await searchTracks(short, 50);
    }
    return found.find((t) => matches(dzTrack, t)) ?? null;
  });
}

export function forgetMatches() {
  cache.map.clear();
}

export function streamUrl(id) {
  const safe = encodeURIComponent(id);
  if (config.jellyfin.streamMode === 'mp3') {
    return `${BASE}/Audio/${safe}/stream.mp3?audioCodec=mp3&audioBitRate=320000`;
  }
  return `${BASE}/Audio/${safe}/stream?static=true`;
}

export function imageUrl(id, size) {
  return `${BASE}/Items/${encodeURIComponent(id)}/Images/Primary?fillWidth=${size}&fillHeight=${size}&quality=90`;
}

export async function refreshLibrary() {
  const { libraryId } = config.jellyfin;
  if (libraryId) {
    await jf(
      `/Items/${libraryId}/Refresh?Recursive=true&MetadataRefreshMode=Default&ImageRefreshMode=Default&ReplaceAllMetadata=false&ReplaceAllImages=false`,
      { method: 'POST' },
    );
  } else {
    await jf('/Library/Refresh', { method: 'POST' });
  }
  log('jellyfin', 'Bibliothek-Scan gestartet');
}

export async function ping() {
  const info = await jf('/System/Info', { timeout: 4000 });
  return { ok: true, version: info?.Version ?? null, name: info?.ServerName ?? null };
}
