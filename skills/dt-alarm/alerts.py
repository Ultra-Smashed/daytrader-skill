#!/usr/bin/env python3
"""Kursalarme und Börsenuhr für dt-alarm (XETRA und US). Nur Standardbibliothek.

    python3 alerts.py clock                          # hat XETRA offen? nächste Eröffnung / Schluss
    python3 alerts.py clock --market us              # dasselbe für NYSE/Nasdaq
    python3 alerts.py quote SAP.DE --write           # Kurse -> trader/prices.json
    python3 alerts.py quote --holdings --write       # jedes Symbol aus Depot und Plan
    python3 alerts.py add --from-plan                # Stop, Ziel und Glattstellen aus trader/plan.json
    python3 alerts.py add --symbol SAP.DE --stop 213.22
    python3 alerts.py add --symbol SAP.DE --target 216.58
    python3 alerts.py add --at 17:25 --label "Glattstellen" --before-close
    python3 alerts.py add --symbol SAP.DE --pct 3
    python3 alerts.py add --opening-bell             # Glocke zur Eröffnung (XETRA 9:00 Uhr, --market us 9:30 ET)
    python3 alerts.py check                          # meldet, was ausgelöst hat, einmal; Exit 1, wenn nichts
    python3 alerts.py check --now "2026-10-27 17:25" --offline tests/fixtures/dt-alarm
    python3 alerts.py list
    python3 alerts.py reset sap.de-plan-stop

Der Markt einer Regel folgt aus ihrem Symbol (SAP.DE = XETRA, TSLA = US) oder
aus "market" in der Regel; Regeln ohne beides (Glocke, Zeitalarm) nehmen
--market, dann "market" in trader/config.json, dann XETRA. Uhrzeiten ("at",
--now ohne Zone) gelten in der Ortszeit dieses Markts.

Regeltypen:
  above / target  der Kurs liegt auf oder über "price"
  below / stop    der Kurs liegt auf oder unter "price"
  pct_move        der Kurs hat sich um "pct" Prozent oder mehr gegenüber dem
                  Vortagesschluss bewegt (oder gegenüber "ref"); "direction": "up" oder "down"
  opening_bell    der Markt hat heute geöffnet (einmal je Handelstag)
  time            die Uhr des Markts hat "at" (HH:MM) an einem Handelstag
                  überschritten (einmal je Handelstag); "before_close": true
                  zieht die Zeit an einem verkürzten Handelstag um den Abstand
                  zum normalen Schluss vor, wenn sie sonst nach dem verkürzten
                  Schluss läge: XETRA 17:25 wird am 30.12.2026 13:55 Uhr,
                  US 15:55 wird an einem 13:00-Schluss 12:55 ET

Eine Regel mit "date" gilt nur an diesem Tag (Ortszeit des Markts; Regeln aus
einem Plan gelten nur am Tag des Plans) und nur mit einem Kurs von diesem Tag. Ein above-/below-Alarm meldet sich
EINMAL und bleibt dann still, bis du ihn zurücksetzt, außer die Regel hat
"rearm": true (dann wird sie wieder scharf, wenn der Kurs zurückkreuzt). Ein
pct_move meldet sich höchstens einmal am Tag.

Kurse (kostenlos, verzögert, inoffiziell; nur für Alarme, nie zum Timen einer Order):
  yahoo   https://query2.finance.yahoo.com/v8/finance/chart/SAP.DE (bei 429
          oder 5xx weiter zu query1; bei 429 ein zweiter Versuch nach einer
          Pause; eine Anfrage je Symbol, eine halbe Sekunde Abstand; Standard).
          XETRA-Kurse bei Yahoo sind etwa 15 Minuten verzögert.
  stooq   https://stooq.com/q/l/?s=tsla.us&f=sd2t2ohlcv&h&e=csv (Stooqs freies
          CSV, nur US; am 13.10.2026 kam 404, bleibt für später). Für XETRA ist
          das Stooq-Symbol nicht geprüft, darum hier nicht eingerichtet.
  --offline ORDNER liest ORDNER/<quelle>-<SYMBOL>.json|csv (oder .json.gz).

Kalender: Handelstage, Feiertage und verkürzte Tage 2026 und 2027 aus markt.py
(XETRA: Deutsche Börse; US: nyse.com). Außerhalb dieser Jahre sagt die Uhr,
dass die Feiertage unbekannt sind.

Ein Alarm ist kein Stop. Der Stop gehört als Order zu deinem Broker.
"""

import argparse
import csv
import datetime
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
PAUSE = 0.5    # seconds between requests: be polite to free endpoints
BACKOFF = 2.0  # seconds to wait before the one retry after a 429
YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
CALENDAR_YEARS = markt.CALENDAR_YEARS
WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
FLAT_LABEL = "Glattstellen vor Handelsschluss"


