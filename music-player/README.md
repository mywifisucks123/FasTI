# Tonspur – persönlicher Musik-Player (iOS-PWA)

Dunkles UI im Stil von Apple Music/Spotify, Suche über den kompletten Deezer-Katalog, Sofort-Wiedergabe und automatischer Download in voller Qualität in die Jellyfin-Bibliothek auf dem Mac Mini.

```
iPhone (PWA)  ──HTTPS──▶  Tonspur-Backend (Node, Port 3000)
                               ├─ Deezer-API ........ Suche, Cover, Metadaten, 30-s-Vorschau
                               ├─ Jellyfin :8096 .... Bibliothek, Streaming, Scan
                               ├─ yt-dlp ............ Sofort-Stream kompletter Songs
                               └─ Deemix :6595 ...... FLAC-Download → ~/jellyfin-app/media/music
```

## So funktioniert die Wiedergabe

Tippst du auf einen Song, entscheidet das Backend in dieser Reihenfolge:

1. Song liegt schon in Jellyfin → Stream direkt vom Mac Mini (FLAC, volle Qualität). Badge im Player: „Bibliothek".
2. Sonst kompletter Song über yt-dlp (YouTube Music, offizielle Audio-Version, per Dauer und Titel abgeglichen). Badge: „Stream". Die ersten Treffer jeder Suche, Album- und Künstlerseite werden schon beim Anzeigen vorgeladen, deshalb startet der Song nach dem Tippen ohne Wartezeit.
3. Ist yt-dlp nicht installiert oder braucht länger als 8 s → 30-Sekunden-Vorschau von Deezer. Badge: „Vorschau · 30 s".

Nach 5 Sekunden Wiedergabe schickt die App lautlos `POST /api/download` ans Backend. Die 5 Sekunden sind Absicht: Wer durch Charts skippt, soll nicht 40 Songs auf die Platte laden. Das Backend prüft, ob der Song schon in Jellyfin liegt, und schickt ihn sonst an Deemix. Es fragt den Fortschritt alle 3 s ab und startet nach dem letzten fertigen Download (15 s Puffer, damit mehrere Downloads nur einen Scan auslösen) den Jellyfin-Scan. Ab dann kommt derselbe Song automatisch aus der Bibliothek.

Das Herz bei einem Song oder Album macht dasselbe sofort, beim Album für das komplette Album. Favoriten liegen in `data/favorites.json` auf dem Mac Mini, nicht im Browser.

## Vorab: zwei Punkte, an denen es sonst hakt

HTTPS ist Pflicht für den Service Worker. Über `http://192.168.0.104:3000` läuft die App zwar und lässt sich auch als Vollbild-App auf den Home-Bildschirm legen, aber iOS registriert ohne HTTPS keinen Service Worker. Die saubere Lösung ist Tailscale Serve (siehe unten): echtes Zertifikat, funktioniert zu Hause und unterwegs, nichts wird ins Internet geöffnet.

Der Deemix-Container muss in den Jellyfin-Ordner schreiben. Das Backend sagt Deemix nur *was* geladen wird, *wohin* bestimmt der Container. Prüfen:

```bash
docker inspect deemix --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

Dort muss `~/jellyfin-app/media/music -> /downloads` auftauchen (bzw. der Pfad, den Deemix in den Einstellungen als Download-Ordner nutzt). Wenn nicht, den Container mit `-v ~/jellyfin-app/media/music:/downloads` neu anlegen. In den Deemix-Einstellungen „Ordner für Künstler" und „Ordner für Alben" anlassen, dann sortiert Jellyfin sauber.

## Einrichtung

```bash
cd music-player
cp .env.example .env
```

In der `.env` drei Werte setzen:

- `JELLYFIN_API_KEY`: Jellyfin → Dashboard → API-Schlüssel → „+" → Name „Tonspur".
- `DEEMIX_ARL`: dasselbe ARL, das Deemix nutzt. Aus dem Container lesen: `docker exec deemix cat /config/.arl` (Containername ggf. anpassen).
- `DEEMIX_BITRATE`: `9` = FLAC (Standard), `3` = MP3 320.

Optional `JELLYFIN_MUSIC_LIBRARY_ID`, damit nur die Musikbibliothek gescannt wird statt aller Bibliotheken (die ID steht in der Jellyfin-URL, wenn du die Bibliothek öffnest: `...&topParentId=<ID>`).

### Variante A: PM2 (empfohlen, nativ auf dem Mac)

```bash
brew install node yt-dlp
npm install -g pm2

