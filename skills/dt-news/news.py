#!/usr/bin/env python3
"""News-Monitor für dt-news. Nur Standardbibliothek.

Beobachtet Schlagzeilen, Ad-hoc-Mitteilungen und SEC-Meldungen zu den Aktien,
die du beobachtest oder hältst, und zeigt nur, was seit dem letzten Lauf neu
ist: Ad-hoc-Mitteilungen oben, sonst das Neueste zuerst, dazu die Tagesbewegung
je Aktie und eine Markierung, welche deiner Ticker eine Meldung betrifft.

    python3 news.py                                    # Watchlist + Plan + Depot
    python3 news.py --tickers SAP.DE BMW.DE TSLA
    python3 news.py --tickers SAP.DE --all --hours 72  # alles der letzten 3 Tage, auch Gesehenes
    python3 news.py --alle-adhoc --hours 12            # alle Ad-hoc-Mitteilungen, ohne Ticker-Filter
    python3 news.py --no-sec                           # ohne SEC-Meldungen
    python3 news.py --no-moves                         # ohne Kurszeile je Ticker

Deine Ticker, wenn --tickers fehlt: alle Treffer in trader/watchlist.json
(dt-scanner), das Symbol in trader/plan.json (dt-ausstieg) und die Positionen
in trader/portfolio.json. Ticker mit .DE gehören zu XETRA, alle anderen zu US.

Quellen, je eine Anfrage pro Feed und Ticker:
  - Yahoo-Finance-Schlagzeilen (RSS), für .DE auf Deutsch:
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=SAP.DE&region=DE&lang=de-DE
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=TSLA&region=US&lang=en-US
  - XETRA: Ad-hoc-Mitteilungen (Art. 17 MAR) und Corporate News aus dem Atom-Feed
    https://www.ad-hoc-news.de/rss/adhocnews.xml, zugeordnet über ISIN oder
    Emittentenname (aus trader/universe.txt oder --isin/--name). Der Feed schreibt
    +02:00 auch in der Winterzeit; der Offset wird wörtlich genommen und die Zeit
    als „laut Feed“ markiert.
  - US: SEC-EDGAR-Meldungen der Firma (Standard 8-K). Die SEC verlangt einen
    User-Agent mit Name und E-Mail (sec_user_agent in trader/config.json oder
    SEC_USER_AGENT). Ohne ihn fällt der SEC-Teil weg, mit Hinweis.
  - Die Bewegung: Yahoo-Chart (inoffiziell, kann verzögert sein), letzter Kurs
    gegen den Vortagesschluss:
    https://query2.finance.yahoo.com/v8/finance/chart/<TICKER>?range=1d&interval=5m

Zeiten stehen in der Ortszeit des Marktes des Tickers (XETRA „08:04 Uhr“,
US „08:04 ET (13:04 Uhr)“). Zustand: trader/state/news.json merkt sich, was du
gesehen hast (30 Tage), damit jede Meldung nur einmal erscheint. Offline:
--offline DIR liest yahoo-<TICKER>.xml, chart-<TICKER>.json, sec-<FORM>-<CIK>.xml,
company_tickers.json und adhocnews.xml aus DIR. Die Tests nutzen das.

Schlagzeilen sind Hinweise, keine Fakten: lies die Meldung, bevor du handelst.
Keine Anlageberatung.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US"
YAHOO_DE = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=DE&lang=de-DE"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
SEC_FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=%s&type=%s"
            "&dateb=&owner=include&count=%d&output=atom")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
ADHOC_FEED = "https://www.ad-hoc-news.de/rss/adhocnews.xml"
ADHOC_FILE = "adhocnews.xml"
PLACEHOLDERS = ("you@example.com", "du@example.com")
BROWSER_UA = "Mozilla/5.0 (compatible; daytrader-skill/1.0; +https://thanisch.co)"
KEEP_DAYS = 30
MOVE_PCT = 3.0  # ab so viel Abstand zum Vortagesschluss gilt eine Aktie als bewegt

ITEMS_8K = {
    "1.01": "wesentlicher Vertrag", "1.02": "Vertrag beendet", "1.03": "Insolvenz",
    "1.05": "Cybersicherheitsvorfall", "2.01": "Kauf oder Verkauf von Vermögenswerten",
    "2.02": "Geschäftszahlen", "2.03": "neue Schulden", "2.04": "Fälligstellung von Schulden",
    "2.05": "Restrukturierungskosten", "2.06": "Wertminderung", "3.01": "Delisting-Hinweis",
    "3.02": "nicht registrierter Aktienverkauf", "3.03": "Änderung der Aktionärsrechte",
    "4.01": "Wechsel des Abschlussprüfers", "4.02": "frühere Abschlüsse nicht mehr verlässlich",
    "5.01": "Kontrollwechsel", "5.02": "Wechsel in Vorstand oder Aufsichtsrat",
    "5.03": "Satzung oder Geschäftsjahr geändert", "5.07": "Ergebnisse der Hauptversammlung",
    "7.01": "Regulation-FD-Offenlegung", "8.01": "sonstige Ereignisse", "9.01": "Anlagen",
}
IMPORTANT_ITEMS = {"1.03", "1.05", "2.02", "2.04", "2.06", "3.01", "4.02", "5.01", "5.02"}
AUSBLICK = (r"(?:bestätigt|bekräftigt|hebt|senkt|erhöht|kappt|passt)\w*\s+(?:\S+\s+){0,3}?Ausblick"
            r"|\bAusblick\s+(?:für|auf|angehoben|gesenkt|bestätigt)")
KEYWORDS = [
    ("adhoc", r"EQS-Ad-?hoc|\bAd[- ]hoc\b|Insiderinformation"),
    ("earnings", r"\bearnings\b|\bresults\b|\bEPS\b|\bguidance\b|\bforecast\b"
                 r"|Quartalszahl|Quartalsmitteilung|Quartalsergebnis|Quartalsbericht|Zwischenmitteilung"
                 r"|Halbjahres(?:finanz)?bericht|Geschäftszahlen|Jahreszahlen|\bUmsatz|\bEBIT(?:DA)?\b"),
    ("guidance", r"\bguidance\b|profit warning|Prognose|Gewinnwarnung|" + AUSBLICK),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|price target|\boutperform\b|\bunderperform\b"
                r"|Kursziel|hochgestuft|herabgestuft|abgestuft|Kaufempfehlung|Verkaufsempfehlung"),
    ("legal", r"\blawsuit\b|\bsued\b|\bprobe\b|\binvestigation\b|\bSEC charges\b|\bantitrust\b|\bjudge\b|\bcourt\b"
              r"|\bKlage|\bverklagt|Ermittlung|Kartell|\bGericht|Razzia|Staatsanwalt"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|\bdeal\b"
             r"|\bÜbernahme|\bFusion|\bBeteiligung|\bVerkauf von\b|\bErwerb\b|\bZukauf"),
    ("capital", r"\bdividend\b|\bbuyback\b|\brepurchase\b|\bstock split\b|\boffering\b"
                r"|Kapitalerhöhung|Aktienrückkauf|Rückkaufprogramm|Dividende"),
    ("people", r"\bCEO\b|\bCFO\b|\bresign|\bsteps down\b|\bappoint"
               r"|\bVorstandschef|\bVorstandsvorsitz|\bFinanzvorstand|Rücktritt|tritt zurück"),
    ("risk", r"\brecall\b|\bbankrupt|\bdefault\b|\bdelist|\bhack|\bbreach\b|\boutage\b"
             r"|Insolvenz|Rückruf|Cyberangriff|Hackerangriff"),
    ("halt", r"\bhalt(?:s|ed)?\b|\btrading (?:pause|suspen)|Handelsaussetzung|Handel (?:wurde )?ausgesetzt"),
    ("regulatory", r"\bFDA\b|\bapproval\b|\bapproves\b|\bclinical\b|\bFTC\b|\bDOJ\b|Zulassung|\bBaFin\b|\bEMA\b"),
    ("macro", r"\bFed\b|\bFOMC\b|\bCPI\b|\binflation\b|\bjobs report\b|\bpayrolls\b|\btariffs?\b|\bfutures\b"
              r"|\bEZB\b|Leitzins|Inflation|\bZölle?\b|\bifo\b|\bZEW\b|Konjunktur"),
    ("insider", r"Directors'? Dealings|Eigengeschäft|Managers'? Transactions"),
    ("voting", r"Stimmrechtsmitteilung|Stimmrechtsanteil|\bvoting rights\b"),
]
TAG_DE = {
    "adhoc": "Ad-hoc", "earnings": "Zahlen", "guidance": "Prognose", "analyst": "Analysten",
    "legal": "Recht", "deal": "Übernahme/Deal", "capital": "Kapital", "people": "Personal",
    "risk": "Risiko", "halt": "Handelsstopp", "regulatory": "Behörden", "macro": "Makro",
    "insider": "Eigengeschäfte", "voting": "Stimmrechte",
}
REPORT_AHEAD = re.compile(
    r"ahead of (?:its |the )?(?:earnings|results)|earnings (?:preview|date|this week|next week)"
    r"|what to watch|\b(?:to|will) report\b|\breports? (?:this|next) week"
    r"|vor (?:den )?(?:Quartals|Geschäfts|Jahres)?zahlen|Berichtstermin|Finanzkalender"
    r"|legt\s+(?:\S+\s+){0,3}?(?:Quartals|Geschäfts|Jahres)?zahlen vor", re.I)
ISSUER_ISIN = re.compile(r"^(.+?)\s*/\s*([A-Z]{2}[A-Z0-9]{9}\d)\s*$")
ADHOC_RX = re.compile(KEYWORDS[0][1], re.I)

LEGAL = {
    "ag", "se", "kgaa", "inh", "vzo", "vz", "st", "na", "nam", "vna", "hldg", "holding", "group",
    "sf", "eo", "dl", "ls", "nv", "sa", "plc", "inc", "corp", "ltd", "gmbh", "co", "kg", "adr",
    "namens", "inhaber", "vorzug", "akt", "aktien", "reg", "on",
}
ABBREV = {"dt": "deutsch"}
FOLD = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e"}
SHORT_TAIL = r"(?=[\W_]+(?:ag|se|kgaa|n\.?v|s\.?a|plc|gmbh|holding|group|hldg)\b|\s*[/:])"


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{ticker: Name oder None}: Treffer des Scanners, der geplante Trade und dein Depot."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[sym.upper()] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(pl["symbol"].upper(), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[sym.upper()] = p.get("name") or out.get(sym.upper())
    return out


def load_universe(path):
    """trader/universe.txt -> {SYMBOL: {"name", "isin"}}. Zeilen SYMBOL|Name|ISIN|Gruppe (oder SYMBOL|Name)."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            isin = parts[2].upper() if len(parts) > 2 and re.match(r"^[A-Z]{2}[A-Z0-9]{9}\d$", parts[2].upper()) else ""
            out[parts[0].upper()] = {"name": parts[1] if len(parts) > 1 else "", "isin": isin}
    return out


