#!/usr/bin/env python3
"""Directors' Dealings für dt-insider: Eigengeschäfte von Führungskräften (Art. 19 MAR). Nur Standardbibliothek.

Liest die öffentliche BaFin-Datenbank „Eigengeschäfte von Führungskräften“ als CSV-Export
und macht daraus saubere Zeilen: Emittent, ISIN, Symbol, Person, Funktion, Kauf oder Verkauf,
Durchschnittspreis, Volumen in Euro, Handels-, Mitteilungs- und Veröffentlichungsdatum,
Handelsplatz und den Meldeverzug in Geschäftstagen.

    python3 insider.py index                              # letzte Woche, alle Emittenten
    python3 insider.py index --isin DE0006305006 --monat  # ein Emittent, letzter Monat
    python3 insider.py index --person "Martin Schmitt" --art kauf --min-volumen 20000
    python3 insider.py index --von 01.10.2026 --bis 28.10.2026 --summe
    python3 insider.py new                                # nur was seit dem letzten Lauf neu ist
    python3 insider.py parse export.csv                   # eine gespeicherte Exportdatei lesen

Woher die Daten kommen:
  - https://portal.mvp.bafin.de/database/DealingsInfo/ (CSV-Export der Suche, UTF-8 mit BOM,
    Trenner ";"). Die BaFin aktualisiert die Datenbank täglich („Stand der Daten“).
  - Symbole kommen aus trader/universe.txt (Zeilen SYMBOL|Name|ISIN|Gruppe).

Was eine Meldung ist, und was nicht:
  - Eine öffentliche Mitteilung nach Art. 19 MAR. Führungskräfte melden unverzüglich, spätestens
    drei Geschäftstage nach dem Geschäft; veröffentlicht wird danach. Die Meldung ist also nie früh.
  - Das Volumen ist ein Betrag in Euro, keine Stückzahl.
  - Schnell gelesen ist kein Insiderwissen. Hier gibt es keins.

Status: `new` merkt sich in trader/state/insider.json, welche Zeilen schon gezeigt wurden
(sha256 über alle Felder einer Zeile), damit jede Meldung einmal auftaucht.
Offline: --offline DATEI liest einen gespeicherten Export statt des Netzes. Die Tests nutzen das.
"""

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

SEARCH_URL = "https://portal.mvp.bafin.de/database/DealingsInfo/sucheForm.do"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
PAUSE_SECONDS = 2.0
ZEITRAUM = {"gesamt": "0", "woche": "1", "monat": "2", "datum": "3"}
ZEITRAUM_TEXT = {"gesamt": "Gesamtzeitraum", "woche": "letzte Woche", "monat": "letzter Monat"}
LATE_BUSINESS_DAYS = 3
THRESHOLD_EUR = 20000
FIRST_RUN_DAYS = 7
HEADERS = {
    "emittent": "issuer",
    "bafin-id": "bafin_id",
    "isin": "isin",
    "meldepflichtiger": "person",
    "position / status": "position",
    "art des instruments": "instrument",
    "art des geschäfts": "kind",
    "durchschnittspreis": "price_text",
    "aggregiertes volumen": "volume_text",
    "mitteilungsdatum": "notified",
    "datum des geschäfts": "traded",
    "ort des geschäfts": "venue",
    "datum der aktivierung": "published",
}
REQUIRED = ("issuer", "person", "kind", "traded", "notified")
FIELDS = ("issuer", "bafin_id", "isin", "person", "position", "instrument", "kind", "price_text",
          "volume_text", "notified", "traded", "venue", "published")
ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
FIRM = re.compile(r"(\bGmbH\b|\bmbH\b|\bAG\b|\bSE\b|\bKG\b|\bKGaA\b|\bUG\b|\bGbR\b|\bOHG\b|"
                  r"\bS\.?A\.?\b|\bSPF\b|\bS\.p\.A\.|\bLtd\b|\bLLC\b|\bInc\b|\bB\.V\.|\bN\.V\.|"
                  r"Holding|Stiftung|\be\.V\.|Partners|Beteiligung|Invest|Capital|Verwaltung)", re.I)