class AlertError(Exception):
    pass


# ---------------------------------------------------------------- time

def parse_now(text, m=None):
    """ISO-Zeit -> naive UTC. Ohne Offset gilt die Ortszeit des Markts."""
    return markt.parse_now(text, m, error=AlertError)


def _combine(t):
    return datetime.datetime.combine(datetime.date(2000, 1, 1), t)


def market_status(now_utc, m=None):
    mk = markt.info(m)
    key = mk["key"]
    local = markt.to_local(now_utc, key)
    d = local.date()
    ok, reason = markt.trading_day(d, key)
    st = {"market": key, "exchange": mk["name"], "now_local": local.strftime("%Y-%m-%d %H:%M"),
          "now_new_york": markt.to_eastern(now_utc).strftime("%Y-%m-%d %H:%M"),
          "now_berlin": markt.to_berlin(now_utc).strftime("%Y-%m-%d %H:%M"),
          "date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "calendar_known": markt.in_calendar(d),
          "open": False, "reason": reason, "early_close": markt.early_close(d, key)}
    s = markt.session(d, key)
    if s:
        o, c = s
        st["opens"], st["closes"] = markt.clock(o), markt.clock(c)
        if o <= local.time() < c:
            st["open"] = True
            st["reason"] = "regulärer Handel"
        elif local.time() < o:
            st["reason"] = "vor der Eröffnung"
        else:
            st["reason"] = "nach Handelsschluss"
    nd = d if (s and local.time() < s[0]) else d + datetime.timedelta(days=1)
    for _ in range(15):
        if markt.session(nd, key):
            st["next_open"] = "%s %s" % (nd.isoformat(), markt.clock(mk["open"]))
            break
        nd += datetime.timedelta(days=1)
    return st


def _local_dt(text):
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M")


def status_line(st):
    """"XETRA: OFFEN, Di 27.10.2026 10:53 Uhr, regulärer Handel"."""
    local = _local_dt(st["now_local"])
    return "%s: %s, %s %s, %s" % (st["exchange"], "OFFEN" if st["open"] else "geschlossen",
                                   markt.day_label(local.date()), markt.clock_both(local, st["market"]),
                                   st["reason"])


# ---------------------------------------------------------------- quotes

def stooq_url(sym):
    return "https://stooq.com/q/l/?s=%s.us&f=sd2t2ohlcv&h&e=csv" % sym.lower().replace(".", "-")


def yahoo_url(sym, host=YAHOO_HOSTS[0]):
    return "https://%s/v8/finance/chart/%s?range=1d&interval=1d" % (host, markt.to_yahoo(sym))


def parse_stooq(text, sym):
    """Symbol,Date,Time,Open,High,Low,Close,Volume -> quote. N/D means no data."""
    rows = list(csv.DictReader(io.StringIO(text.strip())))
    if not rows:
        raise AlertError("Stooq hat keine Zeilen für %s geliefert" % sym)
    r = {k.strip().lower(): (v or "").strip() for k, v in rows[0].items() if k}
    close = r.get("close", "")
    if not close or close.upper() == "N/D":
        raise AlertError("Stooq hat keine Daten für %s (prüf das Symbol)" % sym)

    def f(k):
        v = r.get(k, "")
        try:
            return float(v)
        except ValueError:
            return None
    return {"symbol": sym.upper(), "price": float(close), "open": f("open"), "high": f("high"),
            "low": f("low"), "prev_close": None, "time": ("%s %s" % (r.get("date", ""), r.get("time", ""))).strip(),
            "currency": markt.currency_of(sym), "source": "stooq"}


def parse_yahoo(text, sym):
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise AlertError("Yahoo hat für %s etwas Unerwartetes geliefert" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise AlertError("Yahoo hat keine Daten für %s: %s" % (sym, err.get("description", "unbekanntes Symbol")))
    m = res[0].get("meta", {})
    price = m.get("regularMarketPrice")
    if price is None:
        raise AlertError("Yahoo hat keinen Kurs für %s" % sym)
    t = m.get("regularMarketTime")
    when = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if t else "")
    q = (res[0].get("indicators", {}).get("quote") or [{}])[0]
    opens = [x for x in (q.get("open") or []) if x is not None]
    return {"symbol": sym.upper(), "price": float(price), "open": opens[0] if opens else None,
            "high": m.get("regularMarketDayHigh"), "low": m.get("regularMarketDayLow"),
            "prev_close": m.get("previousClose") or m.get("chartPreviousClose"), "time": when,
            "currency": m.get("currency") or markt.currency_of(sym), "source": "yahoo"}


