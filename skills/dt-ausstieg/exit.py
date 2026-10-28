#!/usr/bin/env python3
"""Ausstiegsplaner für dt-ausstieg: legt Stop und Ziel fest, BEVOR du
einsteigst, damit du weißt, wann du raus bist. Nur Standardbibliothek. Nur
Longs. Platziert nie eine Order.

    python3 exit.py plan                                    # aus trader/entry.json: Stop Range-Mitte, Ziel 2R
    python3 exit.py plan --stop or-mid --target 1R --write  # TSLA: Stop 358,32 $, Ziel 370,04 $
    python3 exit.py plan --symbol SAP.DE --entry 214.90 --or-high 214.75 --or-low 211.70 --date 2026-10-27
    python3 exit.py plan --stop atr:1.5 --offline SAP.DE.json # ATR braucht die Kerzen der Sitzung
    python3 exit.py plan --symbol NVDA --entry 190.25 --setup level --stop pct:1
    python3 exit.py show                                    # der aktuelle trader/plan.json

Der Markt folgt aus dem Symbol: SAP.DE ist XETRA (EUR, deutsche Zeit),
TSLA ist US (USD, New Yorker Zeit). Zeiten ohne Zone gelten in der Ortszeit
des Markts.

Stops (der Stop eines Longs wird auf den Cent ABgerundet, weg vom Einstieg):
  or-mid     Mitte der Opening Range (Standard bei einem Opening-Range-Ausbruch)
  or-low     Tief der Opening Range
  price:X    dein Kurs
  pct:X      X Prozent unter dem Einstieg
  atr:K      K mal die ATR über 14 Kerzen unter dem Einstieg, auf den Kerzen der
             Sitzung bis zur Einstiegskerze (--offline DATEI oder Yahoo). Gibt es
             bis dahin weniger als 14 Kerzen, mittelt es alle und sagt das.
  Ein Level-Setup hat keinen Standard aus der Opening Range: gib einen Stop an.

Ziele (kaufmännisch auf den Cent gerundet):
  2R (Standard), 1R, 1.5R ...  Einstieg + R x Risiko, Risiko = Einstieg - Stop
  price:X                      dein Kurs

Abgelehnt, mit Grund: ein Stop auf oder über dem Einstieg, ein Ziel auf oder
unter ihm, ein Risiko unter 0,05 % vom Kurs (zu eng für den Spread), eine
entry.json, die nicht ausgelöst hat (außer mit --entry), ein Short (v2 plant
nur Longs).

flat_by (glatt bis): Standard aus markt.windows: XETRA 17:25 Uhr, US 15:55 ET,
oder "flat_by" bzw. "zeiten" in trader/config.json. An einem verkürzten
Handelstag rückt es mit dem Schluss vor (XETRA 30.12.2026 Schluss 14:00:
13:55 Uhr; US Schluss 13:00: 12:55 ET). "min_reward_risk" in der Config
(Standard 1,0) gibt hier nur einen Hinweis; dt-risiko setzt es durch.

Ein Stop ist ein Plan, keine Garantie: eine Kurslücke oder ein schneller
Markt kann darüber hinaus ausführen.
Exit-Codes: plan 0 = ein Plan, 1 = abgelehnt oder Fehler. show 0 = ein Plan liegt vor.
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
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
BACKOFF = 5.0
HOSTS = ("query2", "query1")
INTERVALS = {"1m": 60, "5m": 300}
DEFAULTS = {"min_reward_risk": 1.0}
ATR_BARS = 14
MIN_RISK_PCT = Decimal("0.05")     # risk under 0.05% of the price is inside the spread's noise
CENT = Decimal("0.01")
EPOCH = datetime.datetime(1970, 1, 1)
NOTE = "Ein Stop ist ein Plan, keine Garantie: eine Kurslücke oder ein schneller Markt kann darüber hinaus ausführen."
BROKER_NOTE = ("Der Stop gehört als Stop-Order zu deinem Broker, nicht nur in diesen Plan. Viele Neobroker kennen "
               "keine Bracket- oder OCO-Order: dann legst du nach dem Kauf den Stop beim Broker an und lässt das Ziel "
               "per /dt-alarm beobachten.")


class PlanError(Exception):
    pass


# ---------------------------------------------------------------- time

def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def parse_now(text):
    """--now -> naive UTC. Eine Zeit ohne Offset gilt in der Ortszeit des Markts."""
    if not text:
        return markt.utc_now()
    t = text.strip()
    for suffix in (" ET", " UHR"):
        if t.upper().endswith(suffix):
            t = t[:-len(suffix)].strip()
    if re.match(r"^\d{1,2}:\d{2}$", t):
        t = "%s %s" % (markt.to_local(markt.utc_now()).date().isoformat(), t.zfill(5))
    return markt.parse_now(t, error=PlanError)


def parse_hhmm(text, what):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise PlanError("%s erwartet eine Uhrzeit wie %s (%s), nicht %r"
                        % (what, markt.info()["windows"]["flat_by"], markt.info()["zone"], text))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def parse_clock(text, what):
    """10:15 AM, 10:15, 3:05 PM -> time."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*$", str(text))
    if not m:
        raise PlanError("%s erwartet eine Uhrzeit wie 10:15, nicht %r" % (what, text))
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3):
        if not 1 <= h <= 12:
            raise PlanError("%s erwartet eine Uhrzeit wie 10:15 AM, nicht %r" % (what, text))
        h = h % 12 + (12 if m.group(3).upper() == "PM" else 0)
    if h > 23 or mi > 59:
        raise PlanError("%s erwartet eine Uhrzeit wie 10:15, nicht %r" % (what, text))
    return datetime.time(h, mi)