SIDES = {"buy": "Kauf", "sell": "Verkauf", "other": "Sonstiges"}
ART = {"kauf": "buy", "verkauf": "sell", "sonstiges": "other"}
NOTE = ("Öffentliche Meldungen nach Art. 19 MAR aus der BaFin-Datenbank, gemeldet bis zu drei "
        "Geschäftstage nach dem Geschäft und danach veröffentlicht. Volumen ist ein Betrag in Euro, "
        "keine Stückzahl. Kein Insiderwissen.")

_last_request = [0.0]


class InsiderError(Exception):
    pass


# ---------------------------------------------------------------- dates and numbers

def de_date(text):
    """'26.10.2026' -> '2026-10-26', sonst None."""
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", text or "")
    if not m:
        return None
    try:
        return _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def de_datetime(text):
    """'28.10.2026 06:01:37' -> '2026-10-28T06:01:37' (nur Datum: '2026-10-28')."""
    d = de_date(text)
    if not d:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", text)
    if not m:
        return d
    return "%sT%02d:%s:%s" % (d, int(m.group(1)), m.group(2), m.group(3) or "00")


def parse_input_date(text, flag):
    d = de_date(text)
    if not d or not re.match(r"^\s*\d{1,2}\.\d{1,2}\.\d{4}\s*$", text):
        raise InsiderError("%s erwartet ein Datum wie 26.10.2026 (TT.MM.JJJJ), nicht %r" % (flag, text))
    return _dt.date.fromisoformat(d)


def amount(text):
    """'6.660,00 EUR' -> (6660.0, 'EUR', 2); leer -> (None, None, 0)."""
    s = (text or "").strip()
    if not s:
        return None, None, 0
    cur = None
    m = re.match(r"^(.*?)\s*([A-Za-z]{3}|\u20ac)$", s)
    if m:
        s, cur = m.group(1).strip(), m.group(2).upper().replace("\u20ac", "EUR")
    digits = s.split(",", 1)[1] if "," in s else ""
    try:
        value = float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None, cur, 0
    return value, cur or "EUR", len(digits)


def business_days(start, end):
    """Geschäftstage nach dem Handelstag bis einschließlich Mitteilungstag.
    Wochenenden und XETRA-Feiertage zählen nicht. Gleicher Tag = 0."""
    if end <= start:
        return 0
    n, d = 0, start
    while d < end:
        d += _dt.timedelta(days=1)
        if markt.trading_day(d, "xetra")[0]:
            n += 1
    return n


# ---------------------------------------------------------------- parsing the export

def decode(data):
    """Bytes des Exports -> Text. UTF-8 (mit oder ohne BOM), sonst Windows-1252/Latin-1."""
    if isinstance(data, str):
        return data.lstrip("\ufeff")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def side_of(kind):
    k = (kind or "").strip().lower()
    if k.startswith("kauf") or k in ("purchase", "buy"):
        return "buy"
    if k.startswith("verkauf") or k in ("sale", "sell"):
        return "sell"
    return "other"


def associate_kind(row):
    if (row.get("position") or "").strip().lower() != "in enger beziehung":
        return None
    return "firma" if FIRM.search(row.get("person") or "") else "person"


def row_key(fields, nth=0):
    raw = "\x1f".join((fields.get(k) or "").strip() for k in FIELDS) + "\x1f%d" % nth
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _finish(raw, nth):
    row = {k: (raw.get(k) or "").strip() or None for k in FIELDS}
    if row["isin"]:
        row["isin"] = row["isin"].upper()
    row["price"], row["price_currency"], row["price_decimals"] = amount(row["price_text"])
    row["volume"], row["volume_currency"], _ = amount(row["volume_text"])
    traded_text, notified_text, published_text = row["traded"], row["notified"], row["published"]
    row["traded"] = de_date(traded_text)
    row["notified"] = de_date(notified_text)
    row["published"] = de_datetime(published_text)
    row["side"] = side_of(row["kind"])
    row["signal"] = row["side"] in ("buy", "sell")
    row["close_associate"] = associate_kind(row)
    if row["traded"] and row["notified"]:
        days = business_days(_dt.date.fromisoformat(row["traded"]), _dt.date.fromisoformat(row["notified"]))
        row["delay_business_days"] = days
        row["late"] = days > LATE_BUSINESS_DAYS
    else:
        row["delay_business_days"] = None
        row["late"] = False
    row["key"] = row_key(raw, nth)
    row["symbol"] = None
    row["in_portfolio"] = False
    row["on_watchlist"] = False
    return row


