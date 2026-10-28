import collections
import copy
import gzip
import hashlib
import io
import json
import os
import random
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

tm = load("dt-zeitmaschine", "timemachine")

DIR = os.path.join(FIX, "dt-zeitmaschine")
TSLA = os.path.join(DIR, "TSLA-60d5m.json.gz")   # Yahoo v8 chart, range=60d interval=5m, fetched 2026-10-19 10:49 ET
with gzip.open(TSLA, "rt", encoding="utf-8") as _fh:
    TEXT = _fh.read()
NOW = "2026-10-19 10:50"
NOW_UTC = tm.parse_now(NOW)

# the reel's plan, as trader-exit writes it (CONTRACT.md)
PLAN = {"created_by": "dt-ausstieg", "symbol": "TSLA", "side": "buy", "date": "2026-10-19", "setup": "orb",
        "entry": 364.18, "entry_time": "10:15 AM", "entry_bar": 8, "interval": "5m",
        "opening_range": {"high": 362.18, "low": 354.47, "minutes": 15},
        "stop": 358.32, "stop_rule": "or_mid", "stop_label": "opening-range midpoint",
        "target": 370.04, "target_r": 1.0, "target_label": "1R (one times the risk)",
        "risk_per_share": 5.86, "reward_risk": 1.0, "flat_by": "15:55"}

# fingerprints of the reel's refs/sim-out.json (sim.py mid 1, seed 19): proves bit-for-bit equality
SIM_BANDS = "b9b7c006a733c68b"
SIM_PATHS = "90f313ef40c576a0"
SIM_TRADES = "0058bef72b0dcdee"
SIM_HIST = {"lo": 351.75, "hi": 377.39,
            "bins": [107, 109, 128, 199, 252, 331, 465, 571, 689, 694, 757, 811, 761, 732, 686, 558, 503, 452,
                     327, 244, 160, 125, 102, 78]}

# XETRA: Yahoo v8 chart SAP.DE, range=60d interval=5m, recorded Wed 2026-10-28 10:10 Berlin (MEZ)
SAP = os.path.join(DIR, "SAP.DE-60d5m.json.gz")
with gzip.open(SAP, "rt", encoding="utf-8") as _fh:
    SAP_TEXT = _fh.read()
SAP_NOW = "2026-10-28 10:13"
# Tue 2026-10-27: range 9:00 to 9:15 is 211.70 to 214.75, the 10:50 bar closes 214.90 above it
SAP_PLAN = {"created_by": "dt-ausstieg", "symbol": "SAP.DE", "side": "buy", "date": "2026-10-27", "setup": "orb",
            "entry": 214.90, "entry_time": "10:55", "interval": "5m",
            "opening_range": {"high": 214.75, "low": 211.70, "minutes": 15},
            "stop": 213.22, "stop_rule": "or_mid", "target": 216.58, "target_r": 1.0, "flat_by": "17:25"}


def sha(x):
    return hashlib.sha256(json.dumps(x).encode("utf-8")).hexdigest()[:16]


def plan(**kw):
    raw = dict(PLAN)
    raw.update(kw)
    return tm.normalize_plan(raw)


def sap_plan(**kw):
    raw = dict(SAP_PLAN)
    raw.update(kw)
    return tm.normalize_plan(raw)


def sap_now():
    return tm.parse_now(SAP_NOW, "xetra")


def machine(p=None, text=TEXT, now=NOW_UTC, **kw):
    return tm.time_machine(text, p or plan(), now, **kw)


def sap_machine(p=None, text=SAP_TEXT, now=None, **kw):
    return tm.time_machine(text, p or sap_plan(), now or sap_now(), **kw)


def edited(fn, text=TEXT):
    """The fixture's chart JSON, changed by fn(result), back as text."""
    doc = json.loads(text)
    fn(doc["chart"]["result"][0])
    return json.dumps(doc)


def keep_bars(result, keep):
    """Keep only the bars where keep(ts) is true."""
    q = result["indicators"]["quote"][0]
    idx = [i for i, ts in enumerate(result["timestamp"]) if keep(ts)]
    result["timestamp"] = [result["timestamp"][i] for i in idx]
    for k in q:
        q[k] = [q[k][i] for i in idx]


def et(ts):
    return tm.markt.to_eastern(tm.utc_of(ts))


def berlin(ts):
    return tm.markt.to_berlin(tm.utc_of(ts))


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tm.main(argv)
    return code, out.getvalue(), err.getvalue()