def sec_user_agent(cli=None, config="trader/config.json"):
    ua = (cli or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua:
        cfg = load_json(config) or {}
        ua = str(cfg.get("sec_user_agent") or "").strip()
    if not ua or "@" not in ua or any(p in ua for p in PLACEHOLDERS):
        return None
    return ua


def is_xetra(ticker):
    return bool(ticker) and markt.market_of(ticker) == "xetra"


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, sec_ua=None, offline=None, pause=0.15):
        self.sec_ua = sec_ua
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name, sec=False):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: keine Datei %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        if sec and not self.sec_ua:
            raise NewsError("kein SEC-User-Agent gesetzt")
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        headers = {"User-Agent": self.sec_ua if sec else BROWSER_UA, "Accept-Encoding": "gzip"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s für %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            raise NewsError("%s nicht erreichbar: %s" % (url, exc.reason))


def yahoo_symbol(ticker):
    return markt.to_yahoo(ticker)


def cik_map(fetcher, state):
    """Ticker -> 10-stellige CIK, aus company_tickers.json der SEC (im Zustand gecacht)."""
    cached = state.setdefault("ciks", {})
    if cached:
        return cached
    data = json.loads(fetcher.get(TICKERS_URL, "company_tickers.json", sec=True).decode("utf-8"))
    for v in data.values():
        cached.setdefault(v["ticker"].upper().replace("-", "."), str(v["cik_str"]).zfill(10))
    return cached


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS) oder ISO 8601 (Atom) -> UTC-datetime mit tzinfo, oder None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_rss(data, ticker):
    """Yahoo-Schlagzeilen-RSS -> Meldungen."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS für %s ist kein gültiges XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        out.append({"id": "rss:" + guid, "source": "Yahoo Finance", "kind": "headline",
                    "ticker": ticker, "title": title, "summary": _text(it, "description"),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_sec_atom(data, ticker):
    """EDGAR-Atom-Feed einer Firma -> Meldungen."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("SEC-Feed für %s ist kein gültiges XML: %s" % (ticker, exc))
    company = ""
    for el in root.iter():
        if _local(el.tag) == "conformed-name":
            company = (el.text or "").strip()
            break
    out = []
    for entry in root.iter():
        if _local(entry.tag) != "entry":
            continue
        form = _text(entry, "filing-type")
        acc = _text(entry, "accession-number")
        items = re.findall(r"\d+\.\d+", _text(entry, "items-desc"))
        labels = [ITEMS_8K.get(i, "Punkt " + i) for i in items if i != "9.01"]
        link = ""
        for c in entry.iter():
            if _local(c.tag) == "link":
                link = c.get("href", "")
        title = "%s hat ein %s eingereicht" % (company or ticker, form)
        if labels:
            title += ": " + ", ".join(labels)
        out.append({"id": "sec:" + acc, "source": "SEC EDGAR", "kind": "filing", "form": form,
                    "ticker": ticker, "title": title, "summary": _text(entry, "form-name"),
                    "items": items, "important": bool(set(items) & IMPORTANT_ITEMS),
                    "link": link, "time": parse_time(_text(entry, "updated"))})
    return out


