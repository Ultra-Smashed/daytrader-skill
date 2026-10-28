---
name: dt-ausstieg
description: >-
  Ausstiegsplaner. Legt Stop und Kursziel fest, bevor du einsteigst, damit du
  weißt, wann du raus bist. Liest den Einstieg aus /dt-einstieg (oder einen
  Kurs, den du nennst), setzt den Stop standardmäßig auf die Mitte der Opening
  Range (oder auf ihr Tief, deinen Kurs, ein Prozent oder ein Vielfaches der
  ATR), rundet ihn auf den Cent ab und setzt das Ziel auf 2R (oder 1R, oder
  deinen Kurs). XETRA (SAP.DE, 9:00 bis 17:30 Uhr, glatt bis 17:25 Uhr) und US
  (TSLA, glatt bis 15:55 ET), verkürzte Handelstage eingerechnet. Lehnt einen
  Stop auf oder über dem Einstieg, ein Ziel darunter oder einen zu engen Stop
  ab und sagt, warum. Schreibt trader/plan.json für /dt-zeitmaschine,
  /dt-budget und /dt-alarm. Nur Longs. Nutze den Skill, wenn jemand sagt „wo
  setze ich den Stop“, „wann steige ich aus“, „Kursziel“, „Exit-Plan“,
  „Stop-Loss“, „wie viel riskiere ich“, „Stop und Ziel festlegen“, „was ist
  mein R“, „Chance-Risiko“, "where's my stop", "plan the exit", "stop loss",
  oder direkt nachdem /dt-einstieg ausgelöst hat, vor /dt-zeitmaschine.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X]"
---

# dt-ausstieg

Der Ausstiegsplaner entscheidet, wie ein Trade endet, bevor er anfängt. Der
Stop ist der Punkt, an dem das Setup gescheitert ist. Das Ziel ist der Punkt,
an dem du nimmst, wofür du gekommen bist. Beides steht VOR dem Einstieg fest,
schriftlich, und wird weitergereicht, damit niemand mitten in einer schnellen
Bewegung entscheiden muss. Ein Stop ist ein Plan, keine Garantie: eine
Kurslücke oder ein schneller Markt kann darüber hinaus ausführen. Die meisten
Daytrader verlieren Geld (ESMA und BaFin warnen davor), und ein sauberer Plan
ändert daran nichts.

