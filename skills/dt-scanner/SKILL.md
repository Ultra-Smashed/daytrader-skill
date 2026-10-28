---
name: dt-scanner
description: >-
  Chart-Scanner für XETRA (Standard) und US-Börsen. Scannt Tausende Charts nach
  Setups: Opening-Range-Breakouts, Bull Flags, überverkaufte Aktien und
  Erholungen. Baut das Universum aus der offiziellen XETRA-Liste der Deutschen
  Börse (DAX, MDAX, SDAX, DEUTSCHLAND und alle anderen Aktien) oder aus den
  Nasdaq-Trader-Listen, macht einen vorbörslichen Scan der Tagesschlusskurse
  (20-Tage-Schlusshoch-Ausbruch, Bull Flag, 20-Tage-Durchschnitt
  zurückerobert, überverkauft, Erholung aus überverkauft) und einen
  Opening-Range-Breakout-Scan auf 5-Minuten-Kerzen und schreibt
  trader/watchlist.json für dt-news und dt-einstieg. Kostenlose Yahoo-Daten,
  Kerze für Kerze, XETRA ca. 15 Minuten verzögert. Nutze den Skill, wenn jemand
  sagt „scan den Markt“, „finde Setups“, „was bricht aus“,
  „Opening-Range-Breakouts“, „Bull Flags“, „überverkaufte Aktien“,
  „vorbörslicher Scan“, „bau meine Watchlist“, „DAX-Scan“, „was soll ich mir
  heute anschauen“, oder „scan the market“, „find me setups“, „opening range
  breakouts“, „pre-market scan“, am Anfang eines Handelstags vor /dt-news.
argument-hint: "[universe | daily | orb] [--market xetra|us] [--at HH:MM]"
---

# dt-scanner

Der Chart-Scanner ist der erste Schritt eines Daytrades. Er liest Tausende
kostenlose Charts und listet die, die eine Regel erfüllen. Mehr macht er nicht.
Ein Scan ist eine Liste von Charts, die eine Regel erfüllen, keine Liste von
Aktien zum Kaufen, und ein Setup auf einem Chart ist keine Vorhersage. Die
meisten Menschen, die daytraden, verlieren Geld (ESMA und BaFin warnen
ausdrücklich davor); der Scanner ändert daran nichts. Er erspart dir nur, 1.755
Charts von Hand durchzublättern.

