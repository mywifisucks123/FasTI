# -*- coding: utf-8 -*-
"""
FasTI – Threat & Crisis Intelligence Dashboard
Zentrale Konfiguration. Alles, was du anpassen willst, steht hier.

API-Keys: Entweder unten eintragen ODER als Umgebungsvariable setzen
(GEMINI_API_KEY / GROQ_API_KEY bzw. eine Zeile in der Datei .env, die start.sh lädt).
Die Umgebungsvariable hat Vorrang.
"""
import os

# ---------------------------------------------------------------------------
# KI-Analyse
# ---------------------------------------------------------------------------
# "gemini" (Google AI Studio, kostenlos), "groq" (kostenlos) oder "none"
# (rein regelbasiert, ohne KI). Ist kein gültiger Key hinterlegt, fällt das
# Backend automatisch auf die regelbasierte Analyse zurück.
AI_PROVIDER = os.environ.get("AI_PROVIDER", "gemini")

# Key holen: https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "DEIN_KEY_HIER")
# Werden der Reihe nach probiert, falls ein Modell nicht (mehr) existiert.
GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]
# 0 = "Thinking" aus (schneller, spart Free-Tier-Kontingent). None = Modell-Default.
GEMINI_THINKING_BUDGET = 0

# Key holen: https://console.groq.com/keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "DEIN_KEY_HIER")
GROQ_MODELS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant"]

# Sprache für Titel und Executive Summary
OUTPUT_LANGUAGE = "Deutsch"

# Free-Tier-Schutz: Einträge pro KI-Request, Pause zwischen Requests,
# Requests pro Durchlauf und pro Tag (Gemini Free: ca. 10 RPM / 250 RPD).
AI_BATCH_SIZE = 6
AI_MIN_SECONDS_BETWEEN_CALLS = {"gemini": 7.0, "groq": 25.0}
AI_MAX_CALLS_PER_RUN = 6
AI_MAX_CALLS_PER_DAY = 200
AI_REQUEST_TIMEOUT = 90

# Wenn die KI nicht verfügbar ist (kein Key, Kontingent leer, Fehler):
# Einträge regelbasiert analysieren statt sie zurückzustellen. Regelbasierte
# Einträge werden in späteren Durchläufen automatisch per KI nachveredelt.
AI_FALLBACK_HEURISTIC = True

# ---------------------------------------------------------------------------
# Polling & Speicherung
# ---------------------------------------------------------------------------
OUTPUT_FILE = "threats.json"
POLL_INTERVAL_MINUTES = 30        # Intervall für den Dauerbetrieb (start.sh / --loop)
MAX_ITEMS_PER_FEED = 10           # neueste N Einträge je Feed und Durchlauf
MAX_ENTRY_AGE_HOURS = 72          # ältere Feed-Einträge werden ignoriert
RETENTION_DAYS = 14               # Lagebild-Historie
MAX_STORED_THREATS = 500
REQUEST_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 FasTI/1.0"
)

# Strukturierte Quellen
USGS_MIN_MAGNITUDE = 5.0
GDACS_MIN_ALERT = "Green"          # Green | Orange | Red
GDACS_SKIP_GREEN_EARTHQUAKES = True  # grüne Beben deckt USGS bereits ab
NINA_MAX_WARNINGS = 15             # Detailabrufe je NINA-Quelle

