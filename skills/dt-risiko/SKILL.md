---
name: dt-risiko
description: >-
  Risiko-Manager. Prüft jeden Trade gegen deine Limits und stoppt alles, was
  drüber liegt, bevor es zum Broker kann. Für einen Daytrade: ein Stop ist
  Pflicht, der Verlust am Stop (mit Gebühren, Spread-Puffer und Wechselkurs)
  muss in deinen max. Verlust je Trade passen, Chance/Risiko muss dein Minimum
  erreichen, das Risiko des Tages muss in dein Tageslimit passen, nicht mehr
  Trades als erlaubt, und keine neuen Einstiege außerhalb deines Zeitfensters
  oder wenn die Börse zu ist (XETRA- und NYSE-Kalender, verkürzte Tage). Dazu
  die Grundregeln: Sperrliste, Ordergröße, Positionslimit, Cash-Puffer,
  Margin, Leerverkäufe, Optionen und Krypto, fehlerhafte Bracket-Orders,
  Doppelte, Tageslimit, Broker-Plausibilität (Alpaca kann kein XETRA). Raus
  geht immer. Zeigt FREIGABE oder SPERRE mit Grund und speichert das Ergebnis,
  damit /dt-broker nur freigegebene Orders zeigt. Nutzen, wenn du sagst „prüf
  meine Order“, „ist das sicher“, „Risikocheck“, „verstößt das gegen meine
  Regeln“, „darf ich den Trade nehmen“, „wie viel habe ich heute riskiert“,
  und immer vor /dt-broker. Auch: "risk check", "check my order".
argument-hint: "[Pfad zu orders.json]"
---

# dt-risiko

Der Risiko-Manager ist das Tor zwischen Vorschlag und Broker. Jede Order von
/dt-budget oder vom Glattstellen in /dt-broker geht hier durch. Eine SPERRE ist
für diese Order endgültig: sie geht nicht zu dir für ein „ja“ und nicht zum
Broker. Die meisten Daytrader verlieren Geld (ESMA und BaFin warnen davor).
Diese Limits halten jeden Verlust und jeden Tagesverlust klein. Sie machen
keinen Trade zum Gewinner.

