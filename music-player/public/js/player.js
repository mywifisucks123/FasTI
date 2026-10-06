// Ein einziges <audio>-Element für alles: iOS erlaubt nach dem ersten Tipp
// weitere play()-Aufrufe auf demselben Element, auch im Hintergrund.
import { api, streamUrl } from './api.js';

const STORE = 'tonspur:player';
// Erst nach ein paar Sekunden Wiedergabe laden – wer nur durchskippt, füllt nicht die Platte
const DOWNLOAD_AFTER_SECONDS = 5;

function shuffled(n, first) {
  const rest = [...Array(n).keys()].filter((i) => i !== first);
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return first >= 0 ? [first, ...rest] : rest;
}

class Player extends EventTarget {
  constructor() {
    super();
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.audio.setAttribute('playsinline', '');
    this.queue = [];
    this.order = [];
    this.pos = -1;
    this.shuffle = false;
    this.repeat = 'off';
    this.source = null;
    this.usingPreview = false;
    this.downloaded = new Set();
    this.lastPositionUpdate = 0;

    // Audio auch bei Stummschalter spielen (Safari 17+)
    try {
      if (navigator.audioSession) navigator.audioSession.type = 'playback';
    } catch {}

    const a = this.audio;
    a.addEventListener('play', () => this.emit('state'));
    a.addEventListener('pause', () => this.emit('state'));
    a.addEventListener('waiting', () => this.emit('state'));
    a.addEventListener('playing', () => this.emit('state'));
    a.addEventListener('timeupdate', () => this.onTime());
    a.addEventListener('ended', () => this.onEnded());
    a.addEventListener('error', () => this.onError());
    a.addEventListener('loadedmetadata', () => {
      if (this.resumeAt) {
        a.currentTime = this.resumeAt;
        this.resumeAt = 0;
      }
      this.emit('time');
    });

    this.setupMediaSession();
    this.restore();
  }

  emit(type) {
    this.dispatchEvent(new Event(type));
  }

  get current() {
    return this.queue[this.order[this.pos]] ?? null;
  }

  get playing() {
    return !this.audio.paused;
  }

  get loading() {
    return !this.audio.paused && this.audio.readyState < 3;
  }

  get upcoming() {
    return this.order.slice(this.pos + 1).map((i) => this.queue[i]);
  }

  playList(tracks, index = 0, { shuffle = false } = {}) {
    if (!tracks.length) return;
    this.queue = tracks.slice();
    this.shuffle = shuffle;
    if (shuffle) {
      const start = index >= 0 ? index : Math.floor(Math.random() * tracks.length);
      this.order = shuffled(tracks.length, start);
      this.pos = 0;
    } else {
      this.order = tracks.map((_, i) => i);
      this.pos = Math.max(0, index);
    }
    this.load(true);
    this.emit('queue');
  }

  load(autoplay) {
    const t = this.current;
    if (!t) return;
    this.usingPreview = false;
    this.source = t.source === 'jf' ? 'jellyfin' : null;
    this.audio.src = streamUrl(t);
    if (autoplay) this.audio.play().catch((err) => this.emitError(err));
    this.updateMediaSession();
    this.emit('track');
    this.save();

    if (t.source === 'dz') {
      api
        .source(t.id)
        .then((r) => {
          if (this.current !== t) return;
          this.source = this.usingPreview ? 'preview' : r.type;
          this.emit('source');
        })
        .catch(() => {});
    } else {
      this.emit('source');
    }
    api.prefetch(this.upcoming.slice(0, 2).filter((x) => x.source === 'dz').map((x) => x.id));
  }

  emitError(err) {
    if (err?.name === 'AbortError') return;
    this.lastError = err;
    this.emit('error');
  }

  toggle() {
    if (!this.current) return;
    if (this.audio.paused) this.audio.play().catch((err) => this.emitError(err));
    else this.audio.pause();
  }

  next(auto = false) {
    if (this.repeat === 'one' && auto) {
      this.audio.currentTime = 0;
      this.audio.play().catch(() => {});
      return;
    }
    if (this.pos + 1 < this.order.length) this.pos++;
    else if (this.repeat === 'all' || !auto) this.pos = 0;
    else {
      this.audio.pause();
      this.audio.currentTime = 0;
      return;
    }
    this.load(true);
  }

  prev() {
    if (this.audio.currentTime > 3 || this.pos === 0) {
      this.audio.currentTime = 0;
      return;
    }
    this.pos--;
    this.load(true);
  }