def parse_adhoc(data):
    """Atom-Feed von ad-hoc-news.de -> Meldungen ohne Ticker (Zuordnung danach über match_adhoc)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("Ad-hoc-Feed ist kein gültiges XML: %s" % exc)
    out = []
    for entry in root.iter():
        if _local(entry.tag) != "entry":
            continue
        title = re.sub(r"\s+", " ", _text(entry, "title"))
        summary = re.sub(r"\s+", " ", _text(entry, "summary"))
        link = ""
        for c in entry.iter():
            if _local(c.tag) == "link" and c.get("href"):
                link = c.get("href")
        m = ISSUER_ISIN.match(title)
        issuer, isin = (m.group(1), m.group(2)) if m else ("", "")
        if summary and (m or summary.startswith("EQS-")):
            head, rest = re.sub(r"(\((?:deutsch|englisch|english)\)).*$", r"\1", summary), title
        else:
            head, rest = title, summary
        adhoc = bool(ADHOC_RX.search(title + " " + summary))
        out.append({"id": "adhoc:" + (_text(entry, "id") or link), "source": "ad-hoc-news.de",
                    "kind": "adhoc" if adhoc else "corporate", "ticker": "", "title": head,
                    "summary": rest, "link": link, "issuer": issuer, "isin": isin,
                    "important": adhoc, "feed_time": True,
                    "time": parse_time(_text(entry, "published") or _text(entry, "updated"))})
    return out


def fold(text):
    s = (text or "").lower()
    for a, b in FOLD.items():
        s = s.replace(a, b)
    return s


def name_pattern(name):
    """Emittentenname -> Regex auf gefaltetem Text (klein, ä=ae). Rechtsformen und Nennwerte fallen weg,
    abgekürzte Wörter („BAY.MOTOREN“) passen als Präfix, sehr kurze Namen nur vor einer Rechtsform."""
    s = re.sub(r"\bo\.\s?n\.", " ", fold(name))
    toks = re.findall(r"([^\W_]+)(\.?)", s)
    keep = [(w, d) for w, d in toks if w not in LEGAL and not w.isdigit()]
    if not keep:
        keep = [(w, d) for w, d in toks if not w.isdigit()]
    if not keep:
        return None
    parts = []
    for w, dot in keep:
        w = ABBREV.get(w, w) if dot else w
        parts.append(re.escape(w) + (r"\w*" if dot else ""))
    body = r"\b" + r"[\W_]+".join(parts) + r"\b"
    if len(keep) == 1 and not keep[0][1] and len(keep[0][0]) <= 4:
        body += SHORT_TAIL
    return re.compile(body, re.I)


def match_adhoc(item, isin=None, rx=None):
    """Passt eine Feed-Meldung zu einem Emittenten? Über die ISIN (Titel, Text, Link) oder den Namen."""
    if isin and isin.upper() in ("%s %s %s" % (item["title"], item["summary"], item["link"])).upper():
        return True
    return bool(rx and rx.search(fold("%s %s" % (item["title"], item["summary"]))))


def identities(tickers, universe, isins=None, names=None, watch=None):
    """{ticker: {"isin", "name", "rx"}} für XETRA-Ticker."""
    out = {}
    for t in tickers:
        if not is_xetra(t):
            continue
        u = universe.get(t, {})
        isin = ((isins or {}).get(t) or u.get("isin") or "").upper()
        name = (names or {}).get(t) or u.get("name") or (watch or {}).get(t) or ""
        out[t] = {"isin": isin, "name": name, "rx": name_pattern(name) if name else None}
    return out


def parse_chart(data, ticker):
    """Yahoo-Chart-JSON -> {"ticker", "price", "prev_close", "pct", "time"} oder Fehler."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("Chart für %s ist nicht brauchbar" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("Chart für %s hat keinen Kurs" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", yahoo_symbol(t)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", yahoo_symbol(t)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "keine Datei" in str(exc)):
                errors.append("Kurs für %s: %s" % (t, exc))
    return out


