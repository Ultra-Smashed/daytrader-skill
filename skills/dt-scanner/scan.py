#!/usr/bin/env python3
"""Chart-Scanner für dt-scanner: scannt Tausende Charts nach Setups. Nur Standardbibliothek.

    python3 scan.py universe                          # XETRA-Aktien der Deutschen Börse -> trader/universe.txt
    python3 scan.py universe --nur-deutschland        # nur DAX, MDAX, SDAX und DEUTSCHLAND
    python3 scan.py universe --market us              # US-Aktien aus den Nasdaq-Trader-Listen
    python3 scan.py daily                             # vor der Eröffnung: Tages-Setups -> trader/watchlist.json
    python3 scan.py daily --symbols SAP.DE,BMW.DE     # oder --watchlist DATEI, oder --limit 200
    python3 scan.py orb                               # ab 9:20 Uhr: Opening-Range-Breakouts bis jetzt
    python3 scan.py orb --at 10:15 --or-minutes 15    # die Uhr auf 10:15 Uhr stellen
    python3 scan.py orb --offline dax.json.gz --now "2026-10-27 10:15"

Markt: --market xetra|us. Ohne Flag bestimmen die Symbole den Markt (SAP.DE ist
XETRA, TSLA ist US; eine Liste muss zu einem Markt gehören), sonst "market" in
trader/config.json, sonst XETRA. Alle Zeiten sind Ortszeit des Marktes
(XETRA: deutsche Zeit, US: New Yorker Zeit, ET).

universe  XETRA (Standard): lädt die Liste "T7 (XETR) All tradable instruments"
          der Deutschen Börse (CSV, Semikolon) und behält Instrument Type CS
          mit Instrument Status Active. Symbol = Mnemonic + ".DE" (SAP.DE,
          1COV.DE). --gruppen DAX,MDAX filtert nach der Spalte "Product
          Assignment Group Description"; --nur-deutschland = DAX, MDAX, SDAX,
          DEUTSCHLAND. Schreibt SYMBOL|Name|ISIN|Gruppe je Zeile.
          US: lädt nasdaqlisted.txt und otherlisted.txt von Nasdaq Trader und
          behält US-Stammaktien, Ordinary Shares und ADRs. Die Regel, in dieser
          Reihenfolge:
            1. kein Testwert, kein ETF, keine NextShares
            2. ein einfaches Kürzel: 1 bis 5 Buchstaben, oder 1 bis 4 Buchstaben
               plus ein Klassenbuchstabe nach einem Punkt (BRK.B); eine Endung
               .U / .W / .R (Units, Warrants, Rights) fliegt raus, ebenso ein
               $-Vorzug
            3. raus, egal was der Name sonst sagt: Warrants; SPAC-Units und
               -Rights ("Units, each consisting of", "Rights to receive");
               Notes, ETNs, Debentures; ein %-Kupon; "Depositary Shares", die
               nicht American oder Global sind (die tragen einen Vorzug)
            4. drin: der Name nennt Common Stock / Shares / Units, Ordinary
               Shares, Shares of Beneficial Interest, ADS / ADR / American oder
               Global Depositary Shares, oder Partnership- / Trust-Units
            5. raus: der Name sagt noch Unit, Right, Bond, Preferred oder Preference
            6. drin: alles andere (einfache Namen wie "AMETEK, Inc.")
          Schreibt SYMBOL|Name je Zeile. Alle Leser nehmen nur das erste Feld.

daily     Vorbörslicher Scan der Tagesschlusskurse (Yahoo spark: 20 Symbole je
          Anfrage, 3 Monate Tageskerzen, nur Schlusskurse). Liquidität aus den
          spark-Metadaten: regularMarketPrice >= --min-price und
          regularMarketVolume >= --min-volume (XETRA 5 € und 50.000 Stück,
          US 5 $ und 1.000.000 Stück). Setups, nur aus Schlusskursen:
            breakout_20d     der letzte Schluss liegt über jedem der 20 davor
            bull_flag        mehr als 10 % Plus in den 10 Sitzungen vor den
                             letzten 5, dann die letzten 5 Schlüsse in 5 % Spanne
            reclaim_ma20     unter dem 20-Tage-Durchschnitt geschlossen, dann darüber
            oversold         RSI 14 (Wilder) unter 30
            oversold_bounce  RSI 14 war gestern unter 30 und heute ging es aufwärts
          Die heutige Tageskerze zählt erst nach Handelsschluss.

orb       Opening-Range-Breakouts auf 5-Minuten-Kerzen. Die Range sind die
          ersten --or-minutes (15) der Sitzung ab der Eröffnung (XETRA 9:00,
          US 9:30). Stufe 1: spark-Schlusskurse für jedes Symbol (5-Minuten-
          Kerzen, 20 je Anfrage); ein Chart kommt weiter, wenn eine fertige
          Kerze nach der Range auf oder über dem höchsten Range-Schluss schloss
          (eine notwendige Bedingung). Stufe 2: der v8-Chart jedes Kandidaten
          (echte Hochs und Tiefs): Range-Hoch = höchstes Hoch der Range-Kerzen,
          ein Treffer = die erste fertige Kerze, die DARÜBER SCHLIESST, zur
          Schlusszeit dieser Kerze. Stufe 2 lädt höchstens --max-confirm (200)
          Charts, die meistgehandelten zuerst (Preis mal Volumen bis jetzt), und
          sagt es, wenn sie vorher aufhört. Ein Chart ist nur nutzbar, wenn jede
          5-Minuten-Kerze von der Eröffnung bis zur Uhrzeit da ist (eine fehlende
          Kerze heißt Handelsaussetzung oder keine Umsätze). Schwellen:
          --min-price 5 (letzter Schluss), --min-volume 0. Neue Einstiege nur
          bis no_entries_after (XETRA 17:00, US 15:30; Config oder --until).

Kerzen: Schlusskurse null fallen weg, eine Kerze neben dem 5-Minuten-Raster (der
Live-Tick, z. B. 10:49:45) fällt weg, und eine Kerze zählt erst, wenn sie fertig
ist (Beginn + 5 Minuten <= Uhrzeit). --now stellt die Uhr ("2026-10-27 10:15"
in Ortszeit des Marktes; ...Z für UTC). Yahoo liefert XETRA-Kerzen ca. 15 Minuten
verzögert: reichen die Daten nicht bis zur Uhrzeit, scannt orb bis zur letzten
fertigen Kerze und sagt das.

Yahoos Endpunkte sind kostenlos, inoffiziell und können hinterherhinken. Erst
query2, bei 429 oder 5xx query1, nach einem 429 ein zweiter Versuch nach einer
Pause. Eine höfliche Pause zwischen Anfragen (--pause). Teilergebnisse werden
als Teilergebnisse gemeldet.

--offline PFAD liest Dateien statt des Netzes: universe will für XETRA die CSV
(oder einen Ordner mit t7-xetr-allTradableInstruments.csv), für US einen Ordner
mit nasdaqlisted.txt und otherlisted.txt; daily und orb nehmen einen Ordner mit
<T>.json-v8-Charts oder spark-Antworten, oder eine Datei: eine spark-Antwort,
einen v8-Chart oder ein Bündel {"SAP.DE": <v8 json>, ...}. .json.gz geht auch.

Ein Scan ist eine Liste von Charts, die eine Regel erfüllen, keine Liste von Aktien zum Kaufen.
Exit-Code 0, wenn der Scan etwas gefunden hat, 1, wenn nicht oder wenn er nicht laufen konnte.
"""

