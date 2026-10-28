---
name: dt-einstieg
description: >-
  Einstiegs-Timer. Beobachtet ein Setup Kerze für Kerze und sagt dir den
  Moment für den Einstieg. Liest kostenlose Yahoo-Kerzen (5 oder 1 Minute),
  bildet die Opening Range (an XETRA 9:00 bis 9:15 Uhr, in New York 9:30 bis
  9:45 ET) und meldet den Einstieg bei der ersten geschlossenen Kerze, die
  ÜBER dem Range-Hoch schließt, oder über einem Level, das du vorgibst (etwa
  ein 20-Tage-Hoch aus dem Scanner), auf Wunsch mit Volumenprüfung. Sagt
  WARTEN und wie weit, AUSGELÖST mit Zeit und Kurs, ABGELAUFEN oder noch nicht
  offen, nennt ehrlich das Alter der Daten (XETRA bei Yahoo ca. 15 Minuten
  verzögert) und schreibt trader/entry.json für /dt-ausstieg. Nur Long.
  Platziert nie eine Order. Nutze den Skill, wenn jemand sagt „wann steige
  ich ein“, „beobachte SAP“, „ist es ausgelöst“, „sag mir, wann ich kaufen
  soll“, „hat SAP die Range gebrochen“, „Entry-Timing“, „prüf meine
  Watchlist“, oder auf Englisch „tell me when to get in“, „watch the setup“,
  „has it broken out“, „time my entry“; nach /dt-scanner und /dt-news, vor
  /dt-ausstieg.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m] [--now \"2026-10-27 10:55\"]"
---

# dt-einstieg

Der Einstiegs-Timer macht aus einem Setup einen Moment: die Kerze, die es
bestätigt. Er liest Kerzen (5 oder 1 Minute) und wartet, bis jede fertig ist.
Ein Kurs, der mitten in einer Kerze über das Hoch sticht, ist kein Einstieg.
Eine Kerze, die darüber SCHLIESST, schon. Dann nennt er Zeit und Kurs, schreibt
beides für den Ausstiegsplaner auf und hört auf. Er kauft nie etwas. Die
meisten Daytrader verlieren Geld (ESMA und BaFin warnen davor), und ein sauberes
Signal ändert daran nichts.

Der Markt folgt aus dem Symbol: `SAP.DE` ist XETRA (9:00 bis 17:30 Uhr, Euro),
`TSLA` ist US (9:30 bis 16:00 ET, Dollar). Alle Regeln gelten ab der Eröffnung
des jeweiligen Marktes und in seiner Ortszeit.

`${CLAUDE_SKILL_DIR}` unten ist der Ordner dieses Skills (wo diese SKILL.md liegt).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check SAP.DE                # 15-Minuten-Range, 5-Minuten-Kerzen
python3 "${CLAUDE_SKILL_DIR}/entry.py" check SAP.DE --write        # zusätzlich trader/entry.json speichern
python3 "${CLAUDE_SKILL_DIR}/entry.py" check SAP.DE --setup level --level 215,00
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TSLA --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch SAP.DE --until 17:00  # eine Zeile je Kerze, stoppt beim Auslöser
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                   # jeder Treffer in trader/watchlist.json
```

Weitere Flags: `--or-minutes N` (Standard 15), `--json`, `--market xetra|us`
(nur nötig, wenn das Symbol es nicht verrät), `--offline DATEI` (gespeichertes
Yahoo-Chart-JSON, `.json` oder `.json.gz`, oder ein Ordner mit `<SYMBOL>.json`),
`--now "2026-10-27 10:55"` (Ortszeit des Marktes, mit `Z` oder Offset absolut),
um einen Tag nachzuspielen. `watch` mit `--now` oder `--offline` läuft auf einer
simulierten Uhr und spielt den Tag Kerze für Kerze ohne Warten ab.

## Was er liest und schreibt

| Datei | Inhalt |
| --- | --- |
| `trader/watchlist.json` | die Treffer des Scanners (`hits[].symbol`), für `watchlist` |
| `trader/config.json` | `no_entries_before` / `no_entries_after` oder je Markt `"zeiten": {"xetra": {...}, "us": {...}}`. Standard XETRA 09:15 / 17:00, US 09:45 / 15:30. Optional |
| Yahoo-Chart-API | heutige Kerzen, `range=1d&interval=5m` (oder `1m`): kostenlos, inoffiziell, verzögert |
| `trader/entry.json` | bei `check --write` oder wenn `watch` auslöst: symbol, market, currency, setup, status, time, bar_start, bar_index, price, level, opening_range, delay_minutes |

Die Schlüssel in `trader/entry.json` sind die des Originals (`time` bleibt
„10:55 AM“, Preise mit Punkt), dazu kommen `market`, `currency` und
`delay_minutes`.

## Die Regel

- **Opening Range (orb).** Hoch und Tief der ersten 15 Minuten: an XETRA die
  Kerzen 9:00, 9:05 und 9:10 Uhr, in New York 9:30, 9:35 und 9:40 ET, oder
  fünfzehn 1-Minuten-Kerzen. Das Level ist das Range-Hoch.
- **Level.** Ein Kurs, den du vorgibst, etwa ein 20-Tage-Hoch aus `/dt-scanner`.
- **Der Auslöser** ist die erste geschlossene Kerze nach der Range, die ÜBER
  dem Level schließt. Ein Docht darüber ist kein Auslöser. Ein Schluss genau
  auf dem Level liegt nicht darüber.
- **Die Zeit** ist der Schluss dieser Kerze (die 10:50-Kerze schließt um
  10:55 Uhr), der Kurs ist ihr Schlusskurs, auf den Cent.
- **Nur geschlossene Kerzen zählen.** Eine Kerze ist zu, wenn die Uhr ihren
  Start plus 5 (oder 1) Minuten passiert hat und Yahoo bis dahin geliefert hat.
  Yahoos Live-Tick (etwa 9:57:36) ist nie eine Kerze.
- **Volumen, wenn du willst.** `--min-volume-x 1.5` verlangt zusätzlich das
  1,5-Fache des Durchschnittsvolumens der Range-Kerzen.
- **Zeitfenster.** An XETRA keine Einstiege vor 9:15 und nach 17:00 Uhr, in
  New York vor 9:45 und nach 15:30 ET (Config). An einem verkürzten Tag rückt
  die Grenze mit dem Schluss vor: an XETRA am 30.12.2026 (Schluss 14:00 Uhr)
  auf 13:30 Uhr, an der NYSE bei Schluss 13:00 ET auf 12:30 ET.
- **Kalender.** Wochenenden und Börsenfeiertage aus dem Handelskalender des
  Marktes (XETRA 2026: 1.1., 3.4., 6.4., 1.5., 24.12., 25.12., 31.12.).
  Pfingstmontag, Fronleichnam und der 3. Oktober werden an XETRA gehandelt.
- **Was er sagt.** WARTEN (und wie weit der letzte Schluss vom Level weg ist),
  AUSGELÖST, ABGELAUFEN oder KEINE DATEN. Vor der Eröffnung: noch nicht offen.
  Bis zum Ende der Range: Range bildet sich.

## Datenalter: ehrlich sein

Yahoo liefert XETRA-Kerzen ca. 15 Minuten verzögert. Am 28.10.2026 um 10:12 Uhr
war die letzte 5-Minuten-Kerze die von 9:55 Uhr. Das Tool sagt das in jeder
Antwort und verkauft den Status nicht als Echtzeit:

- Es zeigt das Alter der letzten Kerze und des letzten Kurses („Datenstand:
  letzte Kerze 9:55 Uhr, 17 Minuten alt; letzter Kurs von 9:57 Uhr (14 Minuten alt)“).
- Eine Kerze zählt erst, wenn Yahoo ihren Schluss geliefert hat, spätestens
  15 Minuten plus eine Minute nach ihrem Schluss. Die Range steht erst, wenn
  alle drei Range-Kerzen da sind. ABGELAUFEN kommt erst, wenn die Kerzen bis
  17:00 Uhr geliefert sind.
- Löst es live aus, ist die Kerze an XETRA schon rund 15 Minuten alt. Dann sagt
  es das und schickt dich zum aktuellen Kurs in deiner Broker-App.
- `watch` wacht live an XETRA erst 15 Minuten nach jedem Kerzenschluss auf,
  statt Yahoo im Halbminutentakt zu fragen.
- Bei `--now` auf gespeicherten Daten sagt es „Rückblick auf gespeicherte Kerzen“.

## Schritte

1. Hol dir das Symbol vom Nutzer, oder lass nach `/dt-scanner` `entry.py
   watchlist` laufen. Prüf es vorher mit `/dt-news`.
2. Lass `entry.py check SYMBOL` laufen. Sag dem Nutzer den Status in einer
   Zeile: WARTEN und wie weit, AUSGELÖST mit Zeit und Kurs, oder ABGELAUFEN.
   Nenn das Datenalter mit, an XETRA immer.
3. Zum Warten kann Claude `entry.py watch SYMBOL --until 17:00` im
   Hintergrund laufen lassen, oder `entry.py check SYMBOL --write` per `/loop`
   alle 5 Minuten. `watch` druckt eine Zeile je Kerze und endet mit Exit 0 beim
   Auslöser (schreibt `trader/entry.json`) oder Exit 1, wenn das Setup
   abläuft. Halt den Rechner wach: ein schlafender Laptop pausiert die
   Beobachtung und holt beim Aufwachen verspätet auf.
4. Löst es aus, nenn Zeit und Kurs und sag, dass nichts platziert wurde. Ist
   der Auslöser älter als eine Kerze, sag auch das: ein später Einstieg ist ein
   anderer Trade.
5. Übergib an `/dt-ausstieg`, um Stop und Ziel festzulegen, BEVOR irgendetwas
   gekauft wird.

## Beispiel XETRA: SAP.DE am Di 27.10.2026

Echte 5-Minuten-Kerzen von Yahoo (aufgezeichnet am 28.10.2026). Die Opening
Range von 9:00 bis 9:15 Uhr reicht von 211,70 € bis 214,75 €. Die 10:40-Kerze
sticht mit dem Docht genau an 214,75 €, schließt aber bei 214,65 €: kein
Auslöser. Um 10:54 Uhr läuft die 10:50-Kerze noch, also wartet er:

```
$ entry.py check SAP.DE --now "2026-10-27 10:54"
SAP.DE  Di 27.10.2026 10:54 Uhr  Opening-Range-Breakout (15-Minuten-Range) auf 5-Minuten-Kerzen (Yahoo, kostenlos, inoffiziell)
Opening Range 9:00 bis 9:15 Uhr: Hoch 214,75 €, Tief 211,70 € (3 von 3 Kerzen).
WARTEN  letzter Schluss 214,70 € (10:45-Kerze), 0,05 € unter dem Range-Hoch 214,75 € (-0,02 %).
Die 10:50-Kerze läuft noch (bisher 214,90 €, schließt 10:55 Uhr); sie zählt erst, wenn sie geschlossen ist.
Rückblick auf gespeicherte Kerzen (Datei bis Mi 28.10.2026 9:57 Uhr). Live kämen diese Kerzen bei Yahoo ca. 15 Minuten verzögert.
```

Um 10:55 Uhr ist die Kerze zu:

```
$ entry.py check SAP.DE --now "2026-10-27 10:55"
SAP.DE  Di 27.10.2026 10:55 Uhr  Opening-Range-Breakout (15-Minuten-Range) auf 5-Minuten-Kerzen (Yahoo, kostenlos, inoffiziell)
Opening Range 9:00 bis 9:15 Uhr: Hoch 214,75 €, Tief 211,70 € (3 von 3 Kerzen).
AUSGELÖST 10:55 Uhr zu 214,90 €: die 10:50-Kerze (Kerze 22) hat über dem Range-Hoch 214,75 € geschlossen (+0,07 %).
Rückblick auf gespeicherte Kerzen (Datei bis Mi 28.10.2026 9:57 Uhr). Live kämen diese Kerzen bei Yahoo ca. 15 Minuten verzögert.
Jetzt ist der Moment für den Einstieg, wenn du den Trade nimmst. Es wurde nichts platziert.
Live siehst du diese Kerze bei Yahoo erst ca. 15 Minuten später: prüf den aktuellen Kurs in deiner Broker-App, bevor du handelst.
Weiter: Stop und Ziel festlegen, BEVOR du kaufst: /dt-ausstieg (exit.py plan --from trader/entry.json).
```

BMW.DE hat am selben Tag sein Range-Hoch von 57,50 € nie überschlossen: um
17:00 Uhr steht dort ABGELAUFEN. Und live am 28.10.2026 um 10:12 Uhr zeigt SAP.DE
„Datenstand: letzte Kerze 9:55 Uhr, 17 Minuten alt“, weil Yahoo nachhinkt.

## Beispiel US: TSLA am Mo 19.10.2026

5-Minuten-Kerzen, Opening Range 354,47 $ bis 362,18 $. Um 10:12 ET läuft die
10:10-Kerze noch, also wartet er:

```
WARTEN  letzter Schluss 361,68 $ (10:05-Kerze), 0,50 $ unter dem Range-Hoch 362,18 $ (-0,14 %).
Die 10:10-Kerze läuft noch (bisher 364,18 $, schließt 10:15 ET); sie zählt erst, wenn sie geschlossen ist.
```

Um 10:15 ET ist die Kerze zu:

```
TSLA  Mo 19.10.2026 10:15 ET (16:15 Uhr)  Opening-Range-Breakout (15-Minuten-Range) auf 5-Minuten-Kerzen (Yahoo, kostenlos, inoffiziell)
Opening Range 9:30 bis 9:45 ET: Hoch 362,18 $, Tief 354,47 $ (3 von 3 Kerzen).
AUSGELÖST 10:15 ET (16:15 Uhr) zu 364,18 $: die 10:10-Kerze (Kerze 8) hat über dem Range-Hoch 362,18 $ geschlossen (+0,55 %).
Jetzt ist der Moment für den Einstieg, wenn du den Trade nimmst. Es wurde nichts platziert.
Weiter: Stop und Ziel festlegen, BEVOR du kaufst: /dt-ausstieg (exit.py plan --from trader/entry.json).
```

Mit `--min-volume-x 1` ist die 10:10-Kerze zu dünn (das 0,60-Fache des
Range-Volumens), und der Auslöser rückt auf 10:35 ET bei 365,75 $ (die
10:30-Kerze, das 7,98-Fache).

## Regeln

- Kerze für Kerze, auf kostenlosen Yahoo-Kerzen. Sie sind inoffiziell und
  verzögert, an XETRA um ca. 15 Minuten. Sag das, wenn es auf Minuten ankommt.
- Ein Signal ist eine Information, keine Order und kein Versprechen. Nichts hier
  verspricht Gewinner-Trades oder Geld.
- Nur Long. Will der Nutzer short gehen, sag ihm, dass dieses Paket nur Long plant.
- Ein Auslöser je Setup und Tag: der erste Schluss darüber. Spätere Schlüsse
  setzen ihn nicht zurück.
- Melde nie einen Einstieg zu früh, nur weil eine Kerze so aussieht, als
  würde sie darüber schließen.
- Steuern und Recht: keine Anlageberatung im Sinne des WpHG und keine
  Steuerberatung. Gewinne unterliegen der Abgeltungsteuer (25 % plus Soli und
  ggf. Kirchensteuer), Aktienverluste sind nur mit Aktiengewinnen verrechenbar.

## Was er nie tut

Er platziert nie eine Order, berechnet nie eine Positionsgröße, setzt nie den
Stop (das macht `/dt-ausstieg`), verschiebt nie nachträglich das Level und zählt
nie eine Kerze, die noch nicht geschlossen ist. Er startet `/dt-broker` nie aus
einer Beobachtung im Hintergrund: dort ist niemand, der „ja“ sagen kann.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Ein Auslöser ist ein Chart-Signal auf verzögerten Daten, keine Empfehlung. Prüf den echten Kurs in deiner Broker-App.
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
