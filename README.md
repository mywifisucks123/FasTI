# FasTI – Threat & Crisis Intelligence Dashboard

All-Hazard-Lagebild (Cyber, Geopolitik, Naturkatastrophen, Infrastruktur/Supply Chain) im Feedly-TI-Stil. Läuft komplett lokal auf macOS, ohne Docker und ohne Datenbank, mit kostenloser KI-Analyse über Google Gemini oder Groq.

## Start

```bash
chmod +x start.sh
./start.sh
```

Das Skript legt beim ersten Start eine virtuelle Umgebung `.venv` an (umgeht die PEP-668-Sperre von Homebrew-Python), installiert `feedparser` und `requests`, holt einmal alle Quellen, startet `python3 -m http.server` auf `127.0.0.1:8000`, öffnet den Browser und pollt danach im Hintergrund alle 30 Minuten (`backend.log`). Strg+C beendet alles.

Optionen: `--no-ai`, `--no-loop`, `--port 8080`.

## KI-Key

Gemini-Key kostenlos unter https://aistudio.google.com/apikey, Groq unter https://console.groq.com/keys. Entweder in `config.py` bei `GEMINI_API_KEY` eintragen oder (besser) `.env.example` nach `.env` kopieren und dort setzen. Ohne Key läuft das System regelbasiert (Schlagwort-Scoring, eingebauter Gazetteer für Geotagging); diese Einträge werden automatisch per KI nachveredelt, sobald ein Key da ist.

Sind beide Keys hinterlegt, springt das Backend automatisch auf Groq, wenn Gemini überlastet ist (HTTP 503) oder das Kontingent erschöpft ist; innerhalb von Gemini werden vorher mehrere Modelle probiert. Der KI-Status (aktiver Anbieter/Modell oder letzter Fehler) steht oben im Dashboard. Das Free-Tier wird geschont: 10 Meldungen pro Request, max. 8 Requests pro Lauf und 200 pro Tag; Trigger-Kandidaten bekommen die KI zuerst. Strukturierte Quellen (USGS, GDACS, Auswärtiges Amt, NINA) brauchen gar keine KI, weil Koordinaten und Schweregrad direkt aus den Daten kommen.

Hinweis: Im kostenlosen Gemini-Tarif darf Google Eingaben zur Produktverbesserung nutzen. Da nur öffentliche Feed-Inhalte gesendet werden, ist das hier unkritisch.

## Trigger-Monitor (Krisen-Entscheidungsplan)

Jede Meldung wird gegen den Trigger-Katalog in `config.py` (`TRIGGERS`) geprüft: Liste A (harte Trigger A1–A8), Liste B (weiche Indikatoren B1–B7) und als Zusatz diplomatische Signale (D1–D3: Botschafter abberufen/einbestellt, Botschaftsschließungen und Security Alerts, verschärfte Reisehinweise für DE/PL/Baltikum). Die KI bekommt die Definitionen inklusive der „bewusst keine Trigger“-Liste des Plans; ohne KI greifen Regex-Regeln.

Der Tab „Trigger-Monitor“ zeigt die Einschätzung nach Plan: ein Punkt aus Liste A → notieren und täglich bewerten, zwei verschiedene Punkte in 30 Tagen → Stufe 2. Jeder Treffer ist ein Kandidat, der an der Originalquelle verifiziert werden muss; Fehlalarme lassen sich verwerfen. Trigger-Treffer werden 45 Tage gehalten.

Für die Nachbarstaaten in `AA_WATCH_COUNTRIES` meldet das Backend jede Aktualisierung der AA-Reisehinweise und prüft den Volltext auf Ausreiseaufrufe (A8). Zusätzlich laufen US-Botschafts-Alerts (DE, PL, LT, LV, EE), FCDO-Länderfeeds, NATO-News, Bundestag-hib und gezielte Google-News-Suchen pro Trigger.

## Dateien

| Datei | Zweck |
|---|---|
| `config.py` | Quellen, API-Keys, Limits, Intervalle |
| `backend.py` | Fetcher + KI-Analyse, schreibt `threats.json` atomar und dedupliziert |
| `index.html` | Dashboard (Tailwind + Leaflet via CDN), lädt `threats.json` alle 30 s nach |
| `start.sh` | Ein-Befehl-Start für macOS |

Backend manuell: `.venv/bin/python backend.py [--loop] [--no-ai] [--reset] [-v]`.

## Quellen

Cyber: CISA, BleepingComputer, The Hacker News, CERT-Bund WID, heise Security.
Geopolitik: BBC World, Al Jazeera, DW, Tagesschau Ausland, UN News, Bellingcat; Auswärtiges Amt (Open-Data-Reisewarnungen), US State Department Travel Advisories, UK FCDO Travel Advice, US-Botschaft Deutschland (Alerts).
Natur: USGS (GeoJSON, ab M5.0), GDACS, ReliefWeb.
Infrastruktur: BSI, NINA/BBK (MoWaS, KATWARN, BIWAPP inkl. Polygon-Geokodierung), Industrial Cyber, gCaptain, Supply Chain Dive.

Reuters bietet seit 2020 keine öffentlichen RSS-Feeds mehr. Eigene Quellen ergänzt man als Eintrag in `FEEDS`; nicht erreichbare Quellen werden geloggt und im Dashboard unter „Quellen“ angezeigt, stoppen aber den Lauf nicht.

## Sicherheit

Der Webserver ist nur an `127.0.0.1` gebunden. `http.server` liefert allerdings jede Datei im Ordner aus, also auch `config.py` und `.env`. Für ein Single-User-Setup auf dem eigenen Mac ist das vertretbar; den Port nicht ins Netz weiterleiten. Alle Feed-Inhalte werden im Frontend HTML-escaped, Links nur mit http(s) übernommen.