def parse_csv(data):
    """Alle Zeilen eines BaFin-CSV-Exports als dicts, in der Reihenfolge der Datei."""
    text = decode(data)
    if text.lstrip()[:1] == "<":
        raise InsiderError("das ist eine HTML-Seite, kein CSV-Export der BaFin (Suche ohne Treffer, "
                           "Personenauswahl oder Wartungsseite)")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if not header:
        return []
    cols = [HEADERS.get(" ".join(h.strip().lstrip("\ufeff").split()).lower()) for h in header]
    missing = [k for k in REQUIRED if k not in cols]
    if missing:
        raise InsiderError("das ist kein Export „Eigengeschäfte von Führungskräften“: es fehlen die Spalten %s"
                           % ", ".join(missing))
    rows, seen = [], {}
    for rec in reader:
        if not any(x.strip() for x in rec):
            continue
        raw = {}
        for i, key in enumerate(cols):
            if key and i < len(rec):
                raw[key] = rec[i]
        base = row_key(raw)
        nth = seen.get(base, 0)
        seen[base] = nth + 1
        rows.append(_finish(raw, nth))
    return rows


def read_file(path):
    with open(path, "rb") as fh:
        return parse_csv(fh.read())


# ---------------------------------------------------------------- the network

def build_url(zeitraum="woche", isin=None, issuer=None, von=None, bis=None):
    params = [
        ("meldepflichtigerName", ""),
        ("zeitraum", ZEITRAUM[zeitraum]),
        ("d-4000784-e", "1"),
        ("emittentButton", "Suche Emittent"),
        ("emittentName", issuer or ""),
        ("zeitraumVon", markt.date_de(von) if von else ""),
        ("emittentIsin", isin or ""),
        ("6578706f7274", "1"),
        ("zeitraumBis", markt.date_de(bis) if bis else ""),
    ]
    return SEARCH_URL + "?" + urllib.parse.urlencode(params)