_urlopen = urllib.request.urlopen   # tests swap these two
_sleep = time.sleep


def _get(url, timeout=20):
    """(HTTP status, body). A network failure is an AlertError."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with _urlopen(req, timeout=timeout) as r:
            return 200, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        finally:
            try:
                e.close()
            except Exception:
                pass
        return e.code, body
    except urllib.error.URLError as e:
        raise AlertError("%s ist nicht erreichbar: %s" % (url.split("/")[2], e.reason))


def fetch(url, timeout=20):
    code, text = _get(url, timeout)
    if code != 200:
        raise AlertError("%s antwortete mit HTTP %d" % (url.split("?")[0], code))
    return text


def fetch_yahoo(sym, timeout=20):
    """query2 first. A 429 waits BACKOFF seconds and tries once more; a 429 or a 5xx
    after that moves on to query1. A 404 comes back as Yahoo's own error JSON."""
    last = None
    for host in YAHOO_HOSTS:
        url = yahoo_url(sym, host)
        code, text = _get(url, timeout)
        if code == 429:
            _sleep(BACKOFF)
            code, text = _get(url, timeout)
        if code == 200:
            return text
        if code == 404 and text.strip().startswith("{"):
            return text
        last = (url, code)
        if code != 429 and code < 500:
            break
    raise AlertError("%s antwortete mit HTTP %d" % (last[0].split("?")[0], last[1]))


def _offline_text(folder, source, sym):
    ext = "csv" if source == "stooq" else "json"
    base = os.path.join(folder, "%s-%s.%s" % (source, sym, ext))
    if os.path.exists(base):
        with open(base, encoding="utf-8") as fh:
            return fh.read()
    if os.path.exists(base + ".gz"):
        with gzip.open(base + ".gz", "rt", encoding="utf-8") as fh:
            return fh.read()
    raise AlertError("keine Offline-Kursdatei %s" % base)


def get_quotes(symbols, source="yahoo", offline=None, pause=PAUSE):
    """{SYM: quote} and [errors]. One request per ticker, with a pause between."""
    quotes, errors = {}, []
    for i, sym in enumerate(symbols):
        sym = sym.upper()
        try:
            if source == "stooq" and markt.market_of(sym) == "xetra":
                raise AlertError("Stooq ist für XETRA-Werte wie %s nicht eingerichtet: nimm --source yahoo" % sym)
            if offline:
                text = _offline_text(offline, source, sym)
            else:
                if i and pause:
                    _sleep(pause)
                text = fetch(stooq_url(sym)) if source == "stooq" else fetch_yahoo(sym)
            quotes[sym] = parse_stooq(text, sym) if source == "stooq" else parse_yahoo(text, sym)
        except AlertError as e:
            errors.append(str(e))
    return quotes, errors


def quote_when(q, today=None):
    """Die Kurszeit für Menschen, in Ortszeit des Markts: "09:56 Uhr" (mit Datum, wenn nicht von heute)."""
    t = str(q.get("time") or "")
    utc = markt.parse_utc(t) if t.endswith("Z") else None
    if utc is None:
        return t
    m = markt.market_of(q.get("symbol"))
    local = markt.to_local(utc, m)
    out = markt.clock_label(local, m)
    if today is None or local.date().isoformat() != today:
        out = "%s %s" % (markt.day_label(local.date()), out)
    return out


def _quote_on(q, today, m):
    """Is the quote from this local date? A rule with a "date" never rings on another day's price."""
    t = str(q.get("time") or "")
    utc = markt.parse_utc(t) if t.endswith("Z") else None
    return utc is None or markt.to_local(utc, m).date().isoformat() == today


def write_prices(path, quotes, now_utc, source):
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
        except (ValueError, OSError):
            old = {}
    prices = dict(old.get("prices", {}))
    detail = dict(old.get("detail", {}))
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    for s, q in quotes.items():
        prices[s] = q["price"]
        detail[s] = {"prev_close": q.get("prev_close"), "time": q.get("time"), "source": q.get("source"),
                     "fetched": stamp}
    doc = {"as_of": stamp, "source": source,
           "note": ("Verzögerte Kurse für Alarme und zum Prüfen einer Stückzahl (XETRA bei Yahoo etwa 15 Minuten). "
                    "Ausgeführt wird zum Kurs deines Brokers. detail.time ist die Kurszeit, detail.fetched der "
                    "Abruf, beide in UTC."),
           "prices": prices, "detail": detail}
    _write(path, doc)
    return doc


def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def _read(path, default):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise AlertError("%s ist kein gültiges JSON: %s" % (path, e))


