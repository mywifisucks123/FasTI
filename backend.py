#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FasTI – Threat & Crisis Intelligence Backend

Pollt die Quellen aus config.py, analysiert neue Einträge per KI (Gemini/Groq)
oder regelbasiert und schreibt das Lagebild nach threats.json.

  python3 backend.py              # ein Durchlauf
  python3 backend.py --loop       # Dauerbetrieb (Intervall aus config.py)
  python3 backend.py --no-ai      # nur regelbasiert
  python3 backend.py --reset      # threats.json verwerfen und neu aufbauen
"""
from __future__ import annotations

import argparse
import calendar
import fcntl
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

try:
    import feedparser
    import requests
except ImportError:
    sys.stderr.write("Fehlende Pakete. Bitte installieren: pip3 install feedparser requests\n")
    sys.exit(1)

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, config.OUTPUT_FILE)
LOCK_FILE = os.path.join(BASE_DIR, ".backend.lock")
CATEGORIES = ("cyber", "geopolitics", "natural", "infrastructure")
SCHEMA_VERSION = 1

log = logging.getLogger("fasti")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.USER_AGENT,
                        "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, text/xml, */*"})


# ===========================================================================
# Hilfsfunktionen
# ===========================================================================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def make_id(*parts: str) -> str:
    raw = "|".join(p.strip() for p in parts if p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(value: str | None, limit: int = 0) -> str:
    if not value:
        return ""
    text = html.unescape(TAG_RE.sub(" ", value))
    text = WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " …"
    return text


SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9\"'„(])")


FEED_NOISE_RE = re.compile(
    r"\[(?:\.\.\.|…|&#8230;)\]|\s*(?:The post|Der Beitrag) .{0,200}? (?:appeared first on|erschien zuerst auf) .*$|"
    r"\s*(?:Continue reading|Read more|Weiterlesen)\b.*$", re.IGNORECASE)


def two_sentences(text: str) -> str:
    """Kürzt auf maximal zwei Sätze."""
    text = FEED_NOISE_RE.sub("", clean_text(text)).strip()
    if not text:
        return ""
    parts = [p.strip() for p in SENT_RE.split(text) if p.strip()]
    out = " ".join(parts[:2])
    if len(out) > 420:
        out = out[:420].rsplit(" ", 1)[0] + " …"
    if out and out[-1] not in ".!?…":
        out += "."
    return out


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", title.lower()).strip()


def to_float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN raus


def valid_coords(lat, lon) -> tuple[float, float] | tuple[None, None]:
    lat, lon = to_float(lat), to_float(lon)
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, None
    if lat == 0 and lon == 0:
        return None, None
    return round(lat, 4), round(lon, 4)


def safe_url(url: str | None) -> str:
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def http_get(url: str, **kwargs) -> requests.Response:
    resp = SESSION.get(url, timeout=config.REQUEST_TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


# ===========================================================================
# Gazetteer (Geotagging ohne KI und Fallback für KI-Ergebnisse)
# ===========================================================================
# ISO2, Anzeigename, Lat, Lon, Aliasse (exakte Wörter, | getrennt), deutsche Adjektivstämme
COUNTRIES = [
    ("AF", "Afghanistan", 33.94, 67.71, "Afghanistan|Afghan|Taliban", "afghanisch"),
    ("AL", "Albanien", 41.15, 20.17, "Albania|Albanien|Albanian", "albanisch"),
    ("DZ", "Algerien", 28.03, 1.66, "Algeria|Algerien|Algerian", "algerisch"),
    ("AO", "Angola", -11.20, 17.87, "Angola|Angolan", "angolanisch"),
    ("AR", "Argentinien", -38.42, -63.62, "Argentina|Argentinien|Argentine|Argentinian", "argentinisch"),
    ("AM", "Armenien", 40.07, 45.04, "Armenia|Armenien|Armenian", "armenisch"),
    ("AU", "Australien", -25.27, 133.78, "Australia|Australien|Australian", "australisch"),
    ("AT", "Österreich", 47.52, 14.55, "Austria|Österreich|Oesterreich|Austrian", "österreichisch"),
    ("AZ", "Aserbaidschan", 40.14, 47.58, "Azerbaijan|Aserbaidschan|Azerbaijani", "aserbaidschanisch"),
    ("BD", "Bangladesch", 23.68, 90.36, "Bangladesh|Bangladesch|Bangladeshi", "bangladeschisch"),
    ("BY", "Belarus", 53.71, 27.95, "Belarus|Weißrussland|Belarusian|Lukashenko|Lukaschenko", "belarussisch"),
    ("BE", "Belgien", 50.50, 4.47, "Belgium|Belgien|Belgian", "belgisch"),
    ("BJ", "Benin", 9.31, 2.32, "Benin", "beninisch"),
    ("BO", "Bolivien", -16.29, -63.59, "Bolivia|Bolivien|Bolivian", "bolivianisch"),
    ("BA", "Bosnien und Herzegowina", 43.92, 17.68, "Bosnia|Bosnien|Bosnian|Republika Srpska", "bosnisch"),
    ("BR", "Brasilien", -14.24, -51.93, "Brazil|Brasilien|Brazilian", "brasilianisch"),
    ("BG", "Bulgarien", 42.73, 25.49, "Bulgaria|Bulgarien|Bulgarian", "bulgarisch"),
    ("BF", "Burkina Faso", 12.24, -1.56, "Burkina Faso|Burkinabe", ""),
    ("MM", "Myanmar", 21.91, 95.96, "Myanmar|Burma|Birma|Burmese", "birmanisch"),
    ("BI", "Burundi", -3.37, 29.92, "Burundi", "burundisch"),
    ("KH", "Kambodscha", 12.57, 104.99, "Cambodia|Kambodscha|Cambodian", "kambodschanisch"),
    ("CM", "Kamerun", 7.37, 12.35, "Cameroon|Kamerun|Cameroonian", "kamerunisch"),
    ("CA", "Kanada", 56.13, -106.35, "Canada|Kanada|Canadian", "kanadisch"),
    ("CF", "Zentralafrikanische Republik", 6.61, 20.94, "Central African Republic|Zentralafrikanische Republik", "zentralafrikanisch"),
    ("TD", "Tschad", 15.45, 18.73, "Chad|Tschad|Chadian", "tschadisch"),
    ("CL", "Chile", -35.68, -71.54, "Chile|Chilean", "chilenisch"),
    ("CN", "China", 35.86, 104.20, "China|Chinese|PRC|Volksrepublik China", "chinesisch"),
    ("CO", "Kolumbien", 4.57, -74.30, "Colombia|Kolumbien|Colombian", "kolumbianisch"),
    ("CD", "DR Kongo", -4.04, 21.76, "Democratic Republic of the Congo|DR Congo|DRC|DR Kongo|Demokratische Republik Kongo|Congo|Kongo|M23", "kongolesisch"),
    ("HR", "Kroatien", 45.10, 15.20, "Croatia|Kroatien|Croatian", "kroatisch"),
    ("CU", "Kuba", 21.52, -77.78, "Cuba|Kuba|Cuban", "kubanisch"),
    ("CY", "Zypern", 35.13, 33.43, "Cyprus|Zypern|Cypriot", "zyprisch"),
    ("CZ", "Tschechien", 49.82, 15.47, "Czech Republic|Czechia|Tschechien|Czech", "tschechisch"),
    ("DK", "Dänemark", 56.26, 9.50, "Denmark|Dänemark|Danish|Greenland|Grönland", "dänisch"),
    ("EC", "Ecuador", -1.83, -78.18, "Ecuador|Ecuadorian", "ecuadorianisch"),
    ("EG", "Ägypten", 26.82, 30.80, "Egypt|Ägypten|Egyptian|Suez", "ägyptisch"),
    ("SV", "El Salvador", 13.79, -88.90, "El Salvador|Salvadoran", "salvadorianisch"),
    ("ER", "Eritrea", 15.18, 39.78, "Eritrea|Eritrean", "eritreisch"),
    ("EE", "Estland", 58.60, 25.01, "Estonia|Estland|Estonian", "estnisch"),
    ("ET", "Äthiopien", 9.15, 40.49, "Ethiopia|Äthiopien|Ethiopian|Tigray|Amhara", "äthiopisch"),
    ("FI", "Finnland", 61.92, 25.75, "Finland|Finnland|Finnish", "finnisch"),
    ("FR", "Frankreich", 46.23, 2.21, "France|Frankreich|French", "französisch"),
    ("GE", "Georgien", 42.32, 43.36, "Georgien|Tbilisi|Tiflis|Georgian", "georgisch"),
    ("DE", "Deutschland", 51.17, 10.45, "Germany|Deutschland|German|Bundesregierung|Bundeswehr|Bundesamt", "deutsch"),
    ("GH", "Ghana", 7.95, -1.02, "Ghana|Ghanaian", "ghanaisch"),
    ("GR", "Griechenland", 39.07, 21.82, "Greece|Griechenland|Greek", "griechisch"),
    ("GT", "Guatemala", 15.78, -90.23, "Guatemala|Guatemalan", "guatemaltekisch"),
    ("GN", "Guinea", 9.95, -9.70, "Guinea|Guinean", "guineisch"),
    ("HT", "Haiti", 18.97, -72.29, "Haiti|Haitian|Port-au-Prince", "haitianisch"),
    ("HN", "Honduras", 15.20, -86.24, "Honduras|Honduran", "honduranisch"),
    ("HU", "Ungarn", 47.16, 19.50, "Hungary|Ungarn|Hungarian|Orban|Orbán", "ungarisch"),
    ("IS", "Island", 64.96, -19.02, "Iceland|Icelandic|Grindavik|Reykjanes", "isländisch"),
    ("IN", "Indien", 20.59, 78.96, "India|Indien|Indian|Kashmir|Kaschmir", "indisch"),
    ("ID", "Indonesien", -0.79, 113.92, "Indonesia|Indonesien|Indonesian|Sumatra|Java|Sulawesi", "indonesisch"),
    ("IR", "Iran", 32.43, 53.69, "Iran|Iranian|IRGC", "iranisch"),
    ("IQ", "Irak", 33.22, 43.68, "Iraq|Irak|Iraqi", "irakisch"),
    ("IE", "Irland", 53.41, -8.24, "Ireland|Irland|Irish", "irisch"),
    ("IL", "Israel", 31.05, 34.85, "Israel|Israeli|IDF", "israelisch"),
    ("PS", "Palästinensische Gebiete", 31.95, 35.23, "Palestine|Palestinian|Palästina|West Bank|Westjordanland|Hamas", "palästinensisch"),
    ("IT", "Italien", 41.87, 12.57, "Italy|Italien|Italian", "italienisch"),
    ("JP", "Japan", 36.20, 138.25, "Japan|Japanese", "japanisch"),
    ("JO", "Jordanien", 30.59, 36.24, "Jordan|Jordanien|Jordanian", "jordanisch"),
    ("KZ", "Kasachstan", 48.02, 66.92, "Kazakhstan|Kasachstan|Kazakh", "kasachisch"),
    ("KE", "Kenia", -0.02, 37.91, "Kenya|Kenia|Kenyan", "kenianisch"),
    ("XK", "Kosovo", 42.60, 20.90, "Kosovo|Kosovar", "kosovarisch"),
    ("KP", "Nordkorea", 40.34, 127.51, "North Korea|Nordkorea|DPRK|North Korean", "nordkoreanisch"),
    ("KR", "Südkorea", 35.91, 127.77, "South Korea|Südkorea|South Korean", "südkoreanisch"),
    ("KW", "Kuwait", 29.31, 47.48, "Kuwait|Kuwaiti", "kuwaitisch"),
    ("KG", "Kirgisistan", 41.20, 74.77, "Kyrgyzstan|Kirgisistan|Kyrgyz", "kirgisisch"),
    ("LV", "Lettland", 56.88, 24.60, "Latvia|Lettland|Latvian", "lettisch"),
    ("LB", "Libanon", 33.85, 35.86, "Lebanon|Libanon|Lebanese|Hezbollah|Hisbollah", "libanesisch"),
    ("LY", "Libyen", 26.34, 17.23, "Libya|Libyen|Libyan", "libysch"),
    ("LT", "Litauen", 55.17, 23.88, "Lithuania|Litauen|Lithuanian", "litauisch"),
    ("LU", "Luxemburg", 49.82, 6.13, "Luxembourg|Luxemburg", "luxemburgisch"),
    ("MG", "Madagaskar", -18.77, 46.87, "Madagascar|Madagaskar|Malagasy", "madagassisch"),
    ("MW", "Malawi", -13.25, 34.30, "Malawi|Malawian", "malawisch"),
    ("MY", "Malaysia", 4.21, 101.98, "Malaysia|Malaysian", "malaysisch"),
    ("ML", "Mali", 17.57, -4.00, "Mali|Malian", "malisch"),
    ("MX", "Mexiko", 23.63, -102.55, "Mexico|Mexiko|Mexican", "mexikanisch"),
    ("MD", "Moldau", 47.41, 28.37, "Moldova|Moldau|Moldawien|Moldovan|Transnistria|Transnistrien", "moldauisch"),
    ("MN", "Mongolei", 46.86, 103.85, "Mongolia|Mongolei|Mongolian", "mongolisch"),
    ("ME", "Montenegro", 42.71, 19.37, "Montenegro|Montenegrin", "montenegrinisch"),
    ("MA", "Marokko", 31.79, -7.09, "Morocco|Marokko|Moroccan", "marokkanisch"),
    ("MZ", "Mosambik", -18.67, 35.53, "Mozambique|Mosambik|Mozambican|Cabo Delgado", "mosambikanisch"),
    ("NP", "Nepal", 28.39, 84.12, "Nepal|Nepalese", "nepalesisch"),
    ("NL", "Niederlande", 52.13, 5.29, "Netherlands|Niederlande|Holland|Dutch", "niederländisch"),
    ("NZ", "Neuseeland", -40.90, 174.89, "New Zealand|Neuseeland", "neuseeländisch"),
    ("NI", "Nicaragua", 12.87, -85.21, "Nicaragua|Nicaraguan", "nicaraguanisch"),
    ("NE", "Niger", 17.61, 8.08, "Niger|Nigerien", "nigrisch"),
    ("NG", "Nigeria", 9.08, 8.68, "Nigeria|Nigerian|Boko Haram", "nigerianisch"),
    ("MK", "Nordmazedonien", 41.61, 21.75, "North Macedonia|Nordmazedonien|Macedonian", "mazedonisch"),
    ("NO", "Norwegen", 60.47, 8.47, "Norway|Norwegen|Norwegian", "norwegisch"),
    ("OM", "Oman", 21.51, 55.92, "Oman|Omani", "omanisch"),
    ("PK", "Pakistan", 30.38, 69.35, "Pakistan|Pakistani|Balochistan|Belutschistan", "pakistanisch"),
    ("PA", "Panama", 8.54, -80.78, "Panama|Panamanian", "panamaisch"),
    ("PG", "Papua-Neuguinea", -6.31, 143.96, "Papua New Guinea|Papua-Neuguinea", ""),
    ("PY", "Paraguay", -23.44, -58.44, "Paraguay|Paraguayan", "paraguayisch"),
    ("PE", "Peru", -9.19, -75.02, "Peru|Peruvian", "peruanisch"),
    ("PH", "Philippinen", 12.88, 121.77, "Philippines|Philippinen|Filipino|Philippine", "philippinisch"),
    ("PL", "Polen", 51.92, 19.15, "Poland|Polen|Polish", "polnisch"),
    ("PT", "Portugal", 39.40, -8.22, "Portugal|Portuguese", "portugiesisch"),
    ("QA", "Katar", 25.35, 51.18, "Qatar|Katar|Qatari", "katarisch"),
    ("RO", "Rumänien", 45.94, 24.97, "Romania|Rumänien|Romanian", "rumänisch"),
    ("RU", "Russland", 55.75, 37.62, "Russia|Russland|Russian|Kremlin|Kreml|Putin", "russisch"),
    ("RW", "Ruanda", -1.94, 29.87, "Rwanda|Ruanda|Rwandan", "ruandisch"),
    ("SA", "Saudi-Arabien", 23.89, 45.08, "Saudi Arabia|Saudi-Arabien|Saudi", "saudisch"),
    ("SN", "Senegal", 14.50, -14.45, "Senegal|Senegalese", "senegalesisch"),
    ("RS", "Serbien", 44.02, 21.01, "Serbia|Serbien|Serbian", "serbisch"),
    ("SL", "Sierra Leone", 8.46, -11.78, "Sierra Leone", ""),
    ("SG", "Singapur", 1.35, 103.82, "Singapore|Singapur", "singapurisch"),
    ("SK", "Slowakei", 48.67, 19.70, "Slovakia|Slowakei|Slovak", "slowakisch"),
    ("SI", "Slowenien", 46.15, 14.99, "Slovenia|Slowenien|Slovenian", "slowenisch"),
    ("SO", "Somalia", 5.15, 46.20, "Somalia|Somali|al-Shabaab|Al-Shabab|Somaliland", "somalisch"),
    ("ZA", "Südafrika", -30.56, 22.94, "South Africa|Südafrika|South African", "südafrikanisch"),
    ("SS", "Südsudan", 6.88, 31.31, "South Sudan|Südsudan|South Sudanese", "südsudanesisch"),
    ("ES", "Spanien", 40.46, -3.75, "Spain|Spanien|Spanish", "spanisch"),
    ("LK", "Sri Lanka", 7.87, 80.77, "Sri Lanka|Sri Lankan", "sri-lankisch"),
    ("SD", "Sudan", 12.86, 30.22, "Sudan|Sudanese|Darfur|RSF|Rapid Support Forces", "sudanesisch"),
    ("SE", "Schweden", 60.13, 18.64, "Sweden|Schweden|Swedish", "schwedisch"),
    ("CH", "Schweiz", 46.82, 8.23, "Switzerland|Schweiz|Swiss", "schweizerisch"),
    ("SY", "Syrien", 34.80, 38.99, "Syria|Syrien|Syrian", "syrisch"),
    ("TW", "Taiwan", 23.70, 120.96, "Taiwan|Taiwanese|Taiwan Strait|Taiwanstraße", "taiwanisch"),
    ("TJ", "Tadschikistan", 38.86, 71.28, "Tajikistan|Tadschikistan|Tajik", "tadschikisch"),
    ("TZ", "Tansania", -6.37, 34.89, "Tanzania|Tansania|Tanzanian", "tansanisch"),
    ("TH", "Thailand", 15.87, 100.99, "Thailand|Thai", "thailändisch"),
    ("TN", "Tunesien", 33.89, 9.54, "Tunisia|Tunesien|Tunisian", "tunesisch"),
    ("TR", "Türkei", 38.96, 35.24, "Turkey|Türkei|Türkiye|Turkish|Erdogan|Erdoğan", "türkisch"),
    ("TM", "Turkmenistan", 38.97, 59.56, "Turkmenistan|Turkmen", "turkmenisch"),
    ("UG", "Uganda", 1.37, 32.29, "Uganda|Ugandan", "ugandisch"),
    ("UA", "Ukraine", 48.38, 31.17, "Ukraine|Ukrainian|Donbas|Donbass|Crimea|Krim", "ukrainisch"),
    ("AE", "Vereinigte Arabische Emirate", 23.42, 53.85, "United Arab Emirates|UAE|Vereinigte Arabische Emirate|VAE|Emirati", "emiratisch"),
    ("GB", "Vereinigtes Königreich", 54.00, -2.00, "United Kingdom|UK|Britain|Great Britain|Großbritannien|England|Scotland|Schottland|Wales|British", "britisch"),
    ("US", "USA", 39.83, -98.58, "United States|USA|U.S.|US|America|Amerika|American|Pentagon|White House|Weißes Haus", "amerikanisch|us-amerikanisch"),
    ("UY", "Uruguay", -32.52, -55.77, "Uruguay|Uruguayan", "uruguayisch"),
    ("UZ", "Usbekistan", 41.38, 64.59, "Uzbekistan|Usbekistan|Uzbek", "usbekisch"),
    ("VE", "Venezuela", 6.42, -66.59, "Venezuela|Venezuelan|Maduro", "venezolanisch"),
    ("VN", "Vietnam", 14.06, 108.28, "Vietnam|Vietnamese", "vietnamesisch"),
    ("YE", "Jemen", 15.55, 48.52, "Yemen|Jemen|Yemeni|Houthi|Houthis|Huthi|Huthis", "jemenitisch"),
    ("ZM", "Sambia", -13.13, 27.85, "Zambia|Sambia|Zambian", "sambisch"),
    ("ZW", "Simbabwe", -19.02, 29.15, "Zimbabwe|Simbabwe|Zimbabwean", "simbabwisch"),
    # Seegebiete und Regionen (ohne ISO-Code)
    ("", "Rotes Meer", 20.00, 38.50, "Red Sea|Rotes Meer|Roten Meer|Bab el-Mandeb|Gulf of Aden|Golf von Aden", ""),
    ("", "Straße von Hormus", 26.57, 56.25, "Strait of Hormuz|Straße von Hormus|Hormuz|Hormus", ""),
    ("", "Ostsee", 58.00, 19.00, "Baltic Sea|Ostsee", ""),
    ("", "Schwarzes Meer", 43.40, 34.00, "Black Sea|Schwarzes Meer|Schwarzen Meer", ""),
    ("", "Südchinesisches Meer", 12.00, 113.00, "South China Sea|Südchinesisches Meer|Südchinesischen Meer", ""),
    ("", "Sahel", 15.00, 2.00, "Sahel", ""),
]

# Anzeigename, ISO2, Lat, Lon, Aliasse
CITIES = [
    ("Berlin", "DE", 52.52, 13.405, "Berlin"),
    ("Hamburg", "DE", 53.55, 9.99, "Hamburg"),
    ("München", "DE", 48.14, 11.58, "Munich|München"),
    ("Frankfurt am Main", "DE", 50.11, 8.68, "Frankfurt"),
    ("Köln", "DE", 50.94, 6.96, "Cologne|Köln"),
    ("Düsseldorf", "DE", 51.23, 6.77, "Düsseldorf|Duesseldorf"),
    ("Bielefeld", "DE", 52.02, 8.53, "Bielefeld"),
    ("Bonn", "DE", 50.73, 7.10, "Bonn"),
    ("Kyjiw", "UA", 50.45, 30.52, "Kyiv|Kiev|Kiew|Kyjiw"),
    ("Charkiw", "UA", 49.99, 36.23, "Kharkiv|Charkiw"),
    ("Odesa", "UA", 46.48, 30.72, "Odesa|Odessa"),
    ("Saporischschja", "UA", 47.84, 35.14, "Zaporizhzhia|Saporischschja|Zaporizhia"),
    ("Dnipro", "UA", 48.46, 35.05, "Dnipro"),
    ("Moskau", "RU", 55.75, 37.62, "Moscow|Moskau"),
    ("Sankt Petersburg", "RU", 59.93, 30.36, "St Petersburg|St. Petersburg|Sankt Petersburg"),
    ("Kursk", "RU", 51.73, 36.19, "Kursk"),
    ("Belgorod", "RU", 50.60, 36.59, "Belgorod"),
    ("Kaliningrad", "RU", 54.71, 20.51, "Kaliningrad"),
    ("Minsk", "BY", 53.90, 27.56, "Minsk"),
    ("Gaza", "PS", 31.50, 34.47, "Gaza|Gaza Strip|Gazastreifen|Rafah|Khan Younis|Chan Junis"),
    ("Jerusalem", "IL", 31.77, 35.21, "Jerusalem"),
    ("Tel Aviv", "IL", 32.09, 34.78, "Tel Aviv"),
    ("Beirut", "LB", 33.89, 35.50, "Beirut"),
    ("Damaskus", "SY", 33.51, 36.28, "Damascus|Damaskus"),
    ("Aleppo", "SY", 36.20, 37.13, "Aleppo"),
    ("Teheran", "IR", 35.69, 51.39, "Tehran|Teheran"),
    ("Bagdad", "IQ", 33.31, 44.36, "Baghdad|Bagdad"),
    ("Sanaa", "YE", 15.37, 44.19, "Sanaa|Sana'a"),
    ("Aden", "YE", 12.79, 45.02, "Aden"),
    ("Kabul", "AF", 34.56, 69.21, "Kabul"),
    ("Khartum", "SD", 15.50, 32.56, "Khartoum|Khartum"),
    ("El Fasher", "SD", 13.63, 25.35, "El Fasher|El-Fasher|al-Fashir"),
    ("Goma", "CD", -1.68, 29.22, "Goma"),
    ("Kinshasa", "CD", -4.44, 15.27, "Kinshasa"),
    ("Mogadischu", "SO", 2.05, 45.32, "Mogadishu|Mogadischu"),
    ("Nairobi", "KE", -1.29, 36.82, "Nairobi"),
    ("Addis Abeba", "ET", 9.03, 38.74, "Addis Ababa|Addis Abeba"),
    ("Kairo", "EG", 30.04, 31.24, "Cairo|Kairo"),
    ("Tripolis", "LY", 32.89, 13.19, "Tripoli|Tripolis"),
    ("Istanbul", "TR", 41.01, 28.98, "Istanbul"),
    ("Ankara", "TR", 39.93, 32.86, "Ankara"),
    ("London", "GB", 51.51, -0.13, "London"),
    ("Paris", "FR", 48.86, 2.35, "Paris"),
    ("Brüssel", "BE", 50.85, 4.35, "Brussels|Brüssel"),
    ("Den Haag", "NL", 52.07, 4.30, "The Hague|Den Haag"),
    ("Amsterdam", "NL", 52.37, 4.90, "Amsterdam"),
    ("Wien", "AT", 48.21, 16.37, "Vienna|Wien"),
    ("Genf", "CH", 46.20, 6.14, "Geneva|Genf"),
    ("Warschau", "PL", 52.23, 21.01, "Warsaw|Warschau"),
    ("Vilnius", "LT", 54.69, 25.28, "Vilnius"),
    ("Riga", "LV", 56.95, 24.11, "Riga"),
    ("Tallinn", "EE", 59.44, 24.75, "Tallinn"),
    ("Helsinki", "FI", 60.17, 24.94, "Helsinki"),
    ("Stockholm", "SE", 59.33, 18.07, "Stockholm"),
    ("Rom", "IT", 41.90, 12.50, "Rome"),
    ("Madrid", "ES", 40.42, -3.70, "Madrid"),
    ("Belgrad", "RS", 44.79, 20.45, "Belgrade|Belgrad"),
    ("Chișinău", "MD", 47.01, 28.86, "Chisinau|Chișinău|Kischinau"),
    ("Tiflis", "GE", 41.72, 44.79, "Tbilisi|Tiflis"),
    ("Washington, D.C.", "US", 38.90, -77.04, "Washington|Washington DC|Washington, D.C."),
    ("New York", "US", 40.71, -74.01, "New York"),
    ("Los Angeles", "US", 34.05, -118.24, "Los Angeles"),
    ("Mexiko-Stadt", "MX", 19.43, -99.13, "Mexico City|Mexiko-Stadt"),
    ("Caracas", "VE", 10.48, -66.90, "Caracas"),
    ("Port-au-Prince", "HT", 18.59, -72.31, "Port-au-Prince"),
    ("Peking", "CN", 39.90, 116.41, "Beijing|Peking"),
    ("Shanghai", "CN", 31.23, 121.47, "Shanghai"),
    ("Hongkong", "CN", 22.32, 114.17, "Hong Kong|Hongkong"),
    ("Taipeh", "TW", 25.03, 121.57, "Taipei|Taipeh"),
    ("Tokio", "JP", 35.68, 139.69, "Tokyo|Tokio"),
    ("Seoul", "KR", 37.57, 126.98, "Seoul"),
    ("Pjöngjang", "KP", 39.04, 125.76, "Pyongyang|Pjöngjang"),
    ("Neu-Delhi", "IN", 28.61, 77.21, "New Delhi|Neu-Delhi|Delhi"),
    ("Mumbai", "IN", 19.08, 72.88, "Mumbai"),
    ("Islamabad", "PK", 33.68, 73.05, "Islamabad"),
    ("Karachi", "PK", 24.86, 67.01, "Karachi|Karatschi"),
    ("Dhaka", "BD", 23.81, 90.41, "Dhaka|Dhaka"),
    ("Manila", "PH", 14.60, 120.98, "Manila"),
    ("Jakarta", "ID", -6.21, 106.85, "Jakarta"),
    ("Bangkok", "TH", 13.76, 100.50, "Bangkok"),
    ("Sydney", "AU", -33.87, 151.21, "Sydney"),
]


def _alias_pattern(aliases: list[str]) -> str:
    aliases = sorted(set(a for a in aliases if a), key=len, reverse=True)
    return r"(?<![\w-])(" + "|".join(re.escape(a) for a in aliases) + r")(?![\w-])"


def _build_gazetteer():
    lookup_ci: dict[str, tuple] = {}
    lookup_cs: dict[str, tuple] = {}
    by_iso: dict[str, tuple] = {}
    for iso2, name, lat, lon, aliases, adj in COUNTRIES:
        entry = ("country", iso2, name, lat, lon)
        if iso2:
            by_iso[iso2] = entry
        words = [name] + aliases.split("|")
        for stem in filter(None, adj.split("|")):
            words += [stem + suffix for suffix in ("", "e", "en", "er", "es", "em")]
        for w in words:
            # Kurze Akronyme (US, UK, IDF …) nur case-sensitiv
            if len(w) <= 4 and w.upper() == w:
                lookup_cs[w] = entry
            else:
                lookup_ci[w.lower()] = entry
    for name, iso2, lat, lon, aliases in CITIES:
        entry = ("city", iso2, name, lat, lon)
        for w in [name] + aliases.split("|"):
            lookup_ci[w.lower()] = entry
    re_ci = re.compile(_alias_pattern(list(lookup_ci)), re.IGNORECASE)
    re_cs = re.compile(_alias_pattern(list(lookup_cs)))
    return lookup_ci, lookup_cs, by_iso, re_ci, re_cs


GAZ_CI, GAZ_CS, GAZ_ISO, GAZ_RE_CI, GAZ_RE_CS = _build_gazetteer()


def geolocate(title: str, text: str = "") -> dict | None:
    """Ermittelt den wahrscheinlichsten Ort aus Titel (3-fach gewichtet) und Text."""
    scores: dict[str, float] = {}
    first_pos: dict[str, int] = {}
    cities: dict[str, tuple] = {}
    regions: dict[str, tuple] = {}
    for weight, content in ((3.0, title or ""), (1.0, text or "")):
        offset = 0 if weight > 1 else 10_000
        hits = [(m.start(), GAZ_CI[m.group(1).lower()]) for m in GAZ_RE_CI.finditer(content)]
        hits += [(m.start(), GAZ_CS[m.group(1)]) for m in GAZ_RE_CS.finditer(content)]
        for pos, entry in hits:
            kind, iso2, name = entry[0], entry[1], entry[2]
            key = iso2 or "REGION:" + name
            scores[key] = scores.get(key, 0) + weight
            first_pos.setdefault(key, pos + offset)
            if kind == "city":
                cities.setdefault(iso2, entry)
            if not iso2:
                regions[key] = entry
    if not scores:
        return None
    best = sorted(scores, key=lambda k: (-scores[k], first_pos[k]))[0]
    if best in regions:
        _, _, name, lat, lon = regions[best]
        return {"location_name": name, "country_code": "", "latitude": lat, "longitude": lon}
    country = GAZ_ISO.get(best)
    if best in cities:
        _, iso2, name, lat, lon = cities[best]
        cname = country[2] if country else ""
        return {"location_name": f"{name}, {cname}" if cname else name,
                "country_code": iso2, "latitude": lat, "longitude": lon}
    if country:
        _, iso2, name, lat, lon = country
        return {"location_name": name, "country_code": iso2, "latitude": lat, "longitude": lon}
    return None


# ===========================================================================
# Regelbasierte Analyse (Fallback ohne KI)
# ===========================================================================
SEVERITY_KEYWORDS = [
    (3, r"zero[- ]?day|0-day|actively exploited|aktiv ausgenutzt|in the wild|mass exploitation"),
    (3, r"invasion|nuclear|nuklear|atomar|genocide|völkermord|massacre|massaker|coup|putsch"),
    (3, r"tsunami|state of emergency|ausnahmezustand|katastrophenfall|blackout|stromausfall|power outage"),
    (2, r"killed|dead|deaths|fatalities|tote[n]?|getötet|todesopfer|casualties"),
    (2, r"missile|rakete[n]?|airstrike|air strike|luftangriff|drone attack|drohnenangriff|shelling|beschuss|bomb|explosion"),
    (2, r"ransomware|wiper|supply[- ]chain attack|critical vulnerability|kritische schwachstelle|remote code execution|rce\b"),
    (2, r"evacuat|evakuier|sabotage|terror|hostage|geisel|martial law|kriegsrecht|mobilis|mobiliz"),
    (2, r"earthquake|erdbeben|hurricane|hurrikan|typhoon|taifun|cyclone|zyklon|flood|hochwasser|überschwemmung|wildfire|waldbrand|eruption|ausbruch"),
    (1, r"attack|angriff|breach|datenleck|data leak|outage|ausfall|störung|disruption|hack|cyberangriff|ddos|exploit|vulnerability|schwachstelle|sanction|sanktion"),
    (1, r"warning|warnung|alert|travel advisory|reisewarnung|clashes|gefechte|protest|unrest|unruhen|strike|streik"),
]
SEVERITY_RES = [(w, re.compile(p, re.IGNORECASE)) for w, p in SEVERITY_KEYWORDS]
CASUALTY_RE = re.compile(r"(\d[\d,.]*)\s+(?:people\s+)?(?:killed|dead|deaths|tote|todesopfer|menschen getötet)", re.IGNORECASE)
CVSS_RE = re.compile(r"CVSS[^0-9]{0,20}(\d{1,2}(?:\.\d)?)", re.IGNORECASE)
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
ACTOR_RE = re.compile(
    r"(?<![\w-])(APT ?\d{1,3}|UNC\d{3,5}|TA\d{3,4}|FIN\d{1,2}|Storm-\d{3,4}|Lazarus|Sandworm|Fancy Bear|Cozy Bear|"
    r"Volt Typhoon|Salt Typhoon|Flax Typhoon|Scattered Spider|LockBit|BlackCat|ALPHV|Cl0p|Clop|Akira|Black Basta|"
    r"Qilin|RansomHub|Medusa|Kimsuky|Turla|Gamaredon|Killnet|NoName057\(16\)|Hamas|Hezbollah|Hisbollah|Houthis?|"
    r"Huthis?|Wagner|Africa Corps|Taliban|ISIS|Islamic State|Islamischer Staat|al-Shabaab|Boko Haram|M23|RSF|NATO|IAEA|IAEO)(?![\w-])"
)
SECTOR_RULES = [
    ("Energie", r"power grid|stromnetz|energy|energie|pipeline|gas supply|gasversorgung|nuclear plant|kraftwerk|substation|umspannwerk|oil|öl\b|lng"),
    ("Gesundheit", r"hospital|krankenhaus|klinik|health|gesundheit|medical|pharma"),
    ("Finanzen", r"\bbank|finan|payment|zahlungs|crypto|krypto"),
    ("Transport", r"airport|flughafen|aviation|luftfahrt|railway|bahn|rail\b|port\b|hafen|shipping|schifffahrt|vessel|container"),
    ("Telekommunikation", r"telecom|telekommunikation|undersea cable|seekabel|submarine cable|mobilfunk|internet outage|isp\b"),
    ("Wasser", r"water supply|wasserversorgung|drinking water|trinkwasser|wastewater|abwasser"),
    ("Behörden", r"government|regierung|ministry|ministerium|agency|behörde|municipal|kommune"),
    ("Industrie/OT", r"\bics\b|\bot\b|scada|plc\b|industrial|industrie|manufactur"),
    ("Lieferkette", r"supply chain|lieferkette|logistics|logistik|semiconductor|halbleiter"),
]
SECTOR_RES = [(name, re.compile(p, re.IGNORECASE)) for name, p in SECTOR_RULES]
CATEGORY_HINTS = [
    ("cyber", re.compile(r"ransomware|malware|cve-\d|hacker|cyberattack|cyber attack|cyberangriff|phishing|ddos|botnet|vulnerability|schwachstelle|exploit|data breach|datenleck", re.IGNORECASE)),
    ("natural", re.compile(r"earthquake|erdbeben|hurricane|hurrikan|typhoon|taifun|cyclone|zyklon|flood|hochwasser|überschwemmung|wildfire|waldbrand|volcan|vulkan|tsunami|drought|dürre|landslide|erdrutsch|heatwave|hitzewelle|storm\b|sturm\b", re.IGNORECASE)),
    ("infrastructure", re.compile(r"blackout|stromausfall|power outage|undersea cable|seekabel|pipeline|supply chain|lieferkette|port closure|hafen|grid|stromnetz|water supply|wasserversorgung", re.IGNORECASE)),
]
RELEVANCE_RE = re.compile(
    r"war\b|krieg|attack|angriff|strike|killed|dead|tote|military|militär|missile|rakete|drone|drohne|troops|truppen|conflict|konflikt|"
    r"sanction|sanktion|nuclear|nuklear|terror|coup|putsch|protest|unrest|unruhen|crisis|krise|emergency|notstand|evacuat|evakuier|"
    r"earthquake|erdbeben|flood|hochwasser|storm|sturm|hurricane|cyclone|wildfire|waldbrand|disaster|katastrophe|outage|ausfall|"
    r"blackout|cyber|hack|ransomware|sabotage|ceasefire|waffenruhe|refugee|flüchtling|famine|hunger|epidemic|epidemie|outbreak|"
    r"shipping|schifffahrt|tanker|blockade|explosion|hostage|geisel|security|sicherheit|warning|warnung|border|grenze",
    re.IGNORECASE,
)


def heuristic_severity(title: str, text: str, category: str) -> int:
    content = f"{title} {title} {text}"
    score = 2 if category in ("cyber", "infrastructure") else 3
    for weight, rx in SEVERITY_RES:
        if rx.search(content):
            score += weight
    for m in CASUALTY_RE.finditer(content):
        n = to_float(m.group(1).replace(",", "").replace(".", "")) or 0
        score += 3 if n >= 100 else 2 if n >= 10 else 0
    cvss = [to_float(c) or 0 for c in CVSS_RE.findall(content)]
    if cvss and max(cvss) >= 9.0:
        score += 2
    return max(1, min(9, score))


def extract_entities(title: str, text: str, country_code: str = "") -> list[str]:
    content = f"{title} {text}"
    ents: list[str] = []
    for cve in CVE_RE.findall(content):
        ents.append(cve.upper())
    for actor in ACTOR_RE.findall(content):
        ents.append(actor)
    for name, rx in SECTOR_RES:
        if rx.search(content):
            ents.append(name)
    if country_code:
        ents.append(country_code)
    return dedupe_list(ents)[:8]


def dedupe_list(values) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = clean_text(str(v))[:48]
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def guess_category(title: str, text: str, default: str) -> str:
    # Akteursnamen wie "Volt Typhoon" dürfen nicht als Wetterereignis zählen
    title, text = ACTOR_RE.sub(" ", title), ACTOR_RE.sub(" ", text)
    content = f"{title} {text}"
    for cat, rx in CATEGORY_HINTS:
        if cat != default and rx.search(title):
            return cat
    for cat, rx in CATEGORY_HINTS:
        if cat == default and rx.search(content):
            return cat
    return default if default in CATEGORIES else "geopolitics"


# ===========================================================================
# Trigger-Erkennung (Krisen-Entscheidungsplan, Katalog in config.TRIGGERS)
# ===========================================================================
def _wordstart(pattern: str) -> re.Pattern:
    # Muster nur an Wortanfängen erlauben ("riga" soll nicht in "Brigade" treffen)
    return re.compile(r"(?<![a-zäöüß0-9])(?:" + pattern + ")", re.IGNORECASE)


TRIGGER_DEFS = {t["id"]: t for t in config.TRIGGERS}
TRIGGER_RULES = [(t["id"], [_wordstart(p) for p in t.get("match", [])],
                  _wordstart(t["exclude"]) if t.get("exclude") else None) for t in config.TRIGGERS]


def detect_triggers(title: str, text: str) -> list[str]:
    content = f"{title} {text}"
    hits = []
    for tid, patterns, exclude in TRIGGER_RULES:
        if patterns and all(p.search(content) for p in patterns) and not (exclude and exclude.search(content)):
            hits.append(tid)
    return hits


def clean_triggers(values) -> list[str]:
    if not isinstance(values, list):
        values = [values] if values else []
    out = []
    for v in values:
        tid = str(v).strip().upper()[:3]
        if tid in TRIGGER_DEFS and tid not in out:
            out.append(tid)
    return sorted(out)


def analyze_heuristic(item: dict) -> dict | None:
    title, text = item["title"], item["text"]
    if item.get("filter") and not RELEVANCE_RE.search(f"{title} {text}"):
        return None
    category = guess_category(title, text, item["feed_category"])
    geo = None
    if item.get("lat") is not None:
        geo = {"location_name": item.get("location_hint") or "", "country_code": "",
               "latitude": item["lat"], "longitude": item["lon"]}
    geo = geo or geolocate(title, text) or {"location_name": "Global / nicht verortet", "country_code": "",
                                            "latitude": None, "longitude": None}
    summary = two_sentences(text) or two_sentences(title)
    return build_threat(item, {
        "title": title,
        "category": category,
        "severity_score": heuristic_severity(title, text, category),
        "impact_summary": summary,
        "entities": extract_entities(title, text, geo.get("country_code", "")),
        "triggers": detect_triggers(title, text),
        **geo,
    }, "heuristic")


def build_threat(item: dict, fields: dict, analysis: str) -> dict:
    """Normalisiert und validiert einen Datensatz für threats.json."""
    category = str(fields.get("category", "")).lower().strip()
    if category not in CATEGORIES:
        category = item.get("feed_category") if item.get("feed_category") in CATEGORIES else "geopolitics"
    try:
        severity = int(round(float(fields.get("severity_score", 3))))
    except (TypeError, ValueError):
        severity = 3
    lat, lon = valid_coords(fields.get("latitude"), fields.get("longitude"))
    cc = str(fields.get("country_code") or "").upper().strip()[:2]
    cc = cc if re.fullmatch(r"[A-Z]{2}", cc) else ""
    location = clean_text(str(fields.get("location_name") or ""), 120)
    if lat is None and cc in GAZ_ISO:
        _, _, cname, lat, lon = GAZ_ISO[cc]
        location = location or cname
    if lat is None and location and location.lower() not in ("global", "unbekannt", "unknown"):
        geo = geolocate(location)
        if geo:
            lat, lon = geo["latitude"], geo["longitude"]
            cc = cc or geo["country_code"]
    if lat is None and analysis == "ai" and category != "cyber":
        geo = geolocate(item["title"])  # KI hat nicht verortet → Titel als Rückfallebene
        if geo:
            lat, lon, location, cc = geo["latitude"], geo["longitude"], geo["location_name"], cc or geo["country_code"]
    entities = fields.get("entities") or []
    if not isinstance(entities, list):
        entities = [entities]
    triggers = clean_triggers(fields.get("triggers"))
    if any(TRIGGER_DEFS[t]["list"] == "A" for t in triggers):
        severity = max(severity, 8)
    return {
        "id": item["id"],
        "title": clean_text(str(fields.get("title") or item["title"]), 220) or item["title"],
        "source_title": item["title"],
        "category": category,
        "severity_score": max(1, min(10, severity)),
        "location_name": location or ("Global / nicht verortet" if lat is None else ""),
        "country_code": cc,
        "latitude": lat,
        "longitude": lon,
        "impact_summary": two_sentences(str(fields.get("impact_summary") or "")) or two_sentences(item["text"]),
        "entities": dedupe_list(entities)[:10],
        "triggers": triggers,
        "source_url": safe_url(item.get("link")),
        "source_name": item["feed_name"],
        "timestamp": item["published"],
        "fetched_at": iso(now_utc()),
        "analysis": analysis,
        "_excerpt": item["text"][:900] if analysis == "heuristic" else "",
        "_feed_category": item.get("feed_category", ""),
    }


# ===========================================================================
# Quellen-Adapter
# ===========================================================================
def entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def entry_coords(entry) -> tuple[float | None, float | None]:
    point = entry.get("georss_point")
    if isinstance(point, str):
        parts = point.replace(",", " ").split()
        if len(parts) >= 2:
            return valid_coords(parts[0], parts[1])
    where = entry.get("where")
    if isinstance(where, dict) and isinstance(where.get("coordinates"), (list, tuple)):
        coords = where["coordinates"]
        if len(coords) >= 2 and not isinstance(coords[0], (list, tuple)):
            return valid_coords(coords[1], coords[0])  # GeoJSON-Reihenfolge lon, lat
    lat = entry.get("geo_lat")
    lon = entry.get("geo_long") or entry.get("geo_lon")
    return valid_coords(lat, lon)


def base_item(feed: dict, uid: str, title: str, link: str, text: str, published: datetime | None) -> dict:
    return {
        "id": make_id(uid or link or f"{feed['name']}|{title}"),
        "title": clean_text(title, 300),
        "link": safe_url(link),
        "text": clean_text(text, 1500),
        "published": iso(published or now_utc()),
        "feed_name": feed["name"],
        "feed_category": feed.get("category", "geopolitics"),
        "filter": bool(feed.get("filter")),
        "lat": None,
        "lon": None,
    }


def parse_rss(feed: dict) -> list[tuple[dict, dict]]:
    parsed = feedparser.parse(http_get(feed["url"]).content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Feed nicht lesbar: {parsed.get('bozo_exception')}")
    out = []
    for e in parsed.entries:
        text = e.get("summary") or ""
        if not text and e.get("content"):
            text = e["content"][0].get("value", "")
        item = base_item(feed, e.get("id") or e.get("guid") or "", e.get("title", ""), e.get("link", ""),
                         text, entry_datetime(e))
        if not item["title"]:
            continue
        item["lat"], item["lon"] = entry_coords(e)
        out.append((item, e))
    return out


def fetch_rss(feed: dict) -> list[dict]:
    return [item for item, _ in parse_rss(feed)]


def fetch_usgs(feed: dict) -> list[dict]:
    data = http_get(feed["url"]).json()
    items = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        mag = to_float(p.get("mag"))
        if mag is None or mag < config.USGS_MIN_MAGNITUDE:
            continue
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        lat, lon = valid_coords(coords[1], coords[0])
        depth = to_float(coords[2] if len(coords) > 2 else None)
        published = datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc) if p.get("time") else None
        place = p.get("place") or "unbekannte Region"
        item = base_item(feed, f.get("id", ""), p.get("title") or f"M {mag} - {place}", p.get("url", ""), place, published)
        alert = (p.get("alert") or "").lower()
        tsunami = bool(p.get("tsunami"))
        sev = 2 if mag < 5.0 else 3 if mag < 5.5 else 4 if mag < 6.0 else 5 if mag < 6.5 else 6 if mag < 7.0 else 8 if mag < 7.5 else 9
        sev = max(sev, {"yellow": 6, "orange": 8, "red": 10}.get(alert, 0)) + (1 if tsunami else 0)
        alert_de = {"green": "grün", "yellow": "gelb", "orange": "orange", "red": "rot"}.get(alert, "noch keine")
        felt = int(p.get("felt") or 0)
        geo = geolocate(place) or {}
        depth_txt = f" in {depth:.0f} km Tiefe" if depth is not None else ""
        summary = (f"Erdbeben der Stärke {mag:.1f}{depth_txt}, {place}. "
                   f"USGS-PAGER-Schadensprognose: {alert_de}; Tsunami-Hinweis: {'ja' if tsunami else 'nein'}"
                   f"{f'; {felt} Meldungen spürbarer Erschütterungen' if felt else ''}.")
        ents = [f"M{mag:.1f}", "Erdbeben"] + (["Tsunami"] if tsunami else []) + ([f"PAGER {alert}"] if alert else [])
        ents += [geo["country_code"]] if geo.get("country_code") else []
        item["threat"] = build_threat(item, {
            "title": f"Erdbeben M{mag:.1f} – {place}", "category": "natural", "severity_score": min(10, sev),
            "location_name": place, "country_code": geo.get("country_code", ""), "latitude": lat, "longitude": lon,
            "impact_summary": summary, "entities": ents}, "structured")
        items.append(item)
    return items


GDACS_TYPES = {"EQ": "Erdbeben", "TC": "Tropischer Wirbelsturm", "FL": "Überschwemmung", "VO": "Vulkanausbruch",
               "DR": "Dürre", "WF": "Waldbrand", "TS": "Tsunami"}
ALERT_RANK = {"green": 1, "orange": 2, "red": 3}


def fetch_gdacs(feed: dict) -> list[dict]:
    min_rank = ALERT_RANK.get(config.GDACS_MIN_ALERT.lower(), 1)
    out = []
    for item, e in parse_rss(feed):
        level = str(e.get("gdacs_alertlevel") or "").strip().lower()
        if not level:
            m = re.match(r"\s*(green|orange|red)", item["title"], re.IGNORECASE)
            level = m.group(1).lower() if m else "green"
        etype = str(e.get("gdacs_eventtype") or "").strip().upper()
        if ALERT_RANK.get(level, 1) < min_rank:
            continue
        if config.GDACS_SKIP_GREEN_EARTHQUAKES and level == "green" and etype == "EQ":
            continue
        country = clean_text(str(e.get("gdacs_country") or ""))
        sev = {"green": 3, "orange": 7, "red": 9}.get(level, 3)
        geo = geolocate(country or item["title"]) or {}
        lat, lon = item["lat"], item["lon"]
        if lat is None:
            lat, lon = geo.get("latitude"), geo.get("longitude")
        type_de = GDACS_TYPES.get(etype, "Naturereignis")
        level_de = {"green": "Grün", "orange": "Orange", "red": "Rot"}.get(level, level)
        detail = two_sentences(item["text"]).split(". ")[0].rstrip(".") if item["text"] else item["title"]
        place = geo.get("location_name") or country
        summary = (f"GDACS meldet {type_de} mit Alarmstufe {level_de}"
                   f"{' in ' + place if place else ''}. {detail}.")
        ents = [type_de, f"GDACS {level_de}"] + ([geo["country_code"]] if geo.get("country_code") else [])
        item["threat"] = build_threat(item, {
            "title": item["title"], "category": "natural", "severity_score": sev,
            "location_name": place, "country_code": geo.get("country_code", ""),
            "latitude": lat, "longitude": lon, "impact_summary": summary, "entities": ents}, "structured")
        out.append(item)
    return out


def fetch_aa(feed: dict) -> list[dict]:
    """Auswärtiges Amt Open Data: aktuelle Reise- und Teilreisewarnungen."""
    data = http_get(feed["url"]).json()
    payload = data.get("response", data)
    cutoff = now_utc() - timedelta(days=config.RETENTION_DAYS)
    items = []
    for key, c in payload.items():
        if not isinstance(c, dict) or not c.get("countryCode"):
            continue
        flags = [("warning", "eine Reisewarnung", 8), ("partialWarning", "eine Teilreisewarnung", 6),
                 ("situationWarning", "einen Sicherheitshinweis zur Lage", 6),
                 ("situationPartWarning", "einen regionalen Sicherheitshinweis", 5)]
        active = [(label, sev) for flag, label, sev in flags if c.get(flag)]
        cc = str(c.get("countryCode", "")).upper()
        watched = cc in config.AA_WATCH_COUNTRIES
        if not active and not watched:
            continue
        ts = to_float(c.get("lastModified")) or 0
        published = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc) if ts else now_utc()
        if published < cutoff:
            continue
        name = c.get("countryName") or GAZ_ISO.get(cc, ("", "", cc))[2]
        title = c.get("title") or f"{name}: Reise- und Sicherheitshinweise"
        link = f"https://www.auswaertiges-amt.de/opendata/travelwarning/{key}"
        item = base_item(feed, f"aa-{key}-{int(ts)}", title, link, title, published)
        geo = GAZ_ISO.get(cc)
        date_de = published.strftime("%d.%m.%Y")
        label, sev = active[0] if active else ("keine Reisewarnung", 2)
        summary = (f"Das Auswärtige Amt führt für {name} aktuell {label}. "
                   f"Die Reise- und Sicherheitshinweise wurden am {date_de} aktualisiert.")
        triggers, ents = [], [cc, "Auswärtiges Amt"] + (["Reisewarnung"] if active else [])
        if watched:
            # Beobachtetes Nachbarland: Volltext auf Ausreiseaufruf prüfen (Trigger A8)
            content = ""
            try:
                detail = http_get(f"{feed['url']}/{key}").json()
                node = detail.get("response", detail)
                node = node.get(key, node) if isinstance(node, dict) else {}
                content = clean_text(str(node.get("content", "")))
            except (requests.RequestException, ValueError, AttributeError) as exc:
                log.debug("AA-Details %s: %s", cc, exc)
            if AA_DEPARTURE_RE.search(content):
                triggers, sev = ["A8"], 9
                summary = (f"Das Auswärtige Amt fordert Deutsche zur Ausreise aus {name} auf (Stand {date_de}). "
                           f"Trigger A8 des Krisenplans prüfen: gilt erst bei Aufrufen für mehrere Nachbarstaaten.")
            else:
                triggers = ["D3"] if active else []
                summary = (f"Das Auswärtige Amt hat die Reise- und Sicherheitshinweise für {name} am {date_de} "
                           f"aktualisiert. Aktueller Status: {label}; kein Ausreiseaufruf im Text erkannt.")
            ents.append("Nachbarstaat")
        item["threat"] = build_threat(item, {
            "title": f"Auswärtiges Amt: {title}", "category": "geopolitics", "severity_score": sev,
            "location_name": name, "country_code": cc,
            "latitude": geo[3] if geo else None, "longitude": geo[4] if geo else None,
            "impact_summary": summary, "entities": ents, "triggers": triggers}, "structured")
        items.append(item)
    return items


AA_DEPARTURE_RE = re.compile(
    r"(aufgefordert|dringend gebeten|wird dringend geraten|dringend empfohlen).{0,120}(auszureisen|ausreisen|zu verlassen|ausreise)|"
    r"ausreiseaufforderung|zur ausreise aufgefordert|(sofort|umgehend|unverzüglich).{0,40}(auszureisen|zu verlassen)",
    re.IGNORECASE)


NINA_SEVERITY = {"extreme": 9, "severe": 7, "moderate": 5, "minor": 3}
NINA_NATURAL = {"met", "geo", "env"}


def _geojson_centroid(geo: dict) -> tuple[float | None, float | None]:
    pts: list[tuple[float, float]] = []

    def walk(c):
        if isinstance(c, (list, tuple)):
            if len(c) >= 2 and all(isinstance(v, (int, float)) for v in c[:2]):
                pts.append((c[1], c[0]))
            else:
                for sub in c:
                    walk(sub)
    for feat in geo.get("features", []) if isinstance(geo, dict) else []:
        walk((feat.get("geometry") or {}).get("coordinates"))
    if not pts:
        return None, None
    return valid_coords(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def fetch_nina(feed: dict) -> list[dict]:
    """BBK-Warn-API (NINA): MoWaS, KATWARN, BIWAPP."""
    overview = http_get(feed["url"]).json()
    items = []
    for w in (overview or [])[: config.NINA_MAX_WARNINGS]:
        wid = w.get("id")
        if not wid:
            continue
        title = (w.get("i18nTitle") or {}).get("de") or w.get("title") or "Warnmeldung"
        if re.search(r"\btest", title, re.IGNORECASE):
            continue
        published = parse_iso(w.get("startDate")) or now_utc()
        sev = NINA_SEVERITY.get(str(w.get("severity", "")).lower(), 4)
        desc, area, cap_cat, instruction = "", "", "", ""
        try:
            detail = http_get(f"https://warnung.bund.de/api31/warnings/{wid}.json").json()
            info = next((i for i in detail.get("info", []) if str(i.get("language", "")).startswith("de")),
                        (detail.get("info") or [{}])[0])
            title = info.get("headline") or title
            desc = info.get("description") or ""
            instruction = info.get("instruction") or ""
            area = ", ".join(a.get("areaDesc", "") for a in info.get("area", [])[:3] if a.get("areaDesc"))
            cats = info.get("category") or []
            cap_cat = str(cats[0] if isinstance(cats, list) and cats else cats).lower()
            sev = NINA_SEVERITY.get(str(info.get("severity", "")).lower(), sev)
            if str(detail.get("msgType", "")).lower() == "cancel":
                continue
        except (requests.RequestException, ValueError) as exc:
            log.debug("NINA-Details %s: %s", wid, exc)
        lat, lon = None, None
        try:
            lat, lon = _geojson_centroid(http_get(f"https://warnung.bund.de/api31/warnings/{wid}.geojson").json())
        except (requests.RequestException, ValueError):
            pass
        if lat is None:
            lat, lon = 51.17, 10.45
        item = base_item(feed, f"nina-{wid}", title, f"https://warnung.bund.de/meldungen/{wid}/", desc or title, published)
        # Beschreibung beginnt oft mit der Überschrift → abschneiden
        body = desc[len(title):].lstrip(" .:-–") if desc.startswith(title) else desc
        sents = [x for x in SENT_RE.split(two_sentences(body)) if x] if body else []
        if instruction:
            sents.append(two_sentences(instruction).split(". ")[0].rstrip(".") + ".")
        summary = " ".join(sents[:2]) or f"{title}{' – ' + area if area else ''}. Details in der Originalmeldung."
        item["threat"] = build_threat(item, {
            "title": title, "category": "natural" if cap_cat in NINA_NATURAL else "infrastructure",
            "severity_score": sev, "location_name": f"{area or 'Deutschland'}"[:120], "country_code": "DE",
            "latitude": lat, "longitude": lon, "impact_summary": summary,
            "entities": ["DE", "Bevölkerungsschutz", feed["name"].replace("NINA ", "")] + extract_entities(title, desc)[:4]},
            "structured")
        items.append(item)
    return items


ADAPTERS = {"rss": fetch_rss, "usgs": fetch_usgs, "gdacs": fetch_gdacs, "aa": fetch_aa, "nina": fetch_nina}


def fetch_feed(feed: dict) -> tuple[dict, list[dict], str]:
    adapter = ADAPTERS.get(feed.get("type", "rss"), fetch_rss)
    try:
        items = adapter(feed)
        items.sort(key=lambda i: i["published"], reverse=True)
        return feed, items, ""
    except Exception as exc:  # eine defekte Quelle darf den Lauf nicht stoppen
        msg = str(exc)
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            msg = f"HTTP {exc.response.status_code}"
        elif isinstance(exc, requests.RequestException):
            msg = "nicht erreichbar (Netzwerk/Proxy/Timeout)"
        return feed, [], f"{type(exc).__name__}: {msg}"[:160]


# ===========================================================================
# KI-Analyse
# ===========================================================================
SYSTEM_PROMPT = """Du bist Senior-Analyst in einem All-Hazard-Lagezentrum (Cyber, Geopolitik, Naturkatastrophen, \
Kritische Infrastruktur/Lieferketten, hybride Bedrohungen). Du bewertest Meldungen nüchtern, faktenbasiert und \
ausschließlich auf Grundlage des gelieferten Textes. Du antwortest nur mit gültigem JSON."""

USER_PROMPT = """Analysiere die folgenden Meldungen. Gib für JEDE Meldung genau ein Objekt zurück.

