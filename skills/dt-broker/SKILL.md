---
name: dt-broker
description: >-
  Order-Ausführung. Bringt freigegebene Orders zu deinem Broker, Paper Trading
  als Standard, nie ohne dein „ja“. Zeigt jede Order als klares Ticket (eine
  Bracket-Order mit Stop-Loss, Take-Profit und dem max. Verlust am Stop), je
  nach Broker mit dem genauen JSON für Alpacas place_stock_order, dem Entwurf
  für Interactive Brokers oder einer nummerierten Klick-Anleitung für Trade
  Republic, Scalable Capital, comdirect, ING, flatex und andere Apps ohne API.
  Erfasst dein „ja“ Wort für Wort, baut das Verkaufs-Ticket, das einen Daytrade
  bis zum Handelsschluss glattstellt (XETRA 17:25 Uhr, US 15:55 ET), trägt
  Ausführungen ein und loggt den max. Verlust jedes Einstiegs für dt-risiko.
  Auslöser: „platzier die Order“, „kauf es“, „ausführen“, „schick es an meinen
  Broker“, „stell glatt“, „raus aus der Position“, „verbinde IBKR“, „Paper
  Trading einrichten“, „Trade Republic“, „wie gebe ich das in meiner App ein“,
  „place the order“, „buy it“, „flatten“, oder nach einer FREIGABE von /dt-risiko.
argument-hint: "[Ordernummer]"
---

# dt-broker

Die Order-Ausführung ist der einzige Skill in diesem Paket, der zu einer echten
Order führen kann. Deshalb ist er der strengste. Eine Order erreicht den Markt
nur nach drei getrennten Stufen, jedes Mal, für jede Order:

1. **dt-risiko hat genau diese Order heute freigegeben** (FREIGABE, erkannt am Fingerprint).
2. **Du hast im Chat ausdrücklich „ja“ zu genau dieser einen Order geschrieben.**
3. **Du hast auf Claudes eigener Karte „Allow once“ geklickt**, weil das Order-Tool
   auf „Needs approval“ steht. Im Modus `"broker": "manuell"` ist die dritte Stufe,
   dass du die Order selbst in deiner Broker-App eintippst und dort bestätigst.

Zweimal du, einmal die Regeln. Kein „ja“, keine Order. Eine Order pro Frage,
nie „ja zu allem“, nie aus einer geplanten oder Hintergrund-Aufgabe.

