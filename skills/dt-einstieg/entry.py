#!/usr/bin/env python3
"""Einstiegs-Timer für dt-einstieg: beobachtet ein Setup Kerze für Kerze und sagt
den Moment für den Einstieg. Nur Standardbibliothek. Nur Long. Platziert nie eine Order.

    python3 entry.py check SAP.DE                         # Opening-Range-Breakout, 5-Minuten-Kerzen
    python3 entry.py check SAP.DE --now "2026-10-27 10:55" --offline SAP.DE.json
    python3 entry.py check TSLA --setup level --level 371,20     # erster Schluss über einem Kurs
    python3 entry.py check TSLA --interval 1m --min-volume-x 1.5 --write
    python3 entry.py watch SAP.DE --every 30 --until 17:00 # eine Zeile je geschlossener Kerze
    python3 entry.py watchlist                            # jeder Treffer in trader/watchlist.json

Der Markt folgt aus dem Symbol: SAP.DE ist XETRA (9:00 bis 17:30 Uhr), TSLA ist US
(9:30 bis 16:00 ET). Alle Zeiten gelten in der Ortszeit des Marktes; --now ohne
Offset ebenso.

Setups (nur Long):
  orb    Opening-Range-Breakout. Die Range ist Hoch und Tief der ersten
         --or-minutes (Standard 15: an XETRA die Kerzen 9:00, 9:05 und 9:10,
         in New York 9:30, 9:35 und 9:40). Ausgelöst wird bei der ersten
         GESCHLOSSENEN Kerze nach der Range, die ÜBER dem Range-Hoch schließt.
         Ein Docht über das Hoch ist kein Auslöser.
  level  die erste geschlossene Kerze, die über --level schließt (zum Beispiel
         ein 20-Tage-Hoch aus dt-scanner).
  --min-volume-x X  die auslösende Kerze braucht zusätzlich mindestens das
         X-Fache des Durchschnittsvolumens der Range-Kerzen.

Die Zeit eines Auslösers ist der SCHLUSS der Kerze (die 10:50-Kerze schließt um
10:55 Uhr), der Kurs ist ihr Schlusskurs. Nur Kerzen im Raster zählen (Yahoos
Live-Tick, z. B. 9:57:36, fällt weg), und eine Kerze zählt erst, wenn sie
geschlossen ist.

Status: triggered (AUSGELÖST); waiting (WARTEN: noch nicht offen, Range bildet
sich, oder noch kein Schluss über dem Level); expired (ABGELAUFEN: kein Auslöser
bis no_entries_after, XETRA 17:00, US 15:30; an einem verkürzten Tag rückt die
Grenze mit dem Schluss vor); no-data (Börse heute zu oder keine Kerzen).

trader/config.json (optional): "no_entries_before" / "no_entries_after" oder je
Markt "zeiten": {"xetra": {...}, "us": {...}}, in Ortszeit des Marktes.

Datenalter: Yahoo liefert XETRA-Kerzen ca. 15 Minuten verzögert. Das Tool zeigt
das Alter der letzten Kerze und des letzten Kurses und zählt eine Kerze erst,
wenn Yahoo sie geliefert hat (oder nach Verzögerung plus einer Minute).

watch wacht nach jedem Kerzenschluss auf (live an XETRA zusätzlich um die
Verzögerung später), fragt alle --every Sekunden nach, solange Yahoo die neue
Kerze nicht hat, druckt eine Zeile je geschlossener Kerze und stoppt beim
Auslöser (Exit 0, schreibt trader/entry.json), beim Ablauf, zum Schluss oder bei
--until (Exit 1). Mit --now oder --offline läuft es auf einer simulierten Uhr.

Daten: Yahoos kostenloses Chart-JSON (inoffiziell, verzögert, Kerzen statt Einzelumsätze)
  https://query2.finance.yahoo.com/v8/finance/chart/SAP.DE?range=1d&interval=5m
  bei HTTP 429 oder 5xx Wechsel zu query1; ein 429 bekommt nach einer Pause einen zweiten Versuch.
  --offline PFAD liest ein gespeichertes Chart-JSON (.json oder .json.gz) oder
  PFAD/<SYMBOL>.json in einem Ordner. Ohne --now gilt die Zeit der Datei
  (meta.regularMarketTime).

Exit-Codes: check 0 = ausgelöst, 1 = alles andere oder ein Fehler. watch 0 bei
Auslöser, sonst 1. watchlist 0, wenn mindestens ein Symbol ausgelöst hat.
"""

import argparse
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
PAUSE = 0.5      # Sekunden zwischen Anfragen an den kostenlosen Endpunkt
BACKOFF = 5.0    # Sekunden vor dem zweiten Versuch nach HTTP 429
GRACE = 2        # Sekunden nach Kerzenschluss, bevor watch nachfragt
SETTLE = 60      # so lange darf eine geschlossene Kerze auf Yahoos Daten warten
HOSTS = ("query2", "query1")
INTERVALS = {"5m": 300, "1m": 60}
DELAY_MIN = {"xetra": 15, "us": 0}   # Yahoos Verzögerung je Markt in Minuten
EPOCH = datetime.datetime(1970, 1, 1)
CALENDAR_YEARS = markt.CALENDAR_YEARS


class EntryError(Exception):
    pass


# ---------------------------------------------------------------- Zeit

def utc_now():
    return markt.utc_now()


def utc_of(ts):
    """Unix-Sekunden -> naive UTC, ohne die Zeitzone des Rechners."""
    return EPOCH + datetime.timedelta(seconds=int(ts))


def ts_of(utc):
    return int((utc.replace(tzinfo=None) - EPOCH).total_seconds())


def iso(utc):
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_local(utc):
    return markt.to_local(utc)


def to_eastern(utc):
    return markt.to_eastern(utc)


def local_to_utc(local):
    return markt.local_to_utc(local)


def parse_now(text):
    """--now -> naive UTC. "2026-10-27 10:55" (oder ...T10:55, oder nur 10:55 für heute)
    gilt in Ortszeit des Marktes; ein Offset oder Z macht die Zeit absolut."""
    if not text:
        return utc_now()
    t = str(text).strip()
    for suffix in (" ET", " UHR"):
        if t.upper().endswith(suffix):
            t = t[:-len(suffix)].strip()
    if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", t):
        h, rest = t.split(":", 1)
        t = "%s %02d:%s" % (to_local(utc_now()).date().isoformat(), int(h), rest)
    return markt.parse_now(t, error=EntryError)


