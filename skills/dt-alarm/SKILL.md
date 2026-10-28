---
name: dt-alarm
description: >-
  Kursalarme und Börsenuhr für XETRA und US. Meldet sich, wenn ein Kurs, ein
  Stop, ein Ziel, eine Uhrzeit oder die Eröffnung erreicht ist. Macht aus dem
  Trade-Plan von /dt-ausstieg in einem Schritt drei Alarme (Stop, Ziel und
  „Glattstellen vor Handelsschluss“, an XETRA 17:25 Uhr, in den USA 15:55 ET),
  dazu Marken darüber und darunter, Prozentbewegungen zum Vortagesschluss,
  beliebige Uhrzeiten und die Glocke zur Eröffnung (XETRA 9:00 Uhr, NYSE 9:30
  ET), jeder Alarm einmal. Kennt Feiertage und verkürzte Tage 2026 und 2027
  (Jahresschlussbörse 30.12.2026 bis 14:00 Uhr), holt kostenlose, verzögerte
  Kurse (Yahoo, für US auch Stooq) und schreibt trader/prices.json. Platziert
  nie eine Order. Nutze den Skill, wenn jemand sagt „Alarm wenn SAP 200
  erreicht“, „sag Bescheid, wenn der Stop fällt“, „Kursalarm“, „Preisalarm“,
  „erinnere mich ans Glattstellen“, „beobachte meinen Trade“, „hat XETRA
  offen“, „wann öffnet die Börse“, „hol mir einen Kurs“, "alert me when",
  "watch my stop", oder direkt nachdem /dt-ausstieg einen Plan geschrieben hat.
argument-hint: "[Symbol] [Kurs]"
---

# dt-alarm

Der Kursalarm beobachtet die Zahlen, damit du nicht auf den Chart starren
musst. Ein Alarm ist eine Information, keine Order: Wenn ein Stop-Alarm
klingelt, verkauft dieser Skill nichts. Ein Alarm ist kein Stop. Der Stop
gehört als Stop-Order zu deinem Broker; nur der kann dich wirklich ausstoppen.
Viele Neobroker kennen keine Bracket- oder OCO-Order: dann liegt beim Broker
der Stop, und das Ziel beobachtet dieser Skill.