`${CLAUDE_SKILL_DIR}` ist unten der Ordner dieses Skills (wo diese SKILL.md liegt).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                      # jedes Ticket, bereit oder nicht
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "ja"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --filled-qty 8 --filled-price 364.20
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol TSLA --side sell --qty 8 --price 370.04
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol TSLA --qty 8
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` spricht nie mit einem Broker. Es zeigt Tickets, prüft, ob eine
Antwort ein echtes Ja für diese Order ist, baut das Glattstellungs-Ticket und
führt das Log in `trader/state/broker.json`. Der Markt folgt aus dem Symbol:
`SAP.DE` ist XETRA (deutsche Zeit, EUR), `TSLA` ist US (New Yorker Zeit, USD).
`--now "2026-10-19 10:15"` setzt die Uhr in der Ortszeit dieses Marktes.

## Was es liest und schreibt

| Datei | Inhalt |
| --- | --- |
| `trader/config.json` | `broker` („manuell“, „ibkr“, „alpaca“), `paper`, `account_currency`, `fx`, `zeiten` |
| `trader/orders.json` | die vorgeschlagenen Orders (dt-budget schreibt sie, `flatten` ersetzt sie) |
| `trader/state/risk.json` | die Urteile von dt-risiko; nur eine FREIGABE von heute ist BEREIT |
| `trader/state/broker.json` | jedes Ja, Nein, platziert, fehlgeschlagen und ausgeführt, mit dem max. Verlust jedes Einstiegs |
| `trader/portfolio.json` | Bargeld und Stücke, aktualisiert von `fill` und `result --filled-qty` |
| `trader/plan.json` | die Glattstell-Zeit (`flat_by`) für `flatten` |

In den JSON-Dateien bleiben Schlüssel und Werte wie gehabt (`"status": "approved"`,
`"placed"`, `"declined"`, ...). In der Anzeige stehen sie auf Deutsch: bestätigt,
platziert, abgelehnt, verweigert, fehlgeschlagen, ausgeführt.

**Geld und Währung.** Kurse stehen in der Währung des Wertpapiers. Der max. Verlust
kommt aus `plan.max_loss` (Kontowährung inklusive Gebühren, von dt-budget), sonst
aus Stückzahl mal Abstand zum Stop. Weicht deine Kontowährung ab und gibt es einen
Wechselkurs (`plan.fx` oder `"fx": {"USD": ...}` in der Config), steht der Betrag
zusätzlich in Kontowährung da, und so landet er im Log für den Tagesverlust.

## Wann ist eine Antwort ein Ja?

Die Regel ist bewusst eng: Die Antwort beginnt mit dem Wort „ja“ (oder „yes“).
Danach darf nichts stehen, das eine Frage, Bedingung, Einschränkung oder Mehrzahl
ausdrückt, und jede Zahl oder jedes Symbol darin muss zu genau dieser Order passen.

- Zählt: „ja“, „Ja“, „ja, platzieren“, „ja bitte“, „ja 8 TSLA“, „ja 358,32“, „yes“.
- Zählt nicht: „ok“, „klar“, „passt“, „mach“, „jo“, „vielleicht“, „ja?“, „ja zu allen“,
  „ja beide“, „ja aber nur 5“, „ja, wenn es unter 340 ist“, „ja, Stop 357“, „ja AAPL“
  bei einer TSLA-Order, „ja 9“ bei 8 Stück.
- Ein „nein“ (auch „nö“, „nee“, „no“) wird als abgelehnt erfasst. Nichts wird gesendet.

Ist die Antwort kein Ja, druckt `approve` „Nicht erfasst“ mit dem Grund. Dann fragst
du noch einmal, mit dem Ticket. Mach aus einer Antwort nie selbst ein Ja.

## Setup A: Interactive Brokers (Hauptweg für Live-Orders aus Deutschland)

Interactive Brokers veröffentlicht einen verifizierten Connector im Claude-Verzeichnis:
claude.ai/directory/interactive-brokers (Connector-URL `https://api.ibkr.com/v1/api/mcp`).
Damit gehen XETRA- und US-Aktien.

1. In Claude: Customize > Connectors > Browse connectors, „Interactive Brokers“ suchen
   und hinzufügen.
2. Die Anmeldung bei IBKR passiert dort im Anmeldefenster von IBKR, nie im Chat.
   Kein Passwort, kein Code, kein Schlüssel gehört in eine Nachricht.
3. Tool-Berechtigungen: Jedes Tool, das Orders entwirft, ändert oder storniert, auf
   **Needs approval**. Nie auf „Always allow“. Nur lesende Tools dürfen „Always allow“ haben.
4. In `trader/config.json`: `"broker": "ibkr"`. Dein Paper-Konto bei IBKR nutzt du,
   solange `"paper": true` gilt.

Laut Verzeichniseintrag entwirft Claude Order-Anweisungen, die in deinem IBKR-Konto
landen; du prüfst sie dort und gibst sie frei. Claude sendet nie direkt an den Markt.
Bei IBKR liegt die letzte Freigabe also zusätzlich in IBKR selbst.

## Setup B: Alpaca (kostenloser Paper-Testweg, nur US-Aktien)

Alpacas eigener Server ist github.com/alpacahq/alpaca-mcp-server (MIT). Er läuft auf
deinem Rechner in Claude Desktop, steht nicht im Connector-Verzeichnis und handelt im
**Paper**-Konto, solange nichts anderes eingestellt ist (geprüft am Quelltext am
20.10.2026, Version 2.4.0). Alpaca handelt nur US-Werte: Ein XETRA-Symbol wie `SAP.DE`
mit `"broker": "alpaca"` ist immer NICHT BEREIT. Für dich in Deutschland ist Alpaca hier
vor allem zum Testen mit einem Paper-Konto gedacht. Ob und zu welchen Bedingungen ein
Live-Konto für dich möglich ist, klärst du selbst bei Alpaca.

1. Alpaca-Konto anlegen und im Alpaca-Dashboard **Paper-Trading**-API-Schlüssel erzeugen.
   Paper-Schlüssel sind getrennt von Live-Schlüsseln.