class Reel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = machine()

    def test_the_reel_odds(self):
        m = self.doc["mc"]
        self.assertEqual((m["replays"], m["seed"], m["window"], m["until"]), (10000, 19, 2, "16:00"))
        self.assertEqual(m["pool_sessions"], 59)
        self.assertEqual(m["bars_left"], 69)
        self.assertEqual((m["pool_from"], m["pool_to"]), ("2026-07-27", "2026-10-16"))
        self.assertEqual(m["p_target"], 0.2938)
        self.assertEqual(m["p_stop"], 0.2548)
        self.assertEqual(m["p_neither"], 0.4514)
        self.assertEqual(m["p_green"], 0.5168)
        self.assertEqual(m["median_close"], 364.36)
        self.assertEqual(m["p5_close"], 355.54)
        self.assertEqual(m["p95_close"], 373.54)
        self.assertEqual(m["avg_R"], 0.034)
        self.assertEqual(m["r_at_target"], 1.0)

    def test_bit_for_bit_with_the_reel_sim(self):
        m = self.doc["mc"]
        self.assertEqual(sha(m["bands"]), SIM_BANDS)
        self.assertEqual(len(m["sample_paths"]), 160)
        self.assertEqual(sha(m["sample_paths"]), SIM_PATHS)
        self.assertEqual(m["hist"], SIM_HIST)
        self.assertEqual(m["bands"][-1], [355.42, 360.91, 364.46, 368.12, 373.65])

    def test_the_history_replay(self):
        h = self.doc["history"]
        self.assertEqual((h["sessions"], h["triggered"]), (59, 33))
        self.assertEqual((h["target"], h["stop"], h["close"], h["green"]), (13, 15, 5, 15))
        self.assertEqual(h["avg_R"], -0.062)
        self.assertEqual(h["rule"], {"setup": "orb", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 1.0})
        slim = [{"date": t["date"], "entry": t["entry"], "outcome": t["outcome"], "R": t["R"]} for t in h["trades"]]
        self.assertEqual(sha(slim), SIM_TRADES)
        first = h["trades"][0]
        self.assertEqual((first["date"], first["entry"], first["stop"], first["target"], first["outcome"]),
                         ("2026-07-28", 307.97, 304.89, 311.05, "target"))

    def test_the_verdict_says_coin_flip(self):
        self.assertEqual(self.doc["verdict"], "Nahe an einem Münzwurf: Ziel zuerst 29,4 % gegen Stop zuerst 25,5 %.")
        # 1R breaks even at 50 % of the replays that hit one side; the reel's target got 53.6 %
        gap, share, even = tm.lean(self.doc["mc"])
        self.assertEqual((round(share, 3), even), (0.536, 0.5))
        self.assertEqual(self.doc["verdict_notes"],
                         ["45,1 % der Durchläufe erreichten bis 16:00 ET keine Seite; bei denen entscheidet "
                          "der Kurs um 16:00 ET."])

    def test_bands_start_at_the_entry(self):
        m = self.doc["mc"]
        self.assertEqual(m["bands"][0], [364.18] * 5)
        self.assertEqual(len(m["bands"]), 70)
        self.assertEqual((m["band_times"][0], m["band_times"][-1], len(m["band_times"])), ("10:15", "16:00", 70))
        self.assertTrue(all(p[0] == 364.18 and len(p) == 70 for p in m["sample_paths"]))

    def test_the_plan_is_carried_through(self):
        p = self.doc["plan"]
        self.assertEqual((p["symbol"], p["entry"], p["stop"], p["target"], p["entry_bar"], p["entry_time"]),
                         ("TSLA", 364.18, 358.32, 370.04, 8, "10:15 AM"))
        self.assertEqual((p["risk_per_share"], p["target_r"], p["flat_by"], p["market"]), (5.86, 1.0, "15:55", "us"))
        self.assertEqual(self.doc["warnings"], [])
        self.assertEqual(self.doc["created_by"], "dt-zeitmaschine")
        self.assertEqual(self.doc["data"]["last_bar"], "2026-10-19 10:40 ET")

    def test_the_text_report(self):
        text = "\n".join(tm.report(self.doc))
        for line in ("TSLA Kauf, Mo 19.10.2026: Einstieg 364,18 um 10:15 ET (16:15 Uhr) (Kerze 8), Stop 358,32, "
                     "Ziel 370,04 (1R, Risiko 5,86 $ je Aktie).",
                     "10.000 Durchläufe", "69 Fünf-Minuten-Kerzen", "Seed 19", "59 vollen Sitzungen",
                     "27.07.2026 bis 16.10.2026",
                     "Ziel zuerst    29,4 %", "Stop zuerst    25,5 %",
                     "weder noch     45,1 %   zum Handelsschluss (16:00 ET) noch offen",
                     "im Plus        51,7 %", "Median 364,36, 90 % der Durchläufe zwischen 355,54 und 373,54",
                     "Durchschnitt: +0,034 R", "15-Minuten-Range ab 09:30 ET, Stop an der Range-Mitte, Ziel 1R",
                     "59 echten Sitzungen 33-mal: 13 Ziel, 15 Stop, 5 weder noch. Durchschnitt -0,062 R",
                     "Nahe an einem Münzwurf: Ziel zuerst 29,4 % gegen Stop zuerst 25,5 %.\n45,1 % der Durchläufe "
                     "erreichten bis 16:00 ET keine Seite; bei denen entscheidet der Kurs um 16:00 ET.",
                     "Glattstellen laut Plan um 15:55 ET: mit --until glatt",
                     "keine Vorhersage", "Ad-hoc-Meldungen", "--seed 19"):
            self.assertIn(line, text)
        for word in ("Gewinn", "P&L", "garantiert", "Echtzeit", "Tick für Tick", "\u2014"):
            self.assertNotIn(word, text)


class Seeds(unittest.TestCase):
    def test_same_seed_same_numbers(self):
        a = machine(replays=2000, seed=5)["mc"]
        b = machine(replays=2000, seed=5)["mc"]
        self.assertEqual(a, b)

    def test_another_seed_gives_other_numbers(self):
        m = machine(seed=7)["mc"]
        self.assertNotEqual((m["p_target"], m["p_stop"], m["median_close"]), (0.2938, 0.2548, 364.36))
        self.assertAlmostEqual(m["p_target"] + m["p_stop"] + m["p_neither"], 1.0, places=6)
        self.assertNotEqual(sha(m["bands"]), SIM_BANDS)

    def test_the_draws_are_stable_across_pythons(self):
        # random.Random(seed), randint and choice are stable since Python 3.2; the reel numbers above
        # are the real proof, this pins the first draws so a failure points at the RNG
        r = random.Random(19)
        self.assertEqual([r.randint(-2, 2) for _ in range(8)], [-2, 2, -2, 2, -1, 1, 0, 2])
        self.assertEqual(r.choice(range(59)), 18)

    def test_window_and_replays(self):
        a = machine(replays=500, window=0)["mc"]
        self.assertEqual((a["replays"], a["window"]), (500, 0))
        self.assertNotEqual(a["bands"], machine(replays=500)["mc"]["bands"])
        with self.assertRaises(tm.TMError):
            machine(replays=0)
        with self.assertRaises(tm.TMError):
            machine(window=11)