# ---------------------------------------------------------------- rules

PRICE_TYPES = {"above", "below", "stop", "target", "pct_move", "opening_bell", "time"}
NO_QUOTE = {"opening_bell", "time"}


def _hhmm(text):
    m = HHMM.match(str(text or "").strip())
    if not m:
        return None
    return datetime.time(int(m.group(1)), int(m.group(2)))


def validate(rule):
    t = rule.get("type")
    if t not in PRICE_TYPES:
        raise AlertError("Regel %s: unbekannter Typ %r" % (rule.get("id"), t))
    if t not in NO_QUOTE and not rule.get("symbol"):
        raise AlertError("Regel %s braucht ein Symbol" % rule.get("id"))
    if t in ("above", "below", "stop", "target") and not isinstance(rule.get("price"), (int, float)):
        raise AlertError("Regel %s braucht einen Kurs als Zahl (price)" % rule.get("id"))
    if t == "pct_move" and not isinstance(rule.get("pct"), (int, float)):
        raise AlertError("Regel %s braucht pct als Zahl" % rule.get("id"))
    if t == "time" and _hhmm(rule.get("at")) is None:
        raise AlertError("Regel %s braucht \"at\" als Uhrzeit wie \"17:25\" (Ortszeit des Markts)" % rule.get("id"))
    if rule.get("date") and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(rule["date"])):
        raise AlertError("Regel %s: date muss JJJJ-MM-TT sein" % rule.get("id"))
    if rule.get("market"):
        try:
            markt.norm(rule["market"])
        except markt.MarketError as e:
            raise AlertError("Regel %s: %s" % (rule.get("id"), e))


def rule_market(rule, default=None):
    """Der Markt einer Regel: "market", sonst aus dem Symbol, sonst der Standard des Laufs."""
    if rule.get("market"):
        return markt.norm(rule["market"])
    if rule.get("symbol"):
        return markt.market_of(rule["symbol"])
    return markt.norm(default) if default else markt.current()


def active(rule, today):
    """A rule with a "date" is watched on that local date only."""
    return not rule.get("date") or str(rule["date"]) == today


def _rang_today(stamp, today, m=None):
    """Did a rule that rang at this UTC stamp ring on this local date of its market?"""
    if not stamp:
        return False
    try:
        utc = datetime.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return stamp[:10] == today
    return markt.to_local(utc, m).date().isoformat() == today


def ring_time(rule, status):
    """Die Zeit, zu der ein Zeitalarm heute klingelt. Mit "before_close" rückt sie an einem verkürzten Tag
    um den Abstand zwischen normalem und verkürztem Schluss vor, falls sie sonst nach dem verkürzten Schluss läge."""
    at = _hhmm(rule.get("at"))
    if rule.get("before_close") and status.get("early_close") and status.get("closes"):
        early = _hhmm(status["closes"])
        if at >= early:
            normal = markt.info(status.get("market"))["close"]
            at = (_combine(at) - (_combine(normal) - _combine(early))).time()
    return at


def _level(x, cur):
    return markt.money_short(float(x), cur)


