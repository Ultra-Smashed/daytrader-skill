#!/usr/bin/env python3
"""Order-Tickets und das Entscheidungs-Log für dt-broker. Nur Standardbibliothek.

Dieses Tool spricht nie mit einem Broker und platziert nie etwas. Es arbeitet
rund um den einen Moment, auf den es ankommt: dein „ja“.

  show      zeigt jede vorgeschlagene Order als Ticket in klaren Worten. Je nach
            "broker" in trader/config.json dazu das genaue JSON für Alpacas
            place_stock_order ("alpaca"), den Hinweis auf den IBKR-Entwurf
            ("ibkr") oder eine nummerierte Klick-Anleitung für deine Broker-App
            ("manuell", Standard). Eine Order ist BEREIT nur, wenn dt-risiko
            GENAU diese Order heute freigegeben hat (Fingerprint) und noch
            niemand über sie entschieden hat.
  approve   erfasst dein ausdrückliches „ja“ für EINE Order, Wort für Wort. Es
            lehnt „ja zu allen“, „ok“, „klar“, ein Ja mit Bedingung, ein Ja zu
            einer anderen Aktie oder Menge und jede nicht bereite Order ab. Ein
            „nein“ wird als abgelehnt erfasst.
  decline   erfasst ein Nein.
  result    erfasst, was danach passiert ist: placed (mit Order-ID des Brokers),
            denied oder failed.
  fill      trägt eine Ausführung in trader/portfolio.json ein (Bargeld, Stücke).
  flatten   baut das Verkaufs-Ticket, das eine Position bis flat_by schließt.
            Es geht trotzdem durch dt-risiko und dein „ja“.
  log       zeigt die Entscheidungen von heute.

    python3 ticket.py show                       # jede Order, bereit oder nicht
    python3 ticket.py show --index 1 --json      # ein Ticket als JSON
    python3 ticket.py approve --index 1 --reply "ja"
    python3 ticket.py result --index 1 --status placed --filled-qty 17 --filled-price 211.20
    python3 ticket.py fill --symbol SAP.DE --side sell --qty 17 --price 214.90
    python3 ticket.py flatten --symbol SAP.DE --qty 17
    python3 ticket.py log

Wann ist eine Antwort ein Ja? Sie beginnt mit dem Wort „ja“ (oder „yes“, „y“),
enthält keine Frage, keine Bedingung, keinen Zweifel und keine Mehrzahl („alle“,
„beide“, „aber“, „wenn“, „vielleicht“, „nur“, ...), und jede Zahl oder jedes
andere Symbol darin passt zu genau dieser Order. Alles andere ist kein Ja.

Alles landet in trader/state/broker.json (nur angehängt). Daten und Uhrzeiten
gelten im Markt des Symbols (SAP.DE: deutsche Zeit, TSLA: New Yorker Zeit);
--now "2026-10-28 10:15" setzt die Uhr.
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

ALPACA_FIELDS = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                 "stop_price", "trail_price", "trail_percent", "extended_hours", "client_order_id",
                 "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price", "advanced_instructions")
STRING_FIELDS = ("qty", "notional", "limit_price", "stop_price", "trail_price", "trail_percent",
                 "take_profit_limit_price", "stop_loss_stop_price", "stop_loss_limit_price")
TIF_WORDS = {"day": "gültig heute", "gtc": "gültig bis auf Widerruf", "opg": "zur Eröffnung",
             "cls": "zum Schluss", "ioc": "sofort oder stornieren (IOC)", "fok": "ganz oder gar nicht (FOK)"}
SIDE_WORDS = {"buy": "KAUF", "sell": "VERKAUF"}
STATUS_WORDS = {"approved": "bestätigt", "declined": "abgelehnt", "placed": "platziert",
                "denied": "verweigert", "failed": "fehlgeschlagen", "filled": "ausgeführt"}
BROKERS = {"manuell": "manuell", "manual": "manuell", "ibkr": "ibkr", "interactive brokers": "ibkr",
           "alpaca": "alpaca"}
BROKER_NAMES = {"manuell": "manuell in deiner Broker-App", "ibkr": "Interactive Brokers", "alpaca": "Alpaca"}
YES_WORDS = ("ja", "yes", "y")
NO_WORDS = ("nein", "no", "n", "nö", "nee", "noe")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each",
               "alle", "allen", "alles", "allem", "beide", "beiden", "restlichen", "übrigen", "uebrigen",
               "jede", "jeden", "jedes", "sämtliche", "saemtliche", "anderen", "weiteren", "zusammen"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later",
               "hold", "unless", "if",
               "nein", "nicht", "kein", "keine", "keinen", "warte", "wart", "moment", "aber", "vielleicht",
               "später", "spaeter", "falls", "wenn", "sofern", "außer", "ausser", "erst", "stopp", "storno",
               "stornieren", "abbrechen", "halt", "eventuell", "evtl", "lieber", "doch", "oder", "statt",
               "stattdessen", "sondern", "nur", "bloß", "ändere", "ändern"}
FEE_NOTE = "inkl. Gebühren"


class TicketError(Exception):
    pass


# ---------------------------------------------------------------- time

def local_iso(now_utc):
    """naive UTC -> "2026-10-19T10:15:00-04:00" (Ortszeit des Marktes mit Offset)."""
    return "%s%+03d:00" % (markt.to_local(now_utc).replace(microsecond=0).isoformat(), markt.offset(now_utc))


def _hhmm(text):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(text or ""))
    if not m:
        return None
    return datetime.time(int(m.group(1)), int(m.group(2)))


def flat_label(flat_by, today):
    """"17:25" -> "17:25 Uhr" an XETRA, "15:55 ET (21:55 Uhr)" in New York."""
    t = _hhmm(flat_by)
    if t is None:
        return str(flat_by)
    try:
        d = datetime.date.fromisoformat(today)
    except (TypeError, ValueError):
        return markt.clock_label(t)
    return markt.clock_both(datetime.datetime.combine(d, t))


def at_label(at, symbol=None, with_date=False):
    """Ein gespeichertes "at" (ISO mit Offset) in der Uhrzeit des Marktes des Symbols."""
    utc = markt.parse_utc(at)
    if utc is None:
        return str(at or "")
    m = markt.market_of(symbol) if symbol else markt.current()
    with markt.using(m):
        loc = markt.to_local(utc)
        text = markt.clock_both(loc)
    return ("%s %s" % (markt.date_de(loc.date()), text)) if with_date else text


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise TicketError("keine %s unter %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise TicketError("%s ist kein gültiges JSON: %s" % (path, e))


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def rec_day(rec):
    """Der Handelstag einer Entscheidung: ihr "date", sonst der Tag aus "at"."""
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


# ---------------------------------------------------------------- the order

def fingerprint(order):
    """Dieselbe Funktion wie dt-risiko/check.py: erkennt genau diese Order."""
    core = {k: order[k] for k in ALPACA_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _str_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return str(v)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tool_input(order):
    """Die genauen Argumente für place_stock_order: Alpacas Feldnamen, Zahlen als
    Strings. "why", "plan", "name" und "isin" gehören uns und werden nie gesendet."""
    out = {}
    for k in ALPACA_FIELDS:
        if k in order and order[k] is not None:
            out[k] = _str_num(order[k]) if k in STRING_FIELDS else order[k]
    return out


def broker_of(cfg):
    raw = str((cfg or {}).get("broker") or "manuell").strip().lower()
    if raw not in BROKERS:
        raise TicketError('unbekannter Broker "%s" in der Config: erlaubt sind "manuell", "ibkr" und "alpaca"'
                          % raw)
    return BROKERS[raw]


def _plan(order):
    p = order.get("plan")
    return p if isinstance(p, dict) else {}


def currency(order):
    """Instrumentwährung: plan.currency, sonst aus dem Symbol (SAP.DE: EUR, TSLA: USD)."""
    return str(_plan(order).get("currency") or markt.currency_of(order.get("symbol"))).upper()


def account_cur(order, cfg=None):
    """Kontowährung aus deiner Config (wie dt-risiko), nicht aus dem Plan."""
    return markt.account_currency(cfg or {})


def fx_rate(order, cfg=None):
    """Kontowährung je 1 Einheit Instrumentwährung, wie dt-risiko: plan.fx (wenn der Plan
    für dieselbe Kontowährung gerechnet ist), sonst "fx" in der Config, sonst None."""
    cur, acct = currency(order), account_cur(order, cfg)
    if cur == acct:
        return 1.0
    plan = _plan(order)
    pa = str(plan.get("account_currency") or "").strip().upper()
    sources = [plan.get("fx")] if pa in ("", acct) else []
    sources.append((cfg or {}).get("fx"))
    for src in sources:
        v = _f(src.get(cur)) if isinstance(src, dict) else _f(src)
        if v and v > 0:
            return v
    return None


def _px(v, cur):
    return markt.money(_f(v), cur)


def _amt(v, cur):
    return markt.money_short(_f(v), cur)


def is_bracket(order):
    oc = str(order.get("order_class") or "").lower()
    legs = order.get("take_profit_limit_price") is not None or order.get("stop_loss_stop_price") is not None
    return oc == "bracket" or (not oc and legs)


def _max_loss(order):
    """(Betrag, Stop, aus dem Plan?)."""
    stop = _f(order.get("stop_loss_stop_price")) or _f(_plan(order).get("stop"))
    q = _f(order.get("qty"))
    if not stop or not q:
        return None, stop, False
    plan = _plan(order)
    limit = _f(order.get("limit_price")) if str(order.get("type", "market")) == "limit" else None
    planned = _f(plan.get("max_loss"))
    entry_plan = _f(plan.get("entry"))
    if planned is not None and (limit is None or entry_plan is None or abs(limit - entry_plan) < 0.005):
        return round(planned, 2), stop, True
    entry = limit or entry_plan
    if not entry:
        return None, stop, False
    risk = abs(entry - stop)
    return round(q * int(round(risk * 100)) / 100.0, 2), stop, False


def max_loss(order):
    """(Betrag, Stop), wenn der Stop genau beim Stop-Kurs ausgeführt wird, oder (None, Stop).
    Mit plan.max_loss gilt der Plan (dt-budget rechnet ihn in Kontowährung inkl. Gebühren),
    außer bei einer Limit-Order, deren Limit vom Plan-Einstieg abweicht."""
    loss, stop, _ = _max_loss(order)
    return loss, stop


def loss_info(order, cfg=None):
    """Der maximale Verlust in Instrument- und Kontowährung, oder None.
    plan.max_loss gilt in plan.account_currency (bei plan.fx ohne sie: in der Kontowährung),
    plan.max_loss_instrument in Instrumentwährung ohne Gebühren. Ein älterer Plan ohne
    beides rechnet in Instrumentwährung."""
    amt, stop, from_plan = _max_loss(order)
    if amt is None:
        return None
    plan = _plan(order)
    cur, acct = currency(order), account_cur(order, cfg)
    rate = fx_rate(order, cfg)
    plan_cur = str(plan.get("account_currency") or "").strip().upper() or (acct if plan.get("fx") is not None
                                                                           else "")
    if from_plan and plan_cur and plan_cur not in (acct, cur):
        from_plan, amt = False, _f(plan.get("max_loss_instrument"))
        if amt is None:
            return None
    elif from_plan and plan_cur and plan_cur != acct:
        from_plan, amt = False, _f(plan.get("max_loss_instrument")) or amt
    if from_plan and plan_cur:
        inst_amt = _f(plan.get("max_loss_instrument"))
        if inst_amt is None:
            if plan_cur == cur:
                inst_amt = amt
            elif rate and plan_cur == acct:
                inst_amt = round(amt / rate, 2)
        fees = _f(plan.get("fees"))
        return {"instrument": inst_amt, "currency": cur, "account": amt, "account_currency": plan_cur,
                "stop": stop, "fees": fees is None or fees > 0}
    return {"instrument": amt, "currency": cur, "account": round(amt * rate, 2) if rate else None,
            "account_currency": acct, "stop": stop, "fees": False}


def _loss_text(li):
    cur, acct = li["currency"], li["account_currency"]
    fee = (", " + FEE_NOTE) if li["fees"] else ""
    if li["account"] is None:
        return _amt(li["instrument"], cur)
    if cur == acct:
        return "%s%s" % (_amt(li["account"], acct), (" (" + FEE_NOTE + ")") if li["fees"] else "")
    if li["instrument"] is None:
        return "%s (Kontowährung%s)" % (_amt(li["account"], acct), fee)
    return "%s (%s in Kontowährung%s)" % (_amt(li["instrument"], cur), _amt(li["account"], acct), fee)


def recorded_loss(order, cfg=None):
    """(Betrag, Währung) für das Log: in Kontowährung, wenn umrechenbar; dt-risiko summiert ihn."""
    li = loss_info(order, cfg)
    if li is None:
        return None, None
    if li["account"] is not None:
        return li["account"], li["account_currency"]
    return li["instrument"], li["currency"]


def _how(order, cur, short):
    typ = str(order.get("type", "market"))
    if typ == "limit" and order.get("limit_price") is not None:
        return ("Limit %s" if short else "Limit-Order zu %s") % _px(order["limit_price"], cur)
    if typ == "stop" and order.get("stop_price") is not None:
        return "Stop-Order bei %s" % _px(order["stop_price"], cur)
    if typ == "stop_limit":
        return "Stop %s, Limit %s" % (_px(order.get("stop_price"), cur), _px(order.get("limit_price"), cur))
    if typ == "trailing_stop":
        return "Trailing-Stop-Order"
    if typ == "market":
        return "Market" if short else "Market-Order"
    return typ.replace("_", " ")


def plain_parts(order, cfg=None):
    """Das Ticket in klaren Worten, ein Teil pro Zeile."""
    side = SIDE_WORDS.get(str(order.get("side", "")).lower(), str(order.get("side", "")).upper())
    sym = order.get("symbol", "?")
    cur = currency(order)
    tif = TIF_WORDS.get(str(order.get("time_in_force", "day")), order.get("time_in_force"))
    rate = fx_rate(order, cfg)
    acct = account_cur(order, cfg)
    if is_bracket(order):
        parts = ["%s %s Stück %s, %s, %s" % (side, _str_num(order.get("qty")), sym, _how(order, cur, True), tif)]
        if order.get("stop_loss_stop_price") is not None:
            leg = "Stop-Loss %s" % _px(order["stop_loss_stop_price"], cur)
            if order.get("stop_loss_limit_price") is not None:
                leg += " (Limit %s)" % _px(order["stop_loss_limit_price"], cur)
            parts.append(leg)
        if order.get("take_profit_limit_price") is not None:
            parts.append("Take-Profit %s" % _px(order["take_profit_limit_price"], cur))
        li = loss_info(order, cfg)
        if li is not None:
            parts.append("max. Verlust etwa %s, wenn der Stop bei %s ausgeführt wird (in einem schnellen "
                         "Markt kann es schlechter werden)" % (_loss_text(li), _px(li["stop"], cur)))
        return parts
    if order.get("notional") is not None:
        what = "%s %s für %s" % (side, sym, _amt(order["notional"], cur))
        if rate and cur != acct:
            what += " (etwa %s)" % _amt(_f(order["notional"]) * rate, acct)
    else:
        what = "%s %s Stück %s" % (side, _str_num(order.get("qty")), sym)
    return ["%s, %s, %s" % (what, _how(order, cur, False), tif)]


def plain(order, cfg=None):
    """KAUF AAPL für 1.250 $, Market-Order, gültig heute
    KAUF 8 Stück TSLA, Market, gültig heute / Stop-Loss 358,32 $ / Take-Profit 370,04 $ / max. Verlust ..."""
    return " / ".join(plain_parts(order, cfg))


def amount_numbers(order, cfg=None):
    nums = []
    for k in ("notional", "qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",
              "stop_loss_limit_price"):
        if order.get(k) is not None:
            v = _f(order[k])
            if v is not None:
                nums.append(v)
    li = loss_info(order, cfg)
    if li is not None:
        nums.extend(v for v in (li["instrument"], li["account"]) if v is not None)
    return nums


def _readings(tok):
    """Eine Zahl aus einer Antwort, englisch ("1,250.5") und deutsch ("1.250,5") gelesen."""
    out = set()
    for s in (tok.replace(",", ""), tok.replace(".", "").replace(",", ".")):
        try:
            out.add(float(s))
        except ValueError:
            pass
    return out


def first_word(reply):
    words = re.findall(r"[a-zäöüß']+", (reply or "").lower())
    return words[0] if words else ""


def is_no(reply):
    return first_word(reply) in NO_WORDS


def parse_yes(reply, order, batch_symbols=(), cfg=None):
    """Ist diese Antwort ein ausdrückliches Ja für GENAU diese eine Order? (ok, warum)"""
    raw = (reply or "").strip()
    if not raw:
        return False, "die Antwort ist leer"
    if "?" in raw:
        return False, "die Antwort ist eine Frage, kein Ja"
    words = re.findall(r"[a-zäöüß']+", raw.lower())
    if not words or words[0] not in YES_WORDS:
        return False, "nur eine Antwort, die mit „ja“ (oder „yes“) beginnt, zählt (nicht ok, klar, passt, mach)"
    if BATCH_WORDS & set(words):
        return False, "ein Ja gilt immer nur für eine Order, nie für mehrere"
    if DOUBT_WORDS & set(words[1:]):
        return False, "die Antwort enthält eine Bedingung oder einen Zweifel"
    sym = str(order.get("symbol", "")).upper()
    tokens = set(re.findall(r"[A-Z0-9][A-Z0-9.\-]{0,7}", raw.upper()))
    tokens = {t.rstrip(".") for t in tokens if re.search(r"[A-Z]", t)}
    others = {str(s).upper() for s in batch_symbols if s} - {sym}
    others |= {o.split(".")[0] for o in others if "." in o} - {sym.split(".")[0]}
    named = tokens & others
    if named:
        return False, "die Antwort nennt %s, aber diese Order ist für %s" % (", ".join(sorted(named)), sym)
    rest = raw.upper()
    for s in sorted({sym, sym.split(".")[0]} | others, key=len, reverse=True):
        if s:
            rest = re.sub(r"(?<![A-Z0-9])%s(?![A-Z0-9])" % re.escape(s), " ", rest)
    found = re.findall(r"\d[\d.,]*\d|\d", rest)
    if found:
        want = amount_numbers(order, cfg)
        for tok in found:
            if not any(abs(n - w) < 0.005 for n in _readings(tok) for w in want):
                return False, "die Antwort nennt %s, aber diese Order ist: %s" % (tok, plain(order, cfg))
    return True, "ausdrückliches Ja für %s" % plain(order, cfg)


# ---------------------------------------------------------------- manual mode

def manual_steps(order, cfg, idx):
    """Die nummerierte Klick-Anleitung für eine Broker-App ohne API."""
    plan = _plan(order)
    sym = str(order.get("symbol", "?")).upper()
    side = str(order.get("side", "")).lower()
    cur, acct = currency(order), account_cur(order, cfg)
    rate = fx_rate(order, cfg)
    convert = bool(rate) and cur != acct

    def px(v):
        s = _px(v, cur)
        return s + (" (etwa %s)" % _px(_f(v) * rate, acct) if convert else "")

    q = _str_num(order.get("qty")) if order.get("qty") is not None else None
    tif = str(order.get("time_in_force", "day"))
    tif_text = {"day": "nur heute (Tagesorder, gültig bis Handelsschluss)",
                "gtc": "bis auf Widerruf, wenn deine App das anbietet"}.get(tif, TIF_WORDS.get(tif, tif))
    leg_tif = "gültig heute" if tif == "day" else TIF_WORDS.get(tif, tif)
    name = order.get("name") or plan.get("name")
    isin = order.get("isin") or plan.get("isin")
    ident = ("%s (%s)" % (name, sym)) if name else sym
    if isin:
        ident += ", ISIN %s" % isin
    steps = []
    if markt.market_of(sym) == "xetra":
        steps.append("Wertpapier suchen: %s. Handelsplatz XETRA." % ident)
    else:
        where = ("Wertpapier suchen: %s. Handelsplatz: US-Aktien handeln deutsche Broker meist über Plätze wie "
                 "Tradegate, LS Exchange oder gettex in EUR; Kurs und Spread weichen dort vom US-Kurs ab." % ident)
        if convert:
            where += " Die Kurse unten sind US-Kurse in %s, in Klammern mit dem Wechselkurs aus Plan oder Config umgerechnet (nur Richtwerte)." % cur
        else:
            where += " Die Kurse unten sind US-Kurse in %s; rechne sie um, wenn deine App nur EUR zeigt." % cur
        steps.append(where)
    if side == "sell":
        steps.append("Vorher offene Stop- und Limit-Orders auf diese Stücke stornieren, sonst sind die Stücke "
                     "gesperrt oder du verkaufst doppelt.")
    verb = "Verkaufen" if side == "sell" else "Kaufen"
    if q is not None:
        steps.append("%s wählen, Stückzahl %s." % (verb, q))
    else:
        steps.append("%s wählen, Betrag %s (nur wenn dein Broker Betrags- oder Bruchstück-Orders kann; sonst "
                     "die Stückzahl selbst ausrechnen und abrunden)." % (verb, _amt(order.get("notional"), cur)))
    typ = str(order.get("type", "market"))
    if typ == "limit":
        steps.append("Orderart: Limit, Limit %s." % px(order.get("limit_price")))
    elif typ == "stop":
        steps.append("Orderart: Stop (Stop-Market), Stop-Kurs %s." % px(order.get("stop_price")))
    elif typ == "stop_limit":
        steps.append("Orderart: Stop-Limit, Stop-Kurs %s, Limit %s." % (px(order.get("stop_price")),
                                                                      px(order.get("limit_price"))))
    else:
        steps.append("Orderart: Market (%s, ohne Limit)." % ("bestens" if side == "sell" else "billigst"))
    steps.append("Gültigkeit: %s." % tif_text)
    ref = _f(order.get("limit_price")) if typ == "limit" else _f(plan.get("entry"))
    if ref and q is not None:
        vol = _f(q) * ref
        line = "In der Vorschau prüfen: etwa %s × %s = %s" % (q, _px(ref, cur), _amt(vol, cur))
        if convert:
            line += " (etwa %s)" % _amt(vol * rate, acct)
        steps.append(line + " plus Gebühren.")
    steps.append("Order in der App prüfen und dort bestätigen. Das ist die dritte Stufe, sie liegt bei dir. "
                 "Notier Ausführungskurs und Stückzahl.")
    notes = []
    stop = order.get("stop_loss_stop_price")
    target = order.get("take_profit_limit_price")
    if side == "buy" and (stop is not None or target is not None):
        if stop is not None:
            leg = "Erst wenn der Kauf ausgeführt ist: Stop-Loss-Order, Verkauf %s Stück, " % q
            if order.get("stop_loss_limit_price") is not None:
                leg += "Orderart Stop-Limit, Stop-Kurs %s, Limit %s, %s." % (
                    px(stop), px(order["stop_loss_limit_price"]), leg_tif)
            else:
                leg += "Orderart Stop (Stop-Market), Stop-Kurs %s, %s." % (px(stop), leg_tif)
            steps.append(leg)
        if target is not None:
            steps.append("Take-Profit-Order: Verkauf %s Stück, Orderart Limit, Limit %s, %s."
                         % (q, px(target), leg_tif))
        notes.append("Achtung: Viele Neobroker kennen keine Bracket- oder OCO-Orders (eine Order storniert "
                     "die andere) und erlauben Stop und Limit oft nicht gleichzeitig auf dieselben Stücke. "
                     "Dann setz nur den Stop beim Broker und lass das Ziel %s per /dt-alarm beobachten; wird "
                     "es erreicht, verkaufst du von Hand. Liegen beide Orders und eine wird ausgeführt, "
                     "storniere sofort die andere." % (px(target) if target is not None else "aus dem Plan"))
    filled = q or "Q"
    notes.append("Danach hier erfassen: ticket.py result --index %d --status placed --filled-qty %s "
                 "--filled-price KURS (lehnt die App sie ab: --status failed --note \"Grund\")." % (idx, filled))
    if cfg.get("paper", True):
        notes.append("PAPIER: Führe sie nur im Demokonto oder auf Papier aus, nicht im echten Depot.")
    return ["%d. %s" % (i, s) for i, s in enumerate(steps, 1)] + notes


def _wrap(text, width=100, indent="  "):
    out, line = [], ""
    for w in text.split(" "):
        if line and len(indent + line + " " + w) > width:
            out.append(indent + line)
            line = w
        else:
            line = (line + " " + w) if line else w
    if line:
        out.append(indent + line)
    return out


def manual_lines(order, cfg, idx, head):
    lines = ["  " + head]
    for s in manual_steps(order, cfg, idx):
        m = re.match(r"^(\d+\. )", s)
        if m:
            first = _wrap(s, indent="    ")
            lines.append(first[0])
            lines.extend("    " + " " * len(m.group(1)) + l.strip() for l in first[1:])
        else:
            lines.extend(_wrap(s, indent="  "))
    return lines


# ---------------------------------------------------------------- state

def load_state(path):
    return read_json(path, "Broker-Datei", required=False) or {"orders": []}


def latest(state, fp, today):
    """Die letzte Entscheidung von heute für diesen Fingerprint, oder None."""
    found = None
    for rec in state.get("orders", []):
        if rec.get("fingerprint") == fp and rec_day(rec) == today:
            found = rec
    return found


def risk_verdict(risk, fp, today):
    if not risk:
        return None, "dt-risiko hat diese Orders noch nicht geprüft (check.py ausführen)"
    if risk.get("date") != today:
        return None, "die Risikoprüfung ist vom %s, nicht von heute; check.py noch einmal ausführen" % risk.get("date")
    for r in risk.get("results", []):
        if r.get("fingerprint") == fp:
            return r, None
    return None, ("genau diese Order war nicht in der letzten Risikoprüfung (sie wurde geändert oder ist neu); "
                  "check.py noch einmal ausführen")


def broker_problem(order, broker):
    sym = str(order.get("symbol", "")).upper()
    if broker == "alpaca" and markt.market_of(sym) == "xetra":
        return ('Alpaca handelt nur US-Aktien, %s ist ein XETRA-Wert. Für XETRA "broker": "ibkr" oder '
                '"manuell" in trader/config.json setzen' % sym)
    return None


def status_of(order, risk, state, today, cfg=None):
    """(bereit, Text, Risiko-Ergebnis)"""
    broker = broker_of(cfg)
    problem = broker_problem(order, broker)
    if problem:
        return False, "NICHT BEREIT: " + problem, None
    fp = fingerprint(order)
    rv, why = risk_verdict(risk, fp, today)
    if rv is None:
        return False, "NICHT BEREIT: " + why, None
    if rv.get("verdict") != "PASS":
        return False, "GESPERRT von dt-risiko: " + "; ".join(rv.get("reasons", [])), rv
    rec = latest(state, fp, today)
    if rec:
        st = rec.get("status")
        when = at_label(rec.get("at"), order.get("symbol"))
        if st == "approved":
            wait = {"alpaca": "wartet auf den Aufruf von place_stock_order",
                    "ibkr": "wartet auf den Entwurf und deine Freigabe in IBKR",
                    "manuell": "wartet darauf, dass du sie in deiner App eingibst"}[broker]
            return False, "BESTÄTIGT von dir um %s, %s" % (when, wait), rv
        return False, "ERLEDIGT: %s um %s" % (STATUS_WORDS.get(st, st), when), rv
    return True, "BEREIT: dt-risiko FREIGABE, wartet auf dein „ja“", rv


def kind_of(order, rv):
    """entry oder exit, wie dt-risiko es sah (ältere Prüfungen: ein Kauf ist ein Einstieg)."""
    if rv and rv.get("kind"):
        return rv["kind"]
    return "entry" if str(order.get("side", "")).lower() == "buy" else "exit"


# ---------------------------------------------------------------- rendering

def account_label(cfg, broker):
    paper = cfg.get("paper", True)
    if broker == "manuell":
        return "PAPIER (nur im Demokonto oder auf Papier)" if paper else "LIVE, ECHTES GELD in deinem Depot"
    return "PAPIER-Konto" if paper else "LIVE-KONTO, ECHTES GELD"


def market_line(order, cfg, today):
    sym = order.get("symbol", "")
    with markt.using(markt.market_of(sym)):
        mk = markt.info()
        fb = flat_label(markt.windows(cfg)["flat_by"], today)
    line = "Markt %s, Kurse in %s, glatt bis %s" % (mk["name"], currency(order), fb)
    acct = account_cur(order, cfg)
    if acct != currency(order):
        line += ", Konto in %s" % acct
    return line


def render(order, idx, total, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today, cfg)
    broker = broker_of(cfg)
    lines = ["ORDER %d von %d, %s, %s" % (idx, total, account_label(cfg, broker), BROKER_NAMES[broker]),
             "  " + market_line(order, cfg, today)]
    if not cfg.get("paper", True):
        lines.append("  ACHTUNG LIVE: Diese Order setzt echtes Geld ein. Ein Stop ist keine Garantie, bei "
                     "Kurslücken kann der Verlust größer sein als geplant.")
    for part in plain_parts(order, cfg):
        lines.append("  " + part)
    if order.get("why"):
        lines.append("  warum: " + order["why"])
    lines.append("  " + label)
    for w in (rv or {}).get("warnings", []):
        lines.append("  Hinweis: " + w)
    approved = label.startswith("BESTÄTIGT")
    if broker == "ibkr":
        lines.append("  Claude entwirft diese Order mit dem Interactive-Brokers-Connector. IBKR legt sie in dein")
        lines.append("  IBKR-Konto, und an den Markt geht sie erst, nachdem du sie dort freigegeben hast.")
    elif broker == "alpaca":
        lines.append("  Claude ruft place_stock_order mit genau diesem JSON auf:")
        for l in json.dumps(tool_input(order), indent=2).splitlines():
            lines.append("    " + l)
        if is_bracket(order):
            lines.append("  Alpaca platziert den Einstieg, danach Stop-Loss und Take-Profit als zwei Orders, die")
            lines.append("  sich gegenseitig aufheben: wird eine ausgeführt, wird die andere storniert.")
    elif ready or approved:
        lines.extend(manual_lines(order, cfg, idx, "So gibst du sie in deiner Broker-App ein (erst nach deinem "
                                                   "„ja“ hier im Chat):"))
    if ready:
        lines.append("  Antworte „ja“, um genau diese eine Order freizugeben, oder „nein“, um sie auszulassen.")
        if broker == "alpaca":
            lines.append("  Danach fragt Claudes eigene Karte noch einmal: Allow once platziert sie, Deny stoppt sie.")
        elif broker == "ibkr":
            lines.append("  Danach fragt Claudes Karte (Allow once / Deny), und zuletzt gibst du sie in IBKR frei.")
        else:
            lines.append("  Danach tippst du sie selbst in deiner App ein und bestätigst sie dort.")
    return "\n".join(lines), ready


def ticket_json(order, idx, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today, cfg)
    broker = broker_of(cfg)
    loss, stop = max_loss(order)
    rec_loss, rec_cur = recorded_loss(order, cfg)
    with markt.using(markt.market_of(order.get("symbol", ""))):
        mk = markt.current()
        fb = markt.windows(cfg)["flat_by"]
    out = {"index": idx, "ready": ready, "status": label, "plain": plain(order, cfg),
           "fingerprint": fingerprint(order), "paper": bool(cfg.get("paper", True)),
           "broker": broker, "tool": "place_stock_order" if broker == "alpaca" else None,
           "tool_input": tool_input(order), "why": order.get("why", ""),
           "bracket": is_bracket(order), "max_loss": loss, "stop": stop,
           "max_loss_account": rec_loss, "max_loss_currency": rec_cur,
           "market": mk, "currency": currency(order), "account_currency": account_cur(order, cfg),
           "flat_by": fb}
    if broker == "manuell":
        out["anleitung"] = manual_steps(order, cfg, idx)
    return out


# ---------------------------------------------------------------- fills -> portfolio

def apply_fill(portfolio_path, cfg, symbol, side, qty, price, date):
    """Eine Ausführung in trader/portfolio.json: Bargeld und Stücke, ein Kaufposten
    (Lot) je Kauf; ein Verkauf löst die ältesten Posten zuerst auf."""
    pf = read_json(portfolio_path, "Portfolio", required=False)
    if pf is None:
        budget = cfg.get("budget")
        if not budget:
            raise TicketError("noch kein %s und kein budget in der Config, um es anzulegen" % portfolio_path)
        pf = {"cash": float(budget), "positions": []}
    symbol = symbol.upper()
    qty, price = float(qty), float(price)
    if qty <= 0 or price <= 0:
        raise TicketError("eine Ausführung braucht eine positive Stückzahl und einen positiven Kurs")
    cost = round(qty * price, 2)
    pos = None
    for p in pf.setdefault("positions", []):
        if str(p.get("ticker", "")).upper() == symbol:
            pos = p
    if side == "buy":
        if pos is None:
            pos = {"ticker": symbol, "shares": 0.0, "lots": []}
            pf["positions"].append(pos)
        lots = pos.setdefault("lots", [])
        lots.append({"id": "%s-%d" % (symbol, len(lots) + 1), "date": date, "shares": qty, "cost": cost})
        pos["shares"] = round(float(pos.get("shares", 0)) + qty, 6)
        pf["cash"] = round(float(pf.get("cash", 0)) - cost, 2)
    else:
        if pos is None or float(pos.get("shares", 0)) + 1e-9 < qty:
            raise TicketError("Verkauf von %s %s kann nicht erfasst werden: das Portfolio hält %s"
                              % (_str_num(qty), symbol, _str_num(pos.get("shares", 0)) if pos else 0))
        left = qty
        for lot in sorted(pos.get("lots", []), key=lambda l: l.get("date", "")):
            if left <= 1e-9:
                break
            take = min(left, float(lot["shares"]))
            per = float(lot["cost"]) / float(lot["shares"]) if float(lot["shares"]) else 0
            lot["cost"] = round(float(lot["cost"]) - per * take, 2)
            lot["shares"] = round(float(lot["shares"]) - take, 6)
            left -= take
        pos["lots"] = [l for l in pos.get("lots", []) if float(l["shares"]) > 1e-9]
        pos["shares"] = round(float(pos["shares"]) - qty, 6)
        if pos["shares"] <= 1e-9:
            pf["positions"].remove(pos)
        pf["cash"] = round(float(pf.get("cash", 0)) + cost, 2)
    write_json(portfolio_path, pf)
    return pf


def log_fill(state_path, now, today, symbol, side, qty, price):
    """Eine Ausführung im Log, damit dt-risiko Daytrades zählen kann (Kauf und Verkauf am selben Tag)."""
    state = load_state(state_path)
    sym = symbol.upper()
    state.setdefault("orders", []).append({
        "at": local_iso(now), "date": today, "status": "filled", "symbol": sym, "side": side,
        "qty": _str_num(float(qty)), "price": float(price),
        "plain": "%s %s Stück %s zu %s" % (SIDE_WORDS.get(side, side.upper()), _str_num(float(qty)), sym,
                                          _px(price, markt.currency_of(sym)))})
    write_json(state_path, state)


# ---------------------------------------------------------------- commands

def _clock(a):
    now = markt.parse_now(getattr(a, "now", None), error=TicketError)
    today = getattr(a, "today", None) or markt.to_local(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        raise TicketError("--today erwartet ein Datum wie 2026-10-28")
    return now, today


def _use_market(a, symbols, cfg):
    try:
        markt.use(markt.resolve(flag=getattr(a, "market", None), symbols=symbols, cfg=cfg))
    except markt.MarketError as e:
        raise TicketError(str(e))


def _load(a):
    doc = read_json(a.orders, "Order-Datei (zuerst dt-budget oder ticket.py flatten ausführen)")
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not orders:
        raise TicketError("keine Orders in %s" % a.orders)
    cfg = read_json(a.config, "Config", required=False) or {}
    broker_of(cfg)
    _use_market(a, [o.get("symbol") for o in orders if isinstance(o, dict)], cfg)
    risk = read_json(a.risk, "Risikoprüfung", required=False)
    state = load_state(a.state)
    now, today = _clock(a)
    return orders, cfg, risk, state, today, now


def _pick(orders, index):
    if index is None:
        raise TicketError("sag, welche Order: --index N")
    if not 1 <= index <= len(orders):
        raise TicketError("es gibt keine Order %d (es gibt %d)" % (index, len(orders)))
    return orders[index - 1]


def cmd_show(a):
    orders, cfg, risk, state, today, now = _load(a)
    picks = [(a.index, _pick(orders, a.index))] if a.index else list(enumerate(orders, 1))
    if a.json:
        out = [ticket_json(o, i, cfg, risk, state, today) for i, o in picks]
        print(json.dumps(out[0] if a.index else out, indent=2, ensure_ascii=False))
        return 0 if any(t["ready"] for t in out) else 1
    blocks, any_ready = [], False
    for i, o in picks:
        text, ready = render(o, i, len(orders), cfg, risk, state, today)
        blocks.append(text)
        any_ready = any_ready or ready
    print("\n\n".join(blocks))
    print("\nEine Order nach der anderen: ein „ja“ gilt für genau ein Ticket, nie für alle. Bildung und "
          "Werkzeug, keine Anlageberatung.")
    return 0 if any_ready else 1


def _decision(a, order, today, now, status, reply):
    return {"at": local_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
            "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
            "status": status, "reply": reply}


def cmd_approve(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    ready, label, rv = status_of(order, risk, state, today, cfg)
    if not ready:
        raise TicketError("Order %d ist nicht bereit: %s" % (a.index, label))
    if is_no(a.reply):
        rec = _decision(a, order, today, now, "declined", a.reply)
        rec["plain"] = plain(order, cfg)
        state.setdefault("orders", []).append(rec)
        write_json(a.state, state)
        print("Kein Ja: du hast „%s“ geantwortet. Order %d ist als abgelehnt erfasst; nichts wurde gesendet."
              % (a.reply.strip(), a.index))
        return 1
    ok, why = parse_yes(a.reply, order, [o.get("symbol", "") for o in orders], cfg)
    if not ok:
        print("Nicht erfasst: %s. Frag noch einmal, mit dem Ticket für Order %d." % (why, a.index))
        return 1
    broker = broker_of(cfg)
    loss, stop = max_loss(order)
    rec_loss, rec_cur = recorded_loss(order, cfg)
    rec = _decision(a, order, today, now, "approved", a.reply)
    rec.update({"qty": order.get("qty"), "kind": kind_of(order, rv), "max_loss": rec_loss,
                "max_loss_currency": rec_cur, "stop": stop, "plain": plain(order, cfg),
                "paper": bool(cfg.get("paper", True)), "broker": broker})
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Dein „ja“ für Order %d ist erfasst: %s." % (a.index, plain(order, cfg)))
    if broker == "ibkr":
        print("Jetzt mit dem Interactive-Brokers-Connector entwerfen (Karte: Allow once), dann in IBKR prüfen "
              "und freigeben. Danach: ticket.py result --index %d --status placed|denied|failed" % a.index)
    elif broker == "alpaca":
        print("Jetzt place_stock_order mit genau diesem JSON aufrufen:")
        print(json.dumps(tool_input(order), indent=2))
        print("Claudes Karte zeigt Allow once / Deny. Danach: ticket.py result --index %d --status "
              "placed|denied|failed" % a.index)
    else:
        print("\n".join(manual_lines(order, cfg, a.index, "Jetzt in deiner Broker-App:")))
    return 0


def cmd_decline(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    rec = _decision(a, order, today, now, "declined", a.reply or "nein")
    rec["plain"] = plain(order, cfg)
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Erfasst: du hast Order %d abgelehnt (%s). Nichts wurde gesendet." % (a.index, plain(order, cfg)))
    return 0


def cmd_result(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    fp = fingerprint(order)
    rec = latest(state, fp, today)
    if not rec or rec.get("status") != "approved":
        raise TicketError("Order %d hat heute kein erfasstes „ja“; ein Ergebnis kann nur nach einer "
                          "Bestätigung kommen" % a.index)
    new = {"at": local_iso(now), "date": today, "index": a.index, "fingerprint": fp, "symbol": rec["symbol"],
           "side": rec["side"], "plain": rec["plain"], "status": a.status}
    for k in ("qty", "kind", "max_loss", "max_loss_currency", "stop", "broker"):
        if rec.get(k) is not None:
            new[k] = rec[k]
    if a.broker_id:
        new["broker_order_id"] = a.broker_id
    if a.note:
        new["note"] = a.note
    state["orders"].append(new)
    write_json(a.state, state)
    print("Order %d als %s erfasst." % (a.index, STATUS_WORDS.get(a.status, a.status)))
    if a.status == "placed" and a.filled_qty and a.filled_price:
        apply_fill(a.portfolio, cfg, rec["symbol"], rec["side"], a.filled_qty, a.filled_price, today)
        log_fill(a.state, now, today, rec["symbol"], rec["side"], a.filled_qty, a.filled_price)
        print("Ausführung in %s eingetragen." % a.portfolio)
    elif a.status == "placed":
        print("Sobald sie ausgeführt ist, erfasse sie: ticket.py fill --symbol %s --side %s --qty Q --price P"
              % (rec["symbol"], rec["side"]))
    if a.status == "placed" and rec.get("kind") == "entry" and is_bracket(order):
        print("Wird später der Stop-Loss oder das Ziel ausgeführt, erfasse diesen Verkauf genauso mit "
              "ticket.py fill --side sell.")
    return 0


def cmd_fill(a):
    cfg = read_json(a.config, "Config", required=False) or {}
    _use_market(a, [a.symbol], cfg)
    now = markt.parse_now(a.now, error=TicketError)
    date = a.date or markt.to_local(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise TicketError("--date erwartet ein Datum wie 2026-10-28")
    pf = apply_fill(a.portfolio, cfg, a.symbol, a.side, a.qty, a.price, date)
    log_fill(a.state, now, date, a.symbol, a.side, a.qty, a.price)
    sym = a.symbol.upper()
    print("Erfasst: %s %s Stück %s zu %s am %s in %s. Bargeld jetzt %s."
          % ("Kauf" if a.side == "buy" else "Verkauf", a.qty, sym, _px(a.price, markt.currency_of(sym)),
             markt.date_de(datetime.date.fromisoformat(date)), a.portfolio,
             _amt(pf["cash"], markt.account_currency(cfg))))
    return 0


def cmd_flatten(a):
    cfg = read_json(a.config, "Config", required=False) or {}
    broker = broker_of(cfg)
    sym = a.symbol.strip().upper()
    _use_market(a, [sym], cfg)
    now, today = _clock(a)
    source = "deiner Angabe (--qty)"
    if a.qty is not None:
        qty = markt.parse_number(a.qty)
        if qty is None or qty <= 0:
            raise TicketError("--qty erwartet die Stückzahl, die du hältst, z. B. --qty 8")
    else:
        pf = read_json(a.portfolio, "Portfolio", required=False) or {}
        qty = sum(_f(p.get("shares", p.get("qty"))) or 0 for p in pf.get("positions", [])
                  if str(p.get("ticker") or p.get("symbol") or "").upper() == sym)
        source = a.portfolio
        if qty <= 1e-9:
            raise TicketError("nichts glattzustellen: keine %s-Stücke in %s. Prüf dein Depot beim Broker und "
                              "gib --qty an, wenn du doch Stücke hältst" % (sym, a.portfolio))
    plan = read_json(a.plan, "Plan", required=False) or {}
    flat_by = (plan.get("flat_by") if str(plan.get("symbol", "")).upper() == sym else None) \
        or markt.windows(cfg)["flat_by"]
    fb = flat_label(flat_by, today)
    order = {"symbol": sym, "side": "sell", "qty": _str_num(qty), "type": "market", "time_in_force": "day",
             "why": "glatt bis %s: schließt den %s-Daytrade vor Handelsschluss (Stückzahl aus %s)"
             % (fb, sym, source)}
    old = read_json(a.orders, "Orders", required=False)
    replaced = len(old.get("orders", [])) if isinstance(old, dict) else 0
    doc = {"created_by": "dt-broker", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "proposed",
           "paper": bool(cfg.get("paper", True)),
           "note": "Glattstellungs-Ticket. Nichts wird platziert, bevor dt-risiko es freigibt und du im Chat "
                   "„ja“ sagst.",
           "source": "ticket.py flatten %s am %s" % (sym, today), "orders": [order]}
    write_json(a.orders, doc)
    print("Glattstellen %s bis %s: %s." % (sym, fb, plain(order, cfg)))
    if replaced:
        print("Geschrieben nach %s (ersetzt %d %s)." % (a.orders, replaced, "früheren Vorschlag" if replaced == 1
                                                           else "frühere Vorschläge"))
    else:
        print("Geschrieben nach %s." % a.orders)
    if a.qty is None:
        print("Die Stückzahl stammt aus %s. Gleich sie vor deinem „ja“ mit deinem Depot ab%s."
              % (source, " (get_open_position %s)" % sym if broker == "alpaca" else ""))
    print("Weiter:")
    print("  1. dt-risiko: check.py. Ein Verkauf, der nur schließt, was du hältst, wird nie von den")
    print("     Tageslimits oder dem Einstiegsfenster gesperrt.")
    print("  2. ticket.py show, dann dein „ja“ für genau diese eine Order.")
    if broker == "alpaca":
        print("  3. Liegen Stop-Loss und Take-Profit der Bracket-Order noch offen, hält Alpaca die Stücke dafür")
        print("     fest und lehnt einen neuen Verkauf ab. Storniere sie zuerst: get_orders (status open, nested")
        print("     true), dann cancel_order_by_id für jede offene Order (Needs approval). Danach place_stock_order")
        print("     mit dem Ticket.")
    elif broker == "ibkr":
        print("  3. Storniere offene Stop- und Limit-Orders auf diese Stücke in IBKR, entwirf dann den Verkauf")
        print("     mit dem Connector und gib ihn in IBKR frei.")
    else:
        print("  3. In deiner App: Verkaufe %s Stück %s bestens; storniere vorher offene Stop-/Limit-Orders auf"
              % (_str_num(qty), sym))
        print("     diese Stücke.%s" % (" PAPIER: nur im Demokonto oder auf Papier." if cfg.get("paper", True)
                                        else ""))
    return 0


def cmd_log(a):
    cfg = read_json(a.config, "Config", required=False) or {}
    _use_market(a, [], cfg)
    state = load_state(a.state)
    now, today = _clock(a)
    rows = [r for r in state.get("orders", []) if a.all or rec_day(r) == today]
    if not rows:
        print("Keine Entscheidungen erfasst%s." % ("" if a.all else " heute"))
        return 1
    for r in rows:
        st = r.get("status")
        extra = (" ID " + r["broker_order_id"]) if r.get("broker_order_id") else ""
        reply = (" Antwort „%s“" % r["reply"]) if r.get("reply") and st in ("approved", "declined") else ""
        loss = ""
        if r.get("max_loss") is not None and st == "placed":
            loss = " max. Verlust %s" % _amt(r["max_loss"], r.get("max_loss_currency")
                                             or markt.currency_of(r.get("symbol")))
        idx = ("#%s" % r["index"]) if r.get("index") is not None else "  "
        print("%s  %s %-14s %s%s%s%s" % (at_label(r.get("at"), r.get("symbol"), with_date=True), idx,
                                         STATUS_WORDS.get(st, st), r.get("plain"), reply, loss, extra))
    placed = sum(1 for r in rows if r.get("status") == "placed")
    print("%d %splatziert." % (placed, "" if a.all else "heute "))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Order-Tickets und dein „ja“ (dt-broker). Platziert nie selbst Orders.")
    sub = ap.add_subparsers(dest="cmd")

    def clock(p):
        p.add_argument("--now", help="tu so, als wäre es diese Ortszeit des Marktes, z. B. \"2026-10-28 10:15\"")
        p.add_argument("--today", help="JJJJ-MM-TT (Standard: heute im Markt des Symbols)")
        p.add_argument("--market", help="xetra oder us, nur nötig ohne Symbol (Standard: aus dem Symbol)")

    def common(p):
        p.add_argument("--orders", default="trader/orders.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--risk", default="trader/state/risk.json")
        p.add_argument("--state", default="trader/state/broker.json")
        clock(p)

    p = sub.add_parser("show", help="die Tickets zeigen")
    common(p)
    p.add_argument("--index", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve", help="dein ausdrückliches „ja“ für eine Order erfassen")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply", required=True, help="deine Antwort, Wort für Wort")
    p = sub.add_parser("decline", help="ein Nein erfassen")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply")
    p = sub.add_parser("result", help="erfassen, was nach deinem „ja“ passiert ist")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--status", required=True, choices=["placed", "denied", "failed"],
                   help="placed = platziert, denied = verweigert, failed = fehlgeschlagen")
    p.add_argument("--broker-id", help="Order-ID des Brokers, wenn es eine gibt")
    p.add_argument("--note")
    p.add_argument("--filled-qty")
    p.add_argument("--filled-price")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p = sub.add_parser("fill", help="eine Ausführung in trader/portfolio.json eintragen")
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", required=True, choices=["buy", "sell"])
    p.add_argument("--qty", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--date", help="JJJJ-MM-TT (Standard: heute im Markt des Symbols)")
    p.add_argument("--now")
    p.add_argument("--market", help=argparse.SUPPRESS)
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--state", default="trader/state/broker.json")
    p = sub.add_parser("flatten", help="Verkaufs-Ticket, das eine Position bis flat_by schließt")
    p.add_argument("--symbol", required=True)
    p.add_argument("--qty", help="Stücke, die du hältst (Standard: aus trader/portfolio.json)")
    p.add_argument("--orders", default="trader/orders.json", help="wohin das Ticket geschrieben wird")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json")
    clock(p)
    p = sub.add_parser("log", help="die Entscheidungen von heute")
    p.add_argument("--state", default="trader/state/broker.json")
    p.add_argument("--config", default="trader/config.json")
    clock(p)
    p.add_argument("--all", action="store_true", help="alle Tage, nicht nur heute")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    with markt.restore():
        try:
            return {"show": cmd_show, "approve": cmd_approve, "decline": cmd_decline, "result": cmd_result,
                    "fill": cmd_fill, "flatten": cmd_flatten, "log": cmd_log}[a.cmd](a)
        except TicketError as e:
            print("ticket.py: %s" % e, file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
