#!/usr/bin/env python3
"""Positionsgröße für dt-budget. Nur Standardbibliothek.

Standard: rechnet EINEN Daytrade aus trader/plan.json (von dt-ausstieg) auf
dein Budget und deinen max. Verlust je Trade und schreibt eine Bracket-Order
(Einstieg, Stop-Loss, Take-Profit) nach trader/orders.json, in der Form von
Alpacas place_stock_order. Platziert wird nichts: dt-risiko prüft die Order,
dt-broker fragt dich ja oder nein.

    python3 size.py                                  # trader/plan.json + trader/config.json
    python3 size.py --write                          # trader/orders.json schreiben
    python3 size.py --limit                          # Limit-Order zum Einstieg laut Plan
    python3 size.py --limit 364.00 --write           # Limit-Order zu 364.00
    python3 size.py --fx 0.86                        # Kurs Kontowährung je 1 Einheit der Aktienwährung
    python3 size.py --now "2026-10-19 10:15" --json  # Uhr festlegen (Ortszeit des Marktes)

Wie viele Aktien. Nur ganze Aktien (eine Bracket-Order kennt keine Bruchstücke).
Alle Limits sind in deiner Kontowährung, Preise in der Währung der Aktie.

    Aktien = abgerundet das Kleinste aus
      max. Verlust   (max_loss_per_trade - 2 x fee_per_order) / Risiko je Aktie
                     Risiko je Aktie = (Einstieg - Stop + Einstieg x spread_buffer_pct/100) x fx
      Positionslimit budget x max_position_pct / (Einstieg x fx)
      max. Order     max_order / (Einstieg x fx)
      Cash           (budget - Cash-Puffer - fee_per_order) / (Einstieg x fx)
                     (und nicht mehr als das Cash in trader/portfolio.json, falls vorhanden)

fx ist die Kontowährung je 1 Einheit der Aktienwährung (EUR-Konto, US-Aktie:
etwa 0.86 EUR je USD). Gleiche Währung: fx = 1. Quelle in dieser Reihenfolge:
--fx, "fx" in der Config, sonst EUR/USD von Yahoo (nicht mit --offline).
Ohne Kurs gibt es keine Order.

Der Einstieg, mit dem gerechnet wird: bei einer Limit-Order ihr Limit; bei
einer Market-Order der Einstieg laut Plan oder der Kurs in trader/prices.json,
wenn er frisch ist (unter 15 Minuten) und höher liegt. Null Aktien (der Stop
liegt zu weit weg für deinen max. Verlust) ist eine klare Ablehnung: keine
Order. Ebenso ein Chance/Risiko unter min_reward_risk.

Gewichtungsmodus (aus v1): verteilt ein Budget nach Gewichten auf eine Liste.

    python3 size.py --weights AAPL=22.04,AXP=17.14,GOOGL=12.62,KO=10.86,BAC=9.20
    python3 size.py --targets my-weights.json --budget 5000 --write
    python3 size.py --weights ... --whole-shares --prices trader/prices.json

  1. Cash-Puffer   budget x cash_buffer_pct bleibt Cash, wird nie investiert
  2. Gewichte      auf 100 normiert über die Werte, die bleiben (gesperrte
                   fallen zuerst raus; --top N behält die N größten)
  3. Deckel        kein Wert bekommt mehr als max_position_pct des Budgets;
                   der Überschuss geht nach Gewicht an die anderen, so lange,
                   bis keiner mehr drüber liegt
  4. Mindestorder  ein Anteil unter min_order fällt weg, sein Gewicht wird verteilt
  5. Runden        ganze Beträge (--cents für Cent); der Rundungsrest geht an
                   die größte Position ohne Deckel
  6. Ganze Aktien  mit --whole-shares oder "fractional": false; braucht Kurse

Geld, das nicht investiert werden kann, steht als „bleibt liegen“ im Bericht.
"""

import argparse
import datetime
import json
import math
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

DEFAULTS = {
    "budget": None,
    "cash_buffer_pct": 10,
    "max_position_pct": 75,
    "max_order": 4000,
    "min_order": 5,
    "max_loss_per_trade": 50,
    "max_daily_loss": 150,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "fee_per_order": 0,
    "spread_buffer_pct": 0,
    "fractional": False,
    "broker": "manuell",
    "paper": True,
    "blocked": [],
    "allow_options": False,
    "allow_margin": False,
    "allow_short": False,
    "pdt_guard": False,
}
AMOUNTS = ("max_loss_per_trade", "max_daily_loss", "max_order", "min_order")
EPS = 1e-9
FRESH_MINUTES = 15
SETUP_WORDS = {"orb": "Opening-Range-Ausbruch", "flag": "Flagge", "bounce": "Gegenbewegung nach Ausverkauf"}
LIMIT_NAMES = {"max_loss": "max. Verlust", "position_cap": "Positionslimit", "max_order": "max. Order",
               "cash": "Cash"}
YAHOO_FX = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?range=1d&interval=1d"


class SizeError(Exception):
    pass


# ---------------------------------------------------------------- time

def parse_now(text, m=None):
    """ISO-Zeit -> naive UTC. Ohne Offset gilt die Ortszeit des Marktes."""
    return markt.parse_now(text, m, error=SizeError)


def parse_utc(text):
    return markt.parse_utc(text)


def utc_iso(now_utc=None):
    now_utc = now_utc or markt.utc_now()
    return now_utc.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- inputs

def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SizeError("%s nicht gefunden: %s" % (what, path))
    except json.JSONDecodeError as e:
        raise SizeError("%s ist kein gültiges JSON: %s" % (path, e))


def load_config(path):
    """Die Config so, wie du sie geschrieben hast (ohne DEFAULTS)."""
    if path and os.path.exists(path):
        cfg = read_json(path, "Config")
        if not isinstance(cfg, dict):
            raise SizeError("%s ist kein JSON-Objekt" % path)
        return cfg
    return {}


def merged(cfg):
    c = dict(DEFAULTS)
    c.update(cfg or {})
    return c


