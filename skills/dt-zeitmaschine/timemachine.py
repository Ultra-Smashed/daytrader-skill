#!/usr/bin/env python3
"""Zeitmaschine für dt-zeitmaschine. Nur Standardbibliothek.

Spielt einen geplanten Daytrade durch, bevor du einen Euro riskierst: 10.000
simulierte Durchläufe für den Rest der Sitzung ab deinem Einstieg, dazu dieselbe
Regel auf jeder vergangenen Sitzung in den Daten.

    python3 timemachine.py run                          # trader/plan.json, 10.000 Durchläufe, Seed 19
    python3 timemachine.py run --write                  # zusätzlich trader/timemachine.json speichern
    python3 timemachine.py run --until glatt            # jeden Durchlauf zur Glattstell-Zeit beenden
    python3 timemachine.py run --seed 7 --replays 20000 --json
    python3 timemachine.py run --symbol SAP.DE --date 2026-10-27 --entry 214.90 \\
        --stop 213.22 --target 216.58 --entry-time 10:55
    python3 timemachine.py chart                        # ASCII-Fächer der Durchläufe
    python3 timemachine.py chart --from trader/timemachine.json

Der Markt folgt aus dem Symbol (SAP.DE = XETRA 9:00 bis 17:30 Uhr, TSLA = US
9:30 bis 16:00 New Yorker Zeit). Alle Uhrzeiten sind Ortszeit dieses Marktes.

So funktionieren die Durchläufe (gleicher Algorithmus, gleiche Zufallszüge wie sim.py):
  1. 60 Tage 5-Minuten-Kerzen holen (Yahoo v8 chart, range=60d interval=5m;
     eine Anfrage). Nur VOLLE Sitzungen vor dem Tag des Plans zählen: XETRA 102
     Kerzen (9:00 bis 17:30 Uhr), US 78 Kerzen (9:30 bis 16:00 ET). Verkürzte
     Tage, Lücken und heute bleiben draußen. Die Tageszeit-Slots werden in
     Ortszeit des Marktes gebildet, eine Zeitumstellung verschiebt sie nicht.
  2. Der Pool: für jeden Slot 1..N-1 die Kerze jeder vergangenen Sitzung als
     Verhältnis zum Schluss der Kerze davor: (open, high, low, close) / prev close.
  3. Ein Durchlauf startet beim Einstiegskurs und läuft den Rest der Sitzung.
     Für jede Kerze i wählt er den Slot j = i + randint(-window, window), begrenzt
     auf 1..N-1, dann eine vergangene Kerze aus pool[j] (random.choice), und
     skaliert sie auf den aktuellen Kurs. Der Stop wird in jeder Kerze vor dem Ziel
     geprüft; eine Kerze, die beide berührt, zählt als Stop (die vorsichtige Wahl).
  4. Ergebnisse: "target" oder "stop" (was zuerst berührt wurde), sonst "neither",
     wenn der Trade bei --until noch offen ist (Standard: Handelsschluss, an einem
     verkürzten Tag dessen Schluss).
     "Im Plus" = Ziel zuerst, oder bei --until über dem Einstieg (unter bei Verkauf).
     R = das R des Ziels am Ziel, -1 am Stop, sonst (Kurs bei --until - Einstieg) / Risiko.
     Eine Lücke durch den Stop zählt hier -1R; eine echte Ausführung kann schlechter sein.
  5. Der Kurs bei --until: Median und 5. bis 95. Perzentil aller Durchläufe
     (pct(a, q) = sortiertes a an Index int(q * n)). Der Fächer nutzt einen zweiten
     Lauf mit 2.000 Pfaden und demselben Seed. Das Histogramm hat 24 Klassen
     zwischen dem 1. und 99. Perzentil.
  6. Rückschau: die Regel des Plans (Opening-Range-Breakout mit derselben Range ab
     Eröffnung des Marktes, derselben Stop-Regel und demselben Ziel-R) auf jeder
     dieser vollen Sitzungen; der erste Schluss jenseits der Range ist der Einstieg.

Das Urteil schaut auf die Durchläufe, die eine Seite erreicht haben, und vergleicht
den Anteil des Ziels, target / (target + stop), mit dem Anteil, der beim R des Ziels
plusminus null ergibt: 1 / (1 + R), also 50 % bei 1R und 33 % bei 2R. Abstand in Punkten:
  unter 5        "Nahe an einem Münzwurf" (1R) / "Nahe am Break-even" (anderes R)
  5 bis 15       "Neigt zum Ziel" / "Neigt zum Stop"
  15 und mehr    "Deutlich Richtung Ziel" / "Deutlich Richtung Stop"
Darunter: ein Hinweis, wenn mehr als 40 % keine Seite erreichen, und das
durchschnittliche R, wenn sein Vorzeichen gegen die Neigung läuft.

Nur 5-Minuten-Kerzen: Yahoo hält 60 Tage davon, aber nur etwa 7 Tage 1-Minuten-Kerzen.
Unter 20 vollen Sitzungen oder ohne die Einstiegskerze in den Daten lehnt das Tool ab.
Gleicher Plan, gleiche Daten, gleicher --seed: gleiche Zahlen auf jedem Rechner.
Eine Simulation aus den eigenen Kerzen der Aktie ist keine Vorhersage.

Daten: https://query2.finance.yahoo.com/v8/finance/chart/<T>?range=60d&interval=5m
(inoffiziell und kostenlos, kann verzögert sein; bei 429 oder 5xx query1).
--offline DATEI liest ein gespeichertes Chart-JSON (.json oder .json.gz).
--now "2026-10-27 11:00" setzt die Uhr (Ortszeit des Marktes).
"""

import argparse
import datetime
import gzip
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
PAUSE = 0.5          # seconds between requests: be polite to free endpoints
BACKOFF = 5.0        # seconds to wait once after a 429
HOSTS = ("query2", "query1")
INTERVAL = 300       # 5-minute bars, in seconds
MIN_SESSIONS = 20
SAMPLE_PATHS = 160
BAND_PATHS = 2000
BAND_Q = (0.05, 0.25, 0.5, 0.75, 0.95)
HIST_BINS = 24
COIN_FLIP = 0.05     # verdict thresholds, see the docstring
STRONG = 0.15
MANY_NEITHER = 0.40
EPOCH = datetime.datetime(1970, 1, 1)
FLAT_WORDS = ("glatt", "flat", "flat_by")