Antwortformat (exakt dieses JSON-Objekt, keine Erklärungen, kein Markdown):
{{"items": [{{
  "id": "<id aus der Eingabe>",
  "relevant": true,
  "title": "<prägnante Schlagzeile auf {lang}, max. 110 Zeichen, nur Fakten>",
  "category": "cyber|geopolitics|natural|infrastructure",
  "severity_score": 1,
  "location_name": "<Stadt, Land> oder <Land> oder <Region>; 'Global' wenn nicht verortbar",
  "country_code": "<ISO-3166-1 Alpha-2 des Hauptbetroffenen, sonst leer>",
  "latitude": 0.0,
  "longitude": 0.0,
  "impact_summary": "<GENAU 2 Sätze auf {lang}>",
  "entities": ["..."],
  "triggers": []
}}]}}

Regeln:
- relevant=false für Sport, Kultur, Promis, Wirtschaftsnachrichten ohne Krisenbezug, Meinungsbeiträge ohne konkretes \
Ereignis, Produktwerbung, Ratgeber/Tutorials, Routine-Innenpolitik. Bei relevant=false genügen id und relevant.
- category: cyber = Angriffe, Schwachstellen, Malware, Datenlecks. geopolitics = Kriege, Konflikte, Terror, Sanktionen, \
Reisewarnungen, politische Instabilität. natural = Erdbeben, Unwetter, Fluten, Brände, Vulkane, Dürre, Epidemien. \
infrastructure = Strom-/Wasser-/Telekom-/Verkehrsausfälle, Sabotage an KRITIS, Lieferketten, Schifffahrt, Bevölkerungsschutz. \
Hybride Bedrohungen (Sabotage, Drohnen über KRITIS, Desinformation) → infrastructure bzw. geopolitics und Tag "Hybrid".
- severity_score (Ganzzahl 1–10):
  9–10 katastrophal: Massenopfer (≥100 Tote), zwischenstaatliche Kriegseskalation, landesweiter KRITIS-Ausfall, \
