---
name: dt-zeitmaschine
description: >-
  Zeitmaschine. Spielt einen geplanten Daytrade durch, bevor du einen Euro
  riskierst: 10.000 simulierte Sitzungen plus jedes Mal, als dasselbe Setup an
  einem vergangenen Tag gefeuert hat. Nimmt den Plan aus dt-ausstieg (Einstieg,
  Stop, Ziel), baut den Rest des Tages 10.000-mal aus den eigenen
  5-Minuten-Kerzen der Aktie der letzten ~60 Tage nach (XETRA und US, Slots in
  Ortszeit des Marktes) und fährt dieselbe Regel auf jeder vergangenen Sitzung.
  Zeigt die Chancen für Ziel zuerst, Stop zuerst oder keins von beiden bis
  Handelsschluss, den Kurs zum Schluss, das durchschnittliche R, die Rückschau
  und ein ehrliches Urteil, dann weiter zu /dt-budget. Nutze den Skill, wenn
  jemand sagt „wie stehen die Chancen“, „spiel den Trade durch“, „Zeitmaschine“,
  „Backtest“, „Monte Carlo“, „was wäre wenn“, „wie oft hat das funktioniert“,
  „ist das ein Münzwurf“, „simulier den Trade“, oder „run the time machine“,
  „what are the odds“, „backtest this setup“, und nachdem /dt-ausstieg einen
  Plan geschrieben hat, vor /dt-budget.
argument-hint: "[Pfad zu plan.json, oder SYMBOL wie SAP.DE]"
---

# dt-zeitmaschine

Die Zeitmaschine sitzt zwischen dem Plan und dem Geld. dt-ausstieg hat Einstieg,
Stop und Ziel gesetzt. Bevor irgendetwas bemessen oder abgeschickt wird, stellt
dieser Skill eine Frage: Wenn heute so läuft wie die letzten ~60 Tage dieser
Aktie, wie oft erreicht der Plan zuerst das Ziel, zuerst den Stop oder keins von
beiden? Die Antwort kommt aus 10.000 Durchläufen und aus der echten Bilanz
derselben Regel an jedem vergangenen Tag.

**Das ist eine Simulation, keine Vorhersage.** Sie ist aus den letzten ~60 Tagen
5-Minuten-Kerzen der Aktie gebaut. Quartalszahlen, Ad-hoc-Meldungen,
Handelsaussetzungen (Volatilitätsunterbrechungen) und Nachrichten können Dinge
tun, die in diesen 60 Tagen nie passiert sind; die Vergangenheit kann sie nicht
abbilden. Die meisten Daytrader verlieren Geld (ESMA und BaFin warnen davor), und
ein gut aussehender Durchlauf ändert daran nichts.

