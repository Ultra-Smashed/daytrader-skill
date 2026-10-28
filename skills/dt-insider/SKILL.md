---
name: dt-insider
description: >-
  Directors' Dealings aus Deutschland. Liest die öffentliche BaFin-Datenbank
  „Eigengeschäfte von Führungskräften“ (Art. 19 MAR): wer bei welchem
  Emittenten gekauft oder verkauft hat, Funktion (Vorstand, Aufsichtsrat,
  in enger Beziehung), Durchschnittspreis, Volumen in Euro, Handelsplatz,
  Handels-, Mitteilungs- und Veröffentlichungsdatum und den Meldeverzug in
  Geschäftstagen. Meldet jede neue Mitteilung einmal, markiert Werte aus
  deinem Depot und deiner Watchlist und trennt echte Käufe und Verkäufe von
  Zuteilungen und Sonstigem. Nutze den Skill, wenn jemand sagt „was kaufen
  Vorstände“, „Directors' Dealings“, „Insiderkäufe“, „Eigengeschäfte von
  Führungskräften“, „hat der Vorstand von DEUTZ gekauft“, „melde mir neue
  Vorstandskäufe“, „wer verkauft gerade“, oder auf Englisch „insider buying
  Germany“, „Managers' transactions“, „director dealings“.
argument-hint: "[ISIN | Emittent | Person] [--woche | --monat] [--art kauf]"
---

# dt-insider

Führungskräfte börsennotierter Unternehmen müssen ihre eigenen Geschäfte in
Aktien und Schuldtiteln ihres Emittenten melden, ebenso Personen und Firmen,
die ihnen nahestehen („in enger Beziehung“). Die BaFin stellt alle diese
Mitteilungen in eine öffentliche Datenbank. Dieser Skill liest sie, bemerkt
neue Meldungen und schreibt jede in klare Zeilen um.

Er ist schnell. Er ist nicht früh. Die Meldung ist bis zu drei Geschäftstage
nach dem Geschäft fällig, veröffentlicht wird danach, und die Datenbank wird
einmal am Tag aktualisiert. Wenn du eine Meldung liest, ist das Geschäft
Tage alt. Hier gibt es kein Insiderwissen: nur öffentliche Meldungen, schnell
gelesen. Sag das jedes Mal.

Werkzeug in diesem Ordner (Python, nur Standardbibliothek, kein Schlüssel):

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" --help
```

## Was gelesen und geschrieben wird

| Datei / Quelle | wofür |
| --- | --- |
| `https://portal.mvp.bafin.de/database/DealingsInfo/sucheForm.do?...` | CSV-Export der BaFin-Suche (UTF-8 mit BOM, Trenner `;`) |
| `trader/universe.txt` | ISIN zu Symbol: Zeilen `SYMBOL\|Name\|ISIN\|Gruppe`, z. B. `DEZ.DE\|DEUTZ AG O.N.\|DE0006305006\|MDAX` (ältere Zeilen nur `SYMBOL\|Name` werden ignoriert) |
| `trader/portfolio.json` | `positions[]` mit `ticker` oder `symbol`, optional `isin`: markiert „im Depot“ |
| `trader/watchlist.json` | `hits[].symbol` von /dt-scanner: markiert „auf der Watchlist“ |
| `trader/state/insider.json` | schreibt `new`: welche Zeilen schon gezeigt wurden (`seen`, je ein sha256-Schlüssel über alle Felder) und `last_check` |

## Die Regeln

- **Zitiere die Meldung, nicht einen Dienst.** Jede Zeile kommt aus dem
  BaFin-Export, wörtlich: Name der Person wie gemeldet („Schmitt, Martin“),
  Funktion wie gemeldet, Handelsplatz wie gemeldet.
- **Volumen ist ein Betrag.** „Aggregiertes Volumen 6.660,00 EUR“ heißt
  Euro, nie Stückzahl. Die Stückzahl steht nicht im Export; rechne sie nicht
  aus dem Durchschnittspreis zurück und nenne sie nicht als Tatsache.
- **Wer hat gehandelt?** „in enger Beziehung“ ist nicht der Vorstand selbst,
  sondern eine Firma (GmbH, Stiftung, Holding) oder eine Angehörige. Das Tool
  sagt dazu „eine Firma“ oder „eine nahestehende Person“. Sag es genauso.
