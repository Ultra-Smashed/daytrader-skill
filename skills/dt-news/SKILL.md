---
name: dt-news
description: >-
  News-Monitor. Verfolgt Nachrichten zu jeder Aktie, die du beobachtest oder
  hältst, und markiert, was sie bewegt: Yahoo-Finance-Schlagzeilen je Ticker
  (für XETRA-Werte auf Deutsch), Ad-hoc-Mitteilungen nach Art. 17 MAR und
  Corporate News von ad-hoc-news.de (zugeordnet über ISIN oder Emittentenname),
  für US-Werte die 8-K-Meldungen bei der SEC, dazu der Abstand zum
  Vortagesschluss. Zeigt nur Neues seit dem letzten Lauf, Ad-hoc-Mitteilungen
  oben, Zeiten in der Ortszeit des Marktes, Themen wie Zahlen, Prognose,
  Übernahme, Kapital, Eigengeschäfte und Stimmrechte. Nutze den Skill, wenn
  jemand sagt „was gibt es Neues zu SAP“, „warum steigt BMW“, „warum fällt die
  Aktie“, „News zu meiner Watchlist“, „Ad-hoc-Mitteilungen“, „gibt es eine
  Gewinnwarnung“, „Morgen-Briefing“, „Nachrichten vor der Eröffnung“, „behalte
  die News im Blick“, „any news on TSLA“, „breaking news“, „check the 8-Ks“,
  oder nachdem /dt-scanner Setups gefunden hat.
argument-hint: "[Ticker, z. B. SAP.DE BMW.DE TSLA] [--alle-adhoc]"
---

# dt-news

Ein Chart kann perfekt aussehen und trotzdem kurz vor einer Kurslücke stehen:
Quartalszahlen, eine Gewinnwarnung als Ad-hoc-Mitteilung, ein Handelsstopp, eine
Klage. Bevor aus einem Setup ein Trade wird, liest dieser Skill die Feeds, die so
etwas zuerst bringen, für jede Aktie auf der Watchlist, und zeigt dir nur, was neu
ist. Dazu steht je Aktie, wie weit sie heute vom Vortagesschluss entfernt ist, damit
Schlagzeile und Bewegung nebeneinander stehen.

Werkzeug in diesem Ordner (Python-Standardbibliothek, keine Schlüssel):

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                               # Watchlist + Plan + Depot
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers SAP.DE BMW.DE TSLA --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --alle-adhoc --hours 12        # alle Ad-hoc-Mitteilungen
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers IUR.DE --isin DE0006208408 --name "KAP AG"
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-sec --json
```

Ticker mit `.DE` gehören zu XETRA, alle anderen zu den US-Börsen. Weitere Schalter:
`--all` (auch Gesehenes), `--dry-run` (Zustand nicht ändern), `--no-moves`,
`--no-adhoc`, `--move-pct 3`, `--universe DATEI`, `--now "2026-10-28 10:10"`
(ohne Offset gilt die Ortszeit des Marktes).

## Was es liest und schreibt

| Datei / Feed | was |
| --- | --- |
| `--tickers`, sonst `trader/watchlist.json` | die Treffer von /dt-scanner (`hits[].symbol`) |
| `trader/plan.json` | der Trade, den du planst (/dt-ausstieg) |
| `trader/portfolio.json` | was du hältst (/dt-broker trägt Ausführungen dort ein) |
| `trader/universe.txt` | `SYMBOL\|Name\|ISIN\|Gruppe` je Zeile, liefert ISIN und Emittentenname für XETRA-Werte |
| Yahoo-Schlagzeilen (RSS) | XETRA: `...headline?s=SAP.DE&region=DE&lang=de-DE`, US: `...headline?s=TSLA&region=US&lang=en-US` |
| Yahoo-Chart | letzter Kurs gegen den Vortagesschluss (inoffiziell, XETRA etwa 15 Minuten verzögert) |
| ad-hoc-news.de (Atom) | `https://www.ad-hoc-news.de/rss/adhocnews.xml`: Ad-hoc-Mitteilungen und Corporate News, nur für XETRA-Werte |
| SEC EDGAR (Atom) | nur US-Werte, Standard 8-K (`--forms 8-K,10-Q` für mehr); braucht `sec_user_agent` in `trader/config.json` oder `SEC_USER_AGENT` mit Name und E-Mail, sonst fällt der Teil mit Hinweis weg |
| `trader/state/news.json` | was schon gezeigt wurde (30 Tage) und die CIK je US-Ticker |