`${CLAUDE_SKILL_DIR}` ist unten der Ordner dieses Skills (wo diese SKILL.md liegt).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                           # trader/-Dateien; schreibt trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write                # nur ansehen, nichts speichern
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-10-27 09:20"  # Uhr festlegen
```

`--now` ohne Offset gilt als Ortszeit des Marktes der ersten Order: deutsche Zeit
für XETRA-Werte (`SAP.DE`), New Yorker Zeit für US-Werte (`TSLA`). Mit `Z` am
Ende ist es UTC. „Heute“ ist das Datum in dieser Ortszeit.

## Was es liest und schreibt

| Datei | was |
| --- | --- |
| `trader/orders.json` | die vorgeschlagenen Orders (/dt-budget oder Glattstellen in /dt-broker) |
| `trader/config.json` | deine Limits (/dt-budget liefert `config.example.json`) |
| `trader/portfolio.json` | Cash und Bestand; fehlt die Datei, ein frisches Konto mit dem Budget |
| `trader/prices.json` | ein frischer Kurs hebt den Einstieg, ab dem das Risiko zählt; bewertet auch Bestände |
| `trader/state/broker.json` | was platziert wurde: Doppelte, Trades am Tag, Tagesverlust, Daytrades, Häufigkeit |
| `trader/state/risk.json` | das Ergebnis, mit einem Fingerprint jeder einzelnen Order |

Das Tool ruft nichts aus dem Netz ab. Den Wechselkurs für eine US-Aktie auf einem
EUR-Konto nimmt es aus dem Order-Plan (`plan.fx`, von /dt-budget), sonst aus
`"fx"` in der Config.

## Einstieg und Ausstieg

Ein **Einstieg** eröffnet oder vergrößert eine Position: ein Kauf, oder ein
Verkauf, der leer verkaufen würde. Ein **Ausstieg** verkleinert nur, was du
schon hältst. Raus muss immer gehen, also wird ein Ausstieg nur auf Format,
Wertpapier, Broker und Leerverkauf geprüft. Jede andere Regel (Tageslimits,
Zeitfenster, Verlust, Chance/Risiko, Sperrliste, Größe, Doppelte, Währung) wird
für einen Ausstieg zur Warnung, nie zur SPERRE.

## Die Prüfungen

Die Orders werden der Reihe nach geprüft, als wäre jede freigegebene Order
ausgeführt. So fällt ein Paket auf, das Order für Order passt, zusammen aber ein
Limit reißt. Beträge zählen in deiner Kontowährung.

| Prüfung | sperrt, wenn |
| --- | --- |
| Format | kein Symbol, side nicht buy oder sell, qty und notional beide oder keins, eine notional-Order, die nicht Market + day ist, eine Limit-Order ohne Limit; eine Bracket-Order ohne ganze Aktien, nicht `day` oder `gtc`, ohne Stop-Loss oder Take-Profit |
| Wertpapier | ein Optionssymbol bei `allow_options` false; Krypto oder etwas, das nicht wie eine Aktie aussieht (US-Ticker oder XETRA wie `SAP.DE`, `P911.DE`, `1COV.DE`, `HEN3.DE`) |
| Broker | `"broker": "alpaca"` mit einem XETRA-Wert: Alpaca handelt keine XETRA-Werte |
| Leerverkauf | du verkaufst mehr, als du hast (`allow_short` false) |
| Sperrliste | (Einstiege) der Ticker steht auf `blocked` |
| Währung | (Einstiege) Aktie in fremder Währung und kein Kurs in `plan.fx` oder `"fx"` |
| Größe | (Einstiege) unter `min_order` oder über `max_order` |
| Position | (Einstiege) die Aktie wäre über `max_position_pct` des Kontos |
| Cash | (Einstiege) der Kauf ginge in den Cash-Puffer oder bräuchte Margin |
| Stop | (Einstiege) kein Stop bei `require_stop` true (Bracket-`stop_loss_stop_price` oder Stop im Plan); ein Stop auf der falschen Seite |
| Verlust | (Einstiege) Aktien × (Einstieg - Stop) × fx plus Spread-Puffer und Gebühren aus dem Plan über `max_loss_per_trade` |
| Chance/Risiko | (Einstiege) (Ziel - Einstieg) / (Einstieg - Stop) unter `min_reward_risk` |
| Tagesverlust | (Einstiege) die max. Verluste der heutigen Einstiege plus dieser über `max_daily_loss` |
| Trades | (Einstiege) schon `max_trades_per_day` Einstiege heute |
| Zeitfenster | (Einstiege) vor `no_entries_before` oder nach `no_entries_after`, oder die Börse ist zu |
| PDT | (Einstiege, nur US-Werte bei US-Broker) schon 3 Daytrades in den letzten 5 Handelstagen |
| Doppelt | (Einstiege) gleiches Symbol und gleiche Seite zweimal im Paket oder heute schon platziert |
| Tageslimit | (Einstiege) schon `max_orders_per_day` Orders heute |

So rechnen die Zahlen:

- **Der Einstieg, ab dem gemessen wird**: bei einer Limit-Order ihr Limit. Bei
  einer Market-Order das HÖHERE aus Einstieg laut Plan und frischem Kurs aus
  `trader/prices.json` (unter 15 Minuten alt). Ein Plan von 10:15 kann das
  Risiko um 10:55 nicht kleinrechnen, wenn der Kurs gestiegen ist. Ein älterer
  Kurs wird nicht genutzt, und das steht dabei.
- **Max. Verlust**: Kursrisiko × fx, plus Spread-Puffer (`plan.spread_buffer_pct`)
  und Gebühren (`plan.fees`, Kauf und Verkauf). Steht im Plan ein `max_loss` in
  deiner Kontowährung und passt sein `max_loss_instrument` zu genau dieser Order,
  zählt der höhere Wert. Eine geänderte Stückzahl wird immer neu gerechnet.
- **Tagesverlust** zählt den vollen max. Verlust jedes heute platzierten
  Einstiegs, Gewinn oder Verlust, so wie /dt-broker ihn eingetragen hat. Drei
  volle Trades brauchen einen Tag mit 150 auf.
- **Das Zeitfenster** gilt in der Ortszeit des Marktes, im Tool gerechnet
  (Sommer- und Winterzeit eingeschlossen), nie mit der Zeitzone deines Rechners.
  Standard: XETRA 09:15 bis 17:00 Uhr, US 09:45 bis 15:30 ET; eigene Zeiten
  unter `"zeiten"` in der Config. Wochenenden und Börsenfeiertage sind zu
  (XETRA 2026: 1.1., 3.4., 6.4., 1.5., 24.12., 25.12., 31.12.). An einem
  verkürzten Tag rückt das Ende des Fensters um die gleiche Zeit vor: NYSE
  schließt dann um 13:00 ET (3 Stunden früher), XETRA am 30.12.2026 um 14:00 Uhr
  (3,5 Stunden früher, letzte Einstiege 13:30 Uhr). Setz beide `no_entries_*`
  auf null, um das Fenster abzuschalten.
- **PDT** (Pattern Day Trader) ist eine US-Regel der FINRA. Sie zählt nur bei
  US-Werten und einem US-Broker (`"broker": "alpaca"`, außer `"pdt_guard": false`)
  oder wenn du `"pdt_guard": true` setzt. Für deutsche Broker und XETRA-Trades
  gilt sie nicht; dann gibt es nur einen Hinweis. Ein Daytrade ist ein Symbol,
  das am selben Tag gekauft und verkauft wurde, plus jeder heute platzierte
  Einstieg.
- **Häufigkeit**: mehr Einstiege in 30 Tagen als `trade_frequency_warning`
  (Standard 40) geben eine Warnung, keine Sperre: Sehr häufiges Traden kann
  steuerlich als gewerblicher Wertpapierhandel gewertet werden; sprich mit einer
  Steuerberatung.

Warnungen sperren nicht, aber sag sie dem Nutzer: ein LIVE-Konto, eine Zahl als
Zahl statt als String, ein Stop, der nur im Plan steht und nicht beim Broker,
ein zu alter Kurs, ein verkürzter Handelstag, die Häufigkeit.

## Schritte

1. Kann sich der Kurs seit dem Plan bewegt haben, hol ihn erst frisch
   (/dt-alarm: `alerts.py quote SAP.DE --write`).
2. Führ `check.py` aus. Exit-Code 0 heißt: jede Order frei, 1 heißt: mindestens
   eine gesperrt.
3. Sag dem Nutzer das Ergebnis in einfachen Worten, Order für Order: max.
   Verlust am Stop, Chance/Risiko und wie viel der Tageslimits es verbraucht.
   Bei einer SPERRE nenn den Grund und den Ausweg (weniger Aktien, ein engerer
   Stop aus /dt-ausstieg, auf das Zeitfenster warten, den Trade auslassen).
   Ändere nie selbst ein Limit.
4. Ändert sich die Order irgendwie, prüf neu. /dt-broker ordnet jede Order über
   ihren Fingerprint dem Ergebnis zu: eine geänderte Order ist erst nach einer
   neuen Freigabe bereit, und eine Freigabe von gestern zählt heute nicht.

## Beispiel 1: das US-Beispiel aus dem Reel

Die TSLA-Bracket-Order aus /dt-budget (8 Aktien, Stop 358,32, Ziel 370,04) um
10:15 ET am Montag, 19.10.2026, auf einem frischen Paper-Konto mit 5.000 $ und
der Config des Originals (Fixture `tests/fixtures/dt-risiko/orders-tsla.json`):

```
FREIGABE #1 Kauf TSLA 8 Aktien, Einstieg
          Einstieg 364,18 (Einstieg laut Plan), Stop 358,32, Ziel 370,04: Risiko 5,86 $ je Aktie
          max. Verlust 46,88 $ (Limit 50 $), Chance/Risiko 1,00 (min. 1)
          heute vorher: 0 von 3 Trades, 0 $ von 150 $ Tagesverlust