def download(url, timeout=60, pause=PAUSE_SECONDS):
    wait = _last_request[0] + pause - time.time()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv,*/*;q=0.8",
                                               "Accept-Language": "de-DE,de;q=0.9"})
    hint = ("Versuch es später noch einmal, oder lade den CSV-Export im Browser herunter und lies ihn "
            "mit `insider.py parse DATEI`.")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise InsiderError("die BaFin-Datenbank antwortet mit HTTP %s. %s" % (exc.code, hint))
    except urllib.error.URLError as exc:
        raise InsiderError("die BaFin-Datenbank ist nicht erreichbar (%s). %s" % (exc.reason, hint))
    except socket.timeout:
        raise InsiderError("die BaFin-Datenbank antwortet nicht (Zeitüberschreitung nach %d s). %s"
                           % (timeout, hint))
    finally:
        _last_request[0] = time.time()
    if "html" in ctype.lower():
        raise InsiderError("die BaFin hat eine HTML-Seite statt des CSV-Exports geschickt. %s" % hint)
    return data


def load_rows(offline=None, **query):
    if offline:
        return read_file(offline), offline
    url = build_url(**query)
    return parse_csv(download(url)), url


# ---------------------------------------------------------------- your stocks

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def load_universe(path):
    """{ISIN: (Symbol, Name, Gruppe)} aus Zeilen SYMBOL|Name|ISIN|Gruppe. Alte Zeilen SYMBOL|Name zählen nicht."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = [p.strip() for p in line.rstrip("\n").split("|")]
            if len(parts) < 3 or line.startswith("#"):
                continue
            isin = parts[2].upper()
            if parts[0] and ISIN.match(isin):
                out.setdefault(isin, (parts[0].upper(), parts[1], parts[3] if len(parts) > 3 else ""))
    return out


def your_stocks(portfolio=None, watchlist=None):
    """{"portfolio": {"symbols", "isins"}, "watchlist": {"symbols", "isins"}}."""
    out = {"portfolio": {"symbols": set(), "isins": set()}, "watchlist": {"symbols": set(), "isins": set()}}
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []) if isinstance(pf, dict) else []:
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out["portfolio"]["symbols"].add(str(sym).upper())
        if p.get("isin"):
            out["portfolio"]["isins"].add(str(p["isin"]).upper())
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []) if isinstance(wl, dict) else []:
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out["watchlist"]["symbols"].add(str(sym).upper())
        if h.get("isin"):
            out["watchlist"]["isins"].add(str(h["isin"]).upper())
    return out


def mark(rows, universe=None, stocks=None):
    universe = universe or {}
    stocks = stocks or your_stocks()
    for r in rows:
        hit = universe.get(r["isin"] or "")
        r["symbol"] = hit[0] if hit else None
        for name, flag in (("portfolio", "in_portfolio"), ("watchlist", "on_watchlist")):
            s = stocks[name]
            r[flag] = bool((r["isin"] and r["isin"] in s["isins"]) or (r["symbol"] and r["symbol"] in s["symbols"]))
    return rows


# ---------------------------------------------------------------- filters

def person_match(person, query):
    """'Martin Schmitt', 'Schmitt, Martin' oder 'schmitt' gegen 'Schmitt, Martin'."""
    words = [w for w in re.split(r"[\s,]+", (query or "").lower()) if w]
    have = (person or "").lower()
    return all(w in have for w in words)


def select(rows, isin=None, issuer=None, person=None, art="alle", min_volume=None, von=None, bis=None):
    """von/bis filtern auf das Datum des Geschäfts."""
    out = []
    side = ART.get((art or "alle").lower())
    for r in rows:
        if isin and (r["isin"] or "") != isin.upper():
            continue
        if issuer and issuer.lower() not in (r["issuer"] or "").lower():
            continue
        if person and not person_match(r["person"], person):
            continue
        if side and r["side"] != side:
            continue
        if min_volume is not None and (r["volume"] is None or r["volume"] < min_volume):
            continue
        if von and (r["traded"] or "") < von.isoformat():
            continue
        if bis and (r["traded"] or "9999") > bis.isoformat():
            continue
        out.append(r)
    return out


def summarize(rows):
    """Summe Käufe/Verkäufe je Emittent, größte Kaufsumme zuerst."""
    by = {}
    for r in rows:
        key = (r["issuer"] or "?", r["isin"] or "")
        s = by.setdefault(key, {"issuer": key[0], "isin": key[1] or None, "symbol": r["symbol"],
                                "buys": 0, "buy_volume": 0.0, "sells": 0, "sell_volume": 0.0, "other": 0})
        if r["side"] == "buy":
            s["buys"] += 1
            s["buy_volume"] += r["volume"] or 0.0
        elif r["side"] == "sell":
            s["sells"] += 1
            s["sell_volume"] += r["volume"] or 0.0
        else:
            s["other"] += 1
    out = list(by.values())
    for s in out:
        s["buy_volume"] = round(s["buy_volume"], 2)
        s["sell_volume"] = round(s["sell_volume"], 2)
        s["net_volume"] = round(s["buy_volume"] - s["sell_volume"], 2)
    out.sort(key=lambda s: (-s["buy_volume"], -s["sell_volume"], s["issuer"]))
    return out


# ---------------------------------------------------------------- state

def load_state(path):
    doc = load_json(path)
    return doc if isinstance(doc, dict) else {"seen": [], "last_check": None}


def save_state(path, state):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def new_since(rows, state, today, first_days=FIRST_RUN_DAYS):
    """Zeilen, die noch nicht gezeigt wurden. Beim ersten Lauf nur die der letzten first_days Tage
    (nach Veröffentlichung, sonst Mitteilung)."""
    if state.get("last_check") is None:
        cutoff = (today - _dt.timedelta(days=first_days)).isoformat()
        return [r for r in rows if (r["published"] or r["notified"] or "")[:10] >= cutoff]
    seen = set(state.get("seen", []))
    return [r for r in rows if r["key"] not in seen]


# ---------------------------------------------------------------- output

def _iso_day(text):
    return _dt.date.fromisoformat(text[:10]) if text else None


def _published(text):
    if not text:
        return "Veröffentlichung unbekannt"
    if "T" not in text:
        return "veröffentlicht %s" % markt.day_label(_iso_day(text))
    return "veröffentlicht %s Uhr" % markt.stamp(_dt.datetime.fromisoformat(text))


def _delay(r):
    n = r["delay_business_days"]
    if n is None:
        return "Meldeverzug unbekannt"
    if n == 0:
        text = "am selben Tag gemeldet"
    else:
        text = "%d %s später" % (n, "Geschäftstag" if n == 1 else "Geschäftstage")
    if r["late"]:
        text += ", VERSPÄTET (Frist: %d Geschäftstage)" % LATE_BUSINESS_DAYS
    return text


def describe(r):
    """Drei bis fünf Zeilen Text für eine Meldung."""
    ids = [x for x in (r["isin"] and "ISIN %s" % r["isin"], r["symbol"]) if x]
    head = r["issuer"] or "?"
    if ids:
        head += " (%s)" % ", ".join(ids)
    tags = []
    if r["in_portfolio"]:
        tags.append("im Depot")
    if r["on_watchlist"]:
        tags.append("auf der Watchlist")
    if tags:
        head += "  [%s]" % ", ".join(tags)
    who = "%s (%s)" % (r["person"] or "?", r["position"] or "Funktion unbekannt")
    lines = [head, "    %s: %s, %s" % (r["kind"] or "?", who, r["instrument"] or "Instrument unbekannt")]
    money = []
    if r["price"] is not None:
        money.append("Durchschnittspreis %s" % markt.money(r["price"], r["price_currency"],
                                                             max(2, r["price_decimals"])))
    else:
        money.append("kein Preis gemeldet")
    if r["volume"] is not None:
        money.append("Volumen %s (Betrag, keine Stückzahl)" % markt.money(r["volume"], r["volume_currency"]))
    else:
        money.append("kein Volumen gemeldet")
    lines.append("    " + ", ".join(money))
    when = []
    if r["traded"]:
        when.append("Handel %s %s" % (markt.day_label(_iso_day(r["traded"])),
                                      ("an %s" % r["venue"]) if r["venue"] else "(kein Handelsplatz angegeben)"))
    if r["notified"]:
        when.append("Mitteilung %s" % markt.day_label(_iso_day(r["notified"])))
    when.append(_delay(r))
    when.append(_published(r["published"]))
    lines.append("    " + ", ".join(when))
    if not r["signal"]:
        lines.append("    %s ist kein Kauf und kein Verkauf (etwa Zuteilung, Aktienoptionsprogramm, "
                     "Schenkung): zählt nicht als Marktsignal." % (r["kind"] or "Dieses Geschäft"))
    if r["close_associate"] == "firma":
        lines.append("    In enger Beziehung: eine Firma, die einer Führungsperson nahesteht, "
                     "nicht die Führungsperson selbst.")
    elif r["close_associate"] == "person":
        lines.append("    In enger Beziehung: eine nahestehende Person (etwa Angehörige), "
                     "nicht die Führungsperson selbst.")
    return "\n".join(lines)


def render_rows(rows):
    return "".join(describe(r) + "\n" for r in rows)


def render_summary(summary):
    out = ["Summe je Emittent:"]
    for s in summary:
        ident = s["symbol"] or (s["isin"] and "ISIN %s" % s["isin"])
        name = s["issuer"] + (" (%s)" % ident if ident else "")
        bits = []
        if s["buys"]:
            bits.append("%d %s über %s" % (s["buys"], "Kauf" if s["buys"] == 1 else "Käufe",
                                           markt.money(s["buy_volume"], "EUR")))
        if s["sells"]:
            bits.append("%d %s über %s" % (s["sells"], "Verkauf" if s["sells"] == 1 else "Verkäufe",
                                           markt.money(s["sell_volume"], "EUR")))
        if s["buys"] and s["sells"]:
            bits.append("netto %s" % markt.money(s["net_volume"], "EUR"))
        if s["other"]:
            bits.append("%d Sonstiges (kein Signal)" % s["other"])
        out.append("  %s: %s" % (name, ", ".join(bits)))
    return "\n".join(out) + "\n"


def _count(n):
    return "1 Meldung" if n == 1 else "%d Meldungen" % n


# ---------------------------------------------------------------- CLI

def _parser():
    ap = argparse.ArgumentParser(
        description="Directors' Dealings aus der BaFin-Datenbank „Eigengeschäfte von Führungskräften“ "
                    "(Art. 19 MAR): öffentliche Meldungen, schnell gelesen. Kein Insiderwissen.")
    sub = ap.add_subparsers(dest="cmd", metavar="BEFEHL")

    def filters(p):
        p.add_argument("--isin", help="nur dieser Emittent (ISIN, z. B. DE0006305006)")
        p.add_argument("--emittent", help="nur Emittenten, deren Name das enthält")
        p.add_argument("--person", help="nur diese meldepflichtige Person, z. B. \"Martin Schmitt\"")
        p.add_argument("--art", choices=["kauf", "verkauf", "sonstiges", "alle"], default="alle",
                       help="Art des Geschäfts (Standard: alle)")
        p.add_argument("--min-volumen", type=float, metavar="EUR", help="nur ab diesem Volumen in Euro")
        p.add_argument("--summe", action="store_true", help="Summe Käufe/Verkäufe je Emittent anhängen")
        p.add_argument("--limit", type=int, default=50, help="höchstens so viele Zeilen zeigen (Standard 50)")
        p.add_argument("--universe", default="trader/universe.txt", help="Symbolliste SYMBOL|Name|ISIN|Gruppe")
        p.add_argument("--portfolio", default="trader/portfolio.json")
        p.add_argument("--watchlist", default="trader/watchlist.json")
        p.add_argument("--json", action="store_true", help="Ausgabe als JSON")

    def period(p):
        g = p.add_mutually_exclusive_group()
        g.add_argument("--woche", action="store_true", help="letzte Woche (Standard)")
        g.add_argument("--monat", action="store_true", help="letzter Monat")
        g.add_argument("--gesamt", action="store_true", help="Gesamtzeitraum")
        p.add_argument("--von", metavar="TT.MM.JJJJ", help="ab diesem Datum")
        p.add_argument("--bis", metavar="TT.MM.JJJJ", help="bis zu diesem Datum (Standard: heute)")
        p.add_argument("--offline", metavar="CSV", help="einen gespeicherten BaFin-Export lesen statt des Netzes")

    p = sub.add_parser("index", help="Meldungen auflisten")
    period(p)
    filters(p)

    p = sub.add_parser("new", help="nur Meldungen, die seit dem letzten Lauf neu sind")
    period(p)
    filters(p)
    p.add_argument("--state", default="trader/state/insider.json")
    p.add_argument("--today", help="JJJJ-MM-TT, für nachvollziehbare Läufe")
    p.add_argument("--dry-run", action="store_true", help="Statusdatei nicht ändern")

    p = sub.add_parser("parse", help="eine gespeicherte CSV-Exportdatei lesen")
    p.add_argument("csv_file")
    p.add_argument("--von", metavar="TT.MM.JJJJ")
    p.add_argument("--bis", metavar="TT.MM.JJJJ")
    filters(p)
    return ap


def _period(args, today, state=None):
    von = parse_input_date(args.von, "--von") if getattr(args, "von", None) else None
    bis = parse_input_date(args.bis, "--bis") if getattr(args, "bis", None) else None
    if bis and not von:
        raise InsiderError("--bis braucht auch --von")
    if von:
        bis = bis or today
        if bis < von:
            raise InsiderError("--bis liegt vor --von")
        return "datum", von, bis
    if getattr(args, "gesamt", False):
        return "gesamt", None, None
    if getattr(args, "monat", False):
        return "monat", None, None
    if getattr(args, "woche", False):
        return "woche", None, None
    last = (state or {}).get("last_check")
    if last and _iso_day(last) < today - _dt.timedelta(days=FIRST_RUN_DAYS - 1):
        return "monat", None, None
    return "woche", None, None


def _today(args):
    if getattr(args, "today", None):
        try:
            return _dt.date.fromisoformat(args.today)
        except ValueError:
            raise InsiderError("--today erwartet ein Datum wie 2026-10-28 (JJJJ-MM-TT)")
    return _dt.date.today()


def main(argv=None):
    args = _parser().parse_args(argv)
    if not args.cmd:
        _parser().print_help()
        return 2
    with markt.restore():
        markt.use("xetra")
        try:
            return _run(args)
        except (InsiderError, OSError, ValueError, markt.MarketError) as exc:
            print("insider: %s" % exc, file=sys.stderr)
            return 2


def _run(args):
    today = _today(args)
    if args.isin and not ISIN.match(args.isin.strip().upper()):
        raise InsiderError("--isin erwartet eine ISIN wie DE0006305006, nicht %r" % args.isin)
    state = load_state(args.state) if args.cmd == "new" else None
    if args.cmd == "parse":
        zeitraum, von, bis = _period(args, today)
        rows, source = read_file(args.csv_file), args.csv_file
        local_dates = True
    else:
        zeitraum, von, bis = _period(args, today, state)
        rows, source = load_rows(args.offline, zeitraum=zeitraum, isin=args.isin, issuer=args.emittent,
                                 von=von, bis=bis)
        local_dates = bool(args.offline)
    picked = select(rows, isin=args.isin, issuer=args.emittent, person=args.person, art=args.art,
                    min_volume=args.min_volumen, von=von if local_dates else None,
                    bis=bis if local_dates else None)
    mark(picked, load_universe(args.universe), your_stocks(args.portfolio, args.watchlist))

    if args.cmd in ("index", "parse"):
        shown = picked[:args.limit]
        if args.json:
            doc = {"source": source, "count": len(picked), "rows": shown}
            if args.summe:
                doc["summary"] = summarize(picked)
            print(json.dumps(doc, indent=2, ensure_ascii=False))
            return 0 if picked else 1
        if not picked:
            print("Keine passenden Meldungen (%s)." % _source_label(source, zeitraum, von, bis))
            return 1
        print("%s, %s:" % (_count(len(picked)), _source_label(source, zeitraum, von, bis)))
        sys.stdout.write(render_rows(shown))
        if len(picked) > len(shown):
            print("... und %d weitere (--limit N für mehr)." % (len(picked) - len(shown)))
        if args.summe:
            sys.stdout.write(render_summary(summarize(picked)))
        print(NOTE)
        return 0

    fresh = new_since(picked, state, today)
    if args.json:
        print(json.dumps({"source": source, "last_check": state.get("last_check"), "new": fresh},
                         indent=2, ensure_ascii=False))
    elif not fresh:
        last = state.get("last_check")
        print("Nichts Neues seit %s." % (markt.stamp(_dt.datetime.fromisoformat(last)) + " Uhr"
                                         if last else "dem letzten Lauf"))
    else:
        print("NEU: %s seit %s (%s):" % (
            _count(len(fresh)),
            "dem letzten Lauf" if state.get("last_check") else "einer Woche (erster Lauf)",
            _source_label(source, zeitraum, von, bis)))
        sys.stdout.write(render_rows(fresh))
        if args.summe:
            sys.stdout.write(render_summary(summarize(fresh)))
        print(NOTE)
    if not args.dry_run:
        seen = set(state.get("seen", []))
        seen.update(r["key"] for r in picked)
        state["seen"] = sorted(seen)
        state["last_check"] = _dt.datetime.now().replace(microsecond=0).isoformat()
        save_state(args.state, state)
    return 0 if fresh else 1


def _source_label(source, zeitraum, von, bis):
    if source.startswith("http"):
        if zeitraum == "datum":
            span = "%s bis %s" % (markt.date_de(von), markt.date_de(bis))
        else:
            span = ZEITRAUM_TEXT[zeitraum]
        return "BaFin-Datenbank, %s" % span
    label = "Datei %s" % os.path.basename(source)
    if von:
        label += ", Handel %s bis %s" % (markt.date_de(von), markt.date_de(bis))
    return label


if __name__ == "__main__":
    sys.exit(main())
