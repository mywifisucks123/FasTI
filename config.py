# -*- coding: utf-8 -*-
"""
FasTI – Threat & Crisis Intelligence Dashboard
Zentrale Konfiguration. Alles, was du anpassen willst, steht hier.

API-Keys: Entweder unten eintragen ODER als Umgebungsvariable setzen
(GEMINI_API_KEY / GROQ_API_KEY bzw. eine Zeile in der Datei .env, die start.sh lädt).
Die Umgebungsvariable hat Vorrang.
"""
import os
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# KI-Analyse
# ---------------------------------------------------------------------------
# Reihenfolge der KI-Anbieter. Fällt der erste aus (Überlastung, Kontingent),
# wird automatisch der nächste mit gültigem Key genommen. Ohne gültigen Key
# läuft alles regelbasiert.
AI_PROVIDERS = [p.strip() for p in os.environ.get("AI_PROVIDER", "gemini,groq").split(",") if p.strip()]

# Key holen: https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "DEIN_KEY_HIER")
# Werden der Reihe nach probiert, wenn ein Modell fehlt oder überlastet ist (503).
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-flash-lite-latest"]
# 0 = "Thinking" aus (schneller, spart Free-Tier-Kontingent). None = Modell-Default.
GEMINI_THINKING_BUDGET = 0

# Key holen: https://console.groq.com/keys  (großzügigeres Free-Tier, guter Ersatz)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "DEIN_KEY_HIER")
GROQ_MODELS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant"]

# Sprache für Titel und Executive Summary
OUTPUT_LANGUAGE = "Deutsch"

# Free-Tier-Schutz: Einträge pro KI-Request, Pause zwischen Requests,
# Requests pro Durchlauf und pro Tag. Trigger-Kandidaten bekommen die KI zuerst.
AI_BATCH_SIZE = 10
AI_MIN_SECONDS_BETWEEN_CALLS = {"gemini": 7.0, "groq": 25.0}
AI_MAX_CALLS_PER_RUN = 8
AI_MAX_CALLS_PER_DAY = 200
AI_REQUEST_TIMEOUT = 120

# Wenn die KI nicht verfügbar ist: regelbasiert analysieren statt zurückstellen.
# Regelbasierte Einträge werden in späteren Durchläufen per KI nachveredelt.
AI_FALLBACK_HEURISTIC = True

# ---------------------------------------------------------------------------
# Polling & Speicherung
# ---------------------------------------------------------------------------
OUTPUT_FILE = "threats.json"
POLL_INTERVAL_MINUTES = 30        # Intervall für den Dauerbetrieb (start.sh / --loop)
MAX_ITEMS_PER_FEED = 10           # neueste N Einträge je Feed und Durchlauf
MAX_ENTRY_AGE_HOURS = 72          # ältere Feed-Einträge werden ignoriert
RETENTION_DAYS = 14               # Lagebild-Historie
TRIGGER_RETENTION_DAYS = 45       # Trigger-Treffer länger halten (30-Tage-Fenster des Plans)
MAX_STORED_THREATS = 600
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
# Auswärtiges Amt: Für diese Länder wird jede Aktualisierung der Reise- und
# Sicherheitshinweise gemeldet und der Text auf Ausreiseaufrufe geprüft (Trigger A8).
AA_WATCH_COUNTRIES = ["PL", "CZ", "AT", "CH", "FR", "LU", "BE", "NL", "DK", "LT", "LV", "EE", "FI"]


