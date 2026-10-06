import fs from 'node:fs/promises';
import path from 'node:path';

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

/** Kleiner TTL-Cache mit Dedupe laufender Anfragen. */
export class TtlCache {
  constructor(ttlMs, max = 500) {
    this.ttlMs = ttlMs;
    this.max = max;
    this.map = new Map();
    this.pending = new Map();
  }

  get(key) {
    const hit = this.map.get(key);
    if (!hit) return undefined;
    if (hit.expires < Date.now()) {
      this.map.delete(key);
      return undefined;
    }
    return hit.value;
  }

  set(key, value, ttlMs = this.ttlMs) {
    if (this.map.size >= this.max) this.map.delete(this.map.keys().next().value);
    this.map.set(key, { value, expires: Date.now() + ttlMs });
    return value;
  }

  delete(key) {
    this.map.delete(key);
  }

  async wrap(key, fn, ttlMs) {
    const hit = this.get(key);
    if (hit !== undefined) return hit;
    if (this.pending.has(key)) return this.pending.get(key);
    const p = (async () => {
      try {
        return this.set(key, await fn(), ttlMs);
      } finally {
        this.pending.delete(key);
      }
    })();
    this.pending.set(key, p);
    return p;
  }
}

/** Begrenzt parallele Aufgaben; dringende Aufgaben werden vorgezogen. */
export class Limiter {
  constructor(concurrency) {
    this.concurrency = concurrency;
    this.active = 0;
    this.queue = [];
  }

  run(fn, { urgent = false } = {}) {
    return new Promise((resolve, reject) => {
      const task = () => {
        this.active++;
        Promise.resolve()
          .then(fn)
          .then(resolve, reject)
          .finally(() => {
            this.active--;
            this.queue.shift()?.();
          });
      };
      if (this.active < this.concurrency) task();
      else if (urgent) this.queue.unshift(task);
      else this.queue.push(task);
    });
  }
}

export function withTimeout(promise, ms) {
  let timer;
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`timeout after ${ms} ms`)), ms);
    }),
  ]);
}

/** Normalisiert Titel/Künstler für den Abgleich Deezer ↔ Jellyfin. */
export function norm(value = '') {
  return String(value)
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[([](feat|ft|with|featuring)\.?\s[^)\]]*[)\]]/g, '')
    .replace(/\s(feat|ft|featuring)\.?\s.*$/, '')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

export async function readJson(file, fallback) {
  try {
    return JSON.parse(await fs.readFile(file, 'utf8'));
  } catch {
    return fallback;
  }
}

export async function writeJson(file, data) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(data, null, 2));
  await fs.rename(tmp, file);
}

export const log = (scope, ...args) =>
  console.log(new Date().toISOString().slice(11, 19), `[${scope}]`, ...args);