`${CLAUDE_SKILL_DIR}` unten ist der Ordner dieses Skills (wo diese SKILL.md liegt).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # XETRA offen oder zu, nächste Eröffnung
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock --market us              # dasselbe für NYSE/Nasdaq
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # Stop, Ziel, Glattstellen aus trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell             # Glocke: XETRA 9:00 Uhr (--market us: 9:30 ET)
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol SAP.DE --below 200
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol SAP.DE --stop 213,22
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol SAP.DE --target 216,58
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 17:25 --label "Glattstellen" --before-close
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol SAP.DE --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # Exit 0 = etwas hat ausgelöst
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote SAP.DE --write           # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # Symbole aus Depot und Plan
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset sap.de-plan-stop
```

`--now "2026-10-27 17:25"` stellt die Uhr (Ortszeit des Markts: deutsche Zeit
für XETRA, New Yorker Zeit für US, oder `...Z` für UTC); `--offline ORDNER`
liest gespeicherte Kursdateien statt des Netzes; `--market xetra|us` gilt für
Regeln ohne Symbol. Kurse dürfen mit Komma kommen (`211,50`).

## Welcher Markt

Der Markt einer Regel folgt aus ihrem Symbol: `SAP.DE` ist XETRA (EUR,
Uhrzeiten in Uhr), `TSLA` ist US (USD, Uhrzeiten in ET, mit deutscher Zeit in
Klammern). Regeln ohne Symbol (Glocke, Zeitalarm) bekommen beim Anlegen
`"market"`: aus `--market`, sonst `"market"` in trader/config.json, sonst
XETRA. Ein `check` darf Regeln beider Märkte mischen; jede läuft nach ihrer
eigenen Uhr und ihrem eigenen Kalender.

## Was es liest und schreibt

| Datei | was |
| --- | --- |
| `trader/plan.json` | der Trade aus /dt-ausstieg, für `add --from-plan` (nutzt `market`, falls vorhanden) |
| `trader/alerts.json` | die Regeln (`alerts.example.json` in diesem Ordner) |
| `trader/state/alerts.json` | welche Regel wann ausgelöst hat, damit jede nur einmal klingelt |
| `trader/prices.json` | die letzten Kurse, zusammengeführt, für /dt-budget und /dt-risiko. Schlüssel wie im Original; `detail.time` (Kurszeit) und `detail.fetched` (Abruf) in UTC |
| `trader/portfolio.json` | die gehaltenen Symbole, für `quote --holdings` |
| `trader/config.json` | `market`, `flat_by` oder `zeiten`, wenn der Plan kein `flat_by` hat |

## Regeltypen

| Typ | klingelt, wenn | klingelt wieder |
| --- | --- | --- |
| `above` / `target` | Kurs auf oder über `price` | nach `reset`, oder von selbst mit `"rearm": true`, wenn der Kurs zurückgefallen ist |
| `below` / `stop` | Kurs auf oder unter `price` | genauso |
| `pct_move` | Bewegung um `pct` Prozent zum Vortagesschluss (oder `ref`), optional `direction` up oder down | höchstens einmal am Tag |
| `time` | die Uhr des Markts hat `at` ("17:25") an einem Handelstag überschritten | einmal je Handelstag |
| `opening_bell` | der Markt hat offen (XETRA ab 9:00 Uhr, NYSE ab 9:30 ET) | einmal je Handelstag |

Eine Regel mit `"date"` gilt nur an diesem Tag und nur mit einem Kurs von
diesem Tag; `--from-plan`-Regeln tragen das Datum des Plans, also klingelt der
Stop von gestern heute nicht. Ein `time`-Alarm mit `"before_close": true`
rückt an einem verkürzten Handelstag um denselben Abstand vor wie der Schluss,
wenn er sonst danach läge: XETRA 17:25 Uhr wird am Mi 30.12.2026
(Jahresschlussbörse, Schluss 14:00 Uhr) zu 13:55 Uhr, US 15:55 ET an einem
13:00-Schluss zu 12:55 ET. Hat /dt-ausstieg die Zeit schon vorgezogen, bleibt sie.

## Kurse

- `yahoo` (Standard): `query2.finance.yahoo.com/v8/finance/chart/<SYMBOL>`,
  für XETRA direkt `SAP.DE`. Inoffiziell und kostenlos, eine Anfrage je
  Symbol, eine halbe Sekunde Abstand. Bei 429 wartet es und versucht es noch
  einmal; bei 429 oder 5xx danach geht es zu `query1`.
- Yahoo-Kurse für XETRA sind etwa 15 Minuten verzögert: der Kurs, den ein
  `check` um 10:12 Uhr sieht, ist von etwa 9:56 Uhr. Darum ist ein Alarm nie
  ein Stop. Ein Kurs kann zwischen zwei Checks über eine Marke und zurück laufen.
- `stooq`: `stooq.com/q/l/?s=tsla.us&f=sd2t2ohlcv&h&e=csv`, nur für US-Werte
  (am 13.10.2026 kam 404, der Parser bleibt). Für XETRA wäre `sap.de`
  naheliegend, ist aber nicht geprüft; darum ist Stooq für `.DE`-Symbole nicht
  eingerichtet und sagt das.
- Ausgeführt wird zum Kurs deines Brokers. Jeder Kurs in `trader/prices.json`
  behält seine Kurszeit; /dt-risiko nimmt nur einen unter 15 Minuten.
- Fallen beide Quellen aus, nimm den Kurs aus dem Broker-Connector oder deiner
  Broker-App und trag ihn ein: `{"as_of": "...Z", "prices": {"SAP.DE": 211.20}}`.

## Die Börsenuhr

XETRA handelt 9:00 bis 17:30 Uhr deutscher Zeit; handelsfrei 2026: 1.1., 3.4.,
6.4., 1.5., 24.12., 25.12., 31.12.; 2027: 1.1., 26.3., 29.3., 24.12., 31.12.
Am 30.12.2026 nur bis 14:00 Uhr. Pfingstmontag, Fronleichnam und der 3. Oktober
werden gehandelt. Die NYSE handelt 9:30 bis 16:00 ET, mit ihren Feiertagen
und 13:00-Schlüssen. Sommer- und Winterzeit rechnet das Tool selbst, ohne
Zeitzonen-Dateien und ohne die Zeitzone des Rechners. Für andere Jahre sagt
es, dass die Feiertage unbekannt sind.

## Schritte

1. Direkt nachdem /dt-ausstieg den Plan geschrieben hat: `add --from-plan`.
   Bestätige die drei Alarme: Stop, Ziel und Glattstell-Zeit, mit Tag.
2. `check` laufen lassen, solange der Trade offen ist: alle paar Minuten per
   `/loop` (etwa `/loop 5m alerts.py check`) oder als geplante Aufgabe in
   Claude. Jeder Lauf holt nur die Symbole der heutigen Regeln und meldet
   jeden Alarm einmal. Das ist der letzte verzögerte Kurs, kein Live-Kurs.
3. Sag in je einer Zeile, was ausgelöst hat. Ein Stop- oder Ziel-Alarm heißt:
   Schau beim Broker nach, ob die Order ausgeführt ist, und trag die Ausführung
   mit /dt-broker ein. „Glattstellen vor Handelsschluss“ heißt: Schließ, was
   noch offen ist (/dt-broker `flatten`, dann /dt-risiko, dann dein „ja“).
   Handle nie für den Nutzer. Kein Alarm platziert eine Order.

## Beispiel XETRA: SAP.DE am Di 27.10.2026

Der Plan aus /dt-ausstieg (echte Yahoo-Kerzen): Einstieg 214,90 € um 10:55 Uhr,
Stop 213,22 € (Mitte der Opening Range), Ziel 216,58 € (1R), glatt bis 17:25
Uhr. `add --from-plan` legt `sap.de-plan-stop`, `sap.de-plan-target` und
`sap.de-flat-by` für diesen Tag an:

```
SAP.DE am Di 27.10.2026: Stop 213,22 €, Ziel 216,58 €, glatt bis 17:25 Uhr.
```

Mit `add --opening-bell` klingelt um 9:00 Uhr die Glocke, um 17:25 Uhr das Glattstellen:

```
XETRA: OFFEN, Di 27.10.2026 09:00 Uhr, regulärer Handel.
ALARM: Glocke: XETRA ist offen (Di 27.10.2026 09:00 Uhr).