def mention_patterns(watch, ident=None):
    """{ticker: (Regex auf Originaltext, Regex auf gefaltetem Text oder None)}."""
    pats = {}
    for t, name in watch.items():
        if is_xetra(t):
            base = t.rsplit(".", 1)[0]
            alts = [r"\((?:XETRA\s*:\s*)?%s\)" % re.escape(base), r"\bXETRA\s*:\s*%s\b" % re.escape(base)]
            idt = (ident or {}).get(t) or {}
            if idt.get("isin"):
                alts.append(re.escape(idt["isin"]))
            rx_name = idt.get("rx") or (name_pattern(name) if name else None)
            pats[t] = (re.compile("|".join(alts)), rx_name)
            continue
        alts = [r"\(%s\)" % re.escape(t), r"\$%s\b" % re.escape(t),
                r"\b(?:NYSE|NASDAQ|Nasdaq)\s*:\s*%s\b" % re.escape(t)]
        if name and len(name) >= 4:
            alts.append(r"\b%s\b" % re.escape(name).replace(r"\ ", r"[\s-]"))
        pats[t] = (re.compile("|".join(alts)), None)
    return pats


def tag(items, watch, ident=None):
    """Welche deiner Ticker eine Meldung betrifft, und worum es geht."""
    pats = mention_patterns(watch, ident)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        folded = fold(hay)
        touches = set(t for t in it.get("touches") or [] if t in watch)
        if it["ticker"] in watch:
            touches.add(it["ticker"])
        for t, (rx, rx_name) in pats.items():
            if rx.search(hay) or (rx_name is not None and rx_name.search(folded)):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
        if it["kind"] == "filing" and "2.02" in it.get("items", []) and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")
        if "adhoc" in it["tags"]:
            it["important"] = True
        it["report_hint"] = "earnings" in it["tags"] and bool(REPORT_AHEAD.search(hay))
    return items


