"""dt-einstieg-Tests. Fixtures in tests/fixtures/dt-einstieg/:

TSLA-2026-10-19-5m.json  TSLAs 5-Minuten-Kerzen vom 19.10.2026, aus der TSLA-60d5m.json des Reels
                         (Yahoo-Chart-JSON v8, abgerufen 10:49:45 ET). Endet mit der laufenden
                         10:45-Kerze und Yahoos Live-Tick um 10:49:45. meta auf einen Tag gekürzt.
DEMO-1m-synthetic.json   SYNTHETISCHE 1-Minuten-Kerzen (keine Marktdaten): ein Docht über das
                         Range-Hoch, ein Schluss GENAU am Hoch, eine Null-Kerze, ein Live-Tick.
SAP.DE-5d5m-2026-10-28.json  echter v8-Chart SAP.DE, range=5d, interval=5m, aus
                         tests/fixtures/dt-scanner/dax-v8-5d5m-2026-10-28.json.gz (abgerufen Mi 28.10.2026 ca. 10:12 Uhr):
                         22., 23., 26., 27.10. komplett, 28.10. bis zur 9:55-Kerze, Live-Tick 9:57:36.
BMW.DE-5d5m-2026-10-28.json  dasselbe für BMW.DE (am 27.10. kein Ausbruch über das Range-Hoch).
"""

import copy
import datetime
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, SKILLS

entry = load("dt-einstieg", "entry")

EDIR = os.path.join(FIX, "dt-einstieg")
TSLA = os.path.join(EDIR, "TSLA-2026-10-19-5m.json")
DEMO = os.path.join(EDIR, "DEMO-1m-synthetic.json")
SAP = os.path.join(EDIR, "SAP.DE-5d5m-2026-10-28.json")
BMW = os.path.join(EDIR, "BMW.DE-5d5m-2026-10-28.json")
OPEN_TS = 1792416600       # 2026-10-19 09:30 EDT
XOPEN_TS = 1793088000      # 2026-10-27 09:00 MEZ (08:00 UTC)
DT = datetime.datetime

SAFETY = """## Sicherheit

- Bildung und Werkzeug, keine Anlageberatung. Eine FREIGABE ist eine Regelprüfung, keine Empfehlung.
- Paper Trading ist Standard (`"paper": true`). Live zu gehen ist deine eigene Entscheidung, in deiner eigenen Config.
- Nichts in diesem Paket platziert eine Order außer dt-broker, und nur wenn alles drei gilt: dt-risiko hat
  genau diese Order heute freigegeben, du hast im Chat ausdrücklich „ja“ zu genau dieser einen Order geschrieben,
  und du hast auf Claudes eigener Karte „Allow once“ geklickt, weil das Order-Tool auf „Needs approval“ steht
  (Customize > Connectors > Tool-Berechtigungen). Ein Order-Tool nie auf „Always allow“ stellen.
  Im Modus `"broker": "manuell"` tippst du die Order selbst in deiner Broker-App ein.
- Keine Optionen, kein Margin, keine Leerverkäufe, kein Hebel, außer die Config erlaubt es und du bestätigst es.
- Broker-Schlüssel liegen in Umgebungsvariablen oder in der Claude-Desktop-Config, nie im Chat.
"""


def ny(text):
    with entry.markt.using("us"):
        return entry.parse_now(text)


def de(text):
    with entry.markt.using("xetra"):
        return entry.parse_now(text)


def doc(path=TSLA):
    with open(path) as fh:
        return json.load(fh)


def chart(d=None, sym="TSLA"):
    return entry.parse_chart(json.dumps(d if d is not None else doc()), sym)


def at(text, d=None, **kw):
    return entry.evaluate(chart(d), ny(text), **kw)


def xat(text, path=SAP, d=None, **kw):
    sym = os.path.basename(path).split("-")[0]
    return entry.evaluate(chart(d if d is not None else doc(path), sym), de(text), **kw)


def shift_to(d, day, edt):
    """Dieselbe Sitzung an einem anderen Tag: 9:30 New York ist 13:30 UTC in EDT, 14:30 in EST."""
    d = copy.deepcopy(d)
    r = d["chart"]["result"][0]
    new_open = int((DT.combine(day, datetime.time(13 if edt else 14, 30)) - DT(1970, 1, 1)).total_seconds())
    delta = new_open - OPEN_TS
    r["timestamp"] = [t + delta for t in r["timestamp"]]
    r["meta"]["regularMarketTime"] += delta
    r["meta"]["timezone"] = "EDT" if edt else "EST"
    return d


def only_day(d, first_ts, last_ts=None, data_time=None):
    """Nur die Kerzen von first_ts bis last_ts (Start), optional mit einem neuen regularMarketTime."""
    d = copy.deepcopy(d)
    r = d["chart"]["result"][0]
    keep = [i for i, t in enumerate(r["timestamp"]) if t >= first_ts and (last_ts is None or t <= last_ts)]
    r["timestamp"] = [r["timestamp"][i] for i in keep]
    q = r["indicators"]["quote"][0]
    for k in q:
        q[k] = [q[k][i] for i in keep]
    if data_time is not None:
        r["meta"]["regularMarketTime"] = data_time
    return d


def no_breakout(d=None):
    """Jede Kerze nach der Range bleibt unter dem Hoch von 362.18."""
    d = copy.deepcopy(d if d is not None else doc())
    q = d["chart"]["result"][0]["indicators"]["quote"][0]
    for i in range(3, len(q["close"])):
        q["close"][i] = min(q["close"][i], 362.00)
        q["high"][i] = min(q["high"][i], 362.10)
        q["open"][i] = min(q["open"][i], 362.00)
    return d


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = entry.main(argv)
    return code, out.getvalue(), err.getvalue()


