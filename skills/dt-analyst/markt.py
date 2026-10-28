"""Märkte für das Daytrader-Skill-Paket: XETRA (Standard) und US (NYSE/Nasdaq).

Nur Standardbibliothek, ohne Zeitzonen-Dateien (Python 3.8). Diese Datei liegt
als identische Kopie in jedem Skill-Ordner, damit jeder Ordner allein läuft;
tests/test_repo.py prüft, dass alle Kopien gleich sind.

Der Markt eines Symbols folgt aus dem Symbol: SAP.DE ist XETRA, TSLA ist US.
Ohne Symbol entscheidet --market, dann "market" in trader/config.json, dann XETRA.

    import markt
    markt.use("xetra")                      # oder markt.use_for("TSLA")
    markt.to_local(utc)                     # naive Ortszeit des Marktes
    markt.session(datum)                    # (Eröffnung, Schluss) oder None
    markt.money(1234.5)                     # "1.234,50 €"
"""

import contextlib
import datetime
import re

XETRA_HOLIDAYS = {
    "2026-01-01": "Neujahr",
    "2026-04-03": "Karfreitag",
    "2026-04-06": "Ostermontag",
    "2026-05-01": "Tag der Arbeit",
    "2026-12-24": "Heiligabend",
    "2026-12-25": "1. Weihnachtstag",
    "2026-12-31": "Silvester",
    "2027-01-01": "Neujahr",
    "2027-03-26": "Karfreitag",
    "2027-03-29": "Ostermontag",
    "2027-12-24": "Heiligabend",
    "2027-12-31": "Silvester",
}
XETRA_EARLY_CLOSE = {
    "2026-12-30": "Jahresschlussbörse, letzter Handelstag des Jahres",
}
NYSE_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}
NYSE_EARLY_CLOSE = {
    "2026-11-27": "Tag nach Thanksgiving",
    "2026-12-24": "Heiligabend",
    "2027-11-26": "Tag nach Thanksgiving",
}
CALENDAR_YEARS = (2026, 2027)

MARKETS = {
    "xetra": {
        "key": "xetra",
        "name": "XETRA",
        "exchange": "XETRA",
        "tz": "Europe/Berlin",
        "zone": "deutscher Zeit",
        "suffix": "Uhr",
        "open": datetime.time(9, 0),
        "close": datetime.time(17, 30),
        "early": datetime.time(14, 0),
        "holidays": XETRA_HOLIDAYS,
        "early_close": XETRA_EARLY_CLOSE,
        "currency": "EUR",
        "calendar_source": "Handelskalender der Deutschen Börse (deutsche-boerse.com, gelesen am 28.10.2026)",
        "windows": {"no_entries_before": "09:15", "no_entries_after": "17:00", "flat_by": "17:25"},
    },
    "us": {
        "key": "us",
        "name": "US (NYSE/Nasdaq)",
        "exchange": "NYSE",
        "tz": "America/New_York",
        "zone": "New Yorker Zeit",
        "suffix": "ET",
        "open": datetime.time(9, 30),
        "close": datetime.time(16, 0),
        "early": datetime.time(13, 0),
        "holidays": NYSE_HOLIDAYS,
        "early_close": NYSE_EARLY_CLOSE,
        "currency": "USD",
        "calendar_source": "NYSE-Kalender (nyse.com, gelesen am 13.10.2026)",
        "windows": {"no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55"},
    },
}
ALIASES = {"xetra": "xetra", "de": "xetra", "xetr": "xetra", "deutschland": "xetra",
           "us": "us", "usa": "us", "nyse": "us", "nasdaq": "us"}
XETRA_SUFFIX = re.compile(r"\.(DE)$", re.I)
GERMAN_SUFFIX = re.compile(r"\.(DE|F|SG|MU|DU|HM|BE|HA)$", re.I)
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
SYMBOLS = {"EUR": "\u20ac", "USD": "$"}
DEFAULT = "xetra"

_state = {"market": DEFAULT}


class MarketError(Exception):
    pass


# ---------------------------------------------------------------- which market

def norm(name):
    """'XETRA', 'de', 'US' -> 'xetra' / 'us'; anything else raises MarketError."""
    key = ALIASES.get(str(name or "").strip().lower())
    if not key:
        raise MarketError("unbekannter Markt %r: erlaubt sind xetra und us" % name)
    return key