class Bars(unittest.TestCase):
    def setUp(self):
        self.result = tm.chart_result(TEXT, "TSLA")

    def test_the_in_progress_tick_is_dropped(self):
        meta, bars, dropped = tm.parse_bars(self.result, NOW_UTC)
        self.assertEqual(dropped, {"no_price": 0, "off_grid": 1, "not_complete": 1, "outside_hours": 0})
        last = bars[-1]
        self.assertEqual((last["date"], last["start"], last["slot"]), ("2026-10-19", "10:40", 14))
        # with the real clock (any time later) the data's own time still marks 10:45 as in progress
        self.assertEqual(tm.parse_bars(self.result, tm.parse_now(None))[1][-1]["start"], "10:40")
        entry = [b for b in bars if b["date"] == "2026-10-19" and b["slot"] == 8][0]
        self.assertEqual((entry["start"], entry["c"]), ("10:10", 364.1759948730469))

    def test_now_pins_the_clock(self):
        bars = tm.parse_bars(self.result, tm.parse_now("2026-10-19 10:12"))[1]
        today = [b for b in bars if b["date"] == "2026-10-19"]
        self.assertEqual(len(today), 8)
        with self.assertRaises(tm.TMError) as cm:
            machine(now=tm.parse_now("2026-10-19 10:12"))
        self.assertIn("nicht in den Daten", str(cm.exception))
        self.assertIn("Kerze 10:05", str(cm.exception))
        self.assertEqual(machine(now=tm.parse_now("2026-10-19 10:15"), replays=200)["mc"]["pool_sessions"], 59)

    def test_daylight_saving(self):
        stamps = [1793367000,   # 2026-10-30 13:30Z = 9:30 EDT
                  1793629800,   # 2026-11-02 14:30Z = 9:30 EST
                  1793626200,   # 2026-11-02 13:30Z = 8:30 EST, before the open
                  1793649600]   # 2026-11-02 20:00Z = 15:00 EST
        res = {"meta": {"symbol": "X"}, "timestamp": stamps,
               "indicators": {"quote": [{"open": [1] * 4, "high": [1] * 4, "low": [1] * 4, "close": [1] * 4,
                                         "volume": [0] * 4}]}}
        meta, bars, dropped = tm.parse_bars(res, tm.parse_now("2026-11-03T00:00Z"))
        self.assertEqual([(b["date"], b["start"], b["slot"]) for b in bars],
                         [("2026-10-30", "09:30", 0), ("2026-11-02", "09:30", 0), ("2026-11-02", "15:00", 66)])
        self.assertEqual(dropped["outside_hours"], 1)
        self.assertEqual(tm.markt.eastern_offset(tm.utc_of(1793367000)), -4)
        self.assertEqual(tm.markt.eastern_offset(tm.utc_of(1793629800)), -5)

    def test_a_half_day_is_left_out(self):
        def cut(res):  # 2026-09-04 ends at 1:00 PM, like a real early close: 42 bars
            keep_bars(res, lambda ts: not (et(ts).date().isoformat() == "2026-09-04" and et(ts).hour >= 13))
        doc = machine(text=edited(cut), replays=300)
        self.assertEqual(doc["mc"]["pool_sessions"], 58)
        self.assertEqual(doc["data"]["short_sessions_left_out"], [{"date": "2026-09-04", "bars": 42}])
        self.assertEqual(doc["history"]["sessions"], 58)
        self.assertNotIn("2026-09-04", [t["date"] for t in doc["history"]["trades"]])
        self.assertIn("1 kurze Sitzung(en) ausgelassen (verkürzte Tage oder Lücken): 04.09.2026.",
                      "\n".join(tm.report(doc)))

    def test_today_is_not_in_the_pool(self):
        doc = machine(replays=200)
        self.assertEqual(doc["mc"]["pool_to"], "2026-10-16")
        self.assertNotIn("2026-10-19", [t["date"] for t in doc["history"]["trades"]])

    def test_a_missing_price_is_dropped(self):
        def hole(res):
            res["indicators"]["quote"][0]["close"][5] = None
        doc = machine(text=edited(hole), replays=200)
        self.assertEqual(doc["data"]["dropped"]["no_price"], 1)
        self.assertEqual(doc["mc"]["pool_sessions"], 58)   # 2026-07-27 now has a gap

    def test_empty_and_broken_data(self):
        empty = json.dumps({"chart": {"result": [{"meta": {"symbol": "TSLA"}, "timestamp": [],
                                                  "indicators": {"quote": [{}]}}], "error": None}})
        with self.assertRaises(tm.TMError) as cm:
            machine(text=empty)
        self.assertIn("keine fertigen 5-Minuten-Kerzen", str(cm.exception))
        gone = json.dumps({"chart": {"result": None, "error": {"code": "Not Found",
                                                               "description": "No data found, symbol may be delisted"}}})
        with self.assertRaises(tm.TMError) as cm:
            machine(text=gone)
        self.assertIn("No data found", str(cm.exception))
        with self.assertRaises(tm.TMError) as cm:
            machine(text="<html>rate limited</html>")
        self.assertIn("kein JSON", str(cm.exception))

    def test_fewer_than_20_sessions_is_refused(self):
        def trim(res):
            keep_bars(res, lambda ts: et(ts).date().isoformat() >= "2026-09-22")
        with self.assertRaises(tm.TMError) as cm:
            machine(text=edited(trim))
        self.assertIn("nur 19 volle Sitzung(en)", str(cm.exception))
        self.assertIn("mindestens 20", str(cm.exception))

        def twenty(res):
            keep_bars(res, lambda ts: et(ts).date().isoformat() >= "2026-09-21")
        self.assertEqual(machine(text=edited(twenty), replays=200)["mc"]["pool_sessions"], 20)

    def test_an_early_close_day_ends_the_replay_at_1_pm(self):
        # the fixture's bars moved onto the 30 trading days up to Friday 2026-11-27 (an NYSE 1:00 PM
        # close), across the Nov 1 clock change, with real New York times for every bar
        sessions = tm.full_sessions(tm.split_sessions(tm.parse_bars(tm.chart_result(TEXT, "TSLA"), NOW_UTC)[1]),
                                    "2026-10-19")[0][-30:]
        days, d = [], tm.datetime.date(2026, 11, 27)
        while len(days) < 30:
            if d.weekday() < 5 and d.isoformat() != "2026-11-26":
                days.append(d)
            d -= tm.datetime.timedelta(days=1)
        stamps, cols = [], {"open": [], "high": [], "low": [], "close": [], "volume": []}
        for day, (_, bars) in zip(sorted(days), sessions):
            for b in bars[:42] if day.isoformat() == "2026-11-27" else bars:
                local = tm.datetime.datetime.combine(day, tm.datetime.time(9, 30)) + tm.datetime.timedelta(
                    minutes=5 * b["slot"])
                stamps.append(int((tm.markt.local_to_utc(local, "us") - tm.EPOCH).total_seconds()))
                for k, f in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v")):
                    cols[k].append(b[f])
        text = json.dumps({"chart": {"result": [{"meta": {"symbol": "TSLA"}, "timestamp": stamps,
                                                 "indicators": {"quote": [cols]}}]}})
        last = sessions[-1][1]
        p = plan(date="2026-11-27", entry=round(last[8]["c"], 2), stop=round(last[8]["c"], 2) - 5,
                 target=round(last[8]["c"], 2) + 5, stop_rule="pct")
        later = tm.parse_now("2026-11-28 12:00")
        doc = machine(p, text=text, now=later, replays=300)
        self.assertEqual((doc["mc"]["until"], doc["mc"]["bars_left"], doc["mc"]["pool_sessions"]), ("13:00", 33, 29))
        self.assertIn("bis 13:00 ET", "\n".join(tm.report(doc)))
        self.assertIn("zum Handelsschluss (13:00 ET) noch offen", "\n".join(tm.report(doc)))
        with self.assertRaises(tm.TMError) as cm:
            machine(p, text=text, now=later, until="15:55", replays=10)
        self.assertIn("verkürzter Handelstag", str(cm.exception))

    def test_the_data_must_be_the_plans_ticker(self):
        with self.assertRaises(tm.TMError) as cm:
            machine(plan(symbol="AAPL"))
        self.assertIn("Daten sind für TSLA", str(cm.exception))