def parse_hhmm(text, what):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise EntryError("%s erwartet eine Uhrzeit in %s wie 15:30, nicht %r" % (what, markt.info()["zone"], text))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def hm(t):
    """10:10, 09:00: die Form für Dateien und JSON."""
    return markt.clock(t)


def _nolead(s):
    return s[1:] if s.startswith("0") and len(s) > 1 and s[1].isdigit() else s


def short(t):
    """9:55, 10:10: Kerzennamen in Sätzen."""
    return _nolead(markt.clock(t))


def zeit(t):
    """9:55 Uhr, 10:15 ET."""
    return _nolead(markt.clock_label(t))


def zeit2(local):
    """XETRA: 10:55 Uhr. US: 10:15 ET (16:15 Uhr)."""
    return _nolead(markt.clock_both(local))


def ampm(t):
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def geld(x):
    return markt.money(x)


def minuten(n):
    return "1 Minute" if n == 1 else "%d Minuten" % n


def trading_day(d):
    """(Handelstag?, Grund) für den aktuellen Markt."""
    return markt.trading_day(d)


def session(d):
    """(Eröffnung, Schluss) in Ortszeit, oder None an einem handelsfreien Tag."""
    return markt.session(d)


def next_open(d):
    nd = d + datetime.timedelta(days=1)
    for _ in range(15):
        s = session(nd)
        if s:
            return "%s %s" % (nd.isoformat(), hm(s[0]))
        nd += datetime.timedelta(days=1)
    return None


# ---------------------------------------------------------------- Yahoo

def yahoo_symbol(sym):
    return markt.to_yahoo(sym)


def chart_path(sym, rng, interval):
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (yahoo_symbol(sym), rng, interval)


def chart_range(day, today, interval):
    """Die kleinste Yahoo-Range, die die Sitzung von `day` noch enthält."""
    back = (today - day).days
    if back <= 0:
        return "1d"
    if back <= 6:
        return "5d"
    if interval == "1m":
        raise EntryError("Yahoo hält 1-Minuten-Kerzen nur etwa eine Woche: nimm --interval 5m für %s"
                         % markt.date_de(day))
    if back <= 28:
        return "1mo"
    if back <= 58:
        return "60d"
    raise EntryError("Yahoo hält 5-Minuten-Kerzen nur etwa 60 Tage: %s liegt zu weit zurück" % markt.date_de(day))


def _open_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _sleep(seconds):
    time.sleep(seconds)


def yahoo_get(path):
    """GET auf Yahoo: erst query2, bei 429 oder 5xx query1.
    Ein HTTP 429 bekommt nach BACKOFF Sekunden einen zweiten Versuch am selben Host."""
    last = "keine Antwort"
    for host in HOSTS:
        url = "https://%s.finance.yahoo.com%s" % (host, path)
        for attempt in (0, 1):
            try:
                return _open_url(url)
            except urllib.error.HTTPError as e:
                code, body = e.code, None
                try:
                    if code == 404:     # Yahoo nennt den Grund im Body: ein unbekanntes Symbol
                        body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = None
                finally:
                    e.close()
                if code == 404:
                    if body:
                        return body
                    raise EntryError("Yahoo hat keinen Chart unter %s (HTTP 404)" % url.split("?")[0])
                last = "HTTP %d" % code
                if code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if code == 429 or code >= 500:
                    break
                raise EntryError("Yahoo antwortet mit HTTP %d auf %s" % (code, url.split("?")[0]))
            except urllib.error.URLError as e:
                last = "keine Verbindung: %s" % (e.reason,)
                break
            except OSError as e:
                last = "Netzwerkfehler: %s" % (e,)
                break
    raise EntryError("Yahoo antwortet nicht (%s auf query2 und query1): warte eine Minute und versuch es noch einmal"
                     % last)


def parse_chart(text, sym):
    """Yahoo-Chart-JSON v8 -> {symbol, meta, bars, prev_close, data_time}.
    Kerzen ohne Schlusskurs fallen hier weg, Ticks außerhalb des Rasters später."""
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise EntryError("Yahoo hat für %s etwas Unerwartetes geschickt" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise EntryError("Yahoo hat keine Daten für %s: %s" % (sym, err.get("description") or "unbekanntes Symbol"))
    r = res[0] or {}
    meta = r.get("meta") or {}
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0] or {}

    def at(key, i):
        arr = q.get(key) or []
        return arr[i] if i < len(arr) else None

    bars = []
    for i, t in enumerate(r.get("timestamp") or []):
        c = at("close", i)
        if t is None or c is None:
            continue
        o, h, lo = at("open", i), at("high", i), at("low", i)
        bars.append({"t": int(t), "o": float(c if o is None else o), "h": float(c if h is None else h),
                     "l": float(c if lo is None else lo), "c": float(c), "v": int(at("volume", i) or 0)})
    return {"symbol": str(meta.get("symbol") or sym).upper(), "meta": meta, "bars": bars,
            "prev_close": meta.get("previousClose") or meta.get("chartPreviousClose"),
            "data_time": meta.get("regularMarketTime")}


