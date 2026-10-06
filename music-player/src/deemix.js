// Client für die Web-API des Deemix-Containers (deemix-gui / deemix-docker).
// Deemix hält den Deezer-Login pro HTTP-Session, deshalb merken wir uns das Cookie.
import { config } from './config.js';
import { HttpError, log } from './util.js';

const { url: BASE } = config.deemix;
let cookie = '';
let loggedIn = false;
let loginPromise;

async function call(path, { method = 'GET', body, timeout = 15000 } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(cookie ? { Cookie: cookie } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeout),
  });
  const setCookie = res.headers.getSetCookie?.() ?? [];
  if (setCookie.length) {
    const jar = new Map(cookie.split('; ').filter(Boolean).map((c) => c.split(/=(.*)/s)));
    for (const c of setCookie) {
      const [pair] = c.split(';');
      const [k, v] = pair.split(/=(.*)/s);
      jar.set(k.trim(), v);
    }
    cookie = [...jar].map(([k, v]) => `${k}=${v}`).join('; ');
  }
  if (!res.ok) throw new HttpError(502, `Deemix ${res.status} ${path}`);
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return text;
  }
}

async function resolveArl() {
  if (config.deemix.arl) return config.deemix.arl;
  // Manche Deemix-Builds liefern das gespeicherte ARL im Single-User-Modus mit aus
  const info = await call('/api/connect').catch(() => null);
  return info?.singleUser?.arl ?? info?.arl ?? '';
}

async function doLogin() {
  const arl = await resolveArl();
  if (!arl) throw new HttpError(503, 'DEEMIX_ARL fehlt in der .env');
  const qs = `?arl=${encodeURIComponent(arl)}&child=0&force=false`;
  const res = await call(`/api/loginArl${qs}`, {
    method: 'POST',
    body: { arl, child: 0, force: false },
  });
  // LoginStatus: 0 = FAILED, 1 = SUCCESS, 2 = ALREADY_LOGGED, 3 = FORCED_SUCCESS
  const status = typeof res === 'object' ? res?.status : Number(res);
  if (![1, 2, 3].includes(Number(status))) {
    loggedIn = false;
    throw new HttpError(502, `Deemix-Login fehlgeschlagen (Status ${status}) – ARL abgelaufen?`);
  }
  loggedIn = true;
  log('deemix', `eingeloggt als ${res?.user?.name ?? 'Deezer-User'}`);
}

export function login({ force = false } = {}) {
  if (loggedIn && !force) return Promise.resolve();
  loginPromise ??= doLogin().finally(() => {
    loginPromise = undefined;
  });
  return loginPromise;
}

/**
 * Legt Track oder Album in die Deemix-Warteschlange.
 * Liefert die Deemix-UUIDs zurück (Format: `${type}_${id}_${bitrate}`).
 */
export async function addToQueue(type, id) {
  const { bitrate } = config.deemix;
  const link = `https://www.deezer.com/${type}/${id}`;
  const fallbackUuid = `${type}_${id}_${bitrate}`;

  for (let attempt = 0; attempt < 2; attempt++) {
    await login({ force: attempt > 0 });
    const res = await call('/api/addToQueue', {
      method: 'POST',
      body: { url: link, bitrate },
      timeout: 30000,
    });
    if (res?.result === false) {
      if (res.errid === 'NotLoggedIn' && attempt === 0) {
        loggedIn = false;
        continue;
      }
      if (res.errid === 'AlreadyInQueue') return [fallbackUuid];
      throw new HttpError(502, `Deemix: ${res.errid ?? 'addToQueue fehlgeschlagen'}`);
    }
    const objs = [res?.data?.obj ?? res?.obj].flat().filter(Boolean);
    const uuids = objs.map((o) => o.uuid).filter(Boolean);
    return uuids.length ? uuids : [fallbackUuid];
  }
  throw new HttpError(502, 'Deemix: Login fehlgeschlagen');
}

/** Status aller Deemix-Jobs: Map uuid → { status, progress } */
export async function queueStatus() {
  const res = await call('/api/getQueue', { timeout: 8000 });
  const out = new Map();
  for (const [uuid, item] of Object.entries(res?.queue ?? {})) {
    out.set(uuid, {
      status: item.status ?? 'inQueue',
      progress: Number(item.progress ?? 0),
      size: item.size ?? 0,
      downloaded: item.downloaded ?? 0,
      failed: item.failed ?? 0,
    });
  }
  const cur = res?.current;
  if (cur?.uuid) {
    out.set(cur.uuid, {
      ...(out.get(cur.uuid) ?? {}),
      status: 'downloading',
      progress: Number(cur.progress ?? 0),
    });
  }
  return out;
}

export async function ping() {
  const res = await call('/api/connect', { timeout: 4000 });
  return { ok: true, loggedIn, deezerAvailable: res?.deezerAvailable ?? null };
}