def amount(cfg, key):
    """Betrag in Kontowährung; liest auch alte *_usd-Schlüssel."""
    return _f(markt.amount(cfg or {}, key, DEFAULTS.get(key)))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_weights(data):
    """Nimmt eine Gewichtsdatei, ein {ticker: gewicht}-Objekt oder eine Liste.

    Gibt [{"ticker", "name", "weight"}] zurück, weight als float."""
    if isinstance(data, dict) and "weights" in data:
        data = data["weights"]
    rows = []
    if isinstance(data, dict):
        for t, w in data.items():
            rows.append({"ticker": t, "name": "", "weight": w})
    elif isinstance(data, list):
        for i, r in enumerate(data):
            if not isinstance(r, dict):
                raise SizeError("weights[%d] ist kein Objekt" % i)
            t = r.get("ticker") or r.get("symbol")
            w = r.get("weight", r.get("weight_pct", r.get("pct")))
            if not t or w is None:
                raise SizeError("weights[%d] braucht einen Ticker und ein Gewicht" % i)
            rows.append({"ticker": t, "name": r.get("name", ""), "weight": w})
    else:
        raise SizeError("weights muss eine Liste oder ein Objekt sein")
    out = []
    for r in rows:
        try:
            w = float(r["weight"])
        except (TypeError, ValueError):
            raise SizeError("das Gewicht für %s ist keine Zahl: %r" % (r["ticker"], r["weight"]))
        out.append({"ticker": str(r["ticker"]).strip().upper(), "name": r["name"] or "", "weight": w})
    return out


def weights_from_arg(text):
    """AAPL=22.04,AXP=17.14 -> {ticker: gewicht}"""
    out = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SizeError("--weights erwartet Paare TICKER=GEWICHT, bekam %r" % part)
        t, w = part.split("=", 1)
        out[t.strip().upper()] = w.strip()
    return out


def load_prices(path):
    if not path:
        return {}
    data = read_json(path, "Kursdatei")
    prices = data.get("prices", data) if isinstance(data, dict) else {}
    out = {}
    for t, p in prices.items():
        try:
            out[str(t).upper()] = float(p)
        except (TypeError, ValueError):
            continue
    return out


def price_time(doc, sym):
    """Zeit des Kurses: detail[sym].time, sonst detail[sym].fetched, sonst as_of der Datei."""
    det = ((doc or {}).get("detail") or {}).get(sym) or {}
    for key in ("time", "fetched"):
        t = parse_utc(det.get(key))
        if t:
            return t
    return parse_utc((doc or {}).get("as_of"))


def fresh_price(doc, sym, now_utc, minutes=FRESH_MINUTES):
    """(Kurs, Zeit in UTC, frisch?) für sym aus prices.json, sonst (None, None, False)."""
    if not isinstance(doc, dict):
        return None, None, False
    p = _f((doc.get("prices") or {}).get(sym))
    if p is None or p <= 0:
        return None, None, False
    t = price_time(doc, sym)
    if t is None:
        return p, None, False
    age = (now_utc - t).total_seconds()
    return p, t, -60 <= age <= minutes * 60


# ---------------------------------------------------------------- exchange rate

def fx_from_yahoo_doc(doc, inst, acct):
    """Yahoo EURUSD=X (USD je 1 EUR) -> {"rate", "source", "time"} als Kontowährung je 1 inst."""
    try:
        meta = doc["chart"]["result"][0]["meta"]
        usd_per_eur = float(meta["regularMarketPrice"])
        ts = meta.get("regularMarketTime")
    except (KeyError, IndexError, TypeError, ValueError):
        raise SizeError("die Antwort von Yahoo enthält keinen EUR/USD-Kurs")
    if usd_per_eur <= 0:
        raise SizeError("Yahoo meldet einen EUR/USD-Kurs von %r" % usd_per_eur)
    rate = 1.0 / usd_per_eur if (inst, acct) == ("USD", "EUR") else usd_per_eur
    when = None
    if ts:
        when = (datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(ts))).strftime("%Y-%m-%dT%H:%M:%SZ")
    stand = (" (Stand %s Uhr)" % markt.stamp(markt.to_berlin(parse_utc(when)))) if when else ""
    src = "Yahoo EURUSD=X %s $ je 1 €%s" % (markt.num(usd_per_eur, 4), stand)
    return {"rate": rate, "source": src, "time": when}


