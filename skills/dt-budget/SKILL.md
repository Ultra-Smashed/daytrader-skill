---
name: dt-budget
description: >-
  Budget-Manager. Rechnet jede Position auf dein Budget und deinen max.
  Verlust je Trade. Liest den Trade-Plan aus /dt-ausstieg (Einstieg, Stop,
  Ziel), findet die ganzen Aktien, die in vier Grenzen passen (max. Verlust je
  Trade inklusive Gebühren und Spread-Puffer, Positionslimit, max. Order, Cash
  nach deinem Puffer), sagt, welche Grenze entschieden hat, und schreibt EINE
  Bracket-Order (Einstieg, Stop-Loss, Take-Profit) nach trader/orders.json.
  Rechnet in deiner Kontowährung, auch bei US-Aktien in Dollar (Wechselkurs
  sichtbar). Ein Stop, der für deinen max. Verlust zu weit weg ist, ist eine
  klare Ablehnung, keine kleinere Order. Platziert nichts. Nutzen, wenn du
  sagst „wie viele Aktien“, „rechne die Positionsgröße“, „wie viel soll ich
  kaufen“, „ich habe 5.000 €“, „ich will nur 50 € pro Trade riskieren“, „setz
  meine Regeln“, „10 % in Cash halten“, „Gebühren einrechnen“, oder nach
  /dt-ausstieg. Auch: "position size", "how many shares", "size this trade".
argument-hint: "[Budget in Kontowährung]"
---

# dt-budget

Der Budget-Manager macht aus einem Plan („Kauf SAP.DE zu 212,95, Stop 211,70“)
eine genaue Order („Kauf 17 Aktien“), innerhalb von Regeln, die du einmal
festlegst. Der Stop entscheidet die Größe: je weiter weg der Stop, desto weniger
Aktien. Das Tool schreibt nur einen Vorschlag. /dt-risiko prüft ihn, /dt-broker
fragt dich ja oder nein. Die meisten Daytrader verlieren Geld (ESMA und BaFin
warnen davor). Eine Größe nach max. Verlust hält jeden Verlust klein; sie macht
keinen Trade zum Gewinner.