import argparse
import csv
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

UA = "Mozilla/5.0 (compatible; daytrader-skill/1.0; +https://thanisch.co)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
NASDAQ_FILES = ("nasdaqlisted.txt", "otherlisted.txt")
NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/"
XETRA_FILE = "t7-xetr-allTradableInstruments.csv"
XETRA_URL = ("https://www.cashmarket.deutsche-boerse.com/resource/blob/1528/59b934f3381dc7f7ded915216edecddc/"
             "data/" + XETRA_FILE)
GERMAN_GROUPS = ("DAX", "MDAX", "SDAX", "DEUTSCHLAND")
SPARK_MAX = 20      # Yahoo's spark answers 400 above 20 symbols
PAUSE = 0.3         # seconds between requests: be polite to free endpoints
BACKOFF = 5.0       # seconds to wait before the one retry after a 429
SLEEP = time.sleep  # tests swap this out
BAR_MIN = 5
MAX_CONFIRM = 200   # stage-2 v8 charts per orb scan, most traded first
MIN_DAILY_BARS = 30
DEFAULT_UNIVERSE = "trader/universe.txt"
NOTE = "Ein Scan ist eine Liste von Charts, die eine Regel erfüllen, keine Liste von Aktien zum Kaufen."
DELAY_NOTE = "Hinweis: Yahoo liefert XETRA-Daten ca. 15 Minuten verzögert, nicht in Echtzeit."
# (min_price, min_volume) je Befehl und Markt. Yahoos XETRA-Volumen zählt nur den
# fortlaufenden Handel in Stück; bei 100.000 kämen am 27.10.2026 nur 30 der 43
# DAX-Zeilen durch, bei 50.000 sind es 37.
LIQUIDITY = {"daily": {"xetra": (5.0, 50000), "us": (5.0, 1000000)},
             "orb": {"xetra": (5.0, 0), "us": (5.0, 0)}}

SETUPS = [
    ("breakout_20d", "20-Tage-Schlusshoch-Ausbruch"),
    ("bull_flag", "Bull Flag"),
    ("reclaim_ma20", "über den 20-Tage-Durchschnitt zurückerobert"),
    ("oversold", "überverkauft (RSI unter 30)"),
    ("oversold_bounce", "Erholung aus überverkauft"),
]
LABEL = dict(SETUPS)
DROP_LABEL = {
    "test issue": "Testwerte", "ETF": "ETFs", "NextShares": "NextShares",
    "not a plain ticker": "kein einfaches Kürzel", "unit / warrant / right suffix": "Endung .U/.W/.R",
    "warrant": "Warrants", "unit or right": "SPAC-Units oder -Rights", "note": "Notes/ETNs",
    "coupon": "mit %-Kupon", "depositary": "Depositary Shares mit Vorzug", "unit": "Units",
    "right": "Rights", "bond": "Anleihen", "preferred": "Vorzugsaktien",
}


class ScanError(Exception):
    pass


# ---------------------------------------------------------------- time

def parse_now(text):
    """ISO-Zeit -> naive UTC. Ohne Offset gilt die Ortszeit des Marktes."""
    return markt.parse_now(text, error=ScanError)


def parse_hhmm(text, flag="--at"):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ScanError("%s erwartet eine Uhrzeit wie 10:15 (%s)" % (flag, markt.info()["zone"]))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def num(n):
    return markt.num(n, 0)


# ---------------------------------------------------------------- network

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_get(path):
    """GET a Yahoo Finance path. query2 first, query1 on a 429 or 5xx, and one
    more round after BACKOFF seconds if a 429 was seen. 4xx other than 429 is final."""
    last = "keine Antwort"
    for attempt in (0, 1):
        saw_429 = False
        for host in YAHOO_HOSTS:
            try:
                return http_get(host + path)
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                try:
                    body = e.read().decode("utf-8", "replace") if 400 <= e.code < 500 and e.code != 429 else ""
                except Exception:
                    body = ""
                finally:
                    e.close()
                if e.code == 429:
                    saw_429 = True
                    continue
                if e.code >= 500:
                    continue
                if body.strip().startswith("{"):
                    return body  # Yahoo's JSON error ("No data found"), parsed by the caller
                raise ScanError("Yahoo antwortete %s für %s" % (last, path.split("?")[0]))
            except (urllib.error.URLError, OSError) as e:
                last = str(getattr(e, "reason", e))
                continue
        if attempt == 0 and saw_429:
            SLEEP(BACKOFF)
            continue
        break
    raise ScanError("Yahoo antwortete %s für %s" % (last, path.split("?")[0]))


def to_yahoo(sym):
    return markt.to_yahoo(sym)


def spark_path(symbols, rng, interval):
    return "/v7/finance/spark?symbols=%s&range=%s&interval=%s" % (
        ",".join(to_yahoo(s) for s in symbols), rng, interval)


def chart_path(sym, rng, interval):
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (to_yahoo(sym), rng, interval)


# ---------------------------------------------------------------- parsing

def series_from_result(res):
    """A Yahoo chart result (v8 or one spark response) -> plain lists."""
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    t = res.get("timestamp") or []
    n = len(t)

    def col(k):
        v = q.get(k)
        return list(v) + [None] * (n - len(v)) if isinstance(v, list) else None
    return {"t": list(t), "c": col("close") or [None] * n, "o": col("open"), "h": col("high"),
            "l": col("low"), "v": col("volume"), "meta": res.get("meta") or {}}


def parse_spark(text_or_doc, wanted=None):
    """Spark JSON -> {SYM: series}. Symbols Yahoo does not know are simply missing
    from the answer. `wanted` maps Yahoo symbols back to ours (BRK-B -> BRK.B)."""
    doc = json.loads(text_or_doc) if isinstance(text_or_doc, str) else text_or_doc
    sp = (doc or {}).get("spark") if isinstance(doc, dict) else None
    if not isinstance(sp, dict):
        raise ScanError("Yahoos spark-Antwort hat nicht die Form, die dieses Tool kennt")
    err = sp.get("error")
    out = {}
    for item in sp.get("result") or []:
        resp = item.get("response") or []
        if not resp:
            continue
        ysym = item.get("symbol") or (resp[0].get("meta") or {}).get("symbol") or ""
        sym = (wanted or {}).get(ysym.upper(), markt.from_yahoo(ysym))
        out[sym] = series_from_result(resp[0])
    if err and not out:
        raise ScanError("Yahoo spark: %s" % (err.get("description") or err.get("code") or err))
    return out


def parse_chart(text_or_doc, sym=""):
    """v8 chart JSON -> series. Raises ScanError for Yahoo's 'no data' answers."""
    try:
        doc = json.loads(text_or_doc) if isinstance(text_or_doc, str) else text_or_doc
        chart = doc["chart"]
    except (ValueError, KeyError, TypeError):
        raise ScanError("Yahoo hat für %s etwas Unerwartetes geliefert" % sym)
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise ScanError("keine Daten für %s: %s" % (sym, err.get("description", "unbekanntes Symbol")))
    return series_from_result(res[0])


