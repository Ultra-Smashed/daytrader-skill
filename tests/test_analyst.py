import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

facts = load("dt-analyst", "facts")
DIR = os.path.join(FIX, "dt-analyst")
QDIR = os.path.join(DIR, "quartale")
SAP = os.path.join(QDIR, "SAP.DE.json")


def companyfacts(cik):
    with open(os.path.join(DIR, "companyfacts-CIK%s.json" % cik)) as fh:
        return json.load(fh)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = facts.main(args)
    return code, out.getvalue(), err.getvalue()


class Apple(unittest.TestCase):
    def setUp(self):
        self.r = facts.analyse(companyfacts("0000320193"), quarters=8)

    def test_latest_quarter(self):
        q = self.r["rows"][0]
        self.assertEqual(q["end"], "2026-06-27")
        self.assertEqual(q["fiscal"], "Q3 2026")
        self.assertEqual(q["revenue"], 109417000000)
        self.assertEqual(q["net_income"], 29789000000)
        self.assertEqual(q["eps_diluted"], 2.02)
        self.assertEqual(q["revenue_yoy"], 16.4)    # vs 94.036 ein Jahr zuvor
        self.assertEqual(q["eps_yoy"], 28.7)        # vs 1,57
        self.assertEqual(q["gross_margin"], 50.1)
        self.assertEqual(q["operating_margin"], 32.6)
        self.assertEqual(q["net_margin"], 27.2)
        self.assertFalse(q["derived"])

    def test_fiscal_labels_come_from_the_first_filing(self):
        labels = [r["fiscal"] for r in self.r["rows"][:6]]
        self.assertEqual(labels, ["Q3 2026", "Q2 2026", "Q1 2026", "Q4 2025", "Q3 2025", "Q2 2025"])

    def test_q4_is_derived_from_the_10k(self):
        q4 = next(r for r in self.r["rows"] if r["end"] == "2025-09-27")
        self.assertTrue(q4["derived"])
        # GJ 2025 416.161 minus Q1 124.300, Q2 95.359, Q3 94.036
        self.assertEqual(q4["revenue"], 102466000000)
        self.assertEqual(q4["revenue_yoy"], 7.9)

    def test_trailing_twelve_months(self):
        self.assertEqual(self.r["ttm"]["revenue"], 466823000000)
        self.assertEqual(self.r["ttm"]["net_income"], 128930000000)
        self.assertEqual(self.r["ttm"]["eps_diluted"], 8.71)

    def test_what_changed_in_words(self):
        lines = facts.changes(self.r)
        self.assertIn("Umsatz 109,42 Mrd. $ (+16,4 % gegenüber dem Vorjahresquartal)", lines[0])
        self.assertIn("EPS verwässert 2,02 $ (+28,7 %)", lines[0])
        self.assertIn("Quartal bis 27.06.2026", lines[0])
        self.assertTrue(any(l.startswith("Bruttomarge 50,1 % (+0,8 Prozentpunkte") for l in lines))

    def test_restated_values_win_but_labels_stay(self):
        facts_ = [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "fy": 2025, "fp": "Q1",
             "form": "10-Q", "filed": "2025-05-01", "accn": "a"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 90, "fy": 2026, "fp": "Q1",
             "form": "10-Q", "filed": "2026-05-01", "accn": "b"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 1, "fy": 2025, "fp": "Q1",
             "form": "8-K", "filed": "2025-04-20", "accn": "c"},
        ]
        q = facts.quarterly(facts_)
        self.assertEqual(q["2025-03-31"]["value"], 90)
        self.assertEqual((q["2025-03-31"]["fy"], q["2025-03-31"]["fp"]), (2025, "Q1"))