def fetch_fx(inst, acct, timeout=10):
    """EUR/USD von Yahoo. Nur dieses Paar."""
    if {inst, acct} != {"EUR", "USD"}:
        raise SizeError("einen Kurs %s/%s kann ich nicht holen: setz \"fx\": {\"%s\": ...} in "
                        "trader/config.json oder nutze --fx" % (inst, acct, inst))
    req = urllib.request.Request(YAHOO_FX, headers={"User-Agent": "Mozilla/5.0 (dt-budget)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SizeError("kein Wechselkurs: Yahoo nicht erreichbar (%s). Setz \"fx\": {\"%s\": ...} in "
                        "trader/config.json oder nutze --fx. Ohne Kurs keine Order." % (e, inst))
    return fx_from_yahoo_doc(doc, inst, acct)


def resolve_fx(cfg, inst, acct, fx=None, sym=None):
    """{"rate", "source", "time"}: 1.0 bei gleicher Währung, sonst fx-Argument, dann cfg["fx"]."""
    if inst == acct:
        return {"rate": 1.0, "source": "", "time": None}
    if isinstance(fx, dict) and _f(fx.get("rate")):
        out = dict(fx)
        out["rate"] = float(fx["rate"])
    elif _f(fx):
        out = {"rate": float(fx), "source": "deine Angabe (--fx)", "time": None}
    else:
        table = {str(k).upper(): v for k, v in ((cfg or {}).get("fx") or {}).items()}
        rate = _f(table.get(inst))
        if not rate:
            raise SizeError("%s notiert in %s, dein Konto ist in %s: es fehlt ein Wechselkurs. Setz "
                            "\"fx\": {\"%s\": 0.86} in trader/config.json (%s je 1 %s) oder nutze --fx. "
                            "Ohne Kurs keine Order." % (sym or "die Aktie", inst, acct, inst, acct, inst))
        out = {"rate": rate, "source": "deine Config (\"fx\")", "time": None}
    if out["rate"] <= 0:
        raise SizeError("der Wechselkurs muss positiv sein, bekam %r" % out["rate"])
    return out


# ---------------------------------------------------------------- money helpers

def round_cent(x):
    """Preis auf den Cent (kaufmännisch)."""
    return math.floor(float(x) * 100 + 0.5 + EPS) / 100.0


def shares_for(money_, per_share):
    """Ganze Aktien, die in money_ passen, bei per_share je Aktie."""
    if per_share <= 0 or money_ <= 0:
        return 0
    return int(math.floor(float(money_) / float(per_share) + EPS))


def _price(x):
    """358.32 -> "358.32": Alpaca will Preise als Strings."""
    return "%.2f" % round_cent(x)


def _num(x):
    """1250 -> "1250", 1118.13 -> "1118.13" (Alpaca will Strings)."""
    x = round(float(x), 2)
    if abs(x - round(x)) < 0.005:
        return str(int(round(x)))
    return "%.2f" % x


def money(x, cur):
    """Kurz: 50 -> "50 $", 46.88 -> "46,88 $"."""
    return markt.money_short(x, cur)


def money_full(x, cur):
    return markt.money(x, cur)


def sym_of(cur):
    return markt.SYMBOLS.get(cur, cur)


def fx_text(rate, inst, acct):
    """0.86 -> "0,8600 €/$"."""
    return "%s %s/%s" % (markt.num(rate, 4), sym_of(acct), sym_of(inst))


def per_share_text(x, cur, exact):
    return "%s %s" % (markt.num(x, 2 if exact else 4), sym_of(cur))


# ---------------------------------------------------------------- plan mode (the default)

def size_trade(plan, cfg, budget=None, limit=None, price=None, cash=None, today=None, fx=None):
    """Reine Funktion: ein Plan + deine Regeln -> die Rechnung (dict). qty kann 0 sein.

    cfg    deine Config, wie du sie geschrieben hast (DEFAULTS werden hier ergänzt)
    limit  Limit-Preis einer Limit-Order (None = Market)
    price  ein FRISCHER Kurs; eine Market-Order wird zum höheren aus ihm und dem Einstieg gerechnet
    cash   das Cash aus trader/portfolio.json, falls vorhanden (Kontowährung)
    today  Datum in Ortszeit des Marktes (YYYY-MM-DD); ein Plan für einen anderen Tag wird abgelehnt
    fx     Kontowährung je 1 Einheit der Aktienwährung (float oder {"rate", "source", "time"})"""
    user = cfg or {}
    c = merged(user)
    if not isinstance(plan, dict):
        raise SizeError("der Plan ist kein JSON-Objekt")
    sym = str(plan.get("symbol") or "").strip().upper()
    if not sym:
        raise SizeError("der Plan hat kein Symbol (lass /dt-ausstieg laufen)")
    mkt = markt.norm(plan["market"]) if plan.get("market") else markt.market_of(sym)
    inst = str(plan.get("currency") or markt.currency_of(sym)).strip().upper()
    acct = markt.account_currency(user)
    side = str(plan.get("side") or "buy").strip().lower()
    if side != "buy":
        raise SizeError("dieses Paket rechnet nur Kauf-Daytrades (long); der Plan sagt %r" % side)
    if today and plan.get("date") and str(plan["date"]) != today:
        raise SizeError("der Plan ist für %s, heute ist %s (%s): mach mit /dt-ausstieg einen neuen Plan"
                        % (plan["date"], today, markt.info(mkt)["zone"]))
    entry_plan, stop, target = _f(plan.get("entry")), _f(plan.get("stop")), _f(plan.get("target"))
    for name, v in (("Einstieg (entry)", entry_plan), ("Stop (stop)", stop), ("Ziel (target)", target)):
        if v is None or v <= 0:
            raise SizeError("der Plan braucht einen positiven %s (lass /dt-ausstieg laufen); eine "
                            "Bracket-Order braucht Einstieg, Stop und Ziel" % name)
    blocked = {str(b).upper() for b in (c.get("blocked") or [])}
    if sym in blocked:
        raise SizeError("%s steht auf deiner Sperrliste (\"blocked\")" % sym)

    budget = float(budget if budget is not None else (c.get("budget") or 0))
    if budget <= 0:
        raise SizeError("kein Budget: nutze --budget oder setz \"budget\" in trader/config.json")
    buf_pct = float(c.get("cash_buffer_pct") or 0)
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct muss zwischen 0 und 100 liegen")
    fee = float(c.get("fee_per_order") or 0)
    spread_pct = float(c.get("spread_buffer_pct") or 0)
    if fee < 0 or spread_pct < 0:
        raise SizeError("fee_per_order und spread_buffer_pct dürfen nicht negativ sein")
    fxi = resolve_fx(user, inst, acct, fx, sym)
    rate = fxi["rate"]

    if limit is not None:
        ref, ref_from = round_cent(limit), "limit"
    elif price is not None and round_cent(price) > round_cent(entry_plan):
        ref, ref_from = round_cent(price), "price"
    else:
        ref, ref_from = round_cent(entry_plan), "plan"
    stop, target = round_cent(stop), round_cent(target)
    if stop >= ref:
        raise SizeError("der Stop %s liegt nicht unter dem Einstieg %s; ein Kauf braucht den Stop darunter"
                        % (markt.num(stop), markt.num(ref)))
    if target <= ref:
        raise SizeError("das Ziel %s liegt nicht über dem Einstieg %s: die Bewegung ist schon gelaufen. "
                        "Lass den Trade aus oder mach mit /dt-ausstieg einen neuen Plan"
                        % (markt.num(target), markt.num(ref)))
    risk_c = int(round((ref - stop) * 100))
    reward_c = int(round((target - ref) * 100))
    risk = risk_c / 100.0
    spread_ps = round(ref * spread_pct / 100.0, 4)
    risk_eff = round(risk + spread_ps, 4)
    risk_acct = risk_eff * rate
    price_acct = ref * rate
    fees = round(2 * fee, 2)
    exact = rate == 1.0 and spread_pct == 0
    A = acct

    cash_buffer = round(budget * buf_pct / 100.0, 2)
    available = budget - cash_buffer
    cash_note = "Budget %s minus %s Cash-Puffer" % (money(budget, A), money(cash_buffer, A))
    if cash is not None and cash - cash_buffer < available - 0.005:
        available = cash - cash_buffer
        cash_note = "Cash %s laut trader/portfolio.json minus %s Puffer" % (money(cash, A), money(cash_buffer, A))
    available = max(round(available, 2), 0.0)
    per_txt = per_share_text(price_acct, A, rate == 1.0)

    limits = []
    max_loss = amount(user, "max_loss_per_trade")
    if max_loss:
        room = max_loss - fees
        how = "%s max. Verlust" % money(max_loss, A)
        if fees:
            how = "(%s - %s Gebühren)" % (how, money(fees, A))
        how += " / %s Risiko je Aktie" % per_share_text(risk_acct, A, exact)
        limits.append({"key": "max_loss", "amount": max_loss, "per": round(risk_acct, 4),
                       "shares": shares_for(room, risk_acct), "how": how})
    cap_pct = _f(c.get("max_position_pct"))
    if cap_pct:
        cap = round(budget * cap_pct / 100.0, 2)
        limits.append({"key": "position_cap", "amount": cap, "per": round(price_acct, 4),
                       "shares": shares_for(cap, price_acct),
                       "how": "%s %% von %s = %s / %s" % (markt.num_short(cap_pct), money(budget, A),
                                                          money(cap, A), per_txt)})
    max_order = amount(user, "max_order")
    if max_order:
        limits.append({"key": "max_order", "amount": max_order, "per": round(price_acct, 4),
                       "shares": shares_for(max_order, price_acct),
                       "how": "%s / %s" % (money(max_order, A), per_txt)})
    cash_room = available - fee
    limits.append({"key": "cash", "amount": available, "per": round(price_acct, 4),
                   "shares": shares_for(cash_room, price_acct),
                   "how": ("%s = (%s - %s Gebühr) / %s" % (cash_note, money(available, A), money(fee, A), per_txt))
                   if fee else ("%s = %s / %s" % (cash_note, money(available, A), per_txt))})
    for l in limits:
        l["name"] = LIMIT_NAMES[l["key"]]

    qty = max(0, min(l["shares"] for l in limits))
    bound = [l["key"] for l in limits if l["shares"] == qty]
    for l in limits:
        l["binds"] = l["key"] == bound[0]
    cost_i = round(qty * ref, 2)
    cost = round(qty * ref * rate, 2)
    loss_i = round(qty * risk_c / 100.0, 2)
    loss = round(qty * risk_eff * rate + (fees if qty else 0), 2)
    refusal = None
    if qty == 0:
        if bound[0] == "max_loss":
            if max_loss - fees <= 0:
                refusal = ("die Gebühren von %s (Kauf und Verkauf) sind so hoch wie dein max. Verlust je Trade "
                           "von %s. Keine Order." % (money(fees, A), money(max_loss, A)))
            else:
                refusal = ("eine Aktie riskiert %s (Einstieg %s minus Stop %s%s), mehr als dein max. Verlust "
                           "je Trade von %s%s. Keine Order. Lass den Trade aus oder plane mit /dt-ausstieg "
                           "einen engeren Stop."
                           % (per_share_text(risk_acct, A, exact), markt.num(ref), markt.num(stop),
                              (" plus %s %% Spread-Puffer" % markt.num_short(spread_pct)) if spread_pct else "",
                              money(max_loss, A), (" nach %s Gebühren" % money(fees, A)) if fees else ""))
        else:
            lim = limits[[l["key"] for l in limits].index(bound[0])]
            refusal = ("eine Aktie %s kostet %s, mehr als dein Limit %s (%s). Keine Order."
                       % (sym, per_txt, lim["name"], lim["how"]))
    elif _f(c.get("min_reward_risk")) and reward_c < _f(c["min_reward_risk"]) * risk_c - EPS:
        refusal = ("Chance/Risiko %s (Ziel %s, Einstieg %s, Stop %s) liegt unter deinem Minimum %s, "
                   "dt-risiko würde sperren. Keine Order. Lass den Trade aus oder mach mit /dt-ausstieg "
                   "einen neuen Plan."
                   % (markt.num(reward_c / float(risk_c)), markt.num(target), markt.num(ref), markt.num(stop),
                      markt.num_short(c["min_reward_risk"])))
    elif cost < float(amount(user, "min_order") or 0) - 0.005:
        refusal = ("%d %s %s für %s liegt unter deiner Mindestorder von %s. Keine Order."
                   % (qty, "Aktie" if qty == 1 else "Aktien", sym, money(cost, A),
                      money(amount(user, "min_order"), A)))
    return {
        "symbol": sym, "side": "buy", "setup": plan.get("setup", ""), "date": plan.get("date"),
        "market": mkt, "currency": inst, "account_currency": acct,
        "fx": rate, "fx_source": fxi.get("source", ""), "fx_time": fxi.get("time"),
        "entry_time": plan.get("entry_time", ""), "entry_plan": round_cent(entry_plan),
        "entry": ref, "entry_from": ref_from, "stop": stop, "target": target,
        "risk_per_share": risk, "spread_buffer_pct": spread_pct, "spread_per_share": round(spread_ps, 4),
        "risk_per_share_account": round(risk_acct, 4), "reward_risk": round(reward_c / float(risk_c), 2),
        "stop_label": plan.get("stop_label", ""), "target_label": plan.get("target_label", ""),
        "budget": budget, "cash_buffer_pct": buf_pct, "cash_buffer": cash_buffer, "cash_available": available,
        "fee_per_order": fee, "fees": fees if qty else 0.0,
        "max_loss_per_trade": max_loss, "limits": limits, "qty": qty, "bound_by": bound[0],
        "cost": cost, "cost_instrument": cost_i, "max_loss": loss, "max_loss_instrument": loss_i,
        "flat_by": plan.get("flat_by") or markt.windows(user, mkt)["flat_by"],
        "broker": str(c.get("broker") or "manuell").lower(),
        "order_type": "limit" if limit is not None else "market", "refusal": refusal,
    }


def loss_expr(s):
    """"8 × 5,86 = 46,88 $" oder "9 × 5,1962 € + 2 € Gebühren = 48,77 €"."""
    A = s["account_currency"]
    exact = s["fx"] == 1.0 and not s["spread_buffer_pct"]
    if exact:
        txt = "%d × %s" % (s["qty"], markt.num(s["risk_per_share"]))
    else:
        txt = "%d × %s" % (s["qty"], per_share_text(s["risk_per_share_account"], A, False))
    if s["fees"]:
        txt += " + %s Gebühren" % money(s["fees"], A)
    return "%s = %s" % (txt, money(s["max_loss"], A))


def bracket_order(s):
    """Die eine vorgeschlagene Order: Alpaca-Felder (Strings) plus why und plan."""
    if s["refusal"] or s["qty"] <= 0:
        return None
    A = s["account_currency"]
    o = {"symbol": s["symbol"], "side": "buy", "qty": str(int(s["qty"])), "type": s["order_type"],
         "time_in_force": "day"}
    if s["order_type"] == "limit":
        o["limit_price"] = _price(s["entry"])
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "Daytrade")
    binds = {"max_loss": "deinen max. Verlust je Trade von %s" % money(s["max_loss_per_trade"] or 0, A),
             "position_cap": "dein Positionslimit", "max_order": "deine max. Ordergröße",
             "cash": "dein Cash nach dem Puffer"}[s["bound_by"]]
    why = "%s bei %s: %d Aktien, begrenzt durch %s (%s am Stop)" % (setup, s["symbol"], s["qty"], binds,
                                                                  loss_expr(s))
    o.update({
        "order_class": "bracket",
        "take_profit_limit_price": _price(s["target"]),
        "stop_loss_stop_price": _price(s["stop"]),
        "why": why,
        "plan": {"entry": s["entry"], "stop": s["stop"], "target": s["target"],
                 "risk_per_share": s["risk_per_share"], "max_loss": s["max_loss"], "setup": s["setup"],
                 "entry_time": s["entry_time"], "flat_by": s["flat_by"],
                 "market": s["market"], "currency": s["currency"], "account_currency": A,
                 "fx": s["fx"], "fees": s["fees"], "spread_buffer_pct": s["spread_buffer_pct"],
                 "max_loss_instrument": s["max_loss_instrument"]},
    })
    return o