XETRA: OFFEN, Di 27.10.2026 17:25 Uhr, regulärer Handel.
ALARM: Glattstellen vor Handelsschluss: es ist 17:25 Uhr, gestellt war 17:25 Uhr. Der Handel endet um 17:30 Uhr.
Falls SAP.DE noch offen ist, schließ die Position: dt-broker flatten --symbol SAP.DE baut das Verkaufsticket,
dann /dt-risiko und dein „ja“.
```

Ein Kursalarm auf dem echten Kurs vom Mi 28.10.2026 (Abruf 10:12 Uhr, Kurs
von 9:56 Uhr, Vortagesschluss 213,15 €): `add --symbol SAP.DE --stop 211,50`,
dann `check`:

```
ALARM: SAP.DE hat den Stop 211,50 € erreicht (zuletzt 211,20 € um 09:56 Uhr).
```

„Alarm wenn SAP 200 erreicht“ wäre `add --symbol SAP.DE --below 200`; bei
211,20 € meldet `check` „Nichts ausgelöst. 1 Regel(n) heute beobachtet,
SAP.DE 211,20 €.“

## Beispiel US: TSLA am Mo 19.10.2026

Einstieg 364,18 $ um 10:15 ET, Stop 358,32 $, Ziel 370,04 $, glatt bis 15:55
ET. Ein `check` um 10:53 ET liest den echten Kurs von 10:52 ET, 366,48 $,
zwischen Stop und Ziel:

```
US (NYSE/Nasdaq): OFFEN, Mo 19.10.2026 10:53 ET (16:53 Uhr), regulärer Handel.
Nichts ausgelöst. 3 Regel(n) heute beobachtet, TSLA 366,48 $.
```

Um 15:55 ET (21:55 Uhr deutscher Zeit):

```
ALARM: Glattstellen vor Handelsschluss: es ist 15:55 ET (21:55 Uhr), gestellt war 15:55 ET. Der Handel endet
um 16:00 ET. Falls TSLA noch offen ist, schließ die Position: dt-broker flatten --symbol TSLA baut das
Verkaufsticket, dann /dt-risiko und dein „ja“.
```

Es klingelt einmal. Am nächsten Morgen werden die drei Plan-Alarme nicht mehr
beobachtet; mit `add --opening-bell --market us` klingelt die Glocke um 9:30 ET.

## Regeln

- Ein Alarm ist eine Tatsache über einen Kurs oder die Uhr. Sag ihn als Tatsache.
- Gib einen Kurs nie als live aus. Kostenlose Kurse sind verzögert und inoffiziell.
- Bestätige jede neue Regel: Symbol, Typ, Marke, Tag.

## Was es nie tut

Es platziert, storniert oder ändert nie eine Order, ersetzt nie den Stop beim
Broker, gibt einen Kurs nie als live aus und sagt nie voraus, wohin ein Kurs läuft.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Ein Alarm ist eine Erinnerung, keine Order. Er kann zu spät kommen oder ausbleiben.
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