## Ad-hoc-Mitteilungen und Corporate News

- **Zuordnung.** Eine Meldung gehört zu deinem Ticker, wenn seine ISIN im Titel,
  im Text oder im Link steht oder wenn der Emittentenname passt. ISIN und Name kommen
  aus `trader/universe.txt` oder aus `--isin` und `--name` (bei mehreren Tickern als
  `IUR.DE=DE0006208408`). Der Namensabgleich ignoriert Groß- und Kleinschreibung und
  Rechtsformen und Zusätze wie AG, SE, KGaA, O.N., INH., VZO, NA, HLDG. Abgekürzte
  Wörter aus der XETRA-Liste passen als Anfang („BAY.MOTOREN WERKE“ passt auf
  „Bayerische Motoren Werke“). Sehr kurze Namen wie „SAP“ oder „KAP“ zählen nur,
  wenn eine Rechtsform oder ein „/“ oder „:“ folgt, damit „SAP-Lösung“ nicht trifft.
  Ein Beispiel aus dem Feed vom 28.10.2026: XETRA führt dormakaba unter
  CH1486524122, der Feed unter CH0011795959; der Name ordnet die Meldung trotzdem zu.
- **Ad-hoc oben.** Meldungen mit „EQS-Adhoc“, „Ad-hoc“ oder „Insiderinformation“
  bekommen das Thema Ad-hoc, ein `!` und stehen vor allen anderen.
- **`--alle-adhoc`** zeigt jede Ad-hoc-Mitteilung im Zeitfenster (`--hours`), auch ohne
  deinen Ticker. Wo die Universumsliste den Emittenten kennt, steht sein Symbol dabei.
- **Zeitstempel „laut Feed“.** ad-hoc-news.de schreibt +02:00 an jede Zeit, auch in der
  Winterzeit (ab 25.10.2026 gilt MEZ, +01:00). Das Werkzeug nimmt den Offset wörtlich
  und hängt „laut Feed“ an. In der Winterzeit kann die echte Veröffentlichung eine
  Stunde später liegen: Straumann steht im Text mit „07:00 CET/CEST“, das Werkzeug zeigt
  „06:00 Uhr laut Feed“. Nenn im Briefing die Uhrzeit aus dem Meldungstext, wenn sie da ist.

## Die Regeln

- **Schlagzeilen sind Hinweise, keine Fakten.** Bevor du sagst, dass etwas passiert
  ist, öffne die Meldung und lies sie. Nenn die Quelle und verlinke sie. Fass nie eine
  Meldung hinter einer Bezahlschranke zusammen, die du nicht lesen konntest: sag das.
- **Nenn die Zeit.** Jede Meldung bekommt ihre Uhrzeit in der Ortszeit ihres Marktes:
  XETRA „08:04 Uhr“, US „08:04 ET (14:04 Uhr)“, Datum deutsch.
- **Pflichtmeldungen schlagen Schlagzeilen.** Widersprechen sich eine Ad-hoc-Mitteilung
  oder ein 8-K und eine Schlagzeile, gilt, was die Firma selbst veröffentlicht hat.