class Plans(unittest.TestCase):
    def test_an_entry_not_in_the_data_is_refused(self):
        with self.assertRaises(tm.TMError) as cm:
            machine(plan(date="2026-10-20"))
        self.assertIn("nicht in den Daten", str(cm.exception))
        self.assertIn("keine Kerzen an dem Tag", str(cm.exception))
        with self.assertRaises(tm.TMError) as cm:      # 10:50 has not happened in this data yet
            machine(plan(entry_time="10:55 AM", entry_bar=None))
        self.assertIn("nicht in den Daten", str(cm.exception))

    def test_a_holiday_is_refused(self):
        with self.assertRaises(tm.TMError) as cm:
            machine(plan(date="2026-11-26"))
        self.assertIn("Do 26.11.2026 ist an NYSE kein Handelstag", str(cm.exception))

    def test_plan_checks(self):
        cases = [
            (dict(entry_time="10:17 AM", entry_bar=None), "5-Minuten-Raster"),
            (dict(entry_time="4:00 PM", entry_bar=None), "zwischen 09:35 ET und 15:55 ET"),
            (dict(entry_bar=9), "widerspricht sich"),
            (dict(entry_time=None, entry_bar=None), "entry_time"),
            (dict(interval="1m"), "7 Tage 1-Minuten-Kerzen"),
            (dict(stop=365.0), "Stop < Einstieg < Ziel"),
            (dict(side="short"), "buy oder sell"),
            (dict(symbol=""), "Symbol"),
            (dict(entry="abc"), "Zahl für entry"),
            (dict(date="Oct 19"), "Datum wie"),
            (dict(opening_range={"minutes": 7}), "Vielfaches von 5"),
        ]
        for change, words in cases:
            with self.assertRaises(tm.TMError, msg=change) as cm:
                plan(**change)
            self.assertIn(words, str(cm.exception), change)

    def test_entry_bar_or_entry_time_alone(self):
        self.assertEqual(plan(entry_time=None)["entry_time"], "10:15 AM")
        self.assertEqual(plan(entry_bar=None)["entry_bar"], 8)
        self.assertEqual(plan(entry_time="10:15", entry_bar=None)["entry_bar"], 8)
        self.assertEqual(plan(entry_time="10:15am", entry_bar=None)["entry_bar"], 8)
        self.assertEqual(plan(entry_time="10:15 ET", entry_bar=None)["entry_bar"], 8)

    def test_until_cuts_the_replay(self):
        doc = machine(until="15:55", replays=500)
        m = doc["mc"]
        self.assertEqual((m["until"], m["bars_left"], m["band_times"][-1]), ("15:55", 68, "15:55"))
        self.assertIn("um 15:55 ET noch offen", "\n".join(tm.report(doc)))
        self.assertEqual(machine(until="3:55 PM", replays=500)["mc"], m)
        self.assertEqual(machine(until="glatt", replays=500)["mc"], m)   # the plan's flat_by
        for bad, words in (("10:15 AM", "nichts zum Durchspielen"), ("16:05", "spätestens 16:00 ET"),
                           ("15:57", "5-Minuten-Raster"), ("noon", "New Yorker Zeit")):
            with self.assertRaises(tm.TMError) as cm:
                machine(until=bad, replays=10)
            self.assertIn(words, str(cm.exception), bad)

    def test_an_entry_outside_its_bar_is_flagged(self):
        doc = machine(plan(entry=368.0, stop=362.0, target=374.0), replays=200)
        self.assertIn("außerhalb der Spanne dieser Kerze", doc["warnings"][0])
        self.assertIn("Hinweis: der Einstieg 368,00", "\n".join(tm.report(doc)))

    def test_stop_rounds_away_from_the_entry(self):
        self.assertEqual(tm.cents_away(358.325, True), 358.32)
        self.assertEqual(tm.cents_away(358.325, False), 358.33)
        self.assertEqual(tm.cents_away(354.4700012207031, True), 354.47)
        self.assertEqual(tm.cents_away(354.46999999999997, True), 354.47)

    def test_the_stop_rule_is_worked_out_when_not_given(self):
        rule = machine(plan(stop_rule=None), replays=100)["history"]["rule"]
        self.assertEqual(rule["stop_rule"], "or_mid")
        rule = machine(plan(stop_rule=None, stop=354.47, target=373.89), replays=100)["history"]["rule"]
        self.assertEqual((rule["stop_rule"], rule["target_r"]), ("or_low", 1.0))
        rule = machine(plan(stop_rule="atr", stop=360.0, target=372.54), replays=100)["history"]["rule"]
        self.assertEqual((rule["stop_rule"], rule["stop_pct"], rule["target_r"]), ("pct", 1.1478, 2.0))

    def test_a_setup_other_than_orb_skips_the_history(self):
        doc = machine(plan(setup="flag"), replays=200)
        self.assertIsNone(doc["history"]["rule"])
        self.assertIn("orb", doc["history"]["note"])
        self.assertEqual(doc["mc"]["pool_sessions"], 59)
        self.assertIn("Rückschau: übersprungen", "\n".join(tm.report(doc)))

    def test_a_sell_plan_mirrors_the_rules(self):
        doc = machine(plan(side="sell", stop=370.04, target=358.32, stop_rule="or_high"), replays=2000)
        m = doc["mc"]
        self.assertAlmostEqual(m["p_target"] + m["p_stop"] + m["p_neither"], 1.0, places=6)
        self.assertEqual(m["r_at_target"], 1.0)
        self.assertEqual(doc["history"]["rule"]["stop_rule"], "or_high")
        for t in doc["history"]["trades"]:
            self.assertTrue(t["target"] < t["entry"] < t["stop"], t)
        text = "\n".join(tm.report(doc))
        self.assertIn("unter dem Einstieg", text)
        self.assertIn("TSLA Verkauf", text)

    def test_the_verdict_thresholds_at_1r(self):
        # 1R: the target's share of the replays that hit one side against 50 %
        self.assertTrue(tm.verdict({"p_target": 0.30, "p_stop": 0.26}).startswith("Nahe an einem Münzwurf"))
        self.assertTrue(tm.verdict({"p_target": 0.40, "p_stop": 0.30}).startswith("Neigt zum Ziel"))
        self.assertTrue(tm.verdict({"p_target": 0.20, "p_stop": 0.30}).startswith("Neigt zum Stop"))
        self.assertTrue(tm.verdict({"p_target": 0.60, "p_stop": 0.30}).startswith("Deutlich Richtung Ziel"))
        self.assertEqual(tm.verdict({"p_target": 0.10, "p_stop": 0.60, "r_at_target": 1.0}),
                         "Deutlich Richtung Stop: Ziel zuerst 10,0 % gegen Stop zuerst 60,0 %.")
        self.assertEqual(tm.verdict({"p_target": 0.0, "p_stop": 0.0, "until": "15:55"}),
                         "Kein Durchlauf erreichte bis 15:55 ET Ziel oder Stop: der Kurs um 15:55 ET entscheidet jeden.")

    def test_a_2r_target_is_judged_against_its_break_even(self):
        # the live TSLA run of 2026-10-20 (entry 370.58, stop 367.06, 2R target 377.62): it needs 33 %, got 32 %
        mc = {"p_target": 0.241, "p_stop": 0.505, "p_neither": 0.254, "r_at_target": 2.0, "avg_R": 0.095}
        self.assertEqual(tm.verdict(mc), "Nahe am Break-even: bei 2R muss das Ziel in 33 % der Durchläufe, die "
                                         "eine Seite erreichen, zuerst kommen; es kam in 32 % zuerst (Ziel zuerst "
                                         "24,1 % gegen Stop zuerst 50,5 %).")
        self.assertEqual(tm.verdict_notes(mc), [])
        lean = dict(mc, p_target=0.15, p_stop=0.55)
        self.assertTrue(tm.verdict(lean).startswith("Neigt zum Stop: bei 2R muss das Ziel in 33 % der Durchläufe, "
                                                    "die eine Seite erreichen, zuerst kommen; es kam in 21 %"))
        self.assertEqual(tm.verdict_notes(lean), ["Das durchschnittliche R liegt trotzdem bei +0,095: die Durchläufe "
                                                  "ohne Treffer ziehen es in die andere Richtung."])
        self.assertTrue(tm.verdict(dict(mc, p_target=0.30, p_stop=0.40)).startswith("Neigt zum Ziel"))
        self.assertTrue(tm.verdict(dict(mc, p_target=0.40, p_stop=0.40)).startswith("Deutlich Richtung Ziel"))
        self.assertIn("bei 1,5R muss das Ziel in 40 %", tm.verdict(dict(mc, r_at_target=1.5)))

    def test_2r_on_the_fixture_near_break_even(self):
        # stop 362.00, 2R target 368.54: 33.5 % vs 62.4 % looks lopsided, but 2R only needs a third
        doc = machine(plan(stop=362.0, target=368.54, stop_rule="pct"))
        m = doc["mc"]
        self.assertEqual((m["r_at_target"], m["p_target"], m["p_stop"], m["avg_R"]), (2.0, 0.3345, 0.6238, 0.068))
        self.assertEqual(doc["verdict"], "Nahe am Break-even: bei 2R muss das Ziel in 33 % der Durchläufe, die "
                                         "eine Seite erreichen, zuerst kommen; es kam in 35 % zuerst (Ziel zuerst "
                                         "33,5 % gegen Stop zuerst 62,4 %).")
        self.assertEqual(doc["verdict_notes"], [])

    def test_2r_on_the_fixture_a_clear_lean(self):
        # the reel's entry and stop with a 2R target 375.90: the target first only 4.0 % vs stop first 25.6 %
        doc = machine(plan(target=375.90))
        m = doc["mc"]
        self.assertEqual((m["r_at_target"], m["p_target"], m["p_stop"], m["p_neither"], m["avg_R"]),
                         (2.0, 0.0397, 0.2558, 0.7045, 0.042))
        self.assertEqual(doc["verdict"], "Deutlich Richtung Stop: bei 2R muss das Ziel in 33 % der Durchläufe, die "
                                         "eine Seite erreichen, zuerst kommen; es kam in 13 % zuerst (Ziel zuerst "
                                         "4,0 % gegen Stop zuerst 25,6 %).")
        self.assertEqual(doc["verdict_notes"], [
            "70,5 % der Durchläufe erreichten bis 16:00 ET keine Seite; bei denen entscheidet der Kurs um 16:00 ET.",
            "Das durchschnittliche R liegt trotzdem bei +0,042: die Durchläufe ohne Treffer ziehen es in die andere "
            "Richtung."])
        text = "\n".join(tm.report(doc))
        self.assertIn(doc["verdict"] + "\n" + doc["verdict_notes"][0] + "\n" + doc["verdict_notes"][1], text)


