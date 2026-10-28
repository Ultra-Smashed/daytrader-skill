import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, SKILLS, FIX

size = load("dt-budget", "size")
markt = size.markt

CFG = os.path.join(SKILLS, "dt-budget", "config.example.json")
PLAN = os.path.join(FIX, "dt-budget", "plan-tsla.json")
SAP_PLAN = os.path.join(FIX, "dt-budget", "plan-sap.json")
EURUSD = os.path.join(FIX, "dt-budget", "yahoo-eurusd-2026-10-28.json")
TARGETS = os.path.join(SKILLS, "dt-budget", "targets.example.json")
TOP5 = os.path.join(FIX, "dt-budget", "berkshire-q2-2026-top5.json")
NOW = "2026-10-19 10:15"
TODAY = "2026-10-19"
SAP_TODAY = "2026-10-27"
REEL_V1 = {"AAPL": 1250, "AXP": 1119, "GOOGL": 823, "KO": 708, "BAC": 600}
PRICES = {"AAPL": 341.27, "AXP": 309.84, "GOOGL": 353.78, "KO": 90.11, "BAC": 53.96}
# the original pack's US config (v2 contract), key for key: USD account, *_usd keys
US_CFG = {
    "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_usd": 4000, "min_order_usd": 5,
    "max_loss_per_trade_usd": 50, "max_daily_loss_usd": 150, "max_trades_per_day": 3, "max_orders_per_day": 10,
    "min_reward_risk": 1.0, "require_stop": True,
    "no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55",
    "fractional": False, "broker": "alpaca", "paper": True, "blocked": [],
    "allow_options": False, "allow_margin": False, "allow_short": False, "pdt_guard": False,
    "sec_user_agent": "Your Name you@example.com",
}
# v1's rules, for the weights mode tests
V1 = {"budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 2000, "min_order_usd": 5,
      "fractional": True, "paper": True, "blocked": []}


def cfg(**over):
    c = dict(US_CFG)
    c.update(over)
    return c


def example(**over):
    with open(CFG) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def v1(**over):
    c = dict(V1)
    c.update(over)
    return c


def plan(**over):
    with open(PLAN) as fh:
        p = json.load(fh)
    p.update(over)
    return p


def sap(**over):
    with open(SAP_PLAN) as fh:
        p = json.load(fh)
    p.update(over)
    return p


def rows(path):
    with open(path) as fh:
        return size.parse_weights(json.load(fh))


def dollars(result):
    return {p["ticker"]: p["dollars"] for p in result["positions"]}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = size.main(argv)
    return code, out.getvalue(), err.getvalue()


def write(d, name, doc):
    p = os.path.join(d, name)
    with open(p, "w") as fh:
        json.dump(doc, fh)
    return p


def prices_doc(price, quote_time="2026-10-19T14:52:13Z"):
    return {"as_of": quote_time, "source": "yahoo", "prices": {"TSLA": price},
            "detail": {"TSLA": {"prev_close": 354.72, "time": quote_time, "source": "yahoo"}}}


