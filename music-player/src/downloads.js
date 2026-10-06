// Hintergrund-Downloads: Deemix-Queue füttern, Fortschritt pollen, danach Jellyfin scannen.
import path from 'node:path';
import { config } from './config.js';
import * as deemix from './deemix.js';
import * as deezer from './deezer.js';
import * as jellyfin from './jellyfin.js';
import { log, readJson, writeJson } from './util.js';

const FILE = path.join(config.dataDir, 'downloads.json');
const POLL_MS = 3000;
const STUCK_MS = 30 * 60 * 1000;
const KEEP = 300;

/** @type {Map<string, any>} key `${type}:${id}` */
const jobs = new Map();
let pollTimer = null;
let scanTimer = null;
let saveTimer = null;

export async function init() {
  const saved = await readJson(FILE, []);
  for (const job of saved) {
    // Nach einem Neustart weiter beobachten, was noch offen war
    jobs.set(job.key, job);
  }
  if (active().length) startPolling();
}

const active = () => [...jobs.values()].filter((j) => j.status === 'queued' || j.status === 'downloading');

function persist() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const list = [...jobs.values()].sort((a, b) => b.createdAt - a.createdAt).slice(0, KEEP);
    writeJson(FILE, list).catch((err) => log('downloads', `Speichern fehlgeschlagen: ${err.message}`));
  }, 500);
}

function update(job, patch) {
  Object.assign(job, patch, { updatedAt: Date.now() });
  persist();
}

export function list() {
  return [...jobs.values()].sort((a, b) => b.createdAt - a.createdAt);
}

/**
 * Track oder Album herunterladen. Idempotent: bereits laufende oder fertige Jobs
 * werden nicht doppelt angelegt (außer mit force).
 */
const inflight = new Map();

export function enqueue({ type, id, reason = 'manual', force = false }) {
  if (!['track', 'album'].includes(type)) throw new Error('type muss track oder album sein');
  const key = `${type}:${id}`;
  const existing = jobs.get(key);
  if (existing && !force && existing.status !== 'failed') return Promise.resolve(existing);
  if (inflight.has(key)) return inflight.get(key);
  const p = createJob(key, type, id, reason, force).finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

async function createJob(key, type, id, reason, force) {
  const meta = type === 'track' ? await deezer.track(id) : await deezer.album(id);
  const job = {
    key,
    type,
    id: String(id),
    title: meta.title,
    artist: meta.artist,
    cover: meta.coverSmall ?? meta.cover,
    reason,
    status: 'queued',
    progress: 0,
    uuids: [],
    error: null,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
  jobs.set(key, job);
  persist();

  if (type === 'track' && !force) {
    const hit = await jellyfin.findLocal(meta).catch(() => null);
    if (hit) {
      update(job, { status: 'skipped', progress: 100, error: 'schon in der Bibliothek' });
      return job;
    }
  }

  try {
    const uuids = await deemix.addToQueue(type, id);
    update(job, { uuids });
    log('downloads', `${type} ${meta.artist} – ${meta.title} (${reason}) → Deemix`);
    startPolling();
  } catch (err) {
    update(job, { status: 'failed', error: err.message });
    log('downloads', `Fehler bei ${key}: ${err.message}`);
  }
  return job;
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(poll, POLL_MS);
  poll();
}

async function poll() {
  const open = active();
  if (!open.length) {
    clearInterval(pollTimer);
    pollTimer = null;
    return;
  }

  let queue;
  try {
    queue = await deemix.queueStatus();
  } catch (err) {
    log('downloads', `Deemix nicht erreichbar: ${err.message}`);
    return;
  }

  for (const job of open) {
    const states = job.uuids.map((u) => queue.get(u)).filter(Boolean);
    if (!states.length) {
      job.missing = (job.missing ?? 0) + 1;
      // Eintrag ist aus der Deemix-Queue verschwunden (manuell geleert): als fertig werten
      if (job.missing > 5 && job.uuids.length) finish(job, 'done');
      else if (Date.now() - job.createdAt > STUCK_MS) finish(job, 'failed', 'Zeitüberschreitung');
      continue;
    }
    job.missing = 0;

    const failed = states.every((s) => s.status === 'failed');
    const done = states.every((s) => ['completed', 'withErrors', 'failed'].includes(s.status));
    if (failed) {
      finish(job, 'failed', 'Deemix meldet Fehler (Song nicht verfügbar?)');
    } else if (done) {
      const errors = states.some((s) => s.status === 'withErrors');
      finish(job, 'done', errors ? 'teilweise fehlgeschlagen' : null);
    } else {
      const progress = Math.round(states.reduce((sum, s) => sum + s.progress, 0) / states.length);
      const downloading = states.some((s) => s.status === 'downloading' || s.progress > 0);
      if (downloading || progress !== job.progress) {
        update(job, { status: downloading ? 'downloading' : 'queued', progress });
      }
    }
  }
}

function finish(job, status, error = null) {
  update(job, { status, progress: status === 'done' ? 100 : job.progress, error });
  log('downloads', `${job.artist} – ${job.title}: ${status}${error ? ` (${error})` : ''}`);
  if (status === 'done') scheduleScan();
}

/** Mehrere Downloads kurz hintereinander → nur ein Scan. */
function scheduleScan() {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(async () => {
    try {
      await jellyfin.refreshLibrary();
      // Jellyfin braucht etwas für den Scan; danach Abgleich-Cache verwerfen
      setTimeout(jellyfin.forgetMatches, 20000);
      setTimeout(jellyfin.forgetMatches, 60000);
    } catch (err) {
      log('jellyfin', `Scan fehlgeschlagen: ${err.message}`);
    }
  }, config.jellyfin.scanDelayMs);
}

export function clearFinished() {
  for (const [key, job] of jobs) {
    if (!['queued', 'downloading'].includes(job.status)) jobs.delete(key);
  }
  persist();
}