def dedupe(items):
    """Eine Meldung pro Geschichte: gleiche id, gleicher Link oder gleicher Titel am selben Tag."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def collect_adhoc(fetcher, ident, universe=None, all_adhoc=False, errors=None):
    """Feed-Meldungen zu deinen XETRA-Tickern; mit all_adhoc zusätzlich jede Ad-hoc-Mitteilung."""
    errors = [] if errors is None else errors
    try:
        entries = parse_adhoc(fetcher.get(ADHOC_FEED, ADHOC_FILE))
    except NewsError as exc:
        errors.append("Ad-hoc-Feed: %s" % exc)
        return []
    others = {}
    if all_adhoc:
        for sym, u in (universe or {}).items():
            if is_xetra(sym) and sym not in ident:
                others[sym] = {"isin": u.get("isin"), "rx": name_pattern(u["name"]) if u.get("name") else None}
    out = []
    for it in entries:
        hits = [t for t in sorted(ident) if match_adhoc(it, ident[t]["isin"], ident[t]["rx"])]
        if hits:
            it["ticker"], it["touches"] = hits[0], hits
        elif all_adhoc and it["kind"] == "adhoc":
            it["ticker"] = next((s for s in sorted(others)
                                 if match_adhoc(it, others[s]["isin"], others[s]["rx"])), "")
        else:
            continue
        out.append(it)
    return out


def collect(fetcher, watch, state, sec=True, forms=("8-K",), count=10, errors=None,
            ident=None, universe=None, adhoc=True, all_adhoc=False):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        url = (YAHOO_DE if is_xetra(t) else YAHOO) % yahoo_symbol(t)
        try:
            items += parse_rss(fetcher.get(url, "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            errors.append("Schlagzeilen für %s: %s" % (t, exc))
    us = [t for t in sorted(watch) if not is_xetra(t)]
    if sec and us:
        try:
            ciks = cik_map(fetcher, state)
        except NewsError as exc:
            errors.append("SEC-Tickerliste: %s" % exc)
            ciks = {}
        for t in us:
            cik = ciks.get(t)
            if not cik:
                if ciks:
                    errors.append("keine SEC-CIK für %s" % t)
                continue
            for form in forms:
                try:
                    data = fetcher.get(SEC_FEED % (cik, form, count),
                                       "sec-%s-%s.xml" % (form, cik), sec=True)
                    items += parse_sec_atom(data, t)
                except NewsError as exc:
                    errors.append("SEC %s für %s: %s" % (form, t, exc))
    if ident is None:
        ident = identities(watch, universe or {}, watch=watch)
    if adhoc and (ident or all_adhoc):
        items += collect_adhoc(fetcher, ident, universe, all_adhoc, errors)
    return items


def select(items, state, now, hours=48, show_all=False):
    """Meldungen im Zeitfenster; ohne show_all nur ungesehene. Ad-hoc oben, sonst das Neueste zuerst."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # bei festem --now: nichts von danach
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    out.sort(key=lambda i: "adhoc" not in i.get("tags", []))
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


