// Entscheidet pro Deezer-Track, woher der Ton kommt:
//   1. Jellyfin (schon in der Bibliothek, volle Qualität)
//   2. YouTube via yt-dlp (kompletter Song, sofort)
//   3. Deezer-Vorschau (30 Sekunden, Notnagel)
import { config } from './config.js';
import * as deezer from './deezer.js';
import * as jellyfin from './jellyfin.js';
import * as yt from './ytdlp.js';
import { Limiter, TtlCache, log, withTimeout } from './util.js';

const ytCache = new TtlCache(3 * 60 * 60 * 1000, 2000);
const ytFailed = new TtlCache(30 * 60 * 1000, 2000);
const limiter = new Limiter(config.yt.concurrency);

async function local(track) {
  try {
    return await jellyfin.findLocal(track);
  } catch (err) {
    log('resolver', `Jellyfin-Abgleich fehlgeschlagen: ${err.message}`);
    return null;
  }
}

function youtube(track, { urgent = false } = {}) {
  const hit = ytCache.get(track.id);
  if (hit && hit.expires - Date.now() > 10 * 60 * 1000) return Promise.resolve(hit);
  if (ytFailed.get(track.id)) return Promise.reject(new Error('kürzlich fehlgeschlagen'));
  if (ytCache.pending.has(track.id)) return ytCache.pending.get(track.id);

  ytCache.delete(track.id);
  return ytCache.wrap(track.id, () =>
    limiter
      .run(() => yt.resolve(track), { urgent })
      .then(
        (r) => {
          log('yt-dlp', `${track.artist} – ${track.title} → ${r.videoId}`);
          return r;
        },
        (err) => {
          ytFailed.set(track.id, true);
          log('yt-dlp', `${track.artist} – ${track.title}: ${err.message}`);
          throw err;
        },
      ),
  );
}

/** Für Prefetch und Status-Anzeige; startet yt-dlp im Hintergrund. */
export async function prefetch(id) {
  const track = await deezer.track(id);
  if (await local(track)) return;
  if (await yt.version()) await youtube(track).catch(() => {});
}

export async function resolve(id, { wait = true } = {}) {
  const track = await deezer.track(id);

  const hit = await local(track);
  if (hit) return { type: 'jellyfin', jellyfinId: hit.id, track };

  if (await yt.version()) {
    const pending = youtube(track, { urgent: true });
    try {
      const r = wait ? await withTimeout(pending, config.yt.resolveTimeoutMs) : ytCache.get(id);
      if (r) return { type: 'youtube', ...r, track };
    } catch {
      // Timeout oder Fehler → Vorschau. yt-dlp läuft weiter und ist beim nächsten Mal fertig.
      pending.catch(() => {});
    }
  }

  if (track.preview) return { type: 'preview', url: track.preview, track };
  return { type: 'none', track };
}

export function invalidateYoutube(id) {
  ytCache.delete(id);
}