# ---------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------
# category: cyber | geopolitics | natural | infrastructure  (Vorgabe für die
#           KI und Fallback für die regelbasierte Analyse)
# type:     rss (RSS/Atom) | usgs (GeoJSON) | gdacs (RSS mit Geo/Alertlevel)
#           | aa (Auswärtiges Amt Open Data) | nina (BBK Warn-API)
# filter:   True = allgemeiner Nachrichtenfeed; ohne KI werden nur Einträge mit
#           Krisen-Schlagwörtern übernommen.
# Reuters bietet seit 2020 keine öffentlichen RSS-Feeds mehr – ersetzt durch
# BBC, Al Jazeera, DW, Tagesschau und UN News.
FEEDS = [
    # --- Cyber -------------------------------------------------------------
    {"name": "CISA Advisories", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
     "category": "cyber", "type": "rss"},
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/",
     "category": "cyber", "type": "rss"},
    {"name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews",
     "category": "cyber", "type": "rss"},
    {"name": "CERT-Bund WID (BSI)", "url": "https://wid.cert-bund.de/content/public/securityAdvisory/rss",
     "category": "cyber", "type": "rss"},
    {"name": "heise Security", "url": "https://www.heise.de/security/rss/news-atom.xml",
     "category": "cyber", "type": "rss"},

    # --- Geopolitik & Konflikte -------------------------------------------
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
     "category": "geopolitics", "type": "rss", "filter": True},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml",
     "category": "geopolitics", "type": "rss", "filter": True},
    {"name": "DW World", "url": "https://rss.dw.com/rdf/rss-en-world",
     "category": "geopolitics", "type": "rss", "filter": True},
    {"name": "Tagesschau Ausland", "url": "https://www.tagesschau.de/ausland/index~rss2.xml",
     "category": "geopolitics", "type": "rss", "filter": True},
    {"name": "UN News", "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
     "category": "geopolitics", "type": "rss", "filter": True},
    {"name": "Bellingcat (OSINT)", "url": "https://www.bellingcat.com/feed/",
     "category": "geopolitics", "type": "rss"},
    # Botschaften / Außenministerien
    {"name": "Auswärtiges Amt Reisewarnungen", "url": "https://www.auswaertiges-amt.de/opendata/travelwarning",
     "category": "geopolitics", "type": "aa"},
    {"name": "US State Dept Travel Advisories", "url": "https://travel.state.gov/_res/rss/TAsTWs.xml",
     "category": "geopolitics", "type": "rss"},
    {"name": "UK FCDO Travel Advice", "url": "https://www.gov.uk/foreign-travel-advice.atom",
     "category": "geopolitics", "type": "rss"},
    {"name": "US-Botschaft Deutschland (Alerts)", "url": "https://de.usembassy.gov/category/alert/feed/",
     "category": "geopolitics", "type": "rss"},

    # --- Naturkatastrophen & Extremwetter ----------------------------------
    {"name": "USGS Earthquakes", "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
     "category": "natural", "type": "usgs"},
    {"name": "GDACS", "url": "https://www.gdacs.org/xml/rss.xml",
     "category": "natural", "type": "gdacs"},
    {"name": "ReliefWeb Disasters", "url": "https://reliefweb.int/disasters/rss.xml",
     "category": "natural", "type": "rss"},

    # --- Infrastruktur, Bevölkerungsschutz & Supply Chain ------------------
    {"name": "BSI Aktuelles", "url": "https://www.bsi.bund.de/SiteGlobals/Functions/RSSFeed/RSSNewsfeed/RSSNewsfeed.xml",
     "category": "infrastructure", "type": "rss"},
    {"name": "NINA MoWaS (BBK)", "url": "https://warnung.bund.de/api31/mowas/mapData.json",
     "category": "infrastructure", "type": "nina"},
    {"name": "NINA KATWARN", "url": "https://warnung.bund.de/api31/katwarn/mapData.json",
     "category": "infrastructure", "type": "nina"},
    {"name": "NINA BIWAPP", "url": "https://warnung.bund.de/api31/biwapp/mapData.json",
     "category": "infrastructure", "type": "nina"},
    {"name": "Industrial Cyber (ICS/OT)", "url": "https://industrialcyber.co/feed/",
     "category": "infrastructure", "type": "rss"},
    {"name": "gCaptain (Maritime)", "url": "https://gcaptain.com/feed/",
     "category": "infrastructure", "type": "rss", "filter": True},
    {"name": "Supply Chain Dive", "url": "https://www.supplychaindive.com/feeds/news/",
     "category": "infrastructure", "type": "rss", "filter": True},
]