def evaluate(rules, quotes, status, state, now_utc):
    """Pure function. Returns (rings, new_state). Each ring: {id, symbol, message}.
    status is the clock of the default market; rules of another market get their own."""
    state = json.loads(json.dumps(state or {}))
    rung = state.setdefault("rung", {})
    default = status.get("market") or markt.current()
    statuses = {default: status}
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    rings = []
    for r in rules:
        validate(r)
        rid = r.get("id") or "%s-%s" % (r.get("symbol", "market"), r["type"])
        m = rule_market(r, default)
        if m not in statuses:
            statuses[m] = market_status(now_utc, m)
        st = statuses[m]
        today = st["date"]
        if not active(r, today):
            continue
        local = markt.to_local(now_utc, m)
        typ = {"stop": "below", "target": "above"}.get(r["type"], r["type"])
        if typ == "opening_bell":
            if st["open"] and not _rang_today(rung.get(rid), today, m):
                early = ""
                if st.get("early_close"):
                    early = ", heute verkürzt bis %s (%s)" % (markt.clock_label(_hhmm(st["closes"]), m),
                                                              st["early_close"])
                rings.append({"id": rid, "symbol": "", "message": "Glocke: %s ist offen (%s %s)%s." % (
                    st["exchange"], markt.day_label(local.date()), markt.clock_both(local, m), early)})
                rung[rid] = stamp
            continue
        if typ == "time":
            at = ring_time(r, st)
            if st.get("opens") and local.time() >= at and not _rang_today(rung.get(rid), today, m):
                label = r.get("label") or "Zeitalarm"
                msg = "%s%s: es ist %s, gestellt war %s." % (label[:1].upper(), label[1:],
                                                            markt.clock_both(local, m), markt.clock_label(at, m))
                msg += (" Der Handel endet um %s." % markt.clock_label(_hhmm(st["closes"]), m)) if st["open"] \
                    else " Der Handel ist schon geschlossen."
                sym = str(r.get("symbol") or "").upper()
                if sym:
                    msg += (" Falls %s noch offen ist, schließ die Position: dt-broker flatten --symbol %s baut das "
                            "Verkaufsticket, dann /dt-risiko und dein „ja“." % (sym, sym))
                rings.append({"id": rid, "symbol": sym, "message": msg})
                rung[rid] = stamp
            continue
        sym = r["symbol"].upper()
        q = quotes.get(sym)
        if not q or (r.get("date") and not _quote_on(q, today, m)):
            continue
        p = q["price"]
        cur = q.get("currency") or markt.currency_of(sym)
        when = quote_when(q, today)
        last = "zuletzt %s%s" % (markt.money(p, cur), (" um " + when) if when else "")
        if typ in ("above", "below"):
            hit = p >= r["price"] if typ == "above" else p <= r["price"]
            if hit and rid not in rung:
                what = {"stop": "den Stop", "target": "das Ziel", "above": "deine obere Alarmmarke",
                        "below": "deine untere Alarmmarke"}[r["type"]]
                rings.append({"id": rid, "symbol": sym, "message": "%s hat %s %s erreicht (%s)%s." % (
                    sym, what, _level(r["price"], cur), last, (", " + r["note"]) if r.get("note") else "")})
                rung[rid] = stamp
            elif not hit and rid in rung and r.get("rearm"):
                del rung[rid]
        elif typ == "pct_move":
            ref = r.get("ref") or q.get("prev_close") or q.get("open")
            if not ref:
                continue
            move = 100.0 * (p / float(ref) - 1)
            want = r.get("direction")
            hit = abs(move) >= r["pct"] and (not want or (want == "up") == (move > 0))
            if hit and not _rang_today(rung.get(rid), today, m):
                rings.append({"id": rid, "symbol": sym, "message": "%s hat sich um %s bewegt, auf %s (von %s; %s)." % (
                    sym, markt.pct(move, sign=True), markt.money(p, cur), markt.money(float(ref), cur), last)})
                rung[rid] = stamp
    state["last_check"] = stamp
    return rings, state


def _n(x):
    x = float(x)
    return str(int(x)) if x == int(x) else "%.2f" % x


def plan_market(plan):
    if plan.get("market"):
        return markt.norm(plan["market"])
    return markt.market_of(plan.get("symbol"))


def rules_from_plan(plan, cfg=None):
    """trader/plan.json -> ein Stop-, ein Ziel- und ein Glattstell-Alarm, für den Tag des Plans.
    flat_by: aus dem Plan, sonst markt.windows(cfg) für den Markt des Plans (XETRA 17:25, US 15:55)."""
    if not isinstance(plan, dict) or not plan.get("symbol"):
        raise AlertError("der Plan hat kein Symbol (starte zuerst /dt-ausstieg)")
    sym = str(plan["symbol"]).upper()
    m = plan_market(plan)
    out = []
    for key, typ, word, missing in (("stop", "stop", "Plan-Stop", "keinen Stop"),
                                    ("target", "target", "Plan-Ziel", "kein Ziel")):
        v = plan.get(key)
        if not isinstance(v, (int, float)) or v <= 0:
            raise AlertError("der Plan hat %s (starte /dt-ausstieg)" % missing)
        label = plan.get("%s_label" % key)
        out.append({"id": "%s-plan-%s" % (sym.lower(), key), "symbol": sym, "type": typ, "price": float(v),
                    "note": word + (": " + label if label else "")})
    flat = plan.get("flat_by") or markt.windows(cfg if isinstance(cfg, dict) else {}, m)["flat_by"]
    if _hhmm(flat) is None:
        raise AlertError("flat_by %r im Plan ist keine Uhrzeit wie 17:25" % flat)
    out.append({"id": "%s-flat-by" % sym.lower(), "symbol": sym, "type": "time", "at": flat,
                "label": FLAT_LABEL, "before_close": True})
    if plan.get("date"):
        for r in out:
            r["date"] = str(plan["date"])
    return out


# ---------------------------------------------------------------- commands

def holdings(a):
    syms = []
    pf = _read(a.portfolio, {})
    for p in pf.get("positions", []) if isinstance(pf, dict) else []:
        syms.append(str(p.get("ticker") or p.get("symbol") or "").upper())
    plan = _read(a.plan, {})
    if isinstance(plan, dict) and plan.get("symbol"):
        syms.append(str(plan["symbol"]).upper())
    return [s for s in syms if s]