def _flat_label(s, today):
    try:
        d = datetime.date.fromisoformat(s["date"] or today)
        h, m = [int(x) for x in str(s["flat_by"]).split(":")]
    except (TypeError, ValueError):
        return str(s["flat_by"])
    return markt.clock_both(datetime.datetime.combine(d, datetime.time(h, m)), s["market"])


def plan_report(s, order, notes=(), today=None):
    A, I = s["account_currency"], s["currency"]
    rate = s["fx"]
    lines = []
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "Setup")
    lines.append("%s Kauf, %s, Einstieg %s%s" % (s["symbol"], setup, money_full(s["entry_plan"], I),
                                                (" um " + s["entry_time"]) if s["entry_time"] else ""))
    lines.append("Stop %s%s. Ziel %s%s." % (money_full(s["stop"], I), (": " + s["stop_label"]) if s["stop_label"] else "",
                                            money_full(s["target"], I),
                                            (": " + s["target_label"]) if s["target_label"] else ""))
    lines.append("Markt %s, Aktie in %s, Konto in %s." % (markt.info(s["market"])["name"], I, A))
    if I != A:
        lines.append("Wechselkurs %s (%s je 1 %s), Quelle: %s." % (fx_text(rate, I, A), A, I, s["fx_source"]))
    for n in notes:
        lines.append(n)
    src = {"plan": "Einstieg laut Plan", "price": "letzter Kurs, über dem Einstieg laut Plan",
           "limit": "dein Limit"}[s["entry_from"]]
    risk_line = "Risiko je Aktie %s (Einstieg %s minus Stop %s)" % (
        money_full(s["risk_per_share"], I), markt.num(s["entry"]), markt.num(s["stop"]))
    if s["spread_buffer_pct"]:
        risk_line += " plus Spread-Puffer %s %% vom Einstieg (%s) = %s" % (
            markt.num_short(s["spread_buffer_pct"]), per_share_text(s["spread_per_share"], I, False),
            per_share_text(s["risk_per_share"] + s["spread_per_share"], I, False))
    if I != A:
        risk_line += " = %s bei %s" % (per_share_text(s["risk_per_share_account"], A, False), fx_text(rate, I, A))
    lines.append("Gerechnet mit %s (%s). %s. Chance/Risiko %s."
                 % (money_full(s["entry"], I), src, risk_line, markt.num(s["reward_risk"])))
    if s["fee_per_order"]:
        lines.append("Gebühren: 2 × %s (Kauf und Verkauf) = %s, zählen voll in den max. Verlust."
                     % (money_full(s["fee_per_order"], A), money_full(2 * s["fee_per_order"], A)))
    lines.append("")
    lines.append("Grenzen (ganze Aktien, die kleinste gewinnt):")
    for l in s["limits"]:
        lines.append("  %-15s %-70s %3d Aktien%s" % (l["name"], l["how"], l["shares"],
                                                     "  <- greift" if l["binds"] else ""))
    lines.append("")
    if order is None:
        lines.append("Keine Order: " + s["refusal"])
        lines.append("Bildung und Werkzeug, keine Anlageberatung.")
        return "\n".join(lines)
    cost = money_full(s["cost"], A)
    if I != A:
        cost = "%s (%s)" % (money_full(s["cost_instrument"], I), cost)
    lines.append("Größe: %d Aktien %s = %s zu %s. Max. Verlust am Stop: %s."
                 % (s["qty"], s["symbol"], cost, markt.num(s["entry"]), loss_expr(s)))
    if I != A or s["spread_buffer_pct"] or s["fees"]:
        lines.append("Reiner Kursverlust bis zum Stop (ohne Spread-Puffer und Gebühren): %d × %s = %s."
                     % (s["qty"], money_full(s["risk_per_share"], I), money_full(s["max_loss_instrument"], I)))
    lines.append("Ein Stop ist eine Order, kein Versprechen: in einem schnellen Markt kann er unter %s "
                 "ausgeführt werden." % markt.num(s["stop"]))
    lines.append("")
    lines.append("Vorgeschlagene Bracket-Order (Argumente für place_stock_order, nichts ist platziert):")
    how = "Limit %s" % order["limit_price"] if order["type"] == "limit" else "Market"
    lines.append("  Kauf %s %s, %s, gültig heute, Take-Profit %s, Stop-Loss %s"
                 % (order["qty"], order["symbol"], how, order["take_profit_limit_price"],
                    order["stop_loss_stop_price"]))
    if s["broker"] != "alpaca":
        lines.append("Viele Neobroker kennen keine Bracket- oder OCO-Order. /dt-broker macht daraus eine "
                     "Klick-Anleitung für deinen Broker (\"broker\": \"%s\")." % s["broker"])
    if s["flat_by"]:
        lines.append("Glatt bis %s: was dann noch offen ist, wird geschlossen (/dt-alarm erinnert, "
                     "/dt-broker flatten)." % _flat_label(s, today))
    lines.append("")
    lines.append("Weiter: /dt-risiko prüft die Order, dann fragt dich /dt-broker ja oder nein.")
    lines.append("Bildung und Werkzeug, keine Anlageberatung.")
    return "\n".join(lines)


