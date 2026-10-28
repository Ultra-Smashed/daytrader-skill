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

from _load import load, ROOT, FIX

alerts = load("dt-alarm", "alerts")
markt = alerts.markt

QDIR = os.path.join(FIX, "dt-alarm")
PLAN = os.path.join(FIX, "dt-budget", "plan-tsla.json")
# trader/plan.json from dt-ausstieg for SAP.DE on Di 27.10.2026 (real Yahoo bars, see test_exit.py)
SAP_PLAN = os.path.join(QDIR, "plan-sap.json")
DT = datetime.datetime
UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"

# NYSE holidays as published at https://www.nyse.com/markets/hours-calendars (read 2026-10-13)
NYSE_2026 = ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
             "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"]
NYSE_2027 = ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
             "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"]
EARLY = ["2026-11-27", "2026-12-24", "2027-11-26"]
# XETRA, Handelskalender der Deutschen Börse
XETRA_2026 = ["2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01", "2026-12-24", "2026-12-25", "2026-12-31"]
XETRA_2027 = ["2027-01-01", "2027-03-26", "2027-03-29", "2027-12-24", "2027-12-31"]


def ny(text):
    return alerts.parse_now(text, "us")


def de(text):
    return alerts.parse_now(text, "xetra")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = alerts.main(argv)
    return code, out.getvalue(), err.getvalue()


def plan_rules(path=PLAN):
    with open(path, encoding="utf-8") as fh:
        return alerts.rules_from_plan(json.load(fh))