def _dedupe(items):
    out = []
    for s in items:
        if s and s not in out:
            out.append(s)
    return out


def _config(a):
    cfg = _read(getattr(a, "config", None), {})
    return cfg if isinstance(cfg, dict) else {}


def default_market(a, rules, cfg):
    """--market, dann der Markt der ersten Regel mit Symbol oder "market", dann config, dann XETRA."""
    if getattr(a, "market", None):
        return markt.norm(a.market)
    for r in rules:
        if r.get("market") or r.get("symbol"):
            return rule_market(r)
    return markt.resolve(cfg=cfg)


def cmd_clock(a):
    m = markt.resolve(flag=a.market, cfg=_config(a))
    st = market_status(parse_now(a.now, m), m)
    mk = markt.info(m)
    if a.json:
        print(json.dumps(st, indent=2, ensure_ascii=False))
    else:
        print(status_line(st) + ".")
        if st.get("opens"):
            print("Heute: %s bis %s%s." % (markt.clock(_hhmm(st["opens"])), markt.clock_label(_hhmm(st["closes"]), m),
                                          (" (verkürzt: %s)" % st["early_close"]) if st.get("early_close") else ""))
        if not st["open"] and st.get("next_open"):
            nxt = _local_dt(st["next_open"])
            print("Nächste Eröffnung: %s %s." % (markt.day_label(nxt.date()), markt.clock_both(nxt, m)))
        if not st["calendar_known"]:
            print("Der Feiertagskalender umfasst nur %s: prüf dieses Datum selbst (%s)."
                  % (" und ".join(map(str, CALENDAR_YEARS)), mk["calendar_source"]))
    return 0 if st["open"] else 1


def cmd_quote(a):
    syms = _dedupe([s.upper() for s in a.symbols] + (holdings(a) if a.holdings else []))
    if not syms:
        raise AlertError("welche Symbole? alerts.py quote SAP.DE TSLA, oder --holdings")
    m = markt.resolve(flag=a.market, symbols=syms, cfg=_config(a))
    now = parse_now(a.now, m)
    quotes, errors = get_quotes(syms, a.source, a.offline)
    if a.write and quotes:
        write_prices(a.write, quotes, now, a.source)
    if a.json:
        print(json.dumps({"quotes": quotes, "errors": errors}, indent=2, ensure_ascii=False))
    else:
        for s in syms:
            q = quotes.get(s)
            if q:
                cur = q.get("currency") or markt.currency_of(s)
                chg = ""
                if q.get("prev_close"):
                    chg = " (%s zum Vortagesschluss %s)" % (markt.pct(100.0 * (q["price"] / q["prev_close"] - 1),
                                                                      sign=True), markt.money(q["prev_close"], cur))
                print("%-6s %s%s  %s  [%s]" % (s, markt.money(q["price"], cur), chg, quote_when(q), q["source"]))
        for e in errors:
            print("Fehler: " + e)
        if a.write and quotes:
            print("%d Kurs(e) in %s geschrieben." % (len(quotes), a.write))
        print("Kurse sind kostenlos, verzögert und inoffiziell (XETRA bei Yahoo etwa 15 Minuten): nur für Alarme. "
              "Ausgeführt wird zum Kurs deines Brokers.")
    return 0 if quotes else 1


def cmd_check(a):
    doc = _read(a.rules, None)
    if not doc or not doc.get("rules"):
        raise AlertError("keine Regeln in %s: leg welche an mit alerts.py add --from-plan" % a.rules)
    rules = doc["rules"]
    cfg = _config(a)
    dm = default_market(a, rules, cfg)
    now = parse_now(a.now, dm)
    status = market_status(now, dm)
    statuses = {dm: status}
    watched = []
    for r in rules:
        m = rule_market(r, dm)
        if m not in statuses:
            statuses[m] = market_status(now, m)
        if active(r, statuses[m]["date"]):
            watched.append(r)
    syms = _dedupe([str(r.get("symbol", "")).upper() for r in watched if r.get("type") not in NO_QUOTE])
    quotes, errors = (get_quotes(syms, a.source, a.offline) if syms else ({}, []))
    state = _read(a.state, {})
    rings, state = evaluate(rules, quotes, status, state, now)
    if not a.no_write:
        _write(a.state, state)
        if quotes:
            write_prices(a.prices_out, quotes, now, a.source)
    if a.json:
        print(json.dumps({"market": status, "markets": statuses, "rings": rings, "errors": errors,
                          "quotes": {s: q["price"] for s, q in quotes.items()}}, indent=2, ensure_ascii=False))
    else:
        for m in sorted(statuses, key=lambda k: k != dm):
            print(status_line(statuses[m]) + ".")
        for r in rings:
            print("ALARM: " + r["message"])
        if not rings:
            print("Nichts ausgelöst. %d Regel(n) heute beobachtet%s." % (
                len(watched), (", " + ", ".join("%s %s" % (s, markt.money(quotes[s]["price"], quotes[s].get("currency")
                                                                         or markt.currency_of(s)))
                                                 for s in syms if s in quotes)) if quotes else ""))
        for e in errors:
            print("Fehler: " + e)
        if rings:
            print("Ein Alarm ist eine Information, keine Order, und kein Stop: der Stop gehört als Order zu deinem "
                  "Broker. Prüf deine Position beim Broker und trag eine Ausführung ein (ticket.py fill). Selbst "
                  "schließen: ticket.py flatten, dann /dt-risiko und dein „ja“.")
    return 0 if rings else 1