2. `uv` installieren (liefert `uvx`), siehe docs.astral.sh/uv.
3. In Claude Desktop: Settings > Developer > Edit Config. Das öffnet
   `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`,
   Windows: `%APPDATA%\Claude\`). Diesen Block einfügen (steht auch in
   `claude_desktop_config.example.json`) und die eigenen Schlüssel nur in diese Datei tippen:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "DEIN_PAPER_API_KEY_NUR_HIER_EINTRAGEN_NIE_IM_CHAT",
        "ALPACA_SECRET_KEY": "DEIN_PAPER_SECRET_KEY_NUR_HIER_EINTRAGEN_NIE_IM_CHAT",
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,stock-data"
      }
    }
  }
}
```

   Der `env`-Block gibt die Schlüssel als Umgebungsvariablen an den Server.
   **Schlüssel gehören nie in den Chat.** Nie danach fragen, die Datei nie in das
   Gespräch zurücklesen. Fügt jemand trotzdem einen Schlüssel ein: Nachricht löschen
   lassen und im Alpaca-Dashboard neue Schlüssel erzeugen. `ALPACA_PAPER_TRADE` ist
   ohnehin `true`; hingeschrieben ist es sichtbar. `ALPACA_TOOLSETS` ist optional.
4. Claude Desktop neu starten.
5. **Tool-Berechtigungen setzen**: Customize > Connectors (in älteren Versionen
   Settings > Connectors), alpaca öffnen, je Tool Always allow, Needs approval oder Blocked:
   - `place_stock_order`: **Needs approval**. Nie Always allow.
   - alles, was etwas platziert, ändert, storniert oder schließt (`cancel_order_by_id`,
     `replace_order_by_id`, `close_position`, `update_account_config`): Needs approval.
   - `place_option_order`, `place_crypto_order`, `close_all_positions`, `cancel_all_orders`,
     `exercise_options_position`, `do_not_exercise_options_position`: **Blocked**.
   - lesende Tools (`get_account_info`, `get_all_positions`, `get_open_position`,
     `get_orders`, `get_clock`, `get_stock_snapshot`, `get_stock_latest_quote`): Always allow geht.
6. Prüfen: Claude nach den Alpaca-Kontodaten fragen (nur lesen) und im Dashboard
   bestätigen, dass es das Paper-Konto ist. `"broker": "alpaca"` in `trader/config.json`.

In Claude Code statt Claude Desktop bleibt das Order-Tool auf Nachfrage, in
`.claude/settings.json`: `"permissions": {"ask": ["mcp__alpaca__place_stock_order"]}`.
Ein Order-Tool nie in `allow`.

**Bracket-Orders bei Alpaca.** `place_stock_order` nimmt `take_profit_limit_price` und
`stop_loss_stop_price` (optional `stop_loss_limit_price`); dann setzt der Server
`order_class` selbst auf „bracket“. Nur ganze Stücke, `time_in_force` day oder gtc.
Nach dem Einstieg warten Stop-Loss und Take-Profit beim Broker als zwei Orders, die
sich gegenseitig aufheben. Als Tagesorders enden sie zum Handelsschluss: ein Grund
mehr, bis dahin glatt zu sein.

## Setup C: manuell (Standard, für Trade Republic, Scalable Capital, comdirect, ING, flatex, ...)

Die meisten deutschen Broker haben keine API für Claude. Mit `"broker": "manuell"`
(Standard in `config.example.json`) zeigt `ticket.py show` eine BEREITE Order als
nummerierte Klick-Anleitung: Wertpapier (Name, Symbol, ISIN wenn bekannt, Handelsplatz),
Kauf mit Stückzahl, Orderart, Gültigkeit, dann getrennt die Stop-Loss-Order und die
Take-Profit-Order. Die Stufen sind: (1) FREIGABE von dt-risiko, (2) dein „ja“ im Chat,
(3) du tippst die Order selbst in deiner App ein und bestätigst sie dort. Mit
`"paper": true` heißt das: nur im Demokonto oder auf Papier, die Anzeige sagt PAPIER.

Beispiel, erzeugt mit `ticket.py show` (TSLA-Order vom 19.10.2026 aus
`tests/fixtures/dt-risiko/orders-tsla.json`, Standard-Config mit Konto in EUR und
`"fx": {"USD": 0.8986}`, das ist 1 / 1,1128 aus dem EUR/USD-Kurs vom 28.10.2026):