cd music-player
npm install --omit=dev
pm2 start ecosystem.config.cjs
pm2 save
pm2 startup          # gibt einen sudo-Befehl aus → den ausführen, dann startet alles nach Reboot
```

Logs: `pm2 logs tonspur`. Neustart nach Änderungen an der `.env`: `pm2 restart tonspur`.

Falls die Status-Seite nach einem Reboot „yt-dlp nicht installiert" meldet, fehlt Homebrew im PATH von launchd. Dann in der `.env` `YTDLP_BIN=/opt/homebrew/bin/yt-dlp` setzen und `pm2 restart tonspur`.

yt-dlp regelmäßig aktualisieren, YouTube ändert ständig etwas: `brew upgrade yt-dlp`. Die JavaScript-Runtime, die yt-dlp seit Ende 2025 für YouTube braucht, setzt das Backend selbst (Deno, falls installiert, sonst das vorhandene Node).

### Variante B: Docker

```bash
cd music-player
docker compose up -d --build
docker compose logs -f
```

`docker-compose.yml` biegt `JELLYFIN_URL` und `DEEMIX_URL` automatisch auf `host.docker.internal` um, weil Jellyfin und Deemix aus Sicht des Containers auf dem Host laufen. yt-dlp ist im Image enthalten; aktualisieren mit `docker compose build --no-cache && docker compose up -d`.

### Läuft es?

`http://192.168.0.104:3000` im Browser öffnen → Bibliothek → Status. Alle fünf Punkte sollten grün sein (Service Worker wird erst unter HTTPS grün).

## Aufs iPhone

1. Tailscale-Adminkonsole → DNS: MagicDNS und „HTTPS Certificates" aktivieren.
2. Auf dem Mac Mini:
   ```bash
   tailscale serve --bg 3000
   ```
   Mit der Tailscale-App aus dem App Store heißt der Befehl `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 3000`. Die Ausgabe zeigt die Adresse, etwa `https://mac-mini.tailXXXX.ts.net`.
3. Auf dem iPhone Tailscale aktivieren (auch zu Hause), die Adresse in Safari öffnen.
4. Teilen → „Zum Home-Bildschirm". Ab jetzt startet Tonspur ohne Safari-Leisten, mit Sperrbildschirm-Steuerung, AirPlay und Hintergrund-Wiedergabe.

## Projektstruktur

```
music-player/
├── src/
│   ├── server.js       Express-Server, alle API-Routen, liefert das Frontend aus
│   ├── config.js       liest .env
│   ├── resolver.js     wählt die Audioquelle (Jellyfin → yt-dlp → Vorschau)
│   ├── ytdlp.js        YouTube-Music-Suche, Treffer-Scoring, Audio-URL
│   ├── proxy.js        Range-fähiger Stream-Proxy (iOS braucht 206-Antworten)
│   ├── downloads.js    Download-Queue, Deemix-Polling, Jellyfin-Scan
│   ├── deemix.js       Deemix-API (Login per ARL, addToQueue, getQueue)
│   ├── jellyfin.js     Jellyfin-API (Suche, Abgleich, Stream, Scan)
│   ├── deezer.js       öffentliche Deezer-API
│   ├── favorites.js    Favoriten als JSON
│   └── util.js
├── public/             PWA: index.html, manifest, Service Worker, CSS, JS, Icons
├── data/               favorites.json, downloads.json (wird angelegt)
├── Dockerfile, docker-compose.yml, ecosystem.config.cjs
└── .env.example
```

## API

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/search?q=` | Deezer-Songs/Alben/Künstler + Treffer aus Jellyfin |
| GET | `/api/charts` | Startseite |
| GET | `/api/album/:id`, `/api/artist/:id` | Deezer-Details |
| GET | `/api/stream/dz/:id` | Audio für einen Deezer-Track (Quelle automatisch) |
| GET | `/api/stream/jf/:id` | Audio direkt aus Jellyfin |
| GET | `/api/source/dz/:id` | welche Quelle gerade genutzt wird |
| POST | `/api/prefetch` `{ids}` | yt-dlp-Auflösung vorwärmen |
| POST | `/api/download` `{type, id, reason}` | Track/Album an Deemix |
| GET/DELETE | `/api/downloads` | Download-Status / erledigte ausblenden |
| GET/POST/DELETE | `/api/favorites` | Favoriten |
| GET | `/api/library/albums`, `/api/jf/album/:id` | Jellyfin-Bibliothek |
| GET | `/api/health` | Status aller Dienste |

## Grenzen

- Das Backend hat keinen Login. Es gehört nur ins LAN bzw. Tailnet, keine Portfreigabe im Router.
- Der Abgleich Deezer ↔ Jellyfin läuft über Titel + Künstler bzw. Dauer. Da Deemix die Tags aus Deezer schreibt, passt das fast immer; bei Dateien aus anderen Quellen kann ein Song doppelt geladen werden.
- iOS kann eine Home-Bildschirm-App nach langer Zeit im Hintergrund beenden. Läuft Musik, passiert das praktisch nicht; nach dem Pausieren über Nacht startet die App neu, Warteschlange und Position bleiben gespeichert.
- yt-dlp und Deemix verstoßen gegen die Nutzungsbedingungen von YouTube bzw. Deezer. Für den privaten Gebrauch ist das dein Risiko, nicht weiterverbreiten.