`${CLAUDE_SKILL_DIR}` ist unten der Ordner dieses Skills (wo diese SKILL.md liegt).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                        # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                # trader/orders.json schreiben
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit --write        # Limit-Order zum Einstieg laut Plan
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 212.90 --json  # Limit-Order zu 212,90
python3 "${CLAUDE_SKILL_DIR}/size.py" --fx 0.86              # EUR-Konto, US-Aktie: 0,86 € je 1 $
python3 "${CLAUDE_SKILL_DIR}/size.py" --weights SAP.DE=40,ALV.DE=60 --config split.json   # Gewichtungsmodus
```

`--now "2026-10-27 09:20"` legt die Uhr fest. Ohne Offset gilt die Ortszeit des
Marktes: deutsche Zeit für XETRA-Werte (`SAP.DE`), New Yorker Zeit für US-Werte
(`TSLA`). „Heute“ ist das Datum in dieser Ortszeit. Ein Plan für einen anderen
Tag wird abgelehnt: mach mit /dt-ausstieg einen neuen.

## Was es liest und schreibt

| Datei | was |
| --- | --- |
| `trader/config.json` | deine Regeln (Start: `config.example.json` in diesem Ordner) |
| `trader/plan.json` | der Trade: Einstieg, Stop, Ziel, Setup, Glattstell-Zeit, optional `market` und `currency` (/dt-ausstieg schreibt ihn) |
| `trader/prices.json` | optional: ein frischer Kurs über dem Einstieg heißt mehr Risiko (/dt-alarm schreibt ihn) |
| `trader/portfolio.json` | optional: sein Cash begrenzt die Größe (/dt-broker führt es) |
| `trader/orders.json` | die eine vorgeschlagene Bracket-Order, mit `--write` |

## Schritt 1: Regeln einmal festlegen

Gibt es `trader/config.json` noch nicht, kopier `config.example.json` nach
`trader/config.json` und frag nach jedem Wert in einfachen Worten:

- **budget**: wie viel Geld dafür da ist. Nur Geld, dessen Verlust du verkraften kannst.
- **account_currency**: die Währung deines Kontos (Standard EUR). Alle Beträge unten sind in dieser Währung.
- **cash_buffer_pct**: wie viel immer Cash bleibt (Standard 10).
- **max_loss_per_trade**: das Meiste, was ein Trade verlieren darf, wenn der Stop am Stop ausgeführt wird (50).
- **fee_per_order**: Gebühr je Order in Kontowährung (z. B. 1 € bei Trade Republic). Sie zählt zweimal, für Kauf und Verkauf.
- **spread_buffer_pct**: Puffer für Schlupf am Stop, in Prozent vom Einstieg (Beispiel-Config 0,05).
- **max_position_pct**, **max_order**, **min_order**: größte Position (75 % des Budgets), größte Order (4.000) und kleinste Order (50).
- **fx**: Wechselkurse, z. B. `{"USD": 0.86}` = 0,86 € je 1 $. Nur nötig für Aktien in fremder Währung.
- **broker**: `"manuell"` (du tippst selbst, z. B. Trade Republic oder Scalable), `"ibkr"` oder `"alpaca"` (nur US-Werte).
- Die Tageslimits, die /dt-risiko durchsetzt: **max_daily_loss** (150), **max_trades_per_day** (3),
  **min_reward_risk** (1,0), **require_stop** (true) und die Zeitfenster unter **zeiten**:
  XETRA 09:15 bis 17:00 Uhr, glatt bis 17:25 Uhr; US 09:45 bis 15:30 ET, glatt bis 15:55 ET.
- **blocked**: Ticker, die du nie handeln willst.
- Lass **paper** auf true, bis du es auf einem Paper-Konto hast arbeiten sehen.

Alte Configs mit `max_loss_per_trade_usd` und Co. gehen weiter; sie bedeuten ein Konto in USD.

## Schritt 2: die Größe rechnen

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py" --write
```

Nur ganze Aktien: eine Bracket-Order kennt keine Bruchstücke. Die Größe ist
die kleinste von vier Grenzen. Limits in Kontowährung, Preise in der Währung
der Aktie, `fx` = Kontowährung je 1 Einheit der Aktienwährung (1, wenn gleich):

| Grenze | Aktien |
| --- | --- |
| max. Verlust | (`max_loss_per_trade` - 2 × `fee_per_order`) / Risiko je Aktie; Risiko je Aktie = (Einstieg - Stop + Einstieg × `spread_buffer_pct`/100) × fx |
| Positionslimit | Budget × `max_position_pct` / (Einstieg × fx) |
| max. Order | `max_order` / (Einstieg × fx) |
| Cash | (Budget - Cash-Puffer - eine Gebühr) / (Einstieg × fx), nie mehr als das Cash in `trader/portfolio.json` |

Der Wechselkurs kommt aus `--fx`, sonst aus `"fx"` in der Config, sonst holt das
Tool EUR/USD bei Yahoo (`EURUSD=X`, nicht mit `--offline`) und nennt Kurs,
Quelle und Zeit. Ohne Kurs gibt es keine Order.

Der Einstieg, mit dem gerechnet wird: der Limit-Preis mit `--limit`. Bei einer
Market-Order der Einstieg laut Plan oder der Kurs in `trader/prices.json`, wenn
er frisch ist (unter 15 Minuten) und höher liegt. Ein Kurs, der seit dem Plan
gestiegen ist, heißt mehr Verlust am selben Stop, also weniger Aktien. Ein
niedrigerer Kurs macht das Risiko nie kleiner.