def hm(t):
    return markt.clock(t)


def ampm(t):
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def entry_clock(t):
    """entry_time in plan.json: "10:15 AM" in New York (wie im Original), "10:55" an XETRA."""
    return ampm(t) if markt.current() == "us" else hm(t)


def at_day(day, t):
    return markt.clock_both(datetime.datetime.combine(day, t))


# ---------------------------------------------------------------- money math (Decimal, to the cent)

def plain_number(text):
    """"207,80", "207.80", "1.234,56", "1,234.56" -> "207.80" ... (Punkt als Dezimalzeichen)."""
    s = str(text).strip().replace("\u20ac", "").replace("$", "").strip()
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return s


def D(x, what="eine Zahl"):
    try:
        if isinstance(x, float):
            return Decimal(repr(x))
        return Decimal(plain_number(x))
    except (InvalidOperation, ValueError):
        raise PlanError("%s ist keine Zahl: %r" % (what, x))


def cents(x):
    """Round half up to the cent."""
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def floor_cents(x):
    """A long's stop: round down, away from the entry."""
    return D(x).quantize(CENT, rounding=ROUND_FLOOR)


def money(x):
    return markt.money(float(D(x).quantize(CENT)))


def money_exact(x):
    """358,325 $: alle Nachkommastellen, für die Rechenwege."""
    cur = markt.info()["currency"]
    return "%s %s" % (num(x), markt.SYMBOLS.get(cur, cur))


def number_arg(text):
    try:
        return float(plain_number(text))
    except ValueError:
        raise argparse.ArgumentTypeError("keine Zahl: %r" % text)


def num(x):
    """1, 1,5, 358,325: eine Dezimalzahl ohne Nullen am Ende, deutsch geschrieben."""
    s = format(D(x).normalize(), "f")
    nd = len(s.partition(".")[2])
    return markt.num(float(s), nd)


def ratio(x):
    """Chance:Risiko für Menschen: 1,0, 1,5, 1,37."""
    s = "%.2f" % float(x)
    s = s[:-1] if s.endswith("0") else s
    return s.replace(".", ",")


NUMBER = r"([0-9][0-9.,]*)"


