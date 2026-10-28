# Daytrader-Skill

11 Claude-Skills fürs Daytrading an XETRA (und auf Wunsch an US-Börsen): Charts scannen, Ad-hoc-Meldungen und Directors' Dealings verfolgen, Einstieg und Ausstieg planen, die Positionsgröße auf dein Budget rechnen und jeden Trade 10.000-mal durchspielen, bevor du einen Euro riskierst.

> **Wichtige Risikohinweise**
>
> - Daytrading ist hochspekulativ. Ein **Totalverlust** des eingesetzten Geldes ist möglich, und die große Mehrheit der Daytrader verliert auf Dauer Geld.
> - **Keine Anlageberatung**, keine Steuer- oder Rechtsberatung. Die Herausgeber haben keine BaFin-Erlaubnis. Eine FREIGABE prüft nur deine eigenen Regeln.
> - Claude und die Tools können sich irren. Die Kursdaten sind inoffiziell und bei XETRA etwa 15 Minuten verzögert. Ein Stop ist keine Garantie.
> - **Paper Trading** ist Standard. Live zu gehen ist allein deine Entscheidung.
> - Wenn Trading zwanghaft wird: BIÖG-Telefonberatung zur Glücksspielsucht, 0800 1 37 27 00, kostenlos und anonym.
>
> Lies vor der Nutzung die vollständigen [Risikohinweise](RISIKOHINWEISE.md).

Kostenlos, MIT-Lizenz, ohne Anmeldung, ohne API-Schlüssel. Die Tools sind reines Python und lesen frei zugängliche Daten: Yahoo-Finance-Charts, die Instrumentenliste der Deutschen Börse, ad-hoc-news.de, die BaFin-Datenbank der Eigengeschäfte von Führungskräften und für US-Werte SEC EDGAR.

Kein Trade geht raus, bevor du „ja“ sagst. Nichts in diesem Paket platziert eine Order von sich aus.

Gebaut für deutsche Nutzer: XETRA als Standardmarkt, Euro, deutsche Zeiten und Feiertage, Gebühren und Wechselkurse, Neobroker ohne API, Directors' Dealings der BaFin und deutsches Steuerrecht.

## Installation

Füg das in Claude ein:

```
https://github.com/Ultra-Smashed/daytrader-skill

installiere den Skill
```

Oder als Plugin in Claude Code:

```
/plugin marketplace add Ultra-Smashed/daytrader-skill
/plugin install daytrader-skill@daytrader-skill
```

Als Plugin heißen die Skills dann `/daytrader-skill:dt-scanner` und so weiter. Wenn du lieber kurz `/dt-scanner` tippst, kopier die Ordner:

```bash
git clone https://github.com/Ultra-Smashed/daytrader-skill.git
cp -r daytrader-skill/skills/dt-* ~/.claude/skills/
```

Nur für ein Projekt: dieselben Ordner nach `.claude/skills/` in deinem Repo kopieren. Ganz ohne Claude Code: Füg eine einzelne `SKILL.md` oben in einen Chat ein, dann arbeitet Claude nach dieser Methode, nur ohne die Python-Tools.

Die Tools brauchen Python 3.8 oder neuer, nichts muss per pip installiert werden. Leg deine Regeln in `trader/config.json` an, Vorlage ist `skills/dt-budget/config.example.json`. Für US-Werte mit SEC-Daten (News-Filings, Analyst) trägst du dort Namen und E-Mail ein: `"sec_user_agent": "Dein Name du@example.com"`.

## Die elf Skills