def market_of(symbol):
    """Der Markt eines Symbols: SAP.DE -> xetra, TSLA -> us."""
    return "xetra" if XETRA_SUFFIX.search(str(symbol or "").strip()) else "us"


def use(name):
    _state["market"] = norm(name)
    return _state["market"]


def use_for(symbol):
    return use(market_of(symbol))


def current():
    return _state["market"]


def info(m=None):
    return MARKETS[norm(m) if m else _state["market"]]


def resolve(flag=None, symbols=None, cfg=None):
    """--market, dann das erste Symbol, dann config "market", dann XETRA."""
    if flag:
        return norm(flag)
    for s in symbols or ():
        if s:
            return market_of(s)
    if isinstance(cfg, dict) and cfg.get("market"):
        return norm(cfg["market"])
    return DEFAULT


@contextlib.contextmanager
def using(name):
    prev = _state["market"]
    use(name)
    try:
        yield MARKETS[_state["market"]]
    finally:
        _state["market"] = prev


@contextlib.contextmanager
def restore():
    """Stellt den Markt nach einem Befehl wieder her (main() in jedem Tool)."""
    prev = _state["market"]
    try:
        yield
    finally:
        _state["market"] = prev


# ---------------------------------------------------------------- time

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def _last_sunday(year, month):
    d = datetime.date(year + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def berlin_offset(utc):
    """Stunden ab UTC für Berlin: +2 in der Sommerzeit (MESZ), sonst +1 (MEZ).
    EU-Regel: vom letzten Sonntag im März 01:00 UTC bis zum letzten Sonntag im Oktober 01:00 UTC."""
    y = utc.year
    start = datetime.datetime.combine(_last_sunday(y, 3), datetime.time(1, 0))
    end = datetime.datetime.combine(_last_sunday(y, 10), datetime.time(1, 0))
    return 2 if start <= utc.replace(tzinfo=None) < end else 1


def eastern_offset(utc):
    """Stunden ab UTC für New York: -4 in der Sommerzeit, sonst -5.
    US-Regel seit 2007: zweiter Sonntag im März 2:00 bis erster Sonntag im November 2:00."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))
    return -4 if start <= utc.replace(tzinfo=None) < end else -5


def offset(utc, m=None):
    return berlin_offset(utc) if info(m)["key"] == "xetra" else eastern_offset(utc)


def to_local(utc, m=None):
    """Naive UTC -> naive Ortszeit des Marktes. Nutzt nie die Zeitzone des Rechners."""
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=offset(utc, m))


def to_berlin(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=berlin_offset(utc))


def to_eastern(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def local_to_utc(local, m=None):
    offs = (2, 1) if info(m)["key"] == "xetra" else (-4, -5)
    for off in offs:
        utc = local - datetime.timedelta(hours=off)
        if offset(utc, m) == off:
            return utc
    return local - datetime.timedelta(hours=offs[-1])


def ts_to_local(ts, m=None):
    """Unix-Sekunden -> naive Ortszeit des Marktes."""
    return to_local(datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(ts)), m)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def parse_now(text, m=None, error=MarketError):
    """ISO-Zeit -> naive UTC. Ohne Offset gilt die Ortszeit des Marktes."""
    if not text:
        return utc_now()
    t = str(text).strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise error('--now erwartet eine Zeit wie "2026-10-28 10:15" (%s) oder ...Z (UTC)' % info(m)["zone"])
    if dt.tzinfo is None:
        return local_to_utc(dt, m)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_utc(text):
    """"2026-10-19T14:52:13Z" -> naive UTC, oder None."""
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------- calendar

def trading_day(d, m=None):
    """(Handelstag?, Grund)."""
    mk = info(m)
    if d.weekday() >= 5:
        return False, "Wochenende"
    name = mk["holidays"].get(d.isoformat())
    if name:
        return False, "Börsenfeiertag %s: %s" % (mk["exchange"], name)
    return True, ""


def early_close(d, m=None):
    return info(m)["early_close"].get(d.isoformat())


def session(d, m=None):
    """(Eröffnung, Schluss) in Ortszeit, oder None an einem handelsfreien Tag."""
    mk = info(m)
    if not trading_day(d, m)[0]:
        return None
    return mk["open"], (mk["early"] if d.isoformat() in mk["early_close"] else mk["close"])


def in_calendar(d):
    return d.year in CALENDAR_YEARS


def windows(cfg=None, m=None):
    """no_entries_before / no_entries_after / flat_by für diesen Markt.
    Reihenfolge: cfg["zeiten"][markt][key], dann cfg[key], dann der Standard des Marktes."""
    mk = info(m)
    out = dict(mk["windows"])
    cfg = cfg if isinstance(cfg, dict) else {}
    for k in out:
        if k in cfg:
            out[k] = cfg[k]
    per = (cfg.get("zeiten") or {}).get(mk["key"]) or {}
    for k in out:
        if k in per:
            out[k] = per[k]
    return out


# ---------------------------------------------------------------- currency

def currency_of(symbol):
    return "EUR" if GERMAN_SUFFIX.search(str(symbol or "").strip()) else "USD"


def account_currency(cfg=None):
    """Kontowährung: cfg "account_currency", sonst USD bei alten *_usd-Schlüsseln, sonst EUR."""
    cfg = cfg if isinstance(cfg, dict) else {}
    if cfg.get("account_currency"):
        return str(cfg["account_currency"]).strip().upper()
    if any(str(k).endswith("_usd") for k in cfg):
        return "USD"
    return "EUR"


def amount(cfg, key, default=None):
    """Betrag aus der Config: "max_loss_per_trade", alt "max_loss_per_trade_usd"."""
    cfg = cfg if isinstance(cfg, dict) else {}
    for k in (key, key + "_usd", key + "_eur"):
        if cfg.get(k) is not None:
            return cfg[k]
    return default


# ---------------------------------------------------------------- yahoo symbols

def to_yahoo(sym):
    """BRK.B -> BRK-B; SAP.DE bleibt SAP.DE."""
    s = str(sym).strip().upper()
    if GERMAN_SUFFIX.search(s):
        return s
    return s.replace(".", "-")


def from_yahoo(ysym):
    s = str(ysym).strip().upper()
    if GERMAN_SUFFIX.search(s):
        return s
    return s.replace("-", ".")


# ---------------------------------------------------------------- German formats

def num(x, nd=2):
    """1234.5 -> "1.234,50"."""
    s = "{:,.{nd}f}".format(float(x), nd=nd)
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def num_short(x, nd=2):
    """Ganze Zahlen ohne Nachkommastellen: 50 -> "50", 46.88 -> "46,88"."""
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return num(round(x), 0)
    return num(x, nd)


def money(x, cur=None, nd=2):
    """1234.5 -> "1.234,50 €" (Währung des aktuellen Marktes, sonst cur)."""
    cur = (cur or info()["currency"]).upper()
    return "%s %s" % (num(x, nd), SYMBOLS.get(cur, cur))


def money_short(x, cur=None):
    """50 -> "50 €", 46.88 -> "46,88 €"."""
    cur = (cur or info()["currency"]).upper()
    return "%s %s" % (num_short(x), SYMBOLS.get(cur, cur))


def price(x, nd=2):
    return num(x, nd)


def pct(x, nd=2, sign=False):
    """0.55 -> "0,55 %" (mit sign: "+0,55 %")."""
    s = num(abs(float(x)) if sign else float(x), nd)
    if sign:
        s = ("-" if float(x) < 0 else "+") + s
    return s + " %"


def clock(t):
    """datetime oder time -> "10:15"."""
    return "%02d:%02d" % (t.hour, t.minute)


def clock_label(t, m=None):
    """"10:15 Uhr" an XETRA, "10:15 ET" in New York."""
    return "%s %s" % (clock(t), info(m)["suffix"])


def clock_both(local, m=None):
    """Für US-Zeiten zusätzlich die deutsche Zeit: "10:15 ET (16:15 Uhr)"."""
    mk = info(m)
    if mk["key"] == "xetra" or not isinstance(local, datetime.datetime):
        return clock_label(local, m)
    de = to_berlin(local_to_utc(local, m))
    return "%s (%s Uhr)" % (clock_label(local, m), clock(de))


def date_de(d):
    """date -> "19.10.2026"."""
    return "%02d.%02d.%04d" % (d.day, d.month, d.year)


def day_label(d):
    """date -> "Mo 19.10.2026"."""
    return "%s %s" % (WEEKDAYS[d.weekday()], date_de(d))


def stamp(local):
    """datetime -> "Mo 19.10.2026 10:15"."""
    return "%s %s" % (day_label(local.date() if isinstance(local, datetime.datetime) else local), clock(local))


def parse_number(text):
    """"364,50" oder "364.50" -> 364.5; sonst None."""
    if text is None:
        return None
    s = str(text).strip().replace("\u20ac", "").replace("$", "").strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