# ---------------------------------------------------------------- weights mode (v1)

def normalise(rows, blocked=(), top=None):
    """Gesperrte und nicht positive Gewichte raus, Top N behalten, auf 100 normieren."""
    blocked = {str(b).upper() for b in (blocked or [])}
    dropped, keep, seen = [], [], set()
    for r in rows:
        if r["ticker"] in seen:
            raise SizeError("%s steht zweimal in den Gewichten" % r["ticker"])
        seen.add(r["ticker"])
        if r["ticker"] in blocked:
            dropped.append({"ticker": r["ticker"], "reason": "steht auf deiner Sperrliste (blocked)"})
        elif r["weight"] <= 0:
            dropped.append({"ticker": r["ticker"], "reason": "Gewicht ist null oder negativ"})
        else:
            keep.append(dict(r))
    keep.sort(key=lambda r: -r["weight"])
    if top:
        for r in keep[top:]:
            dropped.append({"ticker": r["ticker"], "reason": "nicht unter den größten %d" % top})
        keep = keep[:top]
    total = sum(r["weight"] for r in keep)
    for r in keep:
        r["source_weight"] = r["weight"]
        r["weight"] = 100.0 * r["weight"] / total if total else 0.0
    return keep, dropped


def allocate(rows, investable, cap):
    """Exakte (ungerundete) Beträge je Ticker, mit Deckel.

    Anteilig nach Gewicht; wer über dem Deckel liegt, bekommt den Deckel, der
    Rest wird auf die anderen verteilt, bis keiner mehr drüber liegt.
    Gibt ({ticker: betrag}, Menge der gedeckelten Ticker) zurück."""
    alloc, capped = {}, set()
    active = [r for r in rows]
    money_left = investable
    while active:
        wsum = sum(r["weight"] for r in active)
        trial = {r["ticker"]: money_left * r["weight"] / wsum for r in active}
        over = [r for r in active if trial[r["ticker"]] > cap + EPS]
        if not over:
            alloc.update(trial)
            break
        for r in over:
            alloc[r["ticker"]] = cap
            capped.add(r["ticker"])
            money_left -= cap
        active = [r for r in active if r["ticker"] not in capped]
        if money_left <= EPS:
            for r in active:
                alloc[r["ticker"]] = 0.0
            break
    return alloc, capped


