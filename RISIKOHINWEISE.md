# Risikohinweise

Lies diese Hinweise, bevor du einen der `/dt-*`-Skills nutzt. Sie gelten für das ganze Paket, für jeden einzelnen Skill und für jede Ausgabe, die Claude damit erzeugt.

## 1. Du kannst dein eingesetztes Geld verlieren

- Daytrading ist hochspekulativ. Ein **Totalverlust** des eingesetzten Kapitals ist möglich.
- Die große Mehrheit der Privatleute, die über längere Zeit Daytrading betreibt, verliert Geld. In der bisher vollständigsten Studie dazu (Chague, De Losso, Giovannetti: „Day Trading for a Living?“, 2019/2020, alle Daytrader im brasilianischen Mini-Ibovespa-Future von 2013 bis 2015) haben **97 %** derer, die länger als 300 Tage durchhielten, nach Kosten Geld verloren. Nur 1,1 % verdienten mehr als den brasilianischen Mindestlohn. Quelle: [SSRN 3423101](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101).
- Setze nur Geld ein, dessen Verlust du vollständig verkraften kannst. Nie Geld für Miete, Rücklagen, Altersvorsorge oder Geld auf Kredit.

## 2. Keine Anlageberatung, keine Steuer- oder Rechtsberatung

- Dieses Paket ist ein Lern- und Rechenwerkzeug. Es ist **keine Anlageberatung** und keine Anlageempfehlung im Sinne des Wertpapierhandelsgesetzes (WpHG) oder der Marktmissbrauchsverordnung (MAR), kein Signal- oder Börsenbriefdienst und keine Finanzportfolioverwaltung.
- Die Herausgeber haben **keine Erlaubnis der BaFin** für Anlageberatung, Anlagevermittlung oder Vermögensverwaltung und erbringen keine dieser Leistungen.
- Eine **FREIGABE** von `/dt-risiko` heißt nur: Die Order hält die Regeln ein, die du selbst in deiner Config festgelegt hast. Sie sagt nichts darüber, ob der Trade gut ist.
- Ein Treffer von `/dt-scanner`, ein Auslöser von `/dt-einstieg`, eine Meldung von `/dt-news` oder `/dt-insider` ist ein Hinweis auf einen Chart oder eine Nachricht, keine Kauf- oder Verkaufsempfehlung.
- Jede Entscheidung, jede Order und jede Konsequenz liegt allein bei dir.

## 3. Software, KI und Daten können falsch sein

- **Claude kann sich irren.** Ein Sprachmodell kann Zahlen falsch übertragen, Zusammenhänge falsch deuten oder Dinge erfinden. Die Python-Tools rechnen nach festen Regeln, können aber trotzdem Fehler enthalten.
- **Kursdaten sind inoffiziell und verzögert.** Die Kerzen und Kurse kommen von Yahoo Finance über eine nicht dokumentierte Schnittstelle. XETRA-Daten sind dort etwa **15 Minuten verzögert**, haben Lücken und können ohne Vorwarnung ausfallen oder sich ändern. Sie sind kein Echtzeitkurs.
- **Meldungen kommen mit Verzug.** Ad-hoc-Mitteilungen erreichen den Feed oft erst Minuten später. Directors' Dealings müssen erst bis zu drei Geschäftstage nach dem Geschäft gemeldet werden, manche kommen noch später.
- **Quartalszahlen** für deutsche Emittenten trägst du in `/dt-analyst` selbst von Hand ein. Übertragungsfehler sind deine.
- Prüfe deshalb vor jeder Order Kurs, Stückzahl, Stop und Ziel selbst in deiner Broker-App.

## 4. Ein Stop ist keine Garantie

- Ein Stop-Loss begrenzt den Verlust nur, wenn er zum gewünschten Kurs ausgeführt werden kann. Bei **Kurslücken** (zum Beispiel nach einer Ad-hoc-Mitteilung oder über Nacht), bei **Slippage** und bei einer **Volatilitätsunterbrechung** an XETRA kann der Verlust deutlich größer sein als der geplante maximale Verlust.
- Orders können **teilweise oder gar nicht** ausgeführt werden. Spreads sind kurz nach Eröffnung, kurz vor Schluss und außerhalb der XETRA-Zeiten (Tradegate, gettex, LS Exchange) oft breit.
- Viele Neobroker kennen keine Bracket- oder OCO-Order. Dann musst du Stop und Ziel selbst überwachen und die jeweils andere Order selbst streichen.
- Ein Alarm von `/dt-alarm` ist eine Erinnerung, keine Order. Er kann zu spät kommen oder ausbleiben.
- Technische Störungen bei dir, bei Claude, bei Yahoo oder bei deinem Broker können dazu führen, dass du eine Position nicht rechtzeitig schließen kannst.

