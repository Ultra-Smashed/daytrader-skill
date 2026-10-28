import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, SKILLS, FIX

check = load("dt-risiko", "check")
ticket = load("dt-broker", "ticket")
size = load("dt-budget", "size")
markt = check.markt

EXAMPLE_PATH = os.path.join(SKILLS, "dt-budget", "config.example.json")
TSLA_PATH = os.path.join(FIX, "dt-risiko", "orders-tsla.json")
V1_ORDERS_PATH = os.path.join(FIX, "dt-risiko", "orders-reel.json")
SAP_PLAN = os.path.join(FIX, "dt-budget", "plan-sap.json")
NOW = "2026-10-19 10:15"
TODAY = "2026-10-19"
V1_TODAY = "2026-10-13"
PRICES = {"AAPL": 341.27, "AXP": 309.84, "GOOGL": 353.78, "KO": 90.11, "BAC": 53.96}
QUOTE_TIME = datetime.datetime(2026, 10, 19, 14, 52, 13)   # Yahoos TSLA-Kurs 366.475, 10:52:13 New York
# the original pack's US config (v2 contract): USD account, *_usd keys
US_CFG = {
    "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_usd": 4000, "min_order_usd": 5,
    "max_loss_per_trade_usd": 50, "max_daily_loss_usd": 150, "max_trades_per_day": 3, "max_orders_per_day": 10,
    "min_reward_risk": 1.0, "require_stop": True,
    "no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55",
    "fractional": False, "broker": "alpaca", "paper": True, "blocked": [],
    "allow_options": False, "allow_margin": False, "allow_short": False, "pdt_guard": False,
    "sec_user_agent": "Your Name you@example.com",
}
# v1's rules with every day-trade check switched off: the long-term checks still hold
V1 = {"budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 2000, "min_order_usd": 5,
      "max_orders_per_day": 10, "require_stop": False, "no_entries_before": None, "no_entries_after": None,
      "max_trades_per_day": 0, "max_daily_loss_usd": 0, "max_loss_per_trade_usd": 0, "min_reward_risk": 0}


def at(text):
    return check.parse_now(text)


def berlin(text):
    return check.parse_now(text, "xetra")


def cfg(**over):
    c = dict(US_CFG)
    c.update(over)
    return c


def example(**over):
    with open(EXAMPLE_PATH) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def v1(**over):
    c = dict(V1)
    c.update(over)
    return c


def tsla(**over):
    with open(TSLA_PATH) as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def sap_order(**cfg_over):
    """Die Order, die dt-budget aus dem SAP-Beispielplan rechnet (17 Aktien, max. Verlust 25,06 €)."""
    with open(SAP_PLAN) as fh:
        p = json.load(fh)
    return size.bracket_order(size.size_trade(p, example(**cfg_over), today="2026-10-27"))


def bracket(sym, qty, entry, stop, target):
    return {"symbol": sym, "side": "buy", "qty": str(qty), "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "%.2f" % target,
            "stop_loss_stop_price": "%.2f" % stop,
            "plan": {"entry": entry, "stop": stop, "target": target}}


def v1_orders():
    with open(V1_ORDERS_PATH) as fh:
        return json.load(fh)["orders"]


def buy(sym, usd):
    return {"symbol": sym, "side": "buy", "notional": str(usd), "type": "market", "time_in_force": "day"}


def placed(sym, side="buy", day=TODAY, max_loss=46.88, kind=None, status="placed"):
    r = {"symbol": sym, "side": side, "status": status, "date": day, "at": day + "T10:20:00-04:00"}
    if max_loss is not None:
        r["max_loss"] = max_loss
    if kind:
        r["kind"] = kind
    return r


def verdicts(res):
    return [r["verdict"] for r in res["results"]]


def reasons(res, i=0):
    return " | ".join(res["results"][i]["reasons"])


def warnings(res, i=0):
    return " | ".join(res["results"][i]["warnings"])


def write(d, name, doc):
    p = os.path.join(d, name)
    with open(p, "w") as fh:
        json.dump(doc, fh)
    return p


class TheReel(unittest.TestCase):
    def test_the_tsla_bracket_passes_every_check(self):
        res = check.check([tsla()], cfg(), now=at(NOW))
        r = res["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["warnings"], [])
        self.assertEqual((r["kind"], r["entry_ref"], r["stop"], r["target"]), ("entry", 364.18, 358.32, 370.04))
        self.assertEqual((r["risk_per_share"], r["max_loss"], r["reward_risk"]), (5.86, 46.88, 1.0))
        self.assertEqual((r["value"], r["market"], r["currency"], r["fx"]), (2913.44, "us", "USD", 1.0))
        self.assertEqual(res["cash_after"], 2086.56)
        self.assertEqual((res["date"], res["market"], res["account_currency"]), (TODAY, "us", "USD"))
        self.assertIs(res["paper"], True)

    def test_nine_shares_is_blocked_by_the_max_loss_only(self):
        res = check.check([tsla(qty="9")], cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["BLOCK"])
        self.assertEqual(res["results"][0]["reasons"],
                         ["Verlust: 9 Aktien × 5,86 Risiko je Aktie = 52,74 $ am Stop, über deinem max. Verlust "
                          "je Trade von 50 $"])

    def test_fingerprint_is_shared_with_the_broker(self):
        o = tsla()
        self.assertEqual(check.fingerprint(o), ticket.fingerprint(o))
        self.assertEqual(check.fingerprint(dict(o, why="anything", plan={})), check.fingerprint(o))
        self.assertNotEqual(check.fingerprint(dict(o, qty="9")), check.fingerprint(o))
        self.assertNotEqual(check.fingerprint(dict(o, stop_loss_stop_price="358.00")), check.fingerprint(o))
        self.assertEqual(check.ALPACA_FIELDS, ticket.ALPACA_FIELDS)
        p = dict(o["plan"], fx=0.86, fees=2.0, account_currency="EUR", max_loss=48.77)
        self.assertEqual(check.fingerprint(dict(o, plan=p)), check.fingerprint(o))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "state", "risk.json")
            none = os.path.join(d, "none")
            c = write(d, "config.json", cfg())
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check.main(["--orders", TSLA_PATH, "--config", c, "--portfolio", none,
                                   "--prices", none, "--state", none, "--now", NOW, "--out", out])
            text = buf.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("FREIGABE #1 Kauf TSLA 8 Aktien, Einstieg", text)
            self.assertIn("Einstieg 364,18 (Einstieg laut Plan), Stop 358,32, Ziel 370,04: Risiko 5,86 $ je Aktie",
                          text)
            self.assertIn("max. Verlust 46,88 $ (Limit 50 $), Chance/Risiko 1,00 (min. 1)", text)
            self.assertIn("1 freigegeben, 0 gesperrt, Stand Mo 19.10.2026 10:15 ET (16:15 Uhr)", text)
            self.assertIn("keine Anlageberatung", text)
            with open(out) as fh:
                rec = json.load(fh)
            self.assertEqual(rec["date"], TODAY)
            self.assertEqual(rec["results"][0]["kind"], "entry")
            self.assertEqual(rec["results"][0]["verdict"], "PASS")
            self.assertEqual(rec["results"][0]["fingerprint"], check.fingerprint(tsla()))


