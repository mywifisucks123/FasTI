import express from 'express';
import path from 'node:path';
import { config } from './config.js';
import * as deemix from './deemix.js';
import * as deezer from './deezer.js';
import * as downloads from './downloads.js';
import * as favorites from './favorites.js';
import * as jellyfin from './jellyfin.js';
import { proxy } from './proxy.js';
import * as resolver from './resolver.js';
import { HttpError, log } from './util.js';
import * as yt from './ytdlp.js';

const app = express();
app.disable('x-powered-by');
app.set('trust proxy', true);
app.use(express.json({ limit: '256kb' }));

const api = express.Router();

// --- Suche & Metadaten -------------------------------------------------------

api.get('/search', async (req, res) => {
  const q = String(req.query.q ?? '').trim();
  if (!q) return res.json({ tracks: [], albums: [], artists: [], local: [] });

  const [remote, local] = await Promise.all([
    deezer.search(q),
    jellyfin.isConfigured() ? jellyfin.searchTracks(q, 25).catch(() => []) : [],
  ]);
  // Deezer-Treffer markieren, die schon auf dem Mac Mini liegen
  for (const t of remote.tracks) {
    t.local = local.some((l) => jellyfin.matches(t, l));
  }
  res.json({ ...remote, local: local.slice(0, 8) });
});

api.get('/charts', async (_req, res) => res.json(await deezer.chart()));
api.get('/album/:id', async (req, res) => res.json(await deezer.album(req.params.id)));
api.get('/artist/:id', async (req, res) => res.json(await deezer.artist(req.params.id)));

// --- Streaming ---------------------------------------------------------------

api.get('/stream/dz/:id', async (req, res) => {
  const id = req.params.id;
  for (let attempt = 0; attempt < 2; attempt++) {
    const src = await resolver.resolve(id);
    if (src.type === 'jellyfin') {
      return void (await proxy(req, res, jellyfin.streamUrl(src.jellyfinId), {
        headers: jellyfin.authHeaders(),
      }));
    }
    if (src.type === 'youtube') {
      const status = await proxy(req, res, src.url, {
        headers: src.headers,
        contentType: src.mime,
        retryOn: attempt === 0 ? [403, 410] : undefined,
      });
      if (status === 403 || status === 410) {
        resolver.invalidateYoutube(id);
        continue;
      }
      return;
    }
    if (src.type === 'preview') return res.redirect(302, src.url);
    throw new HttpError(404, 'Keine Audioquelle gefunden');
  }
  throw new HttpError(502, 'Stream nicht verfügbar');
});

api.get('/stream/jf/:id', async (req, res) => {
  await proxy(req, res, jellyfin.streamUrl(req.params.id), { headers: jellyfin.authHeaders() });
});

api.get('/source/dz/:id', async (req, res) => {
  const src = await resolver.resolve(req.params.id, { wait: req.query.wait !== '0' });
  res.json({ type: src.type });
});

api.post('/prefetch', (req, res) => {
  const ids = [...new Set((req.body?.ids ?? []).map(String))].slice(0, 12);
  for (const id of ids) resolver.prefetch(id).catch(() => {});
  res.status(202).json({ ok: true, count: ids.length });
});

// --- Jellyfin-Bibliothek -----------------------------------------------------

api.get('/library/albums', async (_req, res) => res.json(await jellyfin.recentAlbums(60)));
api.get('/jf/album/:id', async (req, res) => res.json(await jellyfin.album(req.params.id)));

api.get('/jf/image/:id', async (req, res) => {
  const size = Math.min(Math.max(Number(req.query.size) || 600, 64), 1200);
  await proxy(req, res, jellyfin.imageUrl(req.params.id, size), {
    headers: jellyfin.authHeaders(),
    cache: 'public, max-age=86400',
  });
});

// --- Downloads & Favoriten ---------------------------------------------------

api.post('/download', async (req, res) => {
  const { type = 'track', id, reason = 'manual', force = false } = req.body ?? {};
  if (!id) throw new HttpError(400, 'id fehlt');
  if (reason === 'play' && !config.autoDownloadOnPlay) return res.status(204).end();
  const job = await downloads.enqueue({ type, id: String(id), reason, force: Boolean(force) });
  res.status(202).json(job);
});

api.get('/downloads', (_req, res) => res.json(downloads.list()));
api.delete('/downloads', (_req, res) => {
  downloads.clearFinished();
  res.json(downloads.list());
});

api.get('/favorites', (_req, res) => res.json(favorites.all()));

api.post('/favorites', async (req, res) => {
  const { type, item } = req.body ?? {};
  if (!item?.id || !item?.source) throw new HttpError(400, 'item fehlt');
  const data = await favorites.add(type, item);
  if (item.source === 'dz') {
    downloads.enqueue({ type, id: item.id, reason: 'favorite' }).catch((err) => log('favorites', err.message));
  }
  res.json(data);
});

api.delete('/favorites/:type/:source/:id', async (req, res) => {
  const { type, source, id } = req.params;
  res.json(await favorites.remove(type, source, id));
});

// --- Status ------------------------------------------------------------------

api.get('/health', async (_req, res) => {
  const settle = (p) =>
    p.then(
      (v) => v,
      (err) => ({ ok: false, error: err.message }),
    );
  const [jf, dm, ytv] = await Promise.all([
    jellyfin.isConfigured() ? settle(jellyfin.ping()) : { ok: false, error: 'JELLYFIN_API_KEY fehlt' },
    settle(deemix.ping()),
    yt.version(),
  ]);
  res.json({
    jellyfin: jf,
    deemix: dm,
    ytdlp: ytv ? { ok: true, version: ytv } : { ok: false, error: config.yt.enabled ? 'nicht installiert' : 'deaktiviert' },
    autoDownloadOnPlay: config.autoDownloadOnPlay,
  });
});

api.use((_req, _res) => {
  throw new HttpError(404, 'Unbekannter Endpunkt');
});

api.use((err, req, res, _next) => {
  const status = err.status ?? 500;
  if (status >= 500) log('api', `${req.method} ${req.originalUrl}: ${err.message}`);
  if (res.headersSent) return res.destroy();
  res.status(status).json({ error: err.message });
});

app.use('/api', api);

// --- Frontend ----------------------------------------------------------------

app.use(
  express.static(config.publicDir, {
    setHeaders(res, file) {
      const name = path.basename(file);
      if (name === 'sw.js' || name.endsWith('.html') || name.endsWith('.webmanifest')) {
        res.setHeader('Cache-Control', 'no-cache');
      }
      if (name.endsWith('.webmanifest')) res.setHeader('Content-Type', 'application/manifest+json');
    },
  }),
);

// SPA-Fallback (Hash-Routing braucht ihn kaum, schadet aber nicht)
app.use((req, res, next) => {
  if (req.method !== 'GET' || !req.accepts('html')) return next();
  res.sendFile(path.join(config.publicDir, 'index.html'));
});

await Promise.all([favorites.init(), downloads.init()]);

app.listen(config.port, config.host, async () => {
  log('server', `läuft auf http://${config.host}:${config.port}`);
  const ytv = await yt.version();
  log('server', `Jellyfin ${config.jellyfin.url} ${jellyfin.isConfigured() ? '' : '(kein API-Key!)'}`);
  log('server', `Deemix ${config.deemix.url} ${config.deemix.arl ? '' : '(kein ARL in .env)'}`);
  log('server', `yt-dlp ${ytv ?? 'nicht verfügbar'}`);
  // Deemix-Login vorwärmen, damit der erste Download nicht wartet
  if (config.deemix.arl) deemix.login().catch((err) => log('deemix', err.message));
});