def gnews(query: str, lang: str = "de") -> str:
    """Google-News-Suche als RSS (kostenlos, ohne Key)."""
    region = {"de": "hl=de&gl=DE&ceid=DE:de", "en": "hl=en-US&gl=US&ceid=US:en"}[lang]
    return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:3d')}&{region}"


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
    {"name": "Tagesschau Inland", "url": "https://www.tagesschau.de/inland/index~rss2.xml",
     "category": "geopolitics", "type": "rss", "filter": True},
    {"name": "UN News", "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
     "category": "geopolitics", "type": "rss", "filter": True},
    {"name": "Bellingcat (OSINT)", "url": "https://www.bellingcat.com/feed/",
     "category": "geopolitics", "type": "rss"},
    {"name": "NATO News", "url": "https://www.nato.int/cps/rss/en/natohq/rssFeed.xsl/rssFeed.xml",
     "category": "geopolitics", "type": "rss"},
    {"name": "Bundestag hib", "url": "https://www.bundestag.de/static/appdata/includes/rss/hib.rss",
     "category": "geopolitics", "type": "rss", "filter": True},

    # --- Botschaften & Außenministerien -------------------------------------
    {"name": "Auswärtiges Amt Reisewarnungen", "url": "https://www.auswaertiges-amt.de/opendata/travelwarning",
     "category": "geopolitics", "type": "aa"},
    {"name": "US State Dept Travel Advisories", "url": "https://travel.state.gov/_res/rss/TAsTWs.xml",
     "category": "geopolitics", "type": "rss"},
    {"name": "UK FCDO Travel Advice", "url": "https://www.gov.uk/foreign-travel-advice.atom",
     "category": "geopolitics", "type": "rss"},
    {"name": "US-Botschaft Deutschland", "url": "https://de.usembassy.gov/category/alert/feed/",
     "category": "geopolitics", "type": "rss"},
    {"name": "US-Botschaft Polen", "url": "https://pl.usembassy.gov/category/alert/feed/",
     "category": "geopolitics", "type": "rss"},
    {"name": "US-Botschaft Litauen", "url": "https://lt.usembassy.gov/category/alert/feed/",
     "category": "geopolitics", "type": "rss"},
    {"name": "US-Botschaft Lettland", "url": "https://lv.usembassy.gov/category/alert/feed/",
     "category": "geopolitics", "type": "rss"},
    {"name": "US-Botschaft Estland", "url": "https://ee.usembassy.gov/category/alert/feed/",
     "category": "geopolitics", "type": "rss"},
    {"name": "UK FCDO Deutschland", "url": "https://www.gov.uk/foreign-travel-advice/germany.atom",
     "category": "geopolitics", "type": "rss"},
    {"name": "UK FCDO Polen", "url": "https://www.gov.uk/foreign-travel-advice/poland.atom",
     "category": "geopolitics", "type": "rss"},
    {"name": "UK FCDO Litauen", "url": "https://www.gov.uk/foreign-travel-advice/lithuania.atom",
     "category": "geopolitics", "type": "rss"},
    {"name": "UK FCDO Lettland", "url": "https://www.gov.uk/foreign-travel-advice/latvia.atom",
     "category": "geopolitics", "type": "rss"},
    {"name": "UK FCDO Estland", "url": "https://www.gov.uk/foreign-travel-advice/estonia.atom",
     "category": "geopolitics", "type": "rss"},

    # --- Gezielte Trigger-Suchen (Google News) ------------------------------
    {"name": "Suche: Botschaften Ausreise", "category": "geopolitics", "type": "rss", "filter": True,
     "url": gnews('"ordered departure" OR "authorized departure" embassy Germany OR Poland OR Lithuania OR Latvia OR Estonia', "en")},
    {"name": "Suche: Botschafter abberufen", "category": "geopolitics", "type": "rss", "filter": True,
     "url": gnews('Botschafter abberufen OR einbestellt OR ausgewiesen OR "Botschaft geschlossen"')},
    {"name": "Suche: Ambassador recalled", "category": "geopolitics", "type": "rss", "filter": True,
     "url": gnews('ambassador recalled OR expelled OR "embassy closed" Europe', "en")},
    {"name": "Suche: Spannungsfall / Bundestag", "category": "geopolitics", "type": "rss", "filter": True,
     "url": gnews('Spannungsfall OR Verteidigungsfall OR Zustimmungsfall Bundestag')},
    {"name": "Suche: Mobilmachung / Reservisten", "category": "geopolitics", "type": "rss", "filter": True,
     "url": gnews('Mobilmachung OR Teilmobilmachung OR Reservisten einberufen OR Einberufungsbescheid')},
    {"name": "Suche: NATO Artikel 4 / 5", "category": "geopolitics", "type": "rss", "filter": True,
     "url": gnews('NATO "Artikel 5" OR "Artikel 4" OR "Article 5" OR "Article 4"')},
    {"name": "Suche: Luftraum gesperrt", "category": "infrastructure", "type": "rss", "filter": True,
     "url": gnews('Luftraum gesperrt OR Flugverkehr eingestellt OR Flughafen gesperrt Drohne')},
    {"name": "Suche: Sabotage Deutschland", "category": "infrastructure", "type": "rss", "filter": True,
     "url": gnews('Sabotage Bahn OR Stromnetz OR Kabel OR Datennetz Deutschland')},
    {"name": "Suche: Ostflanke / Geheimdienstwarnung", "category": "geopolitics", "type": "rss", "filter": True,
     "url": gnews('Ostflanke NATO Verlegung OR Geheimdienst warnt Polen OR Baltikum')},
    {"name": "Suche: Grenzkontrollen / Hamsterkäufe", "category": "infrastructure", "type": "rss", "filter": True,
     "url": gnews('Grenzkontrollen verlängert OR Hamsterkäufe OR "leere Regale" OR Bargeld abheben Krise')},

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