class Xetra(unittest.TestCase):
    """The real SAP.DE recording: 60 days of 5-minute bars up to Wed 2026-10-28 9:50."""

    @classmethod
    def setUpClass(cls):
        cls.doc = sap_machine(until="glatt")

    def setUp(self):
        self.prev = tm.markt.current()

    def tearDown(self):
        tm.markt.use(self.prev)

    def parsed(self):
        with tm.markt.using("xetra"):
            return tm.parse_bars(tm.chart_result(SAP_TEXT, "SAP.DE"), sap_now())

    def test_the_market_comes_from_the_symbol(self):
        p = sap_plan()
        self.assertEqual((p["market"], p["entry_bar"], p["entry_time"], p["flat_by"]), ("xetra", 22, "10:55", "17:25"))
        self.assertEqual(sap_plan(flat_by=None)["flat_by"], "17:25")   # markt.windows: XETRA default
        self.assertEqual(sap_plan(flat_by=None).get("flat_by"),
                         tm.normalize_plan(dict(SAP_PLAN, flat_by=None), cfg={"zeiten": {"xetra": {"flat_by": "17:25"}}})
                         ["flat_by"])
        self.assertEqual(tm.normalize_plan(dict(SAP_PLAN, flat_by=None), cfg={"flat_by": "17:00"})["flat_by"], "17:00")
        self.assertEqual(sap_plan(entry_time="10:55 Uhr")["entry_bar"], 22)
        self.assertEqual(tm.markt.current(), "us")   # normalize_plan leaves the global market alone

    def test_slots_are_local_xetra_time(self):
        meta, bars, dropped = self.parsed()
        days = tm.split_sessions(bars)
        sizes = collections.Counter(len(v) for v in days.values())
        self.assertEqual(sizes, {102: 58, 101: 1, 11: 1})   # 16.10. has one bar without a price, 28.10. runs to 9:50
        for d, s in days.items():
            self.assertEqual(s[0]["start"], "09:00", d)
            if len(s) == 102:
                self.assertEqual(s[101]["start"], "17:25", d)
        self.assertEqual(dropped, {"no_price": 2, "off_grid": 1, "not_complete": 0, "outside_hours": 0})
        self.assertEqual((bars[-1]["date"], bars[-1]["start"]), ("2026-10-28", "09:50"))
        self.assertEqual(self.doc["data"]["last_bar"], "2026-10-28 09:50 Uhr")
        with tm.markt.using("xetra"):
            self.assertEqual(tm.session_bars(), 102)
        self.assertEqual(tm.session_bars(), 78)

    def test_the_clock_change_on_25_october_moves_nothing(self):
        meta, bars, _ = self.parsed()
        days = tm.split_sessions(bars)
        fri, mon = days["2026-10-23"], days["2026-10-26"]   # MESZ (UTC+2), then MEZ (UTC+1)
        ts = [t for t in json.loads(SAP_TEXT)["chart"]["result"][0]["timestamp"]
              if berlin(t).date().isoformat() in ("2026-10-23", "2026-10-26") and berlin(t).strftime("%H:%M") == "09:00"]
        self.assertEqual([str(tm.utc_of(t)) for t in ts], ["2026-10-23 07:00:00", "2026-10-26 08:00:00"])
        self.assertEqual((len(fri), len(mon)), (102, 102))
        for i in (0, 3, 101):
            self.assertEqual(fri[i]["start"], mon[i]["start"])
        self.assertEqual(mon[3]["start"], "09:15")
        # the pool reaches across the change: Friday and Monday both full, nothing shifted or left out
        with tm.markt.using("xetra"):
            sessions, short = tm.full_sessions(days, "2026-10-27")
        self.assertEqual([d for d, _ in sessions][-2:], ["2026-10-23", "2026-10-26"])
        self.assertEqual(short, [{"date": "2026-10-16", "bars": 101}])
        self.assertEqual([b["start"] for b in sessions[-1][1][:2]], ["09:00", "09:05"])
        # read with a fixed summer offset, Monday's 9:00 bar would land at 10:00 (slot 12)
        summer = tm.utc_of(ts[1]) + tm.datetime.timedelta(hours=2)
        self.assertEqual(summer.strftime("%H:%M"), "10:00")

    def test_the_sap_odds_with_seed_19(self):
        m = self.doc["mc"]
        self.assertEqual((m["replays"], m["seed"], m["window"], m["until"], m["bars_left"]), (10000, 19, 2, "17:25", 78))
        self.assertEqual((m["pool_sessions"], m["pool_from"], m["pool_to"]), (57, "2026-08-06", "2026-10-26"))
        self.assertEqual((m["p_target"], m["p_stop"], m["p_neither"], m["p_green"]), (0.6399, 0.3452, 0.0149, 0.6485))
        self.assertEqual((m["median_close"], m["p5_close"], m["p95_close"], m["avg_R"]), (216.06, 210.6, 221.52, 0.296))
        self.assertEqual((m["band_times"][0], m["band_times"][-1], len(m["bands"])), ("10:55", "17:25", 79))
        self.assertEqual(self.doc["verdict"], "Neigt zum Ziel: Ziel zuerst 64,0 % gegen Stop zuerst 34,5 %.")
        self.assertEqual(self.doc["verdict_notes"], [])

    def test_the_same_seed_repeats_and_another_does_not(self):
        a = sap_machine(replays=2000, seed=5)["mc"]
        self.assertEqual(a, sap_machine(replays=2000, seed=5)["mc"])
        self.assertNotEqual(a["sample_paths"], sap_machine(replays=2000, seed=6)["mc"]["sample_paths"])
        to_close = sap_machine()["mc"]
        self.assertEqual((to_close["until"], to_close["bars_left"], to_close["p_target"], to_close["p_stop"]),
                         ("17:30", 79, 0.643, 0.3432))

    def test_the_history_uses_the_xetra_open(self):
        h = self.doc["history"]
        self.assertEqual((h["sessions"], h["triggered"], h["target"], h["stop"], h["close"]), (57, 48, 23, 20, 5))
        self.assertEqual((h["green"], h["avg_R"]), (25, 0.057))
        self.assertEqual(h["rule"], {"setup": "orb", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 1.0})
        self.assertTrue(all("09:20" <= t["time"] <= "17:25" for t in h["trades"]))
        monday = [t for t in h["trades"] if t["date"] == "2026-10-26"][0]
        self.assertEqual((monday["time"], monday["entry"], monday["stop"], monday["target"], monday["outcome"]),
                         ("09:45", 214.15, 213.15, 215.15, "target"))
        self.assertNotIn("2026-10-27", [t["date"] for t in h["trades"]])
        rule = sap_machine(sap_plan(stop_rule=None), replays=100)["history"]["rule"]
        self.assertEqual(rule["stop_rule"], "or_mid")   # worked out from 27.10.'s own 9:00 to 9:15 range

    def test_the_german_report(self):
        text = "\n".join(tm.report(self.doc))
        for line in ("SAP.DE Kauf, Di 27.10.2026: Einstieg 214,90 um 10:55 Uhr (Kerze 22), Stop 213,22, Ziel 216,58 "
                     "(1R, Risiko 1,68 € je Aktie).",
                     "10.000 Durchläufe für den Rest der Sitzung, 10:55 Uhr bis 17:25 Uhr (78 Fünf-Minuten-Kerzen), "
                     "Seed 19.",
                     "aus den letzten 57 vollen Sitzungen (06.08.2026 bis 26.10.2026)",
                     "  Ziel zuerst    64,0 %", "  Stop zuerst    34,5 %",
                     "  weder noch     1,5 %    um 17:25 Uhr noch offen",
                     "  im Plus        64,8 %   Ziel zuerst, oder um 17:25 Uhr über dem Einstieg",
                     "Kurs um 17:25 Uhr: Median 216,06, 90 % der Durchläufe zwischen 210,60 und 221,52.",
                     "Durchschnitt: +0,296 R",
                     "Rückschau: dieselbe Regel (15-Minuten-Range ab 09:00 Uhr, Stop an der Range-Mitte, Ziel 1R) "
                     "feuerte in diesen 57 echten Sitzungen 48-mal: 23 Ziel, 20 Stop, 5 weder noch. Durchschnitt +0,057 R.",
                     "Neigt zum Ziel: Ziel zuerst 64,0 % gegen Stop zuerst 34,5 %.",
                     "1 kurze Sitzung(en) ausgelassen (verkürzte Tage oder Lücken): 16.10.2026.",
                     "keine Vorhersage", "--seed 19"):
            self.assertIn(line, text)
        self.assertNotIn(" ET", text)
        self.assertNotIn("Glattstellen laut Plan", text)   # --until glatt already ends at 17:25
        chart = tm.render_chart(self.doc)
        self.assertEqual(chart[0], "SAP.DE 27.10.2026, 2.000 Pfade ab dem Einstieg um 10:55 Uhr (Seed 19)")
        self.assertTrue(any(l.startswith("   216,58 |") and l.endswith("  Ziel") for l in chart))
        self.assertTrue(any(l.startswith("   213,22 |") and l.endswith("  Stop") for l in chart))
        self.assertTrue(chart[-2].rstrip().endswith("17:25  Uhr"))

    def test_xetra_plan_checks(self):
        with self.assertRaises(tm.TMError) as cm:
            sap_plan(entry_time="17:30")
        self.assertIn("zwischen 09:05 Uhr und 17:25 Uhr", str(cm.exception))
        with self.assertRaises(tm.TMError) as cm:
            sap_machine(until="17:35", replays=10)
        self.assertIn("spätestens 17:30 Uhr", str(cm.exception))
        with self.assertRaises(tm.TMError) as cm:
            sap_machine(sap_plan(date="2026-12-24"), replays=10)
        self.assertIn("Do 24.12.2026 ist an XETRA kein Handelstag (Börsenfeiertag XETRA: Heiligabend)",
                      str(cm.exception))
        with self.assertRaises(tm.TMError) as cm:
            sap_machine(sap_plan(date="2026-10-28", entry_time="10:30"), replays=10)
        self.assertIn("die Daten enden mit der Kerze 09:50", str(cm.exception))

    def test_the_year_end_session_ends_at_2_pm(self):
        # SAP's full sessions moved onto the 30 XETRA trading days up to Wed 2026-12-30 (Jahresschlussbörse,
        # close 14:00), skipping 24. and 25.12., with real Berlin times for every bar
        with tm.markt.using("xetra"):
            sessions = tm.full_sessions(tm.split_sessions(self.parsed()[1]), "2026-10-27")[0][-30:]
        days, d = [], tm.datetime.date(2026, 12, 30)
        while len(days) < 30:
            if tm.markt.trading_day(d, "xetra")[0]:
                days.append(d)
            d -= tm.datetime.timedelta(days=1)
        stamps, cols = [], {"open": [], "high": [], "low": [], "close": [], "volume": []}
        for day, (_, bars) in zip(sorted(days), sessions):
            for b in bars[:60] if day.isoformat() == "2026-12-30" else bars:
                local = tm.datetime.datetime.combine(day, tm.datetime.time(9, 0)) + tm.datetime.timedelta(
                    minutes=5 * b["slot"])
                stamps.append(int((tm.markt.local_to_utc(local, "xetra") - tm.EPOCH).total_seconds()))
                for k, f in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v")):
                    cols[k].append(b[f])
        text = json.dumps({"chart": {"result": [{"meta": {"symbol": "SAP.DE"}, "timestamp": stamps,
                                                 "indicators": {"quote": [cols]}}]}})
        e = round(sessions[-1][1][22]["c"], 2)
        p = sap_plan(date="2026-12-30", entry=e, stop=e - 2, target=e + 2, stop_rule="pct")
        later = tm.parse_now("2026-12-30 15:00", "xetra")
        doc = sap_machine(p, text=text, now=later, replays=300)
        self.assertEqual((doc["mc"]["until"], doc["mc"]["bars_left"], doc["mc"]["pool_sessions"]), ("14:00", 37, 29))
        self.assertIn("zum Handelsschluss (14:00 Uhr) noch offen", "\n".join(tm.report(doc)))
        with self.assertRaises(tm.TMError) as cm:
            sap_machine(p, text=text, now=later, until="glatt", replays=10)
        self.assertIn("spätestens 14:00 Uhr sein (verkürzter Handelstag)", str(cm.exception))

    def test_a_missing_bar_drops_the_session(self):
        def hole(res):
            for i, t in enumerate(res["timestamp"]):
                if berlin(t).strftime("%Y-%m-%d %H:%M") == "2026-10-26 12:00":
                    res["indicators"]["quote"][0]["close"][i] = None
        doc = sap_machine(text=edited(hole, SAP_TEXT), replays=200)
        self.assertEqual(doc["mc"]["pool_sessions"], 56)
        self.assertEqual(doc["mc"]["pool_to"], "2026-10-23")
        self.assertEqual(doc["data"]["short_sessions_left_out"],
                         [{"date": "2026-10-16", "bars": 101}, {"date": "2026-10-26", "bars": 101}])