## 5. Simulationen und Beispiele sind keine Prognosen

- `/dt-zeitmaschine` würfelt mögliche Kursverläufe aus vergangenen Kerzen. Das Ergebnis ist eine **Simulation**. Vergangene Kursverläufe sagen nichts Verlässliches über künftige.
- Alle Beispiele in diesem Repo (SAP.DE, TSLA und andere) zeigen, wie die Tools rechnen. Sie sind keine Aussage darüber, ob sich ein Trade gelohnt hat oder lohnen wird. Im SAP-Beispiel vom 27.10.2026 sagte die Simulation „neigt zum Ziel“, am echten Tag wurde der Stop getroffen.

## 6. Paper zuerst, live nur mit Absicht

- Standard ist `"paper": true`. Übe so lange mit Papiergeld oder im Demokonto, bis du die Tools und deine Regeln wirklich verstehst.
- Auf `"paper": false` umzustellen ist allein deine Entscheidung. Dann zeigt `/dt-broker` vor jeder Order eine deutliche LIVE-Warnung.
- Optionen, Margin, Leerverkäufe und Hebelprodukte sind standardmäßig gesperrt. Sie können Verluste über den Einsatz hinaus erzeugen.

## 7. Steuern

Das ist ein Überblick, **keine Steuerberatung**. Für deinen Fall fragst du eine Steuerberaterin oder einen Lohnsteuerhilfeverein.

- Gewinne aus Aktien unterliegen der **Abgeltungsteuer** von 25 % plus Solidaritätszuschlag und gegebenenfalls Kirchensteuer. Der Sparerpauschbetrag liegt bei 1.000 € (2.000 € bei Zusammenveranlagung).
- **Aktienverluste** lassen sich nur mit Aktiengewinnen verrechnen (Aktienverlusttopf), nicht mit Zinsen, Dividenden oder ETF-Gewinnen.
- Deutsche Broker behalten die Steuer automatisch ein. Bei **ausländischen Brokern** wie Interactive Brokers oder Alpaca passiert das nicht: Du musst alle Erträge und Verluste selbst in der **Anlage KAP** erklären und in Euro umrechnen.
- Bei Trades in US-Dollar zählen auch Wechselkursänderungen zum steuerlichen Ergebnis.
- Sehr häufiges, planmäßiges Handeln kann in Ausnahmefällen als gewerblich eingestuft werden, mit ganz anderen steuerlichen Folgen.
- Gebühren, Spreads und Steuern verringern jeden Gewinn. Viele kleine Trades kosten in Summe viel.

## 8. Dein Verhalten ist ein Risiko

- Daytrading kann süchtig machen. Typische Warnzeichen: Verluste schnell zurückholen wollen, Einsätze nach Verlusten erhöhen, eigene Regeln brechen, mehr Zeit und Geld einsetzen als geplant, Gereiztheit, wenn du nicht handeln kannst.
- Die Tagesgrenzen in deiner Config (`max_daily_loss`, `max_trades_per_day`) sind dafür da, dass du an schlechten Tagen aufhörst. Erhöhe sie nicht im Affekt.
- Wenn du merkst, dass Trading dein Leben bestimmt, hol dir Hilfe. Die **BIÖG-Telefonberatung zur Glücksspielsucht** ist kostenlos und anonym erreichbar unter **0800 1 37 27 00** (Montag bis Donnerstag 10 bis 22 Uhr, Freitag bis Sonntag 10 bis 18 Uhr). Mehr unter [check-dein-spiel.de](https://www.check-dein-spiel.de/).

## 9. Haftung

- Die Software wird unter der MIT-Lizenz **„wie besehen“ und ohne Gewähr** bereitgestellt. Es gibt keine Zusage, dass sie fehlerfrei, vollständig, aktuell oder für einen bestimmten Zweck geeignet ist.
- Die Haftung der Autoren für Verluste, entgangene Gewinne und sonstige Schäden aus der Nutzung ist ausgeschlossen, **soweit gesetzlich zulässig**. Unberührt bleibt die Haftung für Vorsatz und grobe Fahrlässigkeit sowie für Schäden an Leben, Körper und Gesundheit.
- Directors' Dealings sind öffentliche Pflichtmeldungen nach Art. 19 MAR, keine Insiderinformationen. Für die Einhaltung des Wertpapierrechts bei deinen eigenen Geschäften bist du selbst verantwortlich.

Mit der Nutzung der Skills bestätigst du, dass du diese Hinweise gelesen hast und die Risiken selbst trägst.