class Filings(unittest.TestCase):
    def test_latest_10q_and_earnings_press_release(self):
        with open(os.path.join(DIR, "submissions-CIK0000320193.json")) as fh:
            sub = json.load(fh)
        f = facts.latest_filings(sub, "0000320193", facts.Fetcher(offline=DIR))
        self.assertEqual(f["report"]["form"], "10-Q")
        self.assertEqual(f["report"]["period"], "2026-06-27")
        self.assertTrue(f["report"]["url"].endswith("/000032019326000020/aapl-20260627.htm"))
        e = f["earnings_8k"]
        self.assertEqual(e["filed"], "2026-07-30")
        self.assertEqual(e["exhibit"], "https://www.sec.gov/Archives/edgar/data/320193/"
                                       "000032019326000018/a8-kex991q3202606272026.htm")

    def test_exhibit_names_seen_on_edgar(self):
        pick = facts.exhibit_name
        self.assertEqual(pick(["axp-20260724.htm", "q226exhibit991.htm", "q226exhibit992.htm",
                               "R1.htm"], "axp-20260724.htm"), "q226exhibit991.htm")
        self.assertEqual(pick(["goog-20260722.htm", "googexhibit991q22026.htm"],
                              "goog-20260722.htm"), "googexhibit991q22026.htm")
        self.assertEqual(pick(["a2026q2earningsreleaseex-9.htm", "ko-20260728.htm"],
                              "ko-20260728.htm"), "a2026q2earningsreleaseex-9.htm")
        self.assertEqual(pick(["bac-06302026ex993.htm", "bac-06302026ex991.htm"]),
                         "bac-06302026ex991.htm")
        self.assertIsNone(pick(["only-8k.htm"], "only-8k.htm"))


class LaggingData(unittest.TestCase):
    def test_says_when_sec_facts_trail_a_filed_10q(self):
        code, out, err = run(["KO", "--offline", DIR])
        self.assertEqual(code, 0, err)
        self.assertIn("COCA COLA CO (KO)", out)
        self.assertIn("HINWEIS: Die XBRL-Daten der SEC enden am 03.04.2026, aber ein 10-Q für den "
                      "Zeitraum bis 03.07.2026 wurde am 29.07.2026 eingereicht", out)

    def test_one_offs_are_flagged(self):
        result = {"rows": [
            {"end": "2026-06-30", "derived": False, "revenue": 100.0, "net_income": 90.0,
             "operating_income": 30.0, "eps_diluted": 1.0, "revenue_yoy": 10.0,
             "net_income_yoy": 200.0, "eps_yoy": 200.0, "gross_margin": None,
             "operating_margin": 30.0, "net_margin": 90.0}]}
        lines = facts.changes(result)
        self.assertTrue(any("über dem operativen Ergebnis" in l and "den 10-Q" in l for l in lines))