| Befehl | Aufgabe | Was er tut |
| --- | --- | --- |
| `/dt-scanner` | Chart-Scanner | Scannt DAX, MDAX, SDAX oder alle XETRA-Aktien auf Opening-Range-Ausbrüche, Flaggen und Ausbrüche über das 20-Tage-Hoch. |
| `/dt-news` | News-Monitor | Holt Schlagzeilen und Ad-hoc-Mitteilungen zu deinen Werten, ordnet sie über ISIN oder Namen zu und markiert, was den Kurs bewegt. |
| `/dt-einstieg` | Einstiegs-Timer | Beobachtet ein Setup Kerze für Kerze und sagt, wann es auslöst, mit ehrlicher Angabe, wie alt die Daten sind. |
| `/dt-ausstieg` | Ausstiegsplaner | Legt Stop, Ziel und „glatt bis“ fest, bevor du einsteigst. |
| `/dt-zeitmaschine` | Zeitmaschine | Spielt den Rest des Tages 10.000-mal aus den eigenen Kerzen der Aktie durch, dazu jede vergangene Sitzung, in der das Setup ausgelöst hat. |
| `/dt-budget` | Budget-Manager | Rechnet die Stückzahl aus Budget, max. Verlust, Gebühren, Spread-Puffer und Wechselkurs. |
| `/dt-risiko` | Risiko-Manager | Prüft jede Order gegen deine Limits: FREIGABE oder SPERRE, mit Begründung. |
| `/dt-broker` | Order-Ausführung | Zeigt das Ticket, holt dein „ja“ und führt dich Klick für Klick durch deine Broker-App. Alpaca und IBKR gehen auch. |
| `/dt-alarm` | Kursalarme | Meldet Stop, Ziel, Börsenglocke und Zeit zum Glattstellen. |
| `/dt-analyst` | Quartalszahlen | Fasst zusammen, was sich bei Umsatz, Margen und EPS geändert hat. |
| `/dt-insider` | Directors' Dealings | Liest die Pflichtmeldungen von Vorständen und Aufsichtsräten bei der BaFin (Art. 19 MAR). |

## Märkte

| | XETRA (Standard) | US |
| --- | --- | --- |
| Symbole | `SAP.DE`, `BMW.DE`, `1COV.DE` | `TSLA`, `AAPL` |
| Handelszeit | 9:00 bis 17:30 Uhr | 9:30 bis 16:00 ET (meist 15:30 bis 22:00 Uhr) |
| Opening Range | 9:00 bis 9:15 Uhr | 9:30 bis 9:45 ET |
| Einstiege bis, glatt bis | 17:00 Uhr, 17:25 Uhr | 15:30 ET, 15:55 ET |
| Währung | EUR | USD, umgerechnet in deine Kontowährung |
| Kursdaten | Yahoo, ca. 15 Minuten verzögert | Yahoo |

Der Markt folgt aus dem Symbol: Alles mit `.DE` ist XETRA, alles andere US. `"market"` in der Config legt den Standard fest, `--market` überschreibt ihn. Feiertage und verkürzte Tage sind für 2026 und 2027 hinterlegt, etwa der 30.12.2026 mit Handelsschluss um 14:00 Uhr.

## So arbeitest du damit

Alles landet in einem Ordner `trader/` in deinem Projekt, und jeder Skill liest, was der vorige geschrieben hat:

```
scanner -> news -> einstieg -> ausstieg -> zeitmaschine -> budget -> risiko -> broker   (ein Trade)
alarm: Stop, Ziel, glatt bis 17:25 Uhr                                                  (solange er offen ist)
news / analyst / insider                                                                (nach Zeitplan)
```

Ein Beispiel mit echten Daten: SAP an XETRA, Dienstag, 27.10.2026, mit der Beispiel-Config (5.000 € Budget, 50 € max. Verlust je Trade, 1 € Gebühr je Order, Paper).