`${CLAUDE_SKILL_DIR}` unten ist der Ordner dieses Skills (dort liegt diese SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                    # trader/plan.json, 10.000 Durchläufe, Seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write            # zusätzlich trader/timemachine.json speichern
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until glatt      # jeden Durchlauf zur Glattstell-Zeit beenden
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol SAP.DE --date 2026-10-27 \
    --entry 214.90 --stop 213.22 --target 216.58 --entry-time 10:55
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart --from           # ASCII-Fächer des gespeicherten Laufs
```

Weitere Flags: `--replays N`, `--seed N` (Standard 19), `--window N` (Standard 2
Kerzen), `--until 17:25` oder `--until glatt` (die `flat_by`-Zeit des Plans),
`--market xetra|us` (sonst aus dem Symbol), `--config` (Standard
`trader/config.json`), `--offline DATEI` (gespeichertes Yahoo-Chart-JSON, `.json`
oder `.json.gz`), `--now "2026-10-27 11:00"` (Ortszeit des Marktes) setzt die Uhr.

## Markt und Uhrzeiten

Der Markt folgt aus dem Symbol: `SAP.DE` ist XETRA, `TSLA` ist US. Alle Zeiten
sind Ortszeit dieses Marktes.

| Markt | Sitzung | Kerzen je voller Tag | verkürzt | glatt bis (Standard) |
| --- | --- | --- | --- | --- |
| XETRA | 9:00 bis 17:30 Uhr | 102 | 30.12.2026 bis 14:00 Uhr | 17:25 Uhr |
| US | 9:30 bis 16:00 ET | 78 | 27.11. und 24.12.2026 bis 13:00 ET | 15:55 ET |

Die Tageszeit-Slots entstehen in Ortszeit. Die Zeitumstellung (Berlin 25.10.2026,
New York 01.11.2026) verschiebt sie nicht: die 9:00-Uhr-Kerze von SAP ist am
Freitag 23.10. (MESZ, 07:00 UTC) und am Montag 26.10. (MEZ, 08:00 UTC) beide Slot 0.
Handelsfreie Tage lehnt das Tool mit einem Satz ab. `flat_by` kommt aus dem Plan,
sonst aus `trader/config.json` (`zeiten`, `flat_by`), sonst aus dem Standard des Marktes.

## Was es liest und schreibt

| Datei | Inhalt |
| --- | --- |
| `trader/plan.json` | der Plan aus dt-ausstieg: symbol, date, entry, entry_time / entry_bar, stop, stop_rule, target, target_r, opening_range, flat_by |
| `trader/config.json` | optional: market, zeiten, flat_by |
| Yahoo-Chart-API | eine Anfrage: 60 Tage 5-Minuten-Kerzen (`range=60d&interval=5m`), kostenlos und inoffiziell, kann verzögert sein (XETRA etwa 15 Minuten) |
| `trader/timemachine.json` | mit `--write`: `{plan, mc, history}` plus `verdict`. `mc` enthält die Chancen, Perzentile, die Fächer-Bänder, 160 Beispielpfade und ein Histogramm mit 24 Klassen. Schlüssel wie im Original, dazu `plan.market` |

## So funktioniert es

1. **Der Pool.** Nur VOLLE Sitzungen vor dem Tag des Plans zählen (XETRA alle 102
   Kerzen, US alle 78). Verkürzte Tage, Tage mit fehlenden Kerzen und heute
   bleiben draußen und werden genannt. Jede Kerze wird zu vier Verhältnissen zur
   Kerze davor: Eröffnung, Hoch, Tief und Schluss geteilt durch den vorigen Schluss.
2. **Ein Durchlauf.** Start beim Einstiegskurs. Für jede verbleibende Kerze zieht
   er zufällig eine vergangene Kerze derselben Tageszeit (±2 Kerzen) und skaliert
   sie auf den aktuellen Kurs. Kerze für Kerze prüft er zuerst den Stop, dann das
   Ziel. Eine Kerze, die beide berührt, zählt als Stop.
3. **10.000 Durchläufe** ergeben vier Anteile. Ziel zuerst. Stop zuerst. Weder
   noch: der Trade ist bei `--until` noch offen (Standard Handelsschluss, an einem
   verkürzten Tag dessen Schluss). Im Plus: Ziel zuerst oder bei `--until` über
   dem Einstieg. R ist +1 an einem 1R-Ziel, -1 am Stop, sonst der Abstand zum
   Einstieg bei `--until` geteilt durch das Risiko. Eine Kurslücke durch den Stop
   zählt hier -1R; eine echte Ausführung kann schlechter sein.
4. **Die Rückschau.** Die Regel des Plans (dieselbe Opening Range ab Eröffnung des
   Marktes, also 9:00 Uhr an XETRA und 9:30 ET in New York, dieselbe Stop-Regel,
   dasselbe Ziel-R) läuft auf jeder dieser Sitzungen noch einmal. Das ist, was
   wirklich passiert ist, keine Simulation.
5. **Das Urteil** ist eine Zeile aus den Zahlen. Es schaut nur auf die
   Durchläufe, die eine Seite erreicht haben, und fragt, wie oft das Ziel zuerst
   kam. Ein größeres Ziel muss seltener kommen, um plusminus null zu ergeben:
   1 von (1 + R), also 50 % bei 1R, 33 % bei 2R, 25 % bei 3R. Unter 5 Punkten
   Abstand: „Nahe an einem Münzwurf“ bei 1R, „Nahe am Break-even“ bei anderem R.
   5 bis 15 Punkte: „Neigt zum Ziel“ oder „Neigt zum Stop“. Ab 15: „Deutlich
   Richtung“ Ziel oder Stop. Ein 2R-Plan mit Ziel zuerst 24,1 % und Stop zuerst
   50,5 % ist also nahe am Break-even (er braucht 33 % der 74,6 %, die eine Seite
   erreichen, und bekommt 32 %), kein Verlierer.
6. **Unter dem Urteil** steht, wenn es zutrifft: eine Zeile, wenn mehr als 40 %
   der Durchläufe keine Seite erreichen (dann entscheidet der Kurs bei
   `--until`), und das durchschnittliche R, wenn sein Vorzeichen gegen die
   Neigung läuft.

**Der Seed.** Die Züge kommen aus Pythons `random.Random(seed)`, Standard 19.
Gleicher Plan, gleiche Daten, gleicher Seed: gleiche Zahlen, auf jedem Rechner.
Nenn den Seed bei jedem Ergebnis, damit man es wiederholen kann.

**Nur 5-Minuten-Kerzen.** Yahoo hält 60 Tage 5-Minuten-Kerzen, aber nur etwa 7
Tage 1-Minuten-Kerzen, zu wenige Sitzungen für einen fairen Pool. Das Tool lehnt
in einem Satz ab, wenn es weniger als 20 volle Sitzungen gibt, wenn die
Einstiegskerze nicht in den Daten ist (falscher Tag, noch nicht fertig, ein Tag in
der Zukunft, ein Feiertag) oder wenn der Plan keinen Sinn ergibt (Stop über dem
Einstieg eines Kaufs, Einstieg neben dem 5-Minuten-Raster). Eine laufende Kerze
wird nie benutzt.

## Schritte

1. Prüf, dass `trader/plan.json` der heutige Plan aus `/dt-ausstieg` ist. Gibt es
   keinen, lass den zuerst laufen oder gib den Plan als Flags an.
2. Starte `timemachine.py run --write --until glatt`, damit „weder noch“ heißt:
   noch offen zu der Zeit, zu der du glattstellen würdest.
3. Sag dem Nutzer in dieser Reihenfolge: die vier Anteile, Median und 5-bis-95-Spanne
   des Kurses am Ende, das durchschnittliche R, die Rückschau, dann die Urteilszeile
   und jede Zeile darunter genau wie gedruckt. Nenn den Seed.
4. Ist das Urteil ein Münzwurf oder nahe am Break-even, sag das klar. Nichts
   schönreden. Widersprechen sich Rückschau und Durchläufe, sag auch das.
5. Sag einmal, dass das aus den letzten ~60 Tagen gebaut ist und keine Vorhersage
   ist. Zahlen, Ad-hoc-Meldungen, Handelsaussetzungen und Nachrichten kann die
   Vergangenheit nicht abbilden. Prüf vorher `/dt-news` für die Aktie.
6. Will der Nutzer den Trade trotzdem, weiter zu `/dt-budget` für die Größe.

## Beispiel US: TSLA, Mo 19.10.2026

Die 15-Minuten-Opening-Range reicht von 354,47 bis 362,18. Die 10:10-Kerze
schließt darüber: Einstieg 364,18 um 10:15 ET (Kerze 8), Stop 358,32 (Range-Mitte,
abgerundet), Ziel 370,04 (1R, Risiko 5,86 $ je Aktie). Seed 19, `--now "2026-10-19 10:50"`.

```
10.000 Durchläufe für den Rest der Sitzung, 10:15 ET bis 16:00 ET (69 Fünf-Minuten-Kerzen), Seed 19.
  Ziel zuerst    29,4 %
  Stop zuerst    25,5 %
  weder noch     45,1 %   zum Handelsschluss (16:00 ET) noch offen
  im Plus        51,7 %   Ziel zuerst, oder um 16:00 ET über dem Einstieg
  Kurs um 16:00 ET: Median 364,36, 90 % der Durchläufe zwischen 355,54 und 373,54.
  Durchschnitt: +0,034 R (R = das Risiko von 5,86: +1R am Ziel, -1R am Stop).
Rückschau: dieselbe Regel (15-Minuten-Range ab 09:30 ET, Stop an der Range-Mitte, Ziel 1R)
feuerte in diesen 59 echten Sitzungen 33-mal: 13 Ziel, 15 Stop, 5 weder noch. Durchschnitt -0,062 R.
Nahe an einem Münzwurf: Ziel zuerst 29,4 % gegen Stop zuerst 25,5 %.
45,1 % der Durchläufe erreichten bis 16:00 ET keine Seite; bei denen entscheidet der Kurs um 16:00 ET.
```

Bei 1R muss das Ziel in der Hälfte der Durchläufe, die eine Seite erreichen,
zuerst kommen. Es kam in 53,6 %. Die Durchläufe sind nahe an einem Münzwurf, und
die echte Rückschau war leicht schlechter als ausgeglichen. Das ist die ehrliche
Antwort für dieses Setup, und die soll der Nutzer hören, bevor `/dt-budget` die
Größe bemisst.

## Beispiel XETRA: SAP.DE, Di 27.10.2026

Aus der echten Aufzeichnung vom 28.10.2026 (Yahoo, 60 Tage 5-Minuten-Kerzen). Die
Range von 9:00 bis 9:15 Uhr reicht von 211,70 bis 214,75. Die 10:50-Kerze schließt
als erste darüber: Einstieg 214,90 um 10:55 Uhr (Kerze 22), Stop 213,22
(Range-Mitte, abgerundet), Ziel 216,58 (1R, Risiko 1,68 € je Aktie), glatt bis
17:25 Uhr. Seed 19, `--now "2026-10-28 10:13" --until glatt`.

```
10.000 Durchläufe für den Rest der Sitzung, 10:55 Uhr bis 17:25 Uhr (78 Fünf-Minuten-Kerzen), Seed 19.
Jede Kerze kommt ganz aus den echten 5-Minuten-Kerzen von SAP.DE zur selben Tageszeit (±2 Kerzen),
aus den letzten 57 vollen Sitzungen (06.08.2026 bis 26.10.2026).
  Ziel zuerst    64,0 %
  Stop zuerst    34,5 %
  weder noch     1,5 %    um 17:25 Uhr noch offen
  im Plus        64,8 %   Ziel zuerst, oder um 17:25 Uhr über dem Einstieg
  Kurs um 17:25 Uhr: Median 216,06, 90 % der Durchläufe zwischen 210,60 und 221,52.
  Durchschnitt: +0,296 R (R = das Risiko von 1,68: +1R am Ziel, -1R am Stop).
Rückschau: dieselbe Regel (15-Minuten-Range ab 09:00 Uhr, Stop an der Range-Mitte, Ziel 1R)
feuerte in diesen 57 echten Sitzungen 48-mal: 23 Ziel, 20 Stop, 5 weder noch. Durchschnitt +0,057 R.
Neigt zum Ziel: Ziel zuerst 64,0 % gegen Stop zuerst 34,5 %.
1 kurze Sitzung(en) ausgelassen (verkürzte Tage oder Lücken): 16.10.2026.
```

Der Pool reicht über die Zeitumstellung vom 25.10. hinweg (23.10. und 26.10. sind
beide volle 102-Kerzen-Tage). Der 16.10. fehlt, weil Yahoo dort eine Kerze ohne
Kurs liefert. Die Durchläufe neigen zum Ziel, die echte Rückschau war mit 23 zu 20
und +0,057 R viel knapper. Und an diesem Dienstag selbst berührte die 14:00-Kerze
den Stop bei 213,22: genau deshalb ist das eine Simulation, keine Vorhersage.

## Regeln

- Jede Zahl kommt aus dem Lauf. Nie einen Münzwurf zu einem Vorteil aufrunden.
- Die Urteilszeile und die Zeilen darunter druckt das Tool. Wiederhole sie, schreib
  sie nicht um. Einen 2R- oder 3R-Plan nie nur nach Ziel zuerst gegen Stop zuerst
  beurteilen: das Urteil berücksichtigt das R des Ziels schon.
- Simulierte Chancen sind keine Vorhersagen und keine Versprechen. Sag es einmal, klar.
- Kostenlose Yahoo-Daten sind inoffiziell und können verzögert sein. Es sind
  5-Minuten-Kerzen, Kerze für Kerze geprüft, nie einzelne Ticks, nie live.
- Immer den Seed nennen, damit jeder Lauf wiederholbar ist.
- Ein Plan je Lauf. Geänderter Einstieg, Stop, Ziel oder Tag ist ein neuer Lauf.
- Keine Steuer- und keine Anlageberatung. Steuerfragen (Abgeltungsteuer,
  Verlustverrechnung) gehören zu einer Steuerberatung.

## Was es nie tut

Es platziert nie eine Order, bemisst nie eine Position, ändert nie den Plan und
nennt kein Ergebnis sicher. Es druckt keine Gewinn-und-Verlust-Rechnung. Es nutzt
nie eine Kerze, die noch nicht geschlossen ist, und mischt nie die Kerzen von heute
in den Pool.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Die Ergebnisse sind Simulationen aus vergangenen Kerzen. Sie sagen nichts Verlässliches über den nächsten Trade.
- Wenn Trading zwanghaft wird: BIÖG-Telefonberatung zur Glücksspielsucht, 0800 1 37 27 00, kostenlos und anonym.
- Sag das dem User, wenn er nach Gewinnchancen, „sicheren“ Trades oder Empfehlungen fragt, und verweise auf `RISIKOHINWEISE.md` im Repo.

## Sicherheit

- Bildung und Werkzeug, keine Anlageberatung (auch nicht im Sinne des WpHG). Eine
  FREIGABE ist eine Regelprüfung, keine Empfehlung.
- Paper Trading ist Standard (`"paper": true`). Live zu gehen ist deine eigene
  Entscheidung, in deiner eigenen Config.
- Nichts in diesem Paket platziert eine Order außer dt-broker, und nur wenn alles
  drei gilt: dt-risiko hat genau diese Order heute freigegeben, du hast im Chat
  ausdrücklich „ja“ zu genau dieser einen Order geschrieben, und du hast auf
  Claudes eigener Karte „Allow once“ geklickt, weil das Order-Tool auf „Needs
  approval“ steht (Customize > Connectors > Tool-Berechtigungen). Ein Order-Tool
  nie auf „Always allow“ stellen. Im Modus `"broker": "manuell"` tippst du die
  Order selbst in deiner Broker-App ein.
- Keine Optionen, kein Margin, keine Leerverkäufe, kein Hebel, außer die Config
  erlaubt es und du bestätigst es.
- Broker-Schlüssel liegen in Umgebungsvariablen oder in der Claude-Desktop-Config,
  nie im Chat.