Es lehnt ab und schreibt keine Order, wenn: die Größe null Aktien ist, die
Gebühren den max. Verlust auffressen, die Order unter der Mindestorder liegt,
Chance/Risiko unter `min_reward_risk` liegt, der Stop nicht unter dem Einstieg
liegt, das Ziel nicht darüber (die Bewegung ist schon gelaufen), der Plan für
einen anderen Tag ist, der Ticker gesperrt ist, der Plan ein Leerverkauf ist
oder ein Wechselkurs fehlt. Sag den Grund in einem Satz.

## Schritt 3: dem Nutzer zeigen

Zeig die vier Grenzen, welche entschieden hat, die Aktien, den Betrag (bei
Fremdwährung in beiden Währungen), den Wechselkurs mit Quelle und den max.
Verlust am Stop mit der Rechnung (Kursrisiko, Spread-Puffer, Gebühren). Sag
deutlich: ein Stop ist eine Order, kein Versprechen; in einem schnellen Markt
kann er unter dem Stop ausgeführt werden. Viele Neobroker kennen keine
Bracket- oder OCO-Order: bei `"broker": "manuell"` oder `"ibkr"` bleibt die
Order gleich, /dt-broker macht daraus eine Klick-Anleitung. Dann weiter zu
`/dt-risiko`.

## Beispiel 1: das US-Beispiel aus dem Reel (USD-Konto)

TSLA am Montag, 19.10.2026. Opening-Range-Ausbruch: Einstieg 364,18 um 10:15 ET,
Stop 358,32 (Mitte der Opening Range), Ziel 370,04 (1R). Risiko 5,86 $ je Aktie.
Config des Originals: 5.000 $ Budget, 10 % Cash-Puffer, 50 $ max. Verlust,
keine Gebühren (Fixture `tests/fixtures/dt-budget/plan-tsla.json`).

| Grenze | Rechnung | Aktien |
| --- | --- | --- |
| max. Verlust | 50 $ / 5,86 $ | **8 (entscheidet)** |
| Positionslimit | 75 % von 5.000 $ = 3.750 $ / 364,18 $ | 10 |
| max. Order | 4.000 $ / 364,18 $ | 10 |
| Cash | 5.000 $ minus 500 $ = 4.500 $ / 364,18 $ | 12 |

8 Aktien = 2.913,44 $. Max. Verlust am Stop: 8 × 5,86 = 46,88 $. Geschrieben wird
die Bracket-Order buy 8 TSLA, Stop 358.32, Ziel 370.04:

```json
{"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
 "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32",
 "why": "Opening-Range-Ausbruch bei TSLA: 8 Aktien, begrenzt durch deinen max. Verlust je Trade von 50 $ (8 × 5,86 = 46,88 $ am Stop)",
 "plan": {"entry": 364.18, "stop": 358.32, "target": 370.04, "risk_per_share": 5.86, "max_loss": 46.88,
          "setup": "orb", "entry_time": "10:15 AM", "flat_by": "15:55", "market": "us", "currency": "USD",
          "account_currency": "USD", "fx": 1.0, "fees": 0.0, "spread_buffer_pct": 0.0,
          "max_loss_instrument": 46.88}}
```

`why` und `plan` sind Notizen für /dt-risiko, /dt-broker und /dt-alarm; zum
Broker gehen sie nie. Mit Stop 300,00 würde eine Aktie 64,18 $ riskieren, mehr
als 50 $: keine Order. Um 10:52 lag der echte Kurs bei 366,48; derselbe Plan
ergibt dann 6 Aktien bei 8,16 $ Risiko, und Chance/Risiko fällt auf 0,44:
abgelehnt, weil die erwartete Bewegung schon größtenteils gelaufen ist.

## Beispiel 2: derselbe Plan mit EUR-Konto und Gebühren (Rechenbeispiel)