- **Nur Kauf und Verkauf sind ein Signal.** „Sonstiges“ (Zuteilung,
  Aktienoptionsprogramm, Schenkung, Erbschaft, Verpfändung) und andere
  Instrumente sind keine Marktentscheidung. Das Tool kennzeichnet sie mit
  „zählt nicht als Marktsignal“.
- **Sag den Verzug.** Jede Zeile zeigt die Geschäftstage vom Handel bis zur
  Mitteilung (Wochenenden und XETRA-Feiertage zählen nicht). Über drei
  Geschäftstage steht „VERSPÄTET“: Art. 19 Abs. 1 MAR verlangt eine Meldung
  unverzüglich, spätestens drei Geschäftstage nach dem Geschäft. Ein
  „VERSPÄTET“ ist eine Beobachtung aus den Daten, kein Vorwurf: es kann
  Gründe geben, die der Export nicht zeigt.
- **Die Schwelle.** Gemeldet wird erst, wenn die Geschäfte einer Person im
  Kalenderjahr 20.000 € erreichen (Art. 19 Abs. 8 MAR nennt 5.000 €; nach
  Abs. 9 hat die BaFin die Schwelle auf 20.000 € angehoben). Kleine Käufe darunter fehlen also, und das Fehlen
  einer Meldung heißt nicht, dass niemand gehandelt hat.

## Schritt 1: was gemeldet wurde

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" index                                  # letzte Woche, alle
python3 "${CLAUDE_SKILL_DIR}/insider.py" index --isin DE0006305006 --monat      # ein Emittent
python3 "${CLAUDE_SKILL_DIR}/insider.py" index --emittent rheinmetall --gesamt
python3 "${CLAUDE_SKILL_DIR}/insider.py" index --person "Martin Schmitt" --monat
python3 "${CLAUDE_SKILL_DIR}/insider.py" index --von 01.10.2026 --bis 28.10.2026 --art kauf --min-volumen 100000 --summe
```

Zeitraum: `--woche` (Standard), `--monat`, `--gesamt` oder `--von`/`--bis`
(TT.MM.JJJJ). `--isin` und `--emittent` fragt die BaFin direkt; `--person`
filtert lokal im Export, weil die Personensuche der BaFin erst eine
Auswahlliste zeigt und keinen CSV-Export liefert. `--summe` hängt je
Emittent die Summe der Käufe und Verkäufe an. `--json` für Maschinen.
Zwischen zwei Abfragen wartet das Tool zwei Sekunden; frag die Datenbank
sparsam ab, sie ändert sich nur einmal am Tag („Stand der Daten“ auf der
Suchseite).

## Schritt 2: auf Neues warten

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" new
python3 "${CLAUDE_SKILL_DIR}/insider.py" new --art kauf --min-volumen 20000
```

Zeigt nur Meldungen, die beim letzten Lauf noch nicht da waren, und merkt
sie sich in `trader/state/insider.json`. Der erste Lauf zeigt die letzte
Woche. Exit-Code 1 heißt: nichts Neues. Liegt der letzte Lauf länger als
eine Woche zurück, fragt `new` den letzten Monat ab. Weil die BaFin die
Datenbank einmal täglich aktualisiert, reicht stündlich an Werktagen
mehr als aus: mit `/loop 1h` oder einer geplanten Aufgabe.

## Schritt 3: eine gespeicherte Datei lesen

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" parse export.csv --art kauf
```

Wenn die Datenbank nicht erreichbar ist: öffne die Suche im Browser, klick
unter der Trefferliste auf „CSV“ und lies die Datei mit `parse`. UTF-8 und
Latin-1 gehen beide. `--offline DATEI` macht dasselbe für `index` und `new`.

## Beispiel: eine echte Meldung

Aus dem BaFin-Export der letzten Woche, gelesen am 28.10.2026:

```
KST Beteiligungs AG (ISIN DE000A161309)
    Kauf: Schmitt, Martin (Aufsichtsrat), Aktie
    Durchschnittspreis 1,11 €, Volumen 6.660,00 € (Betrag, keine Stückzahl)
    Handel Mo 26.10.2026 an Tradegate, Mitteilung Di 27.10.2026, 1 Geschäftstag später, veröffentlicht Mi 28.10.2026 06:01 Uhr