def parse_stop(text):
    t = str(text).strip().lower()
    if t in ("or-mid", "or_mid", "mid", "or-midpoint", "mitte"):
        return "or_mid", None
    if t in ("or-low", "or_low", "low", "tief"):
        return "or_low", None
    m = re.match(r"^(price|pct|atr):\s*[$\u20ac]?" + NUMBER + r"\s*[$\u20ac%]?$", t)
    if not m:
        raise PlanError("--stop ist or-mid, or-low, price:X, pct:X oder atr:K (bekommen: %r)" % text)
    kind, val = m.group(1), D(m.group(2), "--stop")
    if val <= 0:
        raise PlanError("--stop %s braucht eine Zahl über 0" % kind)
    if kind == "pct" and val >= 100:
        raise PlanError("--stop pct:X braucht X unter 100")
    return kind, val


def parse_target(text):
    t = str(text).strip()
    m = re.match(r"^([0-9]*[.,]?[0-9]+)\s*[Rr]$", t)
    if m:
        r = D(m.group(1), "--target")
        if r <= 0:
            raise PlanError("--target braucht ein R-Vielfaches über 0, etwa 1R oder 2R")
        return "r", r
    m = re.match(r"^price:\s*[$\u20ac]?" + NUMBER + r"\s*[$\u20ac]?$", t.lower())
    if m:
        return "price", D(m.group(1), "--target")
    raise PlanError("--target ist 2R, 1R, 1.5R ... oder price:X (bekommen: %r)" % text)


def r_label(r):
    return "%sR über dem Einstieg" % num(r)


def compute(entry, stop_rule, stop_param, target_rule, target_param, or_high=None, or_low=None,
            atr=None, atr_bars=None):
    """The stop, the target and the risk, in exact cents. Raises PlanError with the reason."""
    e = cents(entry)
    if e <= 0:
        raise PlanError("der Einstiegskurs muss über %s liegen" % money(0))
    detail = ""
    if stop_rule in ("or_mid", "or_low"):
        if or_high is None or or_low is None:
            raise PlanError("ein %s-Stop braucht die Opening Range (--or-high und --or-low)"
                            % stop_rule.replace("_", "-"))
        oh, ol = cents(or_high), cents(or_low)
        if oh <= ol:
            raise PlanError("das Hoch der Opening Range %s muss über ihrem Tief %s liegen" % (money(oh), money(ol)))
        if stop_rule == "or_mid":
            raw = (oh + ol) / 2
            label = "Mitte der Opening Range"
            detail = "(%s + %s) / 2 = %s" % (money(oh), money(ol), money_exact(raw))
        else:
            raw, label = ol, "Tief der Opening Range"
    elif stop_rule == "price":
        raw, label = stop_param, "dein Kurs"
    elif stop_rule == "pct":
        raw = e * (1 - stop_param / 100)
        label = "%s %% unter dem Einstieg" % num(stop_param)
        detail = "%s x (1 - %s %%) = %s" % (money(e), num(stop_param), money_exact(raw))
    elif stop_rule == "atr":
        if atr is None:
            raise PlanError("ein ATR-Stop braucht die Kerzen der Sitzung")
        a = D(round(atr, 6))
        raw = e - stop_param * a
        label = "%s x ATR(%d) unter dem Einstieg" % (num(stop_param), atr_bars)
        detail = "ATR %s über die %d Kerzen bis zum Einstieg%s" % (
            money_exact(a.quantize(Decimal("0.0001"))), atr_bars,
            " (bisher weniger als 14)" if atr_bars < ATR_BARS else "")
    else:
        raise PlanError("unbekannte Stop-Regel %r" % stop_rule)
    stop = floor_cents(raw)
    if stop != D(raw):
        detail = (detail + ", abgerundet" if detail
                  else "%s abgerundet" % money_exact(raw))
    if stop >= e:
        raise PlanError("der Stop %s (%s) liegt auf oder über dem Einstieg %s: bei einem Long gehört der Stop "
                        "unter den Einstieg" % (money(stop), label, money(e)))
    if stop <= 0:
        raise PlanError("der Stop ergibt %s: wähle einen Stop über %s" % (money(stop), money(0)))
    risk = e - stop
    floor_risk = e * MIN_RISK_PCT / 100
    if risk < floor_risk:
        raise PlanError("der Stop liegt nur %s unter dem Einstieg, weniger als 0,05 %% vom Kurs (%s bei %s): zu eng, "
                        "um den Spread zu überstehen, normales Zappeln würde dich ausstoppen. Setz ihn weiter weg."
                        % (money(risk), money(floor_risk.quantize(CENT, rounding=ROUND_HALF_UP)), money(e)))
    if target_rule == "r":
        target = cents(e + target_param * risk)
        t_label = r_label(target_param)
    else:
        target = cents(target_param)
        t_label = None
    if target <= e:
        raise PlanError("das Ziel %s liegt auf oder unter dem Einstieg %s: bei einem Long gehört das Ziel darüber"
                        % (money(target), money(e)))
    rr = ((target - e) / risk).quantize(CENT, rounding=ROUND_HALF_UP)
    if t_label is None:
        t_label = "dein Kurs (%sR)" % ratio(rr)
    return {"entry": e, "stop": stop, "stop_label": label, "stop_detail": detail, "target": target,
            "target_r": target_param if target_rule == "r" else rr, "target_label": t_label,
            "risk": risk, "reward_risk": rr}