Gleicher TSLA-Plan, aber mit der Beispiel-Config dieses Pakets: Konto in EUR,
5.000 € Budget, 50 € max. Verlust, 1 € Gebühr je Order, 0,05 % Spread-Puffer.
Der Wechselkurs **0,8600 € je 1 $ ist eine Annahme** für dieses Rechenbeispiel
(`--fx 0.86`), kein aufgezeichneter Kurs. Das Tool rechnet:

```
Risiko je Aktie 5,86 $ (Einstieg 364,18 minus Stop 358,32) plus Spread-Puffer 0,05 % vom Einstieg
(0,1821 $) = 6,0421 $ = 5,1962 € bei 0,8600 €/$.
Gebühren: 2 × 1,00 € (Kauf und Verkauf) = 2,00 €, zählen voll in den max. Verlust.

  max. Verlust    (50 € max. Verlust - 2 € Gebühren) / 5,1962 € Risiko je Aktie            9 Aktien  <- greift
  Positionslimit  75 % von 5.000 € = 3.750 € / 313,1948 €                                 11 Aktien
  max. Order      4.000 € / 313,1948 €                                                    12 Aktien

Größe: 9 Aktien TSLA = 3.277,62 $ (2.818,75 €) zu 364,18. Max. Verlust am Stop: 9 × 5,1962 € + 2 € Gebühren = 48,77 €.
```

Die Order bekommt `"fx": 0.86`, `"fees": 2.0`, `"max_loss": 48.77` (in Euro)
und `"max_loss_instrument": 52.74` (9 × 5,86 $). /dt-risiko rechnet damit, ohne
selbst einen Kurs zu holen.

## Beispiel 3: SAP.DE an XETRA (aus echten Kerzen)

SAP.DE am Dienstag, 27.10.2026, 5-Minuten-Kerzen von Yahoo (aufgezeichnet am
28.10.2026, Fixture `tests/fixtures/dt-budget/plan-sap.json`): Opening Range 9:00
bis 9:15 Uhr Hoch 214,75 €, Tief 211,70 €; die Kerze 9:15 schließt um 9:20 bei
212,95 €. Als Beispielplan: Einstieg 212,95, Stop am Range-Tief 211,70, Ziel 1R
214,20. Kein Signal, nur Zahlen zum Nachrechnen. Mit der Beispiel-Config:

| Grenze | Rechnung | Aktien |
| --- | --- | --- |
| max. Verlust | (50 € - 2 € Gebühren) / 1,3565 € (1,25 € + 0,05 % Spread-Puffer) | 35 |
| Positionslimit | 75 % von 5.000 € = 3.750 € / 212,95 € | **17 (entscheidet)** |
| max. Order | 4.000 € / 212,95 € | 18 |
| Cash | (4.500 € - 1 € Gebühr) / 212,95 € | 21 |

17 Aktien = 3.620,15 €. Max. Verlust am Stop: 17 × 1,3565 € + 2 € Gebühren = 25,06 €
(reiner Kursverlust 17 × 1,25 € = 21,25 €). Glatt bis 17:25 Uhr.

## Steuern in Deutschland (kurz, keine Steuerberatung)

- Gewinne aus Aktien unterliegen der Abgeltungsteuer: 25 % plus Solidaritätszuschlag und ggf.
  Kirchensteuer. Deutsche Broker führen sie meist direkt ab.
- Sparerpauschbetrag: 1.000 € im Jahr (2.000 € bei Zusammenveranlagung) bleiben steuerfrei,
  wenn du einen Freistellungsauftrag gestellt hast.
- Verluste aus Aktien landen im Aktienverlusttopf und sind nur mit Gewinnen aus Aktien
  verrechenbar, nicht mit Zinsen oder Dividenden.
- Eine Wash-Sale-Regel wie in den USA gibt es in Deutschland nicht.
- Sehr häufiges Traden kann steuerlich als gewerblicher Wertpapierhandel gewertet werden;
  /dt-risiko warnt ab `trade_frequency_warning` Einstiegen in 30 Tagen. Sprich mit einer Steuerberatung.

