#!/usr/bin/env python3
"""Quartalszahlen-Leser für dt-analyst. Nur Standardbibliothek.

Liest die gemeldeten Zahlen einer Firma und zeigt, was sich Quartal für
Quartal geändert hat: Umsatz, Brutto-, operative und Nettomarge,
Nettoergebnis, verwässertes EPS und Wachstum gegenüber dem Vorjahresquartal,
dazu die letzten zwölf Monate (TTM).

    python3 facts.py AAPL
    python3 facts.py AAPL KO --quarters 8
    python3 facts.py AAPL --json
    python3 facts.py AAPL AXP GOOGL KO BAC --metrics trader/metrics.json
    python3 facts.py SAP.DE
    python3 facts.py SAP.DE --quartale trader/quartale/SAP.DE.json

US-Firmen (SEC; ein User-Agent mit Name und E-Mail ist Pflicht, aus
--user-agent, SEC_USER_AGENT oder sec_user_agent in trader/config.json):
  https://www.sec.gov/files/company_tickers.json            Ticker -> CIK
  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
  https://data.sec.gov/submissions/CIK##########.json        Filing-Liste
  https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/index.json
Dazu die neueste Pressemitteilung zu den Zahlen (EX-99 des neuesten 8-K mit
Item 2.02) und der neueste 10-Q oder 10-K.

So entstehen die US-Quartale:
  - Ein Quartal ist ein gemeldeter Wert über etwa drei Monate (80 bis 100
    Tage). Wurde ein Zeitraum mehrfach gemeldet (ein späteres Filing
    wiederholt ihn als Vergleich), gewinnt das neueste Filing, also zählen
    Korrekturen.
  - Für das vierte Quartal gibt es keinen 10-Q. Es ist das Geschäftsjahr
    (10-K) minus die drei Quartale darin und als "abgeleitet" markiert.
    Abgeleitetes EPS ist nur ungefähr: die Aktienzahl ändert sich im Jahr.
  - Der Umsatz kommt aus dem ersten Konzept, das die Firma nutzt:
    RevenueFromContractWithCustomerExcludingAssessedTax, Revenues,
    RevenuesNetOfInterestExpense, SalesRevenueNet und ein paar weitere.
    Banken und Versicherer melden Umsatz anders; Margen bleiben dort leer.

Deutsche Firmen (Symbol mit .DE): Es gibt keine freie maschinenlesbare
Quelle. Die Zahlen stehen von Hand übertragen in trader/quartale/<SYMBOL>.json
(Schema: quartale.example.json). Fehlt die Datei, erklärt das Tool den Weg
und endet mit Exit-Code 1.

--metrics DATEI führt je Ticker eine Zeile in eine JSON-Datei zusammen (für
Notizen oder eine Tabelle: TTM-Umsatz und -EPS, Margen, Wachstum). Offline:
--offline ORDNER liest company_tickers.json, companyfacts-CIK##########.json,
submissions-CIK##########.json und <accession>/index.json aus ORDNER.

Nur Zahlen: Dieses Tool sagt nie, ob eine Aktie ein Kauf ist.
"""

import argparse
import datetime as _dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markt  # noqa: E402

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK%s.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/%d/%s/"
PLACEHOLDERS = ("you@example.com", "du@example.com")
PLACEHOLDER = PLACEHOLDERS[0]
UA_HELP = ("Die SEC verlangt einen User-Agent mit deinem Namen und deiner E-Mail. Trag "
           "\"sec_user_agent\": \"Dein Name du@example.com\" in trader/config.json ein (mit deinem "
           "echten Namen und deiner echten E-Mail), oder setz SEC_USER_AGENT, oder gib --user-agent mit.")

CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenuesNetOfInterestExpense", "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueNet", "SalesRevenueGoodsNet", "SalesRevenueServicesNet"],
    "cost_of_revenue": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
}
FLOWS = ("revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income")

QUARTALE_DIR = os.path.join("trader", "quartale")
DE_FIELDS = ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted")
DE_LABELS = {"revenue": "Umsatz", "gross_profit": "Bruttoergebnis", "operating_income": "EBIT",
             "net_income": "Nettoergebnis", "eps_diluted": "EPS verwässert"}
DE_SOURCE = "Quartalsmitteilung (manuell)"
DE_HINT = "Quelle: Quartalsmitteilung, von Hand übertragen, prüfe die Seitenangabe."


class FactsError(Exception):
    pass