def read_text(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def offline_file(path, sym):
    if os.path.isdir(path):
        for name in (sym + ".json", sym + ".json.gz", yahoo_symbol(sym) + ".json", yahoo_symbol(sym) + ".json.gz"):
            p = os.path.join(path, name)
            if os.path.exists(p):
                return p
        raise EntryError("keine Offline-Datei für %s in %s (erwartet %s.json)" % (sym, path, sym))
    if not os.path.exists(path):
        raise EntryError("keine Offline-Datei %s" % path)
    return path


def get_chart(sym, interval, day=None, offline=None, today=None):
    """Kerzen eines Symbols, von Yahoo (range=1d für heute) oder aus einer gespeicherten Datei."""
    sym = sym.upper()
    if offline:
        f = offline_file(offline, sym)
        try:
            text = read_text(f)
        except (OSError, ValueError) as e:
            raise EntryError("%s ist nicht lesbar: %s" % (f, e))
    else:
        today = today or to_local(utc_now()).date()
        text = yahoo_get(chart_path(sym, chart_range(day or today, today, interval), interval))
    ch = parse_chart(text, sym)
    if ch["symbol"] != yahoo_symbol(sym):
        raise EntryError("die Datei enthält %s, nicht %s" % (ch["symbol"], sym))
    gran = ch["meta"].get("dataGranularity")
    if gran and gran != interval:
        raise EntryError("%s hat %s-Kerzen, nicht %s: nimm --interval %s" % (sym, gran, interval, gran))
    return ch


# ---------------------------------------------------------------- die Regel

def read_config(path):
    """trader/config.json als dict (leer, wenn es sie nicht gibt). Die Zeitfenster
    werden für beide Märkte geprüft, gelesen werden sie über markt.windows()."""
    doc = {}
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except ValueError as e:
            raise EntryError("%s ist kein gültiges JSON: %s" % (path, e))
        if not isinstance(doc, dict):
            raise EntryError("%s muss ein JSON-Objekt sein" % path)
        doc = {k: v for k, v in doc.items() if v not in ("", None)}
    for m in markt.MARKETS:
        with markt.using(m):
            w = markt.windows(doc)
            for k in ("no_entries_before", "no_entries_after"):
                parse_hhmm(w[k], k)
    return doc


def r2(x):
    return None if x is None else round(float(x), 2) + 0.0   # + 0.0 macht aus -0.0 eine 0.0


def early_cutoff(day, t, close_dt):
    """An einem verkürzten Tag rückt die Grenze mit dem Schluss vor: 17:00 (30 Minuten vor
    17:30) wird an XETRA zu 13:30 vor einem Schluss um 14:00, in New York 15:30 zu 12:30.
    Eine Grenze, die schon vor dem verkürzten Schluss liegt, bleibt."""
    mk = markt.info()
    at = datetime.datetime.combine(day, t)
    if at < close_dt:
        return at
    moved = at - (datetime.datetime.combine(day, mk["close"]) - close_dt)
    return moved if moved.time() > mk["open"] else close_dt


def evaluate(chart, now_utc, setup="orb", or_minutes=15, interval="5m", level=None,
             min_volume_x=None, cfg=None, market=None):
    """Reine Funktion: der Status des Setups zu now_utc aus den Kerzen einer Sitzung.
    Der Markt folgt aus dem Symbol des Charts, außer `market` ist gesetzt."""
    with markt.using(market or markt.market_of(chart["symbol"])):
        return _evaluate(chart, now_utc, setup, or_minutes, interval, level, min_volume_x, cfg)


def _evaluate(chart, now_utc, setup, or_minutes, interval, level, min_volume_x, cfg):
    cfg = cfg if isinstance(cfg, dict) else {}
    if interval not in INTERVALS:
        raise EntryError("--interval ist 5m oder 1m")
    step = INTERVALS[interval]
    if or_minutes <= 0 or (or_minutes * 60) % step:
        raise EntryError("--or-minutes muss ein Vielfaches der %s-Kerzen sein" % interval)
    if setup not in ("orb", "level"):
        raise EntryError("--setup ist orb oder level")
    if setup == "level" and level is None:
        raise EntryError("--setup level braucht --level KURS (zum Beispiel ein 20-Tage-Hoch)")
    mk = markt.info()
    delay = DELAY_MIN[mk["key"]] * 60
    win = markt.windows(cfg)
    n_or = or_minutes * 60 // step
    local = to_local(now_utc)
    day = local.date()
    now_ts = ts_of(now_utc)
    res = {"symbol": chart["symbol"], "market": mk["key"], "currency": mk["currency"], "setup": setup,
           "side": "buy", "date": day.isoformat(), "interval": interval, "or_minutes": or_minutes,
           "now": local.strftime("%Y-%m-%d %H:%M:%S"), "status": "waiting", "phase": "", "reason": "",
           "opening_range": None, "level": None, "trigger": None, "last": None, "forming": None,
           "min_volume_x": min_volume_x, "prev_close": chart.get("prev_close"),
           "calendar_known": markt.in_calendar(day), "delay_minutes": DELAY_MIN[mk["key"]],
           "data_age": None, "_bars": []}
    dt = chart.get("data_time")
    res["data_time"] = markt.ts_to_local(dt).strftime("%Y-%m-%d %H:%M:%S") if dt else None
    ok, why = trading_day(day)
    if not ok:
        res.update(status="no-data", phase="closed", reason="%s handelt heute nicht (%s)" % (mk["exchange"], why),
                   next_open=next_open(day))
        return res
    o, c = session(day)
    open_dt = datetime.datetime.combine(day, o)
    close_dt = datetime.datetime.combine(day, c)
    early = markt.early_close(day)
    before = datetime.datetime.combine(day, parse_hhmm(win["no_entries_before"], "no_entries_before"))
    cutoff = early_cutoff(day, parse_hhmm(win["no_entries_after"], "no_entries_after"), close_dt)
    or_end = open_dt + datetime.timedelta(minutes=or_minutes)
    res.update(opens=hm(o), closes=hm(c), early_close=early, no_entries_before=hm(before),
               no_entries_after=hm(cutoff))

    by_slot = {}
    for b in chart["bars"]:
        if b["t"] % step:
            continue                       # Yahoos Live-Tick (9:57:36) ist keine Kerze
        lt = markt.ts_to_local(b["t"])
        if lt.date() != day or not (open_dt <= lt < close_dt):
            continue
        slot = int((lt - open_dt).total_seconds()) // step
        by_slot[slot] = dict(b, lt=lt, end=lt + datetime.timedelta(seconds=step), slot=slot)
    bars, pending, newest = [], None, None
    top = max(by_slot) if by_slot else -1
    for slot in sorted(by_slot):
        b = by_slot[slot]
        end_ts = b["t"] + step
        if b["lt"] <= local:
            newest = b
        if end_ts <= now_ts:
            # Nach der Uhr geschlossen. Live zählt sie, sobald Yahoo nachgezogen hat: der letzte Kurs
            # liegt am oder nach dem Schluss, es gibt eine spätere Kerze, oder Verzögerung plus eine Minute ist um.
            if dt is None or dt >= end_ts or slot < top or now_ts >= end_ts + delay + SETTLE:
                bars.append(b)
            else:
                pending = b
                res["forming"] = {"bar_start": hm(b["lt"]), "closes": ampm(b["end"]), "price": r2(b["c"])}
                res["lag_note"] = ("Yahoos letzter Kurs ist von %s, vor dem Schluss der %s-Kerze: sie zählt, "
                                   "sobald Yahoo nachzieht (%s)" % (
                                       _nolead(markt.ts_to_local(dt).strftime("%H:%M:%S")) + " " + mk["suffix"],
                                       short(b["lt"]),
                                       "an XETRA kommen die Kerzen ca. %d Minuten verzögert" % (delay // 60)
                                       if delay else "höchstens eine Minute"))
        elif b["lt"] <= local:
            res["forming"] = {"bar_start": hm(b["lt"]), "closes": ampm(b["end"]), "price": r2(b["c"])}
    res["_bars"] = bars
    res["bars_closed"] = len(bars)
    if newest:
        replay = dt is not None and dt > now_ts
        res["data_age"] = {
            "last_bar": hm(newest["lt"]), "minutes": int((local - newest["lt"]).total_seconds() // 60),
            "last_trade": markt.ts_to_local(dt).strftime("%H:%M:%S") if dt and not replay else None,
            "last_trade_minutes": int((now_ts - dt) // 60) if dt and not replay else None,
            "replay": replay, "delay_minutes": delay // 60}

    if local < open_dt:
        res.update(phase="pre-open", reason="%s öffnet um %s%s" % (mk["exchange"], zeit(o), (
            " und die %d-Minuten-Range steht um %s" % (or_minutes, zeit(or_end))) if setup == "orb" else ""))
        return res

    or_bars = [b for b in bars if b["slot"] < n_or]
    avg_vol = (sum(b["v"] for b in or_bars) / float(len(or_bars))) if or_bars else None
    range_done = local >= or_end and (len(or_bars) >= n_or or (bars and bars[-1]["slot"] >= n_or - 1)
                                      or now_ts >= ts_of(local_to_utc(or_end)) + delay + SETTLE)
    if or_bars:
        res["opening_range"] = {"high": r2(max(b["h"] for b in or_bars)), "low": r2(min(b["l"] for b in or_bars)),
                                "minutes": or_minutes, "bars": len(or_bars), "of": n_or,
                                "complete": bool(range_done), "avg_volume": int(round(avg_vol))}
    if setup == "orb":
        if not range_done:
            if local < or_end:
                why = "%d von %d Range-Kerzen geschlossen; die Range steht um %s" % (len(or_bars), n_or, zeit(or_end))
            else:
                why = ("%d von %d Range-Kerzen da; Yahoo liefert die letzte noch nach (ca. %d Minuten verzögert)"
                       % (len(or_bars), n_or, delay // 60) if delay else
                       "%d von %d Range-Kerzen da; Yahoo liefert die letzte noch nach" % (len(or_bars), n_or))
            res.update(phase="forming", reason=why)
            return res
        if not or_bars:
            res.update(status="no-data", phase="open", reason="Yahoo hat keine Kerzen für die Opening Range geschickt")
            return res
        lvl = max(b["h"] for b in or_bars)
    else:
        lvl = float(level)
    res["level"] = r2(lvl)

    first_slot = n_or if setup == "orb" else 0
    trig, thin = None, []
    for b in bars:
        if b["slot"] < first_slot or b["end"] < before or b["end"] > cutoff:
            continue
        if b["c"] > lvl:
            vx = (b["v"] / avg_vol) if avg_vol else None
            if min_volume_x and (vx is None or vx < min_volume_x):
                thin.append(b)
                continue
            trig = b
            break
    last = bars[-1] if bars else None
    if last:
        res["last"] = {"bar_start": hm(last["lt"]), "close": r2(last["c"]),
                       "vs_level_pct": r2(100.0 * (last["c"] / lvl - 1))}
    hoch = "dem Range-Hoch" if setup == "orb" else "dem Level"

    if trig:
        vx = (trig["v"] / avg_vol) if avg_vol else None
        res.update(status="triggered", phase="open" if local < close_dt else "after-close",
                   reason="die %s-Kerze hat über %s geschlossen" % (short(trig["lt"]), hoch))
        res["trigger"] = {"time": ampm(trig["end"]), "close_time": hm(trig["end"]), "bar_start": hm(trig["lt"]),
                          "bar_index": trig["slot"], "price": r2(trig["c"]), "close": trig["c"],
                          "volume": trig["v"], "volume_x": r2(vx), "pct_over": r2(100.0 * (trig["c"] / lvl - 1))}
        res["minutes_since"] = int((local - trig["end"]).total_seconds() // 60)
        if dt and utc_of(dt) < local_to_utc(trig["end"]):
            res["data_note"] = ("Yahoos letzter Kurs ist von %s, vor dem Schluss dieser Kerze: ihr Schlusskurs "
                                "kann sich noch um ein, zwei Cent bewegen"
                                % (_nolead(markt.ts_to_local(dt).strftime("%H:%M:%S")) + " " + mk["suffix"]))
        return res
    if not bars:
        res.update(status="no-data", phase="open",
                   reason="Yahoo hat für den %s noch keine Kerzen geschickt" % markt.date_de(day))
        return res
    what = "Schluss über %s %s" % (hoch, geld(lvl))
    grid_end = open_dt + datetime.timedelta(seconds=int((cutoff - open_dt).total_seconds()) // step * step)
    behind = bool(delay) and bars[-1]["end"] < grid_end and now_ts < ts_of(local_to_utc(cutoff)) + delay + SETTLE
    if local >= cutoff and not (pending and pending["end"] <= cutoff) and not behind:
        res.update(status="expired", phase="after-close" if local >= close_dt else "after-cutoff",
                   reason="kein %s bis %s, dem letzten Zeitpunkt für einen neuen Einstieg%s" % (
                       what, zeit(cutoff), " (heute verkürzter Handel bis %s)" % zeit(c) if early else ""))
        return res
    res["phase"] = "open"
    if local >= cutoff:
        res["phase"] = "after-cutoff"
        res["reason"] = ("nach %s keine neuen Einstiege, aber Yahoo liefert die Kerzen bis %s noch nach "
                         "(ca. %d Minuten verzögert); letzter Schluss %s (%s-Kerze)" % (
                             zeit(cutoff), zeit(cutoff), delay // 60, geld(last["c"]), short(last["lt"])))
    elif last["c"] > lvl and last in thin:
        res["reason"] = ("die %s-Kerze hat bei %s darüber geschlossen, aber nur mit dem %s-Fachen des "
                         "Range-Volumens, unter deinem Minimum von %s" % (
                             short(last["lt"]), geld(last["c"]), markt.num(last["v"] / avg_vol if avg_vol else 0),
                             markt.num(min_volume_x)))
    elif last["c"] > lvl and last["end"] < before:
        res["reason"] = "die %s-Kerze hat bei %s darüber geschlossen, aber vor %s gibt es keine Einstiege (Config)" % (
            short(last["lt"]), geld(last["c"]), zeit(before))
    else:
        gap = lvl - last["c"]
        res["reason"] = "letzter Schluss %s (%s-Kerze), %s %s %s %s (%s)" % (
            geld(last["c"]), short(last["lt"]), geld(abs(gap)), "unter" if gap >= 0 else "über",
            hoch, geld(lvl), markt.pct(100.0 * (last["c"] / lvl - 1), sign=True))
    return res


def public(res):
    """Das Ergebnis ohne die interne Kerzenliste, fertig für JSON."""
    return {k: v for k, v in res.items() if not k.startswith("_")}


def entry_doc(res, now_utc):
    """trader/entry.json, die Vertragsform (plus Begründung in Worten)."""
    t = res.get("trigger") or {}
    orr = res.get("opening_range")
    return {"created_by": "dt-einstieg", "symbol": res["symbol"], "market": res.get("market"),
            "currency": res.get("currency"), "setup": res["setup"], "side": "buy",
            "date": res["date"], "status": res["status"], "time": t.get("time"), "bar_start": t.get("bar_start"),
            "bar_index": t.get("bar_index"), "price": t.get("price"), "level": res.get("level"),
            "interval": res["interval"],
            "opening_range": {"high": orr["high"], "low": orr["low"], "minutes": orr["minutes"]} if orr else None,
            "source": "yahoo", "delay_minutes": res.get("delay_minutes"), "checked_at": iso(now_utc),
            "reason": res.get("reason")}


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------- Worte

LABEL = {"triggered": "AUSGELÖST", "waiting": "WARTEN", "expired": "ABGELAUFEN", "no-data": "KEINE DATEN"}
PHASE_LABEL = {"pre-open": "WARTEN (noch nicht offen)", "forming": "WARTEN (Range bildet sich)",
               "closed": "KEINE DATEN (Börse zu)"}
SHORT = {"pre-open": "WARTEN", "forming": "WARTEN", "closed": "ZU"}
SOURCE = {"xetra": "deutsche-boerse.com", "us": "nyse.com"}


def setup_name(res):
    if res["setup"] == "orb":
        return "Opening-Range-Breakout (%d-Minuten-Range)" % res["or_minutes"]
    return "Schluss über %s" % geld(res["level"]) if res["level"] is not None else "Schluss über einem Level"


def _dt(text):
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def data_line(res):
    """Wie alt die Daten sind, ehrlich: Yahoo ist kostenlos und an XETRA verzögert."""
    da = res.get("data_age")
    if not da:
        return None
    delay = da.get("delay_minutes") or 0
    if da["replay"]:
        s = "Rückblick auf gespeicherte Kerzen (Datei bis %s %s)." % (
            markt.day_label(_dt(res["data_time"]).date()), zeit(_dt(res["data_time"])))
        if delay:
            s += " Live kämen diese Kerzen bei Yahoo ca. %d Minuten verzögert." % delay
        return s
    last = datetime.datetime.strptime(da["last_bar"], "%H:%M")
    s = "Datenstand: letzte Kerze %s, %s alt" % (zeit(last), minuten(da["minutes"]))
    if da.get("last_trade"):
        lt = datetime.datetime.strptime(da["last_trade"], "%H:%M:%S")
        s += "; letzter Kurs von %s (%s alt)" % (zeit(lt), minuten(da["last_trade_minutes"]))
    if delay:
        s += ". Yahoo liefert XETRA-Kerzen ca. %d Minuten verzögert: das ist kein Echtzeitkurs." % delay
    else:
        s += " (Yahoo, kostenlos, kann verzögert sein)."
    return s


def describe(res):
    """Zeilen für Menschen."""
    with markt.using(res.get("market") or markt.current()):
        return _describe(res)


def _describe(res):
    when = _dt(res["now"])
    step = INTERVALS[res["interval"]] // 60
    delay = res.get("delay_minutes") or 0
    bars = "5-Minuten-Kerzen" if res["interval"] == "5m" else "1-Minuten-Kerzen"
    out = ["%s  %s %s  %s auf %s (Yahoo, kostenlos, inoffiziell)" % (
        res["symbol"], markt.day_label(when.date()), zeit2(when), setup_name(res), bars)]
    orr = res.get("opening_range")
    if orr:
        start = datetime.datetime.strptime(res["opens"], "%H:%M")
        end = start + datetime.timedelta(minutes=orr["minutes"])
        out.append("Opening Range %s bis %s: Hoch %s, Tief %s (%d von %d Kerzen%s)." % (
            short(start), zeit(end), geld(orr["high"]), geld(orr["low"]), orr["bars"], orr["of"],
            "" if orr["complete"] else ", bildet sich noch"))
    label = PHASE_LABEL.get(res["phase"]) or LABEL.get(res["status"], res["status"].upper())
    t = res.get("trigger")
    if t:
        tend = datetime.datetime.combine(when.date(), datetime.datetime.strptime(t["close_time"], "%H:%M").time())
        out.append("AUSGELÖST %s zu %s: die %s-Kerze (Kerze %d) hat über %s %s geschlossen (%s%s)." % (
            zeit2(tend), geld(t["price"]), short(datetime.datetime.strptime(t["bar_start"], "%H:%M")), t["bar_index"],
            "dem Range-Hoch" if res["setup"] == "orb" else "dem Level", geld(res["level"]),
            markt.pct(t["pct_over"], sign=True),
            (", %s-faches Range-Volumen" % markt.num(t["volume_x"])) if res.get("min_volume_x") and t.get("volume_x")
            else ""))
        line = data_line(res)
        if line:
            out.append(line)
        since = res.get("minutes_since", 0)
        if since <= step:
            out.append("Jetzt ist der Moment für den Einstieg, wenn du den Trade nimmst. Es wurde nichts platziert.")
            if delay:
                out.append("Live siehst du diese Kerze bei Yahoo erst ca. %d Minuten später: prüf den aktuellen Kurs "
                           "in deiner Broker-App, bevor du handelst." % delay)
        elif delay and since <= step + delay:
            out.append("Die Kerze ist %s alt, weil Yahoo XETRA-Kurse ca. %d Minuten verzögert liefert. Der Kurs hat "
                       "sich seitdem bewegt: prüf ihn in deiner Broker-App, bevor du einsteigst. "
                       "Es wurde nichts platziert." % (minuten(since), delay))
        else:
            if res.get("last"):
                out.append("Das war vor %s; der letzte Schluss ist %s (%s-Kerze). Ein später Einstieg ist ein "
                           "anderer Trade: Kurs, Stop-Abstand und Chancen haben sich verschoben." % (
                               minuten(since), geld(res["last"]["close"]),
                               short(datetime.datetime.strptime(res["last"]["bar_start"], "%H:%M"))))
            out.append("Es wurde nichts platziert.")
        if res.get("data_note"):
            out.append(res["data_note"] + ".")
        out.append("Weiter: Stop und Ziel festlegen, BEVOR du kaufst: /dt-ausstieg "
                   "(exit.py plan --from trader/entry.json).")
    else:
        out.append("%s  %s." % (label, res["reason"]))
        f = res.get("forming")
        if res.get("lag_note") and res["status"] == "waiting":
            out.append(res["lag_note"] + ".")
        elif f and res["status"] == "waiting" and res["phase"] in ("open", "forming"):
            fstart = datetime.datetime.strptime(f["bar_start"], "%H:%M")
            out.append("Die %s-Kerze läuft noch (bisher %s, schließt %s); sie zählt erst, wenn sie geschlossen ist." % (
                short(fstart), geld(f["price"]), zeit(fstart + datetime.timedelta(minutes=step))))
        line = data_line(res)
        if line and res["status"] != "no-data":
            out.append(line)
        if res["status"] == "expired":
            out.append("Heute kein Einstieg mehr mit diesem Setup. Es wurde nichts platziert.")
        if res.get("next_open"):
            nxt = datetime.datetime.strptime(res["next_open"], "%Y-%m-%d %H:%M")
            out.append("Nächste Eröffnung: %s %s." % (markt.day_label(nxt.date()), zeit2(nxt)))
    if res.get("early_close"):
        out.append("Heute verkürzter Handel bis %s (%s): keine neuen Einstiege nach %s." % (
            zeit(datetime.datetime.strptime(res["closes"], "%H:%M")), res["early_close"],
            zeit(datetime.datetime.strptime(res["no_entries_after"], "%H:%M"))))
    if not res.get("calendar_known"):
        out.append("Der Feiertagskalender deckt nur %s ab: prüf dieses Datum bei %s." % (
            " und ".join(map(str, CALENDAR_YEARS)), SOURCE.get(res.get("market"), "der Börse")))
    return out


def bar_line(b, res):
    """Eine watch-Zeile für eine gerade geschlossene Kerze."""
    with markt.using(res.get("market") or markt.current()):
        return _bar_line(b, res)


def _bar_line(b, res):
    start = short(b["lt"])
    orr = res.get("opening_range") or {}
    lvl = res.get("level")
    t = res.get("trigger")
    n_or = orr.get("of") or 0
    if res["setup"] == "orb" and b["slot"] < n_or:
        seen = [x for x in res["_bars"] if x["slot"] <= b["slot"]]
        note = "Range bisher %s bis %s" % (geld(min(x["l"] for x in seen)), geld(max(x["h"] for x in seen)))
        if b["slot"] == n_or - 1:
            note = "Opening Range steht: Hoch %s, Tief %s" % (geld(orr["high"]), geld(orr["low"]))
    elif t and t["bar_index"] == b["slot"]:
        note = "AUSGELÖST: Schluss über %s (%s). Jetzt einsteigen, wenn du ihn nimmst: %s, %s" % (
            geld(lvl), markt.pct(t["pct_over"], sign=True), zeit2(b["end"]), geld(t["price"]))
    elif lvl is None:
        note = ""
    elif b["c"] > lvl:
        note = "über %s" % geld(lvl)
        if res["setup"] == "level" or b["slot"] >= n_or:
            avg = orr.get("avg_volume")
            if res.get("min_volume_x") and avg:
                note += ", aber Volumen %sx unter %sx" % (markt.num(b["v"] / float(avg)), markt.num(res["min_volume_x"]))
            elif b["end"] < datetime.datetime.combine(b["lt"].date(), parse_hhmm(res["no_entries_before"], "x")):
                note += ", aber keine Einstiege vor %s" % zeit(parse_hhmm(res["no_entries_before"], "x"))
    else:
        note = "%s unter %s" % (geld(lvl - b["c"]), geld(lvl))
    return "%5s-Kerze  Schluss %s  %s" % (start, geld(b["c"]), note)


# ---------------------------------------------------------------- watch

class SimClock(object):
    """Eine Uhr, die nur beim Schlafen weiterläuft: spielt einen Tag ohne Warten ab."""

    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += datetime.timedelta(seconds=max(1, int(round(seconds))))


def watch_loop(provider, clock, sleep, emit, opts, every=30, until=None, max_errors=5, on_trigger=None, lag=0):
    """Fragt Kerze für Kerze ab bis zum Auslöser (0), Ablauf, Schluss oder --until (1).
    provider(now_utc) -> chart, clock() -> naive UTC, sleep(sekunden), emit(zeile).
    lag: Sekunden, die Yahoo hinterherhängt (live an XETRA 900); watch wacht entsprechend später auf.
    Es schläft in Schritten von höchstens `every` Sekunden und liest die Uhr jedes Mal neu,
    damit ein Rechner, der eingeschlafen war, beim Aufwachen sofort aufholt."""
    with markt.using(opts.get("market") or markt.current()):
        return _watch_loop(provider, clock, sleep, emit, opts, every, until, max_errors, on_trigger, lag)


def _watch_loop(provider, clock, sleep, emit, opts, every, until, max_errors, on_trigger, lag):
    step = INTERVALS[opts.get("interval", "5m")]
    printed, errors, said_preopen, first = -1, 0, False, True
    next_fetch = None
    while True:
        now = clock()
        if next_fetch is not None and now < next_fetch:
            sleep(max(1, min(every, (next_fetch - now).total_seconds())))
            continue
        local = to_local(now)
        day = local.date()
        s = session(day)
        if not s:
            emit("%s: Börse heute geschlossen (%s). Nichts zu beobachten." % (
                markt.day_label(day), trading_day(day)[1]))
            return 1, None
        open_dt = datetime.datetime.combine(day, s[0])
        close_dt = datetime.datetime.combine(day, s[1])
        if local < open_dt + datetime.timedelta(seconds=step + lag):
            if not said_preopen:
                first_close = open_dt + datetime.timedelta(seconds=step)
                emit("%s  %s: beobachte ab dem Schluss der ersten Kerze um %s%s." % (
                    zeit2(local), "noch nicht offen" if local < open_dt else "offen, noch keine Kerze geschlossen",
                    zeit(first_close), (" (bei Yahoo ca. %s, %d Minuten verzögert)" % (
                        zeit(first_close + datetime.timedelta(seconds=lag)), lag // 60)) if lag else ""))
                said_preopen = True
            next_fetch = local_to_utc(open_dt) + datetime.timedelta(seconds=step + lag + GRACE)
            continue
        try:
            chart = provider(now)
            errors = 0
        except EntryError as e:
            errors += 1
            emit("%s  Kerzen nicht lesbar: %s" % (_nolead(local.strftime("%H:%M:%S")) + " " + markt.info()["suffix"], e))
            if errors >= max_errors:
                emit("Abbruch nach %d Fehlversuchen in Folge." % errors)
                return 1, None
            next_fetch = now + datetime.timedelta(seconds=every)
            continue
        res = evaluate(chart, now, **opts)
        bars = res["_bars"]
        lines = describe(res)
        fresh = first
        if first:
            emit(lines[0])
            if len(lines) > 1 and lines[1].startswith("Opening Range"):
                emit(lines[1])
            if bars and not res.get("trigger"):
                emit(bar_line(bars[-1], res))
            printed = bars[-1]["slot"] if bars else -1
            first = False
        else:
            for b in bars:
                if b["slot"] > printed:
                    emit(bar_line(b, res))
                    printed = b["slot"]
        if res["status"] == "triggered":
            for line in lines[1:]:
                if line.startswith("Opening Range") or (line.startswith("AUSGELÖST") and not fresh):
                    continue
                emit(line)
            if on_trigger:
                on_trigger(res, now)
            return 0, res
        if res["status"] == "expired" or local >= close_dt:
            emit("ABGELAUFEN  %s." % (res["reason"] or "Börsenschluss ohne Auslöser"))
            return 1, res
        if until and local >= until:
            emit("Bei --until %s ohne Auslöser gestoppt. %s." % (zeit(until), res["reason"]))
            return 1, res
        # schlafen bis kurz nach dem nächsten Kerzenschluss (plus Yahoos Verzögerung); alle `every` Sekunden, wenn Yahoo hinterherhängt
        seen = local - datetime.timedelta(seconds=lag)
        cur_slot = int((seen - open_dt).total_seconds()) // step
        behind = (not bars) or bars[-1]["slot"] < cur_slot - 1
        if behind:
            wait = every
        else:
            nxt = open_dt + datetime.timedelta(seconds=(cur_slot + 1) * step + lag + GRACE)
            wait = (nxt - local).total_seconds()
        cutoff = datetime.datetime.combine(day, parse_hhmm(res.get("no_entries_after") or "17:00", "cutoff"))
        for stop_at in (until, cutoff, close_dt):
            if stop_at and stop_at > local:
                wait = min(wait, (stop_at - local).total_seconds())
        next_fetch = now + datetime.timedelta(seconds=max(1, wait))


# ---------------------------------------------------------------- Befehle

def _kurs(text):
    v = markt.parse_number(text)
    if v is None:
        raise argparse.ArgumentTypeError("erwartet einen Kurs wie 214,75 oder 214.75, nicht %r" % text)
    return v


def _opts(a, cfg, market):
    if a.side in ("sell", "short"):
        raise EntryError("nur Long: keine Short-Einstiege. Beobachte stattdessen einen Kauf (--side buy).")
    if a.setup == "orb" and a.level is not None:
        raise EntryError("--level gehört zu --setup level (beim orb ist das Level das Range-Hoch)")
    if a.min_volume_x is not None and a.min_volume_x <= 0:
        raise EntryError("--min-volume-x muss über 0 liegen")
    if a.level is not None and a.level <= 0:
        raise EntryError("--level muss ein Kurs über 0 sein")
    return {"setup": a.setup, "or_minutes": a.or_minutes, "interval": a.interval, "level": a.level,
            "min_volume_x": a.min_volume_x, "cfg": cfg, "market": market}


def _market(a, sym, cfg):
    try:
        return markt.use(markt.resolve(flag=a.market, symbols=[sym], cfg=cfg))
    except markt.MarketError as e:
        raise EntryError(str(e))


def _load(a, sym, now):
    """(chart, now). Eine Offline-Datei ohne --now gilt zu ihrer eigenen Zeit."""
    real_today = to_local(utc_now()).date()
    if a.offline and now is None:
        ch = get_chart(sym, a.interval, offline=a.offline)
        return ch, (utc_of(ch["data_time"]) if ch.get("data_time") else utc_now())
    now = now or utc_now()
    return get_chart(sym, a.interval, to_local(now).date(), a.offline, real_today), now


DISCLAIMER = "Ein Auslöser ist ein Chart-Signal, keine Empfehlung. Keine Anlageberatung."


def cmd_check(a):
    cfg = read_config(a.config)
    sym = a.symbol.upper()
    m = _market(a, sym, cfg)
    opts = _opts(a, cfg, m)
    chart, now = _load(a, sym, parse_now(a.now) if a.now else None)
    res = evaluate(chart, now, **opts)
    if a.write:
        write_json(a.write, entry_doc(res, now))
    if a.json:
        print(json.dumps(public(res), indent=2, ensure_ascii=False))
    else:
        for line in describe(res):
            print(line)
        if a.write:
            print("%s geschrieben (Status %s)." % (a.write, LABEL.get(res["status"], res["status"])))
        print(DISCLAIMER)
    return 0 if res["status"] == "triggered" else 1


def cmd_watch(a):
    cfg = read_config(a.config)
    sym = a.symbol.upper()
    m = _market(a, sym, cfg)
    opts = _opts(a, cfg, m)
    if a.every <= 0:
        raise EntryError("--every muss über 0 Sekunden liegen")
    start = parse_now(a.now) if a.now else None
    simulated = bool(a.offline or start is not None)
    if simulated:
        if start is None:
            start = _load(a, sym, None)[1]
        clock = SimClock(start)
        now_fn, sleep_fn = clock.now, clock.sleep
    else:
        now_fn, sleep_fn = utc_now, _sleep
    real_today = to_local(utc_now()).date()

    def provider(now):
        return get_chart(sym, a.interval, to_local(now).date(), a.offline, real_today)

    until = None
    if a.until:
        t = parse_hhmm(a.until, "--until")
        until = datetime.datetime.combine(to_local(now_fn()).date(), t)

    def on_trigger(res, now):
        write_json(a.out, entry_doc(res, now))
        print("%s geschrieben." % a.out, flush=True)

    def emit(line):
        print(line, flush=True)

    code, _ = watch_loop(provider, now_fn, sleep_fn, emit, opts, every=a.every, until=until,
                         on_trigger=on_trigger, lag=0 if simulated else DELAY_MIN[m] * 60)
    return code


def cmd_watchlist(a):
    cfg = read_config(a.config)
    if not os.path.exists(a.watchlist):
        raise EntryError("keine Watchlist unter %s: lass zuerst /dt-scanner laufen (er schreibt die Treffer dorthin)"
                         % a.watchlist)
    try:
        with open(a.watchlist, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as e:
        raise EntryError("%s ist kein gültiges JSON: %s" % (a.watchlist, e))
    hits = [h for h in (doc.get("hits") or []) if isinstance(h, dict) and h.get("symbol")]
    if not hits:
        raise EntryError("keine Treffer in %s: der Scanner hat nichts zum Beobachten gefunden" % a.watchlist)
    if a.offline and not os.path.isdir(a.offline):
        raise EntryError("watchlist --offline erwartet einen Ordner mit <SYMBOL>.json-Dateien")
    rows = []
    for i, h in enumerate(hits):
        sym = str(h["symbol"]).upper()
        try:
            m = _market(a, sym, cfg)
            o = _opts(a, cfg, m)
            if a.setup == "level" and o["level"] is None:
                o["level"] = markt.parse_number(h.get("level")) if h.get("level") is not None else None
            if a.setup == "level" and o["level"] is None:
                raise EntryError("braucht ein Level: --level KURS oder ein \"level\" in der Watchlist")
            if i and not a.offline:
                _sleep(PAUSE)
            chart, when = _load(a, sym, parse_now(a.now) if a.now else None)
            rows.append((sym, evaluate(chart, when, **o), None))
        except EntryError as e:
            rows.append((sym, None, str(e)))
    if a.json:
        print(json.dumps([{"symbol": s, "result": public(r) if r else None, "error": e} for s, r, e in rows],
                         indent=2, ensure_ascii=False))
        return 0 if any(r and r["status"] == "triggered" for _, r, _ in rows) else 1
    fmt = "%-8s  %-10s  %-9s  %-11s  %-11s  %-11s  %s"
    print(fmt % ("SYMBOL", "STATUS", "ZEIT", "KURS", "LEVEL", "LETZTER", "ABSTAND"))
    for s, r, e in rows:
        if e:
            print("%-8s  Fehler: %s" % (s, e))
            continue
        with markt.using(r["market"]):
            t = r.get("trigger") or {}
            last = r.get("last") or {}
            if r["status"] in ("triggered", "expired"):
                status = LABEL[r["status"]]
            else:
                status = SHORT.get(r["phase"]) or LABEL.get(r["status"], r["status"].upper())
            tz = zeit(datetime.datetime.strptime(t["close_time"], "%H:%M")) if t else "-"
            print(fmt % (s, status, tz, geld(t["price"]) if t else "-",
                         geld(r["level"]) if r.get("level") is not None else "-",
                         geld(last["close"]) if last else "-",
                         markt.pct(last["vs_level_pct"], sign=True) if last.get("vs_level_pct") is not None else "-"))
    n = sum(1 for _, r, _ in rows if r and r["status"] == "triggered")
    print("%d von %d ausgelöst. Such dir einen aus, dann: entry.py check <SYMBOL> --write und /dt-ausstieg." % (
        n, len(rows)))
    print("Kostenlose Yahoo-Kerzen, inoffiziell und verzögert (XETRA ca. %d Minuten). Es wurde nichts platziert."
          % DELAY_MIN["xetra"])
    print(DISCLAIMER)
    return 0 if n else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Einstiegs-Timer (dt-einstieg): beobachtet ein Setup Kerze für Kerze. "
                                             "Platziert nie eine Order.")
    sub = ap.add_subparsers(dest="cmd", metavar="BEFEHL")

    def common(p):
        p.add_argument("--setup", choices=["orb", "level"], default="orb",
                       help="orb = Opening-Range-Breakout (Standard), level = Schluss über --level")
        p.add_argument("--or-minutes", type=int, default=15, help="Länge der Opening Range in Minuten (Standard 15)")
        p.add_argument("--interval", choices=["5m", "1m"], default="5m", help="Kerzenlänge (Standard 5m)")
        p.add_argument("--level", type=_kurs, help="der Kurs, über dem geschlossen werden muss (--setup level)")
        p.add_argument("--min-volume-x", type=float,
                       help="Volumen der auslösenden Kerze mindestens das X-Fache des Range-Durchschnitts")
        p.add_argument("--side", default="buy", choices=["buy", "long", "sell", "short"], help="nur buy (Long)")
        p.add_argument("--market", help="xetra oder us (sonst aus dem Symbol: SAP.DE = XETRA, TSLA = US)")
        p.add_argument("--now", help='tu so, als wäre es diese Ortszeit des Marktes, z. B. "2026-10-27 10:55"')
        p.add_argument("--offline", metavar="PFAD", help="gespeichertes Yahoo-Chart-JSON (.json/.json.gz) oder ein Ordner")
        p.add_argument("--config", default="trader/config.json", help="Config (Standard trader/config.json)")

    p = sub.add_parser("check", help="der Status des Setups jetzt")
    p.add_argument("symbol", help="Symbol, z. B. SAP.DE oder TSLA")
    common(p)
    p.add_argument("--write", nargs="?", const="trader/entry.json", metavar="PFAD",
                   help="Ergebnis speichern (Standard trader/entry.json)")
    p.add_argument("--json", action="store_true", help="Ergebnis als JSON")
    p = sub.add_parser("watch", help="Kerze für Kerze abfragen, bis es auslöst oder abläuft")
    p.add_argument("symbol", help="Symbol, z. B. SAP.DE oder TSLA")
    common(p)
    p.add_argument("--every", type=float, default=30, help="Sekunden zwischen Abfragen, solange Yahoo hinterherhängt")
    p.add_argument("--until", help="um diese Ortszeit des Marktes aufhören (HH:MM)")
    p.add_argument("--out", default="trader/entry.json", help="wohin ein Auslöser geschrieben wird")
    p = sub.add_parser("watchlist", help="jeden Treffer in trader/watchlist.json prüfen")
    common(p)
    p.add_argument("--watchlist", default="trader/watchlist.json", help="Watchlist (Standard trader/watchlist.json)")
    p.add_argument("--json", action="store_true", help="Ergebnis als JSON")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    with markt.restore():
        try:
            return {"check": cmd_check, "watch": cmd_watch, "watchlist": cmd_watchlist}[a.cmd](a)
        except EntryError as e:
            print("entry.py: %s" % e, file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("entry.py: gestoppt.", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
