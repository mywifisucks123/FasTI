#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FasTI – lokaler Webserver für das Dashboard.

Liefert ausschließlich index.html und threats.json aus (keine Keys, keine Konfiguration)
und speichert Entscheidungen aus dem Dashboard (Ereignisprotokoll, verworfene Fehlalarme,
Wartungscheck) in decisions.json. Nur an 127.0.0.1 gebunden.

  python3 server.py [--port 8000]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DECISIONS_FILE = os.path.join(BASE_DIR, "decisions.json")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/threats.json": ("threats.json", "application/json; charset=utf-8")}
LOCK = threading.Lock()
MAX_BODY = 64 * 1024


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_decisions() -> dict:
    try:
        with open(DECISIONS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data.setdefault("dismissed", [])
    data.setdefault("confirmed", {})
    data.setdefault("manual", [])
    data.setdefault("maintenance_done", "")
    data.setdefault("prefs", {})
    return data


def save_decisions(data: dict) -> None:
    tmp = DECISIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, DECISIONS_FILE)


def text(value, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def apply_action(data: dict, req: dict) -> None:
    action = req.get("action")
    key = text(req.get("key"), 80)
    if action == "dismiss" and key and key not in data["dismissed"]:
        data["dismissed"].append(key)
        data["confirmed"].pop(key, None)
    elif action == "undismiss":
        data["dismissed"] = [k for k in data["dismissed"] if k != key]
    elif action == "confirm" and key:
        data["confirmed"][key] = {
            "confirmed_at": now_iso(), "event_date": text(req.get("event_date"), 40),
            "title": text(req.get("title")), "source_url": text(req.get("source_url"), 500),
            "trigger": text(req.get("trigger"), 4), "list": text(req.get("list"), 2),
            "label": text(req.get("label")), "stage_after": text(req.get("stage_after"), 40),
            "note": text(req.get("note")),
        }
        data["dismissed"] = [k for k in data["dismissed"] if k != key]
    elif action == "unconfirm":
        data["confirmed"].pop(key, None)
    elif action == "manual_add":
        data["manual"].append({
            "id": uuid.uuid4().hex[:10], "event_date": text(req.get("event_date"), 40) or now_iso()[:10],
            "title": text(req.get("title")), "trigger": text(req.get("trigger"), 4), "list": text(req.get("list"), 2),
            "stage_after": text(req.get("stage_after"), 40), "note": text(req.get("note")), "created_at": now_iso(),
        })
    elif action == "manual_remove":
        data["manual"] = [m for m in data["manual"] if m.get("id") != key]
    elif action == "maintenance_done":
        data["maintenance_done"] = text(req.get("date"), 10) or now_iso()[:10]
    elif action == "set_pref":
        name = text(req.get("name"), 40)
        if name:
            data["prefs"][name] = req.get("value")
    elif action == "import_dismissed":
        for k in req.get("keys") or []:
            k = text(k, 80)
            if k and k not in data["dismissed"]:
                data["dismissed"].append(k)
    else:
        raise ValueError("unbekannte Aktion")


class Handler(BaseHTTPRequestHandler):
    server_version = "FasTI"

    def log_message(self, fmt, *args):  # ruhig bleiben
        pass

    def _allowed_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("localhost", "127.0.0.1")

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._allowed_host():
            return self._send(403, b"forbidden", "text/plain")
        path = self.path.split("?", 1)[0]
        if path == "/api/decisions":
            with LOCK:
                return self._json(200, load_decisions())
        if path in STATIC:
            name, ctype = STATIC[path]
            try:
                with open(os.path.join(BASE_DIR, name), "rb") as fh:
                    return self._send(200, fh.read(), ctype)
            except FileNotFoundError:
                return self._send(404, b"not found", "text/plain")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._allowed_host():
            return self._send(403, b"forbidden", "text/plain")
        origin = (self.headers.get("Origin") or "").lower()
        if origin and not re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", origin):
            return self._send(403, b"forbidden", "text/plain")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(415, b"json required", "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, b"too large", "text/plain")
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "ungültiges JSON"})
        path = self.path.split("?", 1)[0]
        if path == "/api/decisions":
            with LOCK:
                data = load_decisions()
                try:
                    apply_action(data, req)
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
                save_decisions(data)
                return self._json(200, data)
        if path == "/api/test-push":
            try:
                import backend  # lazy: nur für den Test-Push nötig
                channels = backend.send_notification("FasTI · Test",
                                                     "Wenn du das liest, funktionieren die Benachrichtigungen.", 3)
                return self._json(200, {"sent": channels, "topic": backend.ntfy_topic()})
            except Exception as exc:  # noqa: BLE001
                return self._json(500, {"error": str(exc)[:200]})
        return self._send(404, b"not found", "text/plain")


def main() -> None:
    parser = argparse.ArgumentParser(description="FasTI Dashboard-Server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