class Network(unittest.TestCase):
    def setUp(self):
        self.calls, self.sleeps = [], []
        self._get, self._sleep = tm._get, tm._sleep
        tm._sleep = self.sleeps.append

    def tearDown(self):
        tm._get, tm._sleep = self._get, self._sleep

    def answer(self, codes):
        codes = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url.split(".finance")[0].split("//")[1])
            code = codes.pop(0)
            if code != 200:
                raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
            return TEXT
        tm._get = fake

    def test_url_and_user_agent(self):
        self.assertEqual(tm.chart_url("tsla"),
                         "https://query2.finance.yahoo.com/v8/finance/chart/TSLA?range=60d&interval=5m")
        self.assertIn("/chart/BRK-B?", tm.chart_url("brk.b", "query1"))
        self.assertIn("/chart/SAP.DE?", tm.chart_url("sap.de"))
        self.assertEqual(tm.UA, "Mozilla/5.0 (compatible; day-trader-skill/2.0; "
                                "+https://github.com/Jakeschincariol/day-trader-skill)")

    def test_429_waits_retries_then_falls_back_to_query1(self):
        self.answer([429, 429, 200])
        self.assertEqual(tm.fetch_chart("TSLA"), TEXT)
        self.assertEqual(self.calls, ["query2", "query2", "query1"])
        self.assertEqual(self.sleeps, [tm.BACKOFF, tm.PAUSE])

    def test_one_429_then_ok(self):
        self.answer([429, 200])
        self.assertEqual(tm.fetch_chart("TSLA"), TEXT)
        self.assertEqual(self.calls, ["query2", "query2"])

    def test_5xx_falls_back(self):
        self.answer([503, 200])
        self.assertEqual(tm.fetch_chart("TSLA"), TEXT)
        self.assertEqual(self.calls, ["query2", "query1"])

    def test_rate_limited_everywhere_is_one_plain_line(self):
        self.answer([429, 429, 429, 429])
        with self.assertRaises(tm.TMError) as cm:
            tm.fetch_chart("TSLA")
        self.assertIn("Yahoo bremst gerade", str(cm.exception))

    def test_404(self):
        self.answer([404])
        with self.assertRaises(tm.TMError) as cm:
            tm.fetch_chart("ZZZZ")
        self.assertIn("prüf das Symbol", str(cm.exception))

    def test_run_over_the_network_path(self):
        self.answer([200])
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "plan.json")
            with open(p, "w") as fh:
                json.dump(PLAN, fh)
            code, text, _ = run(["run", "--plan", p, "--now", NOW, "--replays", "300"])
            self.assertEqual(code, 0)
            self.assertEqual(self.calls, ["query2"])
        finally:
            shutil.rmtree(d)


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.plan = os.path.join(self.d, "trader", "plan.json")
        os.makedirs(os.path.dirname(self.plan))
        with open(self.plan, "w") as fh:
            json.dump(PLAN, fh, indent=2)
        self.out = os.path.join(self.d, "trader", "timemachine.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_run_with_the_plan_end_to_end(self):
        code, text, err = run(["run", "--plan", self.plan, "--offline", TSLA, "--now", NOW, "--write", self.out])
        self.assertEqual(code, 0, err)
        self.assertIn("Ziel zuerst    29,4 %", text)
        self.assertIn("Nahe an einem Münzwurf: Ziel zuerst 29,4 % gegen Stop zuerst 25,5 %.", text)
        self.assertIn("Gespeichert: %s." % self.out, text)
        self.assertIn("/dt-budget", text)
        with open(self.out, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(sorted(k for k in ("plan", "mc", "history") if k in doc), ["history", "mc", "plan"])
        self.assertEqual(doc["created_by"], "dt-zeitmaschine")
        self.assertEqual(doc["source"], "offline")
        self.assertEqual((doc["mc"]["p_target"], doc["mc"]["avg_R"]), (0.2938, 0.034))
        self.assertEqual(sha(doc["mc"]["sample_paths"]), SIM_PATHS)
        self.assertEqual((doc["history"]["triggered"], doc["history"]["avg_R"]), (33, -0.062))
        self.assertEqual(doc["plan"]["from"], self.plan)

    def test_the_budget_fixture_plan_runs(self):
        budget = os.path.join(FIX, "dt-budget", "plan-tsla.json")
        code, text, err = run(["run", "--plan", budget, "--offline", TSLA, "--now", NOW, "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(text)["mc"]["p_target"], 0.2938)

    def test_json_output(self):
        code, text, _ = run(["run", "--plan", self.plan, "--offline", TSLA, "--now", NOW, "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(text)
        self.assertEqual(doc["mc"]["p_stop"], 0.2548)
        self.assertNotIn("sample_paths", doc["mc"])
        self.assertTrue(doc["verdict"].startswith("Nahe an einem Münzwurf"))
        self.assertFalse(os.path.exists(self.out))

    def test_the_plan_as_flags_matches_the_file(self):
        code, text, err = run(["run", "--symbol", "tsla", "--date", "2026-10-19", "--entry", "364.18",
                               "--stop", "358.32", "--target", "370.04", "--entry-time", "10:15 AM",
                               "--offline", TSLA, "--now", NOW, "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(text)
        self.assertEqual((doc["mc"]["p_target"], doc["mc"]["p_green"]), (0.2938, 0.5168))
        self.assertEqual(doc["plan"]["stop_rule"], "or_mid")
        self.assertEqual((doc["history"]["target"], doc["history"]["stop"], doc["history"]["avg_R"]), (13, 15, -0.062))
        code, _, err = run(["run", "--symbol", "TSLA", "--entry", "364.18", "--offline", TSLA])
        self.assertEqual(code, 1)
        self.assertIn("--stop", err)

    def test_a_xetra_plan_end_to_end(self):
        with open(self.plan, "w") as fh:
            json.dump(SAP_PLAN, fh)
        tm.markt.use("us")
        code, text, err = run(["run", "--plan", self.plan, "--offline", SAP, "--now", SAP_NOW, "--until", "glatt",
                               "--write", self.out])
        self.assertEqual(code, 0, err)
        self.assertEqual(tm.markt.current(), "us")   # main() restores the market
        self.assertIn("Neigt zum Ziel: Ziel zuerst 64,0 % gegen Stop zuerst 34,5 %.", text)
        self.assertIn("10:55 Uhr bis 17:25 Uhr", text)
        with open(self.out, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["plan"]["market"], doc["plan"]["entry_time"], doc["mc"]["until"]),
                         ("xetra", "10:55", "17:25"))
        self.assertEqual(doc["history"]["triggered"], 48)
        # --now without an offset is Berlin time for a XETRA plan: at 10:13 MEZ the 9:50 bar is done
        code, text, err = run(["run", "--symbol", "SAP.DE", "--date", "2026-10-27", "--entry", "214.90",
                               "--stop", "213.22", "--target", "216.58", "--entry-time", "10:55",
                               "--offline", SAP, "--now", SAP_NOW, "--until", "17:25", "--json"])
        self.assertEqual(code, 0, err)
        flags = json.loads(text)
        self.assertEqual((flags["mc"]["p_target"], flags["plan"]["stop_rule"], flags["data"]["last_bar"]),
                         (0.6399, "or_mid", "2026-10-28 09:50 Uhr"))

    def test_offline_folder_and_default_paths(self):
        shutil.copy(TSLA, self.d)
        cwd = os.getcwd()
        os.chdir(self.d)
        try:
            code, text, err = run(["run", "--offline", ".", "--now", NOW, "--replays", "500", "--write"])
            self.assertEqual(code, 0, err)
            self.assertTrue(os.path.exists(os.path.join("trader", "timemachine.json")))
            code, text, err = run(["chart", "--from"])
            self.assertEqual(code, 0, err)
            self.assertIn("* Median", text)
            with open(os.path.join("trader", "timemachine.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["mc"]["replays"], 500)
        finally:
            os.chdir(cwd)

    def test_errors_are_one_plain_line(self):
        for argv in (["run", "--plan", os.path.join(self.d, "nope.json")],
                     ["run", "--plan", self.plan, "--offline", os.path.join(self.d, "missing.json.gz")],
                     ["run", "--plan", self.plan, "--offline", TSLA, "--until", "9:00"],
                     ["run", "--plan", self.plan, "--offline", TSLA, "--market", "tokio"],
                     ["chart", "--from", os.path.join(self.d, "nope.json")]):
            code, text, err = run(argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
            self.assertTrue(err.startswith("timemachine.py: "), err)
            self.assertNotIn("Traceback", err)
        self.assertEqual(run([])[0], 1)

    def test_chart(self):
        run(["run", "--plan", self.plan, "--offline", TSLA, "--now", NOW, "--write", self.out])
        code, text, _ = run(["chart", "--from", self.out])
        self.assertEqual(code, 0)
        lines = text.splitlines()
        self.assertIn("2.000 Pfade ab dem Einstieg um 10:15 ET (Seed 19)", lines[0])
        self.assertTrue(any(l.startswith("   370,04 |") and l.endswith("  Ziel") for l in lines))
        self.assertTrue(any(l.startswith("   358,32 |") and l.endswith("  Stop") for l in lines))
        self.assertTrue(any(l.startswith("   364,18 |*") and l.endswith("  Einstieg") for l in lines))
        self.assertIn("10:15", text)
        self.assertIn("16:00", text)
        self.assertEqual(lines[-2:], ["Nahe an einem Münzwurf: Ziel zuerst 29,4 % gegen Stop zuerst 25,5 %.",
                                      "45,1 % der Durchläufe erreichten bis 16:00 ET keine Seite; bei denen "
                                      "entscheidet der Kurs um 16:00 ET."])
        code, again, _ = run(["chart", "--plan", self.plan, "--offline", TSLA, "--now", NOW])
        self.assertEqual(again, text)


if __name__ == "__main__":
    unittest.main()
