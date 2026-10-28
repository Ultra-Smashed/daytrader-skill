import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

ins = load("dt-insider", "insider")
DIR = os.path.join(FIX, "dt-insider")
WEEK = os.path.join(DIR, "bafin_week.csv")
MONTH = os.path.join(DIR, "bafin_month.csv")
DEUTZ = os.path.join(DIR, "bafin_isin_DE0006305006.csv")
UNIVERSE = os.path.join(DIR, "universe.txt")


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ins.main(args)
    return code, out.getvalue(), err.getvalue()


def write_json(folder, name, doc):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


class ParseExport(unittest.TestCase):
    def setUp(self):
        self.week = ins.read_file(WEEK)
        self.month = ins.read_file(MONTH)

    def test_row_counts_and_bom(self):
        with open(WEEK, "rb") as fh:
            self.assertTrue(fh.read(3) == b"\xef\xbb\xbf")
        self.assertEqual(len(self.week), 15)
        self.assertEqual(len(self.month), 133)
        self.assertEqual(self.week[0]["issuer"], "Beno Holding AG")

    def test_the_kst_row_word_for_word(self):
        kst = next(r for r in self.week if r["issuer"] == "KST Beteiligungs AG")
        self.assertEqual(kst["isin"], "DE000A161309")
        self.assertEqual(kst["bafin_id"], "20000048")
        self.assertEqual(kst["person"], "Schmitt, Martin")
        self.assertEqual(kst["position"], "Aufsichtsrat")
        self.assertEqual(kst["instrument"], "Aktie")
        self.assertEqual((kst["kind"], kst["side"], kst["signal"]), ("Kauf", "buy", True))
        self.assertEqual((kst["price"], kst["price_currency"], kst["price_text"]), (1.11, "EUR", "1,11 EUR"))
        self.assertEqual((kst["volume"], kst["volume_text"]), (6660.0, "6.660,00 EUR"))
        self.assertEqual((kst["traded"], kst["notified"]), ("2026-10-26", "2026-10-27"))
        self.assertEqual(kst["published"], "2026-10-28T06:01:37")
        self.assertEqual(kst["venue"], "Tradegate")
        self.assertEqual((kst["delay_business_days"], kst["late"]), (1, False))
        self.assertIsNone(kst["close_associate"])

    def test_big_numbers_and_empty_fields(self):
        flatex = next(r for r in self.week if r["issuer"] == "flatexDEGIRO SE")
        self.assertEqual(flatex["volume"], 2340570.0)
        self.assertIsNone(flatex["venue"])
        beno = self.week[0]
        self.assertIsNone(beno["isin"])
        self.assertIsNone(beno["price"])
        self.assertIsNone(beno["volume"])
        self.assertEqual(beno["published"], "2026-10-26T15:02:02")

    def test_amounts_and_dates(self):
        self.assertEqual(ins.amount("6.660,00 EUR"), (6660.0, "EUR", 2))
        self.assertEqual(ins.amount("0,0125 EUR"), (0.0125, "EUR", 4))
        self.assertEqual(ins.amount(""), (None, None, 0))
        self.assertEqual(ins.de_date("26.10.2026"), "2026-10-26")
        self.assertIsNone(ins.de_date("31.02.2026"))
        self.assertEqual(ins.de_datetime("28.10.2026 06:01:37"), "2026-10-28T06:01:37")

    def test_latin1_export_and_no_bom(self):
        with open(WEEK, encoding="utf-8-sig") as fh:
            text = fh.read()
        rows = ins.parse_csv(text.encode("latin-1", "replace"))
        self.assertEqual(len(rows), 15)
        self.assertEqual(rows[2]["position"], "Sonstige Führungsperson")
        self.assertEqual(len(ins.parse_csv(text.encode("utf-8"))), 15)

    def test_html_or_wrong_file_is_a_clear_error(self):
        with self.assertRaises(ins.InsiderError) as cm:
            ins.parse_csv(b"<!DOCTYPE html><html></html>")
        self.assertIn("HTML", str(cm.exception))
        with self.assertRaises(ins.InsiderError) as cm:
            ins.parse_csv(b"Symbol;Preis\nSAP;100\n")
        self.assertIn("Eigengeschäfte", str(cm.exception))

    def test_other_deals_and_close_associates(self):
        other = [r for r in self.month if not r["signal"]]
        self.assertEqual(len(other), 52)
        self.assertTrue(all(r["kind"] == "Sonstiges" for r in other))
        firms = {r["person"]: r["close_associate"] for r in self.month if r["close_associate"]}
        self.assertEqual(firms["2. vLB GmbH & Co. KG"], "firma")
        self.assertEqual(firms["Sara Georgi Stiftung"], "firma")
        self.assertEqual(firms["Pareto Capital Partners SA - SPF"], "firma")
        self.assertEqual(firms["Voggenreiter, Dr. Simone"], "person")
        self.assertEqual(firms["Hauschildt, Waltraud"], "person")

    def test_keys_are_stable_and_unique(self):
        again = ins.read_file(MONTH)
        self.assertEqual([r["key"] for r in self.month], [r["key"] for r in again])
        self.assertEqual(len({r["key"] for r in self.month}), 133)
        with open(WEEK, "rb") as fh:
            data = fh.read()
        doubled = ins.parse_csv(data + data.split(b"\n", 1)[1])
        self.assertEqual(len({r["key"] for r in doubled}), 30)


