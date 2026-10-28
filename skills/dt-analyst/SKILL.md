---
name: dt-analyst
description: >-
  Der Quartalszahlen-Analyst. Liest die gemeldeten Zahlen einer Firma und
  fasst zusammen, was sich geändert hat: Umsatz, Brutto-, operative und
  Nettomarge, Nettoergebnis und verwässertes EPS, Quartal für Quartal, jeweils
  gegen das Vorjahresquartal, dazu die letzten zwölf Monate. US-Firmen direkt
  aus SEC EDGAR (XBRL company facts aus 10-Q und 10-K, dazu der neueste
  Earnings-8-K mit Pressemitteilung); deutsche Firmen (SAP.DE, BMW.DE) aus der
  Quartalsmitteilung auf der IR-Seite, von Hand in eine Datei übertragen.
  Liest ein Earnings-Call-Transkript, wenn du eins einfügst. Nutzen, wenn der
  Nutzer sagt „wie waren die Zahlen von SAP“, „analysiere die Quartalszahlen“,
  „was hat sich geändert“, „wächst der Umsatz“, „vergleich die Margen“,
  „prüf den 10-Q“, „fass den Call zusammen“, „berichtet die Firma diese
  Woche“, „earnings“, „how did Tesla's earnings look“, „analyze the
  earnings“, oder bevor eine Aktie rund um ihre Zahlen gehandelt wird.
argument-hint: "[Ticker, z. B. SAP.DE TSLA]"
---

# dt-analyst

Quartalszahlen bewegen Aktien stärker als alles andere im Kalender, und die
Pressemitteilung ist so geschrieben, dass die beste Zahl oben steht. Dieser
Skill liest die Zahlen, die die Firma tatsächlich gemeldet hat, stellt sie
Quartal für Quartal nebeneinander und sagt klar, was sich geändert hat. Für
Daytrader beantwortet er vor einem Trade zwei Fragen: Was stand im letzten
Bericht, und fällt der nächste in diesen Trade?

Tool in diesem Ordner (Python-Standardbibliothek, keine Schlüssel):

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" --help
```

Der Markt folgt aus dem Symbol: `SAP.DE` ist ein deutscher Emittent (XETRA),
`TSLA` eine US-Firma. Beides darf in einem Aufruf stehen.

## US-Firmen: SEC EDGAR

Für US-Firmen braucht das Tool den SEC-User-Agent: `sec_user_agent` in
`trader/config.json` (oder `SEC_USER_AGENT`, oder `--user-agent`), also
„Dein Name du@example.com“ mit deinem echten Namen und deiner echten E-Mail.
Steht dort noch der Platzhalter (`du@example.com` oder `you@example.com`),
gilt er als nicht gesetzt, und das Tool ruft die SEC nicht auf.

- Liest `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (jede
  Zahl, die die Firma in ihren Filings getaggt hat), die Filing-Liste der
  Firma (für den neuesten 10-Q oder 10-K und den neuesten 8-K mit Item 2.02,
  „Results of Operations“) und den Ordner dieses 8-K, um die
  Pressemitteilung zu finden (das Exhibit EX-99.1).
- Für das vierte Quartal gibt es keinen 10-Q. Es ist das 10-K-Jahr minus die
  drei Quartale darin und als „abgeleitet“ markiert.

## Deutsche Firmen: Quartalsmitteilung von Hand

Für deutsche Emittenten gibt es keine freie maschinenlesbare Quelle:
filings.xbrl.org (ESEF) führt für Deutschland keine Filings (geprüft am
28.10.2026), und Yahoos Fundamentaldaten sind ohne Anmeldung gesperrt. Darum
dieser Weg:

