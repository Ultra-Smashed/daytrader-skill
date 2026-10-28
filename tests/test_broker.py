import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, SKILLS, FIX

ticket = load("dt-broker", "ticket")
check = load("dt-risiko", "check")

CFG_PATH = os.path.join(SKILLS, "dt-budget", "config.example.json")
ORDERS_PATH = os.path.join(FIX, "dt-risiko", "orders-tsla.json")
SAP_PATH = os.path.join(FIX, "dt-broker", "orders-sap.json")
PLAN_PATH = os.path.join(FIX, "dt-budget", "plan-tsla.json")
NOW = "2026-10-19 10:15"
TODAY = "2026-10-19"
SAP_NOW = "2026-10-28 10:15"
SAP_TODAY = "2026-10-28"
AAPL = {"symbol": "AAPL", "side": "buy", "notional": "1250", "type": "market", "time_in_force": "day"}
BATCH = ["AAPL", "AXP", "GOOGL", "KO", "BAC"]
TSLA_CALL = {"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
             "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32"}
TSLA_PLAIN = ("KAUF 8 Stück TSLA, Market, gültig heute / Stop-Loss 358,32 $ / Take-Profit 370,04 $ / "
              "max. Verlust etwa 46,88 $, wenn der Stop bei 358,32 $ ausgeführt wird (in einem schnellen "
              "Markt kann es schlechter werden)")


def tsla(**over):
    with open(ORDERS_PATH) as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def sap(**over):
    with open(SAP_PATH, encoding="utf-8") as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ticket.main(argv)
    return code, out.getvalue(), err.getvalue()


def flat(text):
    return " ".join(text.split())


class ExplicitYes(unittest.TestCase):
    def yes(self, reply, order=AAPL, batch=BATCH):
        return ticket.parse_yes(reply, order, batch)[0]

    def test_plain_yes_counts(self):
        for r in ("yes", "Yes.", "YES", "y", "yes place it", "Yes, buy it", "yes AAPL", "yes $1,250 of AAPL",
                  "yes 1250"):
            self.assertTrue(self.yes(r), r)

    def test_anything_else_does_not(self):
        for r in ("", "sure", "ok", "okay", "go", "do it", "yeah", "yep", "absolutely", "send it",
                  "yes to all", "yes, all of them", "yes to the rest", "yes both",
                  "yes AXP", "yes 1000", "yes but make it 1000", "yes?", "no", "not yes",
                  "yes, wait", "yes if it is under 340"):
            self.assertFalse(self.yes(r), r)

    def test_amount_must_match_this_order(self):
        sell = {"symbol": "KO", "side": "sell", "qty": "3", "type": "market", "time_in_force": "day"}
        self.assertTrue(self.yes("yes sell 3 KO", sell))
        self.assertFalse(self.yes("yes sell 4", sell))

    def test_a_bracket_yes(self):
        o = tsla()
        for r in ("yes", "yes 8 TSLA", "yes 358.32", "yes max loss 46.88", "yes target 370.04"):
            self.assertTrue(self.yes(r, o, ["TSLA"]), r)
        for r in ("yes 9", "yes 10 TSLA", "yes but stop at 357", "yes, stop 358.32", "yes AAPL", "sure"):
            self.assertFalse(self.yes(r, o, ["TSLA", "AAPL"]), r)