class Cli(unittest.TestCase):
    def test_metrics_file_for_the_screener(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "trader", "metrics.json")
            code, out, err = run(["AAPL", "KO", "--offline", DIR, "--metrics", path])
            self.assertEqual(code, 0, err)
            with open(path) as fh:
                data = json.load(fh)
        rows = {r["ticker"]: r for r in data["companies"]}
        self.assertEqual(sorted(rows), ["AAPL", "KO"])
        self.assertEqual(rows["AAPL"]["eps_ttm"], 8.71)
        self.assertEqual(rows["AAPL"]["revenue_growth_yoy"], 16.4)
        self.assertEqual(rows["AAPL"]["source"], "SEC XBRL company facts")
        self.assertEqual(rows["KO"]["period_end"], "2026-04-03")
        self.assertIn("geschrieben", out)
        self.assertNotIn(chr(0x2014), out)

    def test_unknown_ticker_and_no_user_agent(self):
        code, _, err = run(["ZZZZ", "--offline", DIR])
        self.assertEqual(code, 2)
        self.assertIn("keine SEC-CIK für ZZZZ", err)
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            code, _, err = run(["AAPL", "--config", "/nonexistent.json"])
            self.assertEqual(code, 2)
            self.assertIn("User-Agent", err)
            self.assertIn("trader/config.json", err)
            self.assertIsNone(facts.user_agent("Your Name you@example.com"))
            self.assertIsNone(facts.user_agent("Dein Name du@example.com"))
            self.assertEqual(facts.user_agent("Erika Muster erika@muster.de"), "Erika Muster erika@muster.de")
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old

    def test_json_output(self):
        code, out, err = run(["AAPL", "--offline", DIR, "--json", "--quarters", "4"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(len(data[0]["result"]["rows"]), 4)
        self.assertEqual(data[0]["result"]["concepts"]["revenue"],
                         ["RevenueFromContractWithCustomerExcludingAssessedTax"])

    def test_german_table_and_numbers(self):
        code, out, err = run(["AAPL", "--offline", DIR, "--no-filings"])
        self.assertEqual(code, 0, err)
        self.assertIn("Mio. US-$ außer EPS", out)
        self.assertIn("27.06.2026", out)
        self.assertIn("109.417", out)
        self.assertIn("Letzte 4 Quartale: Umsatz 466,82 Mrd. $, Nettoergebnis 128,93 Mrd. $, "
                      "EPS verwässert 8,71 $.", out)
        self.assertIn("abgeleitet", out)
        self.assertIn("Was sich geändert hat:", out)


# SAP SE, Quartalsmitteilungen Q4 2025 bis Q3 2026 (IFRS, sap.com), von Hand übertragen
class GermanIssuer(unittest.TestCase):
    def setUp(self):
        self.r = facts.analyse_quartale(facts.load_quartale(SAP, "SAP.DE"), quarters=8)

    def test_latest_quarter_from_the_statement(self):
        q = self.r["rows"][0]
        self.assertEqual(q["end"], "2026-09-30")
        self.assertEqual(q["fiscal"], "Q3 2026")
        self.assertEqual(q["revenue"], 10270000000)
        self.assertEqual(q["eps_diluted"], 1.94)
        self.assertEqual(q["gross_margin"], 73.1)
        self.assertEqual(q["operating_margin"], 28.5)
        self.assertEqual(q["net_margin"], 21.9)
        self.assertEqual(q["revenue_yoy"], 13.2)      # vs 9.076 im Q3 2025
        self.assertEqual(q["net_income_yoy"], 12.2)   # vs 2.004
        self.assertEqual(q["eps_yoy"], 13.5)          # vs 1,71
        self.assertEqual((q["page"], q["basis"]), ("S. 8", "IFRS"))
        self.assertFalse(q["derived"])
        self.assertEqual(q["missing"], [])
        self.assertEqual(len(self.r["rows"]), 8)

    def test_trailing_twelve_months(self):
        self.assertEqual(self.r["ttm"]["revenue"], 39387000000)
        self.assertEqual(self.r["ttm"]["net_income"], 8207000000)
        self.assertEqual(self.r["ttm"]["eps_diluted"], 7.04)

    def test_changes_in_euro(self):
        lines = facts.changes(self.r)
        self.assertIn("Quartal bis 30.09.2026 (Q3 2026): Umsatz 10,27 Mrd. € (+13,2 % gegenüber "
                      "dem Vorjahresquartal), Nettoergebnis 2,25 Mrd. € (+12,2 %), "
                      "EPS verwässert 1,94 € (+13,5 %).", lines)
        self.assertIn("Operative Marge 28,5 % (+1,7 Prozentpunkte gegenüber dem Vorquartal).", lines)
        self.assertTrue(any(l.startswith("Umsatz +4,0 % gegenüber dem Vorquartal") for l in lines))
        self.assertFalse(any("über dem operativen Ergebnis" in l for l in lines))

    def test_cli_with_the_default_folder_layout(self):
        code, out, err = run(["SAP.DE", "--quartale", QDIR])
        self.assertEqual(code, 0, err)
        self.assertIn("SAP SE (SAP.DE), ISIN DE0007164600. Mio. € außer EPS.", out)
        self.assertIn("Quelle: Quartalsmitteilung, von Hand übertragen, prüfe die Seitenangabe.", out)
        self.assertIn("30.09.2026   Q3 2026       10.270   +13,2 %  73,1 %  28,5 %  21,9 %", out)
        self.assertIn("Letzte 4 Quartale: Umsatz 39,39 Mrd. €, Nettoergebnis 8,21 Mrd. €, "
                      "EPS verwässert 7,04 €.", out)
        self.assertIn("Q3 2026 (30.09.2026): S. 8, IFRS, https://www.sap.com/docs/download/investors/"
                      "2026/sap-2026-q3-statement.pdf", out)
        self.assertNotIn(chr(0x2014), out)

    def test_cli_with_a_file_and_no_symbol(self):
        code, out, err = run(["--quartale", SAP, "--quarters", "2"])
        self.assertEqual(code, 0, err)
        self.assertIn("(SAP.DE)", out)
        self.assertNotIn("30.09.2025", out)

    def test_no_user_agent_needed_for_german_issuers(self):
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            code, _, err = run(["SAP.DE", "--quartale", QDIR, "--config", "/nonexistent.json"])
            self.assertEqual(code, 0, err)
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old

    def test_missing_file_explains_the_way_and_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run(["SAP.DE", "--quartale", tmp])
        self.assertEqual(code, 1)
        self.assertIn("keine Quartalsdatei", err)
        self.assertIn("SAP.DE ist ein deutscher Emittent (XETRA)", out)
        self.assertIn("Investor-Relations-Seite", out)
        self.assertIn("Quartalsmitteilung", out)
        self.assertIn("Unternehmensregister", out)
        self.assertIn(os.path.join(tmp, "SAP.DE.json"), out)
        self.assertIn("null", out)
        self.assertNotIn(chr(0x2014), out)

    def test_missing_file_default_path_and_json_stays_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                code, out, err = run(["BMW.DE"])
                self.assertEqual(code, 1)
                self.assertIn(os.path.join("trader", "quartale", "BMW.DE.json"), out)
                code, out, err = run(["BMW.DE", "--json"])
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(out), [])
                self.assertIn("Unternehmensregister", err)
            finally:
                os.chdir(cwd)

    def test_metrics_row_for_a_german_issuer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "trader", "metrics.json")
            code, out, err = run(["SAP.DE", "AAPL", "--quartale", QDIR, "--offline", DIR,
                                  "--no-filings", "--metrics", path])
            self.assertEqual(code, 0, err)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        rows = {r["ticker"]: r for r in data["companies"]}
        self.assertEqual(sorted(rows), ["AAPL", "SAP.DE"])
        sap = rows["SAP.DE"]
        self.assertEqual(sap["source"], "Quartalsmitteilung (manuell)")
        self.assertEqual(sap["name"], "SAP SE")
        self.assertIsNone(sap["cik"])
        self.assertEqual(sap["isin"], "DE0007164600")
        self.assertEqual(sap["period_end"], "2026-09-30")
        self.assertEqual(sap["revenue_ttm"], 39387000000)
        self.assertEqual(sap["eps_ttm"], 7.04)
        self.assertEqual(sap["revenue_growth_yoy"], 13.2)
        self.assertEqual(sap["operating_margin"], 28.5)
        for key in rows["AAPL"]:
            self.assertIn(key, sap)
        self.assertEqual(rows["AAPL"]["source"], "SEC XBRL company facts")

    def test_example_in_the_skill_folder_is_the_fixture(self):
        example = os.path.join(os.path.dirname(facts.__file__), "quartale.example.json")
        with open(example, encoding="utf-8") as a, open(SAP, encoding="utf-8") as b:
            self.assertEqual(json.load(a), json.load(b))