def _rule_json(r):
    return json.dumps(r, ensure_ascii=False)


def cmd_add(a):
    doc = _read(a.rules, {"rules": []})
    doc.setdefault("rules", [])
    cfg = _config(a)
    if a.from_plan:
        plan = _read(a.plan, None)
        if plan is None:
            raise AlertError("kein Plan unter %s (starte zuerst /dt-ausstieg)" % a.plan)
        new = rules_from_plan(plan, cfg)
        ids = {r["id"] for r in new}
        doc["rules"] = [r for r in doc["rules"] if r.get("id") not in ids] + new
        state = _read(a.state, {})
        if state.get("rung"):
            for i in ids:
                state["rung"].pop(i, None)
            _write(a.state, state)
        _write(a.rules, doc)
        for r in new:
            print("Angelegt %s: %s" % (r["id"], _rule_json(r)))
        m = plan_market(plan)
        with markt.using(m):
            cur = str(plan.get("currency") or markt.currency_of(plan["symbol"]))
            try:
                day = " am %s" % markt.day_label(datetime.date.fromisoformat(str(plan.get("date"))))
            except ValueError:
                day = ""
            print("%s%s: Stop %s, Ziel %s, glatt bis %s." % (
                new[0]["symbol"], day, markt.money(new[0]["price"], cur), markt.money(new[1]["price"], cur),
                markt.clock_label(_hhmm(new[2]["at"]), m)))
        print("Führe alerts.py check alle paar Minuten aus, solange der Trade läuft (geplante Aufgabe oder /loop). "
              "Kostenlose Kurse sind verzögert (XETRA bei Yahoo etwa 15 Minuten). Ein Alarm ist kein Stop: "
              "der Stop gehört als Order zu deinem Broker.")
        return 0
    if a.opening_bell:
        rule = {"id": a.id or "opening-bell", "type": "opening_bell",
                "market": markt.resolve(flag=a.market, cfg=cfg)}
    elif a.at:
        if _hhmm(a.at) is None:
            raise AlertError("--at erwartet eine Uhrzeit wie 17:25 (Ortszeit des Markts)")
        rule = {"id": a.id or ("time-%s" % a.at.replace(":", "")), "type": "time", "at": a.at,
                "label": a.label or "Zeitalarm"}
        if a.symbol:
            rule["symbol"] = a.symbol.upper()
        if a.market or not a.symbol:
            rule["market"] = markt.resolve(flag=a.market, cfg=cfg)
        if a.before_close:
            rule["before_close"] = True
    else:
        if not a.symbol:
            raise AlertError("--symbol fehlt (oder --from-plan, --at, --opening-bell)")
        sym = a.symbol.upper()
        if a.above is not None:
            rule = {"type": "above", "price": a.above}
        elif a.below is not None:
            rule = {"type": "below", "price": a.below}
        elif a.stop is not None:
            rule = {"type": "stop", "price": a.stop}
        elif a.target is not None:
            rule = {"type": "target", "price": a.target}
        elif a.pct is not None:
            rule = {"type": "pct_move", "pct": a.pct}
            if a.direction:
                rule["direction"] = a.direction
        else:
            raise AlertError("gib eins von --above, --below, --stop, --target oder --pct an")
        val = rule.get("price", rule.get("pct"))
        rule = dict({"id": a.id or ("%s-%s-%s" % (sym.lower(), rule["type"], _n(val)))}, symbol=sym, **rule)
        if a.rearm:
            rule["rearm"] = True
        if a.note:
            rule["note"] = a.note
    if a.date:
        rule["date"] = a.date
    validate(rule)
    if any(r.get("id") == rule["id"] for r in doc["rules"]):
        raise AlertError("eine Regel mit der id %s gibt es schon" % rule["id"])
    doc["rules"].append(rule)
    _write(a.rules, doc)
    print("Angelegt %s: %s" % (rule["id"], _rule_json(rule)))
    return 0


