"""dt-ausstieg tests. Bars for the ATR stop reuse tests/fixtures/dt-einstieg/
(TSLA's real Oct 19 2026 five-minute bars, see test_entry.py). The XETRA plan
uses SAP.DE's real five-minute bars of Tue 27.10.2026 from
tests/fixtures/dt-ausstieg/ (Yahoo, recorded 28.10.2026)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal

from _load import load, FIX, ROOT

exitp = load("dt-ausstieg", "exit")
entry = load("dt-einstieg", "entry")
markt = exitp.markt

TSLA = os.path.join(FIX, "dt-einstieg", "TSLA-2026-10-19-5m.json")
SAP = os.path.join(FIX, "dt-ausstieg", "SAP.DE-5d-5m-2026-10-28.json")

# trader/plan.json for the reel, exactly as the contract writes it
REEL_PLAN = {"created_by": "dt-ausstieg", "symbol": "TSLA", "side": "buy", "date": "2026-10-19", "setup": "orb",
             "market": "us", "currency": "USD",
             "entry": 364.18, "entry_time": "10:15 AM", "entry_bar": 8, "interval": "5m",
             "opening_range": {"high": 362.18, "low": 354.47, "minutes": 15},
             "stop": 358.32, "stop_rule": "or_mid", "stop_label": "Mitte der Opening Range",
             "target": 370.04, "target_r": 1.0, "target_label": "1R über dem Einstieg",
             "risk_per_share": 5.86, "reward_risk": 1.0, "flat_by": "15:55"}
REEL_ENTRY = {"created_by": "dt-einstieg", "symbol": "TSLA", "setup": "orb", "side": "buy", "date": "2026-10-19",
              "status": "triggered", "time": "10:15 AM", "bar_start": "10:10", "bar_index": 8, "price": 364.18,
              "level": 362.18, "interval": "5m", "opening_range": {"high": 362.18, "low": 354.47, "minutes": 15},
              "source": "yahoo", "checked_at": "2026-10-19T14:15:00Z"}

# SAP.DE, Di 27.10.2026: range 9:00 to 9:15 (bars 9:00, 9:05, 9:10) 211.70 to 214.75;
# the 10:50 bar (bar 22) is the first to close above the high, at 214.90 (10:55 Uhr).
SAP_PLAN = {"created_by": "dt-ausstieg", "symbol": "SAP.DE", "side": "buy", "date": "2026-10-27", "setup": "orb",
            "market": "xetra", "currency": "EUR",
            "entry": 214.90, "entry_time": "10:55", "entry_bar": 22, "interval": "5m",
            "opening_range": {"high": 214.75, "low": 211.70, "minutes": 15},
            "stop": 213.22, "stop_rule": "or_mid", "stop_label": "Mitte der Opening Range",
            "target": 216.58, "target_r": 1.0, "target_label": "1R über dem Einstieg",
            "risk_per_share": 1.68, "reward_risk": 1.0, "flat_by": "17:25"}
SAP_ENTRY = {"created_by": "dt-einstieg", "symbol": "SAP.DE", "setup": "orb", "side": "buy", "date": "2026-10-27",
             "status": "triggered", "time": "10:55", "bar_start": "10:50", "bar_index": 22, "price": 214.90,
             "level": 214.75, "interval": "5m", "opening_range": {"high": 214.75, "low": 211.70, "minutes": 15},
             "source": "yahoo", "checked_at": "2026-10-27T09:55:00Z"}

SAFETY = """## Sicherheit

