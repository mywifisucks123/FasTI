import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Vorhandene Umgebungsvariablen (z. B. aus Docker) haben Vorrang vor .env
try {
  process.loadEnvFile(path.join(root, '.env'));
} catch {
  // keine .env – nur Umgebungsvariablen
}

const str = (key, fallback = '') => (process.env[key] ?? fallback).trim();
const int = (key, fallback) => {
  const n = Number.parseInt(process.env[key] ?? '', 10);
  return Number.isFinite(n) ? n : fallback;
};
const bool = (key, fallback) => {
  const v = process.env[key];
  if (v === undefined || v === '') return fallback;
  return ['1', 'true', 'yes', 'on'].includes(v.trim().toLowerCase());
};
const url = (key, fallback) => str(key, fallback).replace(/\/+$/, '');

export const config = {
  root,
  publicDir: path.join(root, 'public'),
  dataDir: path.resolve(root, str('DATA_DIR', 'data')),
  port: int('PORT', 3000),
  host: str('HOST', '0.0.0.0'),

  jellyfin: {
    url: url('JELLYFIN_URL', 'http://localhost:8096'),
    apiKey: str('JELLYFIN_API_KEY'),
    userId: str('JELLYFIN_USER_ID'),
    libraryId: str('JELLYFIN_MUSIC_LIBRARY_ID'),
    streamMode: str('JELLYFIN_STREAM_MODE', 'static'),
    scanDelayMs: int('JELLYFIN_SCAN_DELAY_MS', 15000),
  },

  deemix: {
    url: url('DEEMIX_URL', 'http://localhost:6595'),
    arl: str('DEEMIX_ARL'),
    bitrate: int('DEEMIX_BITRATE', 9),
  },

  yt: {
    enabled: bool('YTDLP_ENABLED', true),
    bin: str('YTDLP_BIN', 'yt-dlp'),
    extraArgs: str('YTDLP_EXTRA_ARGS').split(/\s+/).filter(Boolean),
    search: str('YT_SEARCH', 'music'),
    concurrency: Math.max(1, int('YTDLP_CONCURRENCY', 2)),
    resolveTimeoutMs: int('STREAM_RESOLVE_TIMEOUT_MS', 8000),
  },

  autoDownloadOnPlay: bool('AUTO_DOWNLOAD_ON_PLAY', true),
};