class Delay(unittest.TestCase):
    def test_business_days_skip_weekends(self):
        d = datetime.date
        self.assertEqual(ins.business_days(d(2026, 10, 26), d(2026, 10, 26)), 0)
        self.assertEqual(ins.business_days(d(2026, 10, 23), d(2026, 10, 26)), 1)  # Fr bis Mo
        self.assertEqual(ins.business_days(d(2026, 10, 21), d(2026, 10, 27)), 4)
        self.assertEqual(ins.business_days(d(2026, 10, 24), d(2026, 10, 26)), 1)  # Sa bis Mo

    def test_xetra_holidays_do_not_count(self):
        d = datetime.date
        # Karfreitag 03.04. und Ostermontag 06.04.2026 sind handelsfrei
        self.assertEqual(ins.business_days(d(2026, 4, 2), d(2026, 4, 8)), 2)
        # Weihnachten: 24., 25. und 31.12. handelsfrei
        self.assertEqual(ins.business_days(d(2026, 12, 23), d(2026, 12, 30)), 3)

    def test_holidays_count_even_when_the_tests_run_on_us(self):
        ins.markt.use("us")
        self.assertEqual(ins.business_days(datetime.date(2026, 4, 30), datetime.date(2026, 5, 4)), 1)

    def test_late_rows_in_the_month(self):
        late = [r for r in ins.read_file(MONTH) if r["late"]]
        self.assertEqual(len(late), 12)
        smart = next(r for r in late if r["issuer"] == "Smartbroker Holding AG")
        self.assertEqual((smart["person"], smart["delay_business_days"]), ("Kolbinger, André", 4))
        maier = next(r for r in ins.read_file(DEUTZ) if r["person"] == "Maier, Dr. Rudolf")
        self.assertEqual((maier["traded"], maier["notified"], maier["delay_business_days"], maier["late"]),
                         ("2026-10-01", "2026-10-06", 3, False))


class Filters(unittest.TestCase):
    def setUp(self):
        self.rows = ins.read_file(MONTH)

    def test_isin_issuer_person(self):
        self.assertEqual(len(ins.select(self.rows, isin="de0006305006")), 6)
        self.assertEqual(len(ins.select(self.rows, issuer="deutz")), 6)
        for q in ("Martin Schmitt", "Schmitt, Martin", "schmitt"):
            self.assertEqual([r["issuer"] for r in ins.select(self.rows, person=q)], ["KST Beteiligungs AG"], q)
        self.assertEqual(ins.select(self.rows, person="Martin Schmitz"), [])

    def test_side_volume_and_dates(self):
        self.assertEqual(len(ins.select(self.rows, art="kauf")), 65)
        self.assertEqual(len(ins.select(self.rows, art="verkauf")), 16)
        big = ins.select(self.rows, art="kauf", min_volume=1000000)
        self.assertEqual({r["issuer"] for r in big},
                         {"CTS Eventim AG & Co. KGaA", "Allerthal-Werke Aktiengesellschaft", "FUCHS SE"})
        span = ins.select(self.rows, von=datetime.date(2026, 10, 22), bis=datetime.date(2026, 10, 23))
        self.assertTrue(span)
        self.assertTrue(all("2026-10-22" <= r["traded"] <= "2026-10-23" for r in span))

    def test_summary_per_issuer(self):
        summary = {(s["issuer"], s["isin"]): s for s in ins.summarize(self.rows)}
        deutz = summary[("DEUTZ Aktiengesellschaft", "DE0006305006")]
        self.assertEqual((deutz["buys"], deutz["buy_volume"], deutz["sells"]), (6, 402015.0, 0))
        asta = summary[("ASTA Energy Solutions AG", "AT100ASTA001")]
        self.assertEqual(asta["net_volume"], -22300.33)
        self.assertEqual(ins.summarize(self.rows)[0]["issuer"], "CTS Eventim AG & Co. KGaA")