def round_to_unit(exact, capped, order, cap, unit):
    """Auf ganze Beträge (unit 1) oder Cent (unit 0.01) runden, Summe halten.

    Die Summe ist die exakte Summe ABGERUNDET, also nie mehr Geld als da ist.
    Jeder Anteil wird gerundet, die Differenz geht an den größten Wert ohne
    Deckel, dann den nächsten, ohne jemanden über den Deckel zu schieben."""
    def units(x):
        return int(math.floor(x / unit + EPS))

    cap_u = units(cap)
    total_u = units(sum(exact.values()))
    out = {}
    for t, v in exact.items():
        out[t] = cap_u if t in capped else int(math.floor(v / unit + 0.5 + EPS))
    diff = total_u - sum(out.values())
    takers = [t for t in order if t not in capped]
    guard = 0
    while diff != 0 and takers and guard < 100000:
        moved = False
        for t in takers:
            if diff == 0:
                break
            if diff > 0 and out[t] + 1 <= cap_u:
                out[t] += 1
                diff -= 1
                moved = True
            elif diff < 0 and out[t] > 0:
                out[t] -= 1
                diff += 1
                moved = True
        if not moved:
            break
        guard += 1
    return {t: round(u * unit, 2) for t, u in out.items()}


def whole_shares(dollars, prices, order, cap, cash):
    """Ganze Aktien: jeden Anteil abrunden, dann je eine Aktie mehr für den Wert,
    der am weitesten unter seinem Anteil liegt, solange Cash und Deckel reichen."""
    shares = {}
    for t in order:
        shares[t] = int(math.floor(dollars[t] / prices[t] + EPS)) if dollars[t] > 0 else 0
    spent = sum(shares[t] * prices[t] for t in order)
    left = cash - spent
    while True:
        best, gap = None, None
        for t in order:
            p = prices[t]
            if p > left + EPS or (shares[t] + 1) * p > cap + EPS:
                continue
            g = dollars[t] - shares[t] * p
            if best is None or g > gap + EPS:
                best, gap = t, g
        if best is None:
            break
        shares[best] += 1
        left -= prices[best]
    return shares


def size(rows, cfg, budget=None, prices=None, whole=None, cents=False, top=None):
    """Gewichtungsmodus. Reine Funktion: Gewichte + Regeln -> die ganze Rechnung (dict)."""
    acct = markt.account_currency(cfg)
    budget = float(budget if budget is not None else (cfg.get("budget") or 0))
    if budget <= 0:
        raise SizeError("kein Budget: nutze --budget oder setz \"budget\" in trader/config.json")
    buf_pct = float(cfg.get("cash_buffer_pct", 10))
    cap_pct = float(cfg.get("max_position_pct", 25))
    min_order = float(markt.amount(cfg, "min_order", 5) or 0)
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct muss zwischen 0 und 100 liegen")
    if not 0 < cap_pct <= 100:
        raise SizeError("max_position_pct muss über 0 und höchstens 100 sein")
    if whole is None:
        whole = not cfg.get("fractional", True)
    prices = prices or {}

    keep, dropped = normalise(rows, cfg.get("blocked"), top)
    if not keep:
        raise SizeError("nichts zu verteilen: nach der Sperrliste bleibt kein Gewicht übrig")

    cash_buffer = round(budget * buf_pct / 100.0, 2)
    investable = round(budget - cash_buffer, 2)
    cap = round(budget * cap_pct / 100.0, 2)
    unit = 0.01 if (cents or whole) else 1.0

    if whole:
        missing = [r["ticker"] for r in keep if not prices.get(r["ticker"])]
        if missing:
            raise SizeError("ganze Aktien brauchen einen Kurs für: %s (in trader/prices.json, z. B. mit "
                            "/dt-alarm: alerts.py quote %s --write)" % (", ".join(missing), " ".join(missing)))

    while True:
        live = [dict(r) for r in keep]
        tot = sum(r["source_weight"] for r in live)
        for r in live:
            r["weight"] = 100.0 * r["source_weight"] / tot
        exact, capped = allocate(live, investable, cap)
        order = [r["ticker"] for r in sorted(live, key=lambda r: -exact[r["ticker"]])]
        dollars = round_to_unit(exact, capped, order, cap, unit)
        shares = None
        if whole:
            shares = whole_shares(dollars, prices, order, cap, sum(dollars.values()))
            dollars = {t: round(shares[t] * prices[t], 2) for t in order}
        small = [r for r in live if dollars[r["ticker"]] < min_order - EPS]
        if not small:
            break
        worst = min(small, key=lambda r: (r["source_weight"], r["ticker"]))
        if whole and shares is not None and shares[worst["ticker"]] == 0 and prices.get(worst["ticker"], 0) > 0:
            reason = ("eine Aktie kostet %s, mehr als ihr Anteil; in ganzen Aktien nicht kaufbar"
                      % money(prices[worst["ticker"]], acct))
        else:
            reason = "ihr Anteil (%s) liegt unter deiner Mindestorder von %s" % (
                money(dollars[worst["ticker"]], acct), money(min_order, acct))
        dropped.append({"ticker": worst["ticker"], "reason": reason})
        keep = [r for r in keep if r["ticker"] != worst["ticker"]]
        if not keep:
            raise SizeError("jeder Anteil liegt unter deiner Mindestorder; erhöhe das Budget oder nimm weniger Werte")

    positions = []
    for r in sorted(live, key=lambda r: -r["weight"]):
        t = r["ticker"]
        p = {"ticker": t, "name": r["name"], "weight": round(r["weight"], 2),
             "source_weight": r["source_weight"], "dollars": dollars[t],
             "capped": t in capped}
        if prices.get(t):
            p["price"] = prices[t]
            p["shares"] = shares[t] if whole else round(dollars[t] / prices[t], 4)
        positions.append(p)
    invested = round(sum(p["dollars"] for p in positions), 2)
    return {
        "budget": budget, "account_currency": acct, "cash_buffer_pct": buf_pct, "cash_buffer": cash_buffer,
        "investable": investable, "max_position_pct": cap_pct, "cap": cap,
        "min_order": min_order, "whole_shares": bool(whole),
        "positions": positions, "invested": invested,
        "idle": round(investable - invested, 2), "dropped": dropped,
    }