# ---------------------------------------------------------------- bars for ATR (same reader as dt-einstieg)

def _open_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _sleep(seconds):
    time.sleep(seconds)


def yahoo_get(path):
    """query2 first, query1 on 429 or 5xx; one retry after a pause on 429."""
    last = "keine Antwort"
    for host in HOSTS:
        url = "https://%s.finance.yahoo.com%s" % (host, path)
        for attempt in (0, 1):
            try:
                return _open_url(url)
            except urllib.error.HTTPError as e:
                code, body = e.code, None
                try:
                    if code == 404:     # Yahoo says why in the body: an unknown ticker
                        body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = None
                finally:
                    e.close()
                if code == 404:
                    if body:
                        return body
                    raise PlanError("Yahoo hat keinen Chart unter %s (HTTP 404)" % url.split("?")[0])
                last = "HTTP %d" % code
                if code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if code == 429 or code >= 500:
                    break
                raise PlanError("Yahoo antwortete mit HTTP %d für %s" % (code, url.split("?")[0]))
            except urllib.error.URLError as e:
                last = "keine Verbindung: %s" % (e.reason,)
                break
            except OSError as e:
                last = "Netzwerkfehler: %s" % (e,)
                break
    raise PlanError("Yahoo hat nicht geantwortet (%s auf query2 und query1): warte eine Minute und versuch es "
                    "noch einmal" % last)