`${CLAUDE_SKILL_DIR}` unten ist der Ordner dieses Skills (wo diese SKILL.md liegt).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                          # trader/entry.json: Stop Range-Mitte, Ziel 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 1R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5           # braucht die Kerzen der Sitzung (Yahoo oder --offline)
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol SAP.DE --entry 214,90 --or-high 214,75 --or-low 211,70
python3 "${CLAUDE_SKILL_DIR}/exit.py" show                          # der aktuelle trader/plan.json
```

Weitere Flags: `--flat-by 17:25`, `--json`, `--now "2026-10-27 10:56"`
(Ortszeit des Markts: deutsche Zeit für XETRA, New Yorker Zeit für US),
`--entry KURS` mit einer wartenden entry.json zum Vorausplanen, `--setup
level`, `--date`, `--time 10:55`, `--offline DATEI` (gespeichertes
Yahoo-Chart-JSON für einen ATR-Stop). Kurse dürfen mit Komma kommen (`214,90`).

Der Markt folgt aus dem Symbol: `SAP.DE` ist XETRA (EUR, Uhr), `TSLA` ist US
(USD, ET, mit deutscher Zeit in Klammern).

## Was es liest und schreibt

| Datei | was |
| --- | --- |
| `trader/entry.json` | der Auslöser aus /dt-einstieg: Symbol, Einstiegskurs, Zeit, Kerze, Opening Range |
| `trader/config.json` | `flat_by` oder `zeiten` (`{"xetra": {"flat_by": "17:25"}}`) und `min_reward_risk` (1,0: hier nur ein Hinweis, /dt-risiko setzt es durch) |
| Yahoo-Chart-API | nur für einen `atr:K`-Stop: die Kerzen der Sitzung bis zur Einstiegskerze, kostenlos und inoffiziell |
| `trader/plan.json` | mit `--write`: Einstieg, Stop und Regel, Ziel und R, Risiko je Aktie, Chance:Risiko, glatt bis, dazu `market` (`xetra`/`us`) und `currency` (`EUR`/`USD`). /dt-zeitmaschine, /dt-budget und /dt-alarm lesen ihn |

Die JSON-Schlüssel bleiben englisch (`stop`, `target`, `flat_by`, ...), die
Texte darin (`stop_label`, `target_label`) sind deutsch. `date` ist der
Handelstag in Ortszeit des Markts. `entry_time` steht für XETRA als `10:55`,
für US wie im Original als `10:15 AM`.

## Stops und Ziele

| Stop | wo er liegt |
| --- | --- |
| `or-mid` | Mitte der Opening Range (Standard bei einem Opening-Range-Ausbruch) |
| `or-low` | Tief der Opening Range: weiter weg, also weniger Stück beim gleichen Maximalverlust |
| `price:X` | dein Kurs |
| `pct:X` | X Prozent unter dem Einstieg |
| `atr:K` | K mal die ATR über 14 Kerzen unter dem Einstieg, auf den Kerzen der Sitzung bis zur Einstiegskerze. Gibt es bis dahin weniger als 14, mittelt es alle und sagt das |

Ein Level-Setup hat keine Opening Range als Stütze, es braucht einen Stop, den du nennst.

- **Runden.** Der Stop wird WEG vom Einstieg auf den Cent gerundet (bei einem
  Long also ab). Risiko = Einstieg minus Stop. Ziel = Einstieg + R x Risiko,
  kaufmännisch auf den Cent. Standard `2R`; `1R`, `1.5R` oder `price:X` gehen auch.
- **Abgelehnt, mit Grund.** Ein Stop auf oder über dem Einstieg. Ein Ziel auf
  oder unter ihm. Ein Risiko unter 0,05 % vom Kurs: zu eng, um den Spread zu
  überstehen, normales Zappeln würde dich ausstoppen. Eine entry.json, die
  nicht ausgelöst hat (außer mit `--entry`). Ein Short: v2 plant nur Longs.
- **Glatt bis.** XETRA 17:25 Uhr, US 15:55 ET (oder `flat_by`/`zeiten` in der
  Config). Raus bis dahin, egal wie es steht, nichts über Nacht. An einem
  verkürzten Handelstag rückt es um denselben Abstand vor wie der Schluss:
  XETRA am Mi 30.12.2026 (Jahresschlussbörse, Schluss 14:00 Uhr) auf 13:55 Uhr,
  US an einem 13:00-Schluss auf 12:55 ET. Ein Einstieg zu oder nach dieser Zeit
  wird abgelehnt; an einem Feiertag gibt es einen Hinweis.

## Neobroker: Stop beim Broker, Ziel per Alarm

Viele Neobroker kennen keine Bracket- oder OCO-Order (Stop und Ziel als
Paar, das sich gegenseitig storniert). Dann gilt: Nach dem Kauf legst du den
Stop als Stop-Order beim Broker an, denn nur der Broker kann dich wirklich
ausstoppen. Das Ziel lässt du per `/dt-alarm` beobachten und verkaufst selbst,
wenn es klingelt. Ein Alarm ist kein Stop. Der Plan sagt das bei jeder Ausgabe
(`broker_note` in trader/plan.json).

## Schritte

1. Direkt nachdem `/dt-einstieg` ausgelöst hat ausführen. Vorher plant
   `--entry KURS` an der erwarteten Marke voraus.
2. Bei einem Opening-Range-Ausbruch den Standard-Stop nehmen, außer der Nutzer
   nennt einen anderen. Ein Level-Setup braucht einen: frag nach.
3. `exit.py plan --write` ausführen. Lies Einstieg, Stop und Regel, Ziel und
   Regel, Risiko je Aktie, Chance:Risiko und „glatt bis“ vor.
4. Lehnt es ab, nenne den Grund und den Ausweg (ein weiterer Stop, ein
   ferneres Ziel). Lockere nie etwas von dir aus.
5. Sag einmal, dass der Stop ein Plan ist, keine Garantie, und dass er beim
   Broker liegen muss.
6. Weiter mit `/dt-zeitmaschine`, die den Plan durchspielt, dann `/dt-budget`,
   das die Stückzahl zum Maximalverlust je Trade rechnet. Biete `/dt-alarm` für
   Stop, Ziel und „glatt bis“ an. Claude kann `entry.py watch` im Hintergrund
   oder per `/loop` laufen lassen, bis ein Setup auslöst, und dann hierher kommen.

## Beispiel XETRA: SAP.DE am Di 27.10.2026

Echte 5-Minuten-Kerzen von Yahoo (aufgezeichnet am 28.10.2026). Die Opening
Range aus den Kerzen 9:00, 9:05 und 9:10 Uhr reicht von 211,70 € bis 214,75 €.
Die erste Kerze, die darüber schließt, ist die 10:50-Uhr-Kerze (Kerze 22):
Schluss 214,90 € um 10:55 Uhr. `exit.py plan --stop or-mid --target 1R --write`:

```
Ausstiegsplan: SAP.DE long, Di 27.10.2026, XETRA, Opening-Range-Ausbruch auf 5-Minuten-Kerzen
  Einstieg         214,90 € um 10:55 Uhr, Kerze 22
  Stop             213,22 €  Mitte der Opening Range: (214,75 € + 211,70 €) / 2 = 213,225 €, abgerundet
  Ziel             216,58 €  1R über dem Einstieg
  Risiko je Aktie  1,68 € (0,78 % vom Einstieg)
  Chance:Risiko    1,0
  Glatt bis        17:25 Uhr, egal wie es steht: nichts über Nacht halten