def cmd_list(a):
    doc = _read(a.rules, {"rules": []})
    state = _read(a.state, {})
    if not doc.get("rules"):
        print("Noch keine Regeln.")
        return 1
    for r in doc["rules"]:
        rid = r.get("id")
        rung = state.get("rung", {}).get(rid)
        print("%-24s %s%s" % (rid, json.dumps({k: v for k, v in r.items() if k != "id"}, ensure_ascii=False),
                              ("  (ausgelöst %s)" % rung) if rung else ""))
    return 0


def cmd_reset(a):
    state = _read(a.state, {})
    if a.id not in state.get("rung", {}):
        print("%s hat nicht ausgelöst (nichts zurückzusetzen)." % a.id)
        return 1
    del state["rung"][a.id]
    _write(a.state, state)
    print("Wieder scharf: %s." % a.id)
    return 0


def _price_arg(text):
    v = markt.parse_number(text)
    if v is None:
        raise argparse.ArgumentTypeError("keine Zahl: %r" % text)
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kursalarme und Börsenuhr (dt-alarm), XETRA und US.")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--market", help="xetra oder us (für Regeln ohne Symbol und --now ohne Zone)")
        p.add_argument("--config", default="trader/config.json")

    def net(p):
        p.add_argument("--source", default="yahoo", choices=["yahoo", "stooq"])
        p.add_argument("--offline", metavar="ORDNER", help="<quelle>-<SYMBOL>.json|csv lesen, kein Netz")
        p.add_argument("--now", help="tu so, als wäre es diese Zeit (ohne Offset: Ortszeit des Markts)")
        p.add_argument("--json", action="store_true")
        common(p)

    p = sub.add_parser("clock", help="hat der Markt offen?")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    common(p)
    p = sub.add_parser("quote", help="die letzten verzögerten Kurse")
    net(p)
    p.add_argument("symbols", nargs="*")
    p.add_argument("--holdings", action="store_true", help="Symbole aus Depot und Plan dazunehmen")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--write", nargs="?", const="trader/prices.json", metavar="PFAD",
                   help="in prices.json speichern (Standard trader/prices.json)")
    p = sub.add_parser("check", help="alle Regeln prüfen, melden, was ausgelöst hat")
    net(p)
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p.add_argument("--prices-out", default="trader/prices.json")
    p.add_argument("--no-write", action="store_true")
    p = sub.add_parser("add", help="eine Regel anlegen")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p.add_argument("--symbol")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--above", type=_price_arg)
    g.add_argument("--below", type=_price_arg)
    g.add_argument("--stop", type=_price_arg)
    g.add_argument("--target", type=_price_arg)
    g.add_argument("--pct", type=_price_arg)
    g.add_argument("--opening-bell", action="store_true", help="Glocke zur Eröffnung (XETRA 9:00 Uhr, US 9:30 ET)")
    g.add_argument("--at", metavar="HH:MM", help="ein Zeitalarm, Ortszeit des Markts")
    g.add_argument("--from-plan", action="store_true", help="Stop, Ziel und Glattstellen aus dem Plan")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--market", help="xetra oder us (für --opening-bell und --at ohne Symbol)")
    p.add_argument("--config", default="trader/config.json", help="flat_by/zeiten, wenn der Plan keins hat")
    p.add_argument("--label", help="was ein Zeitalarm sagt, z. B. \"Glattstellen\"")
    p.add_argument("--before-close", action="store_true",
                   help="ein Zeitalarm, der an einem verkürzten Handelstag mit dem Schluss vorrückt")
    p.add_argument("--date", help="die Regel nur an diesem Tag beobachten (JJJJ-MM-TT, Ortszeit des Markts)")
    p.add_argument("--direction", choices=["up", "down"])
    p.add_argument("--rearm", action="store_true")
    p.add_argument("--note")
    p.add_argument("--id")
    p = sub.add_parser("list", help="die Regeln auflisten")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p = sub.add_parser("reset", help="eine ausgelöste Regel wieder scharf stellen")
    p.add_argument("id")
    p.add_argument("--state", default="trader/state/alerts.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    with markt.restore():
        try:
            return {"clock": cmd_clock, "quote": cmd_quote, "check": cmd_check, "add": cmd_add,
                    "list": cmd_list, "reset": cmd_reset}[a.cmd](a)
        except (AlertError, markt.MarketError) as e:
            print("alerts.py: %s" % e, file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