1 freigegeben, 0 gesperrt, Stand Mo 19.10.2026 10:15 ET (16:15 Uhr). Cash nach den freigegebenen Orders: 2.086,56 $ (Paper-Konto).
```

Eine Aktie mehr, und sie ist gesperrt:

```
SPERRE   #1 Kauf TSLA 9 Aktien, Einstieg
          Einstieg 364,18 (Einstieg laut Plan), Stop 358,32, Ziel 370,04: Risiko 5,86 $ je Aktie
          max. Verlust 52,74 $ (Limit 50 $), Chance/Risiko 1,00 (min. 1)
          heute vorher: 0 von 3 Trades, 0 $ von 150 $ Tagesverlust
        - Verlust: 9 Aktien × 5,86 Risiko je Aktie = 52,74 $ am Stop, über deinem max. Verlust je Trade von 50 $
```

Dieselben 8 Aktien um 10:55 mit dem echten Kurs von 10:52 (366,48) in
`trader/prices.json` sind doppelt gesperrt: 8 × 8,16 = 65,28 $ am Stop und
Chance/Risiko 0,44. Um 9:40 ET sperrt das Zeitfenster (keine neuen Einstiege vor
9:45 ET). Der Verkauf um 15:55 ET, der die Position schließt, geht durch, obwohl
er nach 15:30 liegt: er ist ein Ausstieg.

## Beispiel 2: EUR-Konto mit Gebühren (Rechenbeispiel)

Derselbe TSLA-Plan, gerechnet von /dt-budget mit der Beispiel-Config (EUR-Konto,
1 € Gebühr je Order, 0,05 % Spread-Puffer) und dem **angenommenen** Kurs
0,8600 € je 1 $ (`--fx 0.86`, kein aufgezeichneter Kurs): 9 Aktien.

```
Hinweis: PDT: die US-Regel für Pattern Day Trader gilt nur bei US-Brokern, nicht bei deutschen Brokern ("broker": "manuell"); nicht geprüft.