def testbeispiel(quarters):
    return {"symbol": "TEST.DE", "name": "Testbeispiel AG", "isin": None, "currency": "EUR",
            "quarters": quarters}


def q(end, period, revenue=None, gross_profit=None, operating_income=None, net_income=None,
      eps_diluted=None):
    return {"period_end": end, "period": period, "revenue": revenue, "gross_profit": gross_profit,
            "operating_income": operating_income, "net_income": net_income,
            "eps_diluted": eps_diluted, "source": "https://example.com/test.pdf", "page": "S. 1",
            "basis": "IFRS"}


# Testbeispiel AG ist erfunden und nur für diese Tests da
class GermanEdgeCases(unittest.TestCase):
    def write(self, tmp, data):
        path = os.path.join(tmp, "TEST.DE.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_missing_fields_stay_blank(self):
        data = testbeispiel([
            q("2026-09-30", "Q3 2026", revenue=200e6, net_income=10e6, eps_diluted=0.5),
            q("2025-09-30", "Q3 2025", revenue=160e6, gross_profit=80e6, operating_income=20e6,
              net_income=8e6, eps_diluted=0.4),
        ])
        r = facts.analyse_quartale(data)
        cur = r["rows"][0]
        self.assertIsNone(cur["gross_profit"])
        self.assertIsNone(cur["gross_margin"])
        self.assertIsNone(cur["operating_margin"])
        self.assertEqual(cur["net_margin"], 5.0)
        self.assertEqual(cur["revenue_yoy"], 25.0)
        self.assertEqual(cur["eps_yoy"], 25.0)
        self.assertEqual(cur["missing"], ["gross_profit", "operating_income"])
        self.assertEqual(r["ttm"], {})
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run(["TEST.DE", "--quartale", self.write(tmp, data)])
        self.assertEqual(code, 0, err)
        self.assertIn("Testbeispiel AG (TEST.DE)", out)
        self.assertIn("HINWEIS: Q3 2026 nennt kein Bruttoergebnis, EBIT. Die Felder bleiben leer", out)
        self.assertIn("vier Quartale in Folge", out)
        self.assertNotIn("Bruttomarge", out)

    def test_ttm_needs_four_quarters_in_a_row(self):
        data = testbeispiel([
            q("2026-09-30", "Q3 2026", revenue=4.0, net_income=1.0),
            q("2026-06-30", "Q2 2026", revenue=3.0, net_income=1.0),
            q("2026-03-31", "Q1 2026", revenue=2.0),
            q("2025-12-31", "Q4 2025", revenue=1.0, net_income=1.0),
            q("2025-09-30", "Q3 2025", revenue=1.0, net_income=1.0),
        ])
        r = facts.analyse_quartale(data)
        self.assertEqual(r["ttm"]["revenue"], 10.0)
        self.assertNotIn("net_income", r["ttm"])

    def test_one_off_warning_points_to_the_statement(self):
        data = testbeispiel([q("2026-09-30", "Q3 2026", revenue=100.0, operating_income=10.0,
                               net_income=40.0)])
        lines = facts.changes(facts.analyse_quartale(data))
        self.assertTrue(any("über dem operativen Ergebnis (EBIT)" in l and "die Quartalsmitteilung" in l
                            for l in lines))

    def test_bad_files_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, testbeispiel([q("2026-09-30", "Q3 2026", revenue="10.270")]))
            code, _, err = run(["TEST.DE", "--quartale", path])
            self.assertEqual(code, 2)
            self.assertIn("keine Zahl", err)
            path = self.write(tmp, testbeispiel([q("30.09.2026", "Q3 2026", revenue=1.0)]))
            code, _, err = run(["TEST.DE", "--quartale", path])
            self.assertIn("kein Datum", err)
            path = self.write(tmp, testbeispiel([q("2026-09-30", "Q3 2026", revenue=1.0)]))
            code, _, err = run(["SAP.DE", "--quartale", path])
            self.assertEqual(code, 2)
            self.assertIn("gehört zu TEST.DE", err)


if __name__ == "__main__":
    unittest.main()