# ---------------------------------------------------------------------------
# Trigger-Katalog (Krisen-Entscheidungsplan, Stand 27.09.2026)
# ---------------------------------------------------------------------------
# list A = harte Trigger (2 verschiedene Punkte in 30 Tagen → Stufe 2)
# list B = weiche Indikatoren (3+ gleichzeitig über 14 Tage → Liste A täglich prüfen)
# list D = Diplomatische Signale (Zusatz, nicht Teil des Plans, lösen nichts aus)
#
# ai:      Definition für die KI (präzise, inkl. was NICHT zählt)
# match:   regelbasierte Erkennung ohne KI – ALLE Muster müssen im Text vorkommen
# exclude: Muster, das einen Treffer verwirft (z. B. Übungen)
_DE_PL_BALT = r"germany|deutschland|berlin|frankfurt|poland|polen|warsaw|warschau|lithuania|litauen|vilnius|latvia|lettland|riga|estonia|estland|tallinn|baltic|baltikum|baltisch"
_NATO = (r"nato|germany|deutschland|poland|polen|lithuania|litauen|latvia|lettland|estonia|estland|finland|finnland|"
         r"sweden|schweden|norway|norwegen|denmark|dänemark|netherlands|niederlande|belgium|belgien|france|frankreich|"
         r"romania|rumänien|bulgaria|bulgarien|slovakia|slowakei|czech|tschechien|hungary|ungarn|united kingdom|britain|"
         r"großbritannien|italy|italien|spain|spanien|portugal|greece|griechenland|turkey|türkei")
_EXERCISE = r"übung|manöver|exercise|drill|wehrerfassung|fragebogen|musterung"