1. **`/dt-scanner`** um 11:00 Uhr: Von 43 DAX-Charts waren 31 nutzbar (Yahoo hat bei 12 Lücken). 13 davon hatten über ihrem Opening-Range-Hoch geschlossen, als Letzter SAP.DE um 10:55 Uhr bei 214,90 €, Range 211,70 bis 214,75 €, 0,07 % drüber.
2. **`/dt-news SAP.DE`** zeigt die Schlagzeilen und prüft den Ad-hoc-Feed. Wie eine Ad-hoc-Meldung aussieht: „EQS-Adhoc: KAP AG passt Prognose für das Geschäftsjahr 2026 an“, 27.10.2026, über die ISIN DE0006208408 der KAP AG zugeordnet, Themen Ad-hoc und Prognose.
3. **`/dt-einstieg SAP.DE`** um 10:54 Uhr: WARTEN, der letzte Schluss lag mit 214,70 € noch 0,05 € unter dem Hoch. Dann AUSGELÖST: Die 10:50-Kerze schließt um 10:55 Uhr bei 214,90 €, als erste über der Range. Live siehst du das bei Yahoo erst etwa 15 Minuten später, das Tool sagt dir das jedes Mal.
4. **`/dt-ausstieg`** legt den Plan vor dem Einstieg fest: Stop in der Mitte der Range, 213,22 €, also 1,68 € Risiko je Aktie. Ziel 1R, 216,58 €. Glatt bis 17:25 Uhr, egal wie.
5. **`/dt-zeitmaschine`** spielt den Rest des Tages 10.000-mal durch (Seed 19, jeder kann es nachrechnen): Ziel zuerst 64,0 %, Stop zuerst 34,5 %, weder noch 1,5 %. Dieselbe Regel auf 57 echten Sitzungen davor: 48-mal ausgelöst, 23-mal Ziel, 20-mal Stop, 5-mal weder noch. Urteil: neigt zum Ziel. Am echten 27.10. traf die 14:00-Kerze trotzdem den Stop. Eine Simulation ist keine Vorhersage.
6. **`/dt-budget`** rechnet: 1,68 € Risiko plus 0,05 % Spread-Puffer = 1,7875 € je Aktie. Der max. Verlust würde 26 Aktien erlauben, das Positionslimit von 75 % (3.750 €) begrenzt auf **17 Aktien für 3.653,30 €**. Max. Verlust am Stop: 17 × 1,7875 € + 2 € Gebühren = **32,39 €**.
7. **`/dt-risiko`** prüft die Order um 10:56 Uhr: FREIGABE. Max. Verlust 32,39 € bei 50 € Limit, Chance/Risiko 1,00, 0 von 3 Trades und 0 € von 150 € Tagesverlust verbraucht.
8. **`/dt-broker`** zeigt das Ticket: „KAUF 17 Stück SAP.DE, Market, gültig heute, Stop-Loss 213,22 €, Take-Profit 216,58 €“. Du antwortest „ja“ für genau diese Order. Im Modus `"broker": "manuell"` bekommst du eine Klick-Anleitung für deine Broker-App, mit dem Hinweis, dass viele Neobroker keine OCO-Order kennen. Danach trägst du den Ausführungskurs ein.
9. **`/dt-alarm`** meldet sich am Stop, am Ziel und um 17:25 Uhr zum Glattstellen.

Nebenbei, nach Zeitplan:

- **`/dt-insider`** liest die Directors' Dealings der BaFin. Beispiel: KST Beteiligungs AG, Aufsichtsratsmitglied, Kauf zu 1,11 €, Volumen 6.660,00 €, gehandelt am 26.10., gemeldet am 27.10.2026, also einen Geschäftstag später. Meldungen nach mehr als drei Geschäftstagen markiert das Tool als VERSPÄTET, im Monatsexport waren das 12 von 133 Zeilen.
- **`/dt-analyst SAP.DE`** liest deine von Hand übertragenen Quartalszahlen. SAP Q3 2026: Umsatz 10,27 Mrd. € (+13,2 % zum Vorjahresquartal), Nettoergebnis 2,25 Mrd. € (+12,2 %), EPS verwässert 1,94 € (+13,5 %), operative Marge 28,5 %.

Der US-Weg funktioniert genauso. Das Beispiel aus dem Original: TSLA am 19.10.2026, Ausbruch um 10:15 ET (16:15 Uhr) bei 364,18 $, Stop 358,32 $, Ziel 370,04 $, 8 Aktien für 2.913,44 $ und 46,88 $ max. Verlust. Mit Euro-Konto und dem echten Kurs vom 28.10.2026 (1,1128 $ je €) sind das 42,13 €.