class TheReel(unittest.TestCase):
    def test_triggers_at_1015_on_the_1010_bar(self):
        r = at("2026-10-19 10:15")
        self.assertEqual(r["status"], "triggered")
        self.assertEqual(r["market"], "us")
        self.assertEqual(r["opening_range"]["high"], 362.18)
        self.assertEqual(r["opening_range"]["low"], 354.47)
        self.assertEqual(r["opening_range"]["bars"], 3)
        t = r["trigger"]
        self.assertEqual(t["time"], "10:15 AM")
        self.assertEqual(t["bar_start"], "10:10")
        self.assertEqual(t["bar_index"], 8)
        self.assertEqual(t["price"], 364.18)
        self.assertEqual(t["close"], 364.1759948730469)
        self.assertEqual(t["pct_over"], 0.55)
        self.assertEqual(r["level"], 362.18)
        self.assertEqual(r["prev_close"], 354.72)
        text = "\n".join(entry.describe(r))
        self.assertIn("AUSGELÖST 10:15 ET (16:15 Uhr) zu 364,18 $: die 10:10-Kerze (Kerze 8) hat über dem "
                      "Range-Hoch 362,18 $ geschlossen (+0,55 %).", text)

    def test_at_1012_the_1010_bar_is_still_forming(self):
        r = at("2026-10-19 10:12")
        self.assertEqual(r["status"], "waiting")
        self.assertIsNone(r["trigger"])
        self.assertEqual(r["last"]["bar_start"], "10:05")
        self.assertEqual(r["last"]["close"], 361.68)
        self.assertEqual(r["forming"]["bar_start"], "10:10")
        self.assertIn("0,50 $ unter dem Range-Hoch 362,18 $", r["reason"])
        self.assertEqual(at("2026-10-19 10:14:59")["status"], "waiting")
        text = "\n".join(entry.describe(r))
        self.assertIn("WARTEN  letzter Schluss 361,68 $ (10:05-Kerze)", text)

    def test_before_the_open_and_while_the_range_forms(self):
        r = at("2026-10-19 09:20")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "pre-open"))
        self.assertIn("NYSE öffnet um 9:30 ET", r["reason"])
        r = at("2026-10-19 09:44")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "forming"))
        self.assertEqual(r["opening_range"]["bars"], 2)
        self.assertFalse(r["opening_range"]["complete"])
        r = at("2026-10-19 09:46")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "open"))
        self.assertEqual(r["opening_range"]["bars"], 3)

    def test_the_live_tick_and_the_in_progress_bar_are_dropped(self):
        c = chart()
        self.assertEqual(c["bars"][-1]["t"], 1792421385)          # 10:49:45 steht in der Datei
        r = entry.evaluate(c, entry.utc_of(c["data_time"]))     # zur Zeit der Datei gelesen
        self.assertEqual(r["now"], "2026-10-19 10:49:45")
        self.assertEqual(r["_bars"][-1]["slot"], 14)               # die 10:40-Kerze
        self.assertEqual(r["forming"]["bar_start"], "10:45")
        self.assertEqual(r["bars_closed"], 15)
        # 10:50: nach der Uhr geschlossen, aber Yahoos letzter Kurs (10:49:45) liegt vor dem Schluss
        r = at("2026-10-19 10:50")
        self.assertEqual(r["_bars"][-1]["slot"], 14)
        self.assertIn("Yahoos letzter Kurs ist von 10:49:45", r["lag_note"])
        # eine Minute später ohne neueren Kurs zählt sie; der Tick um 10:49:45 wird nie eine Kerze
        r = at("2026-10-19 10:51")
        self.assertEqual(r["_bars"][-1]["slot"], 15)
        self.assertEqual(r["bars_closed"], 16)
        self.assertTrue(all(b["t"] % 300 == 0 for b in r["_bars"]))

    def test_after_the_close_it_stays_triggered_and_says_it_is_late(self):
        r = at("2026-10-19 16:05")
        self.assertEqual((r["status"], r["phase"]), ("triggered", "after-close"))
        self.assertEqual(r["trigger"]["time"], "10:15 AM")
        text = "\n".join(entry.describe(r))
        self.assertIn("Das war vor 350 Minuten", text)
        self.assertNotIn("Jetzt ist der Moment", text)


