// Favoriten (Herz) als JSON-Datei auf dem Mac Mini – damit sie auf allen Geräten gleich sind.
import path from 'node:path';
import { config } from './config.js';
import { readJson, writeJson } from './util.js';

const FILE = path.join(config.dataDir, 'favorites.json');
let data = { tracks: [], albums: [] };

export async function init() {
  data = { tracks: [], albums: [], ...(await readJson(FILE, {})) };
}

const bucket = (type) => {
  if (type === 'track') return data.tracks;
  if (type === 'album') return data.albums;
  throw new Error('type muss track oder album sein');
};

const key = (item) => `${item.source}:${item.id}`;

export function all() {
  return data;
}

export async function add(type, item) {
  const list = bucket(type);
  if (!list.some((i) => key(i) === key(item))) {
    list.unshift({ ...item, addedAt: Date.now() });
    await writeJson(FILE, data);
  }
  return data;
}

export async function remove(type, source, id) {
  const list = bucket(type);
  const idx = list.findIndex((i) => i.source === source && i.id === id);
  if (idx >= 0) {
    list.splice(idx, 1);
    await writeJson(FILE, data);
  }
  return data;
}