class TMError(Exception):
    pass


# ---------------------------------------------------------------- market clock

def open_min():
    o = markt.info()["open"]
    return o.hour * 60 + o.minute


def close_min():
    c = markt.info()["close"]
    return c.hour * 60 + c.minute


def session_bars():
    """Kerzen einer vollen Sitzung: XETRA 102, US 78."""
    return (close_min() - open_min()) // 5


def parse_now(text, m=None):
    return markt.parse_now(text, m, error=TMError)


def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def parse_clock(text, what):
    """'10:15', '10:15 Uhr', '10:15 AM' oder '3:55' (1 bis 8 Uhr ohne Zusatz heißt nachmittags) -> Minuten."""
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*(?:([AaPp])\.?\s*[Mm]\.?|Uhr|uhr|ET|et)?\s*$", str(text or ""))
    if not m:
        raise TMError("%s erwartet eine Uhrzeit wie 10:15 oder 15:55 (%s), nicht %r"
                      % (what, markt.info()["zone"], text))
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if mi > 59 or h > 23 or (ap and not 1 <= h <= 12):
        raise TMError("%s %r ist keine Uhrzeit" % (what, text))
    if ap == "p" and h != 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 8:
        h += 12
    return h * 60 + mi


def clock12(minutes):
    h, m = divmod(minutes, 60)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def clock24(minutes):
    return "%02d:%02d" % divmod(minutes, 60)


def plan_clock(minutes):
    """Uhrzeit für JSON-Felder (entry_time, trades.time): US wie bisher "10:15 AM", XETRA "10:55"."""
    return clock12(minutes) if markt.current() == "us" else clock24(minutes)


def hm(minutes):
    """Minuten -> "10:15 Uhr" bzw. "10:15 ET"."""
    return markt.clock_label(datetime.time(*divmod(minutes, 60)))


def minutes_of(text):
    return int(text[:2]) * 60 + int(text[3:5])


# ---------------------------------------------------------------- data

def chart_url(sym, host="query2"):
    return "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m" % (
        host, urllib.parse.quote(markt.to_yahoo(sym)))


def _sleep(seconds):
    time.sleep(seconds)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_chart(sym):
    """Eine Anfrage für 60 Tage 5-Minuten-Kerzen. Erst query2, nach einem 429 ein zweiter
    Versuch, dann query1 bei 429 oder 5xx."""
    last = None
    for n, host in enumerate(HOSTS):
        if n:
            _sleep(PAUSE)
        for attempt in (0, 1):
            url = chart_url(sym, host)
            try:
                return _get(url)
            except urllib.error.HTTPError as e:
                last = e.code
                try:
                    e.close()
                except Exception:
                    pass
                if e.code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if e.code == 429 or e.code >= 500:
                    break
                if e.code == 404:
                    raise TMError("Yahoo hat keinen Chart für %s (HTTP 404): prüf das Symbol" % sym.upper())
                raise TMError("Yahoo antwortet HTTP %d für %s" % (e.code, sym.upper()))
            except urllib.error.URLError as e:
                raise TMError("Yahoo ist nicht erreichbar: %s" % e.reason)
            except OSError as e:
                raise TMError("Yahoo ist nicht erreichbar: %s" % e)
    if last == 429:
        raise TMError("Yahoo bremst gerade (HTTP 429). Warte eine Minute und starte es noch einmal.")
    raise TMError("Yahoo antwortet auf beiden Hosts HTTP %s für %s. Versuch es später noch einmal."
                  % (last, sym.upper()))


def read_offline(path, sym):
    """Eine gespeicherte Yahoo-Chart-Datei (.json oder .json.gz) oder ein Ordner mit <SYM>-60d5m.json(.gz)."""
    if os.path.isdir(path):
        for name in ("%s-60d5m.json" % sym.upper(), "%s-60d5m.json.gz" % sym.upper()):
            if os.path.exists(os.path.join(path, name)):
                path = os.path.join(path, name)
                break
        else:
            raise TMError("kein %s-60d5m.json(.gz) in %s" % (sym.upper(), path))
    if not os.path.exists(path):
        raise TMError("keine Offline-Chartdatei %s" % path)
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    except OSError as e:
        raise TMError("%s ist nicht lesbar: %s" % (path, e))


def chart_result(text, sym):
    try:
        data = json.loads(text)
    except ValueError:
        raise TMError("Yahoo hat für %s etwas geliefert, das kein JSON ist" % sym.upper())
    chart = data.get("chart") if isinstance(data, dict) else None
    if not isinstance(chart, dict):
        raise TMError("Yahoo hat für %s etwas Unerwartetes geliefert" % sym.upper())
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise TMError("Yahoo hat keine Daten für %s: %s" % (sym.upper(), err.get("description") or "unbekanntes Symbol"))
    return res[0]