massenhaft ausgenutzte Zero-Day in weit verbreiteter Software, Erdbeben ≥M7.5 in besiedeltem Gebiet.
  7–8 kritisch: zweistellige Opferzahlen, größere Militärschläge, aktiv ausgenutzte kritische Schwachstelle (CVSS ≥9, CISA KEV), \
Ransomware bei KRITIS-Betreibern, regionale Strom-/Kommunikationsausfälle, neue Reisewarnung, Unwetter mit Evakuierungen.
  5–6 hoch: einzelne Todesopfer, Kampfhandlungen ohne neue Qualität, kritische Schwachstelle ohne bekannte Ausnutzung, \
Datenleck bei großem Unternehmen, lokale Ausfälle, Sanktionen mit spürbaren Folgen.
  3–4 moderat: Warnungen, Spannungen, Patches, kleinere Vorfälle ohne Opfer.
  1–2 Info: Hintergrund, Analysen, Berichte ohne akutes Ereignis.
- latitude/longitude: Dezimalgrad des Ereignisorts (Stadt > Region > Landesmitte). null, wenn global oder unbekannt. \
Bei Cyber-Vorfällen: Sitz des Hauptbetroffenen, sonst null.
- impact_summary: Satz 1 = was ist passiert und die unmittelbare Folge. Satz 2 = wer/was ist betroffen bzw. welche \
konkreten Auswirkungen sind zu erwarten. Keine Spekulation über den Quelltext hinaus.
- entities: 3–8 Tags: Akteure (Staaten, Gruppen, APTs, Unternehmen), ISO-Ländercodes, CVE-IDs, Malware, Produkte, \
betroffene Sektoren (z. B. Energie, Gesundheit, Finanzen, Transport, Telekommunikation, Behörden).
- triggers: IDs aus dem Trigger-Katalog unten, aber NUR wenn die Meldung das Ereignis als tatsächlich eingetreten berichtet. Ausdrücklich KEINE Trigger: Politikerzitate und Interviews, Forderungen, Spekulationen, Übungen und Manöver, Rüstungsplanung, Wehrdienst- und Wehrpflichtdebatten, Umfragen, Social-Media-Wellen, historische Rückblicke. Einzelne Sabotageakte dürfen B1 erhalten (die Häufung wird separat gezählt). Im Zweifel leere Liste.
  Bei einem A-Trigger: severity_score mindestens 8.