`${CLAUDE_SKILL_DIR}` ist der Ordner dieses Skills (dort liegt diese SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                         # XETRA-Aktien -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --nur-deutschland       # nur DAX, MDAX, SDAX, DEUTSCHLAND
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --gruppen DAX           # nur die DAX-Zeilen
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --market us             # US-Aktien (Nasdaq Trader)
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                            # vor der Eröffnung -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols SAP.DE,BMW.DE    # oder --watchlist DATEI, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                              # XETRA ab 9:20 Uhr -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:15                   # die Uhr auf 10:15 Uhr stellen
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --symbols TSLA,NVDA          # US: ab 9:50 ET (15:50 bzw. 14:50 Uhr)
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --watchlist trader/watchlist.json --json
```

Flags: `--market xetra|us`, `--min-price` und `--min-volume` (Standards unten),
`--or-minutes 15`, `--max-confirm 200` (orb Stufe 2), `--until HH:MM`,
`--now "2026-10-27 10:15"` (Ortszeit des Marktes; `...Z` für UTC), `--offline PFAD`
für gespeicherte Dateien, `--no-write`, `--show N`, `--json`. Exit-Code 0, wenn der
Scan etwas gefunden hat, 1, wenn nichts oder wenn er nicht laufen konnte (der Grund
steht in einer klaren Zeile).

## Welcher Markt?

1. `--market xetra` oder `--market us`, wenn du es angibst.
2. Sonst die Symbole: `SAP.DE` ist XETRA, `TSLA` ist US. Alle Symbole einer Liste
   müssen zu einem Markt gehören; eine gemischte Liste (SAP.DE und TSLA) bricht mit
   einer klaren Meldung ab. Scanne XETRA- und US-Werte getrennt.
3. Sonst `"market"` in `trader/config.json`.
4. Sonst XETRA.

Alle Zeiten sind Ortszeit des Marktes: XETRA in deutscher Zeit („10:15 Uhr“), US in
New Yorker Zeit („10:15 ET“, dazu die deutsche Zeit in Klammern). Berlin stellt am
letzten Sonntag im Oktober um, New York eine Woche später: in dieser Woche liegen
die beiden Börsen 5 statt 6 Stunden auseinander. Das rechnet `markt.py`.

| | XETRA | US |
| --- | --- | --- |
| Handel | 9:00 bis 17:30 Uhr | 9:30 bis 16:00 ET |
| Opening Range (15 Min.) | Kerzen 9:00, 9:05, 9:10 | Kerzen 9:30, 9:35, 9:40 |
| frühester orb-Lauf | 9:20 Uhr | 9:50 ET |
| no_entries_after | 17:00 Uhr | 15:30 ET |
| daily: min-price, min-volume | 5 €, 50.000 Stück | 5 $, 1.000.000 Stück |
| orb: min-price, min-volume | 5 €, 0 | 5 $, 0 |
| verkürzter Handel | 30.12.2026 bis 14:00 Uhr | 27.11. und 24.12.2026 bis 13:00 ET |

Die Flags überschreiben die Standards, `no_entries_after` kommt aus
`trader/config.json` (`"zeiten": {"xetra": {...}}` oder der alte Schlüssel), sonst
aus der Tabelle. Warum 50.000 Stück an XETRA: Yahoos XETRA-Volumen zählt nur den
fortlaufenden Handel in Stück, und DAX-Werte handeln an XETRA viel weniger Stück als
US-Aktien. Am Di 27.10.2026 hatten 37 der 43 DAX-Zeilen mindestens 50.000 Stück, bei
100.000 wären es nur 30 gewesen. Unter 50.000 lagen HEN.DE, HOT.DE, MTX.DE, HNR1.DE,
VOW.DE und BNR.DE.

## Was er liest und schreibt

| Datei | was |
| --- | --- |
| `trader/universe.txt` | von `universe`: XETRA eine Zeile `SYMBOL\|Name\|ISIN\|Gruppe` (`SAP.DE\|SAP SE O.N.\|DE0007164600\|DAX`), US `SYMBOL\|Name`. `daily` und `orb` lesen nur das erste Feld |
| `trader/watchlist.json` | von `daily` und `orb`: `mode`, `market`, `as_of` („2026-10-27 10:15 Uhr“ bzw. „... ET“), `universe`, `scanned`, `failed`, `hits[]`. dt-news und dt-einstieg lesen `hits[].symbol` |
| `trader/config.json` | `market`, `no_entries_after` bzw. `zeiten` |

## Das Universum

**XETRA (Standard).** `universe` lädt die Liste „T7 (XETR) All tradable instruments“
der Deutschen Börse (CSV mit Semikolon, Kopfzeilen „Market:;XETR“ und „Date Last
Update:;28.10.2026“). Behalten werden Zeilen mit Instrument Type `CS` (Aktie) und
Instrument Status `Active`; ETFs, ETNs und ETCs fliegen raus. Das Symbol ist das
Mnemonic plus `.DE` (SAP.DE, P911.DE, 1COV.DE: Ziffern sind erlaubt). Die Gruppe ist
die Spalte „Product Assignment Group Description“. Ohne Filter bleiben alle Aktien,
auch NORDAMERIKA, FRANKREICH usw. (US-Aktien, die an XETRA in Euro handeln).
`--gruppen DAX,MDAX` filtert (Groß-/Kleinschreibung egal), `--nur-deutschland` ist die
Abkürzung für DAX, MDAX, SDAX und DEUTSCHLAND.

Am 28.10.2026: 5.538 Zeilen, 1.755 Aktien (eine weitere CS-Zeile stand auf
PendingDeletion), davon NORDAMERIKA 844, DEUTSCHLAND 251, SDAX 73, MDAX 55, DAX 43
(der DAX hat 40 Werte; HEN und HEN3, VOW und VOW3 sowie CBK0 sind zusätzliche Zeilen).
Mit `--nur-deutschland` bleiben 422.

**US.** `universe --market us` lädt `nasdaqlisted.txt` und `otherlisted.txt` von
nasdaqtrader.com/dynamic/SymDir und behält eine Zeile, wenn, in dieser Reihenfolge:

1. kein Testwert, kein ETF, keine NextShares;
2. ein einfaches Kürzel: 1 bis 5 Buchstaben oder 1 bis 4 Buchstaben plus ein
   Klassenbuchstabe nach einem Punkt (BRK.B). Ein `$`-Vorzug (ABR$D) fliegt raus,
   ebenso eine Endung `.U`, `.W` oder `.R` (Units, Warrants, Rights);
3. raus, egal was der Name sonst sagt: Warrants, SPAC-Units und -Rights, Notes, ETNs,
   Debentures, ein %-Kupon, „Depositary Shares“, die nicht American oder Global sind;
4. drin: Common Stock, Common Shares oder Units, Ordinary Shares, Shares of
   Beneficial Interest, ADS / ADR, Partnership- oder Trust-Units;
5. raus: der Name sagt noch Unit, Right, Bond, Preferred oder Preference;
6. drin: alles andere (einfache Namen wie „AMETEK, Inc.“).

Auf den Dateien vom 19.10.2026 bleiben 5.943 US-Aktien.

## Der Tages-Scan (vor der Eröffnung)

Yahoos spark-Endpunkt liefert Schlusskurse für 20 Symbole je Anfrage, die 1.755
XETRA-Aktien brauchen also 88 Anfragen. Liquidität kommt aus den spark-Metadaten:
letzter Kurs mindestens `--min-price`, Volumen mindestens `--min-volume`. Lass ihn vor
9:00 Uhr (bzw. 9:30 ET) oder nach Handelsschluss laufen: während der Sitzung ist das
Volumen das von heute bis jetzt, und die heutige Tageskerze bleibt bis 17:30 Uhr
(16:00 ET) draußen. Das Tool sagt das dann in einer Zeile.

Die Setups kommen nur aus Tagesschlusskursen (spark hat keine Hochs und Tiefs):

| Setup (JSON-Schlüssel) | Name | Regel auf Schlusskursen |
| --- | --- | --- |
| `breakout_20d` | 20-Tage-Schlusshoch-Ausbruch | der letzte Schluss liegt über jedem der 20 Sitzungen davor |
| `bull_flag` | Bull Flag | mehr als 10 % Plus in den 10 Sitzungen vor den letzten 5, dann die letzten 5 Schlüsse in 5 % Spanne |
| `reclaim_ma20` | über den 20-Tage-Durchschnitt zurückerobert | der Schluss davor lag unter dem 20-Tage-Durchschnitt, der letzte liegt darüber |
| `oversold` | überverkauft (RSI unter 30) | RSI 14 (Wilder) unter 30 |
| `oversold_bounce` | Erholung aus überverkauft | RSI 14 war gestern unter 30 und heute ging es aufwärts |

Treffer stehen nach gehandeltem Geld (Kurs mal Volumen), die größten zuerst.

## Der Opening-Range-Breakout-Scan (während der Sitzung)

Die Opening Range sind die ersten `--or-minutes` (15) ab der Eröffnung: an XETRA die
5-Minuten-Kerzen 9:00, 9:05 und 9:10, die erste Kerze danach schließt um 9:20 Uhr. Ein
Treffer ist die erste fertige 5-Minuten-Kerze, die ÜBER dem Range-Hoch SCHLIESST, zur
Schlusszeit dieser Kerze.

1. Stufe 1, jedes Symbol: spark-Schlusskurse der 5-Minuten-Kerzen, 20 je Anfrage. Ein
   Chart kommt weiter, wenn eine fertige Kerze nach der Range auf oder über dem
   höchsten Range-Schluss schloss. Das ist eine notwendige Bedingung, es geht also kein
   Ausbruch verloren.
2. Stufe 2, jeder Kandidat: der v8-Chart mit echten Hochs und Tiefs. Range-Hoch = das
   höchste Hoch der Range-Kerzen, Range-Tief = das tiefste Tief. Höchstens
   `--max-confirm` (200), die meistgehandelten zuerst; dann steht TEILERGEBNIS mit der
   Zahl der übersprungenen da. `--max-confirm 0` prüft alle.

Ein Chart ist nur nutzbar, wenn jede 5-Minuten-Kerze von der Eröffnung bis zur
Uhrzeit da ist; eine fehlende Kerze heißt Aussetzung, dünner Handel oder eine Lücke in
Yahoos Daten. Schlusskurse null fallen weg, eine Kerze neben dem Raster (der Live-Tick)
fällt weg, und eine Kerze zählt erst, wenn sie fertig ist. Vor 9:20 Uhr (zu früh), am
Wochenende, an einem Börsenfeiertag (2026: 1.1., 3.4., 6.4., 1.5., 24.12., 25.12.,
31.12.), nach Handelsschluss oder nach `no_entries_after` (ein abgelaufenes Setup)
schreibt er eine klare Zeile und nichts in die Watchlist.

**Verzögerung.** Yahoo liefert XETRA-Kerzen ca. 15 Minuten verzögert (am 28.10.2026 um
10:12 Uhr war die letzte Kerze die von 9:55 Uhr). Reichen die Daten nicht bis zur
Uhrzeit, scannt orb bis zur letzten fertigen Kerze und sagt es: „Die letzte fertige
Kerze in den Daten endet um 10:00 Uhr; der Scan läuft bis dahin statt bis 10:12 Uhr.“
Ein Live-Scan um 9:20 Uhr ist an XETRA also zu früh; ab etwa 9:35 Uhr sind die
Range-Kerzen und die erste Kerze danach da.

## Daten und Grenzen

- Yahoos chart- und spark-Endpunkte sind kostenlos, inoffiziell und können
  hinterherhinken. XETRA ist ca. 15 Minuten verzögert, nie Echtzeit. 5-Minuten-Kerzen,
  Kerze für Kerze, nie Tick für Tick. Erst query2, bei 429 oder 5xx query1, nach einem
  429 ein zweiter Versuch nach 5 Sekunden.
- Teilergebnisse werden als Teilergebnisse gesagt: „233 von 234 Charts geladen (1
  fehlgeschlagen oder ohne Daten)“. Runde einen Teil-Scan nie zu „der ganze Markt“ auf.
- Kalender: Handelskalender der Deutschen Börse und NYSE-Kalender für 2026 und 2027
  (aus `markt.py`).

## Schritte

1. Etwa einmal pro Woche: `scan.py universe` (oder `--nur-deutschland`).
2. Vor der Eröffnung: `scan.py daily`. Sag die Zahlen (geladen, liquide, gescannt,
   Treffer) und die ersten paar je Setup.
3. Ab 9:20 Uhr an XETRA (realistisch ab 9:35 Uhr wegen der Verzögerung; 10:15 Uhr ist
   ein guter Zeitpunkt) bzw. ab 9:50 ET: `scan.py orb`. Sag, wie viele nutzbare Charts
   ihre Range wann gebrochen haben, und dass ein späterer Treffer näher am Kurs von
   jetzt ist.
4. Die Nutzerin oder der Nutzer sucht sich einen Chart aus. Weiter mit
   `/dt-news SYMBOL` (was bewegt ihn), dann `/dt-einstieg SYMBOL`. Wähl nie selbst aus.

## Beispiel: DAX am Di 27.10.2026 um 10:15 Uhr

Echte Yahoo-Charts der 43 DAX-Zeilen, aufgezeichnet am 28.10.2026
(`tests/fixtures/dt-scanner/dax-v8-5d5m-2026-10-28.json.gz`):

```
python3 scan.py orb --offline dax-v8-5d5m-2026-10-28.json.gz --now "2026-10-27 10:15"
Opening-Range-Breakout-Scan XETRA, Di 27.10.2026 10:15 Uhr: 15-Minuten-Range (09:00 bis 09:15 Uhr), 5-Minuten-Kerzen, Yahoo.
43 von 43 Charts geladen; 35 nutzbar; 19 Kandidaten, 19 mit echten Hochs und Tiefs bestätigt.
10 von 35 Charts haben bis 10:15 Uhr über ihrem Opening-Range-Hoch geschlossen:
  09:20 Uhr  ENR.DE      125,48 €  Range 123,84 bis 125,10  +0,30 % drüber
  09:20 Uhr  IFX.DE       50,96 €  Range 50,42 bis 50,87  +0,18 % drüber
  ...
  10:10 Uhr  SHL.DE       42,32 €  Range 41,94 bis 42,24  +0,19 % drüber
```

Siemens Energy: Range aus den Kerzen 9:00 bis 9:10, Hoch 125,10, Tief 123,84; die
9:15-Kerze schloss bei 125,48, 0,30 % über dem Hoch, um 9:20 Uhr. 8 der 43 Charts
waren nicht nutzbar, weil Yahoos Daten bis 10:15 Uhr mindestens eine Lücke hatten
(eine fehlende Kerze oder eine ohne Schlusskurs, u. a. CON.DE, DHL.DE, HEN.DE, VOW.DE).

## Beispiel: Tages-Scan DAX am Mi 28.10.2026

Echte spark-Tagesschlüsse der 43 DAX-Zeilen, abgerufen um 10:10 Uhr
(`tests/fixtures/dt-scanner/dax-spark1d-2026-10-28/`):

```
python3 scan.py daily --offline dax-spark1d-2026-10-28 --now "2026-10-28 10:10"
Tages-Scan XETRA, Mi 28.10.2026 10:10 Uhr, Schlusskurse bis 27.10.2026 (Yahoo spark, nur Tagesschlusskurse).
43 von 43 Charts geladen. 20 haben den Liquiditätsfilter bestanden (ab 5 €, ab 50.000 Stück); 20 gescannt.
Achtung: Die Sitzung läuft. Das Volumen in Yahoos Daten ist das von heute bis jetzt, nicht der ganze Tag; vor 09:00 Uhr zählt der Vortag.
3 Charts erfüllen ein Setup. 20-Tage-Schlusshoch-Ausbruch: 2; Bull Flag: 1.
Meistgehandelte zuerst (Preis mal Volumen):
  DHL.DE       58,82 €  RSI  62,0  20-Tage-Schlusshoch-Ausbruch
  EOAN.DE      18,57 €  RSI  67,3  20-Tage-Schlusshoch-Ausbruch
  ZAL.DE       26,56 €  RSI  68,6  Bull Flag
```

Weil der Abruf um 10:10 Uhr lief, zählt beim Volumen nur die erste Stunde; nur 20 der
43 kamen über 50.000 Stück. Mit `--min-volume 0` sind es 42 gescannte Charts (CBK0.DE
hat zu wenig Tage) und 5 Treffer: zusätzlich RHM.DE (1.025,20 €) und G24.DE (83,20 €)
als Bull Flag.

## Beispiel: US-Wand am Mo 19.10.2026

Der Scan um 10:15 ET über die 234 Ticker des Reels
(`tests/fixtures/dt-scanner/wall5m-2026-10-19.json.gz`, echte Yahoo-Charts):

```
python3 scan.py orb --offline wall5m-2026-10-19.json.gz --now "2026-10-19 10:15" --min-price 0
233 von 234 Charts geladen (1 fehlgeschlagen oder ohne Daten); 231 nutzbar; 95 Kandidaten, 95 mit echten Hochs und Tiefs bestätigt.
42 von 231 Charts haben bis 10:15 ET (16:15 Uhr) über ihrem Opening-Range-Hoch geschlossen:
  09:50 ET   AMC           2,97 $  Range 2,90 bis 2,96  +0,50 % drüber
  ...
  10:15 ET   TSLA        364,18 $  Range 354,47 bis 362,18  +0,55 % drüber
```

Die Wand im Reel hatte keine Preisschwelle (AMC bei 2,97 $ ist einer der 42), daher
`--min-price 0`; mit der Standardschwelle von 5 $ sind es 41. Die Range von TSLA sind
die Kerzen 9:30 bis 9:40, Hoch 362,18, Tief 354,47; die 10:10-Kerze schloss bei
364,18 $, 0,55 % über dem Hoch, um 10:15 ET (16:15 Uhr deutscher Zeit). Danach geht es
mit `/dt-news TSLA` und `/dt-einstieg TSLA` weiter.

## Regeln

- Sag, was gescannt wurde: wie viele Symbole, wie viele Charts zurückkamen, wie viele
  nutzbar waren, und den Zeitstand der Daten (bei XETRA mit der Verzögerung).
- Sag „erfüllt eine Regel“, nie „ein Kauf“, „ein Gewinner“ oder „ein guter Trade“.
- Nenn nie einen Gewinn, eine Rendite oder eine P&L-Zahl.
- Ein Treffer ist alt, sobald der Kurs weitergelaufen ist. Vor jeder Handlung neu scannen.
- Keine Anlageberatung im Sinne des WpHG und keine Steuerberatung.

## Was er nie tut

Er platziert, dimensioniert oder prüft nie eine Order, sagt nie, welche Aktie du
kaufen sollst, nennt Daten nie Echtzeit und verspricht nie, dass ein Setup funktioniert.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Ein Treffer ist ein Chart, der eine Regel erfüllt, keine Kaufempfehlung. XETRA-Kerzen von Yahoo sind ca. 15 Minuten verzögert und haben Lücken.
- Wenn Trading zwanghaft wird: BIÖG-Telefonberatung zur Glücksspielsucht, 0800 1 37 27 00, kostenlos und anonym.
- Sag das dem User, wenn er nach Gewinnchancen, „sicheren“ Trades oder Empfehlungen fragt, und verweise auf `RISIKOHINWEISE.md` im Repo.

## Sicherheit

- Bildung und Werkzeug, keine Anlageberatung. Eine FREIGABE ist eine Regelprüfung, keine Empfehlung.
- Paper Trading ist Standard (`"paper": true`). Live zu gehen ist deine eigene Entscheidung, in deiner eigenen Config.
- Nichts in diesem Paket platziert eine Order außer dt-broker, und nur wenn alles drei gilt: dt-risiko hat
  genau diese Order heute freigegeben, du hast im Chat ausdrücklich „ja“ zu genau dieser einen Order geschrieben,
  und du hast auf Claudes eigener Karte „Allow once“ geklickt, weil das Order-Tool auf „Needs approval“ steht
  (Customize > Connectors > Tool-Berechtigungen). Ein Order-Tool nie auf „Always allow“ stellen.
  Im Modus `"broker": "manuell"` tippst du die Order selbst in deiner Broker-App ein.
- Keine Optionen, kein Margin, keine Leerverkäufe, kein Hebel, außer die Config erlaubt es und du bestätigst es.
- Broker-Schlüssel liegen in Umgebungsvariablen oder in der Claude-Desktop-Config, nie im Chat.