def user_agent(cli=None, config="trader/config.json"):
    ua = (cli or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua and config and os.path.isfile(config):
        try:
            with open(config, encoding="utf-8") as fh:
                ua = str(json.load(fh).get("sec_user_agent") or "").strip()
        except (OSError, ValueError):
            ua = ""
    if not ua or "@" not in ua or any(p in ua.lower() for p in PLACEHOLDERS):
        return None
    return ua


class Fetcher(object):
    def __init__(self, ua=None, offline=None, pause=0.15):
        self.ua, self.offline, self.pause, self._last = ua, offline, pause, 0.0

    def json(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise FactsError("offline: keine Datei %s" % path)
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        if not self.ua:
            raise FactsError(UA_HELP)
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua,
                                                   "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FactsError("die SEC hat keine Daten unter %s (keine XBRL-Filings für diese CIK?)" % url)
            raise FactsError("HTTP %s für %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            raise FactsError("%s nicht erreichbar: %s" % (url, exc.reason))
        return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------- facts

def _date(s):
    return _dt.date.fromisoformat(s)


def _de(s):
    return markt.date_de(_date(s)) if s else "-"


def facts_for(companyfacts, concept, unit_hint=None):
    """Rohwerte für ein us-gaap-Konzept (USD, oder USD/shares für EPS)."""
    node = companyfacts.get("facts", {}).get("us-gaap", {}).get(concept)
    if not node:
        return []
    units = node.get("units", {})
    unit = unit_hint if unit_hint in units else next(iter(units), None)
    return units.get(unit, []) if unit else []


def periods(facts):
    """{(start, end): fact} für Zeitraumwerte aus 10-Q/10-K.

    Der Wert kommt aus dem neuesten Filing (Korrekturen gewinnen). Das
    Geschäftsjahr-Label (fy, fp) kommt aus dem ersten Filing, das den Zeitraum
    gemeldet hat: ein späterer 10-Q, der ihn als Vergleich wiederholt, trägt
    sein eigenes fy und fp."""
    latest, first = {}, {}
    for f in facts:
        if "start" not in f or f.get("form", "").split("/")[0] not in ("10-Q", "10-K", "20-F", "40-F"):
            continue
        key = (f["start"], f["end"])
        stamp = (f.get("filed", ""), f.get("accn", ""))
        if key not in latest or stamp > (latest[key].get("filed", ""), latest[key].get("accn", "")):
            latest[key] = f
        if key not in first or stamp < (first[key].get("filed", ""), first[key].get("accn", "")):
            first[key] = f
    out = {}
    for key, f in latest.items():
        g = dict(f)
        g["fy"], g["fp"] = first[key].get("fy"), first[key].get("fp")
        g["first_filed"] = first[key].get("filed")
        out[key] = g
    return out


def quarterly(facts, derive_q4=True):
    """{end: {"value", "start", "end", "derived", "fy", "fp", "form"}} Dreimonatswerte."""
    per = periods(facts)
    q = {}
    years = []
    for (start, end), f in per.items():
        days = (_date(end) - _date(start)).days
        if 80 <= days <= 100:
            q[end] = {"value": f["val"], "start": start, "end": end, "derived": False,
                      "fy": f.get("fy"), "fp": f.get("fp"), "form": f.get("form"),
                      "filed": f.get("filed")}
        elif 350 <= days <= 380:
            years.append((start, end, f))
    if derive_q4:
        for start, end, f in years:
            if end in q:
                continue
            inside = [v for v in q.values() if v["start"] >= start and v["end"] < end]
            inside.sort(key=lambda v: v["end"])
            if len(inside) != 3:
                continue
            last_q_start = _date(inside[-1]["end"]) + _dt.timedelta(days=1)
            q[end] = {"value": f["val"] - sum(v["value"] for v in inside),
                      "start": last_q_start.isoformat(), "end": end, "derived": True,
                      "fy": f.get("fy"), "fp": "Q4", "form": f.get("form"),
                      "filed": f.get("filed")}
    return q


def series(companyfacts, key, derive_q4=True):
    """Quartalsreihe einer Kennzahl: Konzepte der Reihe nach, Lücken werden gefüllt."""
    unit = "USD/shares" if key == "eps_diluted" else "USD"
    merged, used = {}, []
    for concept in CONCEPTS[key]:
        q = quarterly(facts_for(companyfacts, concept, unit), derive_q4)
        if not q:
            continue
        added = False
        for end, v in q.items():
            if end not in merged:
                merged[end] = dict(v, concept=concept)
                added = True
        if added:
            used.append(concept)
    return merged, used


def _yoy_match(series_, end, days=365, slack=10):
    target = _date(end) - _dt.timedelta(days=days)
    best = None
    for e in series_:
        gap = abs((_date(e) - target).days)
        if gap <= slack and (best is None or gap < best[0]):
            best = (gap, e)
    return series_[best[1]] if best else None


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round(100.0 * (a - b) / abs(b), 1)


def margin(part, whole):
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, 1)


def build(s, quarters=6, ends=None):
    """Zeilen und TTM aus Quartalsreihen {Kennzahl: {end: {"value", ...}}}."""
    rev = s["revenue"]
    if ends is None:
        ends = set(rev) | set(s["net_income"])
    ends = sorted(set(ends), reverse=True)[:quarters]
    rows = []
    for end in ends:
        r = rev.get(end, {}).get("value")
        gp = s["gross_profit"].get(end, {}).get("value")
        if gp is None and r is not None and end in s["cost_of_revenue"]:
            gp = r - s["cost_of_revenue"][end]["value"]
        oi = s["operating_income"].get(end, {}).get("value")
        ni = s["net_income"].get(end, {}).get("value")
        eps = s["eps_diluted"].get(end, {}).get("value")
        prior = {k: _yoy_match(s[k], end) for k in ("revenue", "net_income", "eps_diluted")}
        base = rev.get(end) or s["net_income"].get(end) or {}
        rows.append({
            "end": end, "start": base.get("start"),
            "fiscal": "%s %s" % (base.get("fp") or "", base.get("fy") or ""),
            "derived": any(s[k].get(end, {}).get("derived") for k in ("revenue", "net_income")),
            "revenue": r, "gross_profit": gp, "operating_income": oi, "net_income": ni,
            "eps_diluted": round(eps, 2) if eps is not None else None,
            "gross_margin": margin(gp, r), "operating_margin": margin(oi, r),
            "net_margin": margin(ni, r),
            "revenue_yoy": pct(r, (prior["revenue"] or {}).get("value")),
            "net_income_yoy": pct(ni, (prior["net_income"] or {}).get("value")),
            "eps_yoy": pct(eps, (prior["eps_diluted"] or {}).get("value")),
            "filed": base.get("filed"), "form": base.get("form"),
        })
    ttm = {}
    for key in ("revenue", "net_income", "eps_diluted"):
        last4 = sorted(s[key])[-4:]
        if len(last4) == 4 and (_date(last4[-1]) - _date(last4[0])).days < 300:
            ttm[key] = sum(s[key][e]["value"] for e in last4)
    if "eps_diluted" in ttm:
        ttm["eps_diluted"] = round(ttm["eps_diluted"], 2)
    return rows, ttm


def analyse(companyfacts, quarters=6, name=None):
    """Jede Zahl des Berichts, als dict."""
    s = {}
    concepts = {}
    for key in CONCEPTS:
        s[key], concepts[key] = series(companyfacts, key, derive_q4=True)
    if not s["revenue"] and not s["net_income"]:
        raise FactsError("keine Quartalswerte für Umsatz oder Nettoergebnis in den XBRL-Daten")
    rows, ttm = build(s, quarters)
    return {"entity": name or companyfacts.get("entityName"),
            "cik": str(companyfacts.get("cik", "")).zfill(10),
            "rows": rows, "ttm": ttm, "concepts": concepts}


# ---------------------------------------------------------------- German issuers

def quartale_path(sym, where=None):
    """trader/quartale/SAP.DE.json, oder die mit --quartale genannte Datei bzw. der Ordner."""
    where = where or QUARTALE_DIR
    if where.lower().endswith(".json") and not os.path.isdir(where):
        return where
    return os.path.join(where, sym.upper() + ".json")


def how_to(sym, path):
    """Der dokumentierte Weg, wenn für einen deutschen Emittenten keine Datei da ist."""
    root = sym.upper().split(".")[0]
    return "\n".join([
        "%s ist ein deutscher Emittent (XETRA). Unter %s liegen noch keine Quartalszahlen." % (sym, path),
        "",
        "Für deutsche Firmen gibt es keine freie maschinenlesbare Quelle: filings.xbrl.org (ESEF)",
        "führt für Deutschland keine Filings (geprüft am 28.10.2026), und Yahoos Fundamentaldaten",
        "sind ohne Anmeldung gesperrt. So kommen die Zahlen in die Datei:",
        "",
        "  1. Öffne die Investor-Relations-Seite der Firma (Suche: „%s Investor Relations" % root,
        "     Finanzberichte“) und dort den Bereich mit Quartalsmitteilungen und Berichten.",
        "  2. Lade die aktuelle Quartalsmitteilung bzw. den Halbjahres- oder Geschäftsbericht (PDF).",
        "     Amtliche Quelle für Jahres- und Halbjahresfinanzberichte ist das Unternehmensregister:",
        "     https://www.unternehmensregister.de",
        "  3. Lies in der Konzern-Gewinn- und Verlustrechnung das Quartal und das Vorjahresquartal:",
        "     Umsatz (revenue), Bruttoergebnis (gross_profit), operatives Ergebnis/EBIT",
        "     (operating_income), Ergebnis nach Steuern, den Aktionären zurechenbar (net_income),",
        "     verwässertes Ergebnis je Aktie (eps_diluted). Für die TTM vier Quartale in Folge.",
        "  4. Schreib sie nach %s, Schema wie quartale.example.json im Skill-Ordner." % path,
        "     Beträge in vollen Euro (10,27 Mrd. € = 10270000000), Zahlen ohne Anführungszeichen.",
        "     Was die Mitteilung nicht nennt, bleibt null. Nie raten, nie schätzen.",
        "     Zu jedem Quartal source (URL des PDFs), page (z. B. \"S. 8\") und basis (\"IFRS\").",
        "  5. Ruf danach erneut auf: python3 facts.py %s" % sym,
        "",
        "Den nächsten Berichtstermin nennt der Finanzkalender auf der IR-Seite; /dt-news zeigt",
        "Ad-hoc-Mitteilungen.",
    ]) + "\n"


def _number(v, field, label):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FactsError("%s: %s ist keine Zahl (%r). Schreib Zahlen ohne Anführungszeichen, "
                         "fehlende Werte als null." % (label, field, v))
    return v


def load_quartale(path, sym=None):
    """Die von Hand übertragene Quartalsdatei, geprüft."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise FactsError("%s ist kein gültiges JSON: %s" % (path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("quarters"), list):
        raise FactsError("%s: es fehlt die Liste \"quarters\" (Schema: quartale.example.json)" % path)
    own = str(data.get("symbol") or "").strip().upper()
    if sym and own and own != sym.upper():
        raise FactsError("%s gehört zu %s, nicht zu %s" % (path, own, sym.upper()))
    seen = set()
    for i, q in enumerate(data["quarters"]):
        label = "%s, Quartal %d" % (path, i + 1)
        if not isinstance(q, dict):
            raise FactsError("%s ist kein Objekt" % label)
        try:
            _date(str(q.get("period_end")))
        except ValueError:
            raise FactsError("%s: period_end %r ist kein Datum (JJJJ-MM-TT)" % (label, q.get("period_end")))
        if q["period_end"] in seen:
            raise FactsError("%s: period_end %s kommt doppelt vor" % (label, q["period_end"]))
        seen.add(q["period_end"])
        for k in DE_FIELDS:
            _number(q.get(k), k, label)
    if not data["quarters"]:
        raise FactsError("%s enthält noch keine Quartale" % path)
    return data


def analyse_quartale(data, quarters=6):
    """Dieselbe Auswertung wie analyse(), aus der Quartalsdatei eines deutschen Emittenten."""
    s = {k: {} for k in CONCEPTS}
    meta = {}
    for q in data["quarters"]:
        end = q["period_end"]
        meta[end] = q
        for k in DE_FIELDS:
            if q.get(k) is not None:
                s[k][end] = {"value": q[k], "start": None, "end": end, "derived": False,
                             "fy": None, "fp": None, "form": "Quartalsmitteilung", "filed": None}
    rows, ttm = build(s, quarters, ends=meta)
    for r in rows:
        q = meta[r["end"]]
        r["fiscal"] = str(q.get("period") or "")
        r["source"], r["page"], r["basis"] = q.get("source"), q.get("page"), q.get("basis")
        r["missing"] = [k for k in DE_FIELDS if q.get(k) is None]
    return {"entity": data.get("name"), "cik": None, "isin": data.get("isin"),
            "symbol": data.get("symbol"), "currency": str(data.get("currency") or "EUR").upper(),
            "kind": "quartale", "rows": rows, "ttm": ttm, "concepts": {}, "source": DE_SOURCE}


def stale_note(result, filings):
    """Ein Hinweis, wenn die SEC-Daten hinter einem schon eingereichten Bericht zurückliegen."""
    rep = (filings or {}).get("report")
    if not rep or not result["rows"] or not rep.get("period"):
        return None
    latest = result["rows"][0]["end"]
    if rep["period"] > latest and (_date(rep["period"]) - _date(latest)).days > 20:
        return ("Die XBRL-Daten der SEC enden am %s, aber ein %s für den Zeitraum bis %s wurde am %s "
                "eingereicht. Lies ihn direkt: %s" % (_de(latest), rep["form"], _de(rep["period"]),
                                                      _de(rep["filed"]), rep["url"]))
    return None


def _geld(v, cur="USD"):
    if v is None:
        return "k. A."
    sym = markt.SYMBOLS.get(cur, cur)
    if abs(v) >= 1e9:
        return "%s Mrd. %s" % (markt.num(v / 1e9, 2), sym)
    return "%s Mio. %s" % (markt.num(v / 1e6, 1), sym)


def _vz(v):
    return markt.pct(v, 1, sign=True)


def _punkte(d):
    d = round(d, 1)
    return "%s%s" % ("-" if d < 0 else "+", markt.num(abs(d), 1))


def changes(result):
    """Klare Sätze: was sich im letzten Quartal geändert hat."""
    rows = result["rows"]
    if not rows:
        return []
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    ccy = result.get("currency") or "USD"
    de = result.get("kind") == "quartale"
    out = []

    label = "Quartal bis %s" % _de(cur["end"])
    if de and cur.get("fiscal"):
        label += " (%s)" % cur["fiscal"]
    if cur.get("derived"):
        label += " (aus dem 10-K abgeleitet)"
    line = "%s: Umsatz %s" % (label, _geld(cur["revenue"], ccy))
    if cur["revenue_yoy"] is not None:
        line += " (%s gegenüber dem Vorjahresquartal)" % _vz(cur["revenue_yoy"])
    line += ", Nettoergebnis %s" % _geld(cur["net_income"], ccy)
    if cur["net_income_yoy"] is not None:
        line += " (%s)" % _vz(cur["net_income_yoy"])
    if cur["eps_diluted"] is not None:
        line += ", EPS verwässert %s" % markt.money(cur["eps_diluted"], ccy)
        if cur["eps_yoy"] is not None:
            line += " (%s)" % _vz(cur["eps_yoy"])
    out.append(line + ".")
    for key, name in (("gross_margin", "Bruttomarge"), ("operating_margin", "Operative Marge"),
                      ("net_margin", "Nettomarge")):
        if cur.get(key) is None:
            continue
        s = "%s %s" % (name, markt.pct(cur[key], 1))
        if prev and prev.get(key) is not None:
            s += " (%s Prozentpunkte gegenüber dem Vorquartal)" % _punkte(cur[key] - prev[key])
        out.append(s + ".")
    if cur["net_income"] is not None and cur["operating_income"] is not None \
            and cur["net_income"] > cur["operating_income"]:
        out.append("Das Nettoergebnis liegt über dem operativen Ergebnis (EBIT): Es enthält Erträge "
                   "außerhalb des Kerngeschäfts (Finanzergebnis, Beteiligungen, Steuereffekte). Prüfe %s, "
                   "bevor du es als Wachstum liest." % ("die Quartalsmitteilung" if de else "den 10-Q"))
    if prev and cur["revenue"] is not None and prev["revenue"]:
        out.append("Umsatz %s gegenüber dem Vorquartal (viele Geschäfte sind saisonal: vergleiche "
                   "zuerst mit dem Vorjahresquartal)." % _vz(pct(cur["revenue"], prev["revenue"])))
    return out


# ---------------------------------------------------------------- filings

EXHIBIT_RANK = [r"ex(?:hibit)?[-_]?99[-_.]?0?1(?!\d)", r"ex(?:hibit)?[-_]?99",
                r"earnings|release|press", r"ex(?:hibit)?[-_]?\d"]


def exhibit_name(names, primary=None):
    """Die Pressemitteilung unter den Dateien eines Filings (EX-99.1 nach den üblichen Namen)."""
    docs = [n for n in names if n.lower().endswith((".htm", ".html", ".txt", ".pdf"))
            and n != primary and not re.match(r"^(R\d+\.htm|\d{10}-\d{2}-\d{6})", n)]
    for rx in EXHIBIT_RANK:
        hits = sorted(n for n in docs if re.search(rx, n, re.I))
        if hits:
            return hits[0]
    return None


def latest_filings(submissions, cik, fetcher=None):
    """Neuester 10-Q/10-K und neuester Earnings-8-K (Item 2.02) mit seinem EX-99."""
    rec = submissions.get("filings", {}).get("recent", {})
    out = {"report": None, "earnings_8k": None}
    base_cik = int(cik)
    for i, form in enumerate(rec.get("form", [])):
        acc = rec["accessionNumber"][i]
        folder = ARCHIVE_URL % (base_cik, acc.replace("-", ""))
        if out["report"] is None and form in ("10-Q", "10-K", "20-F", "40-F"):
            out["report"] = {"form": form, "filed": rec["filingDate"][i],
                             "period": rec["reportDate"][i], "accession": acc,
                             "url": folder + rec["primaryDocument"][i]}
        if out["earnings_8k"] is None and form == "8-K" and "2.02" in (rec.get("items", [""] * (i + 1))[i] or ""):
            e = {"form": form, "filed": rec["filingDate"][i], "accession": acc,
                 "url": folder + rec["primaryDocument"][i], "exhibit": None,
                 "index": folder + "%s-index.htm" % acc}
            if fetcher is not None:
                try:
                    idx = fetcher.json(folder + "index.json", os.path.join(acc.replace("-", ""), "index.json"))
                    names = [it["name"] for it in idx.get("directory", {}).get("item", [])]
                    pick = exhibit_name(names, rec["primaryDocument"][i])
                    if pick:
                        e["exhibit"] = folder + pick
                except FactsError:
                    pass
            out["earnings_8k"] = e
        if out["report"] and out["earnings_8k"]:
            break
    return out


# ---------------------------------------------------------------- output

def _m(v):
    if v is None:
        return "-"
    return markt.num(v / 1e6, 0)


def _p(v):
    return "-" if v is None else _vz(v) if v < 0 or v > 0 else "0,0 %"


def _pm(v):
    return "-" if v is None else markt.pct(v, 1)


def _table(result):
    out = ["%-12s %-9s %10s %9s %7s %7s %7s %10s %9s %8s" % (
        "Quartalsende", "GJ", "Umsatz", "Umsatz VJ", "Brutto", "Oper.", "Netto",
        "Nettoerg.", "EPS verw.", "EPS VJ")]
    for r in result["rows"]:
        out.append("%-12s %-9s %10s %9s %7s %7s %7s %10s %9s %8s%s" % (
            _de(r["end"]), r["fiscal"].strip()[:9], _m(r["revenue"]), _p(r["revenue_yoy"]),
            _pm(r["gross_margin"]), _pm(r["operating_margin"]), _pm(r["net_margin"]),
            _m(r["net_income"]), "-" if r["eps_diluted"] is None else markt.num(r["eps_diluted"], 2),
            _p(r["eps_yoy"]), "  abgeleitet" if r.get("derived") else ""))
    t = result["ttm"]
    if t:
        ccy = result.get("currency") or "USD"
        out.append("")
        out.append("Letzte 4 Quartale: Umsatz %s, Nettoergebnis %s, EPS verwässert %s." % (
            _geld(t["revenue"], ccy) if t.get("revenue") is not None else "-",
            _geld(t["net_income"], ccy) if t.get("net_income") is not None else "-",
            markt.money(t["eps_diluted"], ccy) if t.get("eps_diluted") is not None else "-"))
    out.append("")
    out.append("Was sich geändert hat:")
    for line in changes(result):
        out.append("  - " + line)
    return out


def render(ticker, result, filings):
    out = ["%s (%s), CIK %s. Mio. US-$ außer EPS. Quelle: SEC XBRL company facts." % (
        result["entity"], ticker, result["cik"]), ""]
    out.extend(_table(result))
    if filings:
        out.append("")
        rep, e8 = filings.get("report"), filings.get("earnings_8k")
        if rep:
            out.append("Letzter %s: Zeitraum bis %s, eingereicht %s  %s" % (
                rep["form"], _de(rep["period"]), _de(rep["filed"]), rep["url"]))
        if e8:
            out.append("Letzter Earnings-8-K (Item 2.02): eingereicht %s  %s" % (
                _de(e8["filed"]), e8["exhibit"] or e8["index"]))
    note = stale_note(result, filings)
    if note:
        out.append("")
        out.append("HINWEIS: " + note)
    if any(r["derived"] for r in result["rows"]):
        out.append("")
        out.append("Abgeleitete Quartale sind das 10-K-Jahr minus die drei 10-Qs; abgeleitetes EPS "
                   "ist nur ungefähr.")
    return "\n".join(out) + "\n"


def render_quartale(sym, result):
    ccy = result.get("currency") or "EUR"
    ident = ", ISIN %s" % result["isin"] if result.get("isin") else ""
    out = ["%s (%s)%s. Mio. %s außer EPS. %s" % (
        result.get("entity") or sym, sym, ident, markt.SYMBOLS.get(ccy, ccy), DE_HINT), ""]
    out.extend(_table(result))
    out.append("")
    out.append("Quellen:")
    for r in result["rows"]:
        bits = [b for b in (r.get("page"), r.get("basis"), r.get("source")) if b]
        out.append("  %s (%s): %s" % (r["fiscal"] or "-", _de(r["end"]),
                                       ", ".join(bits) if bits else "keine Quelle angegeben"))
    gaps = [r for r in result["rows"] if r.get("missing")]
    if gaps:
        out.append("")
        for r in gaps:
            out.append("HINWEIS: %s nennt kein %s. Die Felder bleiben leer (oft eine Quartalsmitteilung "
                       "ohne vollständige GuV)." % (r["fiscal"] or _de(r["end"]),
                                                   ", ".join(DE_LABELS[k] for k in r["missing"])))
    if not result["ttm"]:
        out.append("")
        out.append("HINWEIS: Für die letzten zwölf Monate fehlen vier Quartale in Folge.")
    return "\n".join(out) + "\n"


def metrics_row(ticker, result):
    rows = result["rows"]
    cur = rows[0] if rows else {}
    t = result["ttm"]
    row = {"ticker": ticker, "name": result["entity"], "cik": result["cik"],
           "period_end": cur.get("end"), "revenue_ttm": t.get("revenue"),
           "net_income_ttm": t.get("net_income"), "eps_ttm": t.get("eps_diluted"),
           "revenue_growth_yoy": cur.get("revenue_yoy"), "eps_growth_yoy": cur.get("eps_yoy"),
           "net_income_growth_yoy": cur.get("net_income_yoy"),
           "gross_margin": cur.get("gross_margin"), "operating_margin": cur.get("operating_margin"),
           "net_margin": cur.get("net_margin"), "source": "SEC XBRL company facts"}
    if result.get("kind") == "quartale":
        row["source"] = DE_SOURCE
        row["isin"], row["currency"] = result.get("isin"), result.get("currency")
    return row


def clean_title(title):
    return re.sub(r"\s*/[A-Z]{2,5}/?\s*$", "", title or "").strip() or None


def ticker_ciks(fetcher):
    """Ticker -> (10-stellige CIK, Firmenname) aus company_tickers.json."""
    data = fetcher.json(TICKERS_URL, "company_tickers.json")
    out = {}
    for v in data.values():
        out.setdefault(v["ticker"].upper().replace("-", "."),
                       (str(v["cik_str"]).zfill(10), clean_title(v.get("title"))))
    return out


def _parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tickers", nargs="*", help="Ticker, z. B. AAPL KO SAP.DE")
    ap.add_argument("--cik", help="diese CIK statt einer Ticker-Suche nutzen (eine US-Firma)")
    ap.add_argument("--quarters", type=int, default=6, help="Anzahl Quartale in der Tabelle (Standard 6)")
    ap.add_argument("--no-filings", action="store_true", help="ohne Links zu 8-K und 10-Q")
    ap.add_argument("--metrics", metavar="DATEI", help="je Ticker eine Zeile in diese JSON-Datei schreiben")
    ap.add_argument("--quartale", metavar="DATEI|ORDNER",
                    help="Quartalsdatei eines deutschen Emittenten oder ihr Ordner (Standard trader/quartale)")
    ap.add_argument("--user-agent", help="SEC-User-Agent: \"Dein Name du@example.com\"")
    ap.add_argument("--config", default="trader/config.json", help="Config-Datei (Standard trader/config.json)")
    ap.add_argument("--offline", metavar="ORDNER", help="SEC-Antworten aus diesem Ordner lesen")
    ap.add_argument("--json", action="store_true", help="alles maschinenlesbar ausgeben")
    return ap


def _write_metrics(path, rows):
    existing = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            existing = {r["ticker"]: r for r in json.load(fh).get("companies", [])}
    for r in rows:
        existing[r["ticker"]] = r
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"as_of": _dt.date.today().isoformat(),
                   "companies": sorted(existing.values(), key=lambda r: r["ticker"])},
                  fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return len(existing)


def _run(argv):
    ap = _parser()
    args = ap.parse_args(argv)
    file_given = bool(args.quartale) and args.quartale.lower().endswith(".json") \
        and not os.path.isdir(args.quartale)
    tickers = [t.upper() for t in args.tickers]
    if not tickers and not args.cik and file_given and os.path.isfile(args.quartale):
        try:
            with open(args.quartale, encoding="utf-8") as fh:
                own = str(json.load(fh).get("symbol") or "").strip().upper()
        except (OSError, ValueError):
            own = ""
        if own:
            tickers = [own]
    if not tickers and not args.cik:
        ap.print_help()
        return 2
    german = [t for t in tickers if markt.market_of(t) == "xetra"] if not args.cik else []
    if file_given and len(german) > 1:
        print("facts: --quartale DATEI geht nur mit einem deutschen Symbol; für mehrere nimm den Ordner "
              "(Standard trader/quartale)", file=sys.stderr)
        return 2
    us = bool(args.cik) or len(german) < len(tickers)
    ua = user_agent(args.user_agent, args.config)
    if us and not ua and not args.offline:
        print("facts: " + UA_HELP, file=sys.stderr)
        return 2
    fetcher = Fetcher(ua, offline=args.offline)
    results, rows, failed, missing = [], [], 0, 0
    try:
        ciks = ticker_ciks(fetcher) if us and not args.cik else {}
    except FactsError as exc:
        print("facts: %s" % exc, file=sys.stderr)
        return 2
    wanted = tickers or [args.cik]
    for tick in wanted:
        if tick in german:
            markt.use("xetra")
            path = quartale_path(tick, args.quartale)
            if not os.path.isfile(path):
                print("facts: %s: keine Quartalsdatei unter %s" % (tick, path), file=sys.stderr)
                (sys.stderr if args.json else sys.stdout).write(how_to(tick, path))
                missing += 1
                continue
            try:
                result = analyse_quartale(load_quartale(path, tick), quarters=args.quarters)
            except FactsError as exc:
                print("facts: %s: %s" % (tick, exc), file=sys.stderr)
                failed += 1
                continue
            results.append({"ticker": tick, "result": result, "filings": None, "path": path,
                            "changes": changes(result), "note": None})
            rows.append(metrics_row(tick, result))
            if not args.json:
                sys.stdout.write(render_quartale(tick, result))
                sys.stdout.write("\n")
            continue
        markt.use("us")
        if args.cik:
            cik, name = str(args.cik).zfill(10), None
        else:
            cik, name = ciks.get(tick.replace("-", "."), (None, None))
        if not cik:
            print("facts: keine SEC-CIK für %s (ist es ein US-Emittent? ETFs und ausländische Emittenten "
                  "haben oft keine XBRL-Daten; deutsche Aktien mit .DE, z. B. SAP.DE)" % tick, file=sys.stderr)
            failed += 1
            continue
        try:
            cf = fetcher.json(FACTS_URL % cik, "companyfacts-CIK%s.json" % cik)
            result = analyse(cf, quarters=args.quarters, name=name)
            filings = None
            if not args.no_filings:
                sub = fetcher.json(SUBMISSIONS_URL % cik, "submissions-CIK%s.json" % cik)
                filings = latest_filings(sub, cik, fetcher)
        except FactsError as exc:
            print("facts: %s: %s" % (tick, exc), file=sys.stderr)
            failed += 1
            continue
        results.append({"ticker": tick, "result": result, "filings": filings,
                        "changes": changes(result), "note": stale_note(result, filings)})
        rows.append(metrics_row(tick, result))
        if not args.json:
            sys.stdout.write(render(tick, result, filings))
            sys.stdout.write("\n")
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    if args.metrics and rows:
        n = _write_metrics(args.metrics, rows)
        if not args.json:
            print("geschrieben: %s (%d Firmen)" % (args.metrics, n))
    if failed and not results:
        return 2
    return 1 if failed or missing else 0


def main(argv=None):
    with markt.restore():
        return _run(argv)


if __name__ == "__main__":
    sys.exit(main())