TRIGGERS = [
    {"id": "A1", "list": "A", "label": "USA/UK ordnen Ausreise von Botschaftsangehörigen aus DE, PL oder Baltikum an",
     "ai": "Die USA oder Großbritannien ordnen die Ausreise (ordered departure) von Botschaftspersonal und/oder deren "
           "Familien aus Deutschland, Polen, Litauen, Lettland oder Estland an. 'Authorized departure' (freiwillig) "
           "zählt NICHT, andere Länder zählen NICHT.",
     "match": [r"ordered departure|order(s|ed)? (the )?departure|departure of .{0,60}(embassy|staff|family)|ausreise.{0,40}(botschaft|diplomat)|(embassy|botschaft).{0,60}(evacuat|withdraw|abzug|abgezogen)|"
               r"(family members|familienangehörige).{0,60}(depart|leave|ausreise)", _DE_PL_BALT],
     "exclude": r"authorized departure"},
    {"id": "A2", "list": "A", "label": "NATO-Staat ruft Teilmobilmachung aus / beruft Reservisten flächendeckend ein",
     "ai": "Ein NATO-Mitgliedstaat verkündet eine (Teil-)Mobilmachung oder beruft Reservisten flächendeckend/landesweit ein. "
           "Übungen, Wehrdienstdebatten, Freiwilligenwerbung oder Russland/Ukraine zählen NICHT.",
     "match": [r"mobili[sz]ation|mobilmachung|teilmobilmachung|reservists?.{0,40}(called up|call-up|mobili)|reservisten.{0,40}einberuf", _NATO],
     "exclude": _EXERCISE + r"|russia|russland|ukrain"},
    {"id": "A3", "list": "A", "label": "Bundestag setzt Zustimmungs- oder Spannungsfall auf die Tagesordnung",
     "ai": "Der Deutsche Bundestag setzt die Feststellung des Spannungsfalls, des Zustimmungsfalls (Art. 80a GG) "
           "oder des Verteidigungsfalls auf die Tagesordnung oder stimmt darüber ab. Bloße Debatten/Forderungen zählen NICHT.",
     "match": [r"spannungsfall|zustimmungsfall|verteidigungsfall|state of tension|state of defen[cs]e", r"bundestag|tagesordnung|abstimmung|feststell"],
     "exclude": r"übung|planspiel"},
    {"id": "A4", "list": "A", "label": "Deutsche Reservisten erhalten reale Einberufungsbescheide",
     "ai": "Deutsche Reservisten erhalten reale Einberufungsbescheide zum Dienst. Übungen, Wehrerfassung, Fragebögen, "
           "Musterung zählen NICHT.",
     "match": [r"einberufungsbescheid|einberufen|called up|call-up", r"reservist", r"deutsch|german|bundeswehr"],
     "exclude": _EXERCISE},
    {"id": "A5", "list": "A", "label": "Artikel 5 wird formell beantragt",
     "ai": "Ein NATO-Mitgliedstaat beantragt/ruft formell den Bündnisfall nach Artikel 5 des Nordatlantikvertrags aus. "
           "Bloße Erwähnungen, Drohungen oder Debatten über Artikel 5 zählen NICHT.",
     "match": [r"article 5|artikel 5|art\. 5|bündnisfall", r"invok|beantrag|ausgerufen|aktiviert|triggered|formally"]},
    {"id": "A6", "list": "A", "label": "Ziviler Luftverkehr in Teilen Europas ausgesetzt / Lufträume gesperrt",
     "ai": "Ziviler Luftverkehr wird in Teilen Europas ausgesetzt oder Lufträume europäischer Staaten werden gesperrt "
           "(nicht nur einzelner Flughafen für wenige Stunden wegen Drohne/Wetter/Streik).",
     "match": [r"airspace|luftraum|lufträume|civil aviation|ziviler luftverkehr|flugverkehr", r"closed|closure|gesperrt|sperrung|suspend|eingestellt|ausgesetzt", _NATO],
     "exclude": r"streik|strike action|unwetter|storm"},
    {"id": "A7", "list": "A", "label": "Bewaffneter Zwischenfall mit Toten auf NATO-Territorium, einem Staat zugeordnet",
     "ai": "Ein bewaffneter Zwischenfall mit Todesopfern auf dem Territorium eines NATO-Mitgliedstaats, der offiziell einem "
           "Staat (z. B. Russland, Belarus) zugeordnet wird. Terror, Kriminalität, Unfälle oder Ukraine zählen NICHT.",
     "match": [r"killed|dead|tote|getötet|todesopfer", r"attack|strike|angriff|incursion|beschuss|drone|drohne|missile|rakete", _NATO,
               r"russia|russland|belarus|weißrussland|attribut|zugeordnet|verantwortlich"],
     "exclude": r"ukrain"},
    {"id": "A8", "list": "A", "label": "Auswärtiges Amt ruft Deutsche zur Ausreise aus mehreren Nachbarstaaten auf",
     "ai": "Das Auswärtige Amt fordert Deutsche zur Ausreise aus einem oder mehreren Nachbarstaaten Deutschlands bzw. "
           "dem Baltikum auf (PL, CZ, AT, CH, FR, LU, BE, NL, DK, LT, LV, EE). Aufrufe für ferne Länder zählen NICHT.",
     "match": [r"auswärtig|foreign office|german government|bundesregierung", r"ausreise|leave the country|verlassen", _DE_PL_BALT + r"|tschechien|österreich|schweiz|frankreich|luxemburg|belgien|niederlande|dänemark"]},

    {"id": "B1", "list": "B", "label": "Häufung von Sabotage an Strom-, Bahn- oder Datennetzen in DE",
     "ai": "Sabotage (nicht bloßer Defekt) an Strom-, Bahn- oder Daten-/Kommunikationsnetzen in Deutschland.",
     "match": [r"sabotage|anschlag|brandanschlag|kabelbrand", r"strom|bahn|gleis|rail|kabel|cable|datennetz|glasfaser|grid|umspannwerk", r"deutschland|germany|deutsche bahn|\bdb\b|berlin|nrw|bayern|hamburg"]},
    {"id": "B2", "list": "B", "label": "Drohnensichtungen über Flughäfen, Kasernen oder Kraftwerken",
     "ai": "Sichtungen nicht identifizierter/feindlicher Drohnen über Flughäfen, Kasernen, Militärstandorten oder "
           "Kraftwerken in Deutschland oder bei europäischen NATO-Partnern.",
     "match": [r"drohne|drone", r"flughafen|airport|kaserne|barracks|military base|stützpunkt|kraftwerk|power plant|flugverkehr"]},
    {"id": "B3", "list": "B", "label": "Artikel-4-Konsultationen der NATO",
     "ai": "Ein NATO-Staat beantragt Konsultationen nach Artikel 4 oder diese finden statt.",
     "match": [r"article 4|artikel 4|art\. 4", r"nato|konsultation|consultation"]},
    {"id": "B4", "list": "B", "label": "Warnungen von Regierungschefs PL/Baltikum mit Verweis auf Geheimdienstlagen",
     "ai": "Regierungschefs oder Präsidenten Polens, Litauens, Lettlands oder Estlands warnen öffentlich und verweisen "
           "dabei auf Geheimdienst-/Nachrichtendienstlagen.",
     "match": [r"poland|polen|polish|polnisch|lithuania|litauen|latvia|lettland|estonia|estland|baltic|baltikum",
               r"prime minister|premier|president|präsident|regierungschef|tusk|nawrocki",
               r"intelligence|geheimdienst|nachrichtendienst"]},
    {"id": "B5", "list": "B", "label": "Verlegung großer NATO-Verbände an die Ostflanke",
     "ai": "Verlegung großer NATO-Verbände (Brigade oder größer) an die Ostflanke. Routinerotationen und Übungen zählen NICHT.",
     "match": [r"nato|bundeswehr|us army|us troops|brigade|division", r"eastern flank|ostflanke|baltic|baltikum|poland|polen|litauen|lithuania",
               r"deploy|verleg|stationier|reinforc|verstärk"],
     "exclude": r"exercise|übung|manöver"},
    {"id": "B6", "list": "B", "label": "Hamsterkäufe, Bargeldabhebungen über Normalmaß, leere Regale",
     "ai": "Berichte über Hamsterkäufe, ungewöhnlich hohe Bargeldabhebungen oder leere Regale in Deutschland.",
     "match": [r"hamsterk|panic buying|leere regale|empty shelves|bank run|bargeld.{0,30}(abheb|knapp|ansturm)"]},
    {"id": "B7", "list": "B", "label": "Dauerhafte Grenzkontrollen innerhalb des Schengenraums",
     "ai": "Einführung oder Verlängerung dauerhafter Binnengrenzkontrollen im Schengenraum.",
     "match": [r"grenzkontroll|border control|border checks", r"schengen|binnengrenz|internal border|verläng|extend|einführ|reintroduc"]},

    {"id": "D1", "list": "D", "label": "Botschafter abberufen, einbestellt oder ausgewiesen (Europa)",
     "ai": "Ein Staat ruft seinen Botschafter aus einem europäischen Land zurück, bestellt einen Botschafter ein oder "
           "weist Diplomaten aus, mit Bezug zu Europa/NATO/Russland.",
     "match": [r"botschafter|ambassador|diplomat", r"abberuf|zurückgerufen|zurückberufen|ruft.{0,60}zurück|einbestellt|bestellt.{0,60}ein\b|ausgewiesen|ausweis|recall|summon|expel|persona non grata"]},
    {"id": "D2", "list": "D", "label": "Botschaft geschlossen / Personal reduziert / Sicherheitswarnung einer Botschaft in Europa",
     "ai": "Eine Botschaft in Europa schließt, reduziert ihr Personal, erlaubt freiwillige Ausreise (authorized departure) "
           "oder veröffentlicht eine Sicherheitswarnung (Security Alert) für ihre Bürger.",
     "match": [r"embassy|botschaft|konsulat|consulate", r"closed|schließ|geschlossen|security alert|sicherheitswarnung|authorized departure|reduc|reduzier"]},
    {"id": "D3", "list": "D", "label": "Reise- und Sicherheitshinweise für DE, PL oder Baltikum verschärft",
     "ai": "Ein Außenministerium (USA, UK, Deutschland oder anderes) verschärft Reise- oder Sicherheitshinweise für "
           "Deutschland, Polen, Litauen, Lettland oder Estland.",
     "match": [r"travel advi|reisehinweis|reisewarnung|sicherheitshinweis|level [34]", _DE_PL_BALT]},
]