## Gewichtungsmodus (aus v1)

`--weights SAP.DE=40,ALV.DE=60` oder `--targets DATEI` (hier `targets.example.json`)
verteilt ein Budget nach Gewicht auf eine Liste: erst geht der Cash-Puffer weg,
die Gewichte werden auf 100 normiert, ein Wert über `max_position_pct` wird
gedeckelt und der Überschuss verteilt, Anteile unter der Mindestorder fallen
weg, Beträge werden auf ganze Einheiten gerundet. Mit `"max_position_pct": 25`,
`"fractional": true` und einem USD-Konto ergibt die Beispieldatei AAPL 1.250 $
(gedeckelt), AXP 1.119 $, GOOGL 823 $, KO 708 $, BAC 600 $. Mit
`"fractional": false` (die Beispiel-Config) kauft es ganze Aktien und braucht
Kurse (`--prices trader/prices.json`). Das sind einfache Käufe ohne Stop:
/dt-risiko sperrt sie, solange `require_stop` true ist. Nimm für eine
langfristige Aufteilung eine eigene Config (`--config`).

## Regeln

- Nur Vorschläge. Dieser Skill ruft nie ein Broker-Tool auf.
- Rechne nie mit Geld, von dem der Nutzer nicht gesagt hat, dass es dafür da ist. Frag nach Budget und max. Verlust.
- Jede Zahl kommt aus der Config, dem Plan, den Kursen oder dem genannten Wechselkurs. Nichts wird geraten.
- Keine Prognosen: sag nie, was ein Trade bringt. Ein Ziel ist ein Plan, keine Vorhersage.
- Kostenlose Yahoo-Kurse sind inoffiziell und können verzögert sein. Es gilt der Kurs deines Brokers.

## Was es nie tut

Es platziert, bestätigt oder plant nie eine Order, hebt nie selbst ein Limit an,
schiebt nie einen Stop näher, um mehr Aktien unterzubringen, und rechnet nie
Optionen, Margin oder Leerverkäufe.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Der maximale Verlust ist ein Plan, keine Obergrenze. Gebühren, Spreads, Wechselkurse und Steuern kommen dazu.
- Wenn Trading zwanghaft wird: BIÖG-Telefonberatung zur Glücksspielsucht, 0800 1 37 27 00, kostenlos und anonym.
- Sag das dem User, wenn er nach Gewinnchancen, „sicheren“ Trades oder Empfehlungen fragt, und verweise auf `RISIKOHINWEISE.md` im Repo.

## Sicherheit

- Bildung und Werkzeug, keine Anlageberatung (auch nicht im Sinne des WpHG). Eine FREIGABE
  ist eine Regelprüfung, keine Empfehlung. Die meisten Daytrader verlieren Geld; ESMA und
  BaFin warnen davor.
- Paper Trading ist Standard (`"paper": true`). Live zu gehen ist deine eigene Entscheidung,
  in deiner eigenen Config.
- Nichts in diesem Paket platziert eine Order außer dt-broker, und nur wenn alles drei gilt:
  dt-risiko hat genau diese Order heute freigegeben, du hast im Chat ausdrücklich „ja“ zu
  genau dieser einen Order geschrieben, und du hast auf Claudes eigener Karte „Allow once“
  geklickt, weil das Order-Tool auf „Needs approval“ steht (Customize > Connectors >
  Tool-Berechtigungen). Ein Order-Tool nie auf „Always allow“ stellen.
  Im Modus `"broker": "manuell"` tippst du die Order selbst in deiner Broker-App ein.
- Keine Optionen, kein Margin, keine Leerverkäufe, kein Hebel, außer die Config erlaubt es
  und du bestätigst es.
- Broker-Schlüssel liegen in Umgebungsvariablen oder in der Claude-Desktop-Config, nie im Chat.