- **Sag, was es betrifft.** Jede Meldung nennt die Ticker, die sie betrifft, und ihre
  Themen: Ad-hoc, Zahlen (Quartalszahlen, Quartalsmitteilung, Halbjahresbericht, Umsatz,
  EBIT), Prognose (Prognose, Ausblick, Gewinnwarnung), Übernahme/Deal (Übernahme, Fusion,
  Beteiligung, Verkauf von), Kapital (Kapitalerhöhung, Aktienrückkauf, Dividende),
  Eigengeschäfte (Directors' Dealings, Details mit /dt-insider), Stimmrechte
  (Stimmrechtsmitteilung), Analysten, Recht, Personal, Risiko, Handelsstopp, Behörden,
  Makro. Im JSON stehen die englischen Schlüssel (`adhoc`, `earnings`, `guidance`,
  `deal`, `capital`, `insider`, `voting`, ...). SEC-Meldungen mit `!` tragen einen
  wichtigen 8-K-Punkt: Geschäftszahlen (2.02), Wechsel in Vorstand oder Aufsichtsrat
  (5.02), Wertminderung (2.06), Delisting-Hinweis (3.01), frühere Abschlüsse nicht mehr
  verlässlich (4.02), Insolvenz (1.03), Cybersicherheitsvorfall (1.05).
- **BEWEGT** markiert eine Aktie, die 3 % oder mehr vom Vortagesschluss entfernt ist
  (`--move-pct`). Eine Bewegung ohne Schlagzeile ist auch eine Aussage wert.
- **Berichtstermin.** Deutet eine Schlagzeile auf nahe Zahlen, druckt das Werkzeug je
  Ticker einen Satz: über Nacht kann der Kurs springen, auch über jeden Stopp hinweg; ein
  Daytrade ist vor Handelsschluss raus (XETRA 17:30 Uhr, US 16:00 ET, an verkürzten Tagen früher).
- **Keine Kursprognose.** Berichte, was veröffentlicht wurde und wie weit der Kurs vom
  Vortagesschluss steht. Sag nie, was die Aktie als Nächstes tut.

## Schritte

1. Prüfen: `python3 "${CLAUDE_SKILL_DIR}/news.py"`. Exit-Code 1 heißt: nichts Neues.
2. Lies zuerst, was zählt: jede Ad-hoc-Mitteilung, jedes `!`, alles mit Zahlen,
   Prognose, Handelsstopp, Recht, Behörden oder Risiko, und jeden Ticker mit BEWEGT.
3. Schreib ein kurzes Briefing je Ticker: was passiert ist, Quelle und Link, die Zeit,
   die Bewegung und ein Satz, warum es für das Setup zählt (zum Beispiel „Zahlen kommen
   diese Woche: eine Lücke über Nacht kann über jeden Stopp springen“).
4. Ändert eine Meldung das Bild, sag es vor /dt-einstieg und /dt-ausstieg: ein
   Zahlentermin im Trade, ein Handelsstopp, eine Kapitalerhöhung. Handle nie allein auf
   eine Schlagzeile hin. Eigengeschäfte von Vorständen prüfst du mit /dt-insider.

Während der Sitzung: `/loop 15m /dt-news`, oder eine geplante Aufgabe jeden Morgen vor
der Eröffnung um 9:00 Uhr.

## Beispiel: XETRA, Mittwoch 28.10.2026

Aufgezeichnete Feeds vom 28.10.2026 (Yahoo-Schlagzeilen zu SAP.DE, ad-hoc-news.de,
Yahoo-Chart von SAP.DE), geprüft um 10:10 Uhr für SAP.DE und KAP AG (IUR.DE, ISIN
DE0006208408 aus der XETRA-Liste), Zeitfenster 72 Stunden. Auszug aus der Ausgabe:

```
SAP.DE  211,20 -0,91 % zum Vortagesschluss 213,15, Stand 09:56 Uhr

! 27.10.2026 16:15 Uhr laut Feed  IUR.DE      ad-hoc-news.de  EQS-Adhoc: KAP AG PASST PROGNOSE FÜR DAS GESCHÄFTSJAHR 2026 AN (deutsch)
      Themen: Ad-hoc, Prognose  https://www.ad-hoc-news.de/boerse/news/ad-hoc-mitteilungen/kap-ag-passt-prognose-fuer-das-geschaeftsjahr-2026-an-eqs-ad-hoc-kap-ag/70421861
  28.10.2026 00:10 Uhr  SAP.DE      Yahoo Finance   Andersen Consulting nimmt das Partnerunternehmen JKIT in seinen Verbund auf
  26.10.2026 08:00 Uhr  SAP.DE      Yahoo Finance   Neues Angebot von Redwood Software wird als SAP-Lösungserweiterung vertrieben.
Geprüft 28.10.2026 10:10 Uhr. Schlagzeilen sind Hinweise, keine Fakten: lies die Meldung, bevor du handelst. Keine Anlageberatung.
```

Das Briefing: „KAP AG hat am Dienstagabend per Ad-hoc-Mitteilung ihre Prognose für 2026
angepasst (ad-hoc-news.de, im Meldungstext 17:15 Uhr; lies die Meldung für die Zahlen).
SAP: keine eigene Unternehmensmeldung, nur Partnermeldungen (Redwood, Andersen
Consulting), keine Ad-hoc. SAP steht 0,91 % unter dem Vortagesschluss von 213,15, Stand
09:56 Uhr, Yahoo etwa 15 Minuten verzögert.“ Das Werkzeug sagt nicht, ob die Anpassung
nach oben oder unten geht; das steht erst in der Meldung.

## Beispiel: US, Montag 19.10.2026 (das Reel)

TSLA brach um 10:15 ET seine Opening Range. Der Lauf um 10:15 ET (Yahoos TSLA-Feed, 16
Schlagzeilen seit 8:00 ET) beginnt mit den echten Geschichten des Morgens: „Meta and Musk
earnings and September pending home sales: What to Watch“ (08:00 ET, Zahlen),
„Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings“ (08:04 ET (14:04 Uhr),
Zahlen und Übernahme/Deal), „Tech Stock Rebound Nudges US Equity Futures Mostly Higher
Pre-Bell“ (08:02 ET, Makro). Darunter steht:

```
Berichtstermin TSLA: Eine Schlagzeile deutet auf nahe Zahlen. Über Nacht kann der Kurs springen, auch über jeden Stopp hinweg; ein Daytrade ist vor Handelsschluss um 16:00 ET (22:00 Uhr) raus.
```

Das Briefing: „Tesla legt diese Woche Zahlen vor, die Aktie kann über Nacht springen; der
heutige Trade ist vor dem Schluss raus. Kein neues 8-K.“ Um 10:52 ET lautet die Kurszeile
`TSLA    366,48 +3,31 % zum Vortagesschluss 354,72, Stand 10:52 ET (16:52 Uhr)  BEWEGT`.
Hat ein Ticker keine Nachrichten, sag das, statt das Briefing aufzufüllen.

## Was es nie tut

- Erfindet oder schmückt nie eine Meldung, ein Zitat oder eine Zahl aus.
- Handelt nie auf Nachrichten und sagt nie, du sollst wegen einer Schlagzeile kaufen oder verkaufen.
- Belastet keinen Server: eine Anfrage je Feed und Ticker, der Ad-hoc-Feed einmal je Lauf,
  eine Pause zwischen den Anfragen, und das SEC-Limit von 10 Anfragen pro Sekunde bleibt weit weg.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Schlagzeilen und Ad-hoc-Meldungen kommen mit Verzug. Bis du sie liest, hat der Markt oft schon reagiert.
- Wenn Trading zwanghaft wird: BIÖG-Telefonberatung zur Glücksspielsucht, 0800 1 37 27 00, kostenlos und anonym.
- Sag das dem User, wenn er nach Gewinnchancen, „sicheren“ Trades oder Empfehlungen fragt, und verweise auf `RISIKOHINWEISE.md` im Repo.

## Sicherheit

- Bildung und Werkzeug, keine Anlageberatung im Sinne des WpHG. Dieser Skill liest und
  berichtet nur. Die meisten Daytrader verlieren Geld; ESMA und BaFin warnen davor.
- Nichts platziert eine Order außer /dt-broker, und nur, nachdem /dt-risiko die Order
  freigegeben hat und du im Chat ausdrücklich „ja“ zu genau dieser einen Order geschrieben hast.