class DeutschesJa(unittest.TestCase):
    def yes(self, reply, order=None, batch=("SAP.DE", "BMW.DE")):
        return ticket.parse_yes(reply, order or sap(), batch)[0]

    def test_ein_klares_ja_zaehlt(self):
        for r in ("ja", "Ja", "JA!", "ja, platzieren", "ja bitte", "Ja, kauf SAP", "ja SAP.DE",
                  "ja 17 Stück", "ja 214,90", "ja 32,70"):
            self.assertTrue(self.yes(r), r)

    def test_alles_zweideutige_ist_kein_ja(self):
        for r in ("vielleicht", "ja aber nur 5", "ok", "ok?", "okay", "klar", "passt", "mach", "jo", "jap",
                  "jawohl", "ja?", "ja zu allen", "ja, alle", "ja beide", "ja zu allem", "ja, wenn es unter 210 ist",
                  "ja, vielleicht", "ja, aber warte", "ja BMW", "ja BMW.DE", "ja 18 Stück", "ja nur heute",
                  "nein", "nicht ja", "ja, später", "ja, Stop 209,50"):
            self.assertFalse(self.yes(r), r)

    def test_deutsche_und_englische_zahlen(self):
        o = sap()
        self.assertTrue(self.yes("ja 209,50", o))
        self.assertTrue(self.yes("ja 209.50", o))
        self.assertFalse(self.yes("ja 209,40", o))
        self.assertTrue(ticket.parse_yes("ja 1.250", AAPL, BATCH)[0])

    def test_nein_erkennen(self):
        for r in ("nein", "Nein danke", "no", "nö", "nee, lass mal"):
            self.assertTrue(ticket.is_no(r), r)
        for r in ("ja", "nicht jetzt", "vielleicht"):
            self.assertFalse(ticket.is_no(r), r)


class TicketShape(unittest.TestCase):
    def test_tool_input_is_the_alpaca_call(self):
        o = dict(AAPL, why="aus einer Liste")
        self.assertEqual(ticket.tool_input(o), AAPL)
        self.assertEqual(ticket.tool_input({"symbol": "KO", "side": "buy", "qty": 3, "type": "limit",
                                            "limit_price": 89.5, "time_in_force": "day"}),
                         {"symbol": "KO", "side": "buy", "qty": "3", "type": "limit", "limit_price": "89.5",
                          "time_in_force": "day"})

    def test_the_bracket_call_leaves_out_why_and_plan(self):
        self.assertEqual(ticket.tool_input(tsla()), TSLA_CALL)
        self.assertEqual(ticket.fingerprint(tsla()), ticket.fingerprint(TSLA_CALL))
        self.assertNotIn("isin", ticket.tool_input(sap()))
        self.assertEqual(ticket.fingerprint(sap()), check.fingerprint(sap()))

    def test_plain_german(self):
        self.assertEqual(ticket.plain(AAPL), "KAUF AAPL für 1.250 $, Market-Order, gültig heute")
        self.assertEqual(ticket.plain({"symbol": "KO", "side": "sell", "qty": "1", "type": "limit",
                                       "limit_price": "95", "time_in_force": "gtc"}),
                         "VERKAUF 1 Stück KO, Limit-Order zu 95,00 $, gültig bis auf Widerruf")
        self.assertEqual(ticket.plain(tsla()), TSLA_PLAIN)
        lim = tsla(type="limit", limit_price="364.00")
        self.assertEqual(ticket.plain(lim).split(" / ")[0], "KAUF 8 Stück TSLA, Limit 364,00 $, gültig heute")
        self.assertEqual(ticket.max_loss(lim), (45.44, 358.32))
        no_plan = dict(TSLA_CALL)
        self.assertEqual(ticket.max_loss(no_plan), (None, 358.32))

    def test_xetra_ticket_in_euro(self):
        parts = ticket.plain_parts(sap(), {"account_currency": "EUR"})
        self.assertEqual(parts[0], "KAUF 17 Stück SAP.DE, Market, gültig heute")
        self.assertEqual(parts[1], "Stop-Loss 209,50 €")
        self.assertEqual(parts[2], "Take-Profit 214,90 €")
        self.assertIn("max. Verlust etwa 32,70 € (inkl. Gebühren)", parts[3])
        self.assertEqual(ticket.max_loss(sap()), (32.7, 209.5))

    def test_account_currency_with_fx(self):
        o = tsla()
        o["plan"] = dict(o["plan"], max_loss=42.32, account_currency="EUR", fx=0.86, fees=2.0)
        cfg = {"account_currency": "EUR"}
        loss = ticket.plain_parts(o, cfg)[3]
        self.assertIn("max. Verlust etwa 46,88 $ (42,32 € in Kontowährung, inkl. Gebühren)", loss)
        del o["plan"]["max_loss_instrument"]
        self.assertIn("etwa 49,21 $ (42,32 € in Kontowährung", ticket.plain(o, cfg))
        self.assertEqual(ticket.recorded_loss(o, cfg), (42.32, "EUR"))
        self.assertTrue(ticket.parse_yes("ja 42,32", o, ["TSLA"], cfg)[0])
        usd_plan = {"account_currency": "EUR", "fx": {"USD": 0.8986}}
        self.assertIn("max. Verlust etwa 46,88 $ (42,13 € in Kontowährung), wenn", ticket.plain(tsla(), usd_plan))
        self.assertEqual(ticket.recorded_loss(tsla(), usd_plan), (42.13, "EUR"))
        self.assertIn("(etwa 1.075 €)", ticket.plain(AAPL, {"account_currency": "EUR", "fx": {"USD": 0.86}}))
        self.assertNotIn("etwa", ticket.plain(AAPL, {"account_currency": "USD", "fx": {"USD": 0.86}}))