def parse_bars(result, now_utc):
    """Yahoo-Chart -> (meta, bars, dropped). Nur 5-Minuten-Kerzen der regulären Sitzung,
    älteste zuerst, Slots in Ortszeit des aktuellen Marktes. Verworfen: Kerzen ohne Kurs,
    Kerzen neben dem 5-Minuten-Raster (der Live-Tick), noch nicht fertige Kerzen (jetzt <
    Start + 5 Minuten; jetzt ist das frühere von --now und regularMarketTime der Daten) und
    Kerzen außerhalb der Handelszeit."""
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    cols = [q.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
    as_of = now_utc
    rmt = meta.get("regularMarketTime")
    if isinstance(rmt, (int, float)) and utc_of(rmt) < as_of:
        as_of = utc_of(rmt)
    first, n_bars = open_min(), session_bars()
    dropped = {"no_price": 0, "off_grid": 0, "not_complete": 0, "outside_hours": 0}
    bars = {}
    for i, ts in enumerate(stamps):
        o, h, l, c, v = [col[i] if i < len(col) else None for col in cols]
        if ts is None or None in (o, h, l, c):
            dropped["no_price"] += 1
            continue
        ts = int(ts)
        if ts % INTERVAL:
            dropped["off_grid"] += 1
            continue
        start = utc_of(ts)
        local = markt.to_local(start)
        mins = local.hour * 60 + local.minute - first
        if mins < 0 or mins >= n_bars * 5:
            dropped["outside_hours"] += 1
            continue
        if start + datetime.timedelta(seconds=INTERVAL) > as_of:
            dropped["not_complete"] += 1
            continue
        bars[ts] = {"date": local.date().isoformat(), "slot": mins // 5, "start": local.strftime("%H:%M"),
                    "o": o, "h": h, "l": l, "c": c, "v": v or 0}
    return meta, [bars[t] for t in sorted(bars)], dropped


def split_sessions(bars):
    """{date: {slot: bar}}."""
    days = {}
    for b in bars:
        days.setdefault(b["date"], {})[b["slot"]] = b
    return days


def full_sessions(days, before):
    """Volle Sitzungen (alle Kerzen des Marktes) strikt vor dem Tag des Plans, älteste zuerst,
    und die ausgelassenen kurzen (verkürzte Tage, Lücken)."""
    n_bars = session_bars()
    full, short = [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        if len(s) == n_bars:
            full.append((d, [s[i] for i in range(n_bars)]))
        else:
            short.append({"date": d, "bars": len(s)})
    return full, short


# ---------------------------------------------------------------- the simulation (sim.py)

def build_pool(sessions):
    """pool[i] = Kerze i jeder vergangenen Sitzung als (o, h, l, c) / Schluss von Kerze i-1, nach Datum."""
    n_bars = len(sessions[0][1]) if sessions else session_bars()
    pool = [[] for _ in range(n_bars)]
    for _, D in sessions:
        for i in range(1, n_bars):
            pc = D[i - 1]["c"]
            pool[i].append((D[i]["o"] / pc, D[i]["h"] / pc, D[i]["l"] / pc, D[i]["c"] / pc))
    return pool


def pct(a, q):
    return a[min(len(a) - 1, int(q * len(a)))]


def simulate(pool, entry, stop, target, k, last, replays=10000, seed=19, window=2, side="buy"):
    """Monte-Carlo-Durchläufe der Kerzen k+1..last. Gleiche Züge und Reihenfolge wie sim.py."""
    long = side == "buy"
    risk = (entry - stop) if long else (stop - entry)
    r_target = round(((target - entry) if long else (entry - target)) / risk, 4)
    top = len(pool) - 1

    def slot(rng, i):
        return i if window == 0 else min(top, max(1, i + rng.randint(-window, window)))

    rng = random.Random(seed)
    choice = rng.choice
    outcomes, closes, paths = [], [], []
    for n in range(replays):
        p = entry
        outcome = None
        keep = n < SAMPLE_PATHS
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            hi, lo, cl = p * h, p * l, p * c
            if outcome is None:
                if long:
                    if lo <= stop:
                        outcome = "stop"        # both inside one bar: count the loss (conservative)
                    elif hi >= target:
                        outcome = "target"
                else:
                    if hi >= stop:
                        outcome = "stop"
                    elif lo <= target:
                        outcome = "target"
            p = cl
            if keep:
                path.append(round(p, 2))
        outcomes.append(outcome or "close")
        closes.append(p)
        if keep:
            paths.append(path)
    cnt = {x: outcomes.count(x) for x in ("target", "stop", "close")}
    green = sum(1 for o, p in zip(outcomes, closes)
                if o == "target" or (o == "close" and (p > entry if long else p < entry)))
    Rs = [r_target if o == "target" else -1.0 if o == "stop" else ((p - entry) if long else (entry - p)) / risk
          for o, p in zip(outcomes, closes)]
    srt = sorted(closes)
    # percentile bands per bar for the fan chart: a second run of 2,000 paths, same seed
    rng = random.Random(seed)
    choice = rng.choice
    allp = []
    for n in range(BAND_PATHS):
        p = entry
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            p = p * c
            path.append(p)
        allp.append(path)
    bands = []
    for j in range(last - k + 1):
        col = sorted(pp[j] for pp in allp)
        bands.append([round(pct(col, q), 2) for q in BAND_Q])
    lo_, hi_ = pct(srt, 0.01), pct(srt, 0.99)
    W = (hi_ - lo_) / HIST_BINS
    bins = [0] * HIST_BINS
    for c in srt:
        b = int((c - lo_) / W) if W > 0 else 0
        if 0 <= b < HIST_BINS:
            bins[b] += 1
    return {
        "replays": replays, "seed": seed, "window": window, "bars_left": last - k,
        "p_target": round(cnt["target"] / replays, 4), "p_stop": round(cnt["stop"] / replays, 4),
        "p_neither": round(cnt["close"] / replays, 4), "p_green": round(green / replays, 4),
        "median_close": round(pct(srt, 0.5), 2), "p5_close": round(pct(srt, 0.05), 2),
        "p95_close": round(pct(srt, 0.95), 2), "avg_R": round(statistics.mean(Rs), 3),
        "r_at_target": r_target, "band_paths": BAND_PATHS, "bands": bands, "sample_paths": paths,
        "hist": {"lo": round(lo_, 2), "hi": round(hi_, 2), "bins": bins},
    }


# ---------------------------------------------------------------- stop rules and the history replay

def cents_away(x, long):
    """Stop auf den Cent runden, weg vom Einstieg: abwärts beim Kauf, aufwärts beim Verkauf."""
    c = round(x * 100, 4)
    return (math.floor(c) if long else math.ceil(c)) / 100.0


def opening_range(D, n):
    """(Hoch, Tief) der ersten n Kerzen einer Sitzung, als {slot: bar} oder Liste."""
    rows = [D[i] for i in range(n)]
    return max(b["h"] for b in rows), min(b["l"] for b in rows)


def rule_stop(rule, oh, ol, entry, long):
    r = rule["stop_rule"]
    if r == "or_mid":
        return cents_away((oh + ol) / 2, long)
    if r in ("or_low", "or_high"):
        return cents_away(ol if long else oh, long)
    frac = rule["stop_pct"] / 100.0
    return cents_away(entry * (1 - frac) if long else entry * (1 + frac), long)


def history_replay(sessions, rule, last, side="buy"):
    """Die Regel des Plans auf jeder vergangenen vollen Sitzung: Einstieg = die erste Kerze nach
    der Opening Range (ab Eröffnung des Marktes), die jenseits davon schließt (bis zur --until-Kerze),
    dann Stop zuerst, dann Ziel, Kerze für Kerze, sonst der Schluss bei --until."""
    long = side == "buy"
    n = rule["or_minutes"] // 5
    first = open_min()
    trades = []
    for d, D in sessions:
        oh, ol = opening_range(D, n)
        kk = next((i for i in range(n, last + 1) if (D[i]["c"] > oh if long else D[i]["c"] < ol)), None)
        if kk is None:
            continue
        e = round(D[kk]["c"], 2)
        s = rule_stop(rule, oh, ol, e, long)
        risk = (e - s) if long else (s - e)
        if risk <= 0:
            continue
        t = round(e + rule["target_r"] * risk, 2) if long else round(e - rule["target_r"] * risk, 2)
        oc = None
        for b in D[kk + 1:last + 1]:
            if (b["l"] <= s) if long else (b["h"] >= s):
                oc = "stop"
                break
            if (b["h"] >= t) if long else (b["l"] <= t):
                oc = "target"
                break
        cl = D[last]["c"]
        R = ((t - e) if long else (e - t)) / risk if oc == "target" else -1.0 if oc == "stop" else \
            ((cl - e) if long else (e - cl)) / risk
        trades.append({"date": d, "time": plan_clock(first + 5 * (kk + 1)), "entry": e, "stop": s, "target": t,
                       "outcome": oc or "close", "R": round(R, 2)})
    return {
        "sessions": len(sessions), "triggered": len(trades),
        "target": sum(1 for x in trades if x["outcome"] == "target"),
        "stop": sum(1 for x in trades if x["outcome"] == "stop"),
        "close": sum(1 for x in trades if x["outcome"] == "close"),
        "green": sum(1 for x in trades if x["R"] > 0),
        "avg_R": round(statistics.mean(x["R"] for x in trades), 3) if trades else None,
        "rule": rule, "trades": trades,
    }


# ---------------------------------------------------------------- the plan

def _num(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise TMError("der Plan braucht eine Zahl für %s, nicht %r" % (what, v))
    if not x > 0 or math.isinf(x):
        raise TMError("%s im Plan muss ein positiver Kurs sein, nicht %r" % (what, v))
    return x


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except ValueError as e:
        raise TMError("%s ist kein gültiges JSON: %s" % (path, e))
    if not isinstance(raw, dict):
        raise TMError("%s ist %s" % (path, what))
    return raw


def load_config(path):
    if not path or not os.path.exists(path):
        return {}
    return read_json(path, "keine Config")


def raw_plan(a, now_utc=None):
    """Der Plan aus --plan (trader/plan.json) oder aus den Flags, noch ungeprüft, und seine Quelle."""
    if a.symbol:
        missing = [f for f in ("entry", "stop", "target", "entry_time") if getattr(a, f) is None]
        if missing:
            raise TMError("mit --symbol bitte auch %s angeben" % ", ".join("--" + m.replace("_", "-") for m in missing))
        raw = {"symbol": a.symbol, "side": a.side, "date": a.date,
               "entry": a.entry, "stop": a.stop, "target": a.target, "entry_time": a.entry_time,
               "setup": a.setup, "opening_range": {"minutes": a.or_minutes}, "stop_rule": a.stop_rule,
               "interval": "5m"}
        return raw, "flags"
    if not os.path.exists(a.plan):
        raise TMError("kein Plan unter %s: erst /dt-ausstieg laufen lassen, oder --symbol --date --entry --stop "
                      "--target --entry-time angeben" % a.plan)
    return read_json(a.plan, "kein Plan"), a.plan


def normalize_plan(raw, src="flags", cfg=None, market=None):
    """Ein Plan (Form von trader/plan.json) -> der geprüfte Plan, den die Zeitmaschine fährt.
    Der Markt kommt aus --market, sonst aus dem Symbol."""
    sym = str(raw.get("symbol") or "").strip().upper()
    if not re.match(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$", sym):
        raise TMError("der Plan braucht ein Symbol (Ticker), nicht %r" % raw.get("symbol"))
    try:
        m = markt.resolve(flag=market, symbols=[sym], cfg=cfg)
    except markt.MarketError as e:
        raise TMError(str(e))
    with markt.using(m):
        return _normalize(raw, src, cfg, sym, m)


def _normalize(raw, src, cfg, sym, m):
    side = str(raw.get("side") or "buy").lower()
    if side not in ("buy", "sell"):
        raise TMError("side muss buy oder sell sein, nicht %r" % raw.get("side"))
    interval = str(raw.get("interval") or "5m")
    if interval != "5m":
        raise TMError("nur 5-Minuten-Kerzen (der Plan sagt %s): Yahoo hält 60 Tage 5-Minuten-Kerzen, aber nur "
                      "etwa 7 Tage 1-Minuten-Kerzen, zu wenige Sitzungen für einen fairen Pool" % interval)
    try:
        date = datetime.date.fromisoformat(str(raw.get("date") or "")).isoformat()
    except ValueError:
        raise TMError("der Plan braucht ein Datum wie 2026-10-27, nicht %r" % raw.get("date"))
    entry, stop, target = (_num(raw.get(k), k) for k in ("entry", "stop", "target"))
    long = side == "buy"
    if long and not stop < entry < target:
        raise TMError("ein Kauf braucht Stop < Einstieg < Ziel (hier Stop %s, Einstieg %s, Ziel %s)"
                      % (markt.num(stop), markt.num(entry), markt.num(target)))
    if not long and not target < entry < stop:
        raise TMError("ein Verkauf braucht Ziel < Einstieg < Stop (hier Ziel %s, Einstieg %s, Stop %s)"
                      % (markt.num(target), markt.num(entry), markt.num(stop)))
    first, n_bars = open_min(), session_bars()
    k = None
    if raw.get("entry_time"):
        cmin = parse_clock(raw["entry_time"], "entry_time")
        if (cmin - first) % 5:
            raise TMError("entry_time %s liegt nicht im 5-Minuten-Raster (nimm den Schluss der Kerze, z. B. %s)"
                          % (raw["entry_time"], hm(first + 75)))
        k = (cmin - first) // 5 - 1
    if raw.get("entry_bar") is not None:
        try:
            kb = int(raw["entry_bar"])
        except (TypeError, ValueError):
            raise TMError("entry_bar muss eine Kerzennummer sein, nicht %r" % raw["entry_bar"])
        if k is not None and kb != k:
            raise TMError("der Plan widerspricht sich: entry_bar %d, aber entry_time %s ist Kerze %d"
                          % (kb, raw["entry_time"], k))
        k = kb
    if k is None:
        raise TMError("der Plan braucht entry_time (Schluss der Einstiegskerze, z. B. %s) oder entry_bar"
                      % hm(first + 75))
    if not 0 <= k <= n_bars - 2:
        raise TMError("der Einstieg muss zwischen %s und %s schließen, damit Kerzen zum Durchspielen bleiben "
                      "(hier %s)" % (hm(first + 5), hm(close_min() - 5), hm(first + 5 * (k + 1))))
    orng = raw.get("opening_range") or {}
    or_min = orng.get("minutes", 15) if isinstance(orng, dict) else 15
    try:
        or_min = int(or_min)
    except (TypeError, ValueError):
        raise TMError("opening_range.minutes muss eine Zahl sein")
    if or_min < 5 or or_min % 5 or or_min >= n_bars * 5:
        raise TMError("opening_range.minutes muss ein Vielfaches von 5 sein (hier %s)" % or_min)
    risk = (entry - stop) if long else (stop - entry)
    flat_by = raw.get("flat_by") or markt.windows(cfg)["flat_by"]
    return {
        "symbol": sym, "market": m, "side": side, "date": date, "setup": str(raw.get("setup") or "orb"),
        "entry": entry, "entry_time": plan_clock(first + 5 * (k + 1)), "entry_bar": k,
        "stop": stop, "target": target, "risk_per_share": round(risk, 2),
        "target_r": round(((target - entry) if long else (entry - target)) / risk, 2),
        "opening_range": dict(orng, minutes=or_min) if isinstance(orng, dict) else {"minutes": or_min},
        "stop_rule": str(raw.get("stop_rule") or "auto"), "interval": "5m",
        "flat_by": flat_by, "from": src,
    }


def resolve_rule(plan, entry_day):
    """Die Regel der Rückschau: orb, die Opening Range des Plans, seine Stop-Regel (or_mid,
    or_low / or_high, oder 'pct' = Stop-Abstand des Plans in Prozent vom Einstieg) und sein
    Ziel-R. 'auto' leitet die Stop-Regel aus der Opening Range des Plantags ab. None, wenn
    das Setup kein orb ist."""
    if plan["setup"].lower() != "orb":
        return None
    long = plan["side"] == "buy"
    n = plan["opening_range"]["minutes"] // 5
    rule = {"setup": "orb", "or_minutes": plan["opening_range"]["minutes"], "stop_rule": plan["stop_rule"],
            "target_r": plan["target_r"],
            "stop_pct": round(100.0 * plan["risk_per_share"] / plan["entry"], 4)}
    far = "or_low" if long else "or_high"
    if rule["stop_rule"] == "auto":
        rule["stop_rule"] = "pct"
        if all(i in entry_day for i in range(n)):
            oh, ol = opening_range(entry_day, n)
            if abs(cents_away((oh + ol) / 2, long) - plan["stop"]) < 0.005:
                rule["stop_rule"] = "or_mid"
            elif abs(cents_away(ol if long else oh, long) - plan["stop"]) < 0.005:
                rule["stop_rule"] = far
    elif rule["stop_rule"] in ("or_low", "or_high") and rule["stop_rule"] != far:
        rule["stop_rule"] = "pct"
    elif rule["stop_rule"] not in ("or_mid", far):
        rule["stop_rule"] = "pct"
    if rule["stop_rule"] != "pct":
        del rule["stop_pct"]
    return rule


# ---------------------------------------------------------------- the run

def _until_label(mc):
    return hm(minutes_of(mc.get("until") or clock24(close_min())))


def pc(x):
    return markt.pct(100.0 * x, 1)


def signed(x, nd=3):
    return ("-" if x < 0 else "+") + markt.num(abs(x), nd)


def r_label(r):
    return ("%gR" % round(r, 2)).replace(".", ",")


def lean(mc):
    """(Abstand, Anteil, Break-even): Anteil des Ziels an den Durchläufen, die eine Seite erreicht
    haben, minus dem Anteil, der beim R des Ziels plusminus null ergibt. None ohne Treffer."""
    pt, ps = mc["p_target"], mc["p_stop"]
    if pt + ps <= 0:
        return None
    r = mc.get("r_at_target") or 1.0
    share, even = pt / (pt + ps), 1.0 / (1.0 + r)
    return share - even, share, even


def verdict(mc):
    """Eine Zeile aus den Zahlen, Schwellen siehe Docstring."""
    pt, ps = mc["p_target"], mc["p_stop"]
    lv = lean(mc)
    if lv is None:
        return "Kein Durchlauf erreichte bis %s Ziel oder Stop: der Kurs um %s entscheidet jeden." % (
            _until_label(mc), _until_label(mc))
    d, share, even = lv
    r = mc.get("r_at_target") or 1.0
    one_r = abs(r - 1.0) < 0.005
    if abs(d) < COIN_FLIP:
        head = "Nahe an einem Münzwurf" if one_r else "Nahe am Break-even"
    elif abs(d) < STRONG:
        head = "Neigt zum Ziel" if d > 0 else "Neigt zum Stop"
    else:
        head = "Deutlich Richtung Ziel" if d > 0 else "Deutlich Richtung Stop"
    odds = "Ziel zuerst %s gegen Stop zuerst %s" % (pc(pt), pc(ps))
    if one_r:
        return "%s: %s." % (head, odds)
    return ("%s: bei %s muss das Ziel in %s der Durchläufe, die eine Seite erreichen, zuerst kommen; "
            "es kam in %s zuerst (%s)." % (head, r_label(r), markt.pct(100 * even, 0),
                                           markt.pct(100 * share, 0), odds))


def verdict_notes(mc):
    """Die Zeilen direkt unter dem Urteil, damit nichts einseitig klingt."""
    notes = []
    pn = mc.get("p_neither", 0)
    if pn > MANY_NEITHER and lean(mc) is not None:
        notes.append("%s der Durchläufe erreichten bis %s keine Seite; bei denen entscheidet der Kurs um %s."
                     % (pc(pn), _until_label(mc), _until_label(mc)))
    lv = lean(mc)
    avg = mc.get("avg_R")
    if lv and abs(lv[0]) >= COIN_FLIP and avg is not None and avg != 0 and (avg > 0) != (lv[0] > 0):
        notes.append("Das durchschnittliche R liegt trotzdem bei %s: die Durchläufe ohne Treffer ziehen es "
                     "in die andere Richtung." % signed(avg))
    return notes


def time_machine(text, plan, now_utc, replays=10000, seed=19, window=2, until=None, source="yahoo"):
    """Chart-JSON-Text + geprüfter Plan -> das timemachine.json-Dokument."""
    with markt.using(plan.get("market") or markt.market_of(plan["symbol"])):
        return _time_machine(text, plan, now_utc, replays, seed, window, until, source)


def _time_machine(text, plan, now_utc, replays, seed, window, until, source):
    if not 1 <= replays <= 1000000:
        raise TMError("--replays muss zwischen 1 und 1.000.000 liegen")
    if not 0 <= window <= 10:
        raise TMError("--window muss zwischen 0 und 10 Kerzen liegen")
    sym = plan["symbol"]
    day = datetime.date.fromisoformat(plan["date"])
    sess = markt.session(day) if markt.in_calendar(day) else None
    if markt.in_calendar(day) and sess is None:
        raise TMError("%s ist an %s kein Handelstag (%s)" % (markt.day_label(day), markt.info()["exchange"],
                                                            markt.trading_day(day)[1]))
    result = chart_result(text, sym)
    meta, bars, dropped = parse_bars(result, now_utc)
    msym = str(meta.get("symbol") or "").upper()
    if msym and msym != markt.to_yahoo(sym):
        raise TMError("die Daten sind für %s, der Plan aber für %s" % (msym, sym))
    gran = meta.get("dataGranularity")
    if gran and gran != "5m":
        raise TMError("die Daten haben %s-Kerzen; die Zeitmaschine braucht 5-Minuten-Kerzen" % gran)
    if not bars:
        raise TMError("keine fertigen 5-Minuten-Kerzen für %s in den Daten" % sym)
    first = open_min()
    k = plan["entry_bar"]
    early = bool(markt.early_close(day))
    end_min = (sess[1].hour * 60 + sess[1].minute) if sess else close_min()
    if until is not None and str(until).strip().lower() in FLAT_WORDS:
        until = plan.get("flat_by") or markt.windows()["flat_by"]
    until_min = end_min if until is None else parse_clock(until, "--until")
    if (until_min - first) % 5 or until_min > end_min:
        raise TMError("--until muss im 5-Minuten-Raster liegen und spätestens %s sein%s"
                      % (hm(end_min), " (verkürzter Handelstag)" if early else ""))
    last = (until_min - first) // 5 - 1
    if last <= k:
        raise TMError("--until %s lässt nach dem Einstieg um %s nichts zum Durchspielen"
                      % (hm(until_min), hm(first + 5 * (k + 1))))
    days = split_sessions(bars)
    entry_day = days.get(plan["date"], {})
    if k not in entry_day:
        reason = ("keine Kerzen an dem Tag" if not entry_day else
                  "die Daten enden mit der Kerze %s" % entry_day[max(entry_day)]["start"])
        raise TMError("der Einstieg ist nicht in den Daten: keine fertige Kerze %s (Schluss %s) am %s für %s (%s)"
                      % (clock24(first + 5 * k), hm(first + 5 * (k + 1)), markt.date_de(day), sym, reason))
    eb = entry_day[k]
    warn = []
    if not eb["l"] - 0.01 <= plan["entry"] <= eb["h"] + 0.01:
        warn.append("der Einstieg %s aus dem Plan liegt außerhalb der Spanne dieser Kerze (%s bis %s)"
                    % (markt.num(plan["entry"]), markt.num(eb["l"]), markt.num(eb["h"])))
    sessions, short = full_sessions(days, plan["date"])
    if len(sessions) < MIN_SESSIONS:
        raise TMError("nur %d volle Sitzung(en) von %s vor dem %s in den Daten; die Zeitmaschine braucht "
                      "mindestens %d" % (len(sessions), sym, markt.date_de(day), MIN_SESSIONS))
    pool = build_pool(sessions)
    mc = simulate(pool, plan["entry"], plan["stop"], plan["target"], k, last, replays, seed, window, plan["side"])
    mc = dict(mc, until=clock24(until_min), pool_sessions=len(sessions), pool_from=sessions[0][0],
              pool_to=sessions[-1][0],
              band_times=[clock24(first + 5 * (j + 1)) for j in range(k, last + 1)])
    rule = resolve_rule(plan, entry_day)
    plan_out = {kk: v for kk, v in plan.items() if v is not None}
    if rule:
        plan_out["stop_rule"] = rule["stop_rule"]
        history = history_replay(sessions, rule, last, plan["side"])
    else:
        history = {"sessions": len(sessions), "triggered": 0, "rule": None, "trades": [],
                   "note": "übersprungen: die Rückschau kennt nur den Opening-Range-Breakout (orb), "
                           "das Setup dieses Plans ist %r" % plan["setup"]}
    last_bar = bars[-1]
    return {
        "created_by": "dt-zeitmaschine",
        "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "data": {"symbol": msym or sym, "interval": "5m", "range": "60d",
                 "last_bar": "%s %s %s" % (last_bar["date"], last_bar["start"], markt.info()["suffix"]),
                 "dropped": dropped, "short_sessions_left_out": short},
        "plan": plan_out,
        "mc": mc,
        "history": history,
        "verdict": verdict(mc),
        "verdict_notes": verdict_notes(mc),
        "warnings": warn,
        "note": ("Eine Simulation aus den letzten %d vollen Sitzungen von %s, keine Vorhersage: Zahlen, Nachrichten, "
                 "Ad-hoc-Meldungen und Handelsaussetzungen können tun, was diese Sitzungen nie getan haben. "
                 "Gleicher Seed, gleiche Zahlen." % (len(sessions), sym)),
    }


# ---------------------------------------------------------------- output

def _doc_market(doc):
    p = doc.get("plan") or {}
    return p.get("market") or markt.market_of(p.get("symbol"))


def report(doc):
    with markt.using(_doc_market(doc)):
        return _report(doc)


def _report(doc):
    p, m, h = doc["plan"], doc["mc"], doc["history"]
    long = p["side"] == "buy"
    day = datetime.date.fromisoformat(p["date"])
    first = open_min()
    entry_min = first + 5 * (p["entry_bar"] + 1)
    until_min = minutes_of(m["until"])
    until = hm(until_min)
    sess = markt.session(day)
    end_min = (sess[1].hour * 60 + sess[1].minute) if sess else close_min()
    cur = markt.currency_of(p["symbol"])
    entry_at = markt.clock_both(datetime.datetime.combine(day, datetime.time(*divmod(entry_min, 60))))
    open_words = ("zum Handelsschluss (%s) noch offen" % until) if until_min == end_min else \
        ("um %s noch offen" % until)
    lines = [
        "%s %s, %s: Einstieg %s um %s (Kerze %d), Stop %s, Ziel %s (%s, Risiko %s je Aktie)."
        % (p["symbol"], "Kauf" if long else "Verkauf", markt.day_label(day), markt.num(p["entry"]), entry_at,
           p["entry_bar"], markt.num(p["stop"]), markt.num(p["target"]), r_label(p["target_r"]),
           markt.money(p["risk_per_share"], cur)),
        "%s Durchläufe für den Rest der Sitzung, %s bis %s (%d Fünf-Minuten-Kerzen), Seed %d."
        % (markt.num(m["replays"], 0), hm(entry_min), until, m["bars_left"], m["seed"]),
        "Jede Kerze kommt ganz aus den echten 5-Minuten-Kerzen von %s zur selben Tageszeit (±%d Kerzen), "
        "aus den letzten %d vollen Sitzungen (%s bis %s)."
        % (p["symbol"], m["window"], m["pool_sessions"], markt.date_de(datetime.date.fromisoformat(m["pool_from"])),
           markt.date_de(datetime.date.fromisoformat(m["pool_to"]))),
        "",
        "  Ziel zuerst    %s" % pc(m["p_target"]),
        "  Stop zuerst    %s" % pc(m["p_stop"]),
        "  weder noch     %-8s %s" % (pc(m["p_neither"]), open_words),
        "  im Plus        %-8s Ziel zuerst, oder um %s %s dem Einstieg" % (pc(m["p_green"]), until,
                                                                         "über" if long else "unter"),
        "",
        "  Kurs um %s: Median %s, 90 %% der Durchläufe zwischen %s und %s."
        % (until, markt.num(m["median_close"]), markt.num(m["p5_close"]), markt.num(m["p95_close"])),
        "  Durchschnitt: %s R (R = das Risiko von %s: %s am Ziel, -1R am Stop)."
        % (signed(m["avg_R"]), markt.num(p["risk_per_share"]), "+" + r_label(m["r_at_target"])),
        "",
    ]
    if h.get("rule"):
        ru = h["rule"]
        stop_words = {"or_mid": "an der Range-Mitte", "or_low": "am Range-Tief",
                      "or_high": "am Range-Hoch"}.get(ru["stop_rule"],
                                                      "%s vom Einstieg" % markt.pct(ru.get("stop_pct", 0)))
        if h["triggered"]:
            lines.append("Rückschau: dieselbe Regel (%d-Minuten-Range ab %s, Stop %s, Ziel %s) feuerte in diesen "
                         "%d echten Sitzungen %d-mal: %d Ziel, %d Stop, %d weder noch. Durchschnitt %s R."
                         % (ru["or_minutes"], hm(first), stop_words, r_label(ru["target_r"]), h["sessions"],
                            h["triggered"], h["target"], h["stop"], h["close"], signed(h["avg_R"])))
        else:
            lines.append("Rückschau: dieselbe Regel hat in diesen %d Sitzungen nie gefeuert." % h["sessions"])
    else:
        lines.append("Rückschau: " + h.get("note", "übersprungen."))
    lines += ["", doc["verdict"]] + list(doc.get("verdict_notes") or []) + [""]
    for w in doc.get("warnings") or []:
        lines.append("Hinweis: " + w + ".")
    flat = p.get("flat_by")
    if flat and re.match(r"^\d{2}:\d{2}$", str(flat)) and minutes_of(flat) < until_min:
        lines.append("Glattstellen laut Plan um %s: mit --until glatt endet jeder Durchlauf dort." % hm(minutes_of(flat)))
    short = doc["data"]["short_sessions_left_out"]
    if short:
        lines.append("%d kurze Sitzung(en) ausgelassen (verkürzte Tage oder Lücken): %s."
                     % (len(short), ", ".join(markt.date_de(datetime.date.fromisoformat(x["date"])) for x in short)))
    lines.append(doc["note"] + " Wiederhol den Lauf mit --seed %d." % m["seed"])
    return lines


def render_chart(doc, height=17):
    """ASCII-Fächer der Bänder: eine Spalte je 5-Minuten-Kerze."""
    with markt.using(_doc_market(doc)):
        return _render_chart(doc, height)


def _render_chart(doc, height):
    p, m = doc["plan"], doc["mc"]
    bands, times = m["bands"], m["band_times"]
    lo = min([b[0] for b in bands] + [p["stop"], p["target"]])
    hi = max([b[4] for b in bands] + [p["stop"], p["target"]])
    pad = (hi - lo) * 0.04 or 0.01
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / (height - 1)

    def row(price):
        return max(0, min(height - 1, int(round((hi - price) / step))))
    grid = [[" "] * len(bands) for _ in range(height)]
    for j, b in enumerate(bands):
        r5, r25, r50, r75, r95 = [row(x) for x in b]
        for r in range(r95, r5 + 1):
            grid[r][j] = "."
        for r in range(r75, r25 + 1):
            grid[r][j] = ":"
        grid[r50][j] = "*"
    marks = {row(p["target"]): "target", row(p["stop"]): "stop"}
    if row(p["entry"]) not in marks:
        marks[row(p["entry"])] = "entry"
    for r in (row(p["target"]), row(p["stop"])):
        grid[r] = ["-" if ch == " " else ch for ch in grid[r]]
    words = {"target": "Ziel", "stop": "Stop", "entry": "Einstieg"}
    entry_min = open_min() + 5 * (p["entry_bar"] + 1)
    out = ["%s %s, %s Pfade ab dem Einstieg um %s (Seed %d)" % (
        p["symbol"], markt.date_de(datetime.date.fromisoformat(p["date"])),
        markt.num(m.get("band_paths", BAND_PATHS), 0), hm(entry_min), m["seed"])]
    for r in range(height):
        label = marks.get(r)
        price = {"target": p["target"], "stop": p["stop"], "entry": p["entry"]}.get(label, hi - r * step)
        left = ("%9s |" % markt.num(price)) if (label or r in (0, height - 1)) else "          |"
        out.append(left + "".join(grid[r]) + ("  " + words[label] if label else ""))
    axis = [" "] * len(bands)
    for j in sorted({0, len(bands) // 2, len(bands) - 1}):
        lab = times[j]
        s = max(0, min(j, len(bands) - len(lab)))
        axis[s:s + len(lab)] = list(lab)
    out.append("          +" + "-" * len(bands))
    out.append("           " + "".join(axis) + "  " + markt.info()["suffix"])
    out.append("* Median   : mittlere Hälfte der Pfade   . 90 % der Pfade   - Stop und Ziel")
    return out


# ---------------------------------------------------------------- commands

def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def compute(a):
    cfg = load_config(a.config)
    raw, src = raw_plan(a)
    sym = str(raw.get("symbol") or "").strip().upper()
    try:
        m = markt.resolve(flag=a.market, symbols=[sym], cfg=cfg)
    except markt.MarketError as e:
        raise TMError(str(e))
    markt.use(m)
    now = parse_now(a.now)
    if not raw.get("date"):
        raw = dict(raw, date=markt.to_local(now).date().isoformat())
    plan = normalize_plan(raw, src, cfg, m)
    if a.offline:
        text, source = read_offline(a.offline, plan["symbol"]), "offline"
    else:
        text, source = fetch_chart(plan["symbol"]), "yahoo"
    return time_machine(text, plan, now, a.replays, a.seed, a.window, a.until, source)


def cmd_run(a):
    doc = compute(a)
    if a.write:
        _write(a.write, doc)
    if a.json:
        slim = dict(doc, mc={k: v for k, v in doc["mc"].items() if k != "sample_paths"})
        print(json.dumps(slim, indent=2, ensure_ascii=False))
    else:
        print("\n".join(report(doc)))
        if a.write:
            print("Gespeichert: %s." % a.write)
        print("Weiter: /dt-budget bemisst die Positionsgröße nach deinem Budget und deinem Maximalverlust pro Trade.")
    return 0


def cmd_chart(a):
    if a.from_file:
        if not os.path.exists(a.from_file):
            raise TMError("kein %s: erst timemachine.py run --write ausführen" % a.from_file)
        try:
            with open(a.from_file, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["mc"]["bands"]
        except (ValueError, KeyError, TypeError):
            raise TMError("%s ist kein Ergebnis der Zeitmaschine" % a.from_file)
    else:
        doc = compute(a)
    print("\n".join(render_chart(doc)))
    print("\n".join([doc.get("verdict", "")] + list(doc.get("verdict_notes") or [])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Zeitmaschine: spielt einen geplanten Daytrade durch (dt-zeitmaschine).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--plan", default="trader/plan.json", help="der Plan aus dt-ausstieg")
        p.add_argument("--config", default="trader/config.json", help="Config (Markt, Glattstell-Zeit)")
        p.add_argument("--market", help="xetra oder us (sonst aus dem Symbol)")
        p.add_argument("--symbol", help="oder den Plan als Flags: Symbol, z. B. SAP.DE oder TSLA")
        p.add_argument("--side", default="buy", choices=["buy", "sell"], help="buy = Kauf, sell = Verkauf")
        p.add_argument("--date", help="Tag des Plans, JJJJ-MM-TT (Standard heute, Ortszeit des Marktes)")
        p.add_argument("--entry", type=float, help="Einstiegskurs")
        p.add_argument("--stop", type=float, help="Stop-Kurs")
        p.add_argument("--target", type=float, help="Zielkurs")
        p.add_argument("--entry-time", help="Schluss der Einstiegskerze, z. B. 10:55")
        p.add_argument("--setup", default="orb", help="Setup (die Rückschau kennt orb)")
        p.add_argument("--or-minutes", type=int, default=15, help="Länge der Opening Range in Minuten")
        p.add_argument("--stop-rule", default="auto", choices=["auto", "or_mid", "or_low", "or_high", "pct"],
                       help="Stop-Regel für die Rückschau")
        p.add_argument("--replays", type=int, default=10000, help="Zahl der Durchläufe (Standard 10.000)")
        p.add_argument("--seed", type=int, default=19, help="Startwert des Zufalls (Standard 19)")
        p.add_argument("--window", type=int, default=2, help="aus derselben Tageszeit ± so vielen Kerzen ziehen")
        p.add_argument("--until", help="jeden Durchlauf hier beenden: Uhrzeit oder glatt (Standard Handelsschluss)")
        p.add_argument("--offline", metavar="DATEI", help="gespeichertes Yahoo-Chart-JSON (.json oder .json.gz), "
                                                          "kein Netz")
        p.add_argument("--now", help='so tun, als wäre es jetzt ("2026-10-27 11:00" Ortszeit, oder ISO mit Z)')

    p = sub.add_parser("run", help="den Plan durchspielen: 10.000 simulierte Sitzungen plus Rückschau")
    common(p)
    p.add_argument("--json", action="store_true", help="Ergebnis als JSON ausgeben")
    p.add_argument("--write", nargs="?", const="trader/timemachine.json", metavar="PFAD",
                   help="Ergebnis speichern (Standard trader/timemachine.json)")
    p = sub.add_parser("chart", help="ASCII-Fächer der Durchläufe")
    common(p)
    p.add_argument("--from", dest="from_file", nargs="?", const="trader/timemachine.json", metavar="PFAD",
                   help="ein gespeichertes Ergebnis zeichnen statt neu zu rechnen")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    with markt.restore():
        try:
            return {"run": cmd_run, "chart": cmd_chart}[a.cmd](a)
        except TMError as e:
            print("timemachine.py: %s" % e, file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