```
ORDER 1 von 1, PAPIER (nur im Demokonto oder auf Papier), manuell in deiner Broker-App
  Markt US (NYSE/Nasdaq), Kurse in USD, glatt bis 15:55 ET (21:55 Uhr), Konto in EUR
  KAUF 8 Stück TSLA, Market, gültig heute
  Stop-Loss 358,32 $
  Take-Profit 370,04 $
  max. Verlust etwa 46,88 $ (42,13 € in Kontowährung), wenn der Stop bei 358,32 $ ausgeführt wird (...)
  BEREIT: dt-risiko FREIGABE, wartet auf dein „ja“
  So gibst du sie in deiner Broker-App ein (erst nach deinem „ja“ hier im Chat):
    1. Wertpapier suchen: TSLA. Handelsplatz: US-Aktien handeln deutsche Broker meist über Plätze
       wie Tradegate, LS Exchange oder gettex in EUR; Kurs und Spread weichen dort vom US-Kurs ab. ...
    2. Kaufen wählen, Stückzahl 8.
    3. Orderart: Market (billigst, ohne Limit).
    4. Gültigkeit: nur heute (Tagesorder, gültig bis Handelsschluss).
    5. In der Vorschau prüfen: etwa 8 × 364,18 $ = 2.913,44 $ (etwa 2.618,02 €) plus Gebühren.
    6. Order in der App prüfen und dort bestätigen. Das ist die dritte Stufe, sie liegt bei dir.
       Notier Ausführungskurs und Stückzahl.
    7. Erst wenn der Kauf ausgeführt ist: Stop-Loss-Order, Verkauf 8 Stück, Orderart Stop
       (Stop-Market), Stop-Kurs 358,32 $ (etwa 321,99 €), gültig heute.
    8. Take-Profit-Order: Verkauf 8 Stück, Orderart Limit, Limit 370,04 $ (etwa 332,52 €), gültig
       heute.
  Achtung: Viele Neobroker kennen keine Bracket- oder OCO-Orders (eine Order storniert die andere)
  und erlauben Stop und Limit oft nicht gleichzeitig auf dieselben Stücke. Dann setz nur den Stop
  beim Broker und lass das Ziel 370,04 $ (etwa 332,52 €) per /dt-alarm beobachten; wird es erreicht,
  verkaufst du von Hand. Liegen beide Orders und eine wird ausgeführt, storniere sofort die andere.
```

Bei einem XETRA-Wert steht in Schritt 1 „Handelsplatz XETRA.“ mit Name und ISIN, und
alle Beträge sind in Euro. Die Euro-Werte in Klammern sind Richtwerte: An Tradegate
oder LS Exchange gilt der dortige Euro-Kurs, nicht der umgerechnete US-Kurs.

Nach dem Eintippen: `ticket.py result --index 1 --status placed --filled-qty 8
--filled-price 364.20` (lehnt die App ab: `--status failed --note "Grund"`). Wird später
Stop oder Ziel ausgeführt: `ticket.py fill --symbol TSLA --side sell --qty 8 --price ...`.

## Ablauf: der Einstieg

1. `ticket.py show`. Nur BEREITE Tickets gehen an dich. Ein Ticket mit NICHT BEREIT
   oder GESPERRT geht zurück an `/dt-risiko`.
2. EIN Ticket zeigen und fragen: „Diese Order platzieren? Antworte ja oder nein.“
   Eine Order pro Frage. Nie „ja zu allem“ anbieten.
3. `ticket.py approve --index N --reply "<deine Antwort, Wort für Wort>"`. Druckt es
   „Nicht erfasst“, war die Antwort kein ausdrückliches Ja für diese Order. Noch einmal fragen.
4. Erst nach „Dein „ja“ für Order N ist erfasst“:
   - alpaca: `place_stock_order` mit genau dem JSON aus dem Ticket aufrufen; Claudes Karte
     zeigt Allow once oder Deny.
   - ibkr: die Order mit dem Connector entwerfen (Karte: Allow once), dann in IBKR freigeben.
   - manuell: du tippst die Order nach der Anleitung in deine App und bestätigst sie dort.