class Rules(unittest.TestCase):
    def test_volume_confirmation_moves_the_trigger(self):
        r = at("2026-10-19 10:49", min_volume_x=1)
        self.assertEqual(r["opening_range"]["avg_volume"], 1658945)
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_index"], t["price"]), ("10:35 AM", 12, 365.75))
        self.assertEqual(t["volume_x"], 7.98)
        r = at("2026-10-19 10:16", min_volume_x=1)
        self.assertEqual(r["status"], "waiting")
        self.assertIn("0,60-Fachen des Range-Volumens, unter deinem Minimum von 1,00", r["reason"])

    def test_level_setup(self):
        r = at("2026-10-19 10:30", setup="level", level=365.5)
        self.assertEqual(r["trigger"]["time"], "10:25 AM")
        self.assertEqual(r["trigger"]["bar_index"], 10)
        self.assertEqual(r["trigger"]["price"], 365.75)
        # ein Level unter der Eröffnung: der erste zulässige Schluss ist der der 9:40-Kerze, um 9:45 (no_entries_before)
        r = at("2026-10-19 10:30", setup="level", level=350)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:45 AM", 2))
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 10:30", setup="level")

    def test_no_breakout_waits_then_expires_at_the_cutoff(self):
        d = no_breakout()
        r = at("2026-10-19 10:49", d)
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(at("2026-10-19 15:29", d)["status"], "waiting")
        r = at("2026-10-19 15:30", d)
        self.assertEqual(r["status"], "expired")
        self.assertIn("bis 15:30 ET", r["reason"])
        self.assertEqual(at("2026-10-19 16:30", d)["phase"], "after-close")
        self.assertIn("ABGELAUFEN  kein Schluss über dem Range-Hoch 362,18 $", "\n".join(entry.describe(r)))

    def test_the_bar_closing_at_the_cutoff_still_counts_when_yahoo_lags(self):
        d = no_breakout()
        r0 = d["chart"]["result"][0]
        keep = [i for i, t in enumerate(r0["timestamp"]) if t <= OPEN_TS + 14 * 300]   # live: bis zur 10:40-Kerze
        r0["timestamp"] = [r0["timestamp"][i] for i in keep]
        q = r0["indicators"]["quote"][0]
        for k in q:
            q[k] = [q[k][i] for i in keep]
        r0["meta"]["regularMarketTime"] = OPEN_TS + 74 * 60 + 40                       # letzter Kurs 10:44:40
        cfg = {"no_entries_before": "09:45", "no_entries_after": "10:45"}
        r = at("2026-10-19 10:45:10", d, cfg=cfg)                           # die 10:40-Kerze nur nach der Uhr zu
        self.assertEqual(r["status"], "waiting")
        self.assertIn("Yahoos letzter Kurs ist von 10:44:40", r["lag_note"])
        self.assertEqual(at("2026-10-19 10:46", d, cfg=cfg)["status"], "expired")

    def test_config_cutoff(self):
        cfg = {"no_entries_before": "09:45", "no_entries_after": "10:10"}
        r = at("2026-10-19 10:15", cfg=cfg)
        self.assertEqual(r["status"], "expired")
        cfg = {"no_entries_before": "10:20", "no_entries_after": "15:30"}
        r = at("2026-10-19 10:30", cfg=cfg)
        self.assertEqual(r["trigger"]["time"], "10:20 AM")       # die 10:15-Kerze, die erste mit Schluss ab 10:20
        # je Markt unter "zeiten": US-Zeiten gelten nicht für XETRA und umgekehrt
        cfg = {"zeiten": {"us": {"no_entries_after": "10:10"}, "xetra": {"no_entries_after": "10:00"}}}
        self.assertEqual(at("2026-10-19 10:15", cfg=cfg)["status"], "expired")
        self.assertEqual(xat("2026-10-27 10:55", cfg=cfg)["status"], "expired")
        self.assertEqual(xat("2026-10-27 10:55", cfg={"zeiten": {"us": {"no_entries_after": "10:10"}}})["status"],
                         "triggered")

    def test_bad_inputs(self):
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 10:15", or_minutes=7)
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 10:15", interval="15m")
        with self.assertRaises(entry.EntryError):
            entry.parse_now("tomorrow")
        with self.assertRaises(entry.EntryError):
            entry.parse_hhmm("25:00", "x")
        self.assertEqual(ny("2026-10-19 10:15"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(ny("2026-10-19T14:15:00Z"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(ny("2026-10-19 10:15 ET"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(de("2026-10-27 10:55 Uhr"), DT(2026, 10, 27, 9, 55))

    def test_or_minutes_30(self):
        r = at("2026-10-19 10:49", or_minutes=30)
        self.assertEqual(r["opening_range"]["bars"], 6)
        self.assertEqual(r["opening_range"]["high"], 362.92)
        self.assertEqual(r["trigger"]["time"], "10:15 AM")


class OneMinute(unittest.TestCase):
    def c(self):
        return entry.parse_chart(json.dumps(doc(DEMO)), "DEMO")

    def test_wick_and_close_at_the_high_do_not_trigger(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m")
        self.assertEqual(r["now"], "2026-10-19 10:06:30")
        self.assertEqual(r["opening_range"], {"high": 100.5, "low": 99.0, "minutes": 15, "bars": 15, "of": 15,
                                              "complete": True, "avg_volume": 10667})
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_start"], t["bar_index"], t["price"]), ("9:59 AM", "09:58", 28, 100.62))
        r = entry.evaluate(c, ny("2026-10-19 09:58:59"), interval="1m")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["forming"]["bar_start"], "09:58")
        self.assertEqual(r["last"]["close"], 100.5)             # die 9:57-Kerze schloss GENAU am Hoch

    def test_null_bar_tick_and_volume(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m", min_volume_x=2)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("10:02 AM", 31))
        slots = [b["slot"] for b in r["_bars"]]
        self.assertNotIn(19, slots)                               # 9:49 kam als Nullen
        self.assertEqual(slots[-1], 35)                           # 10:06 läuft noch, Tick 10:06:30 fällt weg
        self.assertEqual(r["forming"]["bar_start"], "10:06")

    def test_the_file_and_the_interval_must_agree(self):
        code, _, err = run(["check", "DEMO", "--offline", DEMO])
        self.assertEqual(code, 1)
        self.assertIn("hat 1m-Kerzen, nicht 5m", err)


class Calendar(unittest.TestCase):
    def test_dst_both_sides(self):
        for day, edt in ((datetime.date(2026, 12, 7), False), (datetime.date(2026, 11, 2), False),
                         (datetime.date(2026, 10, 30), True), (datetime.date(2026, 3, 9), True)):
            d = shift_to(doc(), day, edt)
            r = entry.evaluate(chart(d), ny("%s 10:15" % day))
            self.assertEqual(r["status"], "triggered", day)
            self.assertEqual(r["trigger"]["time"], "10:15 AM", day)
            self.assertEqual(r["trigger"]["bar_index"], 8, day)
            self.assertEqual(entry.evaluate(chart(d), ny("%s 10:12" % day))["status"], "waiting", day)
        # 7.12. um 10:15 New York ist 15:15 UTC
        self.assertEqual(ny("2026-12-07 10:15"), DT(2026, 12, 7, 15, 15))

    def test_half_day_moves_the_cutoff_up(self):
        d = shift_to(no_breakout(), datetime.date(2026, 11, 27), False)
        r = entry.evaluate(chart(d), ny("2026-11-27 12:29"))
        self.assertEqual(r["status"], "waiting")
        self.assertEqual((r["closes"], r["no_entries_after"]), ("13:00", "12:30"))
        r = entry.evaluate(chart(d), ny("2026-11-27 12:30"))
        self.assertEqual(r["status"], "expired")
        self.assertIn("verkürzter Handel bis 13:00 ET", r["reason"])
        r = entry.evaluate(chart(shift_to(doc(), datetime.date(2026, 11, 27), False)), ny("2026-11-27 10:15"))
        self.assertEqual(r["trigger"]["time"], "10:15 AM")
        self.assertIn("Heute verkürzter Handel bis 13:00 ET", "\n".join(entry.describe(r)))
        # eine Grenze, die schon vor dem verkürzten Schluss liegt, bleibt
        cfg = {"no_entries_before": "09:45", "no_entries_after": "12:00"}
        self.assertEqual(entry.evaluate(chart(d), ny("2026-11-27 11:00"), cfg=cfg)["no_entries_after"], "12:00")

    def test_weekend_holiday_and_empty_data(self):
        r = at("2026-10-17 10:30")
        self.assertEqual((r["status"], r["phase"]), ("no-data", "closed"))
        self.assertEqual(r["next_open"], "2026-10-19 09:30")
        self.assertIn("Wochenende", r["reason"])
        r = at("2026-11-26 10:30")
        self.assertIn("Thanksgiving", r["reason"])
        empty = copy.deepcopy(doc())
        res = empty["chart"]["result"][0]
        del res["timestamp"]
        res["indicators"] = {"quote": [{}]}
        r = at("2026-10-19 10:15", empty)
        self.assertEqual((r["status"], r["phase"]), ("no-data", "open"))
        r = at("2026-10-20 10:15")                                # Yahoo hat nur gestrige Kerzen geschickt
        self.assertEqual(r["status"], "no-data")
        self.assertFalse(at("2028-03-01 10:30")["calendar_known"])

    def test_yahoo_errors(self):
        bad = json.dumps({"chart": {"result": None, "error": {"code": "Not Found",
                                                              "description": "No data found, symbol may be delisted"}}})
        with self.assertRaises(entry.EntryError) as cm:
            entry.parse_chart(bad, "ZZZZ")
        self.assertIn("No data found", str(cm.exception))
        with self.assertRaises(entry.EntryError):
            entry.parse_chart("<html>", "TSLA")


class Xetra(unittest.TestCase):
    """SAP.DE am Di 27.10.2026 (MEZ, nach der Umstellung): Range 9:00 bis 9:15 Uhr, Ausbruch 10:55 Uhr."""

    def test_breakout_on_27_10(self):
        r = xat("2026-10-27 10:55")
        self.assertEqual((r["market"], r["currency"], r["status"]), ("xetra", "EUR", "triggered"))
        self.assertEqual((r["opens"], r["closes"]), ("09:00", "17:30"))
        self.assertEqual((r["no_entries_before"], r["no_entries_after"]), ("09:15", "17:00"))
        self.assertEqual(r["opening_range"], {"high": 214.75, "low": 211.7, "minutes": 15, "bars": 3, "of": 3,
                                              "complete": True, "avg_volume": 7738})
        t = r["trigger"]
        self.assertEqual((t["time"], t["close_time"], t["bar_start"], t["bar_index"], t["price"], t["pct_over"]),
                         ("10:55 AM", "10:55", "10:50", 22, 214.9, 0.07))
        self.assertEqual(r["level"], 214.75)
        text = "\n".join(entry.describe(r))
        self.assertIn("SAP.DE  Di 27.10.2026 10:55 Uhr  Opening-Range-Breakout (15-Minuten-Range)", text)
        self.assertIn("Opening Range 9:00 bis 9:15 Uhr: Hoch 214,75 €, Tief 211,70 € (3 von 3 Kerzen).", text)
        self.assertIn("AUSGELÖST 10:55 Uhr zu 214,90 €: die 10:50-Kerze (Kerze 22) hat über dem Range-Hoch "
                      "214,75 € geschlossen (+0,07 %).", text)
        self.assertIn("Rückblick auf gespeicherte Kerzen", text)
        self.assertIn("ca. 15 Minuten verzögert", text)

    def test_waiting_before_the_trigger_bar_closes(self):
        r = xat("2026-10-27 10:54")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual((r["last"]["bar_start"], r["last"]["close"]), ("10:45", 214.7))
        self.assertEqual(r["forming"]["bar_start"], "10:50")
        self.assertIn("0,05 € unter dem Range-Hoch 214,75 € (-0,02 %)", r["reason"])
        text = "\n".join(entry.describe(r))
        self.assertIn("WARTEN  letzter Schluss 214,70 € (10:45-Kerze)", text)
        self.assertIn("Die 10:50-Kerze läuft noch (bisher 214,90 €, schließt 10:55 Uhr)", text)
        # die 10:40-Kerze hat das Hoch mit dem Docht berührt (214,75) und darunter geschlossen: kein Auslöser
        r = xat("2026-10-27 10:45")
        self.assertEqual((r["status"], r["last"]["bar_start"], r["last"]["close"]), ("waiting", "10:40", 214.65))

    def test_before_9_20(self):
        r = xat("2026-10-27 08:59")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "pre-open"))
        self.assertEqual(r["reason"], "XETRA öffnet um 9:00 Uhr und die 15-Minuten-Range steht um 9:15 Uhr")
        r = xat("2026-10-27 09:10")
        self.assertEqual((r["phase"], r["opening_range"]["bars"]), ("forming", 2))
        r = xat("2026-10-27 09:15")
        self.assertEqual((r["status"], r["phase"], r["opening_range"]["bars"]), ("waiting", "open", 3))
        r = xat("2026-10-27 09:19")
        self.assertEqual((r["status"], r["forming"]["bar_start"]), ("waiting", "09:15"))
        r = xat("2026-10-27 09:20")
        self.assertEqual((r["status"], r["last"]["bar_start"]), ("waiting", "09:15"))
        # Level-Setup: die 9:00- und 9:05-Kerze schließen über 212, aber vor 9:15 Uhr gibt es keine Einstiege
        r = xat("2026-10-27 09:12", setup="level", level=212)
        self.assertEqual(r["status"], "waiting")
        self.assertIn("vor 9:15 Uhr gibt es keine Einstiege", r["reason"])
        r = xat("2026-10-27 09:20", setup="level", level=212)
        self.assertEqual((r["trigger"]["close_time"], r["trigger"]["bar_index"], r["trigger"]["price"]),
                         ("09:20", 3, 212.95))

    def test_expired_after_17_00(self):
        r = xat("2026-10-27 16:59", BMW)
        self.assertEqual((r["status"], r["opening_range"]["high"], r["opening_range"]["low"]), ("waiting", 57.5, 57.04))
        r = xat("2026-10-27 17:00", BMW)
        self.assertEqual((r["status"], r["phase"]), ("expired", "after-cutoff"))
        self.assertEqual(r["reason"], "kein Schluss über dem Range-Hoch 57,50 € bis 17:00 Uhr, dem letzten Zeitpunkt "
                                      "für einen neuen Einstieg")
        text = "\n".join(entry.describe(r))
        self.assertIn("ABGELAUFEN  kein Schluss", text)
        self.assertIn("Es wurde nichts platziert.", text)
        self.assertEqual(xat("2026-10-27 17:40", BMW)["phase"], "after-close")
        # SAP hatte um 10:55 ausgelöst und bleibt nach 17:00 Uhr ausgelöst, aber spät
        r = xat("2026-10-27 17:10")
        self.assertEqual((r["status"], r["minutes_since"]), ("triggered", 375))
        self.assertIn("Das war vor 375 Minuten", "\n".join(entry.describe(r)))

    def test_holidays_and_short_day(self):
        r = xat("2026-12-24 10:00")
        self.assertEqual((r["status"], r["phase"], r["next_open"]), ("no-data", "closed", "2026-12-28 09:00"))
        self.assertEqual(r["reason"], "XETRA handelt heute nicht (Börsenfeiertag XETRA: Heiligabend)")
        self.assertIn("Nächste Eröffnung: Mo 28.12.2026 9:00 Uhr.", "\n".join(entry.describe(r)))
        self.assertIn("Karfreitag", xat("2026-04-03 10:00")["reason"])
        self.assertEqual(xat("2026-04-02 10:00")["phase"], "open")         # Gründonnerstag wird gehandelt
        self.assertEqual(xat("2026-04-03 10:00")["next_open"], "2026-04-07 09:00")
        r = xat("2026-06-04 10:00")                                        # Fronleichnam: XETRA handelt
        self.assertEqual((r["status"], r["phase"]), ("no-data", "open"))
        # verkürzter Tag 30.12.2026 (Schluss 14:00 Uhr): BMW vom 27.10. auf den 30.12. verschoben (beides MEZ)
        d = doc(BMW)
        res = d["chart"]["result"][0]
        delta = (datetime.date(2026, 12, 30) - datetime.date(2026, 10, 27)).days * 86400
        res["timestamp"] = [t + delta for t in res["timestamp"]]
        res["meta"]["regularMarketTime"] += delta
        r = xat("2026-12-30 13:29", d=d, path=BMW)
        self.assertEqual((r["status"], r["closes"], r["no_entries_after"]), ("waiting", "14:00", "13:30"))
        r = xat("2026-12-30 13:30", d=d, path=BMW)
        self.assertEqual(r["status"], "expired")
        self.assertIn("heute verkürzter Handel bis 14:00 Uhr", r["reason"])
        self.assertIn("Heute verkürzter Handel bis 14:00 Uhr (Jahresschlussbörse", "\n".join(entry.describe(r)))

    def test_data_age_on_28_10_at_10_12(self):
        r = xat("2026-10-28 10:12")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["data_time"], "2026-10-28 09:57:36")
        self.assertEqual(r["data_age"], {"last_bar": "09:55", "minutes": 17, "last_trade": "09:57:36",
                                         "last_trade_minutes": 14, "replay": False, "delay_minutes": 15})
        # die 9:55-Kerze ist nach der Uhr seit 10:00 Uhr zu, Yahoo hat aber erst Kurse bis 9:57:36: sie zählt noch nicht
        self.assertEqual(r["last"]["bar_start"], "09:50")
        self.assertEqual(r["forming"]["bar_start"], "09:55")
        self.assertIn("ca. 15 Minuten verzögert", r["lag_note"])
        text = "\n".join(entry.describe(r))
        self.assertIn("Datenstand: letzte Kerze 9:55 Uhr, 17 Minuten alt; letzter Kurs von 9:57 Uhr (14 Minuten alt).",
                      text)
        self.assertIn("das ist kein Echtzeitkurs", text)
        # erst nach Verzögerung plus einer Minute zählt sie ohne neueren Kurs
        self.assertEqual(xat("2026-10-28 10:15:59")["last"]["bar_start"], "09:50")
        self.assertEqual(xat("2026-10-28 10:16")["last"]["bar_start"], "09:55")

    def test_delayed_range_and_late_trigger(self):
        # live um 9:16 Uhr: Yahoo hat Kurse bis 9:01, die Range kann noch nicht stehen
        d = only_day(doc(SAP), XOPEN_TS, XOPEN_TS, data_time=XOPEN_TS + 60)
        r = xat("2026-10-27 09:16", d=d)
        self.assertEqual((r["status"], r["phase"]), ("waiting", "forming"))
        self.assertIn("Yahoo liefert die letzte noch nach (ca. 15 Minuten verzögert)", r["reason"])
        # live um 11:10:30 Uhr: Yahoo hat Kurse bis 10:55:30, die 10:50-Kerze ist geliefert
        d = only_day(doc(SAP), XOPEN_TS, XOPEN_TS + 22 * 300, data_time=XOPEN_TS + 23 * 300 + 30)
        r = xat("2026-10-27 11:10:30", d=d)
        self.assertEqual((r["status"], r["trigger"]["close_time"], r["minutes_since"]), ("triggered", "10:55", 15))
        text = "\n".join(entry.describe(r))
        self.assertIn("Die Kerze ist 15 Minuten alt, weil Yahoo XETRA-Kurse ca. 15 Minuten verzögert liefert", text)
        self.assertNotIn("Jetzt ist der Moment", text)
        self.assertIn("Datenstand: letzte Kerze 10:50 Uhr, 20 Minuten alt", text)

    def test_cutoff_waits_for_delayed_bars(self):
        # live um 17:00 Uhr hat Yahoo erst Kerzen bis 16:45: noch nicht abgelaufen
        last = XOPEN_TS + 7 * 3600 + 40 * 60                    # 16:40-Kerze
        d = only_day(doc(BMW), XOPEN_TS, last, data_time=last + 300)
        r = xat("2026-10-27 17:00", BMW, d=d)
        self.assertEqual((r["status"], r["phase"]), ("waiting", "after-cutoff"))
        self.assertIn("nach 17:00 Uhr keine neuen Einstiege", r["reason"])
        self.assertEqual(xat("2026-10-27 17:16", BMW, d=d)["status"], "expired")

    def test_winter_time_after_the_switch(self):
        # Berlin: MEZ ab So 25.10.2026, 9:00 Uhr ist dann 08:00 UTC, davor 07:00 UTC
        self.assertEqual(de("2026-10-27 09:00"), DT(2026, 10, 27, 8, 0))
        self.assertEqual(de("2026-10-23 09:00"), DT(2026, 10, 23, 7, 0))
        r = xat("2026-10-27 09:20")
        self.assertEqual(entry.utc_of(r["_bars"][0]["t"]), DT(2026, 10, 27, 8, 0))
        r = xat("2026-10-23 09:20")
        self.assertEqual(entry.utc_of(r["_bars"][0]["t"]), DT(2026, 10, 23, 7, 0))
        self.assertEqual((r["opening_range"]["high"], r["opening_range"]["low"]), (213.6, 210.05))
        self.assertEqual(xat("2026-10-26 17:05")["trigger"]["close_time"], "09:45")
        self.assertEqual(xat("2026-10-23 17:05")["trigger"]["close_time"], "14:40")
        # in dieser Woche liegen Berlin und New York 5 Stunden auseinander
        r = entry.evaluate(chart(shift_to(doc(), datetime.date(2026, 10, 27), True)), ny("2026-10-27 10:15"))
        self.assertIn("10:15 ET (15:15 Uhr)", "\n".join(entry.describe(r)))


class Network(unittest.TestCase):
    """Yahoo wird nie aufgerufen: _open_url und _sleep sind Attrappen."""

    def setUp(self):
        self.calls, self.sleeps = [], []
        self._open, self._sleep = entry._open_url, entry._sleep
        entry._sleep = lambda s: self.sleeps.append(s)
        with open(TSLA) as fh:
            self.body = fh.read()

    def tearDown(self):
        entry._open_url, entry._sleep = self._open, self._sleep

    def answers(self, *codes):
        seq = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url)
            code = seq.pop(0)
            if code == 200:
                return self.body
            raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b'{"chart":{"result":null,'
                                                                           b'"error":{"description":"No data found"}}}'))
        entry._open_url = fake

    def test_url_and_429_retry_once_after_a_pause(self):
        self.answers(429, 200)
        c = entry.get_chart("TSLA", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertEqual(len(c["bars"]), 17)
        self.assertEqual(self.calls, ["https://query2.finance.yahoo.com/v8/finance/chart/TSLA?range=1d&interval=5m"] * 2)
        self.assertEqual(self.sleeps, [entry.BACKOFF])

    def test_429_twice_falls_back_to_query1(self):
        self.answers(429, 429, 200)
        entry.get_chart("TSLA", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertEqual([u.split("/")[2] for u in self.calls],
                         ["query2.finance.yahoo.com", "query2.finance.yahoo.com", "query1.finance.yahoo.com"])

    def test_5xx_falls_back_without_waiting(self):
        self.answers(503, 200)
        entry.get_chart("TSLA", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertEqual(self.sleeps, [])
        self.assertIn("query1", self.calls[1])

    def test_still_busy_is_one_plain_error(self):
        self.answers(429, 429, 429, 429)
        code, out, err = run(["check", "TSLA", "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 1)
        self.assertIn("HTTP 429", err)
        self.assertIn("Yahoo antwortet nicht", err)
        self.assertNotIn("Traceback", err)

    def test_unknown_ticker_404(self):
        self.answers(404)
        with self.assertRaises(entry.EntryError) as cm:
            entry.get_chart("ZZZZ", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertIn("No data found", str(cm.exception))

    def test_ranges_for_past_sessions(self):
        today = datetime.date(2026, 10, 20)
        self.assertEqual(entry.chart_range(today, today, "5m"), "1d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 10, 19), today, "5m"), "5d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 10, 1), today, "5m"), "1mo")
        self.assertEqual(entry.chart_range(datetime.date(2026, 8, 31), today, "5m"), "60d")
        with self.assertRaises(entry.EntryError):
            entry.chart_range(datetime.date(2026, 10, 1), today, "1m")
        self.assertIn("/chart/BRK-B?", entry.chart_path("brk.b", "1d", "5m"))
        self.assertIn("/chart/SAP.DE?", entry.chart_path("sap.de", "1d", "5m"))


def live_provider(d, lag_until=None, calls=None, sym="TSLA"):
    """Kerzen so, wie Yahoo sie zu `now` liefert: geschlossene Kerzen final, die laufende Kerze
    mit einer Spitze auf 363.00 (über dem Hoch, dann schließt sie darunter), plus ein Live-Tick.
    lag_until: vor dieser UTC-Zeit hängt Yahoos letzter Kurs 30 Sekunden hinterher."""
    base = chart(d, sym)

    def provider(now):
        if calls is not None:
            calls.append(now)
        nts = entry.ts_of(now)
        lagging = lag_until is not None and now < lag_until
        data_ts = nts - 30 if lagging else nts
        bars = []
        for b in base["bars"]:
            if b["t"] % 300 or b["t"] > data_ts:
                continue
            b = dict(b)
            if b["t"] + 300 > data_ts:
                b["c"], b["h"] = 363.00, max(b["h"], 363.00)
            bars.append(b)
        if data_ts % 300:
            bars.append({"t": data_ts, "o": 363.0, "h": 363.0, "l": 363.0, "c": 363.0, "v": 0})
        return {"symbol": "TSLA", "meta": {}, "bars": bars, "prev_close": 354.72, "data_time": data_ts}
    return provider


def delayed_provider(path, delay=900, calls=None):
    """XETRA live: Yahoo liefert die Kerzen `delay` Sekunden später; die laufende Kerze zeigt den Stand bis dahin."""
    sym = os.path.basename(path).split("-")[0]
    base = chart(doc(path), sym)

    def provider(now):
        if calls is not None:
            calls.append(now)
        data_ts = entry.ts_of(now) - delay
        bars = [dict(b) for b in base["bars"] if b["t"] % 300 == 0 and b["t"] <= data_ts]
        return {"symbol": sym, "meta": {}, "bars": bars, "prev_close": None, "data_time": data_ts}
    return provider


class Watch(unittest.TestCase):
    OPTS = {"setup": "orb", "or_minutes": 15, "interval": "5m", "level": None, "min_volume_x": None, "cfg": None}

    def loop(self, provider, start, **kw):
        clock = entry.SimClock(ny(start))
        lines, fired = [], []
        code, res = entry.watch_loop(provider, clock.now, clock.sleep, lines.append, dict(self.OPTS),
                                     on_trigger=lambda r, now: fired.append((r, now)), **kw)
        return code, res, lines, fired, clock

    def test_fires_on_the_first_closed_bar_not_the_spike_in_progress(self):
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), calls=calls), "2026-10-19 10:07", every=60)
        self.assertEqual(code, 0)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][0]["trigger"]["time"], "10:15 AM")
        self.assertEqual(fired[0][0]["trigger"]["price"], 364.18)
        # um 10:07 (10:05-Kerze läuft mit Spitze auf 363) und um 10:10:02 (die Kerze schloss bei 361,68)
        self.assertEqual([entry.to_eastern(c).strftime("%H:%M:%S") for c in calls], ["10:07:00", "10:10:02", "10:15:02"])
        text = "\n".join(lines)
        self.assertIn("10:05-Kerze  Schluss 361,68 $  0,50 $ unter 362,18 $", text)
        self.assertIn("10:10-Kerze  Schluss 364,18 $  AUSGELÖST", text)
        self.assertEqual(text.count("AUSGELÖST"), 1)

    def test_waits_for_yahoo_to_catch_up(self):
        lag = ny("2026-10-19 10:15:30")
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), lag_until=lag, calls=calls),
                                                   "2026-10-19 10:12", every=30)
        self.assertEqual(code, 0)
        times = [entry.to_eastern(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times, ["10:12:00", "10:15:02", "10:15:32"])   # 10:15:02: Yahoo erst bei 10:14:32
        self.assertEqual(fired[0][0]["trigger"]["time"], "10:15 AM")

    def test_from_before_the_open_prints_the_range_bar_by_bar(self):
        code, res, lines, fired, clock = self.loop(live_provider(doc()), "2026-10-19 09:00", every=30)
        self.assertEqual(code, 0)
        text = "\n".join(lines)
        self.assertIn("noch nicht offen", lines[0])
        self.assertIn(" 9:40-Kerze  Schluss 360,39 $  Opening Range steht: Hoch 362,18 $, Tief 354,47 $", text)
        self.assertEqual(sum(1 for x in lines if "-Kerze  Schluss " in x), 9)    # 9:30 ... 10:10, je eine Zeile

    def test_a_computer_that_dozes_off_catches_up_when_it_wakes(self):
        class Dozing(entry.SimClock):
            naps = 0

            def sleep(self, seconds):
                entry.SimClock.sleep(self, seconds)
                self.naps += 1
                if self.naps == 3:                      # der Laptop schläft mitten im Warten 17 Minuten
                    self.t += datetime.timedelta(minutes=17)
        clock = Dozing(ny("2026-10-19 09:46"))
        calls, lines = [], []
        code, res = entry.watch_loop(live_provider(doc(), calls=calls), clock.now, clock.sleep, lines.append,
                                     dict(self.OPTS), every=30)
        self.assertEqual(code, 0)
        times = [entry.to_eastern(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times[:2], ["09:46:00", "10:04:30"])   # gleich nach dem Aufwachen, nicht erst später
        text = "\n".join(lines)
        for start in (" 9:45", " 9:50", " 9:55", "10:00"):
            self.assertIn(start + "-Kerze  Schluss", text)        # die verschlafenen Kerzen, je eine Zeile
        self.assertEqual(res["trigger"]["time"], "10:15 AM")

    def test_expires_and_until(self):
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-10-19 15:00", every=300)
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "expired")
        self.assertEqual(fired, [])
        self.assertEqual(entry.to_eastern(clock.now()).strftime("%H:%M"), "15:30")
        self.assertTrue(lines[-1].startswith("ABGELAUFEN  "))
        until = DT(2026, 10, 19, 11, 0)
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-10-19 10:30", every=300,
                                                   until=until)
        self.assertEqual(code, 1)
        self.assertIn("--until 11:00 ET", lines[-1])

    def test_closed_day_and_repeated_errors(self):
        code, _, lines, _, _ = self.loop(live_provider(doc()), "2026-10-17 10:00")
        self.assertEqual(code, 1)
        self.assertIn("Wochenende", lines[0])

        def broken(now):
            raise entry.EntryError("Yahoo antwortet nicht")
        code, _, lines, _, _ = self.loop(broken, "2026-10-19 10:00", every=30)
        self.assertEqual(code, 1)
        self.assertIn("Abbruch nach 5 Fehlversuchen", lines[-1])

    def test_xetra_live_waits_for_the_delay(self):
        calls, lines, fired = [], [], []
        clock = entry.SimClock(de("2026-10-27 08:55"))
        opts = dict(self.OPTS, market="xetra")
        code, res = entry.watch_loop(delayed_provider(SAP, calls=calls), clock.now, clock.sleep, lines.append, opts,
                                     every=30, lag=900, on_trigger=lambda r, now: fired.append(r))
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "8:55 Uhr  noch nicht offen: beobachte ab dem Schluss der ersten Kerze um 9:05 Uhr "
                                   "(bei Yahoo ca. 9:20 Uhr, 15 Minuten verzögert).")
        times = [entry.markt.to_berlin(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times[0], "09:20:02")
        self.assertEqual(times[-1], "11:10:02")                  # 10:55 Uhr Kerzenschluss plus 15 Minuten
        self.assertTrue(all(t.endswith(":02") for t in times))   # ein Abruf je Kerze, keine Dauerschleife
        self.assertEqual(fired[0]["trigger"]["close_time"], "10:55")
        text = "\n".join(lines)
        self.assertIn("10:50-Kerze  Schluss 214,90 €  AUSGELÖST: Schluss über 214,75 € (+0,07 %)", text)
        self.assertIn(" 9:10-Kerze  Schluss 211,90 €  Opening Range steht: Hoch 214,75 €, Tief 211,70 €", text)
        self.assertIn("weil Yahoo XETRA-Kurse ca. 15 Minuten verzögert liefert", text)
        self.assertEqual(entry.markt.current(), "us")


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def test_check_write_is_the_contract_shape(self):
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15", "--write"])
        self.assertEqual(code, 0)
        self.assertIn("AUSGELÖST 10:15 ET (16:15 Uhr) zu 364,18 $", text)
        self.assertIn("/dt-ausstieg", text)
        self.assertIn("keine Empfehlung. Keine Anlageberatung.", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            e = json.load(fh)
        want = {"created_by": "dt-einstieg", "symbol": "TSLA", "market": "us", "currency": "USD", "setup": "orb",
                "side": "buy", "date": "2026-10-19",
                "status": "triggered", "time": "10:15 AM", "bar_start": "10:10", "bar_index": 8, "price": 364.18,
                "level": 362.18, "interval": "5m", "opening_range": {"high": 362.18, "low": 354.47, "minutes": 15},
                "source": "yahoo", "checked_at": "2026-10-19T14:15:00Z"}
        for k, v in want.items():
            self.assertEqual(e[k], v, k)

    def test_check_xetra_from_the_symbol(self):
        code, text, _ = run(["check", "SAP.DE", "--offline", SAP, "--now", "2026-10-27 10:55", "--write"])
        self.assertEqual(code, 0)
        self.assertIn("AUSGELÖST 10:55 Uhr zu 214,90 €", text)
        self.assertIn("trader/entry.json geschrieben (Status AUSGELÖST).", text)
        with open(os.path.join("trader", "entry.json"), encoding="utf-8") as fh:
            e = json.load(fh)
        want = {"symbol": "SAP.DE", "market": "xetra", "currency": "EUR", "status": "triggered", "time": "10:55 AM",
                "bar_start": "10:50", "bar_index": 22, "price": 214.9, "level": 214.75,
                "opening_range": {"high": 214.75, "low": 211.7, "minutes": 15}, "delay_minutes": 15,
                "checked_at": "2026-10-27T09:55:00Z"}
        for k, v in want.items():
            self.assertEqual(e[k], v, k)
        self.assertEqual(entry.markt.current(), "us")             # main() setzt den Markt zurück
        code, text, _ = run(["check", "SAP.DE", "--offline", SAP, "--now", "2026-10-27 10:54", "--json"])
        self.assertEqual((code, json.loads(text)["status"]), (1, "waiting"))
        code, text, _ = run(["check", "SAP.DE", "--offline", SAP, "--now", "2026-10-27T09:55:00Z"])
        self.assertEqual(code, 0)

    def test_check_waiting_json_and_exit_codes(self):
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:12", "--json"])
        self.assertEqual(code, 1)
        r = json.loads(text)
        self.assertEqual(r["status"], "waiting")
        self.assertNotIn("_bars", r)
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:12", "--write", "e.json"])
        with open("e.json") as fh:
            self.assertEqual(json.load(fh)["status"], "waiting")
        self.assertIn("läuft noch", text)

    def test_offline_gz_folder_and_mismatch(self):
        os.mkdir("charts")
        with open(TSLA, "rb") as src, gzip.open(os.path.join("charts", "TSLA.json.gz"), "wb") as dst:
            dst.write(src.read())
        shutil.copy(SAP, os.path.join("charts", "SAP.DE.json"))
        code, text, _ = run(["check", "tsla", "--offline", "charts", "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 0)
        code, text, _ = run(["check", "sap.de", "--offline", "charts", "--now", "2026-10-27 10:55"])
        self.assertEqual(code, 0)
        code, _, err = run(["check", "NVDA", "--offline", TSLA])
        self.assertEqual(code, 1)
        self.assertIn("enthält TSLA, nicht NVDA", err)

    def test_longs_only_and_flag_errors(self):
        code, _, err = run(["check", "TSLA", "--offline", TSLA, "--side", "short"])
        self.assertEqual(code, 1)
        self.assertIn("nur Long", err)
        code, _, err = run(["check", "TSLA", "--offline", TSLA, "--level", "300"])
        self.assertIn("--level gehört zu --setup level", err)
        code, _, err = run(["check", "TSLA", "--offline", TSLA, "--setup", "level"])
        self.assertIn("braucht --level", err)
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:30",
                             "--setup", "level", "--level", "365,50"])
        self.assertEqual(code, 0)
        self.assertIn("AUSGELÖST 10:25 ET (16:25 Uhr) zu 365,75 $", text)

    def test_config_is_read(self):
        os.mkdir("trader")
        with open(os.path.join("trader", "config.json"), "w") as fh:
            json.dump({"no_entries_after": "10:10"}, fh)
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 1)
        self.assertIn("ABGELAUFEN", text)
        with open(os.path.join("trader", "config.json"), "w") as fh:
            fh.write("{nope")
        code, _, err = run(["check", "TSLA", "--offline", TSLA])
        self.assertIn("kein gültiges JSON", err)

    def test_watch_replays_the_file_and_writes_the_entry(self):
        code, text, _ = run(["watch", "TSLA", "--offline", TSLA, "--now", "2026-10-19 09:50", "--every", "30"])
        self.assertEqual(code, 0)
        self.assertIn("10:10-Kerze  Schluss 364,18 $  AUSGELÖST", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            self.assertEqual(json.load(fh)["bar_index"], 8)
        code, text, _ = run(["watch", "TSLA", "--offline", TSLA, "--now", "2026-10-19 09:50", "--until", "10:00",
                             "--out", "x.json"])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists("x.json"))
        code, text, _ = run(["watch", "SAP.DE", "--offline", SAP, "--now", "2026-10-27 10:30", "--out", "sap.json"])
        self.assertEqual(code, 0)
        self.assertIn("10:50-Kerze  Schluss 214,90 €  AUSGELÖST", text)
        with open("sap.json", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["market"], "xetra")

    def test_watchlist(self):
        os.mkdir("charts")
        shutil.copy(TSLA, os.path.join("charts", "TSLA.json"))
        shutil.copy(DEMO, os.path.join("charts", "DEMO.json"))
        os.mkdir("trader")
        with open(os.path.join("trader", "watchlist.json"), "w") as fh:
            json.dump({"created_by": "dt-scanner", "hits": [
                {"symbol": "TSLA", "setups": ["orb"], "or_high": 362.18, "or_low": 354.47},
                {"symbol": "ZZZZ", "setups": ["orb"]}, {"symbol": "DEMO", "setups": ["orb"]}]}, fh)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 0)
        rows = text.splitlines()
        self.assertTrue(rows[1].startswith("TSLA      AUSGELÖST   10:15 ET   364,18 $     362,18 $"), rows[1])
        self.assertIn("ZZZZ      Fehler: keine Offline-Datei", rows[2])
        self.assertIn("DEMO      Fehler: DEMO hat 1m-Kerzen", rows[3])
        self.assertIn("1 von 3 ausgelöst", text)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-10-19 10:12", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)[0]["result"]["status"], "waiting")
        code, _, err = run(["watchlist", "--watchlist", "missing.json"])
        self.assertIn("zuerst /dt-scanner", err)

    def test_watchlist_mixes_markets(self):
        os.mkdir("charts")
        shutil.copy(SAP, os.path.join("charts", "SAP.DE.json"))
        shutil.copy(BMW, os.path.join("charts", "BMW.DE.json"))
        os.mkdir("trader")
        with open(os.path.join("trader", "watchlist.json"), "w") as fh:
            json.dump({"created_by": "dt-scanner", "hits": [{"symbol": "SAP.DE"}, {"symbol": "BMW.DE"}]}, fh)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-10-27 17:00"])
        self.assertEqual(code, 0)
        rows = text.splitlines()
        self.assertTrue(rows[1].startswith("SAP.DE    AUSGELÖST   10:55 Uhr  214,90 €     214,75 €"), rows[1])
        self.assertTrue(rows[2].startswith("BMW.DE    ABGELAUFEN  -          -            57,50 €"), rows[2])
        self.assertIn("XETRA ca. 15 Minuten", text)

    def test_help_is_german(self):
        code, text, _ = run([])
        self.assertEqual(code, 1)
        self.assertIn("Kerze für Kerze", text)


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(SKILLS, "dt-einstieg", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("---\nname: dt-einstieg\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertEqual(text[text.index("## Sicherheit"):], SAFETY)
        low = " ".join(text.lower().split())
        for must in ("kerze für kerze", "verzögert", "die meisten daytrader verlieren geld", "/dt-ausstieg",
                     "nur long", "im hintergrund", "/loop", "es wurde nichts platziert", "10:15 et", "364,18 $",
                     "kerze 8", "sap.de", "214,90 €", "10:55 uhr", "kerze 22", "214,75 €", "211,70 €",
                     "keine anlageberatung", "„ja“", "wann steige ich ein", "beobachte sap"):
            self.assertIn(must, low)
        for never in ("\u2014", "tick für tick", "in echtzeit", "pro" + "fit", "gewinngarantie"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