1. `facts.py SAP.DE` ohne Datei erklärt den Weg und endet mit Exit-Code 1.
2. Du (Claude) öffnest die Investor-Relations-Seite der Firma und lädst die
   aktuelle Quartalsmitteilung bzw. den Halbjahres- oder Geschäftsbericht
   (PDF). Amtliche Quelle für Jahres- und Halbjahresfinanzberichte ist das
   [Unternehmensregister](https://www.unternehmensregister.de).
3. Aus der Konzern-GuV liest du das Quartal und das Vorjahresquartal ab und
   schreibst sie nach `trader/quartale/SAP.DE.json`. Für die TTM braucht es
   vier Quartale in Folge.
4. `facts.py SAP.DE` rechnet dann dieselbe Auswertung wie für US-Firmen.
   `--quartale DATEI` (oder ein Ordner) nimmt eine andere Datei.

Schema (vollständiges Beispiel: `quartale.example.json`, echte SAP-Zahlen):

```json
{"symbol": "SAP.DE", "name": "SAP SE", "isin": "DE0007164600", "currency": "EUR",
 "quarters": [{"period_end": "2026-09-30", "period": "Q3 2026",
   "revenue": 10270000000, "gross_profit": 7510000000, "operating_income": 2930000000,
   "net_income": 2249000000, "eps_diluted": 1.94,
   "source": "https://www.sap.com/docs/download/investors/2026/sap-2026-q3-statement.pdf",
   "page": "S. 8", "basis": "IFRS"}]}
```

- Beträge in vollen Euro (die Mitteilung zeigt meist Mio. €: 10.270 Mio. €
  werden 10270000000), Zahlen ohne Anführungszeichen, `period_end` als
  JJJJ-MM-TT.
- `revenue` Umsatzerlöse, `gross_profit` Bruttoergebnis, `operating_income`
  operatives Ergebnis (EBIT), `net_income` Ergebnis nach Steuern, den
  Eigentümern des Mutterunternehmens zurechenbar, `eps_diluted` verwässertes
  Ergebnis je Aktie.
- Was die Mitteilung nicht nennt, ist `null`. Nie raten, nie aus anderen
  Zeilen schätzen. Deutsche Firmen veröffentlichen Q1 und Q3 oft nur als
  Quartalsmitteilung ohne vollständige GuV; dann bleiben Felder leer, und das
  Tool sagt das in einem HINWEIS.
- Zu jedem Quartal `source` (URL des PDFs), `page` (Seite im PDF) und `basis`
  (meist IFRS). Die Ausgabe zeigt jede Quelle und erinnert daran, die
  Seitenangabe zu prüfen.
- Der nächste Berichtstermin steht im Finanzkalender auf der IR-Seite;
  `/dt-news` zeigt Ad-hoc-Mitteilungen.

## Was es schreibt

- `trader/metrics.json` mit `--metrics`: je Firma eine Zeile (TTM-Umsatz,
  Nettoergebnis und verwässertes EPS, die letzten Margen und das Wachstum).
  Deutsche Zeilen haben `"source": "Quartalsmitteilung (manuell)"`, dazu
  `isin` und `currency`. `metrics.example.json` in diesem Ordner ist ein
  echter Lauf für AAPL, AXP, GOOGL, KO und BAC vom 13.10.2026.
- Earnings Calls: Das Tool holt keine Transkripte. Fügt der Nutzer eins ein
  (oder hat die IR-Seite eins), lies es und fasse zusammen, was laut Vorstand
  sich geändert hat: Prognose, Margen, Nachfrage, und welche Fragen er nicht
  beantwortet hat.
- Der nächste Berichtstermin steht nicht in den SEC-Daten. Such ihn in den
  Schlagzeilen von `/dt-news` oder auf der IR-Seite und sag, woher er stammt.

## Die Regeln

- **Gemeldete Zahlen zuerst.** Die Tabelle kommt aus den XBRL-Daten, die die
  Firma eingereicht hat, bzw. aus der Konzern-GuV der Quartalsmitteilung. Die
  Pressemitteilung liefert Kontext (Prognose, Segmente); sag, welche Zahl
  woher kommt.
- **Gleiches mit Gleichem vergleichen.** Wachstum heißt: gegen das
  Vorjahresquartal. Die Veränderung zum Vorquartal steht dabei, aber viele
  Geschäfte sind saisonal (Apples Dezemberquartal ist immer das größte).
- **Abgeleitetes markieren.** Das US-Q4 ist das 10-K-Jahr minus drei
  Quartale und als „abgeleitet“ markiert; abgeleitetes EPS ist nur ungefähr.
- **Verzögerung sagen.** Die Facts-API der SEC kann einem Filing
  hinterherlaufen. Ist der neueste 10-Q jünger als das neueste Quartal in den
  Daten, druckt das Tool einen HINWEIS mit Link: lies dann den 10-Q selbst.
  Deutsche Zahlen sind von Hand übertragen: prüf die Seitenangabe.
- **Einmaleffekte markieren.** Liegt das Nettoergebnis über dem operativen
  Ergebnis (EBIT), stecken Erträge außerhalb des Kerngeschäfts darin
  (Finanzergebnis, Beteiligungen, Steuereffekte). Das Tool sagt das. Banken
  und Versicherer haben keine Bruttomarge: leer, nicht null.

## Schritte

1. Lass es für die gefragten Firmen laufen (oder für die Ticker auf
   `trader/watchlist.json`):

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/facts.py" TSLA
   python3 "${CLAUDE_SKILL_DIR}/facts.py" SAP.DE
   python3 "${CLAUDE_SKILL_DIR}/facts.py" TSLA NVDA SAP.DE --metrics trader/metrics.json
   ```

   `--quarters 8` zeigt zwei Jahre, `--json` alles maschinenlesbar, `--cik`
   eine US-Firma ohne Ticker. Fehlt bei einem `.DE`-Symbol die Datei, folge
   der Anleitung im Abschnitt „Deutsche Firmen“ und ruf es erneut auf.
2. Öffne bei Bedarf die neueste Pressemitteilung (der EX-99-Link) und den
   10-Q bzw. die Quartalsmitteilung und lies sie.
3. Schreib die Zusammenfassung: eine Zeile zum Quartal (Umsatz, EPS,
   Wachstum), eine zu den Margen, eine zu allem Ungewöhnlichen (Einmaleffekt,
   abgeleitetes Quartal, verzögerte Daten, leere Felder), dazu die Links.
   Klare Worte, echte Zahlen, keine Adjektive, die die Zahlen nicht tragen.
4. Fällt der nächste Bericht in den geplanten Trade (Halten über Nacht oder
   ein Bericht vor der Eröffnung), sag es, bevor `/dt-ausstieg` den Stop
   setzt: Ein Stop schützt nicht vor einer Kurslücke, die Aktie kann jenseits
   davon eröffnen.

## Beispiel: Tesla (US)

`facts.py TSLA` (Lauf am 20.10.2026): Quartal bis 30.06.2026 (Q2 2026),
Umsatz 28,24 Mrd. $, +25,5 % gegenüber dem Vorjahresquartal, Nettoergebnis
1,11 Mrd. $ (-4,9 %), EPS verwässert 0,32 $ (-3,0 %); Bruttomarge 16,8 %
(-4,3 Prozentpunkte gegenüber dem Vorquartal), operative Marge 1,4 %; letzte
vier Quartale 103,6 Mrd. $ Umsatz und 1,08 $ EPS. Das Tool markiert, dass
das Nettoergebnis über dem operativen Ergebnis liegt, also Erträge außerhalb
des Kerngeschäfts darin stecken. Letzter 10-Q eingereicht am 23.07.2026. Die
Schlagzeilen vom Montag sagten, Tesla berichtet diese Woche, also endet die
Zusammenfassung: „Der nächste Bericht ist Tage entfernt. Ein Daytrade, der
vor Handelsschluss glattgestellt ist, ist ihm nicht ausgesetzt; alles, was
über Nacht gehalten wird, schon.“

`facts.py AAPL` (13.10.2026): Umsatz 109,42 Mrd. $, +16,4 % gegenüber dem
Vorjahresquartal, EPS verwässert 2,02 $ (+28,7 %). Bei Coca-Cola meldete das
Tool, dass die SEC-Daten am 03.04.2026 enden, der 10-Q für den 03.07.2026
aber schon eingereicht war; die Zusammenfassung las deshalb diesen 10-Q
direkt.

## Beispiel: SAP (XETRA)

`facts.py SAP.DE` mit den Zahlen aus SAPs Quartalsmitteilungen Q4 2025 bis
Q3 2026 (IFRS, sap.com, übertragen am 28.10.2026): Quartal bis 30.09.2026
(Q3 2026), Umsatz 10,27 Mrd. € (+13,2 % gegenüber dem Vorjahresquartal),
Nettoergebnis 2,25 Mrd. € (+12,2 %), EPS verwässert 1,94 € (+13,5 %);
Bruttomarge 73,1 % (-0,1 Prozentpunkte), operative Marge 28,5 % (+1,7
Prozentpunkte), Nettomarge 21,9 %; letzte vier Quartale 39,39 Mrd. € Umsatz
und 7,04 € EPS. Quelle: Quartalsmitteilung Q3 2026, S. 8.

## Was es nie tut

- Sagt nie, eine Aktie sei billig, teuer, ein Kauf oder ein Verkauf. Es
  berichtet, was die Firma gemeldet hat.
- Erfindet nie eine Zahl, die nicht in den Berichten steht, und schätzt kein
  Quartal, das es nicht ableiten kann. Leere Felder bleiben leer.
- Ruft die SEC nie ohne User-Agent auf und bleibt deutlich unter 10 Anfragen
  pro Sekunde.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Quartalszahlen sagen nichts über den Kurs der nächsten Minuten. Von Hand übertragene Zahlen können falsch sein.
- Wenn Trading zwanghaft wird: BIÖG-Telefonberatung zur Glücksspielsucht, 0800 1 37 27 00, kostenlos und anonym.
- Sag das dem User, wenn er nach Gewinnchancen, „sicheren“ Trades oder Empfehlungen fragt, und verweise auf `RISIKOHINWEISE.md` im Repo.

## Sicherheit

Bildung und Werkzeug, keine Anlageberatung (auch nicht im Sinne des WpHG).
Dieser Skill liest nur Berichte. Nichts in diesem Paket platziert eine Order
außer `/dt-broker`, und das nur, nachdem `/dt-risiko` genau diese Order
freigegeben hat und du im Chat ausdrücklich „ja“ zu genau dieser einen Order
geschrieben hast.
