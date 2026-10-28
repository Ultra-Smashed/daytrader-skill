import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

news = load("dt-news", "news")
markt = news.markt
DIR = os.path.join(FIX, "dt-news")
UNIVERSE = os.path.join(DIR, "universe.txt")
NOW = "2026-10-14T00:00:00+00:00"
NOW_DE = "2026-10-28T10:10:00+01:00"  # die XETRA-Fixtures wurden am 28.10.2026 bis 10:13 Uhr aufgezeichnet
UTC = datetime.timezone.utc


def raw(name):
    with open(os.path.join(DIR, name), "rb") as fh:
        return fh.read()


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = news.main(args)
    return code, out.getvalue(), err.getvalue()


def adhoc_entries():
    return news.parse_adhoc(raw("adhocnews.xml"))


class Feeds(unittest.TestCase):
    def test_yahoo_rss(self):
        items = news.parse_rss(raw("yahoo-AAPL.xml"), "AAPL")
        self.assertEqual(len(items), 6)
        first = items[0]
        self.assertEqual(first["title"], "Apple may have a way to dominate the smart home space")
        self.assertEqual(first["time"], datetime.datetime(2026, 10, 13, 19, 46, 52, tzinfo=UTC))
        self.assertTrue(first["link"].startswith("https://finance.yahoo.com/"))
        self.assertTrue(first["id"].startswith("rss:"))

    def test_yahoo_rss_german(self):
        items = news.parse_rss(raw("yahoo-SAP.DE.xml"), "SAP.DE")
        self.assertEqual(len(items), 18)
        self.assertEqual(items[0]["title"],
                         "Neues Angebot von Redwood Software wird als SAP-Lösungserweiterung vertrieben.")
        self.assertEqual(items[0]["time"], datetime.datetime(2026, 10, 26, 7, 0, tzinfo=UTC))
        self.assertTrue(items[0]["link"].startswith("https://de.finance.yahoo.com/nachrichten/"))

    def test_sec_atom_8k(self):
        items = news.parse_sec_atom(raw("sec-8-K-0000320193.xml"), "AAPL")
        self.assertEqual([i["form"] for i in items], ["8-K/A", "8-K", "8-K"])
        earn = items[1]
        self.assertEqual(earn["items"], ["2.02", "9.01"])
        self.assertTrue(earn["important"])
        self.assertEqual(earn["title"], "Apple Inc. hat ein 8-K eingereicht: Geschäftszahlen")
        self.assertEqual(earn["id"], "sec:0000320193-26-000018")
        self.assertIn("000032019326000018", earn["link"])
        # 16:30:28 New Yorker Zeit ist 20:30:28 UTC
        self.assertEqual(earn["time"].isoformat(), "2026-07-30T20:30:28+00:00")
        self.assertEqual(items[0]["title"], "Apple Inc. hat ein 8-K/A eingereicht: Wechsel in Vorstand oder Aufsichtsrat")

    def test_times(self):
        self.assertEqual(news.parse_time("Tue, 13 Oct 2026 20:02:03 +0000").hour, 20)
        self.assertEqual(news.parse_time("2026-09-01T16:30:35-04:00").hour, 20)
        self.assertIsNone(news.parse_time("soon"))

    def test_yahoo_symbols(self):
        self.assertEqual(news.yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(news.yahoo_symbol("SAP.DE"), "SAP.DE")
        self.assertEqual(news.yahoo_symbol("1COV.DE"), "1COV.DE")


class AdHoc(unittest.TestCase):
    def test_parse_feed(self):
        items = adhoc_entries()
        self.assertEqual(len(items), 20)
        kap = [i for i in items if "70421861" in i["link"]][0]
        self.assertEqual(kap["kind"], "adhoc")
        self.assertTrue(kap["important"])
        self.assertEqual(kap["title"], "EQS-Adhoc: KAP AG PASST PROGNOSE FÜR DAS GESCHÄFTSJAHR 2026 AN (deutsch)")
        self.assertIn("Insiderinformation", kap["summary"])
        self.assertEqual(kap["source"], "ad-hoc-news.de")
        self.assertTrue(kap["feed_time"])
        corp = [i for i in items if "70421865" in i["link"]][0]
        self.assertEqual((corp["issuer"], corp["isin"]), ("KAP AG", "DE0006208408"))
        self.assertEqual(corp["kind"], "corporate")
        self.assertEqual(corp["title"], "KAP AG PASST PROGNOSE FÜR DAS GESCHÄFTSJAHR 2026 AN")
        dorma = [i for i in items if "70424096" in i["link"]][0]
        self.assertTrue(dorma["title"].endswith("(deutsch)"))
        self.assertEqual(sum(1 for i in items if i["kind"] == "adhoc"), 7)

    def test_feed_offset_is_taken_literally(self):
        # Der Feed schreibt 07:00:23+02:00, obwohl am 28.10. MEZ (+01:00) gilt: wörtlich genommen 05:00:23 UTC
        straumann = [i for i in adhoc_entries() if "70424155" in i["link"]][0]
        self.assertEqual(straumann["time"], datetime.datetime(2026, 10, 28, 5, 0, 23, tzinfo=UTC))
        self.assertEqual(news.when_label(straumann["time"], "xetra", True), "28.10.2026 06:00 Uhr laut Feed")

    def test_universe(self):
        u = news.load_universe(UNIVERSE)
        self.assertEqual(u["SAP.DE"], {"name": "SAP SE O.N.", "isin": "DE0007164600"})
        self.assertEqual(u["IUR.DE"]["isin"], "DE0006208408")
        self.assertEqual(news.load_universe("/nonexistent.txt"), {})

    def test_match_by_isin(self):
        items = adhoc_entries()
        hits = [i for i in items if news.match_adhoc(i, "DE0006208408", None)]
        self.assertEqual(sorted(i["link"][-8:] for i in hits), ["70421865", "70421866"])

    def test_match_by_name(self):
        items = adhoc_entries()

        def hits(name):
            rx = news.name_pattern(name)
            return sorted(i["link"][-8:] for i in items if news.match_adhoc(i, None, rx))

        self.assertEqual(hits("KAP AG  INH O.N."), ["70421861", "70421865", "70421866"])
        self.assertEqual(hits("STRAUMANN HLDG NA SF 0,01"), ["70424155"])
        # XETRA führt dormakaba unter CH1486524122, der Feed unter CH0011795959: der Name trägt
        self.assertEqual(hits("DORMAKABA HLDG NA.SF 0,01"), ["70424096", "70424098", "70424101"])
        self.assertEqual(hits("SAP SE O.N."), [])

    def test_name_pattern_is_robust(self):
        def hit(name, text):
            return bool(news.name_pattern(name).search(news.fold(text)))

        self.assertTrue(hit("BAY.MOTOREN WERKE AG ST", "Bayerische Motoren Werke AG: Quartalsmitteilung"))
        self.assertTrue(hit("DT.TELEKOM AG NA", "Deutsche Telekom AG / DE0005557508"))
        self.assertTrue(hit("MUENCH.RUECKVERS. NA O.N.", "Münchener Rückversicherungs-Gesellschaft AG"))
        self.assertTrue(hit("SAP SE O.N.", "EQS-Adhoc: SAP SE: Prognose angehoben"))
        self.assertTrue(hit("sap se", "SAP SE / DE0007164600"))
        self.assertFalse(hit("SAP SE O.N.", "Neues Angebot wird als SAP-Lösungserweiterung vertrieben"))
        self.assertFalse(hit("KAP AG  INH O.N.", "Kapitalerhöhung erfolgreich abgeschlossen"))
        self.assertFalse(hit("SIEMENS AG  NA O.N.", "Neues Quartier in der Siemensstadt"))

    def test_ticker_gets_its_adhoc_on_top(self):
        tmp = tempfile.mkdtemp()
        base = ["--offline", DIR, "--state", os.path.join(tmp, "s.json"), "--now", NOW_DE,
                "--portfolio", "/x", "--watchlist", "/x", "--plan", "/x", "--dry-run", "--no-moves"]
        code, out, err = run(["--tickers", "IUR.DE", "--isin", "DE0006208408", "--universe", "/none",
                              "--json"] + base)
        data = json.loads(out)
        self.assertEqual([i["kind"] for i in data["items"]], ["corporate", "corporate"])
        code, out, err = run(["--tickers", "IUR.DE", "--name", "KAP AG", "--universe", "/none",
                              "--json"] + base)
        data = json.loads(out)
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["items"][0]["tags"][:2], ["adhoc", "guidance"])
        self.assertEqual(data["items"][0]["time"], "2026-10-27T15:15:32+00:00")
        self.assertEqual({t for i in data["items"] for t in i["touches"]}, {"IUR.DE"})
        code, out, err = run(["--tickers", "IUR.DE", "SAP.DE", "--universe", UNIVERSE] + base)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("! 27.10.2026 16:15 Uhr laut Feed  IUR.DE"), lines[0])
        self.assertIn("Themen: Ad-hoc, Prognose", lines[1])
        code, _, err = run(["--tickers", "IUR.DE", "SAP.DE", "--isin", "DE0006208408"] + base)
        self.assertEqual(code, 2)
        self.assertIn("SYMBOL=WERT", err)
        code, out, _ = run(["--tickers", "IUR.DE", "SAP.DE", "--isin", "IUR.DE=DE0006208408",
                            "--universe", "/none", "--json"] + base)
        self.assertEqual(len([i for i in json.loads(out)["items"] if i["ticker"] == "IUR.DE"]), 2)

    def test_alle_adhoc(self):
        code, out, err = run(["--alle-adhoc", "--hours", "12", "--offline", DIR, "--universe", UNIVERSE,
                              "--now", NOW_DE, "--dry-run", "--json", "--state", "/nonexistent/s.json",
                              "--portfolio", "/x", "--watchlist", "/x", "--plan", "/x"])
        self.assertEqual(code, 0, err)
        items = json.loads(out)["items"]
        self.assertEqual(len(items), 6)  # KAP liegt weiter als 12 Stunden zurück
        self.assertTrue(all("adhoc" in i["tags"] for i in items))
        by = {i["link"][-8:]: i["ticker"] for i in items}
        self.assertEqual(by["70424155"], "QS51.DE")
        self.assertEqual(by["70424096"], "KAB0.DE")
        self.assertEqual(by["70424212"], "")