```

Im selben Export: vier DEUTZ-Käufe über zusammen 249.075,00 € (Aufsichtsrat
Helmut Ernst 99.600,00 € zu 9,96 € an XETRA, dazu Aufsichtsrat
Dr. Dietmar Voggenreiter und zweimal Dr. Simone Voggenreiter „in enger
Beziehung“), und ein Vorstandskauf bei Smartbroker Holding AG (Kolbinger,
André, 8,24 €, 247.200,00 €), gehandelt am 21.10.2026, gemeldet am
27.10.2026: 4 Geschäftstage, also VERSPÄTET. Dann der Satz: „Das ist eine
öffentliche Meldung, einen Geschäftstag nach dem Kauf mitgeteilt. Sie sagt,
was ein Aufsichtsrat am 26.10. gekauft hat, nicht, was die Aktie als
Nächstes tut.“

Wenn jemand daraus handeln will, geht es den langen Weg: ein Vorstandskauf
ist ein Grund, einen Chart anzusehen, kein Setup. /dt-scanner und
/dt-einstieg entscheiden, ob es heute einen Trade gibt; /dt-budget rechnet
die Größe, /dt-risiko prüft, /dt-broker platziert erst nach deinem „ja“.
Viele Meldungen betreffen kleine Werte ohne XETRA-Handel und mit dünnem
Umsatz (KST Beteiligungs AG wird an Tradegate gehandelt): dann gibt es oft
gar keinen Daytrade.

## US-Werte

Für US-Aktien ist hier keine Entsprechung eingebaut. Der Pelosi-Tracker des
Originals (Kongress-Meldungen nach dem STOCK Act) wurde bewusst durch diesen
Skill ersetzt. US-Insidermeldungen (SEC Form 4) liest dieser Skill nicht.

## Was er nie tut

- Er sagt oder unterstellt nie, dass eine Führungskraft Insiderwissen
  genutzt hat, oder dass Nachkaufen von Vorstandskäufen den Markt schlägt.
  Keine Renditeversprechen.
- Er nennt nie ein Volumen als Stückzahl und nie ein Mitteilungs- oder
  Veröffentlichungsdatum als Handelsdatum.
- Er handelt nie automatisch und platziert nie eine Order.
- Er umgeht keine Sperren und keine Anmeldung der BaFin-Seite.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Directors' Dealings sind öffentliche Pflichtmeldungen, keine Insiderinformationen, und kommen Tage nach dem Geschäft.
- Wenn Trading zwanghaft wird: BIÖG-Telefonberatung zur Glücksspielsucht, 0800 1 37 27 00, kostenlos und anonym.
- Sag das dem User, wenn er nach Gewinnchancen, „sicheren“ Trades oder Empfehlungen fragt, und verweise auf `RISIKOHINWEISE.md` im Repo.

## Sicherheit

- Bildung und Werkzeug. Keine Anlageberatung, auch nicht im Sinne des WpHG.
  Eine FREIGABE ist eine Regelprüfung, keine Empfehlung. Die meisten
  Daytrader verlieren Geld; ESMA und BaFin warnen davor.
- Paper Trading ist Standard (`"paper": true`). Live zu gehen ist deine
  eigene Entscheidung, in deiner eigenen Config.
- Nichts in diesem Paket platziert eine Order außer dt-broker, und nur wenn
  alles drei gilt: dt-risiko hat genau diese Order heute freigegeben, du hast
  im Chat ausdrücklich „ja“ zu genau dieser einen Order geschrieben, und du
  hast auf Claudes eigener Karte „Allow once“ geklickt, weil das Order-Tool
  auf „Needs approval“ steht (Customize > Connectors > Tool-Berechtigungen).
  Ein Order-Tool nie auf „Always allow“ stellen. Im Modus
  `"broker": "manuell"` tippst du die Order selbst in deiner Broker-App ein.
- Keine Optionen, kein Margin, keine Leerverkäufe, kein Hebel, außer die
  Config erlaubt es und du bestätigst es.
- Broker-Schlüssel liegen in Umgebungsvariablen oder in der
  Claude-Desktop-Config, nie im Chat.
- Directors' Dealings sind ÖFFENTLICHE Meldungen nach Art. 19 MAR, bis zu
  drei Geschäftstage nach dem Geschäft mitgeteilt und danach veröffentlicht.
  Dieser Skill liest sie schnell; er hat kein Insiderwissen, und er sagt es.