```

Das Standardziel 2R wäre 214,90 + 2 x 1,68 = 218,26 €. Mit `--stop or-low`
liegt der Stop bei 211,70 €, das Risiko bei 3,20 € je Aktie. Mit `--stop
atr:1.5` (ATR 0,4143 € über die letzten 14 Kerzen bis 10:55 Uhr) liegt er bei
214,27 €. Derselbe Plan am Mi 30.12.2026 hätte „Glatt bis 13:55 Uhr:
vorgezogen wegen des verkürzten Handelstags (Schluss 14:00 Uhr, ...)“.

## Beispiel US: TSLA am Mo 19.10.2026

Einstieg 364,18 $ um 10:15 ET (die 10:10-Kerze, Kerze 8), Opening Range
354,47 $ bis 362,18 $. `exit.py plan --stop or-mid --target 1R --write`:

```
Ausstiegsplan: TSLA long, Mo 19.10.2026, US (NYSE/Nasdaq), Opening-Range-Ausbruch auf 5-Minuten-Kerzen
  Einstieg         364,18 $ um 10:15 ET (16:15 Uhr), Kerze 8
  Stop             358,32 $  Mitte der Opening Range: (362,18 $ + 354,47 $) / 2 = 358,325 $, abgerundet
  Ziel             370,04 $  1R über dem Einstieg
  Risiko je Aktie  5,86 $ (1,61 % vom Einstieg)
  Chance:Risiko    1,0
  Glatt bis        15:55 ET (21:55 Uhr), egal wie es steht: nichts über Nacht halten
```

Das Standardziel 2R wäre 364,18 + 2 x 5,86 = 375,90 $. /dt-budget rechnet
dann die Stückzahl: bei 50 $ Maximalverlust je Trade floor(50 / 5,86) = 8 Aktien.

## Regeln

- Stop und Ziel stehen vor dem Einstieg fest, nie danach.
- Einen Stop nie weiter vom Einstieg wegschieben, wenn der Trade läuft.
- Nur nackte Zahlen: Einstieg, Stop, Ziel, Risiko je Aktie, Chance:Risiko. Es
  zeigt nie ein Ergebnis in Geld oder eine Rendite.
- Nichts hier verspricht Treffer oder Geld. Ein 1R-Ziel ist keine Vorhersage,
  dass der Kurs dort ankommt.
- Nur Longs. v2 plant nur Longs.
- Steuern (Abgeltungsteuer, Verlusttopf) und Kosten rechnet dieses Tool nicht;
  das ist keine Steuerberatung.

## Was es nie tut

Es platziert nie eine Order, rechnet keine Stückzahl, weitet nie einen Stop,
damit ein Plan durchgeht, und nennt einen Stop nie eine Garantie.

## Risikohinweise

- Daytrading ist hochspekulativ, ein Totalverlust des eingesetzten Geldes ist möglich. Die große Mehrheit der Daytrader verliert auf Dauer Geld.
- Keine Anlageberatung, keine Steuer- oder Rechtsberatung. Jede Entscheidung und jede Order triffst du selbst.
- Claude und die Tools können sich irren. Kursdaten von Yahoo sind inoffiziell und können verzögert, lückenhaft oder falsch sein.
- Ein Stop ist keine Garantie: Bei Kurslücken, Slippage oder einer Volatilitätsunterbrechung kann der Verlust größer sein als geplant.
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