class DesktopConfig(unittest.TestCase):
    def test_example_is_paper_with_placeholder_keys(self):
        with open(os.path.join(SKILLS, "dt-broker", "claude_desktop_config.example.json"), encoding="utf-8") as fh:
            server = json.load(fh)["mcpServers"]["alpaca"]
        self.assertEqual((server["command"], server["args"]), ("uvx", ["alpaca-mcp-server"]))
        self.assertEqual(server["env"]["ALPACA_PAPER_TRADE"], "true")
        for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
            self.assertIn("NIE_IM_CHAT", server["env"][k])


class Base(unittest.TestCase):
    orders_src = ORDERS_PATH
    now = NOW
    cfg_over = {}

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orders = os.path.join(self.d, "orders.json")
        shutil.copy(self.orders_src, self.orders)
        self.cfg = os.path.join(self.d, "config.json")
        with open(CFG_PATH, encoding="utf-8") as fh:
            c = json.load(fh)
        c.update(self.cfg_over)
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump(c, fh)
        self.risk = os.path.join(self.d, "state", "risk.json")
        self.state = os.path.join(self.d, "state", "broker.json")
        self.pf = os.path.join(self.d, "portfolio.json")
        self.none = os.path.join(self.d, "none")

    def tearDown(self):
        shutil.rmtree(self.d)

    def set_cfg(self, **kw):
        with open(self.cfg, encoding="utf-8") as fh:
            c = json.load(fh)
        c.update(kw)
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump(c, fh)

    def args(self, *extra, **kw):
        return list(extra) + ["--orders", self.orders, "--config", self.cfg, "--risk", self.risk,
                              "--state", self.state, "--now", kw.get("now", self.now)]

    def run_risk(self, now=None):
        with redirect_stdout(io.StringIO()):
            return check.main(["--orders", self.orders, "--config", self.cfg, "--portfolio", self.pf,
                               "--prices", self.none, "--state", self.state, "--now", now or self.now,
                               "--out", self.risk])

    def state_doc(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)