FREIGABE #1 Kauf TSLA 9 Aktien, Einstieg
          Wechselkurs 0,8600 EUR je 1 USD (aus Plan)
          Einstieg 364,18 (Einstieg laut Plan), Stop 358,32, Ziel 370,04: Risiko 5,86 $ je Aktie
          max. Verlust 48,77 € (Limit 50 €), Chance/Risiko 1,00 (min. 1)
          heute vorher: 0 von 3 Trades, 0 € von 150 € Tagesverlust

1 freigegeben, 0 gesperrt, Stand Mo 19.10.2026 10:15 ET (16:15 Uhr). Cash nach den freigegebenen Orders: 2.181,25 € (Paper-Konto).
```

Fehlt `plan.fx` und steht kein `"fx"` in der Config, ist die Order gesperrt
(„Währung: TSLA notiert in USD, dein Konto ist in EUR ...“).

## Beispiel 3: SAP.DE an XETRA

Der SAP.DE-Beispielplan aus echten Kerzen vom 27.10.2026 (siehe /dt-budget):
17 Aktien, max. Verlust 25,06 € mit Gebühren. Um 9:20 Uhr frei, um 9:10 Uhr
gesperrt („Zeitfenster: keine neuen Einstiege vor 09:15 Uhr“). Am 30.12.2026
(Jahresschlussbörse bis 14:00 Uhr) um 13:45 Uhr:

```
WARNUNG: verkürzter Handel heute bis 14:00 Uhr (Jahresschlussbörse, letzter Handelstag des Jahres): keine neuen Einstiege nach 13:30 Uhr

SPERRE   #1 Kauf SAP.DE 17 Aktien, Einstieg
          Einstieg 212,95 (Einstieg laut Plan), Stop 211,70, Ziel 214,20: Risiko 1,25 € je Aktie
          max. Verlust 25,06 € (Limit 50 €), Chance/Risiko 1,00 (min. 1)
          heute vorher: 0 von 3 Trades, 0 € von 150 € Tagesverlust
        - Zeitfenster: keine neuen Einstiege nach 13:30 Uhr (es ist 13:45 Uhr)
```

Mit `"broker": "alpaca"` wäre dieselbe Order immer gesperrt: „Broker: Alpaca
handelt keine XETRA-Werte; nimm ibkr oder manuell“.

## Regeln

- Eine FREIGABE heißt nur: die Order darf dem Nutzer gezeigt werden. Sie ist kein „ja“.
- Jede Zahl kommt aus der Config, der Order, dem Depot, den Kursen oder dem Broker-Log.
- Kostenlose Yahoo-Kurse sind inoffiziell und können verzögert sein; es gilt der Kurs deines
  Brokers, und ein Stop kann in einem schnellen Markt schlechter ausgeführt werden.

## Was es nie tut

Es platziert nie eine Order, ändert nie eine Order, damit sie durchgeht, lockert
nie ein Limit, sperrt nie einen Verkauf, der dich nur rausbringt, und hält eine
FREIGABE nie für dein „ja“.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Eine FREIGABE prüft nur deine eigenen Regeln. Sie sagt nichts darüber, ob der Trade gut ist.
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
- Steuern: Gewinne unterliegen in Deutschland der Abgeltungsteuer (25 % plus Soli, ggf.
  Kirchensteuer); Aktienverluste sind nur mit Aktiengewinnen verrechenbar. Keine Steuerberatung.