# ---------------------------------------------------------------- output

def market_for(ticker):
    return markt.market_of(ticker) if ticker else "xetra"


def when_label(utc, m, feed=False):
    """UTC -> "28.10.2026 08:04 Uhr" an XETRA, "19.10.2026 08:04 ET (14:04 Uhr)" in den USA."""
    with markt.using(m):
        loc = markt.to_local(utc)
        s = "%s %s" % (markt.date_de(loc), markt.clock_both(loc))
    return s + (" laut Feed" if feed else "")


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "BEWEGT" if abs(m["pct"]) >= move_pct else ""
        when = ""
        if m.get("time"):
            with markt.using(market_for(m["ticker"])):
                when = ", Stand %s" % markt.clock_both(markt.to_local(m["time"]))
        out.append("%-7s %s %s zum Vortagesschluss %s%s  %s" % (
            m["ticker"], markt.num(m["price"]), markt.pct(m["pct"], sign=True),
            markt.num(m["prev_close"]), when, flag))
    return out


def report_hints(items, now):
    """Ein Satz je Ticker, wenn eine Schlagzeile einen nahen Zahlentermin nahelegt."""
    out, done = [], set()
    for it in items:
        if not it.get("report_hint"):
            continue
        for t in it["touches"] or [it["ticker"]]:
            if not t or t in done:
                continue
            done.add(t)
            with markt.using(market_for(t)):
                local = markt.to_local(now)
                sess = markt.session(local.date())
                close = sess[1] if sess else markt.info()["close"]
                at = markt.clock_both(_dt.datetime.combine(local.date(), close))
            out.append("Berichtstermin %s: Eine Schlagzeile deutet auf nahe Zahlen. Über Nacht kann der Kurs "
                       "springen, auch über jeden Stopp hinweg; ein Daytrade ist vor Handelsschluss "
                       "um %s raus." % (t, at))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT, m=None):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nichts Neues.")
    for it in items:
        when = when_label(it["time"], market_for(it["ticker"]), it.get("feed_time")) \
            if it["time"] else "Zeit unbekannt"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"] or it.get("issuer") or "-"
        out.append("%s %s  %-11s %-15s %s" % (mark, when, who, it["source"], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("Themen: " + ", ".join(TAG_DE.get(t, t) for t in it["tags"]))
        if "insider" in it["tags"]:
            extra.append("Eigengeschäfte: Details mit /dt-insider")
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    hints = report_hints(items, now)
    if hints:
        out.append("")
        out.extend(hints)
    for e in errors:
        out.append("Hinweis: %s" % e)
    out.append("Geprüft %s. Schlagzeilen sind Hinweise, keine Fakten: lies die Meldung, bevor du handelst. "
               "Keine Anlageberatung." % when_label(now, m or markt.current()))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def _per_ticker(values, tickers, flag):
    """--isin SAP.DE=DE0007164600 oder, bei genau einem XETRA-Ticker, nur --isin DE0007164600."""
    out = {}
    xetra = [t for t in tickers if is_xetra(t)]
    for v in values or []:
        if "=" in v and v.split("=", 1)[0].strip().upper() in tickers:
            sym, val = v.split("=", 1)
            out[sym.strip().upper()] = val.strip()
        elif len(xetra) == 1:
            out[xetra[0]] = v.strip()
        else:
            raise NewsError("%s braucht SYMBOL=WERT, wenn du nicht genau einen XETRA-Ticker prüfst" % flag)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="Standard: Watchlist + Plan + Depot")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--universe", default="trader/universe.txt",
                    help="SYMBOL|Name|ISIN|Gruppe je Zeile, für die Zuordnung der Ad-hoc-Mitteilungen")
    ap.add_argument("--isin", action="append", metavar="[SYMBOL=]ISIN", help="ISIN für einen XETRA-Ticker")
    ap.add_argument("--name", action="append", metavar="[SYMBOL=]NAME", help="Emittentenname für einen XETRA-Ticker")
    ap.add_argument("--alle-adhoc", dest="alle_adhoc", action="store_true",
                    help="alle Ad-hoc-Mitteilungen im Zeitfenster, ohne Ticker-Filter")
    ap.add_argument("--no-adhoc", action="store_true", help="ohne den Ad-hoc-Feed")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ältere Meldungen ignorieren (Stunden)")
    ap.add_argument("--all", action="store_true", help="auch schon gesehene Meldungen zeigen")
    ap.add_argument("--forms", default="8-K", help="SEC-Formulare, durch Komma getrennt")
    ap.add_argument("--no-sec", action="store_true", help="ohne SEC-Meldungen")
    ap.add_argument("--no-moves", action="store_true", help="ohne Kurszeile je Ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="ab dieser Bewegung markieren (Prozent)")
    ap.add_argument("--user-agent", help="SEC-User-Agent: \"Dein Name du@example.com\"")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO-Zeit, für reproduzierbare Läufe (ohne Offset: Ortszeit des Marktes)")
    ap.add_argument("--dry-run", action="store_true", help="Zustandsdatei nicht ändern")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    with markt.restore():
        try:
            return _run(args)
        except NewsError as exc:
            print("news: %s" % exc, file=sys.stderr)
            return 2


def _run(args):
    if args.tickers:
        watch = {t.upper(): None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch and not args.alle_adhoc:
        print("news: keine Ticker. Gib --tickers an oder lass zuerst /dt-scanner laufen (es schreibt "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    main_market = "us" if watch and not any(is_xetra(t) for t in watch) else "xetra"
    markt.use(main_market)
    if args.now:
        now = markt.parse_now(args.now, error=NewsError).replace(tzinfo=_dt.timezone.utc)
    else:
        now = _dt.datetime.now(_dt.timezone.utc)
    isins = _per_ticker(args.isin, list(watch), "--isin")
    names = _per_ticker(args.name, list(watch), "--name")
    need_universe = args.alle_adhoc or any(is_xetra(t) for t in watch)
    universe = load_universe(args.universe) if need_universe else {}
    for t in watch:
        if is_xetra(t) and not watch[t] and universe.get(t, {}).get("name"):
            watch[t] = universe[t]["name"]
    ident = identities(watch, universe, isins, names, watch)
    state = load_json(args.state) or {}
    errors = []
    ua = sec_user_agent(args.user_agent, args.config)
    sec = not args.no_sec and any(not is_xetra(t) for t in watch)
    if sec and not ua and not args.offline:
        errors.append("SEC-Meldungen übersprungen: setz sec_user_agent in trader/config.json oder "
                      "SEC_USER_AGENT („Dein Name du@example.com“), um sie einzubeziehen")
        sec = False
    fetcher = Fetcher(ua, offline=args.offline)
    forms = [f.strip().upper() for f in args.forms.split(",") if f.strip()]
    items = collect(fetcher, watch, state, sec=sec, forms=forms, errors=errors, ident=ident,
                    universe=universe, adhoc=not args.no_adhoc, all_adhoc=args.alle_adhoc)
    items = dedupe(tag(items, watch, ident))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct, main_market))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