class Flow(Base):
    cfg_over = {"broker": "alpaca", "account_currency": "USD"}

    def test_nothing_is_ready_before_the_risk_check(self):
        code, text, _ = run(self.args("show"))
        self.assertEqual(code, 1)
        self.assertIn("NICHT BEREIT", text)
        self.assertNotIn("Antworte „ja“", text)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "ja"))
        self.assertEqual(code, 1)
        self.assertIn("nicht bereit", err)

    def test_the_full_two_yes_flow(self):
        self.assertEqual(self.run_risk(), 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 0)
        self.assertIn("ORDER 1 von 1, PAPIER-Konto, Alpaca", text)
        self.assertIn("Markt US (NYSE/Nasdaq), Kurse in USD, glatt bis 15:55 ET (21:55 Uhr)", text)
        for part in TSLA_PLAIN.split(" / "):
            self.assertIn("  " + part + "\n", text)
        self.assertIn("BEREIT: dt-risiko FREIGABE", text)
        self.assertIn('"order_class": "bracket"', text)
        self.assertIn('"stop_loss_stop_price": "358.32"', text)
        self.assertNotIn('"plan"', text)
        self.assertNotIn('"why"', text)
        self.assertIn("Allow once", text)

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "klar"))
        self.assertEqual(code, 1)
        self.assertIn("Nicht erfasst", text)
        self.assertFalse(os.path.exists(self.state))

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "ja"))
        self.assertEqual(code, 0)
        self.assertIn("place_stock_order", text)
        self.assertEqual(json.loads(text[text.index("{"):text.rindex("}") + 1]), TSLA_CALL)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "ja"))
        self.assertEqual(code, 1)
        self.assertIn("BESTÄTIGT", err)

        code, text, _ = run(self.args("result", "--index", "1", "--status", "placed", "--broker-id", "abc123",
                                      "--filled-qty", "8", "--filled-price", "364.20", "--portfolio", self.pf,
                                      now="2026-10-19 10:16"))
        self.assertEqual(code, 0)
        st = self.state_doc()
        self.assertEqual([r["status"] for r in st["orders"]], ["approved", "placed", "filled"])
        appr, plc = st["orders"][0], st["orders"][1]
        self.assertEqual((appr["reply"], appr["kind"], appr["max_loss"], appr["date"]), ("ja", "entry", 46.88, TODAY))
        self.assertEqual(appr["max_loss_currency"], "USD")
        self.assertEqual(appr["at"], "2026-10-19T10:15:00-04:00")
        self.assertEqual((plc["broker_order_id"], plc["max_loss"], plc["kind"]), ("abc123", 46.88, "entry"))
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 2086.4)
        self.assertEqual(pf["positions"][0]["shares"], 8)

        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("ERLEDIGT: platziert", text)
        code, text, _ = run(["log", "--state", self.state, "--now", NOW, "--market", "us"])
        self.assertIn("1 heute platziert", text)
        self.assertIn("max. Verlust 46,88 $", text)
        self.assertIn("19.10.2026 10:15 ET (16:15 Uhr)", text)

        now = ticket.markt.local_to_utc(datetime.datetime(2026, 10, 19, 10, 30), "us")
        res = check.check([tsla()], {"budget": 5000}, state=st, today=TODAY, now=now)
        self.assertEqual(res["results"][0]["verdict"], "BLOCK")
        self.assertEqual((res["today"]["entries_placed"], res["today"]["loss_at_risk"]), (1, 46.88))

    def test_flatten_by_the_close(self):
        self.run_risk()
        run(self.args("approve", "--index", "1", "--reply", "yes"))
        run(self.args("result", "--index", "1", "--status", "placed", "--broker-id", "abc",
                      "--filled-qty", "8", "--filled-price", "364.20", "--portfolio", self.pf))
        late = "2026-10-19 15:55"
        code, text, _ = run(["flatten", "--symbol", "TSLA", "--orders", self.orders, "--portfolio", self.pf,
                             "--plan", PLAN_PATH, "--config", self.cfg, "--now", late])
        self.assertEqual(code, 0)
        self.assertIn("Glattstellen TSLA bis 15:55 ET (21:55 Uhr): VERKAUF 8 Stück TSLA, Market-Order, "
                      "gültig heute.", text)
        self.assertIn("ersetzt 1 früheren Vorschlag", text)
        self.assertIn("cancel_order_by_id", text)
        with open(self.orders, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(ticket.tool_input(doc["orders"][0]),
                         {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market", "time_in_force": "day"})
        self.assertEqual(self.run_risk(now=late), 0)
        with open(self.risk) as fh:
            self.assertEqual(json.load(fh)["results"][0]["kind"], "exit")
        code, text, _ = run(self.args("show", now=late))
        self.assertEqual(code, 0)
        self.assertIn("BEREIT", text)
        self.assertEqual(run(self.args("approve", "--index", "1", "--reply", "ja, verkauf 8 TSLA", now=late))[0], 0)
        code, _, _ = run(self.args("result", "--index", "1", "--status", "placed", "--filled-qty", "8",
                                   "--filled-price", "366.10", "--portfolio", self.pf, now="2026-10-19 15:56"))
        self.assertEqual(code, 0)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual((pf["cash"], pf["positions"]), (5015.2, []))
        self.assertEqual(check.day_trades(self.state_doc(), TODAY)[0], 1)
        code, _, err = run(["flatten", "--symbol", "TSLA", "--orders", self.orders, "--portfolio", self.pf,
                            "--now", late])
        self.assertEqual(code, 1)
        self.assertIn("nichts glattzustellen", err)

    def test_flatten_with_the_broker_qty(self):
        code, text, _ = run(["flatten", "--symbol", "tsla", "--qty", "8", "--orders", self.orders,
                             "--portfolio", self.none, "--plan", self.none, "--config", self.cfg, "--now", NOW])
        self.assertEqual(code, 0)
        self.assertNotIn("Gleich sie", text)
        self.assertIn("bis 15:55 ET", text)
        self.assertEqual(run(["flatten", "--symbol", "TSLA", "--qty", "0", "--orders", self.orders])[0], 1)

    def test_an_edited_order_is_not_ready(self):
        self.run_risk()
        with open(self.orders) as fh:
            doc = json.load(fh)
        doc["orders"][0]["qty"] = "9"
        with open(self.orders, "w") as fh:
            json.dump(doc, fh)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 1)
        self.assertIn("war nicht in der letzten Risikoprüfung", text)

    def test_yesterdays_check_does_not_count(self):
        self.run_risk(now="2026-10-16 10:15")
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("nicht von heute", text)

    def test_blocked_orders_are_never_ready(self):
        self.assertEqual(self.run_risk(now="2026-10-19 09:40"), 1)
        with open(self.risk) as fh:
            self.assertEqual(json.load(fh)["results"][0]["verdict"], "BLOCK")
        code, text, _ = run(self.args("show", "--index", "1", now="2026-10-19 09:40"))
        self.assertIn("GESPERRT von dt-risiko: ", text)
        self.assertIn("09:45", text)
        code, _, _ = run(self.args("approve", "--index", "1", "--reply", "ja", now="2026-10-19 09:40"))
        self.assertEqual(code, 1)

    def test_result_needs_an_approval_and_decline_is_logged(self):
        self.run_risk()
        code, _, err = run(self.args("result", "--index", "1", "--status", "placed"))
        self.assertEqual(code, 1)
        self.assertIn("kein erfasstes „ja“", err)
        code, text, _ = run(self.args("decline", "--index", "1", "--reply", "nein danke"))
        self.assertEqual(code, 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("ERLEDIGT: abgelehnt", text)

    def test_a_no_in_approve_is_logged_as_declined(self):
        self.run_risk()
        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "Nein"))
        self.assertEqual(code, 1)
        self.assertIn("abgelehnt", text)
        self.assertEqual([(r["status"], r["reply"]) for r in self.state_doc()["orders"]], [("declined", "Nein")])
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "ja"))
        self.assertEqual(code, 1)
        self.assertIn("ERLEDIGT: abgelehnt", err)

    def test_ibkr_tickets_send_the_final_yes_to_ibkr(self):
        self.set_cfg(broker="ibkr")
        self.run_risk()
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("Interactive Brokers", text)
        self.assertIn("nachdem du sie dort freigegeben hast", text)
        self.assertNotIn("place_stock_order", text)

    def test_live_is_shouted(self):
        self.set_cfg(paper=False)
        code, text, _ = run(self.args("show"))
        self.assertIn("LIVE-KONTO, ECHTES GELD", text)
        self.assertIn("ACHTUNG LIVE", text)
        self.assertIn("Ein Stop ist keine Garantie", text)

    def test_paper_has_no_live_warning(self):
        code, text, _ = run(self.args("show"))
        self.assertNotIn("ACHTUNG LIVE", text)

    def test_unknown_broker_is_an_error(self):
        self.set_cfg(broker="robinhood")
        code, _, err = run(self.args("show"))
        self.assertEqual(code, 1)
        self.assertIn("unbekannter Broker", err)

    def test_fill_sell_relieves_the_oldest_lot(self):
        pf = {"cash": 0, "positions": [{"ticker": "KO", "shares": 3, "lots": [
            {"id": "KO-1", "date": "2025-01-02", "shares": 2, "cost": 120.0},
            {"id": "KO-2", "date": "2026-01-02", "shares": 1, "cost": 70.0}]}]}
        with open(self.pf, "w") as fh:
            json.dump(pf, fh)
        code, text, _ = run(["fill", "--symbol", "KO", "--side", "sell", "--qty", "2.5", "--price", "90",
                             "--date", TODAY, "--portfolio", self.pf, "--config", self.cfg, "--state", self.state])
        self.assertEqual(code, 0)
        self.assertIn("Verkauf 2.5 Stück KO zu 90,00 $ am 19.10.2026", text)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 225.0)
        lots = pf["positions"][0]["lots"]
        self.assertEqual([l["id"] for l in lots], ["KO-2"])
        self.assertEqual(lots[0]["shares"], 0.5)
        self.assertEqual(lots[0]["cost"], 35.0)
        self.assertEqual(self.state_doc()["orders"][-1]["status"], "filled")
        code, _, err = run(["fill", "--symbol", "KO", "--side", "sell", "--qty", "5", "--price", "90",
                            "--portfolio", self.pf, "--config", self.cfg, "--state", self.state])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)


