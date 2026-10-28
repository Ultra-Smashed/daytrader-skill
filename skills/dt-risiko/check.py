#!/usr/bin/env python3
"""Risikoprüfung vor dem Trade für dt-risiko. Nur Standardbibliothek, kein Netz.

Liest die vorgeschlagenen Orders (trader/orders.json) und prüft jede gegen
deine Regeln (trader/config.json), dein Konto (trader/portfolio.json), Kurse
(trader/prices.json) und das, was heute schon platziert wurde
(trader/state/broker.json). Jede Order bekommt FREIGABE oder SPERRE (im JSON
PASS / BLOCK) mit Gründen. Die Orders werden der Reihe nach geprüft, als wäre
jede Freigabe ausgeführt, also fallen Käufe auf, die einzeln gehen, zusammen
aber ein Limit reißen.

    python3 check.py                                 # die trader/-Dateien, schreibt trader/state/risk.json
    python3 check.py --now "2026-10-27 09:20"        # Uhr festlegen (Ortszeit des Marktes)
    python3 check.py --orders trader/orders.json --json
    python3 check.py --no-write                      # prüfen, ohne das Ergebnis zu speichern

Markt, Kalender und Zeitfenster folgen dem Symbol jeder Order (SAP.DE ist
XETRA, TSLA ist US). Beträge (Ordergröße, Cash, Position, max. Verlust,
Tagesverlust) zählen in deiner Kontowährung; den Kurs für eine Aktie in
fremder Währung nimmt check.py aus dem Order-Plan (plan.fx, von dt-budget),
sonst aus "fx" in der Config.

Einstieg und Ausstieg. Ein EINSTIEG eröffnet oder vergrößert eine Position. Ein
AUSSTIEG verkleinert nur, was du hältst. Raus muss immer gehen: ein Ausstieg
wird nur auf Format, Wertpapier, Broker und Leerverkauf geprüft; jede andere
Regel wird für ihn zur Warnung.

Was jede Order sperrt:

  Format        Symbol oder side fehlt, qty und notional beide oder keins,
                notional bei etwas anderem als Market/day (Alpacas Regel),
                Limit-Order ohne limit_price, unbekannter Typ; eine Bracket-Order
                ohne ganze Aktien, nicht day / gtc oder ohne ein Bein
  Wertpapier    Optionen (OCC-Symbole) außer mit "allow_options": true; Krypto
                und alles, was keine Aktie und kein ETF ist
  Broker        "broker": "alpaca" mit einem XETRA-Wert (Alpaca handelt nur US)
  Leerverkauf   mehr verkaufen, als du hast, außer mit "allow_short": true

Was einen Einstieg zusätzlich sperrt:

  Sperrliste    ein Ticker auf deiner Liste "blocked"
  Währung       Aktie in fremder Währung ohne Kurs (plan.fx oder "fx")
  Größe         unter min_order, über max_order
  Position      die Aktie wäre über max_position_pct des Kontos
  Cash          der Kauf ginge in den Cash-Puffer oder bräuchte Margin
  Doppelt       gleiches Symbol und gleiche Seite zweimal im Durchlauf oder
                heute schon platziert (trader/state/broker.json)
  Tageslimit    max_orders_per_day Orders heute platziert
  Stop          kein Stop bei "require_stop": true (stop_loss_stop_price der
                Bracket-Order oder Stop im Plan); ein Stop auf der falschen Seite
  Verlust       Aktien x (Einstieg - Stop) x fx (+ Spread-Puffer + Gebühren aus
                dem Plan) über max_loss_per_trade. Der Einstieg ist das Limit
                einer Limit-Order, sonst das HÖHERE aus Einstieg laut Plan und
                frischem Kurs (unter 15 Minuten), damit ein alter Plan das
                Risiko nicht kleinrechnet
  Chance/Risiko (Ziel - Einstieg) / (Einstieg - Stop) unter min_reward_risk
  Tagesverlust  die max. Verluste der heutigen Einstiege plus dieser über
                max_daily_loss (Gewinn oder Verlust, jeder zählt voll)
  Trades        max_trades_per_day Einstiege heute schon platziert
  Zeitfenster   vor no_entries_before oder nach no_entries_after (Ortszeit des
                Marktes: XETRA 09:15 bis 17:00 Uhr, US 09:45 bis 15:30 ET), oder
                die Börse ist zu (Wochenende, Feiertag, außerhalb der Handelszeit;
                an einem verkürzten Tag rückt das Ende des Fensters um die
                gleiche Zeit vor: US 3 Stunden, XETRA 30.12. 3,5 Stunden)
  PDT           nur bei US-Werten und US-Broker ("broker": "alpaca") oder
                ausdrücklich "pdt_guard": true: schon 3 Daytrades in den letzten
                5 Handelstagen (ein 4. löst die Pattern-Day-Trader-Regel aus)

Warnung ohne Sperre: mehr Einstiege in 30 Tagen als trade_frequency_warning.

Exit-Code 0, wenn jede Order frei ist, 1, wenn eine gesperrt ist.
Das Ergebnis geht mit einem Fingerprint jeder Order nach trader/state/risk.json,
damit dt-broker eine Order nur zeigt, wenn GENAU diese Order heute frei war.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

DEFAULTS = {
    "budget": None, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order": 4000,
    "min_order": 5, "max_loss_per_trade": 50, "max_daily_loss": 150, "max_trades_per_day": 3,
    "max_orders_per_day": 10, "min_reward_risk": 1.0, "require_stop": True,
    "paper": True, "blocked": [], "allow_options": False, "allow_margin": False, "allow_short": False,
    "pdt_guard": False, "trade_frequency_warning": 40,
}
ALPACA_FIELDS = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                 "stop_price", "trail_price", "trail_percent", "extended_hours", "client_order_id",
                 "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price", "advanced_instructions")
PRICE_FIELDS = ("qty", "notional", "limit_price", "stop_price", "take_profit_limit_price",
                "stop_loss_stop_price", "stop_loss_limit_price")
TYPES = {"market", "limit", "stop", "stop_limit", "trailing_stop"}
TIFS = {"day", "gtc", "opg", "cls", "ioc", "fok"}
OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
TICKER = re.compile(r"^(?:[A-Z]{1,5}(?:[.\-][A-Z]{1,2})?|[A-Z0-9]{1,6}\.DE)$")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
CENT = 0.005
FRESH_MINUTES = 15
FREQ_DAYS = 30
US_BROKERS = ("alpaca",)
REF_WORDS = {"plan": "Einstieg laut Plan", "price": "letzter Kurs", "limit": "Limit",
             "stop price": "Stop-Preis", "stale price": "alter Kurs"}
SIDE_WORDS = {"buy": "Kauf", "sell": "Verkauf"}
KIND_WORDS = {"entry": "Einstieg", "exit": "Ausstieg"}
VERDICT_WORDS = {"PASS": "FREIGABE", "BLOCK": "SPERRE"}
FREQ_TEXT = ("Sehr häufiges Traden kann steuerlich als gewerblicher Wertpapierhandel gewertet werden; "
             "sprich mit einer Steuerberatung.")


class RiskError(Exception):
    pass


# ---------------------------------------------------------------- time

def parse_now(text, m=None):
    """ISO-Zeit -> naive UTC. Ohne Offset gilt die Ortszeit des Marktes."""
    return markt.parse_now(text, m, error=RiskError)


def parse_utc(text):
    return markt.parse_utc(text)


def hhmm(value, key):
    """"09:45" -> time(9, 45); None oder "" -> None (diese Grenze ist aus)."""
    if value in (None, "", False):
        return None
    m = HHMM.match(str(value).strip())
    if not m:
        raise RiskError("%s muss eine Uhrzeit wie \"09:45\" sein (Ortszeit des Marktes), bekam %r" % (key, value))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def _minus(t, delta):
    return (datetime.datetime.combine(datetime.date(2000, 1, 1), t) - delta).time()


def _now_text(now_local, m=None):
    """"09:44 Uhr" an XETRA, "09:44 ET = 15:44 Uhr" in New York."""
    if markt.info(m)["key"] == "xetra":
        return markt.clock_label(now_local, m)
    de = markt.to_berlin(markt.local_to_utc(now_local, m))
    return "%s = %s Uhr" % (markt.clock_label(now_local, m), markt.clock(de))


def window_check(now_local, c, m=None):
    """Gründe, warum jetzt kein Einstieg geht (Ortszeit des Marktes). Leer, wenn das Fenster aus ist."""
    before = hhmm(c.get("no_entries_before"), "no_entries_before")
    after = hhmm(c.get("no_entries_after"), "no_entries_after")
    if before is None and after is None:
        return [], []
    mk = markt.info(m)
    warns = []
    d, t = now_local.date(), now_local.time().replace(second=0, microsecond=0)
    if not markt.in_calendar(d):
        warns.append("der Feiertagskalender (%s) deckt nur %s ab: prüf den %s selbst"
                     % (mk["exchange"], " und ".join(map(str, markt.CALENDAR_YEARS)), markt.date_de(d)))
    ok, why = markt.trading_day(d, m)
    stamp = "%s %s" % (markt.stamp(now_local), mk["suffix"])
    if not ok:
        return ["Zeitfenster: die Börse ist heute geschlossen (%s, %s)" % (why, stamp)], warns
    open_, close = markt.session(d, m)
    if t < open_ or now_local.time() >= close:
        return ["Zeitfenster: die Börse ist geschlossen (%s; Handel %s bis %s)"
                % (stamp, markt.clock(open_), markt.clock_label(close, m))], warns
    early = markt.early_close(d, m)
    if early and after is not None:
        shift = (datetime.datetime.combine(d, mk["close"]) - datetime.datetime.combine(d, close))
        after = _minus(after, shift)
        warns.append("verkürzter Handel heute bis %s (%s): keine neuen Einstiege nach %s"
                     % (markt.clock_label(close, m), early, markt.clock_label(after, m)))
    if before is not None and t < before:
        return ["Zeitfenster: keine neuen Einstiege vor %s (es ist %s)"
                % (markt.clock_label(before, m), _now_text(now_local, m))], warns
    if after is not None and t > after:
        return ["Zeitfenster: keine neuen Einstiege nach %s (es ist %s)"
                % (markt.clock_label(after, m), _now_text(now_local, m))], warns
    return [], warns


def business_days(today, n=5):
    """Die letzten n Handelstage bis einschließlich heute, neuester zuerst (aktueller Markt)."""
    out, d = [], today
    for _ in range(40):
        if markt.trading_day(d)[0]:
            out.append(d.isoformat())
            if len(out) == n:
                break
        d -= datetime.timedelta(days=1)
    return out


# ---------------------------------------------------------------- files and helpers

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise RiskError("%s nicht gefunden: %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise RiskError("%s ist kein gültiges JSON: %s" % (path, e))


def fingerprint(order):
    """Gleiche Funktion in dt-broker/ticket.py: genau die Order, die geprüft wurde."""
    core = {k: order[k] for k in ALPACA_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def money(x, cur):
    return markt.money_short(x, cur)


def _cent(x):
    """Preis auf den Cent, kaufmännisch (366.475 -> 366.48)."""
    return int(float(x) * 100 + 0.5 + 1e-9) / 100.0


def _p(x):
    return markt.num(x)


def _pct(x):
    return markt.num_short(x)


def _num(x):
    x = float(x)
    return markt.num(x, 0) if x == int(x) else markt.num(x, 4).rstrip("0").rstrip(",")


def amount(user, key):
    """Betrag in Kontowährung; liest auch alte *_usd-Schlüssel."""
    return _f(markt.amount(user or {}, key, DEFAULTS.get(key)))


def fx_table(user):
    return {str(k).upper(): _f(v) for k, v in ((user or {}).get("fx") or {}).items() if _f(v)}


def order_fx(plan, inst, acct, table):
    """(Kurs Kontowährung je 1 inst, Quelle) oder (None, None)."""
    if inst == acct:
        return 1.0, ""
    pa = str(plan.get("account_currency") or "").strip().upper()
    pfx = _f(plan.get("fx"))
    if pfx and pfx > 0 and pa in ("", acct):
        return pfx, "Plan"
    if table.get(inst):
        return table[inst], "Config"
    return None, None


def account(cfg, portfolio, prices, acct_cur, table):
    """Startkonto: Cash und Positionswerte in Kontowährung. Ohne Depotdatei
    ein frisches Konto mit dem Budget."""
    warnings = []
    if portfolio is None:
        budget = _f(cfg.get("budget"))
        if not budget:
            raise RiskError("kein trader/portfolio.json und kein Budget in der Config: "
                            "nichts, woran die Orders gemessen werden können")
        return {"cash": budget, "shares": {}, "values": {}}, warnings
    cash = _f(portfolio.get("cash"))
    if cash is None:
        raise RiskError("portfolio.json braucht eine Zahl \"cash\"")
    shares, values = {}, {}
    for p in portfolio.get("positions", []):
        t = str(p.get("ticker") or p.get("symbol") or "").upper()
        if not t:
            continue
        n = _f(p.get("shares", p.get("qty")))
        if n is None:
            n = sum(_f(l.get("shares")) or 0 for l in p.get("lots", []))
        shares[t] = shares.get(t, 0) + n
        inst = markt.currency_of(t)
        rate = 1.0 if inst == acct_cur else table.get(inst)
        if prices.get(t) and rate:
            values[t] = shares[t] * prices[t] * rate
        else:
            basis = sum(_f(l.get("cost")) or 0 for l in p.get("lots", []))
            values[t] = basis
            warnings.append("kein %s für %s: bewertet mit dem Einstandswert %s"
                            % ("Kurs" if not prices.get(t) else "Wechselkurs %s/%s" % (inst, acct_cur), t,
                               money(basis, acct_cur)))
    return {"cash": cash, "shares": shares, "values": values}, warnings


def rec_day(rec):
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


def rec_is_entry(rec):
    """dt-broker schreibt die Art, die dt-risiko vergeben hat; ältere Einträge: ein Kauf ist ein Einstieg."""
    k = rec.get("kind")
    if k:
        return k == "entry"
    return str(rec.get("side", "")).lower() == "buy"


def placed_today(state, today):
    """Orders, die dt-broker heute als platziert eingetragen hat."""
    out = []
    for rec in (state or {}).get("orders", []):
        if rec.get("status") == "placed" and rec_day(rec) == today:
            out.append(rec)
    return out


def entries_in_days(state, today, days=FREQ_DAYS):
    """Platzierte Einstiege in den letzten `days` Kalendertagen bis einschließlich heute."""
    end = datetime.date.fromisoformat(today)
    start = (end - datetime.timedelta(days=days - 1)).isoformat()
    n = 0
    for rec in (state or {}).get("orders", []):
        d = rec_day(rec)
        if rec.get("status") == "placed" and rec_is_entry(rec) and start <= d <= today:
            n += 1
    return n


def day_trades(state, today):
    """Daytrades in den letzten 5 Handelstagen: ein (Tag, Symbol) mit Kauf und
    Verkauf, platziert oder ausgeführt. Ein heute platzierter Einstieg zählt mit:
    er soll bis zum Schluss glatt sein. Gibt (Anzahl, sortierte Liste "Tag SYM")."""
    days = set(business_days(datetime.date.fromisoformat(today)))
    sides = {}
    for rec in (state or {}).get("orders", []):
        if rec.get("status") not in ("placed", "filled"):
            continue
        d = rec_day(rec)
        if d not in days:
            continue
        key = (d, str(rec.get("symbol", "")).upper())
        sides.setdefault(key, set()).add(str(rec.get("side", "")).lower())
        if d == today and rec.get("status") == "placed" and rec_is_entry(rec):
            sides[key].add("pending")
    hits = sorted("%s %s" % k for k, s in sides.items()
                  if ("buy" in s and "sell" in s) or (k[0] == today and "pending" in s))
    return len(hits), hits


def order_market(o):
    plan = o.get("plan") if isinstance(o.get("plan"), dict) else {}
    if plan.get("market"):
        try:
            return markt.norm(plan["market"])
        except markt.MarketError:
            pass
    return markt.market_of(str(o.get("symbol", "")).strip())


# ---------------------------------------------------------------- the check

def check(orders, cfg, portfolio=None, prices=None, state=None, today=None, now=None, price_times=None):
    """Reine Funktion. Gibt {"results": [...], "pass": n, "block": n, "warnings": [...]} zurück.

    cfg          deine Config, wie du sie geschrieben hast
    now          naive UTC (Standard: die echte Uhr); "heute" ist das Datum in Ortszeit des Marktes
    price_times  {SYM: naive UTC-Zeit des Kurses}; None = jeder Kurs gilt als frisch"""
    user = cfg or {}
    first = [str(o.get("symbol", "")).strip() for o in orders if isinstance(o, dict) and o.get("symbol")]
    m = order_market(orders[0]) if orders and isinstance(orders[0], dict) and orders[0].get("symbol") else \
        markt.resolve(symbols=first[:1], cfg=user)
    with markt.using(m):
        return _check(orders, user, portfolio, prices, state, today, now, price_times, m)


def _check(orders, user, portfolio, prices, state, today, now, price_times, m):
    c = dict(DEFAULTS)
    c.update(user)
    acct_cur = markt.account_currency(user)
    table = fx_table(user)
    prices = {str(k).upper(): float(v) for k, v in (prices or {}).items() if _f(v)}
    now_utc = now or markt.utc_now()
    now_local = markt.to_local(now_utc, m)
    today = today or now_local.date().isoformat()
    acct, top_warn = account(c, portfolio, prices, acct_cur, table)
    notes = []
    blocked = {str(b).upper() for b in c.get("blocked") or []}
    broker = str(c.get("broker") or "").strip().lower()
    done_today = placed_today(state, today)
    count_today = len(done_today)
    entries_today = [r for r in done_today if rec_is_entry(r)]
    loss_today = 0.0
    for r in entries_today:
        ml = _f(r.get("max_loss"))
        if ml is None:
            top_warn.append("ein heute platzierter Einstieg (%s %s) hat keinen max. Verlust im Log; zählt nicht "
                            "in den Tagesverlust" % (SIDE_WORDS.get(r.get("side"), r.get("side")), r.get("symbol")))
        else:
            loss_today += ml
    placed_keys = {(str(r.get("symbol", "")).upper(), r.get("side")) for r in done_today}
    windows = {}
    if "pdt_guard" in user:
        pdt_on = bool(user.get("pdt_guard"))
    else:
        pdt_on = broker in US_BROKERS
    pdt_n, pdt_list = day_trades(state, today) if pdt_on and m == "us" else (0, [])
    pdt_used = False
    seen = set()
    results = []
    batch_entries, batch_loss = 0, 0.0
    if not c.get("paper", True):
        top_warn.append("LIVE-Konto (\"paper\": false): diese Orders nutzen echtes Geld")
    freq = int(c.get("trade_frequency_warning") or 0)
    if freq and state:
        n30 = entries_in_days(state, today)
        if n30 > freq:
            top_warn.append("Häufigkeit: %d Einstiege in den letzten %d Tagen, mehr als dein Hinweiswert "
                            "trade_frequency_warning %d. %s" % (n30, FREQ_DAYS, freq, FREQ_TEXT))

    def fresh(sym):
        if sym not in prices:
            return None
        if price_times is None:
            return prices[sym]
        t = price_times.get(sym)
        if t is None:
            return None
        age = (now_utc - t).total_seconds()
        return prices[sym] if -60 <= age <= FRESH_MINUTES * 60 else None

    def window_for(om):
        if om not in windows:
            with markt.using(om):
                windows[om] = window_check(markt.to_local(now_utc, om), markt.windows(user, om), om)
                top_warn.extend(windows[om][1])
        return windows[om][0]

    for i, o in enumerate(orders, 1):
        reasons, warns, info = [], [], []
        later = []                       # nur für Einstiege; bei einem Ausstieg werden sie zu Warnungen
        sym = str(o.get("symbol", "")).strip().upper()
        side = str(o.get("side", "")).strip().lower()
        sw = SIDE_WORDS.get(side, side)
        typ = str(o.get("type", "market")).strip().lower()
        tif = str(o.get("time_in_force", "day")).strip().lower()
        qty, notional = o.get("qty"), o.get("notional")
        plan = o.get("plan") if isinstance(o.get("plan"), dict) else {}
        oc = str(o.get("order_class") or "").strip().lower()
        legs = o.get("take_profit_limit_price") is not None or o.get("stop_loss_stop_price") is not None
        bracket = oc == "bracket" or (not oc and legs)
        om = order_market(o)
        inst = str(plan.get("currency") or markt.currency_of(sym)).strip().upper()
        rate, rate_from = order_fx(plan, inst, acct_cur, table)
        value = value_i = None

        # Format
        if not sym:
            reasons.append("Format: kein Symbol")
        if side not in ("buy", "sell"):
            reasons.append("Format: side muss buy oder sell sein, bekam %r" % o.get("side"))
        if (qty is None) == (notional is None):
            reasons.append("Format: gib genau eins von qty oder notional an")
        for k in PRICE_FIELDS:
            if o.get(k) is not None:
                v = _f(o.get(k))
                if v is None or v <= 0:
                    reasons.append("Format: %s muss eine positive Zahl sein, bekam %r" % (k, o.get(k)))
                elif not isinstance(o.get(k), str):
                    warns.append("schick %s als String (\"%s\"), so wie place_stock_order es erwartet"
                                 % (k, o.get(k)))
        if typ not in TYPES:
            reasons.append("Format: unbekannter Order-Typ %r" % typ)
        if tif not in TIFS:
            reasons.append("Format: unbekanntes time_in_force %r" % tif)
        if notional is not None and (typ != "market" or tif != "day"):
            reasons.append("Format: eine notional-Order (Betrag) muss eine Market-Order mit time_in_force day sein")
        if typ in ("limit", "stop_limit") and o.get("limit_price") is None:
            reasons.append("Format: eine %s-Order braucht einen limit_price" % typ)
        if typ in ("stop", "stop_limit") and o.get("stop_price") is None:
            reasons.append("Format: eine %s-Order braucht einen stop_price" % typ)
        if o.get("extended_hours") and not (typ == "limit" and tif in ("day", "gtc")):
            reasons.append("Format: extended hours braucht eine Limit-Order mit time_in_force day oder gtc")
        if o.get("stop_loss_limit_price") is not None and o.get("stop_loss_stop_price") is None:
            reasons.append("Format: stop_loss_limit_price braucht einen stop_loss_stop_price")
        if bracket:
            if notional is not None:
                reasons.append("Format: eine Bracket-Order braucht ganze Aktien als qty, keinen notional-Betrag")
            elif _f(qty) is not None and abs(_f(qty) - round(_f(qty))) > 1e-9:
                reasons.append("Format: eine Bracket-Order nimmt nur ganze Aktien, bekam qty %r" % qty)
            if tif not in ("day", "gtc"):
                reasons.append("Format: eine Bracket-Order braucht time_in_force day oder gtc, bekam %r" % tif)
            if o.get("take_profit_limit_price") is None or o.get("stop_loss_stop_price") is None:
                reasons.append("Format: eine Bracket-Order braucht take_profit_limit_price und "
                               "stop_loss_stop_price")
        elif oc or o.get("advanced_instructions"):
            warns.append("erweiterte Order (%s): prüf jedes Bein, bevor du ja sagst"
                         % (oc or "advanced_instructions"))

        # Wertpapier und Broker
        if sym and OCC.match(sym.replace(" ", "")):
            if not c.get("allow_options"):
                reasons.append("Wertpapier: %s ist ein Optionskontrakt; Optionen sind aus "
                               "(\"allow_options\": false)" % sym)
            else:
                warns.append("Options-Order: bei Optionen kannst du 100 % des Einsatzes verlieren")
        elif sym and ("/" in sym or not TICKER.match(sym)):
            reasons.append("Wertpapier: %s sieht nicht wie eine Aktie aus; dieses Paket handelt nur Aktien "
                           "und ETFs" % sym)
        if sym and broker in US_BROKERS and om == "xetra":
            reasons.append("Broker: Alpaca handelt keine XETRA-Werte; nimm ibkr oder manuell "
                           "(\"broker\" in trader/config.json)")

        # Referenzpreis: was eine Aktie beim Einstieg kostet (Aktienwährung)
        plan_entry = _f(plan.get("entry"))
        live = fresh(sym)
        ref, ref_from = None, None
        if typ in ("limit", "stop_limit"):
            ref, ref_from = _f(o.get("limit_price")), "limit"
        elif typ == "stop":
            ref, ref_from = _f(o.get("stop_price")), "stop price"
        if ref is None:
            cands = [(p, w) for p, w in ((plan_entry, "plan"), (live, "price")) if p]
            if cands:
                ref, ref_from = max(cands, key=lambda x: x[0])
                ref = _cent(ref)
                if live and ref_from == "price" and plan_entry and live > plan_entry + CENT:
                    info.append("%s zuletzt %s liegt über dem Einstieg laut Plan %s: das Risiko wird ab %s gemessen"
                                % (sym, _p(ref), _p(plan_entry), _p(ref)))
            elif sym in prices:
                ref, ref_from = prices[sym], "stale price"
        if plan_entry and live is None and sym in prices and price_times is not None and typ == "market":
            warns.append("der %s-Kurs in trader/prices.json ist älter als %d Minuten: nicht verwendet"
                         % (sym, FRESH_MINUTES))
        q = _f(qty)
        if notional is not None and _f(notional):
            value_i = _f(notional)
        elif q and ref:
            value_i = q * ref
        if value_i is not None and rate:
            value = value_i * rate

        # Einstieg oder Ausstieg
        held = acct["shares"].get(sym, 0.0)
        held_value = acct["values"].get(sym, 0.0)
        exiting = False
        if side == "sell" and held > 1e-9:
            if q is not None:
                exiting = q <= held + 1e-9
            elif value is not None:
                exiting = value <= held_value + CENT
        elif side == "buy" and held < -1e-9 and q is not None:
            exiting = q <= -held + 1e-9
        kind = "exit" if exiting else "entry"
        if rate is None and sym:
            later.append("Währung: %s notiert in %s, dein Konto ist in %s, und es gibt keinen Wechselkurs "
                         "(plan.fx oder \"fx\" in der Config). Lass /dt-budget die Order neu rechnen oder setz "
                         "\"fx\": {\"%s\": ...} in trader/config.json" % (sym, inst, acct_cur, inst))
        elif kind == "entry" and value_i is None and q:
            later.append("Kurs: kein Kurs für %s, um eine Order über %s Aktien zu bewerten; trag ihn in "
                         "trader/prices.json ein (/dt-alarm: alerts.py quote %s --write)" % (sym, qty, sym))
        if rate is not None and rate != 1.0:
            info.append("Wechselkurs %s %s je 1 %s (aus %s)" % (markt.num(rate, 4), acct_cur, inst, rate_from))

        # Sperrliste und Größe
        if sym in blocked:
            later.append("Sperrliste: %s steht auf deiner Sperrliste" % sym)
        min_order, max_order = amount(user, "min_order"), amount(user, "max_order")
        if value is not None:
            if value < float(min_order or 0) - CENT:
                later.append("Größe: %s liegt unter deiner Mindestorder von %s"
                             % (money(value, acct_cur), money(min_order, acct_cur)))
            if max_order and value > max_order + CENT:
                later.append("Größe: %s liegt über deiner max. Order von %s"
                             % (money(value, acct_cur), money(max_order, acct_cur)))

        # Wirkung aufs Konto, der Reihe nach
        cash = acct["cash"]
        total = cash + sum(acct["values"].values())
        buffer_amt = total * float(c.get("cash_buffer_pct") or 0) / 100.0
        if value is not None and side == "buy" and kind == "entry":
            after_cash = cash - value
            if after_cash < -CENT and not c.get("allow_margin"):
                later.append("Cash: braucht %s, aber nur %s Cash da; das wäre Margin (geliehenes Geld)"
                             % (money(value, acct_cur), money(cash, acct_cur)))
            elif after_cash < buffer_amt - CENT:
                later.append("Cash: lässt %s Cash, unter deinem Puffer von %s %% = %s"
                             % (money(max(after_cash, 0), acct_cur), _pct(c["cash_buffer_pct"]),
                                money(buffer_amt, acct_cur)))
            pos_after = held_value + value
            limit = total * float(c.get("max_position_pct") or 100) / 100.0
            if total > 0 and pos_after > limit + CENT:
                later.append("Position: %s wäre %s, %s des Kontos von %s, über deinem Deckel von %s %%"
                             % (sym, money(pos_after, acct_cur), markt.pct(100.0 * pos_after / total, 1),
                                money(total, acct_cur), _pct(c["max_position_pct"])))
        if side == "sell" and sym and kind == "entry":
            if q is not None:
                over = q > held + 1e-9
            elif value is not None:
                over = value > held_value + CENT
            else:
                over = held <= 0
            if over and not c.get("allow_short"):
                reasons.append("Leerverkauf: du verkaufst mehr %s, als du hast (%s Aktien); Leerverkäufe sind aus. "
                               "Wenn du gekauft hast, trag erst die Ausführung ein (ticket.py fill)" % (sym, _num(held)))

        # Daytrade-Prüfungen: Stop, Verlust, Chance/Risiko, Tagesverlust, Trades, Zeitfenster, PDT
        max_loss = max_loss_i = risk_ps = rr = stop = target = None
        max_loss_cap = amount(user, "max_loss_per_trade")
        daily = amount(user, "max_daily_loss")
        if kind == "entry" and side in ("buy", "sell"):
            long = side == "buy"
            leg_stop, plan_stop = _f(o.get("stop_loss_stop_price")), _f(plan.get("stop"))
            stop = leg_stop if leg_stop else plan_stop
            target = _f(o.get("take_profit_limit_price")) or _f(plan.get("target"))
            if leg_stop and plan_stop and abs(leg_stop - plan_stop) > CENT:
                warns.append("der Bracket-Stop %s weicht vom Stop im Plan %s ab: der Broker nutzt den der "
                             "Bracket-Order" % (_p(leg_stop), _p(plan_stop)))
            if stop and not leg_stop:
                warns.append("der Stop %s steht nur im Plan, nicht beim Broker: setz einen Stop-Alarm "
                             "(/dt-alarm: alerts.py add --from-plan)" % _p(stop))
            if not stop:
                if c.get("require_stop", True):
                    later.append("Stop: kein Stop. Jeder Einstieg braucht einen (\"require_stop\": true): einen "
                                 "stop_loss_stop_price in der Bracket-Order, von /dt-ausstieg und /dt-budget")
                else:
                    warns.append("kein Stop: der max. Verlust ist nicht begrenzt und zählt nicht in den Tagesverlust")
            elif ref:
                if (long and stop >= ref - CENT) or (not long and stop <= ref + CENT):
                    later.append("Stop: der Stop %s muss %s dem Einstieg %s liegen (%s)"
                                 % (_p(stop), "unter" if long else "über", _p(ref), sw))
                else:
                    risk_c = int(round(abs(ref - stop) * 100))
                    risk_ps = risk_c / 100.0
                    shares = q if q is not None else ((value_i or 0) / ref)
                    max_loss_i = round(shares * risk_ps, 2)
                    if rate:
                        spread_pct = _f(plan.get("spread_buffer_pct")) or 0.0
                        fees = _f(plan.get("fees")) or 0.0
                        spread = shares * ref * spread_pct / 100.0
                        max_loss = round((shares * risk_ps + spread) * rate + fees, 2)
                        pml, pmi = _f(plan.get("max_loss")), _f(plan.get("max_loss_instrument"))
                        same_acct = str(plan.get("account_currency") or acct_cur).strip().upper() == acct_cur
                        if pml is not None and pmi is not None and same_acct and abs(pmi - max_loss_i) <= CENT:
                            max_loss = max(max_loss, round(pml, 2))
                        if max_loss_cap and max_loss > max_loss_cap + CENT:
                            how = "%s Aktien × %s Risiko je Aktie" % (_num(shares), _p(risk_ps))
                            if spread_pct:
                                how += " + %s %% Spread-Puffer" % _pct(spread_pct)
                            if rate != 1.0:
                                how += " bei %s %s/%s" % (markt.num(rate, 4), acct_cur, inst)
                            if fees:
                                how += " + %s Gebühren" % money(fees, acct_cur)
                            later.append("Verlust: %s = %s am Stop, über deinem max. Verlust je Trade von %s"
                                         % (how, money(max_loss, acct_cur), money(max_loss_cap, acct_cur)))
                    min_rr = _f(c.get("min_reward_risk"))
                    if target:
                        if (long and target <= ref + CENT) or (not long and target >= ref - CENT):
                            later.append("Ziel: das Ziel %s muss %s dem Einstieg %s liegen"
                                         % (_p(target), "über" if long else "unter", _p(ref)))
                        else:
                            rr = round(int(round(abs(target - ref) * 100)) / float(risk_c), 2)
                            if min_rr and rr < min_rr - 1e-9:
                                later.append("Chance/Risiko: %s (Ziel %s, Einstieg %s, Stop %s) liegt unter deinem "
                                             "Minimum %s" % (markt.num(rr), _p(target), _p(ref), _p(stop),
                                                             _num(min_rr)))
                    elif min_rr:
                        later.append("Chance/Risiko: kein Ziel, an dem es sich messen lässt (min_reward_risk %s)"
                                     % _num(min_rr))
            if daily and max_loss is not None:
                used = loss_today + batch_loss
                if used + max_loss > daily + CENT:
                    later.append("Tagesverlust: %s heute schon im Risiko plus %s für diese = %s, über deinem "
                                 "Tageslimit von %s" % (money(used, acct_cur), money(max_loss, acct_cur),
                                                        money(used + max_loss, acct_cur), money(daily, acct_cur)))
            cap_t = int(c.get("max_trades_per_day") or 0)
            if cap_t and len(entries_today) + batch_entries >= cap_t:
                later.append("Trades: %d Einstiege heute platziert plus %d vorher in diesem Durchlauf freigegeben, "
                             "dein Limit ist %d am Tag" % (len(entries_today), batch_entries, cap_t))
            if sym:
                later.extend(window_for(om))
            if pdt_on and om == "us":
                pdt_used = True
                if pdt_n >= 3:
                    later.append("PDT: %d Daytrades in den letzten 5 Handelstagen (%s); ein 4. löst die "
                                 "Pattern-Day-Trader-Regel deines US-Brokers aus" % (pdt_n, ", ".join(pdt_list)))
            elif pdt_on and om != "us":
                note = ("PDT: die US-Regel für Pattern Day Trader (FINRA) gilt nur für US-Werte bei US-Brokern; "
                        "für XETRA-Trades und deutsche Broker nicht. pdt_guard wird hier nicht angewandt.")
                if note not in notes:
                    notes.append(note)
            if stop and ref and risk_ps:
                info.append("Einstieg %s (%s), Stop %s, Ziel %s: Risiko %s je Aktie"
                            % (_p(ref), REF_WORDS.get(ref_from, ref_from), _p(stop),
                               _p(target) if target else "keins", money(risk_ps, inst)))
                if max_loss is not None:
                    info.append("max. Verlust %s%s, Chance/Risiko %s%s"
                                % (money(max_loss, acct_cur),
                                   (" (Limit %s)" % money(max_loss_cap, acct_cur)) if max_loss_cap else "",
                                   markt.num(rr) if rr is not None else "k. A.",
                                   (" (min. %s)" % _num(c["min_reward_risk"])) if _f(c.get("min_reward_risk")) else ""))
            if daily or cap_t:
                info.append("heute vorher: %d von %s Trades, %s von %s Tagesverlust"
                            % (len(entries_today) + batch_entries, cap_t or "unbegrenzt",
                               money(loss_today + batch_loss, acct_cur),
                               money(daily, acct_cur) if daily else "ohne Limit"))

        # Doppelte und das Tageslimit für Orders
        key = (sym, side)
        if key in seen:
            later.append("Doppelt: ein zweiter %s %s in diesem Durchlauf" % (sw, sym))
        if key in placed_keys:
            later.append("Doppelt: %s %s wurde heute schon platziert" % (sw, sym))
        passed_so_far = sum(1 for r in results if r["verdict"] == "PASS")
        cap_n = int(c.get("max_orders_per_day") or 0)
        if cap_n and count_today + passed_so_far >= cap_n:
            later.append("Tageslimit: %d heute platziert plus %d vorher in diesem Durchlauf freigegeben, "
                         "dein Limit ist %d am Tag" % (count_today, passed_so_far, cap_n))
        seen.add(key)

        if kind == "entry":
            reasons.extend(later)
        else:
            warns.extend("Ausstieg, nicht gesperrt: " + x for x in later)

        verdict = "BLOCK" if reasons else "PASS"
        if verdict == "PASS":
            if kind == "entry" and side in ("buy", "sell"):
                batch_entries += 1
                batch_loss += max_loss or 0.0
            if side == "buy":
                if value is not None:
                    acct["cash"] -= value
                    acct["values"][sym] = acct["values"].get(sym, 0.0) + value
                if q is not None:
                    acct["shares"][sym] = held + q
                elif ref and value_i is not None:
                    acct["shares"][sym] = held + value_i / ref
            elif side == "sell":
                if value is not None:
                    acct["cash"] += value
                    acct["values"][sym] = max(acct["values"].get(sym, 0.0) - value, 0.0)
                if q is not None:
                    acct["shares"][sym] = held - q
                elif ref and value_i is not None:
                    acct["shares"][sym] = held - value_i / ref
        results.append({
            "index": i, "symbol": sym, "side": side, "kind": kind, "market": om,
            "amount": money(_f(notional) or 0, inst) if notional is not None else ("%s Aktien" % qty),
            "currency": inst, "fx": rate,
            "value": round(value, 2) if value is not None else None,
            "entry_ref": round(ref, 2) if ref else None, "entry_ref_from": ref_from,
            "stop": stop, "target": target, "risk_per_share": risk_ps, "max_loss": max_loss,
            "max_loss_instrument": max_loss_i,
            "reward_risk": rr, "fingerprint": fingerprint(o), "verdict": verdict,
            "reasons": reasons, "warnings": warns, "info": info,
        })

    if pdt_used is False and not pdt_on and m == "us" and broker and broker not in US_BROKERS:
        notes.append("PDT: die US-Regel für Pattern Day Trader gilt nur bei US-Brokern, nicht bei deutschen "
                      "Brokern (\"broker\": \"%s\"); nicht geprüft." % broker)
    return {
        "date": today,
        "market": m,
        "now_local": now_local.strftime("%Y-%m-%d %H:%M"),
        "account_currency": acct_cur,
        "paper": bool(c.get("paper", True)),
        "results": results,
        "pass": sum(1 for r in results if r["verdict"] == "PASS"),
        "block": sum(1 for r in results if r["verdict"] == "BLOCK"),
        "warnings": top_warn,
        "notes": notes,
        "cash_after": round(acct["cash"], 2),
        "today": {"orders_placed": count_today, "entries_placed": len(entries_today),
                  "loss_at_risk": round(loss_today, 2), "day_trades_5d": pdt_n if pdt_used else None},
    }


def report(res):
    lines = []
    for w in res["warnings"]:
        lines.append("WARNUNG: " + w)
    for n in res.get("notes", []):
        lines.append("Hinweis: " + n)
    if res["warnings"] or res.get("notes"):
        lines.append("")
    for r in res["results"]:
        lines.append("%-8s #%d %s %s %s, %s" % (VERDICT_WORDS[r["verdict"]], r["index"],
                                                SIDE_WORDS.get(r["side"], r["side"]), r["symbol"], r["amount"],
                                                KIND_WORDS[r["kind"]]))
        for x in r.get("info", []):
            lines.append("          " + x)
        for x in r["reasons"]:
            lines.append("        - " + x)
        for x in r["warnings"]:
            lines.append("        ~ " + x)
    lines.append("")
    m = res.get("market", "us")
    local = datetime.datetime.strptime(res["now_local"], "%Y-%m-%d %H:%M")
    when = "%s %s" % (markt.day_label(local.date()), markt.clock_both(local, m))
    lines.append("%d freigegeben, %d gesperrt, Stand %s. Cash nach den freigegebenen Orders: %s (%s)."
                 % (res["pass"], res["block"], when, markt.money(res["cash_after"], res["account_currency"]),
                    "Paper-Konto" if res["paper"] else "LIVE-Konto"))
    if res["block"]:
        lines.append("Gesperrte Orders gehen nicht zum Broker. Ändere die Order oder deine Regeln und prüf neu.")
    else:
        lines.append("Jede Order ist freigegeben. /dt-broker fragt dich trotzdem für jede einzeln ja oder nein.")
    lines.append("Bildung und Werkzeug, keine Anlageberatung. Eine FREIGABE ist eine Regelprüfung, keine Empfehlung.")
    return "\n".join(lines)


def load_prices(pdoc):
    """prices.json -> ({SYM: Kurs}, {SYM: Zeit des Kurses als naive UTC oder None}).

    Die Zeit ist die des Kurses (detail.time), sonst wann er geholt wurde
    (detail.fetched), sonst as_of der Datei."""
    if not isinstance(pdoc, dict):
        return {}, {}
    prices = pdoc.get("prices", pdoc)
    if not isinstance(prices, dict):
        return {}, {}
    out, times = {}, {}
    as_of = parse_utc(pdoc.get("as_of"))
    detail = pdoc.get("detail") or {}
    for s, p in prices.items():
        if _f(p) is None:
            continue
        s = str(s).upper()
        out[s] = float(p)
        d = detail.get(s) or {}
        times[s] = parse_utc(d.get("time")) or parse_utc(d.get("fetched")) or as_of
    return out, times


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prüft vorgeschlagene Orders gegen deine Limits (dt-risiko).")
    ap.add_argument("--orders", default="trader/orders.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json",
                    help="dein Konto; fehlt die Datei, ein frisches Konto mit dem Budget")
    ap.add_argument("--prices", default="trader/prices.json")
    ap.add_argument("--state", default="trader/state/broker.json", help="was dt-broker platziert hat")
    ap.add_argument("--market", help="xetra oder us (sonst aus dem Symbol der ersten Order)")
    ap.add_argument("--now", help="so tun, als wäre es diese Zeit, z. B. \"2026-10-27 09:20\"; ohne Offset "
                                  "gilt die Ortszeit des Marktes (XETRA: deutsche Zeit, US: New Yorker Zeit)")
    ap.add_argument("--today", help="JJJJ-MM-TT (Standard: heute in Ortszeit des Marktes)")
    ap.add_argument("--out", default="trader/state/risk.json", help="wohin das Ergebnis geschrieben wird")
    ap.add_argument("--no-write", action="store_true", help="das Ergebnis nicht speichern")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    with markt.restore():
        try:
            if a.today and not re.match(r"^\d{4}-\d{2}-\d{2}$", a.today):
                raise RiskError("--today erwartet ein Datum wie 2026-10-19")
            doc = read_json(a.orders, "Order-Datei (lass zuerst /dt-budget laufen)")
            orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
            if not isinstance(orders, list) or not orders:
                raise RiskError("keine Orders in %s" % a.orders)
            cfg = read_json(a.config, "Config", required=False) or {}
            first = orders[0] if isinstance(orders[0], dict) else {}
            m = markt.norm(a.market) if a.market else (
                order_market(first) if first.get("symbol") else markt.resolve(cfg=cfg))
            markt.use(m)
            now = parse_now(a.now)
            portfolio = read_json(a.portfolio, "Depot", required=False)
            pdoc = read_json(a.prices, "Kursdatei", required=False) or {}
            prices, times = load_prices(pdoc)
            state = read_json(a.state, "Broker-Log", required=False)
            res = check(orders, cfg, portfolio, prices, state, a.today, now, times)
            if pdoc.get("as_of"):
                res["prices_as_of"] = pdoc["as_of"]
            if not a.no_write:
                d = os.path.dirname(a.out)
                if d:
                    os.makedirs(d, exist_ok=True)
                rec = dict(res)
                rec["checked_at"] = markt.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
                rec["orders_file"] = a.orders
                tmp = a.out + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(rec, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                os.replace(tmp, a.out)
        except (RiskError, markt.MarketError) as e:
            print("check.py: %s" % e, file=sys.stderr)
            return 1
        print(json.dumps(res, indent=2, ensure_ascii=False) if a.json else report(res))
        return 1 if res["block"] else 0


if __name__ == "__main__":
    sys.exit(main())