- Bildung und Werkzeug, keine Anlageberatung. Eine FREIGABE ist eine Regelprüfung, keine Empfehlung."""


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


def c(entry_px, stop, target="2R", oh=362.18, ol=354.47, atr=None, n=None):
    sr, sp = exitp.parse_stop(stop)
    tr, tp = exitp.parse_target(target)
    return exitp.compute(entry_px, sr, sp, tr, tp, oh, ol, atr, n)


class Math(unittest.TestCase):
    def setUp(self):
        markt.use("us")

    def test_the_reel_or_mid_1r(self):
        p = c(364.18, "or-mid", "1R")
        self.assertEqual(p["stop"], Decimal("358.32"))           # floor(358.325)
        self.assertEqual(p["risk"], Decimal("5.86"))
        self.assertEqual(p["target"], Decimal("370.04"))
        self.assertEqual(p["reward_risk"], Decimal("1.00"))
        self.assertEqual(p["target_label"], "1R über dem Einstieg")
        self.assertEqual(p["stop_detail"], "(362,18 $ + 354,47 $) / 2 = 358,325 $, abgerundet")

    def test_the_default_2r(self):
        p = c(364.18, "or-mid")
        self.assertEqual(p["target"], Decimal("375.90"))
        self.assertEqual(p["target_label"], "2R über dem Einstieg")

    def test_raw_yahoo_floats_give_the_same_cents(self):
        p = c(364.1759948730469, "or-mid", "1R", 362.17999267578125, 354.4700012207031)
        self.assertEqual((p["entry"], p["stop"], p["target"]), (Decimal("364.18"), Decimal("358.32"), Decimal("370.04")))

    def test_other_stops(self):
        p = c(364.18, "or-low")
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("354.47"), Decimal("9.71"), Decimal("383.60")))
        self.assertEqual(p["stop_label"], "Tief der Opening Range")
        p = c(364.18, "price:358.329")
        self.assertEqual(p["stop"], Decimal("358.32"))              # rounds away from the entry
        self.assertEqual(c(364.18, "price:358,329")["stop"], Decimal("358.32"))   # German comma
        p = c(364.18, "pct:1")
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("360.53"), Decimal("3.65"), Decimal("371.48")))
        self.assertEqual(p["stop_label"], "1 % unter dem Einstieg")
        p = c(364.18, "atr:1.5", atr=3.2181, n=9)
        self.assertEqual(p["stop"], Decimal("359.35"))              # 364.18 - 4.82715 = 359.35285
        self.assertEqual(p["stop_label"], "1,5 x ATR(9) unter dem Einstieg")
        self.assertIn("(bisher weniger als 14)", p["stop_detail"])

    def test_target_rounds_half_up_and_price_targets(self):
        p = c(100, "price:99.01", "1.5R", None, None)
        self.assertEqual(p["target"], Decimal("101.49"))            # 100 + 1.485
        self.assertEqual(p["target_label"], "1,5R über dem Einstieg")
        self.assertEqual(c(100, "price:99.01", "1,5R", None, None)["target"], Decimal("101.49"))
        p = c(364.18, "or-mid", "price:372")
        self.assertEqual(p["reward_risk"], Decimal("1.33"))
        self.assertEqual(p["target_label"], "dein Kurs (1,33R)")
        self.assertEqual(p["target_r"], Decimal("1.33"))

    def test_refusals_say_why(self):
        cases = [("price:364.18", "2R", "auf oder über dem Einstieg"),
                 ("price:365", "2R", "auf oder über dem Einstieg"),
                 ("or-mid", "price:364", "auf oder unter dem Einstieg"),
                 ("price:364.01", "2R", "zu eng, um den Spread zu überstehen"),
                 ("pct:0.04", "2R", "zu eng, um den Spread zu überstehen")]
        for stop, target, why in cases:
            with self.assertRaises(exitp.PlanError) as cm:
                c(364.18, stop, target)
            self.assertIn(why, str(cm.exception), stop)
        # 0.05% of 364.18 is 0.182: a $0.19 risk is allowed, $0.18 is not
        self.assertEqual(c(364.18, "price:363.99")["risk"], Decimal("0.19"))
        with self.assertRaises(exitp.PlanError):
            c(364.18, "price:364.00")
        with self.assertRaises(exitp.PlanError):
            c(358.00, "or-mid")                                     # the midpoint is above this entry
        for bad in ("mid-ish", "pct:100", "price:0", "atr:-1"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_stop(bad)
        for bad in ("0R", "R", "lots", "price:x"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_target(bad)
        with self.assertRaises(exitp.PlanError):
            c(364.18, "or-mid", oh=None, ol=None)
        with self.assertRaises(exitp.PlanError):
            c(364.18, "or-mid", oh=354.47, ol=362.18)

    def test_atr_on_the_session_bars(self):
        ch = exitp.load_chart("TSLA", "5m", None, TSLA)
        day = exitp.datetime.date(2026, 10, 19)
        bars = exitp.session_bars(ch, day, "5m", upto_slot=8)
        self.assertEqual(len(bars), 9)                              # 9:30 ... the 10:10 entry bar
        # by hand: the true range of each bar, the first one without the overnight gap
        trs, prev = [], None
        for b in bars:
            r = b["h"] - b["l"]
            if prev is not None:
                r = max(r, abs(b["h"] - prev), abs(b["l"] - prev))
            trs.append(r)
            prev = b["c"]
        self.assertAlmostEqual(trs[0], 362.18 - 354.47, places=4)
        atr, n = exitp.atr_of(bars)
        self.assertEqual(n, 9)
        self.assertAlmostEqual(atr, sum(trs) / 9, places=9)
        self.assertAlmostEqual(atr, 3.2182, places=4)
        # later in the day it uses the last 14 bars; the file's in-progress 10:45 bar and tick never count
        all_bars = exitp.session_bars(ch, day, "5m")
        self.assertEqual(len(all_bars), 15)
        self.assertEqual(exitp.atr_of(all_bars)[1], 14)


class Xetra(unittest.TestCase):
    def setUp(self):
        markt.use("xetra")

    def test_the_sap_session_bars_start_at_9(self):
        ch = exitp.load_chart("SAP.DE", "5m", None, SAP)
        day = exitp.datetime.date(2026, 10, 27)
        bars = exitp.session_bars(ch, day, "5m")
        self.assertEqual(len(bars), 102)                            # 9:00 ... 17:25, all closed
        first = markt.to_local(exitp.utc_of(bars[0]["t"]))
        self.assertEqual(first, exitp.datetime.datetime(2026, 10, 27, 9, 0))
        orb = bars[:3]
        self.assertEqual((round(max(b["h"] for b in orb), 2), round(min(b["l"] for b in orb), 2)), (214.75, 211.7))
        trigger = next(i for i, b in enumerate(bars) if i >= 3 and b["c"] > 214.75)
        self.assertEqual((trigger, round(bars[trigger]["c"], 2)), (22, 214.9))
        p = c(bars[trigger]["c"], "or-mid", "1R", 214.75, 211.7)
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("213.22"), Decimal("1.68"), Decimal("216.58")))
        self.assertEqual(p["stop_detail"], "(214,75 € + 211,70 €) / 2 = 213,225 €, abgerundet")


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)
        os.mkdir("trader")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def write(self, path, doc):
        with open(path, "w") as fh:
            json.dump(doc, fh)

    def plan(self, *args):
        return run(exitp, ["plan", "--now", "2026-10-19 10:16"] + list(args))

    def read_plan(self):
        with open(os.path.join("trader", "plan.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_entry_to_plan_end_to_end(self):
        code, _, err = run(entry, ["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15", "--write"])
        self.assertEqual(code, 0, err)
        code, text, err = self.plan("--stop", "or-mid", "--target", "1R", "--write")
        self.assertEqual(code, 0, err)
        p = self.read_plan()
        for k, v in REEL_PLAN.items():
            self.assertEqual(p[k], v, k)
        self.assertIn("Einstieg         364,18 $ um 10:15 ET (16:15 Uhr), Kerze 8", text)
        self.assertIn("Stop             358,32 $  Mitte der Opening Range", text)
        self.assertIn("Ziel             370,04 $  1R über dem Einstieg", text)
        self.assertIn("Risiko je Aktie  5,86 $ (1,61 % vom Einstieg)", text)
        self.assertIn("Chance:Risiko    1,0", text)
        self.assertIn("Glatt bis        15:55 ET (21:55 Uhr)", text)
        self.assertIn("keine Garantie", text)
        self.assertIn("Neobroker", text)
        self.assertIn("/dt-zeitmaschine", text)
        self.assertNotIn("gewinn", text.lower())   # never on screen
        code, text, _ = self.plan("--write")                       # the defaults: or-mid, 2R
        self.assertEqual(self.read_plan()["target"], 375.90)
        self.assertEqual(self.read_plan()["target_r"], 2.0)
        code, text, _ = run(exitp, ["show", "--now", "2026-10-19 10:20"])
        self.assertEqual(code, 0)
        self.assertIn("375,90 $", text)
        self.assertNotIn("nicht für heute", text)
        code, text, _ = run(exitp, ["show", "--now", "2026-10-20 10:20"])
        self.assertIn("nicht für heute", text)

    def test_manual_flags_and_json(self):
        code, text, _ = self.plan("--symbol", "tsla", "--entry", "364.18", "--or-high", "362.18", "--or-low", "354.47",
                                  "--time", "10:15", "--entry-bar", "8", "--date", "2026-10-19", "--target", "1R",
                                  "--json")
        self.assertEqual(code, 0)
        p = json.loads(text)
        for k, v in REEL_PLAN.items():
            self.assertEqual(p[k], v, k)
        self.assertEqual(p["warnings"], [])

    def test_atr_stop_reads_bars(self):
        self.write(os.path.join("trader", "entry.json"), REEL_ENTRY)
        code, text, err = self.plan("--stop", "atr:1.5", "--offline", TSLA, "--json")
        self.assertEqual(code, 0, err)
        p = json.loads(text)
        self.assertEqual((p["stop"], p["risk_per_share"], p["target"]), (359.35, 4.83, 373.84))
        self.assertEqual((p["stop_rule"], p["atr_bars"]), ("atr", 9))
        self.assertAlmostEqual(p["atr"], 3.2182, places=4)
        code, _, err = self.plan("--stop", "atr:1.5", "--offline", TSLA, "--entry-bar", "1")
        self.assertEqual(code, 1)
        self.assertIn("mindestens 3 abgeschlossene", err)

    def test_refusals_from_the_cli(self):
        self.write(os.path.join("trader", "entry.json"), dict(REEL_ENTRY, status="waiting", time=None, price=None,
                                                              bar_index=None, bar_start=None))
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("TSLA steht auf waiting, nicht ausgelöst", err)
        code, text, _ = self.plan("--entry", "362.19", "--json")    # plan ahead at the level
        self.assertEqual(code, 0)
        p = json.loads(text)
        self.assertEqual((p["entry"], p["stop"], p["entry_time"]), (362.19, 358.32, None))
        self.assertEqual(json.loads(self.plan("--entry", "362,19", "--json")[1])["entry"], 362.19)

        self.write(os.path.join("trader", "entry.json"), dict(REEL_ENTRY, setup="level", level=362.0))
        code, _, err = self.plan()
        self.assertIn("level-Setup hat keinen Opening-Range-Stop", err)
        self.assertEqual(self.plan("--stop", "pct:1")[0], 0)

        code, _, err = self.plan("--side", "sell")
        self.assertIn("v2 plant nur Longs", err)
        self.write(os.path.join("trader", "entry.json"), dict(REEL_ENTRY, side="sell"))
        code, _, err = self.plan()
        self.assertIn("nur Longs", err)
        code, _, err = self.plan("--stop", "price:364.10")
        self.assertIn("nur Longs", err)
        os.remove(os.path.join("trader", "entry.json"))
        code, _, err = self.plan()
        self.assertIn("kein Einstieg", err)
        code, _, err = self.plan("--symbol", "TSLA")
        self.assertIn("braucht --entry", err)
        code, _, err = self.plan("--symbol", "TSLA", "--from", "x.json", "--entry", "1")
        self.assertIn("nicht beides", err)
        code, _, err = self.plan("--symbol", "TSLA", "--entry", "364.18", "--or-high", "362.18")
        self.assertIn("--or-high und --or-low zusammen", err)
        self.assertNotIn("Traceback", err)

    def test_flat_by_config_half_day_and_late_entries(self):
        self.write(os.path.join("trader", "entry.json"), REEL_ENTRY)
        self.write(os.path.join("trader", "config.json"), {"flat_by": "15:45", "min_reward_risk": 1.5})
        code, text, _ = self.plan("--target", "1R", "--json")
        p = json.loads(text)
        self.assertEqual(p["flat_by"], "15:45")
        self.assertIn("unter deinem min_reward_risk 1,5", p["warnings"][0])
        self.write(os.path.join("trader", "config.json"), {"zeiten": {"us": {"flat_by": "15:50"}}})
        self.assertEqual(json.loads(self.plan("--json")[1])["flat_by"], "15:50")
        os.remove(os.path.join("trader", "config.json"))

        half = dict(REEL_ENTRY, date="2026-11-27")
        self.write(os.path.join("trader", "entry.json"), half)
        code, text, _ = run(exitp, ["plan", "--now", "2026-11-27 10:16"])
        self.assertEqual(code, 0)
        self.assertIn("Glatt bis        12:55 ET", text)
        self.assertIn("verkürzten Handelstags (Schluss 13:00 ET, Tag nach Thanksgiving)", text)
        code, _, err = run(exitp, ["plan", "--now", "2026-11-27 10:16", "--flat-by", "14:00"])
        self.assertEqual(code, 1)
        self.assertIn("nach dem Handelsschluss um 13:00 ET", err)

        self.write(os.path.join("trader", "entry.json"), REEL_ENTRY)
        code, _, err = self.plan("--flat-by", "16:30")
        self.assertIn("nach dem Handelsschluss um 16:00 ET", err)
        self.write(os.path.join("trader", "config.json"), {"flat_by": "16:30"})
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("flat_by 16:30 ET aus der Config", err)
        os.remove(os.path.join("trader", "config.json"))
        self.write(os.path.join("trader", "entry.json"), dict(REEL_ENTRY, time="3:58 PM"))
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("keine Zeit", err)

    def test_show_without_a_plan(self):
        code, text, _ = run(exitp, ["show"])
        self.assertEqual(code, 1)
        self.assertIn("Noch kein Plan", text)


class XetraCli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)
        os.mkdir("trader")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def write(self, path, doc):
        with open(path, "w") as fh:
            json.dump(doc, fh)

    def read_plan(self):
        with open(os.path.join("trader", "plan.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_sap_plan_from_entry_json(self):
        self.write(os.path.join("trader", "entry.json"), SAP_ENTRY)
        code, text, err = run(exitp, ["plan", "--target", "1R", "--write", "--now", "2026-10-27 10:56"])
        self.assertEqual(code, 0, err)
        p = self.read_plan()
        for k, v in SAP_PLAN.items():
            self.assertEqual(p[k], v, k)
        self.assertEqual(p["created_at"], "2026-10-27T09:56:00Z")      # 10:56 Uhr MEZ = 09:56 UTC
        self.assertIn("Ausstiegsplan: SAP.DE long, Di 27.10.2026, XETRA, Opening-Range-Ausbruch", text)
        self.assertIn("Einstieg         214,90 € um 10:55 Uhr, Kerze 22", text)
        self.assertIn("Stop             213,22 €  Mitte der Opening Range: (214,75 € + 211,70 €) / 2 = 213,225 €, "
                      "abgerundet", text)
        self.assertIn("Ziel             216,58 €  1R über dem Einstieg", text)
        self.assertIn("Risiko je Aktie  1,68 € (0,78 % vom Einstieg)", text)
        self.assertIn("Glatt bis        17:25 Uhr,", text)
        self.assertNotIn(" ET", text)
        self.assertNotIn("Hinweis:", text)
        code, text, _ = run(exitp, ["show", "--now", "2026-10-27 11:00"])
        self.assertEqual(code, 0)
        self.assertIn("216,58 €", text)
        self.assertNotIn("nicht für heute", text)

    def test_the_sap_plan_from_flags_default_2r_and_or_low(self):
        args = ["plan", "--symbol", "sap.de", "--entry", "214,90", "--or-high", "214,75", "--or-low", "211,70",
                "--time", "10:55", "--entry-bar", "22", "--date", "2026-10-27", "--now", "2026-10-27 10:56", "--json"]
        code, text, err = run(exitp, args)
        self.assertEqual(code, 0, err)
        p = json.loads(text)
        self.assertEqual((p["symbol"], p["market"], p["currency"]), ("SAP.DE", "xetra", "EUR"))
        self.assertEqual((p["stop"], p["target"], p["target_r"], p["flat_by"]), (213.22, 218.26, 2.0, "17:25"))
        self.assertEqual(p["warnings"], [])
        p = json.loads(run(exitp, args + ["--stop", "or-low"])[1])
        self.assertEqual((p["stop"], p["risk_per_share"], p["target"]), (211.7, 3.2, 221.3))

    def test_the_sap_atr_stop(self):
        self.write(os.path.join("trader", "entry.json"), SAP_ENTRY)
        code, text, err = run(exitp, ["plan", "--stop", "atr:1.5", "--offline", SAP, "--now", "2026-10-27 10:56",
                                      "--json"])
        self.assertEqual(code, 0, err)
        p = json.loads(text)
        self.assertEqual(p["atr_bars"], 14)                          # 23 bars by 10:55, the last 14 count
        markt.use("xetra")
        bars = exitp.session_bars(exitp.load_chart("SAP.DE", "5m", None, SAP), exitp.datetime.date(2026, 10, 27),
                                  "5m", 22)
        self.assertEqual(len(bars), 23)
        self.assertAlmostEqual(p["atr"], exitp.atr_of(bars)[0], places=4)
        self.assertLess(p["stop"], 214.90)

    def test_a_sap_entry_at_or_after_17_25_is_refused(self):
        self.write(os.path.join("trader", "entry.json"), dict(SAP_ENTRY, time="17:25"))
        code, _, err = run(exitp, ["plan", "--now", "2026-10-27 17:26"])
        self.assertEqual(code, 1)
        self.assertIn("Glattstellen um 17:25 Uhr: es bleibt keine Zeit", err)
        code, _, err = run(exitp, ["plan", "--now", "2026-10-27 11:00", "--flat-by", "17:30"])
        self.assertIn("nach dem Handelsschluss um 17:30 Uhr am Di 27.10.2026", err)

    def test_the_short_day_30_12_2026(self):
        self.write(os.path.join("trader", "entry.json"), dict(SAP_ENTRY, date="2026-12-30"))
        code, text, err = run(exitp, ["plan", "--now", "2026-12-30 10:56", "--json"])
        self.assertEqual(code, 0, err)
        p = json.loads(text)
        self.assertEqual(p["flat_by"], "13:55")                    # 17:25 minus the 3.5 hours (14:00 statt 17:30)
        self.assertIn("Glatt bis 13:55 Uhr: vorgezogen wegen des verkürzten Handelstags (Schluss 14:00 Uhr, "
                      "Jahresschlussbörse", p["warnings"][0])
        code, _, err = run(exitp, ["plan", "--now", "2026-12-30 10:56", "--flat-by", "14:00"])
        self.assertEqual(code, 1)
        self.assertIn("nach dem Handelsschluss um 14:00 Uhr am Mi 30.12.2026", err)
        self.assertEqual(json.loads(run(exitp, ["plan", "--now", "2026-12-30 10:56", "--flat-by", "13:30",
                                                "--json"])[1])["flat_by"], "13:30")
        self.write(os.path.join("trader", "entry.json"), dict(SAP_ENTRY, date="2026-12-30", time="13:55"))
        self.assertIn("keine Zeit", run(exitp, ["plan", "--now", "2026-12-30 13:56"])[2])

    def test_a_holiday_warns(self):
        self.write(os.path.join("trader", "entry.json"), dict(SAP_ENTRY, date="2026-12-24"))
        p = json.loads(run(exitp, ["plan", "--now", "2026-12-24 10:56", "--json"])[1])
        self.assertIn("Do 24.12.2026 wird an XETRA nicht gehandelt (Börsenfeiertag XETRA: Heiligabend)",
                      p["warnings"][0])

    def test_market_is_restored(self):
        markt.use("us")
        self.write(os.path.join("trader", "entry.json"), SAP_ENTRY)
        run(exitp, ["plan", "--now", "2026-10-27 10:56"])
        self.assertEqual(markt.current(), "us")


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(ROOT, "skills", "dt-ausstieg", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("---\nname: dt-ausstieg\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertIn(SAFETY, text)
        self.assertGreater(text.index("## Sicherheit"), text.index("## Beispiel"))
        low = " ".join(text.lower().split())
        for must in ("vor dem einstieg", "ein stop ist ein plan, keine garantie", "die meisten daytrader verlieren geld",
                     "/dt-zeitmaschine", "/dt-budget", "/dt-alarm", "nur longs", "neobroker", "oco",
                     "358,32 $", "370,04 $", "5,86 $", "375,90", "zu eng, um den spread zu überstehen",
                     "sap.de", "213,22 €", "216,58 €", "1,68 €", "214,90 €", "17:25 uhr", "13:55 uhr",
                     "keine anlageberatung", "„ja“", "wo setze ich den stop", "exit-plan"):
            self.assertIn(must, low)
        for never in ("\u2014", "tick " + "by tick", "echt" + "zeit", "gewinn" + "garantie", "pro" + "fit"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