def read_text(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_chart(sym, interval, day, offline=None):
    ysym = markt.to_yahoo(sym)
    if offline:
        path = offline
        if os.path.isdir(offline):
            path = os.path.join(offline, ysym + ".json")
            if not os.path.exists(path):
                path += ".gz"
        if not os.path.exists(path):
            raise PlanError("keine Offline-Datei %s" % path)
        try:
            text = read_text(path)
        except (OSError, ValueError) as e:
            raise PlanError("%s ließ sich nicht lesen: %s" % (path, e))
    else:
        back = (markt.to_local(markt.utc_now()).date() - day).days
        rng = "1d" if back <= 0 else "5d" if back <= 6 else "1mo" if back <= 28 else "60d"
        if interval == "1m" and back > 6:
            raise PlanError("Yahoo hält 1-Minuten-Kerzen nur etwa eine Woche vor")
        text = yahoo_get("/v8/finance/chart/%s?range=%s&interval=%s" % (ysym, rng, interval))
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise PlanError("Yahoo hat für %s etwas Unerwartetes geliefert" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise PlanError("Yahoo hat keine Daten für %s: %s" % (sym, err.get("description") or "unbekanntes Symbol"))
    r = res[0] or {}
    meta = r.get("meta") or {}
    if str(meta.get("symbol") or ysym).upper() != ysym:
        raise PlanError("die Chart-Datei enthält %s, nicht %s" % (meta.get("symbol"), sym))
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0] or {}

    def at(key, i):
        arr = q.get(key) or []
        return arr[i] if i < len(arr) else None

    bars = []
    for i, t in enumerate(r.get("timestamp") or []):
        c = at("close", i)
        if t is None or c is None:
            continue
        h, lo = at("high", i), at("low", i)
        bars.append({"t": int(t), "h": float(c if h is None else h), "l": float(c if lo is None else lo),
                     "c": float(c)})
    return {"bars": bars, "data_time": meta.get("regularMarketTime")}


def session_bars(chart, day, interval, upto_slot=None, now_utc=None):
    """Closed, on-grid bars of one session in the market's local time, oldest first (the live tick is dropped)."""
    step = INTERVALS[interval]
    s = markt.session(day)
    if not s:
        return []
    open_dt = datetime.datetime.combine(day, s[0])
    close_dt = datetime.datetime.combine(day, s[1])
    if now_utc is None and chart.get("data_time"):
        now_utc = utc_of(chart["data_time"])
    local = markt.to_local(now_utc) if now_utc else None
    out = {}
    for b in chart["bars"]:
        if b["t"] % step:
            continue
        lt = markt.to_local(utc_of(b["t"]))
        if lt.date() != day or not (open_dt <= lt < close_dt):
            continue
        if local and lt + datetime.timedelta(seconds=step) > local:
            continue
        slot = int((lt - open_dt).total_seconds()) // step
        if upto_slot is not None and slot > upto_slot:
            continue
        out[slot] = b
    return [out[k] for k in sorted(out)]


def atr_of(bars, n=ATR_BARS):
    """Average true range of the last n bars (all of them if fewer). The first
    bar of the session uses its own high - low (no overnight gap)."""
    trs, prev = [], None
    for b in bars:
        tr = b["h"] - b["l"]
        if prev is not None:
            tr = max(tr, abs(b["h"] - prev), abs(b["l"] - prev))
        trs.append(tr)
        prev = b["c"]
    use = trs[-n:]
    return sum(use) / len(use), len(use)


# ---------------------------------------------------------------- plan

def read_json(path, what):
    if not path or not os.path.exists(path):
        raise PlanError("kein %s unter %s" % (what, path))
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise PlanError("%s ist kein gültiges JSON: %s" % (path, e))


def read_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        doc = read_json(path, "Config")
        if isinstance(doc, dict):
            for k, v in doc.items():
                if v is not None:
                    cfg[k] = v
    return cfg


def resolve_flat_by(day, explicit, cfg, entry_time):
    """(HH:MM, Hinweis). flat_by aus markt.windows; an einem verkürzten Tag rückt es um die
    Differenz zwischen normalem und verkürztem Schluss vor (XETRA 17:25 -> 13:55, US 15:55 -> 12:55)."""
    mk = markt.info()
    t = parse_hhmm(explicit or markt.windows(cfg)["flat_by"], "--flat-by" if explicit else "flat_by")
    note = ""
    s = markt.session(day) if day else None
    if s:
        close_dt = datetime.datetime.combine(day, s[1])
        at = datetime.datetime.combine(day, t)
        if at >= close_dt:
            if explicit:
                raise PlanError("--flat-by %s liegt auf oder nach dem Handelsschluss um %s am %s"
                                % (markt.clock_label(t), markt.clock_label(s[1]), markt.day_label(day)))
            early = markt.early_close(day)
            moved = at - (datetime.datetime.combine(day, mk["close"]) - close_dt)
            if not early or moved.time() <= mk["open"]:
                raise PlanError("flat_by %s aus der Config liegt auf oder nach dem Handelsschluss um %s"
                                % (markt.clock_label(t), markt.clock_label(s[1])))
            t = moved.time()
            note = "vorgezogen wegen des verkürzten Handelstags (Schluss %s, %s)" % (markt.clock_label(s[1]), early)
    if entry_time and entry_time >= t:
        raise PlanError("der Einstieg um %s liegt auf oder nach deinem Glattstellen um %s: es bleibt keine Zeit, "
                        "die Position zu halten" % (markt.clock_label(entry_time), markt.clock_label(t)))
    return hm(t), note


def gather(a):
    """The entry facts, from trader/entry.json or the flags."""
    if a.symbol and a.from_path:
        raise PlanError("nimm --from oder --symbol, nicht beides")
    if a.side in ("sell", "short"):
        raise PlanError("v2 plant nur Longs: kein Stop über einem Short-Einstieg. Plane einen Kauf.")
    if a.symbol:
        if a.entry is None:
            raise PlanError("--symbol braucht --entry KURS")
        if (a.or_high is None) != (a.or_low is None):
            raise PlanError("gib --or-high und --or-low zusammen an, oder keins von beiden")
        info = {"symbol": a.symbol.upper(), "entry": a.entry, "setup": a.setup or ("orb" if a.or_high is not None else "level"),
                "date": a.date, "entry_time": a.time, "entry_bar": a.entry_bar, "interval": a.interval or "5m",
                "or_high": a.or_high, "or_low": a.or_low, "or_minutes": a.or_minutes, "source": "flags"}
    else:
        path = a.from_path or "trader/entry.json"
        doc = read_json(path, "Einstieg (starte zuerst /dt-einstieg oder gib --symbol und --entry an)")
        if str(doc.get("side") or "buy").lower() not in ("buy", "long"):
            raise PlanError("%s ist ein %s: v2 plant nur Longs" % (path, doc.get("side")))
        if doc.get("status") != "triggered" and a.entry is None:
            raise PlanError("%s sagt, %s steht auf %s, nicht ausgelöst (triggered): plane, sobald es auslöst, "
                            "oder gib --entry KURS an, um vorauszuplanen"
                            % (path, doc.get("symbol"), doc.get("status") or "unbekannt"))
        orr = doc.get("opening_range") or {}
        info = {"symbol": str(doc.get("symbol") or "").upper(), "entry": a.entry if a.entry is not None else doc.get("price"),
                "setup": a.setup or doc.get("setup") or "orb", "date": a.date or doc.get("date"),
                "entry_time": a.time or (doc.get("time") if a.entry is None else None),
                "entry_bar": a.entry_bar if a.entry_bar is not None else (doc.get("bar_index") if a.entry is None else None),
                "interval": a.interval or doc.get("interval") or "5m",
                "or_high": a.or_high if a.or_high is not None else orr.get("high"),
                "or_low": a.or_low if a.or_low is not None else orr.get("low"),
                "or_minutes": orr.get("minutes") or a.or_minutes, "source": path}
        if not info["symbol"] or info["entry"] is None:
            raise PlanError("%s hat kein Symbol oder keinen Kurs" % path)
    if info["interval"] not in INTERVALS:
        raise PlanError("interval ist 5m oder 1m")
    return info


def build_plan(a, now_utc, info=None, cfg=None):
    info = info or gather(a)
    cfg = cfg if cfg is not None else read_config(a.config)
    stop_text = a.stop
    if not stop_text:
        if info["setup"] != "orb":
            raise PlanError("ein %s-Setup hat keinen Opening-Range-Stop als Standard: gib --stop price:X, pct:X "
                            "oder atr:K an" % info["setup"])
        stop_text = "or-mid"
    stop_rule, stop_param = parse_stop(stop_text)
    target_rule, target_param = parse_target(a.target or "2R")
    day = None
    if info["date"]:
        try:
            day = datetime.date.fromisoformat(str(info["date"]))
        except ValueError:
            raise PlanError("date erwartet JJJJ-MM-TT, nicht %r" % info["date"])
    else:
        day = markt.to_local(now_utc).date()
    entry_time = parse_clock(info["entry_time"], "die Einstiegszeit") if info["entry_time"] else None
    atr = atr_n = None
    if stop_rule == "atr":
        chart = load_chart(info["symbol"], info["interval"], day, a.offline)
        bars = session_bars(chart, day, info["interval"], info["entry_bar"], parse_now(a.now) if a.now else None)
        if len(bars) < 3:
            raise PlanError("ein ATR-Stop braucht mindestens 3 abgeschlossene %s-Kerzen von %s am %s bis zum "
                            "Einstieg; gefunden: %d" % (info["interval"], info["symbol"], markt.date_de(day), len(bars)))
        atr, atr_n = atr_of(bars)
    c = compute(info["entry"], stop_rule, stop_param, target_rule, target_param, info["or_high"], info["or_low"],
                atr, atr_n)
    flat_by, flat_note = resolve_flat_by(day, a.flat_by, cfg, entry_time)
    orr = None
    if info["or_high"] is not None and info["or_low"] is not None:
        orr = {"high": float(cents(info["or_high"])), "low": float(cents(info["or_low"])),
               "minutes": int(info["or_minutes"] or 15)}
    plan = {"created_by": "dt-ausstieg", "symbol": info["symbol"], "side": "buy", "date": day.isoformat(),
            "market": markt.current(), "currency": markt.currency_of(info["symbol"]),
            "setup": info["setup"], "entry": float(c["entry"]),
            "entry_time": entry_clock(entry_time) if entry_time else None,
            "entry_bar": info["entry_bar"], "interval": info["interval"], "opening_range": orr,
            "stop": float(c["stop"]), "stop_rule": stop_rule, "stop_label": c["stop_label"],
            "target": float(c["target"]), "target_r": float(c["target_r"]), "target_label": c["target_label"],
            "risk_per_share": float(c["risk"]), "reward_risk": float(c["reward_risk"]), "flat_by": flat_by,
            "stop_detail": c["stop_detail"], "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "note": NOTE,
            "broker_note": BROKER_NOTE}
    if atr is not None:
        plan["atr"] = round(atr, 4)
        plan["atr_bars"] = atr_n
    warnings = []
    ok, why = markt.trading_day(day)
    if not ok:
        warnings.append("Am %s wird an %s nicht gehandelt (%s)." % (markt.day_label(day), markt.info()["name"], why))
    if flat_note:
        warnings.append("Glatt bis %s: %s." % (markt.clock_label(parse_hhmm(flat_by, "flat_by")), flat_note))
    mrr = cfg.get("min_reward_risk")
    try:
        if mrr is not None and c["reward_risk"] < D(mrr):
            warnings.append("Chance:Risiko %s liegt unter deinem min_reward_risk %s aus der Config: /dt-risiko "
                            "prüft das." % (ratio(c["reward_risk"]), num(D(mrr))))
    except PlanError:
        pass
    today = markt.to_local(now_utc).date()
    if day != today:
        warnings.append("Dieser Plan ist für %s, nicht für heute (%s)." % (markt.day_label(day), markt.day_label(today)))
    return plan, warnings


def describe(plan):
    day = datetime.date.fromisoformat(plan["date"])
    setup = {"orb": "Opening-Range-Ausbruch", "level": "Schlusskurs über einer Marke"}.get(plan["setup"], plan["setup"])
    e = D(plan["entry"])
    risk = D(plan["risk_per_share"])
    pct = (risk / e * 100).quantize(CENT, rounding=ROUND_HALF_UP)
    when = ""
    if plan.get("entry_time"):
        try:
            when = " um %s" % at_day(day, parse_clock(plan["entry_time"], "entry_time"))
        except PlanError:
            when = " um %s" % plan["entry_time"]
        if plan.get("entry_bar") is not None:
            when += ", Kerze %d" % plan["entry_bar"]
    flat = at_day(day, parse_hhmm(plan["flat_by"], "flat_by"))
    out = ["Ausstiegsplan: %s long, %s, %s, %s auf %s" % (
        plan["symbol"], markt.day_label(day), markt.info()["name"], setup,
        "5-Minuten-Kerzen" if plan["interval"] == "5m" else "1-Minuten-Kerzen")]
    out.append("  Einstieg         %s%s" % (money(plan["entry"]), when))
    out.append("  Stop             %s  %s%s" % (money(plan["stop"]), plan["stop_label"],
                                                (": " + plan["stop_detail"]) if plan.get("stop_detail") else ""))
    out.append("  Ziel             %s  %s" % (money(plan["target"]), plan["target_label"]))
    out.append("  Risiko je Aktie  %s (%s vom Einstieg)" % (money(plan["risk_per_share"]), markt.pct(float(pct))))
    out.append("  Chance:Risiko    %s" % ratio(plan["reward_risk"]))
    out.append("  Glatt bis        %s, egal wie es steht: nichts über Nacht halten" % flat)
    out.append("Steht vor dem Einstieg fest. Erreicht der Kurs den Stop, bist du raus; schieb ihn nie weiter weg.")
    out.append(BROKER_NOTE)
    out.append(NOTE)
    return out


def cmd_plan(a):
    info = gather(a)
    cfg = read_config(a.config)
    markt.use_for(info["symbol"])
    now = parse_now(a.now)
    plan, warnings = build_plan(a, now, info, cfg)
    if a.write:
        d = os.path.dirname(a.write)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.write, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    if a.json:
        print(json.dumps(dict(plan, warnings=warnings), indent=2, ensure_ascii=False))
        return 0
    for line in describe(plan):
        print(line)
    for w in warnings:
        print("Hinweis: " + w)
    if a.write:
        print("Geschrieben: %s." % a.write)
    print("Weiter: /dt-zeitmaschine spielt den Plan durch, dann rechnet /dt-budget die Stückzahl zu deinem "
          "Maximalverlust. Es wurde nichts platziert.")
    return 0


def cmd_show(a):
    if not os.path.exists(a.plan):
        print("Noch kein Plan unter %s. Leg einen an: exit.py plan --write" % a.plan)
        return 1
    plan = read_json(a.plan, "Plan")
    for k in ("symbol", "date", "entry", "stop", "target", "risk_per_share", "reward_risk", "flat_by"):
        if plan.get(k) is None:
            raise PlanError("in %s fehlt %r: leg mit exit.py plan --write einen neuen Plan an" % (a.plan, k))
    markt.use(plan.get("market") or markt.market_of(plan["symbol"]))
    if a.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    for line in describe(dict({"setup": "orb", "interval": "5m", "stop_label": "", "target_label": ""}, **plan)):
        print(line)
    today = markt.to_local(parse_now(a.now)).date()
    if plan["date"] != today.isoformat():
        print("Hinweis: Dieser Plan ist für %s, nicht für heute (%s)."
              % (markt.day_label(datetime.date.fromisoformat(plan["date"])), markt.day_label(today)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ausstiegsplaner (dt-ausstieg): Stop und Ziel vor dem Einstieg.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="Stop und Ziel festlegen")
    p.add_argument("--from", dest="from_path", metavar="PFAD", help="entry.json als Grundlage (Standard trader/entry.json)")
    p.add_argument("--symbol", help="z. B. SAP.DE (XETRA) oder TSLA (US)")
    p.add_argument("--entry", type=number_arg, help="Einstiegskurs (oder ein geplanter Kurs zusammen mit --from)")
    p.add_argument("--or-high", type=number_arg, help="Hoch der Opening Range")
    p.add_argument("--or-low", type=number_arg, help="Tief der Opening Range")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--setup", choices=["orb", "level"])
    p.add_argument("--date", help="Handelstag JJJJ-MM-TT (Standard: der des Einstiegs, sonst heute)")
    p.add_argument("--time", help="Einstiegszeit in Ortszeit des Markts, z. B. 10:55 oder 10:15 AM")
    p.add_argument("--entry-bar", type=int)
    p.add_argument("--interval", choices=["5m", "1m"])
    p.add_argument("--side", default="buy", choices=["buy", "long", "sell", "short"], help="v2: nur buy")
    p.add_argument("--stop", help="or-mid (Standard bei orb), or-low, price:X, pct:X, atr:K")
    p.add_argument("--target", help="2R (Standard), 1R, 1.5R, price:X")
    p.add_argument("--flat-by", help="HH:MM in Ortszeit des Markts (Standard: XETRA 17:25, US 15:55)")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--offline", metavar="PFAD", help="gespeichertes Yahoo-Chart-JSON für einen ATR-Stop")
    p.add_argument("--now", help='tu so, als wäre es diese Ortszeit des Markts, z. B. "2026-10-27 10:55"')
    p.add_argument("--write", nargs="?", const="trader/plan.json", metavar="PFAD",
                   help="Plan speichern (Standard trader/plan.json)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="den aktuellen Plan zeigen")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    with markt.restore():
        try:
            return {"plan": cmd_plan, "show": cmd_show}[a.cmd](a)
        except PlanError as e:
            print("exit.py: %s" % e, file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