def _read_maybe_gz(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _stem(name):
    for ext in (".json.gz", ".json"):
        if name.endswith(ext):
            return name[:-len(ext)]
    return name


def _absorb(doc, name_hint, data, errors):
    """One parsed offline JSON doc -> data / errors."""
    if isinstance(doc, dict) and "spark" in doc:
        data.update(parse_spark(doc))
    elif isinstance(doc, dict) and "chart" in doc:
        sym = name_hint
        if not sym:
            try:
                sym = (doc["chart"].get("result") or [{}])[0]["meta"]["symbol"]
            except (AttributeError, KeyError, TypeError, IndexError):
                raise ScanError("ein Offline-v8-Chart ohne Symbol: nenn die Datei <SYMBOL>.json")
        sym = markt.from_yahoo(sym)
        try:
            data[sym] = parse_chart(doc, sym)
        except ScanError as e:
            errors[sym] = str(e)
    elif isinstance(doc, dict):
        for k, v in doc.items():
            _absorb(v, k, data, errors)
    else:
        raise ScanError("die Offline-Datei %s ist keine spark-Antwort, kein v8-Chart und kein Bündel" % name_hint)


def load_offline(path):
    """A folder of <T>.json(.gz) files or one file -> ({SYM: series}, {SYM: error})."""
    data, errors = {}, {}
    if os.path.isdir(path):
        names = sorted(f for f in os.listdir(path) if f.endswith((".json", ".json.gz")))
        if not names:
            raise ScanError("keine .json-Dateien in %s" % path)
        for f in names:
            try:
                doc = json.loads(_read_maybe_gz(os.path.join(path, f)))
            except ValueError as e:
                raise ScanError("%s ist kein gültiges JSON: %s" % (f, e))
            if isinstance(doc, dict) and ("chart" in doc or "spark" in doc):
                _absorb(doc, "" if "spark" in doc else _stem(f), data, errors)
            else:
                _absorb(doc, "", data, errors)
    elif os.path.isfile(path):
        try:
            doc = json.loads(_read_maybe_gz(path))
        except ValueError as e:
            raise ScanError("%s ist kein gültiges JSON: %s" % (path, e))
        _absorb(doc, "", data, errors)
    else:
        raise ScanError("keine Offline-Datei und kein Ordner unter %s" % path)
    return data, errors


# ---------------------------------------------------------------- universe: US

TICKER = re.compile(r"^[A-Z]{1,5}$|^[A-Z]{1,4}\.[A-Z]$")
ALWAYS_OUT = [
    ("warrant", re.compile(r"\bwarrants?\b")),
    ("unit or right", re.compile(r"\b(units?|rights?),? (each|that|entitling)\b|(?<!the )\brights? to\b")),
    ("note", re.compile(r"\b(notes?|etns?|debentures?)\b")),
    ("coupon", re.compile(r"%")),
    ("depositary", re.compile(r"(?<!american )(?<!global )\bdepositary shares?\b")),
]
COMMON = re.compile(
    r"\bcommon (stock|shares?|units?)\b|\bord(inary)? shares?\b|\bshares? of beneficial interest\b"
    r"|\b(american|global) deposit[ao]ry\b|\bads[s]?\b|\badrs?\b"
    r"|\b(limited partnership|partnership|trust) units?\b|\bl\.?p\.? units?\b"
    r"|\bunits? (of|representing)\b.*\b(limited partner|partnership|beneficial interest|limited liability)")
SOFT_OUT = [
    ("unit", re.compile(r"\bunits?\b")),
    ("right", re.compile(r"\brights?\b")),
    ("bond", re.compile(r"\bbonds?\b")),
    ("preferred", re.compile(r"\bpreferred\b|\bpreference\b")),
]


def classify(row):
    """One symbol-directory row -> 'keep' or the rule that drops it."""
    sym = (row.get("Symbol") or row.get("ACT Symbol") or "").strip()
    if (row.get("Test Issue") or "").strip() != "N":
        return "test issue"
    if (row.get("ETF") or "").strip() != "N":
        return "ETF"
    if (row.get("NextShares") or "N").strip() != "N":
        return "NextShares"
    if not TICKER.match(sym):
        return "not a plain ticker"
    if re.search(r"\.[UWR]$", sym):
        return "unit / warrant / right suffix"
    name = " ".join((row.get("Security Name") or "").lower().split())
    for tag, rx in ALWAYS_OUT:
        if rx.search(name):
            return tag
    if COMMON.search(name):
        return "keep"
    for tag, rx in SOFT_OUT:
        if rx.search(name):
            return tag
    return "keep"


def parse_symdir(text):
    """Nasdaq Trader pipe file -> (rows, file_created). The last line is 'File Creation Time: ...'."""
    lines = [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]
    if not lines or "|" not in lines[0]:
        raise ScanError("kein Nasdaq-Trader-Symbolverzeichnis")
    hdr = [h.strip() for h in lines[0].split("|")]
    if "Security Name" not in hdr or not ({"Symbol", "ACT Symbol"} & set(hdr)):
        raise ScanError("kein Nasdaq-Trader-Symbolverzeichnis (Kopfzeile %s)" % lines[0][:60])
    rows, created = [], None
    for ln in lines[1:]:
        if ln.startswith("File Creation Time"):
            m = re.search(r"(\d{2})(\d{2})(\d{4})(\d{2}):(\d{2})", ln)
            if m:
                created = "%s-%s-%s %s:%s" % (m.group(3), m.group(1), m.group(2), m.group(4), m.group(5))
            continue
        rows.append(dict(zip(hdr, ln.split("|"))))
    return rows, created


def build_universe(texts):
    """{filename: text} -> (kept [(SYM, name)], counts, created)."""
    kept, counts, created = {}, {}, None
    for fname in NASDAQ_FILES:
        if fname not in texts:
            raise ScanError("%s fehlt" % fname)
        rows, c = parse_symdir(texts[fname])
        created = created or c
        counts["rows"] = counts.get("rows", 0) + len(rows)
        for r in rows:
            why = classify(r)
            counts[why] = counts.get(why, 0) + 1
            if why == "keep":
                sym = (r.get("Symbol") or r.get("ACT Symbol")).strip()
                kept[sym] = " ".join((r.get("Security Name") or "").split())
    return sorted(kept.items()), counts, created


# ---------------------------------------------------------------- universe: XETRA

XETRA_COLUMNS = ("Instrument", "ISIN", "Mnemonic", "Instrument Type", "Instrument Status",
                 "Product Assignment Group Description")


def parse_xetra(text):
    """Deutsche-Börse-CSV (Semikolon, Kopfzeilen 'Market:;XETR' und 'Date Last Update:;28.10.2026')
    -> (rows, list_date oder None)."""
    lines = text.lstrip("\ufeff").replace("\r", "").split("\n")
    head, meta = None, {}
    for i, ln in enumerate(lines[:20]):
        cells = [c.strip() for c in ln.split(";")]
        if "Mnemonic" in cells and "ISIN" in cells:
            head = i
            break
        if len(cells) >= 2 and cells[0].endswith(":"):
            meta[cells[0][:-1].strip().lower()] = cells[1]
    if head is None:
        raise ScanError("keine Deutsche-Börse-Liste (T7 XETR All tradable instruments): Kopfzeile mit "
                        "Mnemonic und ISIN fehlt")
    rows = list(csv.DictReader(lines[head:], delimiter=";"))
    missing = [c for c in XETRA_COLUMNS if rows and c not in rows[0]]
    if missing:
        raise ScanError("der Deutsche-Börse-Liste fehlen Spalten: %s" % ", ".join(missing))
    listed = None
    try:
        listed = datetime.datetime.strptime(meta.get("date last update", ""), "%d.%m.%Y").date()
    except ValueError:
        pass
    return rows, listed


def split_groups(text):
    return [g.strip().upper() for g in re.split(r"[,;]", text or "") if g.strip()]


def build_xetra_universe(rows, groups=None):
    """rows -> (kept [(SYM, Name, ISIN, Gruppe)], counts). Aktien = Instrument Type CS, Status Active.
    groups filtert nach Product Assignment Group Description (Groß-/Kleinschreibung egal)."""
    stocks, dropped, all_groups = {}, {}, {}
    for r in rows:
        kind = (r.get("Instrument Type") or "").strip() or "ohne Typ"
        if kind != "CS":
            dropped[kind] = dropped.get(kind, 0) + 1
            continue
        if (r.get("Instrument Status") or "").strip() != "Active":
            dropped["nicht aktiv"] = dropped.get("nicht aktiv", 0) + 1
            continue
        mnemonic = (r.get("Mnemonic") or "").strip().upper()
        if not mnemonic:
            dropped["ohne Mnemonic"] = dropped.get("ohne Mnemonic", 0) + 1
            continue
        sym = mnemonic + ".DE"
        if sym in stocks:
            dropped["doppelt"] = dropped.get("doppelt", 0) + 1
            continue
        group = " ".join((r.get("Product Assignment Group Description") or "").split()).upper()
        name = " ".join((r.get("Instrument") or "").split()).replace("|", "/")
        stocks[sym] = (sym, name, (r.get("ISIN") or "").strip(), group)
        all_groups[group] = all_groups.get(group, 0) + 1
    want = [g.upper() for g in groups or []]
    unknown = [g for g in want if g not in all_groups]
    if unknown:
        raise ScanError("Gruppe %s gibt es in der Liste nicht. Vorhanden: %s" % (
            ", ".join("„%s“" % g for g in unknown), ", ".join(sorted(all_groups))))
    kept = sorted(v for v in stocks.values() if not want or v[3] in want)
    per = {}
    for k in kept:
        per[k[3]] = per.get(k[3], 0) + 1
    return kept, {"rows": len(rows), "stocks": len(stocks), "kept": len(kept), "groups": per,
                  "dropped": dropped}


# ---------------------------------------------------------------- daily setups

def rsi(closes, n=14):
    """Wilder's RSI on closes (the same math as the reel's refs/scan.py)."""
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def daily_closes(series, now_utc):
    """[(date, close)] of COMPLETE daily bars: null closes dropped, today's bar dropped
    until the session closes, anything dated after the clock dropped."""
    now = markt.to_local(now_utc)
    today = now.date()
    s = markt.session(today)
    today_done = s is None or now.time() >= s[1]
    out = {}
    for ts, c in zip(series["t"], series["c"]):
        if c is None:
            continue
        d = markt.ts_to_local(ts).date()
        if d > today or (d == today and not today_done):
            continue
        out[d] = float(c)  # one bar a day: a late duplicate (the live tick) wins
    return sorted(out.items())


def find_setups(closes):
    """closes (oldest first, >= 30) -> (setup keys, numbers)."""
    c = closes
    last = c[-1]
    hi20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi(c)
    r_prev = rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    return tags, {"rsi": r, "rsi_prev": r_prev, "high20": hi20, "ma20": ma20,
                  "run_pct": run * 100, "range5_pct": rng5 * 100}


def scan_daily(data, symbols, now_utc, min_price, min_volume):
    """Pure. data = {SYM: series}. Returns (hits, counts, last_date)."""
    hits, dates = [], {}
    counts = {"requested": len(symbols), "fetched": 0, "illiquid": 0, "short": 0, "scanned": 0}
    for sym in symbols:
        s = data.get(sym)
        if not s:
            continue
        counts["fetched"] += 1
        bars = daily_closes(s, now_utc)
        meta = s.get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None and bars:
            price = bars[-1][1]
        vol = meta.get("regularMarketVolume")
        if price is None or price < min_price or (min_volume > 0 and (vol is None or vol < min_volume)):
            counts["illiquid"] += 1
            continue
        if len(bars) < MIN_DAILY_BARS:
            counts["short"] += 1
            continue
        counts["scanned"] += 1
        d_last = bars[-1][0]
        dates[d_last] = dates.get(d_last, 0) + 1
        closes = [c for _, c in bars]
        tags, nums = find_setups(closes)
        if tags:
            hits.append({"symbol": sym, "setups": tags, "price": round(closes[-1], 2),
                         "close_date": d_last.isoformat(), "rsi": round(nums["rsi"], 1),
                         "volume": int(vol) if vol is not None else None})
    hits.sort(key=lambda h: (-(h["price"] * (h["volume"] or 0)), h["symbol"]))  # most money traded first
    last_date = max(dates, key=lambda d: (dates[d], d)) if dates else None
    counts["hits"] = len(hits)
    return hits, counts, last_date


# ---------------------------------------------------------------- opening-range breakout

def slot(day, k):
    return datetime.datetime.combine(day, markt.info()["open"]) + datetime.timedelta(minutes=BAR_MIN * k)


def session_bars(series, day, cutoff):
    """5-minute bars of `day` that are complete at `cutoff` (naive local market time),
    on the grid, with a close. Sorted, one per slot."""
    s = markt.session(day)
    open_t = markt.info()["open"]
    close_t = s[1] if s else markt.info()["close"]
    out = {}
    hs, ls = series.get("h"), series.get("l")
    for i, ts in enumerate(series["t"]):
        c = series["c"][i]
        if c is None:
            continue
        lt = markt.ts_to_local(ts)
        if lt.date() != day or lt.second or lt.minute % BAR_MIN:
            continue  # another day, or the live tick off the grid
        if lt.time() < open_t or lt.time() >= close_t:
            continue  # pre-market, after hours, the closing print
        if lt + datetime.timedelta(minutes=BAR_MIN) > cutoff:
            continue  # still in progress at the cutoff
        v = series.get("v")
        out[lt] = {"start": lt, "c": float(c),
                   "h": None if not hs or hs[i] is None else float(hs[i]),
                   "l": None if not ls or ls[i] is None else float(ls[i]),
                   "v": (v[i] or 0) if v else 0}
    return [out[k] for k in sorted(out)]


def usable(bars, day, cutoff, n_range):
    """Every slot from the open to the cutoff is there, and at least the range."""
    want = int((cutoff - slot(day, 0)).total_seconds() // (BAR_MIN * 60))
    s = markt.session(day)
    if s:
        want = min(want, int((datetime.datetime.combine(day, s[1]) - slot(day, 0)).total_seconds()
                             // (BAR_MIN * 60)))
    if want < n_range or len(bars) != want:
        return False
    return all(b["start"] == slot(day, k) for k, b in enumerate(bars))


def latest_bar_end(data, day, cutoff):
    """Ende der letzten fertigen Kerze von `day` bis `cutoff` über alle Charts, oder None."""
    best = None
    for s in data.values():
        bars = session_bars(s, day, cutoff)
        if bars:
            end = bars[-1]["start"] + datetime.timedelta(minutes=BAR_MIN)
            if best is None or end > best:
                best = end
    return best


def orb_candidate(bars, n_range):
    """Stage 1, closes only: some completed bar after the range closed at or above
    the highest close of the range. Necessary for a breakout (range high >= any range close)."""
    top = max(b["c"] for b in bars[:n_range])
    return any(b["c"] >= top for b in bars[n_range:])


def orb_hit(bars, n_range):
    """Stage 2, real highs and lows: the first completed bar to CLOSE above the range high."""
    rng = bars[:n_range]
    if any(b["h"] is None or b["l"] is None for b in rng):
        return None
    oh = max(b["h"] for b in rng)
    ol = min(b["l"] for b in rng)
    for k in range(n_range, len(bars)):
        b = bars[k]
        if b["c"] > oh:
            closes_at = b["start"] + datetime.timedelta(minutes=BAR_MIN)
            return {"price": round(b["c"], 2), "at": markt.clock_label(closes_at),
                    "bar_start": b["start"].strftime("%H:%M"), "bar_index": k,
                    "or_high": round(oh, 2), "or_low": round(ol, 2),
                    "pct_over": round((b["c"] / oh - 1) * 100, 2), "_t": closes_at}
    return None


def first_close(day, or_minutes):
    return slot(day, or_minutes // BAR_MIN) + datetime.timedelta(minutes=BAR_MIN)


def orb_window(now_utc, at, or_minutes, until, explicit_day=None):
    """-> (day, cutoff in naive local market time) or raise ScanError with the plain message."""
    lbl = markt.clock_label
    now = markt.to_local(now_utc)
    day = explicit_day or now.date()
    if or_minutes < BAR_MIN or or_minutes % BAR_MIN or or_minutes > 120:
        raise ScanError("--or-minutes erwartet ein Vielfaches von 5 zwischen 5 und 120 (15 ist der Klassiker)")
    ok, why = markt.trading_day(day)
    if not ok:
        raise ScanError("Kein Handel am %s (%s): die Börse ist geschlossen. Starte orb an einem Handelstag nach "
                        "der Opening Range oder spiel einen vergangenen Tag mit --offline nach."
                        % (markt.day_label(day), why))
    s = markt.session(day)
    range_end = slot(day, or_minutes // BAR_MIN)
    fc = first_close(day, or_minutes)
    close_dt = datetime.datetime.combine(day, s[1])
    if at is not None:
        cutoff = datetime.datetime.combine(day, at)
        if explicit_day is None and cutoff > now + datetime.timedelta(seconds=59):
            raise ScanError("--at %s liegt nach der aktuellen Zeit (%s)." % (markt.clock(at), lbl(now)))
        if cutoff > close_dt:
            raise ScanError("--at %s liegt nach Handelsschluss um %s am %s."
                            % (markt.clock(at), lbl(close_dt), markt.day_label(day)))
    else:
        cutoff = now.replace(second=0, microsecond=0)
        if cutoff >= close_dt:
            raise ScanError("Der Handel hat am %s um %s geschlossen. Spiel die Sitzung mit --at 10:15 nach."
                            % (markt.day_label(day), lbl(close_dt)))
    if cutoff < fc:
        raise ScanError("Es ist %s, zu früh: die %d-Minuten-Opening-Range läuft von %s bis %s, die erste Kerze "
                        "danach schließt um %s. Starte orb nach %s wieder."
                        % (lbl(cutoff), or_minutes, markt.clock(slot(day, 0)), lbl(range_end), lbl(fc), lbl(fc)))
    if until is not None and cutoff.time() > until:
        raise ScanError("Es ist %s, nach %s, deiner letzten Zeit für neue Einstiege (no_entries_after): ein "
                        "Opening-Range-Breakout, der jetzt auftaucht, ist abgelaufen. Starte orb am nächsten "
                        "Handelstag nach %s oder spiel heute mit --at 10:15 nach."
                        % (lbl(cutoff), markt.clock(until), lbl(fc)))
    return day, cutoff


def scan_orb(stage1, symbols, day, cutoff, or_minutes, min_price=0.0, min_volume=0, confirm=None,
             max_confirm=None):
    """stage1 = {SYM: series} with closes (spark or v8). confirm(sym) -> series with highs/lows
    (None = use the stage-1 series). With confirm and max_confirm, only the max_confirm most
    traded candidates (price x volume so far) are confirmed; the rest are counted as unconfirmed.
    Returns (hits, counts, failed {sym: why})."""
    n_range = or_minutes // BAR_MIN
    counts = {"requested": len(symbols), "fetched": 0, "unusable": 0, "illiquid": 0, "scanned": 0,
              "candidates": 0, "confirmed": 0, "unconfirmed": 0}
    hits, failed, cands = [], {}, []
    for sym in symbols:
        s = stage1.get(sym)
        if not s:
            continue
        counts["fetched"] += 1
        bars = session_bars(s, day, cutoff)
        if not usable(bars, day, cutoff, n_range):
            counts["unusable"] += 1
            continue
        vol = sum(b["v"] for b in bars) if s.get("v") else (s.get("meta") or {}).get("regularMarketVolume") or 0
        if bars[-1]["c"] < min_price or vol < min_volume:
            counts["illiquid"] += 1
            continue
        counts["scanned"] += 1
        if orb_candidate(bars, n_range):
            cands.append((sym, bars, bars[-1]["c"] * vol))
    counts["candidates"] = len(cands)
    if confirm is not None and max_confirm and len(cands) > max_confirm:
        cands.sort(key=lambda x: -x[2])
        counts["unconfirmed"] = len(cands) - max_confirm
        cands = cands[:max_confirm]
    for sym, bars, _ in cands:
        full = bars
        if confirm is not None:
            try:
                s2 = confirm(sym)
            except ScanError as e:
                failed[sym] = str(e)
                continue
            full = session_bars(s2, day, cutoff)
            if not usable(full, day, cutoff, n_range):
                failed[sym] = "dem v8-Chart fehlt eine Kerze"
                continue
        counts["confirmed"] += 1
        h = orb_hit(full, n_range)
        if h:
            hits.append(dict({"symbol": sym, "setups": ["orb"]}, **h))
    hits.sort(key=lambda x: (x["_t"], x["symbol"]))
    for h in hits:
        del h["_t"]
    counts["hits"] = len(hits)
    return hits, counts, failed


# ---------------------------------------------------------------- fetching

def progress(a, msg):
    if not getattr(a, "json", False) and not getattr(a, "quiet", False):
        print(msg, file=sys.stderr)


def fetch_spark(symbols, rng, interval, pause, a=None):
    """Batches of 20. -> ({SYM: series}, {SYM: error})."""
    data, failed = {}, {}
    batches = [symbols[i:i + SPARK_MAX] for i in range(0, len(symbols), SPARK_MAX)]
    for k, batch in enumerate(batches):
        if k and pause:
            SLEEP(pause)
        wanted = {to_yahoo(s): s for s in batch}
        try:
            got = parse_spark(yahoo_get(spark_path(batch, rng, interval)), wanted)
        except (ScanError, ValueError) as e:
            for s in batch:
                failed[s] = str(e)
            continue
        for s in batch:
            if s in got:
                data[s] = got[s]
            else:
                failed[s] = "keine Daten von Yahoo"
        if a is not None and len(batches) > 25 and (k + 1) % 50 == 0:
            progress(a, "  spark: %d von %d Anfragen" % (k + 1, len(batches)))
    return data, failed


def read_symbols(a, offline_syms=None):
    if a.symbols:
        syms = [s for s in re.split(r"[,\s]+", a.symbols.upper()) if s]
    elif a.watchlist:
        syms = symbols_from_file(a.watchlist)
    elif offline_syms is not None and not a.universe:
        syms = sorted(offline_syms)  # offline: every chart in the file, unless a list was given
    else:
        path = a.universe or DEFAULT_UNIVERSE
        if not os.path.exists(path):
            raise ScanError("noch keine %s: starte zuerst `scan.py universe` oder gib --symbols an" % path)
        syms = symbols_from_file(path)
    out = []
    for s in syms:
        if s not in out:
            out.append(s)
    if a.limit:
        out = out[:a.limit]
    if not out:
        raise ScanError("keine Symbole zum Scannen")
    return out


def symbols_from_file(path):
    if not os.path.exists(path):
        raise ScanError("keine Datei unter %s" % path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if text.lstrip().startswith(("{", "[")):
        try:
            doc = json.loads(text)
        except ValueError as e:
            raise ScanError("%s ist kein gültiges JSON: %s" % (path, e))
        items = doc.get("hits", []) if isinstance(doc, dict) else doc
        return [str(x.get("symbol") if isinstance(x, dict) else x).upper() for x in items if x]
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln.split("|")[0].strip().upper())
    return out


def pick_market(flag, symbols, cfg):
    """--market, sonst der Markt der Symbole (alle aus einem Markt), sonst config, sonst XETRA."""
    by = {}
    for s in symbols or ():
        by.setdefault(markt.market_of(s), []).append(s)
    try:
        if flag:
            m = markt.norm(flag)
            other = [s for s in symbols or () if markt.market_of(s) != m]
            if other:
                raise ScanError("--market %s passt nicht zu %s (%s). Lass --market weg oder scanne eine Liste "
                                "aus einem Markt." % (m, ", ".join(other[:3]), markt.info(markt.market_of(other[0]))
                                                      ["name"]))
            return m
        if len(by) > 1:
            raise ScanError("die Liste mischt Märkte: %s (XETRA) und %s (US). Ein Scan läuft auf einem Markt: "
                            "scanne XETRA- und US-Werte getrennt, mit je einer Liste."
                            % (", ".join(by["xetra"][:3]), ", ".join(by["us"][:3])))
        if by:
            return list(by)[0]
        return markt.resolve(cfg=cfg)
    except markt.MarketError as e:
        raise ScanError(str(e))


def apply_liquidity(a, cmd, m):
    price, volume = LIQUIDITY[cmd][m]
    if a.min_price is None:
        a.min_price = price
    if a.min_volume is None:
        a.min_volume = volume


def read_config(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except ValueError as e:
        raise ScanError("%s ist kein gültiges JSON: %s" % (path, e))
    return cfg if isinstance(cfg, dict) else {}


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def write_lines(path, lines):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(ln + "\n")


def plural(n, one, many):
    return one if n == 1 else many


# ---------------------------------------------------------------- commands

def cmd_universe(a):
    try:
        m = markt.norm(a.market) if a.market else markt.resolve(cfg=read_config(a.config))
    except markt.MarketError as e:
        raise ScanError(str(e))
    markt.use(m)
    if m == "xetra":
        return universe_xetra(a)
    if a.gruppen or a.nur_deutschland:
        raise ScanError("--gruppen und --nur-deutschland gibt es nur für --market xetra")
    return universe_us(a)


def universe_xetra(a):
    t0 = time.time()
    groups = split_groups(a.gruppen)
    if a.nur_deutschland:
        groups += [g for g in GERMAN_GROUPS if g not in groups]
    if a.offline:
        path = a.offline
        if os.path.isdir(path):
            path = os.path.join(path, XETRA_FILE)
        if not os.path.isfile(path):
            raise ScanError("keine Deutsche-Börse-Liste unter %s" % path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    else:
        try:
            text = http_get(XETRA_URL, timeout=60)
        except urllib.error.HTTPError as e:
            raise ScanError("deutsche-boerse.com antwortete HTTP %d für %s" % (e.code, XETRA_FILE))
        except (urllib.error.URLError, OSError) as e:
            raise ScanError("deutsche-boerse.com ist nicht erreichbar: %s" % getattr(e, "reason", e))
    rows, listed = parse_xetra(text)
    kept, counts = build_xetra_universe(rows, groups)
    if not a.no_write:
        write_lines(a.out, ["|".join(k) for k in kept])
    per = sorted(counts["groups"].items(), key=lambda kv: (-kv[1], kv[0]))
    if a.json:
        print(json.dumps({"market": "xetra", "count": len(kept), "rows": counts["rows"],
                          "stocks": counts["stocks"], "list_date": listed.isoformat() if listed else None,
                          "filter": groups, "groups": dict(per), "dropped": counts["dropped"],
                          "out": None if a.no_write else a.out, "seconds": round(time.time() - t0, 1)},
                         indent=2, ensure_ascii=False))
        return 0 if kept else 1
    print("Deutsche-Börse-Liste „T7 (XETR) All tradable instruments“%s: %s Zeilen." % (
        (", Stand %s" % markt.date_de(listed)) if listed else "", num(counts["rows"])))
    dropped = sorted(counts["dropped"].items(), key=lambda kv: -kv[1])
    print("%s Aktien (Instrument Type CS, Status Active)%s." % (
        num(counts["stocks"]),
        ("; aussortiert: " + ", ".join("%s %s" % (num(v), k) for k, v in dropped)) if dropped else ""))
    if groups:
        print("Filter Gruppen %s: %s %s behalten." % (", ".join(groups), num(len(kept)),
                                                      plural(len(kept), "Aktie", "Aktien")))
    else:
        print("Behalten: alle %s Aktien." % num(len(kept)))
    print("Je Gruppe: " + ", ".join("%s %s" % (g or "ohne Gruppe", num(n)) for g, n in per) + ".")
    if not a.no_write:
        print("Geschrieben: %s (eine Zeile SYMBOL|Name|ISIN|Gruppe, Symbol = Mnemonic + .DE)." % a.out)
    return 0 if kept else 1


def universe_us(a):
    t0 = time.time()
    texts = {}
    for k, fname in enumerate(NASDAQ_FILES):
        if a.offline:
            p = os.path.join(a.offline, fname)
            if not os.path.exists(p):
                raise ScanError("keine %s in %s" % (fname, a.offline))
            with open(p, encoding="utf-8", errors="replace") as fh:
                texts[fname] = fh.read()
        else:
            if k and a.pause:
                SLEEP(a.pause)
            try:
                texts[fname] = http_get(NASDAQ_URL + fname, timeout=60)
            except urllib.error.HTTPError as e:
                raise ScanError("nasdaqtrader.com antwortete HTTP %d für %s" % (e.code, fname))
            except (urllib.error.URLError, OSError) as e:
                raise ScanError("nasdaqtrader.com ist nicht erreichbar: %s" % getattr(e, "reason", e))
    kept, counts, created = build_universe(texts)
    if not a.no_write:
        write_lines(a.out, ["%s|%s" % (sym, name) for sym, name in kept])
    dropped = {k: v for k, v in counts.items() if k not in ("keep", "rows")}
    if a.json:
        print(json.dumps({"market": "us", "count": len(kept), "rows": counts.get("rows", 0),
                          "files_created": created, "dropped": dropped, "out": None if a.no_write else a.out,
                          "seconds": round(time.time() - t0, 1)}, indent=2))
        return 0 if kept else 1
    when = ""
    if created:
        c = datetime.datetime.strptime(created, "%Y-%m-%d %H:%M")
        when = ", Dateien vom %s %s" % (markt.date_de(c), markt.clock_label(c))
    print("Nasdaq-Trader-Symbolverzeichnisse%s: %s Zeilen." % (when, num(counts.get("rows", 0))))
    print("Behalten: %s US-Aktien (Stammaktien, Ordinary Shares und ADRs)." % num(len(kept)))
    print("Aussortiert: " + ", ".join("%s %s" % (num(v), DROP_LABEL.get(k, k))
                                      for k, v in sorted(dropped.items(), key=lambda kv: -kv[1])) + ".")
    if not a.no_write:
        print("Geschrieben: %s (eine Zeile SYMBOL|Name)." % a.out)
    return 0 if kept else 1


def _prepare(a, cmd):
    """Offline-Daten, Symbole, Markt und Config. -> (cfg, data, failed, symbols)."""
    cfg = read_config(a.config)
    data = failed = None
    offline_syms = None
    if a.offline:
        data, failed = load_offline(a.offline)
        offline_syms = sorted(set(data) | set(failed))
    symbols = read_symbols(a, offline_syms)
    m = pick_market(a.market, symbols, cfg)
    markt.use(m)
    apply_liquidity(a, cmd, m)
    return cfg, data, failed, symbols


def cmd_daily(a):
    t0 = time.time()
    cfg, data, failed, symbols = _prepare(a, "daily")
    now = parse_now(a.now)
    mk = markt.info()
    if not a.offline:
        progress(a, "Lade Tagesschlusskurse für %s Symbole (%d spark-Anfragen) ..."
                 % (num(len(symbols)), (len(symbols) + SPARK_MAX - 1) // SPARK_MAX))
        data, failed = fetch_spark(symbols, "3mo", "1d", a.pause, a)
    hits, counts, last_date = scan_daily(data, symbols, now, a.min_price, a.min_volume)
    nfailed = len(symbols) - counts["fetched"]
    as_of = ("%s Schluss" % last_date.isoformat()) if last_date else None
    doc = {"created_by": "dt-scanner", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "daily",
           "market": mk["key"], "as_of": as_of, "universe": len(symbols), "scanned": counts["scanned"],
           "failed": nfailed, "source": "yahoo", "filters": {"min_price": a.min_price, "min_volume": a.min_volume},
           "note": NOTE, "hits": hits}
    if a.offline:
        doc["offline"] = os.path.basename(a.offline.rstrip("/"))
    if not a.no_write:
        write_json(a.out, doc)
    if a.json:
        print(json.dumps(dict(doc, counts=counts, seconds=round(time.time() - t0, 1)), indent=2,
                         ensure_ascii=False))
        return 0 if hits else 1
    local = markt.to_local(now)
    print("Tages-Scan %s, %s, Schlusskurse bis %s (Yahoo spark, nur Tagesschlusskurse)." % (
        mk["name"], "%s %s" % (markt.day_label(local.date()), markt.clock_both(local)),
        markt.date_de(last_date) if last_date else "nichts"))
    print("%s von %s Charts geladen%s. %s haben den Liquiditätsfilter bestanden (ab %s, %s)%s; "
          "%s gescannt." % (num(counts["fetched"]), num(len(symbols)),
                            (" (%s fehlgeschlagen oder ohne Daten)" % num(nfailed)) if nfailed else "",
                            num(counts["fetched"] - counts["illiquid"]), markt.money_short(a.min_price),
                            ("ab %s Stück" % num(a.min_volume)) if a.min_volume > 0 else "ohne Volumen-Schwelle",
                            (", %d mit weniger als %d Tagen" % (counts["short"], MIN_DAILY_BARS))
                            if counts["short"] else "", num(counts["scanned"])))
    s = markt.session(local.date())
    if s and s[0] <= local.time() < s[1] and a.min_volume > 0:
        print("Achtung: Die Sitzung läuft. Das Volumen in Yahoos Daten ist das von heute bis jetzt, nicht der "
              "ganze Tag; vor %s zählt der Vortag." % markt.clock_label(s[0]))
    if hits:
        per = [(k, sum(1 for h in hits if k in h["setups"])) for k, _ in SETUPS]
        print("%d %s ein Setup. %s." % (len(hits), plural(len(hits), "Chart erfüllt", "Charts erfüllen"),
                                         "; ".join("%s: %d" % (LABEL[k], n) for k, n in per if n)))
        print("Meistgehandelte zuerst (Preis mal Volumen):")
    else:
        print("Keine Setups.")
    for h in hits[:a.show]:
        print("  %-8s %11s  RSI %5s  %s" % (h["symbol"], markt.money(h["price"]), markt.num(h["rsi"], 1),
                                            ", ".join(LABEL[t] for t in h["setups"])))
    if len(hits) > a.show:
        print("  ... und %d weitere in der Watchlist (--show N für mehr)." % (len(hits) - a.show))
    if not a.no_write:
        print("Geschrieben: %s (Modus daily, %d Treffer)." % (a.out, len(hits)))
    if mk["key"] == "xetra":
        print(DELAY_NOTE)
    print(NOTE + " Nächster Schritt: such dir einen Chart aus, dann /dt-news SYMBOL.")
    return 0 if hits else 1


def cmd_orb(a):
    t0 = time.time()
    cfg, data, failed, symbols = _prepare(a, "orb")
    mk = markt.info()
    now = parse_now(a.now)
    at = parse_hhmm(a.at) if a.at else None
    until = parse_hhmm(a.until or markt.windows(cfg)["no_entries_after"], "--until")
    explicit_day = None
    if a.offline and not a.now:
        days = [markt.ts_to_local(s["t"][-1]).date() for s in data.values() if s["t"]]
        if days:
            explicit_day = max(days)
            if at is None:
                raise ScanError("Offline-Wiederholung: gib --at HH:MM oder --now \"JJJJ-MM-TT HH:MM\" an")
    day, cutoff = orb_window(now, at, a.or_minutes, until, explicit_day)
    confirm = None
    if not a.offline:
        today = markt.to_local(parse_now(None)).date()
        if (today - day).days > 6:
            raise ScanError("Yahoos kostenlose 5-Minuten-Historie ist kurz: spiel den %s mit --offline nach"
                            % markt.date_de(day))
        rng = "1d" if day == today else "5d"
        progress(a, "Stufe 1: 5-Minuten-Schlusskurse für %s Symbole (%d spark-Anfragen) ..."
                 % (num(len(symbols)), (len(symbols) + SPARK_MAX - 1) // SPARK_MAX))
        data, failed = fetch_spark(symbols, rng, "%dm" % BAR_MIN, a.pause, a)
        done = []

        def confirm(sym):
            if a.pause:
                SLEEP(a.pause)
            done.append(sym)
            if len(done) % 50 == 0:
                progress(a, "  Stufe 2: bisher %d v8-Charts" % len(done))
            return parse_chart(yahoo_get(chart_path(sym, rng, "%dm" % BAR_MIN)), sym)
    asked = cutoff
    latest = latest_bar_end(data, day, cutoff)
    if latest is not None and cutoff - latest >= datetime.timedelta(minutes=BAR_MIN):
        cutoff = latest
        if cutoff < first_close(day, a.or_minutes):
            raise ScanError("Die Daten reichen erst bis %s (Yahoo liefert %s-Kerzen ca. 15 Minuten verzögert): "
                            "die erste Kerze nach der Opening Range schließt um %s. Starte orb in ein paar "
                            "Minuten wieder." % (markt.clock_label(cutoff), mk["name"],
                                                  markt.clock_label(first_close(day, a.or_minutes))))
    hits, counts, failed2 = scan_orb(data, symbols, day, cutoff, a.or_minutes, a.min_price, a.min_volume, confirm,
                                     a.max_confirm)
    failed = dict(failed or {})
    failed.update(failed2)
    nfailed = len([s for s in symbols if s in failed])
    as_of = "%s %s" % (day.isoformat(), markt.clock_label(cutoff))
    doc = {"created_by": "dt-scanner", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "orb",
           "market": mk["key"], "as_of": as_of, "universe": len(symbols), "scanned": counts["scanned"],
           "failed": nfailed, "unconfirmed": counts["unconfirmed"], "source": "yahoo", "or_minutes": a.or_minutes,
           "interval": "%dm" % BAR_MIN,
           "filters": {"min_price": a.min_price, "min_volume": a.min_volume}, "note": NOTE, "hits": hits}
    if a.offline:
        doc["offline"] = os.path.basename(a.offline.rstrip("/"))
    if not a.no_write:
        write_json(a.out, doc)
    if a.json:
        print(json.dumps(dict(doc, counts=counts, seconds=round(time.time() - t0, 1)), indent=2,
                         ensure_ascii=False))
        return 0 if hits else 1
    print("Opening-Range-Breakout-Scan %s, %s %s: %d-Minuten-Range (%s bis %s), 5-Minuten-Kerzen, Yahoo."
          % (mk["name"], markt.day_label(day), markt.clock_both(cutoff), a.or_minutes,
             markt.clock(slot(day, 0)), markt.clock_label(slot(day, a.or_minutes // BAR_MIN))))
    if cutoff != asked:
        print("Die letzte fertige Kerze in den Daten endet um %s; der Scan läuft bis dahin statt bis %s."
              % (markt.clock_label(cutoff), markt.clock_label(asked)))
    print("%s von %s Charts geladen%s; %s nutzbar%s; %s %s, %s mit echten Hochs und Tiefs bestätigt."
          % (num(counts["fetched"]), num(len(symbols)),
             (" (%s fehlgeschlagen oder ohne Daten)" % num(nfailed)) if nfailed else "",
             num(counts["scanned"]),
             (" (%s unter der Preis-/Volumen-Schwelle)" % num(counts["illiquid"])) if counts["illiquid"] else "",
             num(counts["candidates"]), plural(counts["candidates"], "Kandidat", "Kandidaten"),
             num(counts["confirmed"])))
    if counts["unconfirmed"]:
        print("TEILERGEBNIS: %s weitere Kandidaten wurden nicht geprüft (nur die %s meistgehandelten; "
              "--max-confirm 0 prüft alle)." % (num(counts["unconfirmed"]), num(a.max_confirm)))
    if hits:
        base = ("der %s geprüften" % num(counts["confirmed"])) if counts["unconfirmed"] else \
            ("von %s" % num(counts["scanned"]))
        print("%d %s Charts %s bis %s über ihrem Opening-Range-Hoch geschlossen:"
              % (len(hits), base, plural(len(hits), "hat", "haben"), markt.clock_both(cutoff)))
        for h in hits[:a.show]:
            print("  %-9s  %-8s %11s  Range %s bis %s  %s drüber" % (
                h["at"], h["symbol"], markt.money(h["price"]), markt.num(h["or_low"]), markt.num(h["or_high"]),
                markt.pct(h["pct_over"], sign=True)))
        if len(hits) > a.show:
            print("  ... und %d weitere in der Watchlist (--show N für mehr)." % (len(hits) - a.show))
    else:
        print("Kein Chart hat bis %s über seinem Opening-Range-Hoch geschlossen." % markt.clock_both(cutoff))
    if not a.no_write:
        print("Geschrieben: %s (Modus orb, %d Treffer)." % (a.out, len(hits)))
    if mk["key"] == "xetra":
        print(DELAY_NOTE)
    print(NOTE + " Nächster Schritt: such dir einen Chart aus, dann /dt-news SYMBOL und /dt-einstieg SYMBOL.")
    return 0 if hits else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chart-Scanner (dt-scanner): Tages-Setups und Opening-Range-Breakouts "
                                             "für XETRA und US.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("universe", help="Aktienliste laden -> trader/universe.txt")
    p.add_argument("--market", help="xetra (Standard: Deutsche-Börse-Liste) oder us (Nasdaq-Trader-Listen)")
    p.add_argument("--gruppen", help="nur diese Gruppen, z. B. DAX,MDAX,SDAX,DEUTSCHLAND (nur XETRA)")
    p.add_argument("--nur-deutschland", action="store_true", help="Abkürzung für DAX, MDAX, SDAX, DEUTSCHLAND")
    p.add_argument("--out", default=DEFAULT_UNIVERSE)
    p.add_argument("--offline", metavar="PFAD",
                   help="XETRA: die CSV der Deutschen Börse; US: Ordner mit nasdaqlisted.txt und otherlisted.txt")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--pause", type=float, default=PAUSE)
    p.add_argument("--json", action="store_true")

    def common(p):
        g = p.add_mutually_exclusive_group()
        g.add_argument("--symbols", help="Symbole mit Komma statt des Universums (SAP.DE,BMW.DE oder TSLA,NVDA)")
        g.add_argument("--watchlist", metavar="DATEI", help="eine watchlist.json (hits) oder eine Textdatei mit Symbolen")
        p.add_argument("--universe", help="Symbolliste, eine Zeile SYMBOL|... (Standard %s)" % DEFAULT_UNIVERSE)
        p.add_argument("--market", help="xetra oder us (Standard: aus den Symbolen, dann config, dann xetra)")
        p.add_argument("--limit", type=int, help="nur die ersten N Symbole scannen")
        p.add_argument("--min-price", type=float, default=None, help="Mindestkurs (Standard 5)")
        p.add_argument("--min-volume", type=int, default=None, help="Mindestvolumen in Stück")
        p.add_argument("--offline", metavar="PFAD", help="Fixture-Ordner oder -Datei statt des Netzes")
        p.add_argument("--now", help='so tun, als wäre es jetzt ("2026-10-27 10:15" Ortszeit des Marktes, oder ...Z)')
        p.add_argument("--out", default="trader/watchlist.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--no-write", action="store_true")
        p.add_argument("--pause", type=float, default=PAUSE, help="Sekunden zwischen Anfragen (%.1f)" % PAUSE)
        p.add_argument("--show", type=int, default=50, help="so viele Treffer anzeigen (geschrieben werden alle)")
        p.add_argument("--quiet", action="store_true")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("daily", help="vorbörsliche Setups aus Tagesschlusskursen")
    common(p)
    p = sub.add_parser("orb", help="Opening-Range-Breakouts bis jetzt")
    common(p)
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--max-confirm", type=int, default=MAX_CONFIRM,
                   help="v8-Charts in Stufe 2, meistgehandelte zuerst (%d; 0 = alle)" % MAX_CONFIRM)
    p.add_argument("--at", help="die Uhr auf diese Ortszeit stellen, HH:MM")
    p.add_argument("--until", help="keine neuen Einstiege nach HH:MM (Standard: no_entries_after, XETRA 17:00, US 15:30)")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    with markt.restore():
        try:
            return {"universe": cmd_universe, "daily": cmd_daily, "orb": cmd_orb}[a.cmd](a)
        except (ScanError, markt.MarketError) as e:
            print("scan.py: %s" % e, file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("scan.py: abgebrochen", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