class DayTradeChecks(unittest.TestCase):
    def one(self, order, now=NOW, **over):
        return check.check([order], cfg(**over), now=at(now))

    def test_a_stop_is_required(self):
        o = tsla()
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price", "plan"):
            o.pop(k)
        o["plan"] = {"entry": 364.18}
        res = self.one(o)
        self.assertIn("Stop: kein Stop", reasons(res))
        res = self.one(o, require_stop=False, min_reward_risk=0)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("kein Stop", warnings(res))

    def test_a_plan_stop_counts_but_warns(self):
        o = tsla()
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price"):
            o.pop(k)
        res = self.one(o)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("nur im Plan", warnings(res))
        self.assertEqual(res["results"][0]["max_loss"], 46.88)

    def test_stop_and_target_on_the_right_side(self):
        self.assertIn("muss unter dem Einstieg 364,18 liegen",
                      reasons(self.one(tsla(stop_loss_stop_price="365.00"))))
        res = self.one(tsla(take_profit_limit_price="364.00"))
        self.assertIn("Ziel: das Ziel 364,00 muss über dem Einstieg 364,18 liegen", reasons(res))

    def test_reward_risk(self):
        res = self.one(tsla(take_profit_limit_price="368.00"))
        self.assertIn("Chance/Risiko: 0,65", reasons(res))
        self.assertEqual(verdicts(self.one(tsla(take_profit_limit_price="368.00"), min_reward_risk=0.5)), ["PASS"])

    def test_a_fresh_higher_price_is_the_entry(self):
        later = at("2026-10-19 10:55")
        res = check.check([tsla()], cfg(), prices={"TSLA": 366.475}, now=later, price_times={"TSLA": QUOTE_TIME})
        r = res["results"][0]
        self.assertEqual((r["entry_ref"], r["entry_ref_from"], r["risk_per_share"]), (366.48, "price", 8.16))
        self.assertIn("Verlust: 8 Aktien × 8,16 Risiko je Aktie = 65,28 $", reasons(res))

    def test_a_stale_or_future_price_is_not_used(self):
        for now in ("2026-10-19 11:30", "2026-10-19 10:15"):
            res = check.check([tsla()], cfg(), prices={"TSLA": 366.475}, now=at(now),
                              price_times={"TSLA": QUOTE_TIME})
            self.assertEqual(verdicts(res), ["PASS"], now)
            self.assertEqual(res["results"][0]["entry_ref"], 364.18)
            self.assertIn("älter als 15 Minuten", warnings(res))

    def test_a_lower_price_does_not_shrink_the_risk(self):
        res = check.check([tsla()], cfg(), prices={"TSLA": 360.00}, now=at(NOW))
        self.assertEqual(res["results"][0]["entry_ref"], 364.18)

    def test_a_limit_order_uses_its_limit_price(self):
        o = tsla(type="limit", limit_price="364.00")
        res = check.check([o], cfg(), prices={"TSLA": 366.475}, now=at(NOW))
        r = res["results"][0]
        self.assertEqual((r["entry_ref"], r["max_loss"], r["verdict"]), (364.0, 45.44, "PASS"))

    def test_daily_loss_and_trades_per_day(self):
        two = {"orders": [placed("AAPL"), placed("AMD")]}
        res = check.check([tsla()], cfg(), state=two, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("heute vorher: 2 von 3 Trades, 93,76 $ von 150 $ Tagesverlust", res["results"][0]["info"][-1])
        three = {"orders": [placed("AAPL"), placed("AMD"), placed("NVDA")]}
        res = check.check([tsla()], cfg(), state=three, now=at(NOW))
        why = reasons(res)
        self.assertIn("Trades: 3 Einstiege heute platziert", why)
        self.assertIn("Tagesverlust: 140,64 $ heute schon im Risiko plus 46,88 $ für diese = 187,52 $, über deinem "
                      "Tageslimit von 150 $", why)
        yesterday = {"orders": [placed(s, day="2026-10-16") for s in ("AAPL", "AMD", "NVDA")]}
        self.assertEqual(verdicts(check.check([tsla()], cfg(), state=yesterday, now=at(NOW))), ["PASS"])

    def test_exits_and_declines_do_not_count_as_trades(self):
        st = {"orders": [placed("AAPL"), placed("AAPL", side="sell", kind="exit", max_loss=None),
                         placed("AMD", status="declined"), placed("NVDA", status="failed")]}
        res = check.check([tsla()], cfg(), state=st, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertEqual(res["today"]["entries_placed"], 1)

    def test_the_batch_counts_toward_the_daily_limits(self):
        orders = [bracket(s, 1, 50.0, 10.0, 90.0) for s in ("AAA", "BBB", "CCC", "DDD")]
        res = check.check(orders, cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS", "PASS", "BLOCK"])
        why = reasons(res, 3)
        self.assertIn("Trades: 0 Einstiege heute platziert plus 3 vorher", why)
        self.assertIn("Tagesverlust: 120 $ heute schon im Risiko plus 40 $ für diese = 160 $", why)

    def test_entry_window_new_york_time(self):
        cases = [("2026-10-19 09:44", "keine neuen Einstiege vor 09:45 ET (es ist 09:44 ET = 15:44 Uhr)"),
                 ("2026-10-19 15:31", "keine neuen Einstiege nach 15:30 ET (es ist 15:31 ET = 21:31 Uhr)"),
                 ("2026-10-19 08:00", "die Börse ist geschlossen (Mo 19.10.2026 08:00 ET"),
                 ("2026-10-19 16:05", "die Börse ist geschlossen"),
                 ("2026-10-17 10:15", "die Börse ist heute geschlossen (Wochenende"),
                 ("2026-11-26 10:15", "die Börse ist heute geschlossen (Börsenfeiertag NYSE: Thanksgiving Day"),
                 ("2026-11-27 12:31", "keine neuen Einstiege nach 12:30 ET"),
                 ("2026-11-27 13:05", "die Börse ist geschlossen"),
                 ("2026-11-02T14:40:00Z", "keine neuen Einstiege vor 09:45 ET (es ist 09:40 ET = 15:40 Uhr)")]
        for now, want in cases:
            res = self.one(tsla(), now=now)
            self.assertIn("Zeitfenster: " + want, reasons(res), now)
        for now in ("2026-10-19 09:45", "2026-10-19 15:30", "2026-11-27 12:30", "2026-11-02T15:15:00Z",
                    "2026-10-30T14:40:00Z", "2026-03-09T13:50:00Z"):
            self.assertEqual(verdicts(self.one(tsla(), now=now)), ["PASS"], now)
        self.assertIn("verkürzter Handel heute bis 13:00 ET",
                      " ".join(self.one(tsla(), now="2026-11-27 12:30")["warnings"]))
        res = self.one(tsla(), now="2026-10-17 10:15", no_entries_before=None, no_entries_after=None)
        self.assertEqual(verdicts(res), ["PASS"])
        with self.assertRaises(check.RiskError):
            self.one(tsla(), no_entries_before="9.45am")

    def test_the_window_uses_new_york_time_not_the_machine(self):
        self.assertEqual(markt.to_local(at("2026-10-19 10:15"), "us"), datetime.datetime(2026, 10, 19, 10, 15))
        self.assertEqual(at("2026-10-19 10:15"), datetime.datetime(2026, 10, 19, 14, 15))
        self.assertEqual(at("2026-12-01 10:15"), datetime.datetime(2026, 12, 1, 15, 15))

    def test_pdt_guard(self):
        def trade(day):
            return [placed("X" + day[-2:], day=day), placed("X" + day[-2:], side="sell", day=day, kind="exit",
                                                            status="filled", max_loss=None)]
        st = {"orders": trade("2026-10-13") + trade("2026-10-14") + trade("2026-10-15")}
        self.assertEqual(verdicts(self.one(tsla())), ["PASS"])
        res = check.check([tsla()], cfg(pdt_guard=True), state=st, now=at(NOW))
        self.assertIn("PDT: 3 Daytrades in den letzten 5 Handelstagen", reasons(res))
        self.assertEqual(verdicts(check.check([tsla()], cfg(), state=st, now=at(NOW))), ["PASS"])
        old = {"orders": trade("2026-10-12") + trade("2026-10-14") + trade("2026-10-15")}
        self.assertEqual(verdicts(check.check([tsla()], cfg(pdt_guard=True), state=old, now=at(NOW))), ["PASS"])
        pending = {"orders": trade("2026-10-14") + trade("2026-10-15") + [placed("AMD")]}
        res = check.check([tsla()], cfg(pdt_guard=True), state=pending, now=at(NOW))
        self.assertIn("PDT: 3 Daytrades", reasons(res))
        buy_only = {"orders": [placed("AMD", day="2026-10-15"), placed("NVDA", day="2026-10-16")]}
        self.assertEqual(check.day_trades(buy_only, TODAY)[0], 0)

    def test_a_short_entry_when_allowed(self):
        short = {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market", "time_in_force": "day",
                 "order_class": "bracket", "take_profit_limit_price": "358.32", "stop_loss_stop_price": "370.04",
                 "plan": {"entry": 364.18}}
        res = self.one(short)
        self.assertIn("Leerverkauf: du verkaufst mehr TSLA, als du hast", reasons(res))
        res = self.one(short, allow_short=True)
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["kind"], r["max_loss"], r["reward_risk"]), ("PASS", "entry", 46.88, 1.0))
        res = self.one(dict(short, stop_loss_stop_price="360.00"), allow_short=True)
        self.assertIn("muss über dem Einstieg 364,18 liegen (Verkauf)", reasons(res))

    def test_bracket_format(self):
        self.assertIn("ganze Aktien als qty", reasons(self.one(dict(tsla(qty=None), notional="2900"))))
        self.assertIn("nimmt nur ganze Aktien", reasons(self.one(tsla(qty="8.5"))))
        self.assertIn("time_in_force day oder gtc", reasons(self.one(tsla(time_in_force="ioc"))))
        self.assertEqual(verdicts(self.one(tsla(time_in_force="gtc"))), ["PASS"])
        o = tsla()
        o.pop("take_profit_limit_price")
        self.assertIn("braucht take_profit_limit_price und stop_loss_stop_price", reasons(self.one(o)))
        self.assertIn("braucht einen stop_loss_stop_price", reasons(self.one(dict(tsla(), stop_loss_stop_price=None,
                                                                                  stop_loss_limit_price="357.00"))))
        self.assertIn("als String", warnings(self.one(tsla(stop_loss_stop_price=358.32))))

    def test_extended_hours(self):
        lim = {"symbol": "KO", "side": "buy", "qty": "1", "type": "limit", "limit_price": "90",
               "time_in_force": "gtc", "extended_hours": True}
        res = check.check([lim], v1(), prices=PRICES, today=V1_TODAY)
        self.assertEqual(verdicts(res), ["PASS"])
        res = check.check([dict(lim, type="market", limit_price=None)], v1(), prices=PRICES, today=V1_TODAY)
        self.assertIn("extended hours braucht eine Limit-Order", reasons(res))


class Exits(unittest.TestCase):
    PF = {"cash": 2086.56, "positions": [{"ticker": "TSLA", "shares": 8,
                                           "lots": [{"date": TODAY, "shares": 8, "cost": 2913.44}]}]}
    SELL = {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market", "time_in_force": "day"}

    def test_getting_out_is_never_blocked_by_the_day_limits(self):
        full = {"orders": [placed("TSLA"), placed("AMD"), placed("NVDA")] +
                          [placed("T%d" % i, max_loss=1) for i in range(6)] +
                          [placed("TSLA", side="sell", kind="exit", max_loss=None)]}
        c = cfg(blocked=["TSLA"], max_order_usd=100, max_daily_loss_usd=50)
        res = check.check([self.SELL], c, portfolio=self.PF, state=full, now=at("2026-10-19 15:58"))
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["kind"]), ("PASS", "exit"), r["reasons"])
        why = warnings(res)
        for word in ("Sperrliste:", "Doppelt:", "Tageslimit:"):
            self.assertIn("Ausstieg, nicht gesperrt: " + word, why)
        self.assertNotIn("Kurs:", why)
        res = check.check([self.SELL], cfg(), portfolio=self.PF, now=at("2026-10-17 12:00"))
        self.assertEqual(verdicts(res), ["PASS"])

    def test_a_partial_exit_and_the_rest(self):
        half = dict(self.SELL, qty="4")
        res = check.check([half, half], cfg(), portfolio=self.PF, prices={"TSLA": 366.0}, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        self.assertEqual([r["kind"] for r in res["results"]], ["exit", "exit"])
        self.assertIn("Ausstieg, nicht gesperrt: Doppelt", warnings(res, 1))
        res = check.check([half, half, half], cfg(), portfolio=self.PF, prices={"TSLA": 366.0}, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS", "BLOCK"])
        self.assertIn("Leerverkauf:", reasons(res, 2))

    def test_format_asset_and_short_still_apply_to_a_sell(self):
        res = check.check([dict(self.SELL, type="limit")], cfg(), portfolio=self.PF, now=at(NOW))
        self.assertIn("braucht einen limit_price", reasons(res))
        res = check.check([dict(self.SELL, qty="9")], cfg(), portfolio=self.PF, now=at(NOW))
        self.assertIn("Leerverkauf: du verkaufst mehr TSLA, als du hast (8 Aktien)", reasons(res))
        res = check.check([self.SELL], cfg(), now=at(NOW))
        self.assertIn("trag erst die Ausführung ein", reasons(res))

    def test_buy_then_sell_in_one_batch(self):
        res = check.check([tsla(), self.SELL], cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        self.assertEqual(res["results"][1]["kind"], "exit")


class V1Checks(unittest.TestCase):
    """v1's Langfrist-Prüfungen gelten weiter (Daytrade-Prüfungen aus)."""

    def one(self, order, **over):
        return check.check([order], v1(**over), prices=PRICES, today=V1_TODAY)["results"][0]

    def test_the_five_buys_pass_on_a_fresh_5000_paper_account(self):
        res = check.check(v1_orders(), v1(), today=V1_TODAY)
        self.assertEqual(verdicts(res), ["PASS"] * 5)
        self.assertEqual(res["cash_after"], 500)
        self.assertEqual(res["results"][0]["value"], 1250)
        self.assertEqual(res["results"][0]["amount"], "1.250 $")

    def test_a_sixth_buy_is_blocked_three_ways(self):
        res = check.check(v1_orders() + [buy("AAPL", 100)], v1(), today=V1_TODAY)
        self.assertEqual(verdicts(res), ["PASS"] * 5 + ["BLOCK"])
        why = reasons(res, 5)
        self.assertIn("Cash:", why)
        self.assertIn("Position:", why)
        self.assertIn("Doppelt:", why)

    def test_the_v2_config_blocks_buys_without_a_stop(self):
        res = check.check(v1_orders(), cfg(), now=at(NOW))
        self.assertEqual(verdicts(res)[0], "BLOCK")
        self.assertIn("Stop: kein Stop", reasons(res))

    def test_max_and_min_order(self):
        self.assertIn("über deiner max. Order von 2.000 $",
                      " ".join(self.one(buy("KO", 2500), max_position_pct=100)["reasons"]))
        self.assertIn("unter deiner Mindestorder von 5 $", " ".join(self.one(buy("KO", 2))["reasons"]))

    def test_blocked_list(self):
        r = self.one(buy("KO", 100), blocked=["KO"])
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("Sperrliste", r["reasons"][0])

    def test_options_off_unless_allowed(self):
        opt = {"symbol": "BE270617C00100000", "side": "buy", "qty": "1", "type": "limit",
               "limit_price": "12.50", "time_in_force": "day"}
        r = self.one(opt)
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("Optionskontrakt", " ".join(r["reasons"]))
        r = self.one(opt, allow_options=True)
        self.assertEqual(r["verdict"], "PASS")
        self.assertTrue(r["warnings"])

    def test_crypto_and_junk_symbols(self):
        crypto = {"symbol": "BTC/USD", "side": "buy", "notional": "50", "type": "market", "time_in_force": "day"}
        self.assertIn("sieht nicht wie eine Aktie aus", " ".join(self.one(crypto)["reasons"]))

    def test_format_rules(self):
        both = dict(buy("KO", 100), qty="1")
        self.assertIn("genau eins von qty oder notional", " ".join(self.one(both)["reasons"]))
        lim = dict(buy("KO", 100), type="limit", limit_price="90")
        self.assertIn("Market-Order mit time_in_force day", " ".join(self.one(lim)["reasons"]))
        nolimit = {"symbol": "KO", "side": "buy", "qty": "1", "type": "limit", "time_in_force": "day"}
        self.assertIn("braucht einen limit_price", " ".join(self.one(nolimit)["reasons"]))
        bad = {"symbol": "KO", "side": "hold", "notional": "100"}
        self.assertIn("side muss buy oder sell sein", " ".join(self.one(bad)["reasons"]))

    def test_numbers_should_be_strings(self):
        r = self.one({"symbol": "KO", "side": "buy", "notional": 100, "type": "market", "time_in_force": "day"})
        self.assertEqual(r["verdict"], "PASS")
        self.assertIn("als String", r["warnings"][0])

    def test_share_orders_need_a_price(self):
        q = {"symbol": "ZZZZ", "side": "buy", "qty": "2", "type": "market", "time_in_force": "day"}
        self.assertIn("kein Kurs für ZZZZ", " ".join(self.one(q)["reasons"]))
        q["symbol"] = "KO"
        r = self.one(q)
        self.assertEqual(r["verdict"], "PASS")
        self.assertAlmostEqual(r["value"], 180.22)

    def test_margin(self):
        r = check.check([buy("KO", 1500)], v1(cash_buffer_pct=0, max_position_pct=100),
                        portfolio={"cash": 1000, "positions": []}, today=V1_TODAY)["results"][0]
        self.assertIn("Margin", " ".join(r["reasons"]))

    PF = {"cash": 500.0, "positions": [{"ticker": "KO", "shares": 7.8571,
                                         "lots": [{"date": "2026-10-13", "shares": 7.8571, "cost": 708.0}]}]}

    def test_short_sales_are_blocked(self):
        sell = {"symbol": "KO", "side": "sell", "qty": "10", "type": "market", "time_in_force": "day"}
        r = check.check([sell], v1(), portfolio=self.PF, prices=PRICES, today=V1_TODAY)["results"][0]
        self.assertIn("Leerverkauf:", " ".join(r["reasons"]))
        sell["qty"] = "3"
        r = check.check([sell], v1(), portfolio=self.PF, prices=PRICES, today=V1_TODAY)["results"][0]
        self.assertEqual(r["verdict"], "PASS")

    def test_a_sell_frees_cash_for_a_later_buy(self):
        orders = [{"symbol": "KO", "side": "sell", "qty": "5", "type": "market", "time_in_force": "day"},
                  buy("BAC", 450)]
        res = check.check(orders, v1(max_position_pct=100), portfolio=self.PF, prices=PRICES, today=V1_TODAY)
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        res = check.check([buy("BAC", 450)], v1(max_position_pct=100), portfolio=self.PF, prices=PRICES,
                          today=V1_TODAY)
        self.assertEqual(verdicts(res), ["BLOCK"])

    def test_daily_limit_and_already_placed_today(self):
        st = {"orders": [{"symbol": "T%d" % i, "side": "buy", "status": "placed", "at": V1_TODAY + "T10:00:00"}
                         for i in range(10)]}
        res = check.check([buy("KO", 100)], v1(), state=st, today=V1_TODAY)
        self.assertIn("Tageslimit", reasons(res))
        res = check.check([buy("KO", 100)], v1(), state=st, today="2026-10-14")
        self.assertEqual(verdicts(res), ["PASS"])
        ko = {"orders": [{"symbol": "KO", "side": "buy", "status": "placed", "at": V1_TODAY + "T10:00:00"}]}
        res = check.check([buy("KO", 100)], v1(), state=ko, today=V1_TODAY)
        self.assertIn("Doppelt: Kauf KO wurde heute schon platziert", reasons(res))
        declined = {"orders": [{"symbol": "KO", "side": "buy", "status": "declined", "at": V1_TODAY + "T10:00:00"}]}
        self.assertEqual(verdicts(check.check([buy("KO", 100)], v1(), state=declined, today=V1_TODAY)), ["PASS"])

    def test_live_account_warns(self):
        res = check.check([buy("KO", 100)], v1(paper=False), today=V1_TODAY)
        self.assertIn("LIVE", res["warnings"][0])


class Xetra(unittest.TestCase):
    """SAP.DE aus dem Beispielplan (echte Kerzen vom 27.10.2026), Beispiel-Config mit EUR-Konto."""

    def one(self, now, order=None, **over):
        return check.check([order or sap_order()], example(**over), now=berlin(now))

    def test_the_sap_order_passes_at_9_20(self):
        res = self.one("2026-10-27 09:20")
        r = res["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual((res["market"], res["date"], res["account_currency"]), ("xetra", "2026-10-27", "EUR"))
        self.assertEqual((r["market"], r["currency"], r["fx"], r["value"]), ("xetra", "EUR", 1.0, 3620.15))
        self.assertEqual((r["max_loss"], r["max_loss_instrument"], r["reward_risk"]), (25.06, 21.25, 1.0))
        self.assertEqual(res["cash_after"], 1379.85)
        self.assertEqual(res["notes"], [])

    def test_xetra_window_in_berlin_time(self):
        cases = [("2026-10-27 09:14", "keine neuen Einstiege vor 09:15 Uhr (es ist 09:14 Uhr)"),
                 ("2026-10-27 17:01", "keine neuen Einstiege nach 17:00 Uhr (es ist 17:01 Uhr)"),
                 ("2026-10-27 08:59", "die Börse ist geschlossen (Di 27.10.2026 08:59 Uhr; Handel 09:00 bis 17:30 Uhr)"),
                 ("2026-10-27 17:35", "die Börse ist geschlossen"),
                 ("2026-10-24 10:00", "die Börse ist heute geschlossen (Wochenende"),
                 ("2026-04-06 10:00", "die Börse ist heute geschlossen (Börsenfeiertag XETRA: Ostermontag"),
                 ("2026-12-30 13:31", "keine neuen Einstiege nach 13:30 Uhr (es ist 13:31 Uhr)"),
                 ("2026-12-30 14:05", "die Börse ist geschlossen"),
                 ("2026-10-27T08:10:00Z", "keine neuen Einstiege vor 09:15 Uhr (es ist 09:10 Uhr)"),
                 ("2026-10-23T07:10:00Z", "keine neuen Einstiege vor 09:15 Uhr (es ist 09:10 Uhr)")]
        for now, want in cases:
            self.assertIn("Zeitfenster: " + want, reasons(self.one(now)), now)
        for now in ("2026-10-27 09:15", "2026-10-27 17:00", "2026-12-30 13:30", "2026-05-25 10:00",
                    "2026-10-27T08:20:00Z", "2026-10-23T07:20:00Z", "2026-10-27T15:55:00Z"):
            self.assertEqual(verdicts(self.one(now)), ["PASS"], now)

    def test_the_short_day_moves_the_window_by_3_5_hours(self):
        res = self.one("2026-12-30 13:30")
        self.assertIn("verkürzter Handel heute bis 14:00 Uhr (Jahresschlussbörse, letzter Handelstag des Jahres): "
                      "keine neuen Einstiege nach 13:30 Uhr", " ".join(res["warnings"]))

    def test_berlin_time_in_winter_and_summer(self):
        self.assertEqual(berlin("2026-10-27 09:20"), datetime.datetime(2026, 10, 27, 8, 20))     # MEZ, UTC+1
        self.assertEqual(berlin("2026-10-23 09:20"), datetime.datetime(2026, 10, 23, 7, 20))     # MESZ, UTC+2
        res = self.one("2026-10-27T23:30:00Z")                                                   # 00:30 am 28.10.
        self.assertEqual(res["date"], "2026-10-28")

    def test_own_windows_per_market(self):
        res = self.one("2026-10-27 09:20", zeiten={"xetra": {"no_entries_before": "09:30"}})
        self.assertIn("keine neuen Einstiege vor 09:30 Uhr", reasons(res))

    def test_xetra_tickers_look_like_stocks(self):
        for sym in ("SAP.DE", "P911.DE", "1COV.DE", "HEN3.DE"):
            res = check.check([buy(sym, 100)], example(), today="2026-10-27")
            self.assertNotIn("Wertpapier", reasons(res), sym)
        for sym in ("BTC/EUR", "SAP.DEX", "TOOLONGNAME.DE"):
            res = check.check([buy(sym, 100)], example(), today="2026-10-27")
            self.assertIn("sieht nicht wie eine Aktie aus", reasons(res), sym)

    def test_alpaca_does_not_trade_xetra(self):
        res = self.one("2026-10-27 09:20", broker="alpaca")
        self.assertEqual(verdicts(res), ["BLOCK"])
        self.assertIn("Broker: Alpaca handelt keine XETRA-Werte; nimm ibkr oder manuell", reasons(res))
        for b in ("ibkr", "manuell"):
            self.assertEqual(verdicts(self.one("2026-10-27 09:20", broker=b)), ["PASS"], b)
        sell = {"symbol": "SAP.DE", "side": "sell", "qty": "17", "type": "market", "time_in_force": "day"}
        pf = {"cash": 1379.85, "positions": [{"ticker": "SAP.DE", "shares": 17, "lots": [{"cost": 3620.15}]}]}
        res = check.check([sell], example(broker="alpaca"), portfolio=pf, now=berlin("2026-10-27 12:00"))
        self.assertIn("Alpaca handelt keine XETRA-Werte", reasons(res))


class Pdt(unittest.TestCase):
    STATE = {"orders": [placed("X%d" % d, day="2026-10-%d" % d) for d in (13, 14, 15)] +
                       [placed("X%d" % d, side="sell", day="2026-10-%d" % d, kind="exit", status="filled",
                               max_loss=None) for d in (13, 14, 15)]}

    def test_alpaca_turns_it_on_unless_switched_off(self):
        c = cfg()
        c.pop("pdt_guard")
        res = check.check([tsla()], c, state=self.STATE, now=at(NOW))
        self.assertIn("PDT: 3 Daytrades", reasons(res))
        self.assertEqual(res["today"]["day_trades_5d"], 3)
        self.assertEqual(verdicts(check.check([tsla()], cfg(), state=self.STATE, now=at(NOW))), ["PASS"])

    def test_german_brokers_get_a_note_instead(self):
        c = cfg(broker="manuell")
        c.pop("pdt_guard")
        res = check.check([tsla()], c, state=self.STATE, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("nicht bei deutschen Brokern", " ".join(res["notes"]))
        self.assertIsNone(res["today"]["day_trades_5d"])
        res = check.check([tsla()], cfg(broker="manuell", pdt_guard=True), state=self.STATE, now=at(NOW))
        self.assertIn("PDT: 3 Daytrades", reasons(res))

    def test_never_on_xetra(self):
        st = {"orders": [dict(r, symbol="SAP.DE", day=r["date"].replace("-10-1", "-10-2"),
                              date=r["date"].replace("-10-1", "-10-2")) for r in self.STATE["orders"]]}
        res = check.check([sap_order()], example(pdt_guard=True), state=st, now=berlin("2026-10-27 09:20"))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("gilt nur für US-Werte bei US-Brokern", " ".join(res["notes"]))

    def test_the_cli_shows_the_note(self):
        with tempfile.TemporaryDirectory() as d:
            none = os.path.join(d, "none")
            c = write(d, "config.json", example(fx={"USD": 0.86}))
            buf = io.StringIO()
            with redirect_stdout(buf):
                check.main(["--orders", TSLA_PATH, "--config", c, "--portfolio", none, "--prices", none,
                            "--state", none, "--now", NOW, "--no-write"])
            self.assertIn("Hinweis: PDT:", buf.getvalue())


class Frequency(unittest.TestCase):
    def state(self, n, start=datetime.date(2026, 9, 21)):
        days = [start + datetime.timedelta(days=i % 26) for i in range(n)]
        return {"orders": [placed("F%d" % i, day=d.isoformat()) for i, d in enumerate(days)]}

    def test_warns_above_the_threshold_but_never_blocks(self):
        res = check.check([tsla()], cfg(trade_frequency_warning=40), state=self.state(41), now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        w = " ".join(res["warnings"])
        self.assertIn("Häufigkeit: 41 Einstiege in den letzten 30 Tagen", w)
        self.assertIn("gewerblicher Wertpapierhandel", w)
        self.assertIn("Steuerberatung", w)

    def test_quiet_at_or_under_it_and_for_old_trades(self):
        res = check.check([tsla()], cfg(trade_frequency_warning=40), state=self.state(40), now=at(NOW))
        self.assertNotIn("Häufigkeit", " ".join(res["warnings"]))
        old = self.state(60, start=datetime.date(2026, 8, 1))
        res = check.check([tsla()], cfg(trade_frequency_warning=40), state=old, now=at(NOW))
        self.assertNotIn("Häufigkeit", " ".join(res["warnings"]))
        res = check.check([tsla()], cfg(trade_frequency_warning=0), state=self.state(41), now=at(NOW))
        self.assertNotIn("Häufigkeit", " ".join(res["warnings"]))

    def test_default_threshold_is_40(self):
        res = check.check([tsla()], cfg(), state=self.state(41), now=at(NOW))
        self.assertIn("Häufigkeit", " ".join(res["warnings"]))


class Currency(unittest.TestCase):
    """EUR-Konto, US-Aktie: den Kurs nimmt check.py aus dem Order-Plan, sonst aus der Config."""

    def eur_order(self):
        with open(os.path.join(FIX, "dt-budget", "plan-tsla.json")) as fh:
            p = json.load(fh)
        return size.bracket_order(size.size_trade(p, example(), today=TODAY, fx=0.86))

    def test_an_eur_order_from_dt_budget_passes(self):
        res = check.check([self.eur_order()], example(), now=at(NOW))
        r = res["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual((r["fx"], r["value"], r["max_loss"], r["max_loss_instrument"]), (0.86, 2818.75, 48.77, 52.74))
        self.assertIn("Wechselkurs 0,8600 EUR je 1 USD (aus Plan)", r["info"])
        self.assertIn("max. Verlust 48,77 € (Limit 50 €)", " ".join(r["info"]))
        self.assertEqual(res["cash_after"], 2181.25)

    def test_no_rate_is_a_block(self):
        res = check.check([tsla()], example(), now=at(NOW))
        self.assertEqual(verdicts(res), ["BLOCK"])
        self.assertIn("Währung: TSLA notiert in USD, dein Konto ist in EUR", reasons(res))
        o = self.eur_order()
        o["plan"].pop("fx")
        self.assertIn("Währung:", reasons(check.check([o], example(), now=at(NOW))))

    def test_a_rate_from_the_config(self):
        res = check.check([tsla()], example(fx={"USD": 0.86}), now=at(NOW))
        r = res["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual((r["fx"], r["value"], r["max_loss"]), (0.86, 2505.56, 40.32))
        self.assertIn("(aus Config)", " ".join(r["info"]))

    def test_the_euro_limits_apply(self):
        o = self.eur_order()
        res = check.check([o], example(max_loss_per_trade=45), now=at(NOW))
        self.assertIn("Verlust: 9 Aktien × 5,86 Risiko je Aktie + 0,05 % Spread-Puffer bei 0,8600 EUR/USD + 2 € "
                      "Gebühren = 48,77 € am Stop, über deinem max. Verlust je Trade von 45 €", reasons(res))
        res = check.check([o], example(max_order=2500), now=at(NOW))
        self.assertIn("Größe: 2.818,75 € liegt über deiner max. Order von 2.500 €", reasons(res))

    def test_the_plan_max_loss_counts_when_it_matches_the_order(self):
        p = dict(tsla()["plan"], max_loss=55.0)
        res = check.check([tsla(plan=p)], cfg(), now=at(NOW))
        self.assertEqual(res["results"][0]["max_loss"], 55.0)
        self.assertIn("= 55 $ am Stop", reasons(res))
        res = check.check([tsla(plan=p, qty="4")], cfg(), now=at(NOW))
        self.assertEqual((verdicts(res), res["results"][0]["max_loss"]), (["PASS"], 23.44))

    def test_fees_in_the_plan_count(self):
        p = dict(tsla()["plan"], fees=2.0)
        p.pop("max_loss")
        r = check.check([tsla(plan=p)], cfg(), now=at(NOW))["results"][0]
        self.assertEqual((r["verdict"], r["max_loss"]), ("PASS", 48.88))

    def test_an_exit_without_a_rate_is_not_blocked(self):
        pf = {"cash": 2181.25, "positions": [{"ticker": "TSLA", "shares": 9, "lots": [{"cost": 2818.75}]}]}
        sell = {"symbol": "TSLA", "side": "sell", "qty": "9", "type": "market", "time_in_force": "day"}
        res = check.check([sell], example(), portfolio=pf, now=at("2026-10-19 15:58"))
        self.assertEqual((verdicts(res), res["results"][0]["kind"]), (["PASS"], "exit"))
        self.assertIn("Ausstieg, nicht gesperrt: Währung:", warnings(res))


class NeutralKeys(unittest.TestCase):
    def test_neutral_keys_work_and_mean_an_eur_account(self):
        neutral = {k.replace("_usd", ""): v for k, v in US_CFG.items()}
        self.assertEqual(verdicts(check.check([tsla()], neutral, now=at(NOW))), ["BLOCK"])   # EUR, kein Kurs
        neutral["account_currency"] = "USD"
        res = check.check([tsla()], neutral, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        res = check.check([tsla()], dict(neutral, max_loss_per_trade=40), now=at(NOW))
        self.assertIn("über deinem max. Verlust je Trade von 40 $", reasons(res))

    def test_the_users_old_key_beats_the_new_default(self):
        res = check.check([tsla(qty="9")], {"budget": 5000, "max_loss_per_trade_usd": 60, "broker": "alpaca"},
                          now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])


class Cli(unittest.TestCase):
    def test_prices_file_freshness(self):
        with tempfile.TemporaryDirectory() as d:
            pp = write(d, "prices.json", {"as_of": "2026-10-19T14:55:00Z", "prices": {"TSLA": 366.475},
                                          "detail": {"TSLA": {"time": "2026-10-19T14:52:13Z",
                                                              "fetched": "2026-10-19T14:55:00Z"}}})
            none = os.path.join(d, "none")
            c = write(d, "config.json", cfg())
            base = ["--orders", TSLA_PATH, "--config", c, "--portfolio", none, "--prices", pp,
                    "--state", none, "--no-write"]
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(check.main(base + ["--now", "2026-10-19 10:55"]), 1)
            self.assertIn("8 Aktien × 8,16 Risiko je Aktie = 65,28 $", buf.getvalue())
            self.assertIn("SPERRE   #1", buf.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(check.main(base + ["--now", "2026-10-19 11:30"]), 0)

    def test_v1_orders_with_a_v1_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "config.json", v1())
            none = os.path.join(d, "none")
            out = os.path.join(d, "state", "risk.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check.main(["--orders", V1_ORDERS_PATH, "--config", c, "--portfolio", none, "--prices", none,
                                   "--state", none, "--today", V1_TODAY, "--out", out])
            self.assertEqual(code, 0)
            self.assertIn("5 freigegeben, 0 gesperrt", buf.getvalue())
            with open(out) as fh:
                rec = json.load(fh)
            self.assertEqual(rec["date"], V1_TODAY)
            self.assertTrue(all(len(r["fingerprint"]) == 16 for r in rec["results"]))
            bad = write(d, "orders.json", {"orders": v1_orders() + [buy("AAPL", 100)]})
            with redirect_stdout(io.StringIO()):
                code = check.main(["--orders", bad, "--config", c, "--portfolio", none, "--prices", none,
                                   "--state", none, "--today", V1_TODAY, "--no-write"])
            self.assertEqual(code, 1)

    def test_xetra_now_is_berlin_time(self):
        with tempfile.TemporaryDirectory() as d:
            orders = write(d, "orders.json", {"orders": [sap_order()]})
            none = os.path.join(d, "none")
            base = ["--orders", orders, "--config", EXAMPLE_PATH, "--portfolio", none, "--prices", none,
                    "--state", none, "--no-write"]
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(check.main(base + ["--now", "2026-10-27 09:20"]), 0)
            self.assertIn("1 freigegeben, 0 gesperrt, Stand Di 27.10.2026 09:20 Uhr", buf.getvalue())
            self.assertIn("1.379,85 €", buf.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(check.main(base + ["--now", "2026-10-27 09:10"]), 1)
            markt.use("us")
            with redirect_stdout(io.StringIO()):
                check.main(base + ["--now", "2026-10-27 09:20"])
            self.assertEqual(markt.current(), "us")

    def test_errors_are_one_line(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", "/nonexistent.json", "--no-write"]), 1)
        self.assertIn("Order-Datei", err.getvalue())
        self.assertIn("nicht gefunden", err.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", TSLA_PATH, "--now", "noon", "--no-write"]), 1)
        self.assertIn("--now erwartet", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", TSLA_PATH, "--today", "monday", "--no-write"]), 1)
        self.assertIn("--today erwartet", err.getvalue())


if __name__ == "__main__":
    unittest.main()