def orders_from(result, source=""):
    """Gewichtungsmodus: je Position eine Kauf-Order in der Form von place_stock_order."""
    out = []
    acct = result.get("account_currency", "EUR")
    for p in result["positions"]:
        if p["dollars"] <= 0:
            continue
        why = "%s der Aufteilung" % markt.pct(p["weight"])
        if source:
            why = "%s, Gewichte aus %s" % (why, source)
        if p["capped"]:
            why += "; gedeckelt bei %s %% des Budgets von %s" % (markt.num_short(result["max_position_pct"]),
                                                                money(result["budget"], acct))
        o = {"symbol": p["ticker"], "side": "buy"}
        if result["whole_shares"]:
            o["qty"] = str(int(p["shares"]))
        else:
            o["notional"] = _num(p["dollars"])
        o.update({"type": "market", "time_in_force": "day", "why": why})
        out.append(o)
    return out


def report(result, orders, source=""):
    """Tabelle im Gewichtungsmodus."""
    r = result
    A = r.get("account_currency", "EUR")
    lines = []
    if source:
        lines.append("Gewichte aus: %s" % source)
    lines.append("Budget %s, Cash-Puffer %s %% = %s, investiert werden %s, Deckel %s %% = %s je Wert"
                 % (money_full(r["budget"], A), markt.num_short(r["cash_buffer_pct"]), money_full(r["cash_buffer"], A),
                    money_full(r["investable"], A), markt.num_short(r["max_position_pct"]), money_full(r["cap"], A)))
    lines.append("")
    has_price = any("price" in p for p in r["positions"])
    head = "%-7s %-22s %9s %13s" % ("Ticker", "Name", "Gewicht", "Betrag")
    if has_price:
        head += " %12s %10s" % ("Kurs", "Aktien")
    lines.append(head + "  Hinweis")
    for p in r["positions"]:
        row = "%-7s %-22s %9s %13s" % (p["ticker"], (p["name"] or "")[:22], markt.pct(p["weight"]),
                                       money_full(p["dollars"], A))
        if has_price:
            row += " %12s %10s" % (markt.num(p["price"]) if "price" in p else "", p.get("shares", ""))
        if p["capped"]:
            row += "  gedeckelt bei %s %%" % markt.num_short(r["max_position_pct"])
        lines.append(row)
    lines.append("%-7s %-22s %9s %13s" % ("", "investiert", "", money_full(r["invested"], A)))
    lines.append("%-7s %-22s %9s %13s" % ("", "Cash-Puffer", "", money_full(r["cash_buffer"], A)))
    lines.append("%-7s %-22s %9s %13s" % ("", "bleibt liegen", "", money_full(r["idle"], A)))
    if r["idle"] >= 1:
        lines.append("")
        lines.append("Bleibt liegen %s: %s" % (money_full(r["idle"], A), (
            "ganze Aktien gehen nicht glatt auf" if r["whole_shares"]
            else "jeder Wert ist am Deckel; nimm mehr Werte oder erhöhe max_position_pct")))
    for d in r["dropped"]:
        lines.append("Weggelassen %s: %s" % (d["ticker"], d["reason"]))
    foreign = sorted({p["ticker"] for p in r["positions"] if markt.currency_of(p["ticker"]) != A})
    if foreign:
        lines.append("Achtung: %s notier%s nicht in %s. Die Beträge sind in %s; rechne beim Broker um."
                     % (", ".join(foreign), "t" if len(foreign) == 1 else "en", A, A))
    lines.append("")
    lines.append("Vorgeschlagene Orders (Argumente für place_stock_order, nichts ist platziert):")
    for o in orders:
        amt = ("notional \"%s\"" % o["notional"]) if "notional" in o else ("qty \"%s\"" % o["qty"])
        lines.append("  Kauf %s %s, Market, gültig heute" % (o["symbol"], amt))
    lines.append("")
    lines.append("Diese Käufe haben keinen Stop. /dt-risiko sperrt sie, solange \"require_stop\" true ist, "
                 "und legt deine Daytrade-Limits an jeden Kauf an.")
    lines.append("Weiter: /dt-risiko prüft jede Order, dann fragt dich /dt-broker für jede einzeln ja oder nein.")
    lines.append("Bildung und Werkzeug, keine Anlageberatung.")
    return "\n".join(lines)


# ---------------------------------------------------------------- orders file