5. Ergebnis erfassen: `ticket.py result --index N --status placed --broker-id <ID>
   --filled-qty Q --filled-price P`, oder `--status denied`, oder `--status failed --note ...`.
   Eine fehlgeschlagene Order wird nie ohne neue Prüfung und neues Ja wiederholt.
   Das Log behält den max. Verlust des Einstiegs für den Tagesverlust von dt-risiko.

## Während der Trade offen ist, und glatt bis Handelsschluss

- `/dt-alarm` beobachtet Stop, Ziel und Glattstell-Zeit (`alerts.py add --from-plan`).
  Bei Alpaca und IBKR stoppen die Bracket-Orders selbst; im manuellen Modus oft nur der Stop.
- Wird Stop oder Ziel ausgeführt: `ticket.py fill --symbol TSLA --side sell --qty 8 --price 358.32`.
- Bis `flat_by` (XETRA 17:25 Uhr, US 15:55 ET; einstellbar unter `zeiten` in der Config)
  wird alles Offene geschlossen:
  1. Stückzahl prüfen: im Depot, bei Alpaca mit `get_open_position` (nur lesen).
  2. `ticket.py flatten --symbol TSLA --qty 8` schreibt einen Market-Verkauf nach
     `trader/orders.json`.
  3. `/dt-risiko`. Ein Verkauf, der nur schließt, was du hältst, wird nie von den
     Tageslimits oder dem Einstiegsfenster gesperrt.
  4. `ticket.py show`, dann dein „ja“ für genau diese eine Order, wie oben.
  5. Offene Stop- und Limit-Orders auf diese Stücke zuerst stornieren. Alpaca: `get_orders`
     (status open, nested true), dann `cancel_order_by_id` (Needs approval). Manuell druckt
     `flatten`: „Verkaufe 8 Stück TSLA bestens; storniere vorher offene Stop-/Limit-Orders
     auf diese Stücke.“ Dann platzieren und `result` erfassen.

## Beispiel: TSLA aus dem Reel (Alpaca, Paper)

Die TSLA-Order vom 19.10.2026 (`tests/fixtures/dt-risiko/orders-tsla.json`), Konto in USD,
`"broker": "alpaca"`, nach der FREIGABE von dt-risiko:

```
ORDER 1 von 1, PAPIER-Konto, Alpaca
  Markt US (NYSE/Nasdaq), Kurse in USD, glatt bis 15:55 ET (21:55 Uhr)
  KAUF 8 Stück TSLA, Market, gültig heute
  Stop-Loss 358,32 $
  Take-Profit 370,04 $
  max. Verlust etwa 46,88 $, wenn der Stop bei 358,32 $ ausgeführt wird (in einem schnellen Markt kann es schlechter werden)
  warum: Opening-Range-Ausbruch bei TSLA: 8 Aktien, begrenzt durch deinen max. Verlust je Trade von 50 $ (8 × 5,86 = 46,88 $ am Stop)
  BEREIT: dt-risiko FREIGABE, wartet auf dein „ja“
  Claude ruft place_stock_order mit genau diesem JSON auf:
    {"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
     "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32"}
```

Du antwortest „ja“. Claude erfasst es, ruft `place_stock_order` auf, und die Karte zeigt
„Claude wants to use Place stock order“ mit diesem JSON und zwei Knöpfen: Allow once, Deny.
Allow once schickt sie ans Paper-Konto. `why` und `plan` bleiben in der Datei; sie werden
nie gesendet. Auf „ja aber nur 5“ antwortet `approve`: „Nicht erfasst: die Antwort enthält
eine Bedingung oder einen Zweifel.“

## Was es nie tut

- Nie eine Order ohne alle drei Stufen, und nie zwei Orders auf ein Ja.
- Nie Orders aus einer geplanten oder Hintergrund-Aufgabe: Da ist niemand, der „ja“ sagt.
- Nie nach API-Schlüsseln, Passwörtern oder TANs fragen, sie lesen, speichern oder wiederholen.
- Nie `ALPACA_PAPER_TRADE` oder `"paper"` auf live stellen. Das machst du selbst.
- Nie `close_all_positions`, `cancel_all_orders`, Options- oder Krypto-Tools von sich aus.
- Nie einen Ausführungskurs versprechen: Market- und Stop-Orders werden zu dem Kurs
  ausgeführt, den der Markt gerade hergibt.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Mit "paper": false setzt jede Order echtes Geld ein. Prüf jedes Ticket selbst, bevor du „ja“ sagst.
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