class TheReel(unittest.TestCase):
    """5.000 $, 10 % Puffer, 50 $ max. Verlust, TSLA Risiko 5,86 -> 8 Aktien, 2.913,44 $, max. Verlust 46,88 $."""

    def test_tsla_is_8_shares_bound_by_the_max_loss(self):
        s = size.size_trade(plan(), cfg(), today=TODAY)
        self.assertEqual(s["qty"], 8)
        self.assertEqual(s["bound_by"], "max_loss")
        self.assertEqual(s["risk_per_share"], 5.86)
        self.assertEqual(s["cost"], 2913.44)
        self.assertEqual(s["max_loss"], 46.88)
        self.assertEqual(s["reward_risk"], 1.0)
        self.assertEqual(s["cash_buffer"], 500)
        self.assertEqual((s["account_currency"], s["currency"], s["market"], s["fx"]), ("USD", "USD", "us", 1.0))
        self.assertEqual([(l["key"], l["shares"]) for l in s["limits"]],
                         [("max_loss", 8), ("position_cap", 10), ("max_order", 10), ("cash", 12)])
        self.assertEqual([l["name"] for l in s["limits"] if l["binds"]], ["max. Verlust"])
        self.assertIsNone(s["refusal"])

    def test_the_bracket_order(self):
        o = size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY))
        why = o.pop("why")
        self.assertEqual(o, {
            "symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32",
            "plan": {"entry": 364.18, "stop": 358.32, "target": 370.04, "risk_per_share": 5.86,
                     "max_loss": 46.88, "setup": "orb", "entry_time": "10:15 AM", "flat_by": "15:55",
                     "market": "us", "currency": "USD", "account_currency": "USD", "fx": 1.0, "fees": 0.0,
                     "spread_buffer_pct": 0.0, "max_loss_instrument": 46.88}})
        self.assertEqual(why, "Opening-Range-Ausbruch bei TSLA: 8 Aktien, begrenzt durch deinen max. Verlust je "
                              "Trade von 50 $ (8 × 5,86 = 46,88 $ am Stop)")

    def test_the_fixture_orders_file_is_what_it_writes(self):
        with open(os.path.join(FIX, "dt-risiko", "orders-tsla.json")) as fh:
            fixture = json.load(fh)["orders"][0]
        self.assertEqual(size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY)), fixture)

    def test_a_limit_order(self):
        o = size.bracket_order(size.size_trade(plan(), cfg(), limit=364.18, today=TODAY))
        self.assertEqual((o["type"], o["limit_price"], o["qty"]), ("limit", "364.18", "8"))
        s = size.size_trade(plan(), cfg(), limit=364.00, today=TODAY)
        self.assertEqual((s["risk_per_share"], s["qty"], s["max_loss"]), (5.68, 8, 45.44))
        self.assertEqual(size.bracket_order(s)["limit_price"], "364.00")

    def test_cli_writes_one_bracket_order(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "config.json", cfg())
            out = os.path.join(d, "trader", "orders.json")
            code, text, _ = run(["--plan", PLAN, "--config", c, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("Größe: 8 Aktien TSLA = 2.913,44 $ zu 364,18", text)
            self.assertIn("8 × 5,86 = 46,88 $", text)
            self.assertIn("<- greift", text)
            self.assertIn("Glatt bis 15:55 ET (21:55 Uhr)", text)
            self.assertIn("keine Anlageberatung", text)
            self.assertNotIn("Neobroker", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual(doc["created_by"], "dt-budget")
            self.assertEqual(doc["status"], "proposed")
            self.assertIs(doc["paper"], True)
            self.assertEqual(doc["created_at"], "2026-10-19T14:15:00Z")
            self.assertEqual(len(doc["orders"]), 1)
            self.assertEqual(doc["orders"][0]["plan"]["max_loss"], 46.88)

    def test_cli_json_and_limit(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "config.json", cfg())
            code, text, _ = run(["--plan", PLAN, "--config", c, "--portfolio", "/nonexistent", "--now", NOW,
                                 "--limit", "--json"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual(out["sizing"]["qty"], 8)
        self.assertEqual(out["orders"][0]["limit_price"], "364.18")


class PlanRules(unittest.TestCase):
    def test_zero_shares_is_a_plain_refusal(self):
        s = size.size_trade(plan(stop=300.0), cfg(), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("mehr als dein max. Verlust je Trade von 50 $", s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        with tempfile.TemporaryDirectory() as d:
            p = write(d, "plan.json", plan(stop=300.0))
            c = write(d, "config.json", cfg())
            out = os.path.join(d, "orders.json")
            code, text, _ = run(["--plan", p, "--config", c, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 1)
            self.assertIn("Keine Order:", text)
            self.assertFalse(os.path.exists(out))

    def test_each_limit_can_bind(self):
        self.assertEqual(size.size_trade(plan(), cfg(max_order_usd=1000), today=TODAY)["bound_by"], "max_order")
        s = size.size_trade(plan(), cfg(max_position_pct=20), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"]), (2, "position_cap"))
        s = size.size_trade(plan(), cfg(), cash=1200, today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"], s["cash_available"]), (1, "cash", 700))
        s = size.size_trade(plan(), cfg(max_loss_per_trade_usd=100), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"]), (10, "position_cap"))

    def test_a_fresh_higher_price_means_a_bigger_risk(self):
        s = size.size_trade(plan(), cfg(min_reward_risk=0), price=366.475, today=TODAY)
        self.assertEqual((s["entry"], s["entry_from"], s["risk_per_share"]), (366.48, "price", 8.16))
        self.assertEqual((s["qty"], s["max_loss"], s["reward_risk"]), (6, 48.96, 0.44))
        self.assertIsNone(s["refusal"])
        s = size.size_trade(plan(), cfg(), price=366.475, today=TODAY)
        self.assertIn("Chance/Risiko 0,44 (Ziel 370,04, Einstieg 366,48, Stop 358,32) liegt unter deinem Minimum 1",
                      s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        lower = size.size_trade(plan(), cfg(), price=363.00, today=TODAY)
        self.assertEqual((lower["entry"], lower["qty"]), (364.18, 8))

    def test_prices_file_is_used_only_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            pp = write(d, "prices.json", prices_doc(366.475))
            c = write(d, "config.json", cfg())
            base = ["--plan", PLAN, "--config", c, "--portfolio", os.path.join(d, "none"), "--prices", pp, "--json"]
            code, text, _ = run(base + ["--now", "2026-10-19 10:55"])
            out = json.loads(text)
            self.assertEqual((code, out["sizing"]["qty"], out["orders"]), (1, 6, []))
            self.assertIn("über dem Einstieg laut Plan", out["notes"][0])
            self.assertIn("10:52 ET", out["notes"][0])
            out = json.loads(run(base + ["--now", "2026-10-19 11:30"])[1])
            self.assertEqual(out["sizing"]["qty"], 8)
            self.assertIn("nicht verwendet", out["notes"][0])

    def test_the_portfolio_cash_caps_the_size(self):
        with tempfile.TemporaryDirectory() as d:
            pf = write(d, "portfolio.json", {"cash": 1200, "positions": []})
            c = write(d, "config.json", cfg())
            out = json.loads(run(["--plan", PLAN, "--config", c, "--portfolio", pf, "--now", NOW, "--json"])[1])
            self.assertEqual((out["sizing"]["qty"], out["sizing"]["bound_by"]), (1, "cash"))

    def test_bad_plans(self):
        for p, word in ((plan(stop=365.0), "nicht unter dem Einstieg"),
                        (plan(target=360.0), "schon gelaufen"),
                        (plan(target=None), "positiven Ziel"),
                        (plan(side="sell"), "nur Kauf-Daytrades"),
                        (plan(symbol=""), "kein Symbol")):
            with self.assertRaises(size.SizeError) as e:
                size.size_trade(p, cfg(), today=TODAY)
            self.assertIn(word, str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), price=371.00, today=TODAY)
        self.assertIn("schon gelaufen", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(blocked=["tsla"]), today=TODAY)
        self.assertIn("Sperrliste", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), today="2026-10-20")
        self.assertIn("neuen Plan", str(e.exception))

    def test_under_the_minimum_order(self):
        cheap = plan(symbol="ABC", entry=4.0, stop=3.0, target=5.0)
        s = size.size_trade(cheap, cfg(max_loss_per_trade_usd=1), today=TODAY)
        self.assertEqual(s["qty"], 1)
        self.assertIn("unter deiner Mindestorder von 5 $", s["refusal"])
        self.assertIsNone(size.bracket_order(s))

    def test_missing_plan_and_weights_only_flags(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "config.json", cfg())
            code, _, err = run(["--plan", "/nonexistent/plan.json", "--config", c, "--now", NOW])
            self.assertEqual(code, 1)
            self.assertIn("Plan nicht gefunden", err)
            code, _, err = run(["--plan", PLAN, "--config", c, "--now", NOW, "--top", "2"])
            self.assertEqual(code, 1)
            self.assertIn("--weights", err)
            code, _, err = run(["--plan", PLAN, "--config", c, "--now", "tomorrow"])
            self.assertEqual(code, 1)
            self.assertIn("--now erwartet", err)
            self.assertNotIn("Traceback", err)

    def test_today_is_the_new_york_date(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "config.json", cfg())
            base = ["--plan", PLAN, "--config", c, "--portfolio", os.path.join(d, "none"), "--json"]
            self.assertEqual(run(base + ["--now", "2026-10-20T02:00:00Z"])[0], 0)   # 22:00 ET am 19.10.
            code, _, err = run(base + ["--now", "2026-10-20T05:00:00Z"])          # 01:00 ET am 20.10.
            self.assertEqual(code, 1)
            self.assertIn("heute ist 2026-10-20", err)


class FeesAndSpread(unittest.TestCase):
    """fee_per_order zählt zweimal (Kauf und Verkauf), spread_buffer_pct erhöht das Risiko je Aktie."""

    def test_defaults_leave_the_us_numbers_alone(self):
        s = size.size_trade(plan(), cfg(), today=TODAY)
        self.assertEqual((s["fees"], s["spread_buffer_pct"], s["max_loss"]), (0.0, 0.0, 46.88))

    def test_fees_count_twice(self):
        s = size.size_trade(plan(), cfg(fee_per_order=1), today=TODAY)
        self.assertEqual((s["qty"], s["fees"], s["max_loss"], s["max_loss_instrument"]), (8, 2.0, 48.88, 46.88))
        s = size.size_trade(plan(), cfg(fee_per_order=3), today=TODAY)       # (50 - 6) / 5,86 = 7,5
        self.assertEqual((s["qty"], s["max_loss"]), (7, 47.02))
        self.assertIn("(50 $ max. Verlust - 6 $ Gebühren) / 5,86 $ Risiko je Aktie", s["limits"][0]["how"])
        why = size.bracket_order(s)["why"]
        self.assertIn("7 × 5,86 + 6 $ Gebühren = 47,02 $ am Stop", why)

    def test_fees_as_high_as_the_max_loss(self):
        s = size.size_trade(plan(), cfg(fee_per_order=25), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("Gebühren von 50 $", s["refusal"])

    def test_the_spread_buffer(self):
        s = size.size_trade(plan(), cfg(spread_buffer_pct=0.05), today=TODAY)   # 5,86 + 0,1821 = 6,0421
        self.assertEqual((s["qty"], s["max_loss"], s["spread_per_share"]), (8, 48.34, 0.1821))
        s = size.size_trade(plan(), cfg(spread_buffer_pct=0.5), today=TODAY)    # 5,86 + 1,8209 = 7,6809
        self.assertEqual((s["qty"], s["max_loss"], s["max_loss_instrument"]), (6, 46.09, 35.16))

    def test_fees_also_come_out_of_the_cash(self):
        s = size.size_trade(plan(), cfg(fee_per_order=1, max_loss_per_trade_usd=0, max_position_pct=0,
                                        max_order_usd=0), cash=864.36, today=TODAY)
        # 864,36 - 500 Puffer = 364,36; minus 1 $ Gebühr bleibt weniger als eine Aktie zu 364,18
        self.assertEqual((s["qty"], s["bound_by"]), (0, "cash"))


class Currency(unittest.TestCase):
    """EUR-Konto, US-Aktie: Limits in EUR, Preise in USD, fx = EUR je 1 USD."""

    def eur(self, **over):
        return example(**over)

    def test_fx_from_the_config(self):
        s = size.size_trade(plan(), self.eur(fx={"USD": 0.86}), today=TODAY)
        self.assertEqual((s["account_currency"], s["currency"], s["fx"]), ("EUR", "USD", 0.86))
        self.assertEqual((s["qty"], s["bound_by"]), (9, "max_loss"))
        self.assertEqual((s["cost"], s["cost_instrument"]), (2818.75, 3277.62))
        self.assertEqual((s["max_loss"], s["max_loss_instrument"], s["fees"]), (48.77, 52.74, 2.0))
        self.assertEqual(s["risk_per_share_account"], 5.1962)
        self.assertEqual([(l["key"], l["shares"]) for l in s["limits"]],
                         [("max_loss", 9), ("position_cap", 11), ("max_order", 12), ("cash", 14)])
        o = size.bracket_order(s)
        self.assertEqual({k: o["plan"][k] for k in ("market", "currency", "account_currency", "fx", "fees",
                                                    "spread_buffer_pct", "max_loss", "max_loss_instrument")},
                         {"market": "us", "currency": "USD", "account_currency": "EUR", "fx": 0.86, "fees": 2.0,
                          "spread_buffer_pct": 0.05, "max_loss": 48.77, "max_loss_instrument": 52.74})
        self.assertIn("deinen max. Verlust je Trade von 50 €", o["why"])
        self.assertIn("9 × 5,1962 € + 2 € Gebühren = 48,77 € am Stop", o["why"])

    def test_no_rate_is_a_refusal(self):
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), self.eur(), today=TODAY)
        self.assertIn("es fehlt ein Wechselkurs", str(e.exception))
        self.assertIn("Ohne Kurs keine Order", str(e.exception))

    def test_an_explicit_rate_wins(self):
        s = size.size_trade(plan(), self.eur(fx={"USD": 0.5}), today=TODAY, fx=0.86)
        self.assertEqual((s["fx"], s["qty"]), (0.86, 9))

    def test_cli_fx_flag_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            none = os.path.join(d, "none")
            code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", none, "--now", NOW, "--fx", "0,86"])
            self.assertEqual(code, 0)
            self.assertIn("Wechselkurs 0,8600 €/$ (EUR je 1 USD), Quelle: deine Angabe (--fx)", text)
            self.assertIn("5,86 $ (Einstieg 364,18 minus Stop 358,32) plus Spread-Puffer 0,05 % vom Einstieg "
                          "(0,1821 $) = 6,0421 $ = 5,1962 € bei 0,8600 €/$", text)
            self.assertIn("Gebühren: 2 × 1,00 € (Kauf und Verkauf) = 2,00 €", text)
            self.assertIn("Größe: 9 Aktien TSLA = 3.277,62 $ (2.818,75 €) zu 364,18", text)
            self.assertIn("Neobroker", text)
            self.assertIn("/dt-broker", text)

    def test_cli_offline_without_a_rate(self):
        code, _, err = run(["--plan", PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--now", NOW, "--offline"])
        self.assertEqual(code, 1)
        self.assertIn("TSLA notiert in USD, dein Konto ist in EUR", err)

    def test_yahoo_eurusd(self):
        with open(EURUSD) as fh:
            doc = json.load(fh)
        fx = size.fx_from_yahoo_doc(doc, "USD", "EUR")          # 1,1128 $ je € am 28.10.2026
        self.assertAlmostEqual(fx["rate"], 1 / 1.1128, places=10)
        self.assertEqual(fx["time"], "2026-10-28T09:10:43Z")
        self.assertIn("Yahoo EURUSD=X 1,1128 $ je 1 €", fx["source"])
        self.assertIn("Mi 28.10.2026 10:10 Uhr", fx["source"])
        self.assertAlmostEqual(size.fx_from_yahoo_doc(doc, "EUR", "USD")["rate"], 1.1128)
        with self.assertRaises(size.SizeError):
            size.fx_from_yahoo_doc({"chart": {"result": []}}, "USD", "EUR")

    def test_cli_fetches_eurusd_only_when_needed(self):
        with open(EURUSD) as fh:
            doc = json.load(fh)
        calls = []

        def fake(inst, acct, timeout=10):
            calls.append((inst, acct))
            return size.fx_from_yahoo_doc(doc, inst, acct)
        real = size.fetch_fx
        size.fetch_fx = fake
        try:
            code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--now", NOW,
                                 "--json"])
            out = json.loads(text)
            self.assertEqual((code, calls), (0, [("USD", "EUR")]))
            self.assertAlmostEqual(out["orders"][0]["plan"]["fx"], 1 / 1.1128)
            self.assertIn("Yahoo EURUSD=X", out["sizing"]["fx_source"])
            with tempfile.TemporaryDirectory() as d:
                c = write(d, "config.json", example(fx={"USD": 0.86}))
                run(["--plan", PLAN, "--config", c, "--portfolio", "/nonexistent", "--now", NOW])
                run(["--plan", SAP_PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--now", "2026-10-27 09:20"])
            self.assertEqual(len(calls), 1)
        finally:
            size.fetch_fx = real


class Xetra(unittest.TestCase):
    """SAP.DE, Beispielplan aus echten 5-Minuten-Kerzen vom 27.10.2026 (Fixture plan-sap.json)."""

    def test_sap_with_the_example_config(self):
        s = size.size_trade(sap(), example(), today=SAP_TODAY)
        self.assertEqual((s["market"], s["currency"], s["account_currency"], s["fx"]), ("xetra", "EUR", "EUR", 1.0))
        # Risiko 1,25 + 0,05 % von 212,95 = 1,3565 €; (50 - 2) / 1,3565 = 35; Positionslimit 3.750 / 212,95 = 17
        self.assertEqual([(l["key"], l["shares"]) for l in s["limits"]],
                         [("max_loss", 35), ("position_cap", 17), ("max_order", 18), ("cash", 21)])
        self.assertEqual((s["qty"], s["bound_by"], s["cost"]), (17, "position_cap", 3620.15))
        self.assertEqual((s["max_loss"], s["max_loss_instrument"]), (25.06, 21.25))
        o = size.bracket_order(s)
        self.assertEqual((o["symbol"], o["qty"], o["stop_loss_stop_price"], o["take_profit_limit_price"]),
                         ("SAP.DE", "17", "211.70", "214.20"))
        self.assertIn("begrenzt durch dein Positionslimit", o["why"])
        self.assertEqual(o["plan"]["flat_by"], "17:25")

    def test_the_flat_by_comes_from_the_market(self):
        s = size.size_trade(sap(flat_by=None, market=None, currency=None), example(), today=SAP_TODAY)
        self.assertEqual((s["market"], s["currency"], s["flat_by"]), ("xetra", "EUR", "17:25"))
        s = size.size_trade(sap(flat_by=None), example(zeiten={"xetra": {"flat_by": "17:20"}}), today=SAP_TODAY)
        self.assertEqual(s["flat_by"], "17:20")

    def test_today_is_the_berlin_date_in_winter_time(self):
        base = ["--plan", SAP_PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--json"]
        code, text, _ = run(base + ["--now", "2026-10-27 09:20"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["sizing"]["qty"], 17)
        self.assertEqual(run(base + ["--now", "2026-10-26T23:30:00Z"])[0], 0)       # 00:30 Uhr am 27.10.
        code, _, err = run(base + ["--now", "2026-10-27T23:30:00Z"])                 # 00:30 Uhr am 28.10.
        self.assertEqual(code, 1)
        self.assertIn("heute ist 2026-10-28 (deutscher Zeit)", err)

    def test_cli_report(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "orders.json")
            code, text, _ = run(["--plan", SAP_PLAN, "--config", CFG, "--portfolio", os.path.join(d, "none"),
                                 "--now", "2026-10-27 09:20", "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("Markt XETRA, Aktie in EUR, Konto in EUR.", text)
            self.assertNotIn("Wechselkurs", text)
            self.assertIn("Größe: 17 Aktien SAP.DE = 3.620,15 € zu 212,95", text)
            self.assertIn("17 × 1,3565 € + 2 € Gebühren = 25,06 €", text)
            self.assertIn("Glatt bis 17:25 Uhr", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual(doc["account_currency"], "EUR")
            self.assertEqual(doc["orders"][0]["plan"]["market"], "xetra")


class NeutralKeys(unittest.TestCase):
    def test_neutral_and_old_keys_give_the_same_size(self):
        neutral = {k.replace("_usd", ""): v for k, v in US_CFG.items()}
        neutral["account_currency"] = "USD"
        a = size.size_trade(plan(), neutral, today=TODAY)
        b = size.size_trade(plan(), cfg(), today=TODAY)
        self.assertEqual((a["qty"], a["max_loss"], a["cost"]), (b["qty"], b["max_loss"], b["cost"]))

    def test_the_users_value_beats_the_default(self):
        s = size.size_trade(plan(), {"budget": 5000, "account_currency": "USD", "max_loss_per_trade": 30},
                            today=TODAY)
        self.assertEqual((s["qty"], s["max_loss"]), (5, 29.3))
        s = size.size_trade(plan(), {"budget": 5000, "max_loss_per_trade_usd": 30}, today=TODAY)
        self.assertEqual((s["account_currency"], s["qty"]), ("USD", 5))

    def test_the_example_config_has_the_new_keys(self):
        c = example()
        self.assertEqual((c["market"], c["account_currency"], c["broker"]), ("xetra", "EUR", "manuell"))
        for k in ("max_loss_per_trade", "max_daily_loss", "max_order", "min_order", "fee_per_order",
                  "spread_buffer_pct", "fx", "zeiten", "trade_frequency_warning"):
            self.assertIn(k, c)
        self.assertFalse([k for k in c if k.endswith("_usd")])
        self.assertIs(c["paper"], True)


class WeightsMode(unittest.TestCase):
    """v1's Aufteilung hinter --weights / --targets: 5.000 $, 10 % Cash, 25 % Deckel."""

    def check_reel(self, r):
        self.assertEqual(dollars(r), REEL_V1)
        self.assertEqual(r["cash_buffer"], 500)
        self.assertEqual(r["invested"], 4500)
        self.assertEqual(r["idle"], 0)
        self.assertEqual(r["cap"], 1250)
        self.assertEqual([p["ticker"] for p in r["positions"] if p["capped"]], ["AAPL"])

    def test_from_the_raw_weights(self):
        self.check_reel(size.size(rows(TOP5), v1()))

    def test_from_the_renormalised_weights_file(self):
        self.check_reel(size.size(rows(TARGETS), v1()))

    def test_from_inline_weights(self):
        w = size.parse_weights(size.weights_from_arg("AAPL=22.04,AXP=17.14,GOOGL=12.62,KO=10.86,BAC=9.20"))
        self.check_reel(size.size(w, v1()))

    def test_renormalised_weights(self):
        r = size.size(rows(TOP5), v1())
        shown = {p["ticker"]: round(p["weight"], 1) for p in r["positions"]}
        self.assertEqual(shown, {"AAPL": 30.7, "AXP": 23.9, "GOOGL": 17.6, "KO": 15.1, "BAC": 12.8})

    def test_one_decimal_weights_stay_within_a_dollar(self):
        w = size.parse_weights({"AAPL": 30.7, "AXP": 23.9, "GOOGL": 17.6, "KO": 15.1, "BAC": 12.8})
        r = size.size(w, v1())
        self.assertEqual(r["invested"], 4500)
        self.assertEqual(dollars(r)["AAPL"], 1250)
        for t, v in dollars(r).items():
            self.assertLessEqual(abs(v - REEL_V1[t]), 1.0, t)

    def test_orders_are_place_stock_order_shaped(self):
        r = size.size(rows(TOP5), v1())
        orders = size.orders_from(r, "a 13F")
        self.assertEqual(orders[0], {"symbol": "AAPL", "side": "buy", "notional": "1250", "type": "market",
                                     "time_in_force": "day", "why": orders[0]["why"]})
        self.assertIn("gedeckelt bei 25 %", orders[0]["why"])
        self.assertIn("5.000 $", orders[0]["why"])
        for o in orders:
            self.assertIsInstance(o["notional"], str)
            self.assertNotIn("qty", o)
        self.assertEqual([o["notional"] for o in orders], ["1250", "1119", "823", "708", "600"])

    def test_cents_mode_keeps_the_total(self):
        r = size.size(rows(TOP5), v1(), cents=True)
        d = dollars(r)
        self.assertEqual(d["AAPL"], 1250)
        self.assertAlmostEqual(sum(d.values()), 4500, places=2)
        self.assertAlmostEqual(d["AXP"], 1118.13, places=2)
        self.assertEqual(size.orders_from(r)[1]["notional"], "1118.13")

    def test_cap_redistributes_until_nobody_is_over(self):
        w = size.parse_weights({"A": 60, "B": 30, "C": 10})
        r = size.size(w, {"budget": 1000, "cash_buffer_pct": 0, "max_position_pct": 40, "min_order_usd": 1})
        self.assertEqual(dollars(r), {"A": 400, "B": 400, "C": 200})
        self.assertEqual(sorted(p["ticker"] for p in r["positions"] if p["capped"]), ["A", "B"])

    def test_everything_capped_leaves_money_idle(self):
        w = size.parse_weights({"AAPL": 50, "KO": 50})
        r = size.size(w, v1())
        self.assertEqual(dollars(r), {"AAPL": 1250, "KO": 1250})
        self.assertEqual(r["idle"], 2000)
        self.assertIn("jeder Wert ist am Deckel", size.report(r, size.orders_from(r)))

    def test_slices_under_the_minimum_are_dropped_and_shared_out(self):
        w = size.parse_weights({"A": 90, "B": 7, "C": 3})
        r = size.size(w, {"budget": 100, "cash_buffer_pct": 10, "max_position_pct": 100, "min_order_usd": 5})
        self.assertNotIn("C", dollars(r))
        self.assertEqual(sum(dollars(r).values()), 90)
        self.assertTrue(all(v >= 5 for v in dollars(r).values()))
        self.assertEqual(r["dropped"][0]["ticker"], "C")
        self.assertIn("unter deiner Mindestorder", r["dropped"][0]["reason"])

    def test_blocked_tickers_are_dropped_first(self):
        r = size.size(rows(TOP5), v1(blocked=["ko"]))
        self.assertNotIn("KO", dollars(r))
        self.assertEqual(r["invested"], 4500)
        self.assertIn("Sperrliste", r["dropped"][0]["reason"])

    def test_top_n(self):
        r = size.size(rows(TOP5), v1(max_position_pct=100), top=2)
        self.assertEqual(sorted(dollars(r)), ["AAPL", "AXP"])

    def test_whole_shares_need_prices(self):
        with self.assertRaises(size.SizeError):
            size.size(rows(TOP5), v1(fractional=False))
        with self.assertRaises(size.SizeError):
            size.size(rows(TOP5), example())          # die Beispiel-Config rechnet in ganzen Aktien

    def test_whole_shares_with_prices(self):
        r = size.size(rows(TOP5), v1(fractional=False), prices=PRICES)
        self.assertTrue(r["whole_shares"])
        for p in r["positions"]:
            self.assertEqual(p["shares"], int(p["shares"]))
            self.assertAlmostEqual(p["dollars"], p["shares"] * PRICES[p["ticker"]], places=2)
            self.assertLessEqual(p["dollars"], 1250)
        self.assertAlmostEqual(r["invested"] + r["idle"], 4500, places=2)
        self.assertLess(r["idle"], min(PRICES.values()) * 2)
        orders = size.orders_from(r)
        self.assertTrue(all("qty" in o and "notional" not in o for o in orders))

    def test_no_budget_and_duplicates_are_errors(self):
        with self.assertRaises(size.SizeError):
            size.size(rows(TOP5), {"cash_buffer_pct": 10})
        with self.assertRaises(size.SizeError):
            size.size([{"ticker": "KO", "name": "", "weight": 1}, {"ticker": "KO", "name": "", "weight": 2}], v1())

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "config.json", v1())
            out = os.path.join(d, "trader", "orders.json")
            code, text, _ = run(["--targets", TARGETS, "--config", c, "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("bleibt liegen", text)
            self.assertIn("require_stop", text)
            self.assertIn("4.500,00 $", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual([o["symbol"] for o in doc["orders"]], ["AAPL", "AXP", "GOOGL", "KO", "BAC"])
            code, text, _ = run(["--targets", TARGETS, "--config", c, "--json"])
            self.assertEqual(json.loads(text)["result"]["idle"], 0)
            code, _, err = run(["--targets", "/nonexistent/targets.json", "--config", c])
            self.assertEqual(code, 1)
            self.assertIn("Gewichtsdatei nicht gefunden", err)

    def test_cli_with_an_eur_account_flags_foreign_stocks(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "config.json", example(fractional=True, max_position_pct=25, min_order=5))
            code, text, _ = run(["--targets", TARGETS, "--config", c])
            self.assertEqual(code, 0)
            self.assertIn("4.500,00 €", text)
            self.assertIn("notieren nicht in EUR", text)


class MarketIsRestored(unittest.TestCase):
    def test_main_leaves_the_global_market_alone(self):
        markt.use("us")
        run(["--plan", SAP_PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--now", "2026-10-27 09:20"])
        self.assertEqual(markt.current(), "us")


if __name__ == "__main__":
    unittest.main()