Trigger-Katalog:
{triggers}

Meldungen:
{items}"""


TRIGGER_PROMPT = "\n".join(f"  {t['id']} (Liste {t['list']}): {t['ai']}" for t in config.TRIGGERS)


class AIUnavailable(Exception):
    """KI derzeit nicht nutzbar (Kontingent, Auth, Netz) – Rest des Laufs ohne KI."""


class AIClient:
    def __init__(self, provider: str, usage_root: dict):
        self.provider = provider
        self.usage = usage_root.setdefault(provider, {})
        self.calls_this_run = 0
        self.last_call = 0.0
        self.models = list(config.GEMINI_MODELS if provider == "gemini" else config.GROQ_MODELS)
        self.key = config.GEMINI_API_KEY if provider == "gemini" else config.GROQ_API_KEY
        self.thinking = config.GEMINI_THINKING_BUDGET
        self.interval = config.AI_MIN_SECONDS_BETWEEN_CALLS.get(provider, 10.0)

    def budget_left(self) -> bool:
        today = now_utc().strftime("%Y-%m-%d")
        if self.usage.get("date") != today:
            self.usage.clear()
            self.usage.update({"date": today, "calls": 0})
        return (self.calls_this_run < config.AI_MAX_CALLS_PER_RUN
                and self.usage.get("calls", 0) < config.AI_MAX_CALLS_PER_DAY)

    def analyze(self, batch: list[dict]) -> dict[str, dict]:
        payload = [{"id": str(i), "source": it["feed_name"], "source_category": it["feed_category"],
                    "published": it["published"], "title": it["title"], "text": it["text"][:1200]}
                   for i, it in enumerate(batch)]
        prompt = USER_PROMPT.format(lang=config.OUTPUT_LANGUAGE, triggers=TRIGGER_PROMPT,
                                    items=json.dumps(payload, ensure_ascii=False, indent=1))
        wait = self.interval - (time.time() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        raw = self._request(prompt)
        self.last_call = time.time()
        self.calls_this_run += 1
        self.usage["calls"] = self.usage.get("calls", 0) + 1
        results = self._parse(raw)
        return {batch[int(r["id"])]["id"]: r for r in results
                if str(r.get("id", "")).isdigit() and int(r["id"]) < len(batch)}

    @staticmethod
    def _parse(raw: str) -> list[dict]:
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
            if not m:
                raise ValueError("KI-Antwort enthält kein JSON")
            data = json.loads(m.group(0))
        if isinstance(data, dict):
            data = data.get("items") or data.get("results") or data.get("threats") or []
        return [d for d in data if isinstance(d, dict)]

    def _request(self, prompt: str) -> str:
        last_error = "unbekannt"
        while self.models:
            model = self.models[0]
            for attempt in range(3):
                try:
                    if self.provider == "gemini":
                        resp = self._gemini(model, prompt)
                    else:
                        resp = self._groq(model, prompt)
                except requests.RequestException as exc:
                    last_error = str(exc)
                    time.sleep(2 ** attempt * 3)
                    continue
                status = resp.status_code
                if status == 200:
                    return self._extract(resp.json())
                body = resp.text[:300]
                last_error = f"HTTP {status}: {body}"
                if status == 400 and self.provider == "gemini" and self.thinking is not None and "thinking" in body.lower():
                    self.thinking = None  # Modell unterstützt thinkingConfig nicht
                    continue
                if status == 404 or (status == 400 and "model" in body.lower() and "not" in body.lower()):
                    log.warning("Modell %s nicht verfügbar, nächstes Modell …", model)
                    break
                if status in (401, 403):
                    raise AIUnavailable(f"API-Key ungültig oder gesperrt ({status})")
                if status == 429:
                    if "per day" in body.lower() or "PerDay" in body:
                        raise AIUnavailable("Tageskontingent erschöpft (429)")
                    retry = to_float(resp.headers.get("Retry-After")) or 20 * (attempt + 1)
                    log.info("Rate-Limit erreicht, warte %.0f s …", min(retry, 60))
                    time.sleep(min(retry, 60))
                    continue
                if status >= 500:
                    if attempt >= 1:  # überlastet → nächstes Modell statt endlos warten
                        log.warning("Modell %s überlastet (HTTP %d), nächstes Modell …", model, status)
                        break
                    time.sleep(8)
                    continue
                raise AIUnavailable(last_error)
            else:
                log.warning("Modell %s: %s", model, last_error[:120])
            self.models.pop(0)
        raise AIUnavailable(f"Kein Modell verfügbar ({last_error})")

    @property
    def model(self) -> str:
        return self.models[0] if self.models else ""

    def _gemini(self, model: str, prompt: str) -> requests.Response:
        gen_cfg: dict = {"temperature": 0.2, "responseMimeType": "application/json", "maxOutputTokens": 8192}
        if self.thinking is not None:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": self.thinking}
        body = {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": gen_cfg}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        return requests.post(url, json=body, timeout=config.AI_REQUEST_TIMEOUT,
                             headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})

    def _groq(self, model: str, prompt: str) -> requests.Response:
        body = {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]}
        return requests.post("https://api.groq.com/openai/v1/chat/completions", json=body,
                             timeout=config.AI_REQUEST_TIMEOUT, headers={"Authorization": f"Bearer {self.key}"})

    def _extract(self, data: dict) -> str:
        if self.provider == "gemini":
            cands = data.get("candidates") or []
            if not cands:
                raise ValueError(f"Leere Gemini-Antwort: {str(data.get('promptFeedback', ''))[:200]}")
            parts = (cands[0].get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return data["choices"][0]["message"]["content"]


def _has_key(provider: str) -> bool:
    key = config.GEMINI_API_KEY if provider == "gemini" else config.GROQ_API_KEY
    return bool(key) and key.strip() not in ("", "DEIN_KEY_HIER")


class AIPool:
    """Kette von KI-Anbietern: fällt einer aus, übernimmt der nächste mit gültigem Key."""

    def __init__(self, usage_root: dict, status: dict, disabled: bool = False):
        if "date" in usage_root:  # altes Format (ein Zähler für alles)
            usage_root.clear()
        providers = [] if disabled else [p.lower() for p in getattr(config, "AI_PROVIDERS", [getattr(config, "AI_PROVIDER", "gemini")])]
        self.clients = [AIClient(p, usage_root) for p in providers if p in ("gemini", "groq") and _has_key(p)]
        self.status = status
        status.update({"configured": [c.provider for c in self.clients], "run_calls": 0, "run_items": 0})
        if not self.clients and not disabled:
            log.warning("Kein gültiger KI-API-Key gesetzt – regelbasierte Analyse aktiv.")
            status.update({"active": False, "last_error": "Kein API-Key hinterlegt"})
        elif disabled:
            status.update({"active": False, "last_error": "KI per --no-ai deaktiviert"})

    def __bool__(self) -> bool:
        return bool(self.clients)

    @property
    def label(self) -> str:
        return self.clients[0].provider if self.clients else "none"

    def budget_left(self) -> bool:
        return bool(self.clients) and self.clients[0].budget_left()

    def analyze(self, batch: list[dict]) -> dict[str, dict]:
        while self.clients:
            client = self.clients[0]
            try:
                res = client.analyze(batch)
                self.status.update({"active": True, "provider": client.provider, "model": client.model,
                                    "last_success": iso(now_utc()), "last_error": ""})
                self.status["run_calls"] += 1
                self.status["run_items"] += len(res)
                return res
            except AIUnavailable as exc:
                log.warning("KI %s nicht verfügbar: %s", client.provider, exc)
                self.status.update({"active": False, "last_error": f"{client.provider}: {str(exc)[:160]}",
                                    "last_error_at": iso(now_utc())})
                self.clients.pop(0)
        raise AIUnavailable(self.status.get("last_error") or "keine KI verfügbar")


# ===========================================================================
# Persistenz
# ===========================================================================
def load_db() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            db = json.load(fh)
        if isinstance(db, dict) and isinstance(db.get("threats"), list):
            db.setdefault("seen_ids", {})
            db.setdefault("ai_usage", {})
            db.setdefault("ai_status", {})
            return db
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("%s nicht lesbar (%s) – starte neu.", config.OUTPUT_FILE, exc)
    return {"threats": [], "seen_ids": {}, "ai_usage": {}, "ai_status": {}}


def save_db(db: dict, feeds_status: list[dict], provider: str) -> None:
    cutoff = now_utc() - timedelta(days=config.RETENTION_DAYS)
    trig_cutoff = now_utc() - timedelta(days=config.TRIGGER_RETENTION_DAYS)

    def keep(t: dict) -> bool:
        ts = parse_iso(t.get("timestamp")) or now_utc()
        return ts >= (trig_cutoff if t.get("triggers") else cutoff)
    threats = [t for t in db["threats"] if keep(t)]
    threats.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
    # Trigger-Treffer haben Vorrang vor dem Mengenlimit
    flagged = [t for t in threats if t.get("triggers")]
    others = [t for t in threats if not t.get("triggers")][: max(0, config.MAX_STORED_THREATS - len(flagged))]
    threats = sorted(flagged + others, key=lambda t: t.get("timestamp", ""), reverse=True)
    seen = {k: v for k, v in db["seen_ids"].items() if (parse_iso(v) or now_utc()) >= trig_cutoff}
    counts = {c: sum(1 for t in threats if t["category"] == c) for c in CATEGORIES}
    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso(now_utc()),
        "ai_provider": provider,
        "ai_status": db.get("ai_status", {}),
        "triggers": [{"id": t["id"], "list": t["list"], "label": t["label"]} for t in config.TRIGGERS],
        "poll_interval_minutes": config.POLL_INTERVAL_MINUTES,
        "stats": {"total": len(threats), "by_category": counts,
                  "critical": sum(1 for t in threats if t["severity_score"] >= 8),
                  "high": sum(1 for t in threats if 5 <= t["severity_score"] <= 7)},
        "feeds": feeds_status,
        "threats": threats,
        "seen_ids": seen,
        "ai_usage": db.get("ai_usage", {}),
    }
    db["threats"], db["seen_ids"] = threats, seen
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA_FILE)  # atomar: das Frontend liest nie eine halbe Datei


# ===========================================================================
# Pipeline
# ===========================================================================
def run_once(use_ai: bool = True) -> None:
    started = time.time()
    db = load_db()
    known = {t["id"] for t in db["threats"]} | set(db["seen_ids"])
    known_titles = {norm_title(t.get("source_title") or t["title"]) for t in db["threats"]}
    ai = AIPool(db["ai_usage"], db["ai_status"], disabled=not use_ai)
    provider = ai.label

    log.info("Rufe %d Quellen ab …", len(config.FEEDS))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_feed, config.FEEDS))

    max_age = now_utc() - timedelta(hours=config.MAX_ENTRY_AGE_HOURS)
    feeds_status, structured, pending = [], [], []
    for feed, items, error in results:
        fresh = [i for i in items if i["id"] not in known and norm_title(i["title"]) not in known_titles
                 and (parse_iso(i["published"]) or now_utc()) >= max_age][: config.MAX_ITEMS_PER_FEED]
        for i in fresh:
            known_titles.add(norm_title(i["title"]))
        feeds_status.append({"name": feed["name"], "category": feed.get("category"), "ok": not error,
                             "items": len(items), "new": len(fresh), "error": error})
        if error:
            log.warning("  ✗ %-34s %s", feed["name"], error)
        else:
            log.info("  ✓ %-34s %3d Einträge, %2d neu", feed["name"], len(items), len(fresh))
        for i in fresh:
            (structured if "threat" in i else pending).append(i)

    stamp = iso(now_utc())
    for i in structured:
        db["threats"].append(i["threat"])
        db["seen_ids"][i["id"]] = stamp
    if structured:
        save_db(db, feeds_status, provider)

    # Trigger-Kandidaten und wichtigste Meldungen zuerst an die KI
    def priority(i: dict) -> tuple:
        trig = detect_triggers(i["title"], i["text"])
        return (any(t.startswith("A") for t in trig), bool(trig),
                heuristic_severity(i["title"], i["text"], i["feed_category"]))
    pending.sort(key=priority, reverse=True)
    added = dropped = deferred = 0
    queue = list(pending)
    while queue:
        batch, queue = queue[: config.AI_BATCH_SIZE], queue[config.AI_BATCH_SIZE:]
        results_ai: dict[str, dict] = {}
        if ai and ai.budget_left():
            try:
                results_ai = ai.analyze(batch)
                log.info("KI-Analyse: %d/%d Einträge (%s/%s)", len(results_ai), len(batch),
                         ai.status.get("provider"), ai.status.get("model"))
            except AIUnavailable:
                log.warning("Keine KI verfügbar – Rest dieses Laufs regelbasiert.")
            except (ValueError, KeyError, requests.RequestException) as exc:
                log.warning("KI-Antwort unbrauchbar (%s) – Batch regelbasiert.", exc)
        for item in batch:
            res = results_ai.get(item["id"])
            if res is not None:
                if res.get("relevant") is False:
                    dropped += 1
                    db["seen_ids"][item["id"]] = stamp
                    continue
                threat = build_threat(item, res, "ai")
            elif config.AI_FALLBACK_HEURISTIC or provider == "none":
                threat = analyze_heuristic(item)
                if threat is None:
                    dropped += 1
                    db["seen_ids"][item["id"]] = stamp
                    continue
            else:
                deferred += 1  # nicht als gesehen markieren → nächster Lauf
                continue
            db["threats"].append(threat)
            db["seen_ids"][item["id"]] = stamp
            added += 1
        save_db(db, feeds_status, provider)

    upgraded = upgrade_heuristic(db, ai, feeds_status, provider) if ai else 0
    save_db(db, feeds_status, provider)
    log.info("Fertig in %.0f s: %d strukturiert, %d analysiert, %d verworfen, %d zurückgestellt, %d nachveredelt. "
             "Bestand: %d Lagemeldungen.", time.time() - started, len(structured), added, dropped, deferred,
             upgraded, len(db["threats"]))


def upgrade_heuristic(db: dict, ai: AIPool, feeds_status: list[dict], provider: str) -> int:
    """Verbleibendes KI-Kontingent nutzen, um regelbasierte Einträge der letzten 48 h nachzuveredeln."""
    cutoff = now_utc() - timedelta(hours=48)
    candidates = [t for t in db["threats"] if t.get("analysis") == "heuristic" and t.get("_excerpt")
                  and (parse_iso(t.get("timestamp")) or now_utc()) >= cutoff]
    candidates.sort(key=lambda t: (bool(t.get("triggers")), t["severity_score"]), reverse=True)
    upgraded = 0
    while candidates and ai.budget_left():
        chunk, candidates = candidates[: config.AI_BATCH_SIZE], candidates[config.AI_BATCH_SIZE:]
        items = [{"id": t["id"], "title": t["source_title"], "text": t["_excerpt"], "link": t["source_url"],
                  "published": t["timestamp"], "feed_name": t["source_name"],
                  "feed_category": t.get("_feed_category") or t["category"]} for t in chunk]
        try:
            res = ai.analyze(items)
        except (AIUnavailable, ValueError, KeyError, requests.RequestException) as exc:
            log.info("Nachveredelung abgebrochen: %s", exc)
            break
        by_id = {t["id"]: t for t in chunk}
        for item in items:
            r = res.get(item["id"])
            if r is None:
                continue
            old = by_id[item["id"]]
            if r.get("relevant") is False:
                db["threats"] = [t for t in db["threats"] if t["id"] != old["id"]]
            else:
                new = build_threat(item, r, "ai")
                new["fetched_at"] = old.get("fetched_at", new["fetched_at"])
                db["threats"] = [new if t["id"] == old["id"] else t for t in db["threats"]]
            upgraded += 1
        save_db(db, feeds_status, provider)
    return upgraded


def locked_run(use_ai: bool) -> bool:
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log.warning("Ein anderer Backend-Lauf ist aktiv – übersprungen.")
            return False
        try:
            run_once(use_ai)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="FasTI Threat & Crisis Intelligence Backend")
    parser.add_argument("--loop", action="store_true", help="Dauerbetrieb im Intervall aus config.py")
    parser.add_argument("--interval", type=float, default=config.POLL_INTERVAL_MINUTES, help="Intervall in Minuten")
    parser.add_argument("--no-ai", action="store_true", help="nur regelbasierte Analyse")
    parser.add_argument("--reset", action="store_true", help="threats.json verwerfen")
    parser.add_argument("--skip-first", action="store_true", help="im Loop-Modus erst nach einem Intervall starten")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    if args.reset and os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
        log.info("%s gelöscht.", config.OUTPUT_FILE)

    if not args.loop:
        locked_run(not args.no_ai)
        return
    interval = max(1.0, args.interval) * 60
    log.info("Dauerbetrieb: alle %.0f Minuten (Strg+C beendet).", interval / 60)
    if args.skip_first:
        time.sleep(interval)
    while True:
        try:
            locked_run(not args.no_ai)
        except Exception:  # Loop darf nie sterben
            log.exception("Unerwarteter Fehler im Durchlauf")
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