def write_orders(path, orders, cfg, source="", now_utc=None):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    doc = {
        "created_by": "dt-budget",
        "created_at": utc_iso(now_utc),
        "status": "proposed",
        "paper": bool(merged(cfg).get("paper", True)),
        "account_currency": markt.account_currency(cfg),
        "note": ("Nur Vorschläge. Nichts wird platziert, bevor /dt-risiko jede Order freigibt "
                 "und du im Chat ja zu ihr sagst."),
        "source": source,
        "orders": orders,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- main

def run_plan(a, cfg):
    try:
        plan = read_json(a.plan, "Plan")
    except SizeError as e:
        raise SizeError("%s (lass zuerst /dt-ausstieg laufen, oder nutze --weights für eine Aufteilung)" % e)
    if not isinstance(plan, dict):
        raise SizeError("der Plan ist kein JSON-Objekt")
    sym = str(plan.get("symbol") or "").upper()
    m = markt.resolve(flag=a.market or plan.get("market"), symbols=[sym], cfg=cfg)
    markt.use(m)
    now = parse_now(a.now)
    today = markt.to_local(now).date().isoformat()
    limit = None
    if a.limit is not None:
        if a.limit == "plan":
            limit = _f(plan.get("entry"))
        else:
            limit = markt.parse_number(a.limit)
            if limit is None or limit <= 0:
                raise SizeError("--limit erwartet einen Preis, etwa --limit 364.00")
    notes, price = [], None
    ppath = a.prices or ("trader/prices.json" if os.path.exists("trader/prices.json") else None)
    if ppath and limit is None and sym:
        pdoc = read_json(ppath, "Kursdatei")
        p, t, fresh = fresh_price(pdoc, sym, now)
        if p is not None and fresh:
            price = p
            if round_cent(p) > round_cent(_f(plan.get("entry")) or 0):
                notes.append("%s zuletzt %s (Stand %s) liegt über dem Einstieg laut Plan %s, das Risiko ist "
                             "größer: gerechnet mit %s." % (sym, markt.num(p), markt.clock_both(markt.to_local(t)),
                                                            markt.num(_f(plan.get("entry"))), markt.num(round_cent(p))))
        elif p is not None:
            notes.append("%s in %s ist %s: nicht verwendet (älter als %d Minuten). Gerechnet mit dem Einstieg "
                         "laut Plan." % (sym, ppath, ("von " + markt.stamp(markt.to_local(t)) + " " +
                                                      markt.info()["suffix"]) if t else "ohne Zeitangabe",
                                         FRESH_MINUTES))
    cash = None
    if a.portfolio and os.path.exists(a.portfolio):
        pf = read_json(a.portfolio, "Depot")
        cash = _f(pf.get("cash")) if isinstance(pf, dict) else None
    fx = None
    if a.fx is not None:
        fx = markt.parse_number(a.fx)
        if not fx or fx <= 0:
            raise SizeError("--fx erwartet einen Kurs wie 0.86 (Kontowährung je 1 Einheit der Aktienwährung)")
        fx = {"rate": fx, "source": "deine Angabe (--fx)", "time": None}
    else:
        inst = str(plan.get("currency") or markt.currency_of(sym)).upper()
        acct = markt.account_currency(cfg)
        has_cfg = _f({str(k).upper(): v for k, v in (cfg.get("fx") or {}).items()}.get(inst))
        if sym and inst != acct and not has_cfg:
            if a.offline:
                raise SizeError("%s notiert in %s, dein Konto ist in %s: es fehlt ein Wechselkurs (--offline, also "
                                "kein Abruf bei Yahoo). Setz \"fx\" in trader/config.json oder nutze --fx. Ohne Kurs "
                                "keine Order." % (sym, inst, acct))
            fx = fetch_fx(inst, acct)
    s = size_trade(plan, cfg, a.budget, limit, price, cash, today, fx)
    order = bracket_order(s)
    if order and a.write:
        src = "trader/plan.json (%s %s %s)" % (s["symbol"], s["setup"] or "plan", s["date"] or today)
        write_orders(a.write, [order], cfg, src, now)
    if a.json:
        print(json.dumps({"sizing": s, "orders": [order] if order else [], "notes": notes}, indent=2,
                         ensure_ascii=False))
    else:
        print(plan_report(s, order, notes, today))
        if order and a.write:
            print("1 vorgeschlagene Bracket-Order nach %s geschrieben." % a.write)
    return 0 if order else 1


def run_weights(a, cfg):
    source = ""
    if a.weights:
        rows = parse_weights(weights_from_arg(a.weights))
    else:
        data = read_json(a.targets, "Gewichtsdatei")
        rows = parse_weights(data)
        if isinstance(data, dict):
            source = data.get("source", "")
    prices = load_prices(a.prices)
    if not prices and os.path.exists("trader/prices.json") and not a.prices:
        prices = load_prices("trader/prices.json")
    whole = True if a.whole_shares else None
    c = merged(cfg)
    for k in AMOUNTS:
        c.pop(k, None)
        if markt.amount(cfg, k) is not None:
            c[k] = markt.amount(cfg, k)
    if "account_currency" not in c:
        c["account_currency"] = markt.account_currency(cfg)
    result = size(rows, c, a.budget, prices, whole, a.cents, a.top)
    orders = orders_from(result, source)
    if a.write:
        write_orders(a.write, orders, cfg, source, parse_now(a.now))
    if a.json:
        print(json.dumps({"result": result, "orders": orders}, indent=2, ensure_ascii=False))
    else:
        print(report(result, orders, source))
        if a.write:
            print("%d vorgeschlagene Orders nach %s geschrieben." % (len(orders), a.write))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rechnet einen Daytrade auf dein Budget und deinen max. Verlust "
                                             "(dt-budget).")
    ap.add_argument("--plan", default="trader/plan.json", help="der Trade-Plan (Standard trader/plan.json)")
    ap.add_argument("--config", default="trader/config.json", help="deine Regeln (Standard trader/config.json)")
    ap.add_argument("--budget", type=float, help="Budget aus der Config überschreiben (Kontowährung)")
    ap.add_argument("--limit", nargs="?", const="plan", metavar="PREIS",
                    help="Limit- statt Market-Order, zum Einstieg laut Plan oder zu PREIS")
    ap.add_argument("--prices", help="Kurse als JSON (Standard trader/prices.json, falls vorhanden)")
    ap.add_argument("--portfolio", default="trader/portfolio.json",
                    help="dein Konto; sein Cash begrenzt die Größe, falls die Datei existiert")
    ap.add_argument("--fx", metavar="KURS",
                    help="Wechselkurs: Kontowährung je 1 Einheit der Aktienwährung, z. B. 0.86 (EUR je USD)")
    ap.add_argument("--offline", action="store_true", help="keinen Wechselkurs bei Yahoo holen")
    ap.add_argument("--market", help="xetra oder us (sonst aus dem Symbol)")
    ap.add_argument("--now", help="so tun, als wäre es diese Zeit, z. B. \"2026-10-19 10:15\"; ohne Offset "
                                  "gilt die Ortszeit des Marktes (XETRA: deutsche Zeit, US: New Yorker Zeit)")
    ap.add_argument("--write", nargs="?", const="trader/orders.json", metavar="PFAD",
                    help="die vorgeschlagene Order schreiben (Standard trader/orders.json)")
    ap.add_argument("--json", action="store_true", help="JSON statt Bericht ausgeben")
    g = ap.add_argument_group("Gewichtungsmodus (ein Budget auf eine Liste verteilen)")
    g.add_argument("--weights", help="Gewichte direkt: AAPL=22.04,AXP=17.14")
    g.add_argument("--targets", help="eine Gewichtsdatei: {\"weights\": [{\"ticker\", \"weight\"}]}")
    g.add_argument("--top", type=int, help="nur die N größten Gewichte behalten")
    g.add_argument("--whole-shares", action="store_true", help="nur ganze Aktien (braucht --prices)")
    g.add_argument("--cents", action="store_true", help="auf den Cent statt auf ganze Beträge")
    a = ap.parse_args(argv)
    with markt.restore():
        try:
            cfg = load_config(a.config)
            if a.weights or a.targets:
                markt.use(markt.resolve(flag=a.market, cfg=cfg))
                return run_weights(a, cfg)
            if a.top or a.whole_shares or a.cents:
                raise SizeError("--top, --whole-shares und --cents gehen nur mit --weights oder --targets")
            return run_plan(a, cfg)
        except (SizeError, markt.MarketError) as e:
            print("size.py: %s" % e, file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