## Die Tools

Reines Python aus der Standardbibliothek. Die Daten-Tools fragen öffentliche Quellen höflich und sparsam ab.

```bash
python3 skills/dt-scanner/scan.py universe --nur-deutschland         # DAX, MDAX, SDAX, DEUTSCHLAND aus der Deutsche-Börse-Liste
python3 skills/dt-scanner/scan.py daily                              # Setups aus den Tageskerzen
python3 skills/dt-scanner/scan.py orb --now "2026-10-27 11:00"       # Opening-Range-Ausbrüche bis jetzt
python3 skills/dt-news/news.py --tickers SAP.DE --hours 12           # Schlagzeilen, Ad-hoc, Kursbewegung
python3 skills/dt-einstieg/entry.py check SAP.DE --setup orb         # WARTEN / AUSGELÖST / ABGELAUFEN
python3 skills/dt-einstieg/entry.py watch SAP.DE                     # Kerze für Kerze, bis es auslöst
python3 skills/dt-ausstieg/exit.py plan --stop or-mid --target 1R --write   # -> trader/plan.json
python3 skills/dt-zeitmaschine/timemachine.py run --write            # 10.000 Durchläufe plus Rückschau
python3 skills/dt-budget/size.py --write                             # -> trader/orders.json
python3 skills/dt-risiko/check.py                                    # FREIGABE / SPERRE je Order
python3 skills/dt-broker/ticket.py show                              # die Tickets, BEREIT oder nicht
python3 skills/dt-alarm/alerts.py add --from-plan                    # Stop, Ziel, glatt bis 17:25 Uhr
python3 skills/dt-alarm/alerts.py check                              # meldet, was erreicht ist, einmal
python3 skills/dt-analyst/facts.py SAP.DE                            # Quartale, Wachstum, Margen, EPS
python3 skills/dt-insider/insider.py index --woche --art kauf        # Directors' Dealings der letzten Woche
```

```bash
python3 -m unittest discover -s tests -v
```

Die Tests laufen offline auf Ausschnitten echter Daten: XETRA-Kerzen aller DAX-Werte vom 22. bis 28.10.2026, 60 Tage SAP-Kerzen, die Deutsche-Börse-Instrumentenliste, der Ad-hoc-Feed und BaFin-Exporte vom 28.10.2026, SAPs Quartalsmitteilungen sowie die US-Daten des Originals (TSLA am 19.10.2026, SEC-XBRL). Sie bilden die Zahlen im Beispiel oben nach (`tests/test_beispiel.py` spielt die SAP-Kette durch).

## Kleingedrucktes

Die vollständige Fassung steht in [RISIKOHINWEISE.md](RISIKOHINWEISE.md).

**Keine Anlageberatung.** Das ist Software, die öffentliche Daten liest und rechnet. Sie kennt deine Lage nicht und kann nicht in die Zukunft sehen. Die meisten Daytrader verlieren Geld, auch du kannst Geld verlieren. Entscheide selbst und hol dir bei Bedarf Rat von einer zugelassenen Fachperson.

**Kein Trade ohne dein „ja“.** Nur `/dt-broker` kann zu einer Order führen, und nur, wenn `/dt-risiko` genau diese Order heute freigegeben hat und du im Chat „ja“ zu genau dieser einen Order schreibst. Mit Alpaca oder IBKR steht das Order-Tool in Claude auf „Needs approval“ (Customize, Connectors, Tool-Berechtigungen), nie auf „Always allow“, damit Claudes Karte „Allow once / Deny“ ein zweites Mal fragt. Im Modus `"manuell"` tippst du die Order ohnehin selbst ein. Optionen, Margin, Leerverkäufe und Hebel sind gesperrt, bis du sie einschaltest.