class Tagging(unittest.TestCase):
    def test_touches_and_tags(self):
        items = news.parse_rss(raw("yahoo-KO.xml"), "KO")
        watch = {"KO": "Coca-Cola", "CVX": "Chevron", "AAPL": "Apple"}
        news.tag(items, watch)
        by = {i["title"][:20]: i for i in items}
        chevron = by["Coca-Cola or Chevron"]
        self.assertEqual(chevron["touches"], ["CVX", "KO"])
        self.assertIn("capital", chevron["tags"])  # dividend
        self.assertEqual(by["Is Coca-Cola (KO) St"]["touches"], ["KO"])

    def test_earnings_filings_are_tagged(self):
        items = news.tag(news.parse_sec_atom(raw("sec-8-K-0000021344.xml"), "KO"), {"KO": None})
        self.assertEqual(items[0]["tags"][0], "earnings")
        self.assertFalse(items[1]["important"])  # 8.01 sonstige Ereignisse

    def test_dedupe_merges_the_same_story(self):
        a = news.parse_rss(raw("yahoo-AAPL.xml"), "AAPL")
        b = news.parse_rss(raw("yahoo-AAPL.xml"), "GOOGL")
        items = news.dedupe(news.tag(a + b, {"AAPL": None, "GOOGL": None}))
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["touches"], ["AAPL", "GOOGL"])

    def test_day_trading_tags(self):
        items = [{"id": "x", "source": "Yahoo Finance", "kind": "headline", "ticker": "TSLA",
                  "title": "Trading halted in XYZ after FDA approval; futures rise before CPI",
                  "summary": "", "link": "", "time": None}]
        tags = news.tag(items, {"TSLA": None})[0]["tags"]
        for t in ("halt", "regulatory", "macro"):
            self.assertIn(t, tags)

    def test_german_tags(self):
        cases = {
            "BMW legt Quartalszahlen vor: EBIT über den Erwartungen": "earnings",
            "Quartalsmitteilung Q3: Umsatz steigt um 4 %": "earnings",
            "Halbjahresbericht 2026 veröffentlicht": "earnings",
            "Gewinnwarnung: Zulieferer senkt Prognose für 2026": "guidance",
            "Prognoseanhebung nach starkem Quartal": "guidance",
            "Straumann bestätigt Ausblick für das Gesamtjahr": "guidance",
            "Übernahmeangebot für Rivalen": "deal",
            "Fusion mit dem Konkurrenten geplant": "deal",
            "Verkauf von Sparte an Finanzinvestor": "deal",
            "Beteiligung an Start-up aufgestockt": "deal",
            "Kapitalerhöhung erfolgreich abgeschlossen": "capital",
            "Aktienrückkauf beschlossen": "capital",
            "Hauptversammlung beschließt Dividende von 2,50 Euro": "capital",
            "Directors' Dealings: Vorstand kauft Aktien": "insider",
            "Eigengeschäfte von Führungskräften nach Art. 19 MAR": "insider",
            "Stimmrechtsmitteilung nach § 33 WpHG": "voting",
            "EQS-Adhoc: Veröffentlichung einer Insiderinformation": "adhoc",
        }
        for title, label in cases.items():
            it = {"id": title, "source": "x", "kind": "headline", "ticker": "SAP.DE", "title": title,
                  "summary": "", "link": "", "time": None}
            self.assertIn(label, news.tag([it], {"SAP.DE": None})[0]["tags"], title)
        it = {"id": "y", "source": "x", "kind": "headline", "ticker": "SAP.DE", "summary": "", "link": "",
              "title": "Aktien Frankfurt Ausblick: Moderat aufwärts vor Jackson Hole", "time": None}
        self.assertNotIn("guidance", news.tag([it], {"SAP.DE": None})[0]["tags"])

    def test_german_display_and_insider_hint(self):
        t = datetime.datetime(2026, 10, 28, 8, 4, tzinfo=UTC)
        it = {"id": "z", "source": "Yahoo Finance", "kind": "headline", "ticker": "SAP.DE",
              "title": "Directors' Dealings: SAP-Vorstand kauft Aktien", "summary": "", "link": "L", "time": t}
        news.tag([it], {"SAP.DE": None})
        it["new"] = True
        out = news.render([it], [], t, m="xetra")
        self.assertIn("  28.10.2026 09:04 Uhr  SAP.DE", out)
        self.assertIn("Themen: Eigengeschäfte", out)
        self.assertIn("/dt-insider", out)
        self.assertNotIn("insider", out.replace("/dt-insider", ""))

    def test_xetra_mentions_by_name(self):
        it = {"id": "m", "source": "x", "kind": "headline", "ticker": "SAP.DE", "summary": "", "link": "",
              "title": "Bayerische Motoren Werke AG hebt die Prognose an", "time": None}
        watch = {"SAP.DE": None, "BMW.DE": "BAY.MOTOREN WERKE AG ST"}
        self.assertEqual(news.tag([it], watch)[0]["touches"], ["BMW.DE", "SAP.DE"])


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state", "news.json")
        self.base = ["--offline", DIR, "--state", self.state, "--now", NOW,
                     "--portfolio", os.path.join(self.tmp.name, "none.json"),
                     "--watchlist", os.path.join(self.tmp.name, "none.json"),
                     "--plan", os.path.join(self.tmp.name, "none.json"),
                     "--universe", UNIVERSE]

    def tearDown(self):
        self.tmp.cleanup()

    def de(self, args):
        a = list(self.base)
        a[a.index("--now") + 1] = NOW_DE
        return run(args + a)

    def test_new_items_once_newest_first(self):
        code, out, err = run(["--tickers", "AAPL", "KO", "--hours", "24", "--json"] + self.base)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        times = [i["time"] for i in data["items"]]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(len(data["items"]), 10)  # 6 Apple + 4 Coca-Cola, die Meldungen sind älter
        code, out, _ = run(["--tickers", "AAPL", "KO", "--hours", "24"] + self.base)
        self.assertEqual(code, 1)
        self.assertIn("Nichts Neues.", out)

    def test_filings_show_in_a_wider_window(self):
        code, out, err = run(["--tickers", "AAPL", "--hours", "2400"] + self.base)
        self.assertEqual(code, 0, err)
        self.assertIn("! 30.07.2026 16:30 ET (22:30 Uhr)  AAPL", out)  # 20:30 UTC
        self.assertIn("Geschäftszahlen", out)
        self.assertIn("Keine Anlageberatung", out)
        self.assertNotIn(chr(0x2014), out)

    def test_tickers_from_watchlist_and_plan(self):
        wl = os.path.join(self.tmp.name, "watchlist.json")
        with open(wl, "w") as fh:
            json.dump({"created_by": "dt-scanner", "hits": [{"symbol": "KO", "setups": ["orb"]}]}, fh)
        plan = os.path.join(self.tmp.name, "plan.json")
        with open(plan, "w") as fh:
            json.dump({"created_by": "dt-ausstieg", "symbol": "AAPL"}, fh)
        self.assertEqual(sorted(news.watch_from_files("/nonexistent.json", wl, plan)), ["AAPL", "KO"])
        args = list(self.base)
        args[args.index("--watchlist") + 1] = wl
        code, out, err = run(["--json", "--dry-run", "--hours", "24"] + args)
        self.assertEqual(code, 0, err)
        tickers = {t for i in json.loads(out)["items"] for t in i["touches"]}
        self.assertEqual(tickers, {"KO"})
        self.assertFalse(os.path.exists(self.state))

    def test_watchlist_with_xetra_hits(self):
        wl = os.path.join(self.tmp.name, "watchlist.json")
        with open(wl, "w") as fh:
            json.dump({"created_by": "dt-scanner", "hits": [{"symbol": "SAP.DE"}, {"symbol": "QS51.DE"}]}, fh)
        args = list(self.base)
        args[args.index("--watchlist") + 1] = wl
        args[args.index("--now") + 1] = NOW_DE
        code, out, err = run(["--json", "--dry-run", "--hours", "30", "--no-moves"] + args)
        self.assertEqual(code, 0, err)
        items = json.loads(out)["items"]
        self.assertEqual(items[0]["ticker"], "QS51.DE")
        self.assertEqual(items[0]["tags"][0], "adhoc")
        self.assertIn("SAP.DE", {i["ticker"] for i in items})

    def test_no_tickers_is_an_error(self):
        code, _, err = run(self.base)
        self.assertEqual(code, 2)
        self.assertIn("keine Ticker", err)

    def test_sec_needs_a_user_agent(self):
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            self.assertIsNone(news.sec_user_agent(None, "/nonexistent.json"))
            self.assertIsNone(news.sec_user_agent("Your Name you@example.com"))
            self.assertIsNone(news.sec_user_agent("Dein Name du@example.com"))
            self.assertEqual(news.sec_user_agent("Ada ada@example.org"), "Ada ada@example.org")
            with self.assertRaises(news.NewsError):
                news.Fetcher(None).get("https://www.sec.gov/x", "x", sec=True)
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old

    def test_sources_per_market(self):
        calls = []

        class Spy(news.Fetcher):
            def get(self, url, name, sec=False):
                calls.append(url)
                return news.Fetcher.get(self, url, name, sec)

        errors = []
        f = Spy("Ada ada@example.org", offline=DIR)
        watch = {"SAP.DE": None, "AAPL": None}
        news.collect(f, watch, {}, errors=errors, universe=news.load_universe(UNIVERSE))
        self.assertIn(news.YAHOO_DE % "SAP.DE", calls)
        self.assertIn("region=DE&lang=de-DE", news.YAHOO_DE)
        self.assertIn(news.YAHOO % "AAPL", calls)
        self.assertIn(news.ADHOC_FEED, calls)
        self.assertEqual(len([c for c in calls if "sec.gov/cgi-bin" in c]), 1)  # nur AAPL
        self.assertFalse([e for e in errors if "SAP.DE" in e], errors)
        calls[:] = []
        news.collect(f, {"AAPL": None}, {}, errors=[])
        self.assertNotIn(news.ADHOC_FEED, calls)
        code, out, _ = run(["--tickers", "SAP.DE", "--hours", "30", "--no-moves"] + self.base[:2] +
                           ["--state", self.state, "--now", NOW_DE, "--universe", UNIVERSE])
        self.assertNotIn("SEC", out)

    def test_the_reel_tsla_morning(self):
        # Der echte Feed aus dem Reel: Yahoo-Finance-Schlagzeilen zu TSLA, Montag 19.10.2026, geprüft um 10:15 ET
        code, out, err = run(["--tickers", "TSLA", "--hours", "6", "--no-sec", "--no-moves",
                              "--now", "2026-10-19T10:15:00-04:00"] + self.base[:4])
        self.assertEqual(code, 0, err)
        self.assertIn("19.10.2026 08:04 ET (14:04 Uhr)  TSLA", out)
        self.assertNotIn("10:32 ET", out)  # nach der festen Uhr 10:15 veröffentlicht
        self.assertIn("Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings", out)
        merger = [l for l in out.splitlines() if "Merger Mania" in l]
        tags = out.splitlines()[out.splitlines().index(merger[0]) + 1]
        self.assertIn("Zahlen", tags)
        self.assertIn("Übernahme/Deal", tags)
        self.assertIn("Geprüft 19.10.2026 10:15 ET (16:15 Uhr)", out)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("  19.10.2026")]), 16)  # 18 im Feed, 2 nach 10:15
        self.assertIn("Berichtstermin TSLA:", out)
        self.assertIn("ein Daytrade ist vor Handelsschluss um 16:00 ET (22:00 Uhr) raus", out)
        # die Kurszeile, aus dem Chart von 10:52
        code, out, err = run(["--tickers", "TSLA", "--hours", "6", "--no-sec", "--dry-run",
                              "--now", "2026-10-19T10:52:00-04:00"] + self.base[:4])
        self.assertRegex(out, r"TSLA\s+366,4[78] \+3,31 % zum Vortagesschluss 354,72, Stand 10:52 ET \(16:52 Uhr\)  BEWEGT")

    def test_moves(self):
        m = news.parse_chart(raw("chart-TSLA.json"), "TSLA")
        self.assertEqual(m["prev_close"], 354.72)
        self.assertEqual(m["pct"], 3.31)
        self.assertEqual(markt.clock(markt.to_local(m["time"], "us")), "10:52")
        quiet = dict(m, pct=1.2)
        self.assertNotIn("BEWEGT", news.render_moves([quiet])[0])
        self.assertIn("BEWEGT", news.render_moves([quiet], move_pct=1.0)[0])
        with self.assertRaises(news.NewsError):
            news.parse_chart(b'{"chart": {"result": null}}', "ZZZZ")
        # ohne Chart-Datei offline: keine Kurszeile, kein Hinweis
        code, out, _ = run(["--tickers", "KO", "--hours", "24", "--dry-run"] + self.base)
        self.assertNotIn("Vortagesschluss", out)
        self.assertNotIn("Hinweis:", out)

    def test_moves_xetra(self):
        m = news.parse_chart(raw("chart-SAP.DE.json"), "SAP.DE")
        self.assertEqual((m["price"], m["prev_close"], m["pct"]), (211.2, 213.15, -0.91))
        self.assertEqual(news.render_moves([m])[0],
                         "SAP.DE  211,20 -0,91 % zum Vortagesschluss 213,15, Stand 09:56 Uhr  ")

    def test_mixed_xetra_and_us(self):
        code, out, err = self.de(["--tickers", "TSLA", "SAP.DE", "QS51.DE", "KAB0.DE", "--hours", "30",
                                  "--no-sec", "--dry-run"])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("SAP.DE  211,20 -0,91 %"))
        self.assertIn("TSLA    366,48 +3,31 % zum Vortagesschluss 354,72, Stand 10:52 ET (16:52 Uhr)  BEWEGT", lines[1])
        items = [l for l in lines if l[:2] in ("! ", "  ") and l[2:3].isdigit()]
        self.assertTrue(items[0].startswith("! 28.10.2026 06:00 Uhr laut Feed  QS51.DE"), items[0])
        self.assertTrue(items[1].startswith("! 28.10.2026 05:30 Uhr laut Feed  KAB0.DE"), items[1])
        self.assertIn("  28.10.2026 00:10 Uhr  SAP.DE      Yahoo Finance   Andersen Consulting", out)
        self.assertIn("Geprüft 28.10.2026 10:10 Uhr.", out)
        code, out, err = self.de(["--tickers", "TSLA", "SAP.DE", "--hours", "240", "--no-sec",
                                  "--no-moves", "--dry-run", "--json"])
        data = json.loads(out)
        self.assertEqual({i["ticker"] for i in data["items"]}, {"TSLA", "SAP.DE"})
        self.assertEqual([i["time"] for i in data["items"]], sorted((i["time"] for i in data["items"]), reverse=True))
        code, out, err = self.de(["--tickers", "TSLA", "SAP.DE", "--hours", "240", "--no-sec",
                                  "--no-moves", "--dry-run"])
        self.assertIn("  22.10.2026 15:08 Uhr  SAP.DE", out)  # 13:08 UTC, noch Sommerzeit
        self.assertIn("  19.10.2026 08:04 ET (14:04 Uhr)  TSLA", out)
        self.assertEqual(markt.current(), "us")  # main() stellt den Markt wieder her

    def test_report_hint_xetra(self):
        now = datetime.datetime(2026, 10, 28, 9, 10, tzinfo=UTC)
        it = {"id": "r", "source": "Yahoo Finance", "kind": "headline", "ticker": "SAP.DE", "link": "",
              "title": "SAP legt am Donnerstag Quartalszahlen vor", "summary": "", "time": now}
        news.tag([it], {"SAP.DE": None})
        self.assertTrue(it["report_hint"])
        out = news.render([it], [], now, m="xetra")
        self.assertIn("Berichtstermin SAP.DE:", out)
        self.assertIn("vor Handelsschluss um 17:30 Uhr raus", out)
        early = datetime.datetime(2026, 12, 30, 9, 0, tzinfo=UTC)
        self.assertIn("um 14:00 Uhr raus", news.render([dict(it, time=early)], [], early, m="xetra"))
        it2 = dict(it, title="SAP-Chef sieht historische Wachstumschance", id="r2")
        news.tag([it2], {"SAP.DE": None})
        self.assertFalse(it2["report_hint"])

    def test_bad_now_is_an_error(self):
        code, _, err = run(["--tickers", "SAP.DE", "--now", "morgen"] + self.base[:4])
        self.assertEqual(code, 2)
        self.assertIn("--now", err)

    def test_naive_now_is_market_time(self):
        code, out, _ = run(["--tickers", "SAP.DE", "--hours", "30", "--no-moves", "--dry-run",
                            "--now", "2026-10-28 10:10"] + self.base[:4] + ["--universe", UNIVERSE])
        self.assertIn("Geprüft 28.10.2026 10:10 Uhr.", out)

    def test_market_time_follows_daylight_saving(self):
        utc = datetime.datetime(2026, 1, 15, 15, 0, tzinfo=UTC)
        self.assertEqual(markt.to_local(utc, "us").hour, 10)  # EST, UTC-5
        utc = datetime.datetime(2026, 10, 19, 14, 15, tzinfo=UTC)
        self.assertEqual(markt.to_local(utc, "us").hour, 10)  # EDT, UTC-4
        utc = datetime.datetime(2026, 11, 1, 6, 30)            # 1:30 EST, kurz nach der Umstellung
        self.assertEqual(markt.to_local(utc, "us").hour, 1)
        utc = datetime.datetime(2026, 10, 28, 8, 4, tzinfo=UTC)
        self.assertEqual(news.when_label(utc, "xetra"), "28.10.2026 09:04 Uhr")  # MEZ seit 25.10.
        self.assertEqual(news.when_label(utc, "us"), "28.10.2026 04:04 ET (09:04 Uhr)")  # 5 Stunden bis 01.11.

    def test_state_forgets_after_30_days(self):
        state = {"seen": {"old": "2026-08-01T00:00:00+00:00"}}
        now = news.parse_time(NOW)
        news.remember([], state, now)
        self.assertNotIn("old", state["seen"])
        self.assertEqual(state["last_check"], now.isoformat())


if __name__ == "__main__":
    unittest.main()