class YourStocks(unittest.TestCase):
    def test_universe_resolves_isins_and_ignores_old_lines(self):
        uni = ins.load_universe(UNIVERSE)
        self.assertEqual(uni["DE0007030009"][0], "RHM.DE")
        self.assertEqual(uni["DE0006305006"], ("DEZ.DE", "DEUTZ AG O.N.", "MDAX"))
        self.assertNotIn("TSLA", [v[0] for v in uni.values()])
        self.assertEqual(ins.load_universe("/nonexistent"), {})

    def test_portfolio_and_watchlist_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = write_json(tmp, "portfolio.json", {"positions": [
                {"ticker": "RHM.DE", "shares": 2},
                {"symbol": "XYZ", "isin": "DE000A161309"}]})
            wl = write_json(tmp, "watchlist.json", {"hits": [{"symbol": "DEZ.DE"}]})
            rows = ins.mark(ins.read_file(MONTH), ins.load_universe(UNIVERSE), ins.your_stocks(pf, wl))
        held = {r["issuer"] for r in rows if r["in_portfolio"]}
        self.assertEqual(held, {"Rheinmetall Aktiengesellschaft", "KST Beteiligungs AG"})
        watched = {r["issuer"] for r in rows if r["on_watchlist"]}
        self.assertEqual(watched, {"DEUTZ Aktiengesellschaft"})
        rhm = next(r for r in rows if r["person"] == "Papperger, Armin Theodor")
        self.assertEqual((rhm["symbol"], rhm["price"], rhm["volume"]), ("RHM.DE", 950.38, 498947.8))


class NewSinceLastRun(unittest.TestCase):
    def test_shows_each_row_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "state", "insider.json")
            base = ["new", "--offline", MONTH, "--state", state, "--today", "2026-10-28",
                    "--portfolio", os.path.join(tmp, "none.json"), "--watchlist", os.path.join(tmp, "none.json"),
                    "--universe", UNIVERSE]
            code, out, _ = run(base)
            self.assertEqual(code, 0)
            self.assertIn("erster Lauf", out)
            self.assertIn("KST Beteiligungs AG", out)
            self.assertNotIn("Papperger", out)  # 29.09., älter als eine Woche
            with open(state, encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertEqual(len(saved["seen"]), 133)
            self.assertTrue(saved["last_check"])
            code, out, _ = run(base)
            self.assertEqual(code, 1)
            self.assertIn("Nichts Neues seit", out)

    def test_a_new_row_is_new(self):
        rows = ins.read_file(WEEK)
        state = {"seen": [r["key"] for r in rows[1:]], "last_check": "2026-10-27T09:00:00"}
        fresh = ins.new_since(rows, state, datetime.date(2026, 10, 28))
        self.assertEqual([r["person"] for r in fresh], ["Renner, Florian"])

    def test_dry_run_keeps_state_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "insider.json")
            code, out, _ = run(["new", "--offline", WEEK, "--state", state, "--today", "2026-10-28",
                                "--dry-run", "--json", "--art", "kauf"])
            self.assertEqual(code, 0)
            self.assertFalse(os.path.exists(state))
            doc = json.loads(out)
            self.assertEqual(len(doc["new"]), 9)
            self.assertTrue(all(r["side"] == "buy" for r in doc["new"]))