**Paper zuerst.** `"paper": true` ist der Standard in `config.example.json`. Mit `"paper": false` zeigt `/dt-broker` vor jeder Order eine LIVE-Warnung. Broker-Schlüssel gehören in Umgebungsvariablen, nie in den Chat.

**Die Zeitmaschine ist eine Simulation.** Sie baut auf den letzten rund 60 Tagen 5-Minuten-Kerzen der Aktie auf. Die Zukunft kann Dinge tun, die diese 60 Tage nie getan haben: Quartalszahlen, eine Ad-hoc-Meldung, eine Volatilitätsunterbrechung.

**Ein Stop ist ein Plan, keine Garantie.** In einem schnellen Markt oder über eine Kurslücke kann ein Stop weit unter seinem Kurs ausgeführt werden. Der angezeigte max. Verlust gilt beim Stop-Kurs.

**Die Daten sind kostenlos und inoffiziell.** Der Chart-Endpunkt von Yahoo Finance ist keine offizielle Schnittstelle. XETRA-Kurse sind dort etwa 15 Minuten verzögert und haben Lücken. Prüf alles Wichtige in deiner Broker-App, bevor du handelst.

**Die PDT-Regel gilt nur bei US-Brokern.** Die Pattern-Day-Trader-Regel der FINRA betrifft US-Broker wie Alpaca, nicht deutsche Depots. FINRA hat die 25.000-$-Grenze zum 4. Juni 2026 abgeschafft (Regulatory Notice 26-10), Broker dürfen die Änderung bis 20. Oktober 2027 umsetzen. Gilt bei deinem US-Broker noch die alte Regel, setz `"pdt_guard": true`.

**Directors' Dealings sind öffentlich, kein Insiderwissen.** Führungskräfte börsennotierter Unternehmen müssen eigene Geschäfte innerhalb von drei Geschäftstagen melden (Art. 19 MAR). `/dt-insider` liest diese öffentlichen Meldungen.

**Steuern.** Keine Steuerberatung.

- Kursgewinne unterliegen der **Abgeltungsteuer** von 25 % plus Solidaritätszuschlag und gegebenenfalls Kirchensteuer.
- Der Sparerpauschbetrag liegt bei 1.000 € (2.000 € bei Zusammenveranlagung).
- Aktienverluste lassen sich nur mit Aktiengewinnen verrechnen (Aktienverlusttopf).
- Eine Wash-Sale-Regel wie in den USA gibt es in Deutschland nicht.
- Deutsche Broker führen die Steuer automatisch ab. Bei ausländischen Brokern wie IBKR oder Alpaca erklärst du alles selbst in der Anlage KAP.
- Sehr häufiges Handeln kann in Ausnahmefällen als gewerblich gelten.

## Dateien

```
RISIKOHINWEISE.md            die vollständigen Risikohinweise
skills/dt-scanner/           SKILL.md, scan.py
skills/dt-news/              SKILL.md, news.py
skills/dt-einstieg/          SKILL.md, entry.py
skills/dt-ausstieg/          SKILL.md, exit.py
skills/dt-zeitmaschine/      SKILL.md, timemachine.py
skills/dt-risiko/            SKILL.md, check.py
skills/dt-budget/            SKILL.md, size.py, config.example.json, targets.example.json
skills/dt-broker/            SKILL.md, ticket.py, claude_desktop_config.example.json
skills/dt-alarm/             SKILL.md, alerts.py, alerts.example.json
skills/dt-analyst/           SKILL.md, facts.py, metrics.example.json, quartale.example.json
skills/dt-insider/           SKILL.md, insider.py
skills/*/markt.py            gemeinsames Marktmodell (Zeitzonen, Kalender, Formate), in jedem Ordner gleich
tests/                       unittest-Suite und Offline-Fixtures
.claude-plugin/              plugin.json, marketplace.json
```

MIT-Lizenz, siehe [LICENSE](LICENSE). Von [Christopher Thanisch](https://thanisch.co).