  seek(seconds) {
    if (Number.isFinite(seconds)) this.audio.currentTime = seconds;
  }

  toggleShuffle() {
    this.shuffle = !this.shuffle;
    const currentIndex = this.order[this.pos];
    if (this.shuffle) {
      this.order = shuffled(this.queue.length, currentIndex);
      this.pos = 0;
    } else {
      this.order = this.queue.map((_, i) => i);
      this.pos = currentIndex;
    }
    this.emit('queue');
    this.save();
  }

  cycleRepeat() {
    this.repeat = { off: 'all', all: 'one', one: 'off' }[this.repeat];
    this.emit('queue');
    this.save();
  }

  onTime() {
    const a = this.audio;
    const t = this.current;
    if (t?.source === 'dz' && !this.usingPreview && a.currentTime >= DOWNLOAD_AFTER_SECONDS && !this.downloaded.has(t.id)) {
      this.downloaded.add(t.id);
      // Lautloser Hintergrund-Download in die Jellyfin-Bibliothek
      api.download('track', t.id, 'play').catch(() => {});
    }
    const now = Date.now();
    if (now - this.lastPositionUpdate > 1000) {
      this.lastPositionUpdate = now;
      this.updatePositionState();
      this.save();
    }
    this.emit('time');
  }

  onEnded() {
    this.next(true);
  }

  onError() {
    const t = this.current;
    if (!t || !this.audio.src) return;
    // Volle Quelle nicht spielbar → 30-s-Vorschau als Notnagel
    if (t.source === 'dz' && t.preview && !this.usingPreview) {
      this.usingPreview = true;
      this.source = 'preview';
      this.audio.src = t.preview;
      this.audio.play().catch(() => {});
      this.emit('source');
      return;
    }
    this.emitError(new Error('Titel nicht abspielbar'));
  }

  // --- Sperrbildschirm / Control Center ---

  setupMediaSession() {
    const ms = navigator.mediaSession;
    if (!ms) return;
    const handlers = {
      play: () => this.audio.play(),
      pause: () => this.audio.pause(),
      previoustrack: () => this.prev(),
      nexttrack: () => this.next(),
      seekto: (d) => this.seek(d.seekTime),
      seekbackward: (d) => this.seek(this.audio.currentTime - (d.seekOffset ?? 10)),
      seekforward: (d) => this.seek(this.audio.currentTime + (d.seekOffset ?? 10)),
    };
    for (const [action, fn] of Object.entries(handlers)) {
      try {
        ms.setActionHandler(action, fn);
      } catch {}
    }
  }

  updateMediaSession() {
    const t = this.current;
    if (!navigator.mediaSession || !t) return;
    const art = t.cover ?? t.coverSmall;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title,
      artist: t.artist,
      album: t.album ?? '',
      artwork: art
        ? [
            { src: new URL(t.coverSmall ?? art, location.href).href, sizes: '256x256', type: 'image/jpeg' },
            { src: new URL(art, location.href).href, sizes: '1000x1000', type: 'image/jpeg' },
          ]
        : [],
    });
  }

  updatePositionState() {
    const a = this.audio;
    if (!navigator.mediaSession?.setPositionState || !Number.isFinite(a.duration) || a.duration <= 0) return;
    try {
      navigator.mediaSession.setPositionState({
        duration: a.duration,
        playbackRate: a.playbackRate,
        position: Math.min(a.currentTime, a.duration),
      });
    } catch {}
  }

  // --- Zustand über Neustarts der App hinweg ---

  save() {
    try {
      localStorage.setItem(
        STORE,
        JSON.stringify({
          queue: this.queue.slice(0, 300),
          order: this.order.filter((i) => i < 300),
          pos: this.pos,
          time: this.audio.currentTime,
          shuffle: this.shuffle,
          repeat: this.repeat,
        }),
      );
    } catch {}
  }

  restore() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) ?? 'null');
      if (!s?.queue?.length) return;
      this.queue = s.queue;
      this.order = s.order?.length ? s.order : s.queue.map((_, i) => i);
      this.pos = Math.min(Math.max(0, s.pos ?? 0), this.order.length - 1);
      this.shuffle = Boolean(s.shuffle);
      this.repeat = s.repeat ?? 'off';
      this.resumeAt = s.time ?? 0;
      this.audio.preload = 'metadata';
      this.load(false);
      this.audio.preload = 'auto';
    } catch {}
  }
}

export const player = new Player();