class Calendar(unittest.TestCase):
    def test_holidays_match_the_published_list(self):
        self.assertEqual(sorted(markt.NYSE_HOLIDAYS), NYSE_2026 + NYSE_2027)
        self.assertEqual(sorted(markt.NYSE_EARLY_CLOSE), EARLY)
        self.assertEqual(sorted(markt.XETRA_HOLIDAYS), XETRA_2026 + XETRA_2027)
        self.assertEqual(sorted(markt.XETRA_EARLY_CLOSE), ["2026-12-30"])
        for d in list(markt.NYSE_HOLIDAYS) + list(markt.NYSE_EARLY_CLOSE) + list(markt.XETRA_HOLIDAYS):
            self.assertLess(datetime.date.fromisoformat(d).weekday(), 5, d)

    def test_daylight_saving_switches(self):
        self.assertEqual(markt.eastern_offset(DT(2026, 3, 8, 6, 59)), -5)
        self.assertEqual(markt.eastern_offset(DT(2026, 3, 8, 7, 0)), -4)
        self.assertEqual(markt.eastern_offset(DT(2026, 11, 1, 5, 59)), -4)
        self.assertEqual(markt.eastern_offset(DT(2026, 11, 1, 6, 0)), -5)
        self.assertEqual(markt.eastern_offset(DT(2027, 3, 14, 7, 0)), -4)
        self.assertEqual(markt.berlin_offset(DT(2026, 10, 25, 0, 59)), 2)
        self.assertEqual(markt.berlin_offset(DT(2026, 10, 25, 1, 0)), 1)

    def test_parse_now(self):
        self.assertEqual(ny("2026-10-13T09:30"), DT(2026, 10, 13, 13, 30))
        self.assertEqual(ny("2026-10-19 10:15"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(ny("2026-12-01T09:30"), DT(2026, 12, 1, 14, 30))
        self.assertEqual(ny("2026-10-13T20:00:01Z"), DT(2026, 10, 13, 20, 0, 1))
        self.assertEqual(de("2026-10-27 09:00"), DT(2026, 10, 27, 8, 0))     # MEZ
        self.assertEqual(de("2026-10-23 09:00"), DT(2026, 10, 23, 7, 0))     # MESZ
        with self.assertRaises(alerts.AlertError):
            ny("tomorrow")

    def test_market_status(self):
        st = alerts.market_status(ny("2026-10-13T10:00"), "us")
        self.assertTrue(st["open"])
        self.assertEqual((st["market"], st["now_new_york"], st["now_berlin"]), ("us", "2026-10-13 10:00", "2026-10-13 16:00"))
        self.assertFalse(alerts.market_status(ny("2026-10-13T09:29"), "us")["open"])
        self.assertEqual(alerts.market_status(ny("2026-10-13T09:29"), "us")["next_open"], "2026-10-13 09:30")
        after = alerts.market_status(ny("2026-10-13T16:00"), "us")
        self.assertFalse(after["open"])
        self.assertEqual(after["next_open"], "2026-10-14 09:30")
        july = alerts.market_status(ny("2026-07-03T11:00"), "us")
        self.assertFalse(july["open"])
        self.assertIn("Independence Day", july["reason"])
        self.assertEqual(july["next_open"], "2026-07-06 09:30")
        self.assertTrue(alerts.market_status(ny("2026-11-27T12:59"), "us")["open"])
        self.assertFalse(alerts.market_status(ny("2026-11-27T13:00"), "us")["open"])
        xmas = alerts.market_status(ny("2027-12-24T10:00"), "us")
        self.assertFalse(xmas["open"])
        self.assertEqual(xmas["next_open"], "2027-12-27 09:30")
        self.assertTrue(alerts.market_status(ny("2027-12-31T10:00"), "us")["open"])
        self.assertEqual(alerts.market_status(ny("2026-10-17T10:00"), "us")["reason"], "Wochenende")
        self.assertFalse(alerts.market_status(ny("2028-03-01T10:00"), "us")["calendar_known"])

    def test_xetra_status(self):
        st = alerts.market_status(de("2026-10-27 09:00"), "xetra")
        self.assertTrue(st["open"])
        self.assertEqual((st["opens"], st["closes"], st["reason"]), ("09:00", "17:30", "regulärer Handel"))
        early = alerts.market_status(de("2026-10-27 08:59"), "xetra")
        self.assertEqual((early["open"], early["reason"], early["next_open"]),
                         (False, "vor der Eröffnung", "2026-10-27 09:00"))
        self.assertFalse(alerts.market_status(de("2026-10-27 17:30"), "xetra")["open"])
        self.assertTrue(alerts.market_status(de("2026-12-30 13:59"), "xetra")["open"])
        short = alerts.market_status(de("2026-12-30 14:00"), "xetra")
        self.assertFalse(short["open"])
        self.assertEqual(short["closes"], "14:00")
        self.assertIn("Jahresschlussbörse", short["early_close"])
        silvester = alerts.market_status(de("2026-12-31 10:00"), "xetra")
        self.assertIn("Silvester", silvester["reason"])
        self.assertEqual(silvester["next_open"], "2027-01-04 09:00")
        self.assertIn("Heiligabend", alerts.market_status(de("2026-12-24 10:00"), "xetra")["reason"])
        self.assertTrue(alerts.market_status(de("2026-05-25 10:00"), "xetra")["open"])   # Pfingstmontag is traded


class Quotes(unittest.TestCase):
    def test_yahoo_fixtures(self):
        with open(os.path.join(QDIR, "yahoo-AAPL.json")) as fh:
            q = alerts.parse_yahoo(fh.read(), "AAPL")
        self.assertEqual(q["price"], 341.27)
        self.assertEqual(q["prev_close"], 340.97)
        self.assertEqual(q["time"], "2026-10-13T20:00:01Z")
        with open(os.path.join(QDIR, "yahoo-TSLA.json")) as fh:
            q = alerts.parse_yahoo(fh.read(), "TSLA")
        self.assertEqual((q["price"], q["prev_close"], round(q["open"], 2)), (366.475, 354.72, 357.48))
        self.assertEqual(q["time"], "2026-10-19T14:52:13Z")

    def test_a_xetra_quote(self):
        # real Yahoo answer for SAP.DE, recorded Mi 28.10.2026 (about 15 minutes late: 09:56 Uhr at 10:11 Uhr)
        with open(os.path.join(QDIR, "yahoo-SAP.DE.json")) as fh:
            q = alerts.parse_yahoo(fh.read(), "SAP.DE")
        self.assertEqual((q["price"], q["prev_close"], round(q["open"], 2), q["currency"]), (211.2, 213.15, 212.9, "EUR"))
        self.assertEqual(q["time"], "2026-10-28T08:56:26Z")
        self.assertEqual(alerts.quote_when(q, "2026-10-28"), "09:56 Uhr")
        self.assertEqual(alerts.quote_when(q, "2026-10-27"), "Mi 28.10.2026 09:56 Uhr")

    def test_stooq_fixture(self):
        with open(os.path.join(QDIR, "stooq-AAPL.csv")) as fh:
            q = alerts.parse_stooq(fh.read(), "AAPL")
        self.assertEqual(q["price"], 341.27)
        self.assertEqual(q["open"], 344.67)
        with open(os.path.join(QDIR, "stooq-ZZZZ.csv")) as fh:
            with self.assertRaises(alerts.AlertError):
                alerts.parse_stooq(fh.read(), "ZZZZ")

    def test_stooq_is_not_set_up_for_xetra(self):
        q, errors = alerts.get_quotes(["SAP.DE"], "stooq", QDIR)
        self.assertEqual(q, {})
        self.assertIn("Stooq ist für XETRA-Werte wie SAP.DE nicht eingerichtet", errors[0])

    def test_urls_and_user_agent(self):
        self.assertEqual(alerts.UA, UA)
        self.assertEqual(alerts.stooq_url("BRK.B"), "https://stooq.com/q/l/?s=brk-b.us&f=sd2t2ohlcv&h&e=csv")
        self.assertEqual(alerts.yahoo_url("brk.b"),
                         "https://query2.finance.yahoo.com/v8/finance/chart/BRK-B?range=1d&interval=1d")
        self.assertEqual(alerts.yahoo_url("sap.de"),
                         "https://query2.finance.yahoo.com/v8/finance/chart/SAP.DE?range=1d&interval=1d")
        self.assertIn("//query1.finance.yahoo.com/", alerts.yahoo_url("TSLA", alerts.YAHOO_HOSTS[1]))

    def test_offline_quotes_and_errors(self):
        q, errors = alerts.get_quotes(["AAPL", "KO", "ZZZZ", "NOPE", "SAP.DE"], "yahoo", QDIR)
        self.assertEqual(sorted(q), ["AAPL", "KO", "SAP.DE"])
        self.assertEqual(q["KO"]["price"], 90.11)
        self.assertEqual(len(errors), 2)
        self.assertIn("No data found", errors[0])
        self.assertIn("keine Offline-Kursdatei", errors[1])

    def test_offline_gz(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(QDIR, "yahoo-TSLA.json"), "rb") as src:
                with gzip.open(os.path.join(d, "yahoo-TSLA.json.gz"), "wb") as dst:
                    dst.write(src.read())
            q, errors = alerts.get_quotes(["TSLA"], "yahoo", d)
            self.assertEqual((q["TSLA"]["price"], errors), (366.475, []))
        finally:
            shutil.rmtree(d)


class FakeNet(object):
    """Stands in for urllib: answers each request with the next status code."""

    def __init__(self, codes, body=None):
        self.codes, self.calls, self.sleeps = list(codes), [], []
        with open(os.path.join(QDIR, "yahoo-TSLA.json")) as fh:
            self.body = body or fh.read()

    def urlopen(self, req, timeout=None):
        self.calls.append((req.full_url.split("/")[2], req.get_header("User-agent")))
        code = self.codes.pop(0)
        if code != 200:
            fp = io.BytesIO(b'{"chart":{"result":null,"error":{"code":"Not Found",'
                            b'"description":"No data found, symbol may be delisted"}}}' if code == 404 else b"")
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, fp)
        return io.BytesIO(self.body.encode("utf-8"))


class Network(unittest.TestCase):
    def setUp(self):
        self.saved = (alerts._urlopen, alerts._sleep)

    def tearDown(self):
        alerts._urlopen, alerts._sleep = self.saved

    def net(self, codes):
        f = FakeNet(codes)
        alerts._urlopen = f.urlopen
        alerts._sleep = f.sleeps.append
        return f

    def hosts(self, f):
        return [h.split(".")[0] for h, _ in f.calls]

    def test_query2_first_with_the_contract_user_agent(self):
        f = self.net([200])
        q, errors = alerts.get_quotes(["TSLA"])
        self.assertEqual((q["TSLA"]["price"], errors), (366.475, []))
        self.assertEqual(f.calls, [("query2.finance.yahoo.com", UA)])

    def test_one_retry_with_a_pause_on_429(self):
        f = self.net([429, 200])
        self.assertEqual(alerts.get_quotes(["TSLA"])[0]["TSLA"]["price"], 366.475)
        self.assertEqual(self.hosts(f), ["query2", "query2"])
        self.assertEqual(f.sleeps, [alerts.BACKOFF])

    def test_falls_back_to_query1_on_429_and_5xx(self):
        f = self.net([429, 429, 200])
        self.assertIn("TSLA", alerts.get_quotes(["TSLA"])[0])
        self.assertEqual(self.hosts(f), ["query2", "query2", "query1"])
        f = self.net([503, 200])
        self.assertIn("TSLA", alerts.get_quotes(["TSLA"])[0])
        self.assertEqual(self.hosts(f), ["query2", "query1"])
        f = self.net([500, 502])
        q, errors = alerts.get_quotes(["TSLA"])
        self.assertEqual(q, {})
        self.assertIn("query1.finance.yahoo.com/v8/finance/chart/TSLA antwortete mit HTTP 502", errors[0])

    def test_a_404_is_yahoos_answer_and_a_403_is_not_retried(self):
        f = self.net([404])
        q, errors = alerts.get_quotes(["NOPE"])
        self.assertIn("No data found", errors[0])
        self.assertEqual(self.hosts(f), ["query2"])
        f = self.net([403])
        q, errors = alerts.get_quotes(["TSLA"])
        self.assertIn("HTTP 403", errors[0])
        self.assertEqual(self.hosts(f), ["query2"])

    def test_a_pause_between_tickers(self):
        f = self.net([200, 200])
        alerts.get_quotes(["TSLA", "AAPL"])
        self.assertEqual(f.sleeps, [alerts.PAUSE])


class Rules(unittest.TestCase):
    def setUp(self):
        self.q, _ = alerts.get_quotes(["AAPL", "BAC", "KO", "TSLA"], "yahoo", QDIR)
        self.open = alerts.market_status(ny("2026-10-13T10:00"), "us")
        self.now = ny("2026-10-13T10:00")

    def at(self, text, rules, state=None, quotes=None):
        now = ny(text)
        return alerts.evaluate(rules, self.q if quotes is None else quotes, alerts.market_status(now, "us"),
                               state or {}, now)

    def test_a_target_rings_once(self):
        rules = [{"id": "aapl-340", "symbol": "AAPL", "type": "above", "price": 340}]
        rings, st = alerts.evaluate(rules, self.q, self.open, {}, self.now)
        self.assertEqual(len(rings), 1)
        self.assertEqual("AAPL hat deine obere Alarmmarke 340 $ erreicht (zuletzt 341,27 $ um 16:00 ET).",
                         rings[0]["message"])
        rings, st = alerts.evaluate(rules, self.q, self.open, st, self.now)
        self.assertEqual(rings, [])

    def test_stop_and_rearm(self):
        rules = [{"id": "bac-stop", "symbol": "BAC", "type": "stop", "price": 54, "rearm": True}]
        rings, st = alerts.evaluate(rules, self.q, self.open, {}, self.now)
        self.assertIn("hat den Stop 54 $ erreicht", rings[0]["message"])
        self.q["BAC"]["price"] = 55.0
        rings, st = alerts.evaluate(rules, self.q, self.open, st, self.now)
        self.assertEqual(rings, [])
        self.assertNotIn("bac-stop", st["rung"])
        self.q["BAC"]["price"] = 53.5
        rings, st = alerts.evaluate(rules, self.q, self.open, st, self.now)
        self.assertEqual(len(rings), 1)

    def test_pct_move_from_previous_close(self):
        big = [{"id": "bac-3", "symbol": "BAC", "type": "pct_move", "pct": 3}]
        self.assertEqual(alerts.evaluate(big, self.q, self.open, {}, self.now)[0], [])
        small = [{"id": "bac-1", "symbol": "BAC", "type": "pct_move", "pct": 1, "direction": "down"}]
        rings, st = alerts.evaluate(small, self.q, self.open, {}, self.now)
        self.assertIn("-1,14 %", rings[0]["message"])
        self.assertEqual(alerts.evaluate(small, self.q, self.open, st, self.now)[0], [])
        up = [{"id": "bac-up", "symbol": "BAC", "type": "pct_move", "pct": 1, "direction": "up"}]
        self.assertEqual(alerts.evaluate(up, self.q, self.open, {}, self.now)[0], [])
        tsla = [{"id": "tsla-3", "symbol": "TSLA", "type": "pct_move", "pct": 3}]
        rings, _ = self.at("2026-10-19 10:52", tsla)
        self.assertIn("TSLA hat sich um +3,31 % bewegt, auf 366,48 $ (von 354,72 $", rings[0]["message"])

    def test_opening_bell_once_per_trading_day(self):
        rules = [{"id": "bell", "type": "opening_bell", "market": "us"}]
        closed = alerts.market_status(ny("2026-10-13T08:00"), "us")
        self.assertEqual(alerts.evaluate(rules, {}, closed, {}, ny("2026-10-13T08:00"))[0], [])
        rings, st = alerts.evaluate(rules, {}, self.open, {}, self.now)
        self.assertEqual(rings[0]["message"], "Glocke: US (NYSE/Nasdaq) ist offen (Di 13.10.2026 10:00 ET (16:00 Uhr)).")
        self.assertEqual(alerts.evaluate(rules, {}, self.open, st, ny("2026-10-13T11:00"))[0], [])
        nxt = alerts.market_status(ny("2026-10-14T09:31"), "us")
        self.assertEqual(len(alerts.evaluate(rules, {}, nxt, st, ny("2026-10-14T09:31"))[0]), 1)

    def test_the_plan_gives_a_stop_a_target_and_flat_by_close(self):
        rules = plan_rules()
        self.assertEqual([(r["id"], r["type"]) for r in rules],
                         [("tsla-plan-stop", "stop"), ("tsla-plan-target", "target"), ("tsla-flat-by", "time")])
        self.assertEqual((rules[0]["price"], rules[1]["price"]), (358.32, 370.04))
        self.assertEqual((rules[2]["at"], rules[2]["label"], rules[2]["before_close"]),
                         ("15:55", "Glattstellen vor Handelsschluss", True))
        self.assertTrue(all(r["date"] == "2026-10-19" for r in rules))
        rings, st = self.at("2026-10-19 10:52", rules)          # the real 10:52 quote, 366.475
        self.assertEqual(rings, [])
        q = json.loads(json.dumps(self.q))
        q["TSLA"]["price"] = 358.10
        rings, st = self.at("2026-10-19 11:30", rules, st, q)
        self.assertEqual([r["id"] for r in rings], ["tsla-plan-stop"])
        self.assertEqual("TSLA hat den Stop 358,32 $ erreicht (zuletzt 358,10 $ um 10:52 ET), "
                         "Plan-Stop: opening-range midpoint.", rings[0]["message"])
        q["TSLA"]["price"] = 370.04
        self.assertEqual([r["id"] for r in self.at("2026-10-19 12:00", rules, st, q)[0]], ["tsla-plan-target"])

    def test_flat_by_close_rings_once_per_trading_day(self):
        rules = plan_rules()[2:]
        self.assertEqual(self.at("2026-10-19 15:54", rules)[0], [])
        rings, st = self.at("2026-10-19 15:55", rules)
        self.assertEqual(len(rings), 1)
        self.assertIn("Glattstellen vor Handelsschluss: es ist 15:55 ET (21:55 Uhr), gestellt war 15:55 ET. "
                      "Der Handel endet um 16:00 ET.", rings[0]["message"])
        self.assertIn("dt-broker flatten --symbol TSLA", rings[0]["message"])
        self.assertEqual(self.at("2026-10-19 15:59", rules, st)[0], [])
        rings, _ = self.at("2026-10-19 16:10", rules)
        self.assertIn("Der Handel ist schon geschlossen", rings[0]["message"])
        self.assertEqual(self.at("2026-10-20 15:56", rules, st)[0], [])     # plan rules: their day only

    def test_a_time_alert_moves_with_an_early_close(self):
        rule = [{"id": "flat", "type": "time", "at": "15:55", "label": "Glattstellen", "before_close": True,
                 "market": "us"}]
        self.assertEqual(self.at("2026-11-27 12:54", rule)[0], [])
        rings, _ = self.at("2026-11-27 12:55", rule)
        self.assertIn("gestellt war 12:55 ET. Der Handel endet um 13:00 ET", rings[0]["message"])
        plain = [{"id": "t", "type": "time", "at": "15:55", "label": "check", "market": "us"}]
        self.assertEqual(self.at("2026-11-27 12:55", plain)[0], [])
        already = [dict(rule[0], at="12:55")]                              # a plan made that day: not moved twice
        self.assertEqual(len(self.at("2026-11-27 12:55", already)[0]), 1)
        self.assertEqual(self.at("2026-11-27 09:55", already)[0], [])
        self.assertEqual(self.at("2026-10-17 15:56", rule)[0], [])         # Saturday: no session
        self.assertEqual(self.at("2026-11-26 15:56", rule)[0], [])         # Thanksgiving
        rings, st = self.at("2026-12-01 15:55", rule)                      # standard time
        self.assertEqual(len(rings), 1)
        self.assertEqual(st["rung"]["flat"], "2026-12-01T20:55:00Z")

    def test_the_example_rules_are_valid(self):
        with open(os.path.join(ROOT, "skills", "dt-alarm", "alerts.example.json"), encoding="utf-8") as fh:
            rules = json.load(fh)["rules"]
        for r in rules:
            alerts.validate(r)

        def strip(rs):
            return [{k: v for k, v in r.items() if k != "note"} for r in rs]
        self.assertEqual(strip(r for r in rules if r["id"].startswith("tsla-plan") or r["id"] == "tsla-flat-by"),
                         strip(dict(r, date="2026-10-19") for r in plan_rules()))
        self.assertEqual([r for r in rules if r["id"].startswith("sap.de-plan") or r["id"] == "sap.de-flat-by"],
                         plan_rules(SAP_PLAN))

    def test_bad_rules(self):
        with self.assertRaises(alerts.AlertError):
            alerts.evaluate([{"id": "x", "type": "moon"}], {}, self.open, {}, self.now)
        with self.assertRaises(alerts.AlertError):
            alerts.evaluate([{"id": "x", "type": "above", "symbol": "AAPL"}], {}, self.open, {}, self.now)
        with self.assertRaises(alerts.AlertError):
            alerts.evaluate([{"id": "x", "type": "time", "at": "4pm"}], {}, self.open, {}, self.now)
        with self.assertRaises(alerts.AlertError):
            alerts.evaluate([{"id": "x", "type": "opening_bell", "market": "mars"}], {}, self.open, {}, self.now)
        with self.assertRaises(alerts.AlertError):
            alerts.rules_from_plan({"symbol": "TSLA", "stop": 358.32})


class XetraRules(unittest.TestCase):
    def setUp(self):
        self.q, _ = alerts.get_quotes(["SAP.DE"], "yahoo", QDIR)

    def at(self, text, rules, state=None, quotes=None):
        now = de(text)
        return alerts.evaluate(rules, self.q if quotes is None else quotes, alerts.market_status(now, "xetra"),
                               state or {}, now)

    def test_the_sap_plan(self):
        rules = plan_rules(SAP_PLAN)
        self.assertEqual([(r["id"], r["type"]) for r in rules],
                         [("sap.de-plan-stop", "stop"), ("sap.de-plan-target", "target"), ("sap.de-flat-by", "time")])
        self.assertEqual((rules[0]["price"], rules[1]["price"], rules[2]["at"]), (213.22, 216.58, "17:25"))
        self.assertEqual((rules[0]["note"], rules[1]["note"]),
                         ("Plan-Stop: Mitte der Opening Range", "Plan-Ziel: 1R über dem Einstieg"))
        self.assertTrue(all(r["date"] == "2026-10-27" for r in rules))
        self.assertEqual(self.at("2026-10-27 17:24", rules[2:])[0], [])
        rings, st = self.at("2026-10-27 17:25", rules[2:])
        self.assertEqual(rings[0]["message"],
                         "Glattstellen vor Handelsschluss: es ist 17:25 Uhr, gestellt war 17:25 Uhr. Der Handel endet "
                         "um 17:30 Uhr. Falls SAP.DE noch offen ist, schließ die Position: dt-broker flatten --symbol "
                         "SAP.DE baut das Verkaufsticket, dann /dt-risiko und dein „ja“.")
        self.assertEqual(st["rung"]["sap.de-flat-by"], "2026-10-27T16:25:00Z")
        self.assertEqual(self.at("2026-10-27 17:28", rules[2:], st)[0], [])
        q = json.loads(json.dumps(self.q))
        q["SAP.DE"].update(price=213.1, time="2026-10-27T10:42:00Z")
        rings, _ = self.at("2026-10-27 11:43", rules[:2], quotes=q)
        self.assertEqual(rings[0]["message"], "SAP.DE hat den Stop 213,22 € erreicht (zuletzt 213,10 € um 11:42 Uhr), "
                                              "Plan-Stop: Mitte der Opening Range.")
        self.assertEqual(self.at("2026-10-28 11:43", rules[:2], quotes=q)[0], [])   # the plan's day only
        self.assertEqual(self.at("2026-10-27 11:43", rules[:2])[0], [])             # never on the 28th's price

    def test_flat_by_on_the_short_day_30_12_2026(self):
        with open(SAP_PLAN, encoding="utf-8") as fh:
            plan = json.load(fh)
        rule = alerts.rules_from_plan(dict(plan, date="2026-12-30"))[2:]
        self.assertEqual(self.at("2026-12-30 13:54", rule)[0], [])
        rings, _ = self.at("2026-12-30 13:55", rule)
        self.assertIn("es ist 13:55 Uhr, gestellt war 13:55 Uhr. Der Handel endet um 14:00 Uhr.", rings[0]["message"])
        moved = alerts.rules_from_plan(dict(plan, date="2026-12-30", flat_by="13:55"))[2:]   # dt-ausstieg already moved it
        self.assertEqual(self.at("2026-12-30 10:25", moved)[0], [])
        self.assertEqual(len(self.at("2026-12-30 13:55", moved)[0]), 1)

    def test_the_flat_by_without_a_plan_time_comes_from_the_market(self):
        with open(SAP_PLAN, encoding="utf-8") as fh:
            plan = json.load(fh)
        plan.pop("flat_by")
        self.assertEqual(alerts.rules_from_plan(plan)[2]["at"], "17:25")
        self.assertEqual(alerts.rules_from_plan(plan, {"zeiten": {"xetra": {"flat_by": "17:15"}}})[2]["at"], "17:15")
        plan.pop("market")
        self.assertEqual(alerts.rules_from_plan(plan, {"flat_by": "17:20"})[2]["at"], "17:20")

    def test_the_bell_at_9(self):
        rules = [{"id": "opening-bell", "type": "opening_bell", "market": "xetra"}]
        self.assertEqual(self.at("2026-10-27 08:59", rules)[0], [])
        rings, st = self.at("2026-10-27 09:00", rules)
        self.assertEqual(rings[0]["message"], "Glocke: XETRA ist offen (Di 27.10.2026 09:00 Uhr).")
        self.assertEqual(self.at("2026-10-27 12:00", rules, st)[0], [])
        rings, _ = self.at("2026-12-30 09:00", rules, st)
        self.assertIn("heute verkürzt bis 14:00 Uhr (Jahresschlussbörse", rings[0]["message"])
        self.assertEqual(self.at("2026-12-31 09:00", rules, st)[0], [])

    def test_two_markets_in_one_check(self):
        rules = [{"id": "bell-de", "type": "opening_bell", "market": "xetra"},
                 {"id": "bell-us", "type": "opening_bell", "market": "us"}]
        self.assertEqual([r["id"] for r in self.at("2026-10-27 14:29", rules)[0]], ["bell-de"])
        rings, _ = self.at("2026-10-27 14:30", rules)                      # 9:30 New York: 5 hours apart this week
        self.assertEqual([r["id"] for r in rings], ["bell-de", "bell-us"])
        self.assertIn("09:30 ET (14:30 Uhr)", rings[1]["message"])

    def test_a_stop_on_the_recorded_quote(self):
        rules = [{"id": "sap.de-stop-211.50", "symbol": "SAP.DE", "type": "stop", "price": 211.5}]
        rings, _ = self.at("2026-10-28 10:12", rules)
        self.assertEqual(rings[0]["message"], "SAP.DE hat den Stop 211,50 € erreicht (zuletzt 211,20 € um 09:56 Uhr).")
        self.assertEqual(self.at("2026-10-28 10:12", [dict(rules[0], price=211.0)])[0], [])
        rings, _ = self.at("2026-10-28 10:12", [{"id": "m", "symbol": "SAP.DE", "type": "pct_move", "pct": 0.9}])
        self.assertIn("SAP.DE hat sich um -0,91 % bewegt, auf 211,20 € (von 213,15 €", rings[0]["message"])


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.rules = os.path.join(self.d, "alerts.json")
        self.state = os.path.join(self.d, "state", "alerts.json")
        self.prices = os.path.join(self.d, "prices.json")
        self.none = os.path.join(self.d, "none")

    def tearDown(self):
        shutil.rmtree(self.d)

    def check(self, now, *more):
        return run(["check", "--rules", self.rules, "--state", self.state, "--prices-out", self.prices,
                    "--offline", QDIR, "--now", now, "--config", self.none] + list(more))

    def test_the_reel_trade_from_the_plan(self):
        code, text, _ = run(["add", "--from-plan", "--plan", PLAN, "--rules", self.rules, "--state", self.state,
                             "--config", self.none])
        self.assertEqual(code, 0)
        self.assertIn("Angelegt tsla-flat-by", text)
        self.assertIn("TSLA am Mo 19.10.2026: Stop 358,32 $, Ziel 370,04 $, glatt bis 15:55 ET.", text)
        self.assertIn("/loop", text)
        self.assertEqual(run(["add", "--rules", self.rules, "--opening-bell", "--market", "us"])[0], 0)

        code, text, _ = self.check("2026-10-19 10:52")
        self.assertEqual(code, 0)                                      # the opening bell rings first
        code, text, _ = self.check("2026-10-19 10:53")
        self.assertEqual(code, 1)
        self.assertIn("US (NYSE/Nasdaq): OFFEN, Mo 19.10.2026 10:53 ET (16:53 Uhr), regulärer Handel.", text)
        self.assertIn("Nichts ausgelöst. 4 Regel(n) heute beobachtet, TSLA 366,48 $.", text)
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["prices"], {"TSLA": 366.475})
        self.assertEqual(doc["detail"]["TSLA"]["time"], "2026-10-19T14:52:13Z")
        self.assertEqual(doc["detail"]["TSLA"]["fetched"], "2026-10-19T14:53:00Z")

        code, text, _ = self.check("2026-10-19 15:55")
        self.assertEqual(code, 0)
        self.assertIn("ALARM: Glattstellen vor Handelsschluss", text)
        self.assertIn("keine Order", text)
        self.assertEqual(self.check("2026-10-19 15:57")[0], 1)
        code, text, _ = self.check("2026-10-20 10:00")
        self.assertIn("ALARM: Glocke", text)
        code, text, _ = self.check("2026-10-20 10:05")
        self.assertIn("Nichts ausgelöst. 1 Regel(n) heute beobachtet.", text)

        # a new plan replaces the plan rules and re-arms them
        code, text, _ = run(["add", "--from-plan", "--plan", PLAN, "--rules", self.rules, "--state", self.state])
        with open(self.rules) as fh:
            ids = [r["id"] for r in json.load(fh)["rules"]]
        self.assertEqual(sorted(ids), ["opening-bell", "tsla-flat-by", "tsla-plan-stop", "tsla-plan-target"])
        with open(self.state) as fh:
            self.assertNotIn("tsla-flat-by", json.load(fh)["rung"])

    def test_the_sap_trade_from_the_plan(self):
        code, text, _ = run(["add", "--from-plan", "--plan", SAP_PLAN, "--rules", self.rules, "--state", self.state,
                             "--config", self.none])
        self.assertEqual(code, 0)
        self.assertIn("SAP.DE am Di 27.10.2026: Stop 213,22 €, Ziel 216,58 €, glatt bis 17:25 Uhr.", text)
        self.assertIn("15 Minuten", text)
        self.assertIn("kein Stop", text)
        code, text, _ = run(["add", "--rules", self.rules, "--opening-bell", "--config", self.none])
        self.assertIn('"market": "xetra"', text)
        self.assertEqual(self.check("2026-10-27 08:59", "--no-write")[0], 1)
        code, text, _ = self.check("2026-10-27 09:00", "--no-write")
        self.assertEqual(code, 0)
        self.assertIn("XETRA: OFFEN, Di 27.10.2026 09:00 Uhr, regulärer Handel.", text)
        self.assertIn("ALARM: Glocke: XETRA ist offen (Di 27.10.2026 09:00 Uhr).", text)
        self.assertNotIn(" ET", text)
        code, text, _ = self.check("2026-10-27 17:25", "--json", "--no-write")
        doc = json.loads(text)
        self.assertEqual(doc["market"]["market"], "xetra")
        self.assertEqual([r["id"] for r in doc["rings"]], ["sap.de-flat-by", "opening-bell"])

    def test_a_xetra_stop_from_the_recorded_quote(self):
        code, _, _ = run(["add", "--rules", self.rules, "--symbol", "sap.de", "--stop", "211,50"])
        self.assertEqual(code, 0)
        with open(self.rules) as fh:
            self.assertEqual(json.load(fh)["rules"][0], {"id": "sap.de-stop-211.50", "symbol": "SAP.DE",
                                                         "type": "stop", "price": 211.5})
        code, text, _ = self.check("2026-10-28 10:12")
        self.assertEqual(code, 0)
        self.assertIn("ALARM: SAP.DE hat den Stop 211,50 € erreicht (zuletzt 211,20 € um 09:56 Uhr).", text)
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["prices"], {"SAP.DE": 211.2})
        self.assertEqual(doc["detail"]["SAP.DE"]["time"], "2026-10-28T08:56:26Z")
        self.assertEqual(doc["detail"]["SAP.DE"]["fetched"], "2026-10-28T09:12:00Z")    # 10:12 Uhr MEZ
        self.assertEqual(self.check("2026-10-28 10:17")[0], 1)

    def test_the_v1_portfolio_evening_and_morning(self):
        for args in (["--opening-bell", "--market", "us"], ["--symbol", "AAPL", "--above", "350"],
                     ["--symbol", "BAC", "--stop", "50"]):
            code, _, _ = run(["add", "--rules", self.rules] + args)
            self.assertEqual(code, 0)
        code, _, err = run(["add", "--rules", self.rules, "--symbol", "AAPL", "--above", "350"])
        self.assertEqual(code, 1)
        self.assertIn("gibt es schon", err)

        code, text, _ = self.check("2026-10-13T20:00")
        self.assertEqual(code, 1)
        self.assertIn("Nichts ausgelöst", text)
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["prices"], {"AAPL": 341.27, "BAC": 53.96})

        code, text, _ = self.check("2026-10-14T09:31")
        self.assertEqual(code, 0)
        self.assertIn("ALARM: Glocke", text)
        code, text, _ = self.check("2026-10-14T09:45")
        self.assertEqual(code, 1)

        code, text, _ = run(["list", "--rules", self.rules, "--state", self.state])
        self.assertIn("ausgelöst", text)
        self.assertEqual(run(["reset", "opening-bell", "--state", self.state])[0], 0)
        self.assertEqual(run(["reset", "opening-bell", "--state", self.state])[0], 1)

    def test_add_time_and_target(self):
        code, text, _ = run(["add", "--rules", self.rules, "--at", "15:55", "--label", "flat by close",
                             "--before-close", "--symbol", "tsla"])
        self.assertEqual(code, 0)
        code, text, _ = run(["add", "--rules", self.rules, "--symbol", "TSLA", "--target", "370.04",
                             "--date", "2026-10-19"])
        self.assertEqual(code, 0)
        code, text, _ = run(["add", "--rules", self.rules, "--at", "17:25", "--config", self.none])
        self.assertEqual(code, 0)
        with open(self.rules) as fh:
            rules = json.load(fh)["rules"]
        self.assertEqual(rules[0], {"id": "time-1555", "type": "time", "at": "15:55", "label": "flat by close",
                                    "symbol": "TSLA", "before_close": True})
        self.assertEqual(rules[1], {"id": "tsla-target-370.04", "symbol": "TSLA", "type": "target",
                                    "price": 370.04, "date": "2026-10-19"})
        self.assertEqual(rules[2], {"id": "time-1725", "type": "time", "at": "17:25", "label": "Zeitalarm",
                                    "market": "xetra"})
        self.assertEqual(run(["add", "--rules", self.rules, "--at", "4pm"])[0], 1)
        code, _, err = run(["add", "--rules", self.rules, "--from-plan", "--plan", self.none])
        self.assertEqual(code, 1)
        self.assertIn("kein Plan", err)
        code, _, err = run(["add", "--rules", self.rules, "--opening-bell", "--market", "mars"])
        self.assertEqual(code, 1)
        self.assertIn("unbekannter Markt", err)

    def test_quote_write_merges(self):
        code, text, _ = run(["quote", "AAPL", "KO", "--offline", QDIR, "--write", self.prices,
                             "--now", "2026-10-13T20:00:01Z"])
        self.assertEqual(code, 0)
        self.assertIn("AAPL   341,27 $ (+0,09 % zum Vortagesschluss 340,97 $)", text)
        self.assertIn("verzögert", text)
        run(["quote", "BAC", "--offline", QDIR, "--write", self.prices])
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(sorted(doc["prices"]), ["AAPL", "BAC", "KO"])
        self.assertEqual(doc["detail"]["KO"]["prev_close"], 89.79)
        self.assertEqual(doc["detail"]["KO"]["fetched"], "2026-10-13T20:00:01Z")

    def test_quote_a_xetra_symbol(self):
        code, text, _ = run(["quote", "SAP.DE", "--offline", QDIR, "--write", self.prices,
                             "--now", "2026-10-28 10:12"])
        self.assertEqual(code, 0)
        self.assertIn("SAP.DE 211,20 € (-0,91 % zum Vortagesschluss 213,15 €)  Mi 28.10.2026 09:56 Uhr  [yahoo]", text)
        self.assertIn("15 Minuten", text)
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["detail"]["SAP.DE"]["fetched"], "2026-10-28T09:12:00Z")
        code, text, _ = run(["quote", "SAP.DE", "--source", "stooq", "--offline", QDIR])
        self.assertEqual(code, 1)
        self.assertIn("nicht eingerichtet", text)

    def test_quote_holdings_from_portfolio_and_plan(self):
        pf = os.path.join(self.d, "portfolio.json")
        with open(pf, "w") as fh:
            json.dump({"cash": 0, "positions": [{"ticker": "KO", "shares": 1}]}, fh)
        code, text, _ = run(["quote", "--holdings", "--portfolio", pf, "--plan", PLAN, "--offline", QDIR, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(json.loads(text)["quotes"]), ["KO", "TSLA"])

    def test_clock_exit_codes(self):
        self.assertEqual(run(["clock", "--market", "us", "--now", "2026-10-19 10:15"])[0], 0)
        code, text, _ = run(["clock", "--market", "us", "--now", "2026-12-25T10:00"])
        self.assertEqual(code, 1)
        self.assertIn("Christmas Day", text)
        code, text, _ = run(["clock", "--now", "2026-10-27 09:00", "--config", self.none])
        self.assertEqual(code, 0)
        self.assertIn("XETRA: OFFEN", text)
        self.assertIn("Heute: 09:00 bis 17:30 Uhr.", text)
        code, text, _ = run(["clock", "--now", "2026-12-30 14:00", "--config", self.none])
        self.assertEqual(code, 1)
        self.assertIn("Heute: 09:00 bis 14:00 Uhr (verkürzt: Jahresschlussbörse", text)
        self.assertIn("Nächste Eröffnung: Mo 04.01.2027 09:00 Uhr.", text)
        code, text, _ = run(["clock", "--now", "2028-03-01 10:00", "--config", self.none])
        self.assertIn("umfasst nur 2026 und 2027", text)

    def test_check_without_rules(self):
        code, _, err = run(["check", "--rules", self.rules, "--offline", QDIR])
        self.assertEqual(code, 1)
        self.assertIn("keine Regeln", err)

    def test_market_is_restored(self):
        markt.use("us")
        run(["clock", "--now", "2026-10-27 09:00", "--config", self.none])
        self.assertEqual(markt.current(), "us")


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(ROOT, "skills", "dt-alarm", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("---\nname: dt-alarm\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertIn("## Sicherheit\n\n- Bildung und Werkzeug, keine Anlageberatung.", text)
        low = " ".join(text.lower().split())
        for must in ("alarm wenn sap 200 erreicht", "kursalarm", "erinnere mich ans glattstellen", "/loop",
                     "15 minuten", "ein alarm ist kein stop", "keine order", "17:25 uhr", "9:00 uhr", "213,22 €",
                     "211,20 €", "358,32", "366,48 $", "stooq", "keine anlageberatung", "„ja“"):
            self.assertIn(must, low)
        for never in ("\u2014", "echt" + "zeit"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