class Manuell(Base):
    """Standard-Config (broker "manuell", Konto in EUR) mit dem XETRA-Beispiel SAP.DE."""
    orders_src = SAP_PATH
    now = SAP_NOW

    def test_xetra_ticket_before_and_after_the_check(self):
        code, text, _ = run(self.args("show"))
        self.assertEqual(code, 1)
        self.assertIn("NICHT BEREIT", text)
        self.assertNotIn("Klick", text)
        self.assertNotIn("Stückzahl 17", text)
        self.assertEqual(self.run_risk(), 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 0)
        self.assertIn("ORDER 1 von 1, PAPIER (nur im Demokonto oder auf Papier), manuell in deiner Broker-App", text)
        self.assertIn("Markt XETRA, Kurse in EUR, glatt bis 17:25 Uhr", text)
        self.assertIn("KAUF 17 Stück SAP.DE, Market, gültig heute", text)
        self.assertNotIn("place_stock_order", text)
        t = flat(text)
        self.assertIn("1. Wertpapier suchen: SAP SE (SAP.DE), ISIN DE0007164600. Handelsplatz XETRA.", t)
        self.assertIn("Kaufen wählen, Stückzahl 17.", t)
        self.assertIn("Orderart: Market (billigst, ohne Limit).", t)
        self.assertIn("Gültigkeit: nur heute", t)
        self.assertIn("etwa 17 × 211,20 € = 3.590,40 € plus Gebühren", t)
        self.assertIn("Stop-Loss-Order, Verkauf 17 Stück, Orderart Stop (Stop-Market), Stop-Kurs 209,50 €", t)
        self.assertIn("Take-Profit-Order: Verkauf 17 Stück, Orderart Limit, Limit 214,90 €", t)
        self.assertIn("keine Bracket- oder OCO-Orders", t)
        self.assertIn("Dann setz nur den Stop beim Broker und lass das Ziel 214,90 € per /dt-alarm beobachten", t)
        self.assertIn("PAPIER: Führe sie nur im Demokonto oder auf Papier aus", t)
        self.assertIn("Danach tippst du sie selbst in deiner App ein", t)

    def test_json_carries_the_steps(self):
        self.run_risk()
        code, text, _ = run(self.args("show", "--index", "1", "--json"))
        self.assertEqual(code, 0)
        tj = json.loads(text)
        self.assertEqual((tj["broker"], tj["market"], tj["currency"], tj["flat_by"], tj["tool"]),
                         ("manuell", "xetra", "EUR", "17:25", None))
        self.assertEqual((tj["max_loss"], tj["max_loss_currency"]), (32.7, "EUR"))
        self.assertTrue(any("Stückzahl 17" in s for s in tj["anleitung"]))

    def test_manual_flow_with_a_german_yes(self):
        self.run_risk()
        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "ja aber nur 5"))
        self.assertEqual(code, 1)
        self.assertIn("Nicht erfasst", text)
        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "Ja, platzieren"))
        self.assertEqual(code, 0)
        self.assertIn("Jetzt in deiner Broker-App", text)
        self.assertIn("Stop-Kurs 209,50 €", flat(text))
        st = self.state_doc()["orders"][0]
        self.assertEqual((st["status"], st["reply"], st["date"], st["broker"]),
                         ("approved", "Ja, platzieren", SAP_TODAY, "manuell"))
        self.assertEqual((st["max_loss"], st["max_loss_currency"], st["kind"]), (32.7, "EUR", "entry"))
        self.assertEqual(st["at"], "2026-10-28T10:15:00+01:00")
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("BESTÄTIGT von dir um 10:15 Uhr, wartet darauf, dass du sie in deiner App eingibst", text)
        code, text, _ = run(self.args("result", "--index", "1", "--status", "placed", "--filled-qty", "17",
                                      "--filled-price", "211.30", "--portfolio", self.pf, now="2026-10-28 10:17"))
        self.assertEqual(code, 0)
        self.assertIn("Order 1 als platziert erfasst.", text)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], round(5000 - 17 * 211.30, 2))
        code, text, _ = run(["log", "--state", self.state, "--config", self.cfg, "--now", "2026-10-28 10:20"])
        self.assertIn("max. Verlust 32,70 €", text)
        self.assertIn("28.10.2026 10:15 Uhr", text)

    def test_flatten_writes_a_sell_guide(self):
        late = "2026-10-28T16:20:00Z"
        with open(self.pf, "w") as fh:
            json.dump({"cash": 1408.4, "positions": [{"ticker": "SAP.DE", "shares": 17, "lots": [
                {"id": "SAP.DE-1", "date": SAP_TODAY, "shares": 17, "cost": 3591.6}]}]}, fh)
        code, text, _ = run(["flatten", "--symbol", "SAP.DE", "--qty", "17", "--orders", self.orders,
                             "--portfolio", self.none, "--plan", self.none, "--config", self.cfg,
                             "--now", late])
        self.assertEqual(code, 0)
        self.assertIn("Glattstellen SAP.DE bis 17:25 Uhr: VERKAUF 17 Stück SAP.DE, Market-Order, gültig heute.", text)
        self.assertIn("Verkaufe 17 Stück SAP.DE bestens; storniere vorher offene Stop-/Limit-Orders auf diese Stücke.",
                      flat(text))
        self.assertNotIn("cancel_order_by_id", text)
        self.assertEqual(self.run_risk(now=late), 0)
        code, text, _ = run(self.args("show", now=late))
        self.assertEqual(code, 0)
        t = flat(text)
        self.assertIn("Vorher offene Stop- und Limit-Orders auf diese Stücke stornieren", t)
        self.assertIn("Verkaufen wählen, Stückzahl 17.", t)
        self.assertIn("Orderart: Market (bestens, ohne Limit).", t)
        self.assertNotIn("OCO", t)

    def test_alpaca_cannot_trade_xetra(self):
        self.set_cfg(broker="alpaca")
        self.run_risk()
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 1)
        self.assertIn("NICHT BEREIT: Alpaca handelt nur US-Aktien, SAP.DE ist ein XETRA-Wert", text)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "ja"))
        self.assertEqual(code, 1)
        self.assertIn("Alpaca handelt nur US-Aktien", err)

    def test_ibkr_can_trade_xetra(self):
        self.set_cfg(broker="ibkr")
        self.run_risk()
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 0)
        self.assertIn("Interactive Brokers", text)

    def test_us_stock_by_hand_mentions_german_venues(self):
        with open(ORDERS_PATH) as fh:
            doc = json.load(fh)
        doc["orders"][0]["plan"]["fx"] = 0.86
        doc["orders"][0]["plan"]["account_currency"] = "EUR"
        doc["orders"][0]["plan"]["max_loss"] = 42.32
        doc["orders"][0]["plan"]["fees"] = 2.0
        with open(self.orders, "w") as fh:
            json.dump(doc, fh)
        self.assertEqual(self.run_risk(now=NOW), 0)
        code, text, _ = run(self.args("show", "--index", "1", now=NOW))
        self.assertEqual(code, 0)
        t = flat(text)
        self.assertIn("Markt US (NYSE/Nasdaq), Kurse in USD, glatt bis 15:55 ET (21:55 Uhr), Konto in EUR", t)
        self.assertIn("Tradegate, LS Exchange oder gettex in EUR", t)
        self.assertIn("Stop-Kurs 358,32 $ (etwa 308,16 €)", t)
        self.assertIn("max. Verlust etwa 46,88 $ (42,32 € in Kontowährung, inkl. Gebühren)", t)


if __name__ == "__main__":
    unittest.main()