class Cli(unittest.TestCase):
    def test_index_in_german(self):
        code, out, _ = run(["index", "--offline", WEEK, "--universe", UNIVERSE, "--portfolio", "/nonexistent",
                            "--watchlist", "/nonexistent", "--summe"])
        self.assertEqual(code, 0)
        self.assertIn("15 Meldungen, Datei bafin_week.csv:", out)
        self.assertIn("KST Beteiligungs AG (ISIN DE000A161309)", out)
        self.assertIn("Kauf: Schmitt, Martin (Aufsichtsrat), Aktie", out)
        self.assertIn("Durchschnittspreis 1,11 €, Volumen 6.660,00 € (Betrag, keine Stückzahl)", out)
        self.assertIn("Handel Mo 26.10.2026 an Tradegate, Mitteilung Di 27.10.2026, 1 Geschäftstag später, "
                      "veröffentlicht Mi 28.10.2026 06:01 Uhr", out)
        self.assertIn("DEUTZ Aktiengesellschaft (ISIN DE0006305006, DEZ.DE)", out)
        self.assertIn("zählt nicht als Marktsignal", out)
        self.assertIn("In enger Beziehung: eine Firma", out)
        self.assertIn("Summe je Emittent:", out)
        self.assertIn("DEUTZ Aktiengesellschaft (DEZ.DE): 4 Käufe über 249.075,00 €", out)
        self.assertIn("Kein Insiderwissen", out)
        self.assertNotIn(chr(0x2014), out)

    def test_late_and_flags_in_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = write_json(tmp, "p.json", {"positions": [{"ticker": "RHM.DE"}]})
            code, out, _ = run(["parse", MONTH, "--universe", UNIVERSE, "--portfolio", pf,
                                "--watchlist", "/nonexistent", "--limit", "200"])
        self.assertEqual(code, 0)
        self.assertIn("4 Geschäftstage später, VERSPÄTET (Frist: 3 Geschäftstage)", out)
        self.assertIn("Rheinmetall Aktiengesellschaft (ISIN DE0007030009, RHM.DE)  [im Depot]", out)
        self.assertIn("(kein Handelsplatz angegeben)", out)

    def test_parse_json_and_date_window(self):
        code, out, _ = run(["parse", MONTH, "--json", "--von", "26.10.2026", "--bis", "26.10.2026",
                            "--portfolio", "/nonexistent", "--watchlist", "/nonexistent"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertTrue(all(r["traded"] == "2026-10-26" for r in doc["rows"]))
        self.assertEqual(doc["count"], len(doc["rows"]))

    def test_nothing_found_and_errors_in_german(self):
        code, out, _ = run(["index", "--offline", WEEK, "--person", "Niemand", "--portfolio", "/x"])
        self.assertEqual(code, 1)
        self.assertIn("Keine passenden Meldungen", out)
        code, _, err = run(["index", "--offline", WEEK, "--isin", "SAP"])
        self.assertEqual(code, 2)
        self.assertIn("--isin erwartet eine ISIN", err)
        code, _, err = run(["index", "--offline", WEEK, "--von", "2026-10-01"])
        self.assertEqual(code, 2)
        self.assertIn("TT.MM.JJJJ", err)
        code, _, err = run(["parse", "/nonexistent.csv"])
        self.assertEqual(code, 2)

    def test_url_and_market_restored(self):
        url = ins.build_url("datum", isin="DE0006305006", von=datetime.date(2026, 10, 1),
                            bis=datetime.date(2026, 10, 28))
        self.assertTrue(url.startswith("https://portal.mvp.bafin.de/database/DealingsInfo/sucheForm.do?"))
        for part in ("zeitraum=3", "emittentIsin=DE0006305006", "zeitraumVon=01.10.2026",
                     "zeitraumBis=28.10.2026", "d-4000784-e=1", "6578706f7274=1", "emittentButton=Suche+Emittent"):
            self.assertIn(part, url)
        self.assertIn("zeitraum=1", ins.build_url())
        ins.markt.use("us")
        run(["index", "--offline", WEEK, "--portfolio", "/x"])
        self.assertEqual(ins.markt.current(), "us")


if __name__ == "__main__":
    unittest.main()
