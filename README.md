<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/png/dark_logo.png">
  <img alt="Finanzcockpit" src="brand/png/logo.png" height="64">
</picture>

# Finanzcockpit für Home Assistant

Zeigt Kontostände als Sensoren in Home Assistant an und gruppiert sie über Labels in Töpfe (z.B. Steuern, Notgroschen, Altersvorsorge). Dazu kommen Summen nach Währung und Anlageklasse, eine Vorsorge-Simulation bis ins hohe Alter mit Szenarien und Reglern sowie ein Dashboard. Die Daten stammen aus einfachen Textdateien. Es gibt keine Bankanbindung und keine Cloud.

## Installation über HACS

1. HACS → ⋮ → **Benutzerdefinierte Repositories** → `https://github.com/joe-akeem/ha-finanzcockpit`, Typ **Integration**
2. **Finanzcockpit** installieren und Home Assistant neu starten
3. Die Dateien unter `/config/finanzcockpit/` anlegen (siehe unten)
4. Einstellungen → Geräte & Dienste → **Integration hinzufügen** → Finanzcockpit

## Dateien

Alle Dateien liegen unter `/config/finanzcockpit/`. Vorlagen findest du im Ordner [`examples/`](examples/).

### `konten.yaml`: Stammdaten

```yaml
konten:
  - id: lohnkonto          # a-z, 0-9, _  → sensor.finanzcockpit_lohnkonto
    name: Lohnkonto
    institut: Beispielbank # optional
    eigentuemer: Gemeinsam # optional, freier Text
    iban: CH93 0076 2011 6238 5295 7  # optional, Prüfziffer wird geprüft
    land: CH               # optional, Ländercode; ohne Angabe aus der IBAN
    waehrung: CHF          # CHF, EUR, USD oder BTC
    topf: Frei verfügbar   # → Label «Topf: Frei verfügbar»
    anlageklasse: liquiditaet
    rhythmus: monatlich    # optional, nur zur Information

  - id: saeule3a_er
    # …
    anlageklasse:          # gemischtes Konto: Aufteilung in Prozent, Summe 100
      aktien: 45
      obligationen: 30
      immobilien: 15
      liquiditaet: 10
```

`anlageklasse` ist Pflicht. Erlaubt sind `liquiditaet`, `obligationen`, `aktien`, `immobilien`, `rohstoffe` und `krypto`. Bei Fonds oder Vorsorgelösungen die Aufteilung aus dem Factsheet übernehmen.

Ist sowohl `iban` als auch `land` angegeben, müssen die Länder übereinstimmen. Den Ländercode `NO` (Norwegen) in Anführungszeichen setzen, sonst liest YAML ihn als «nein».

### `saldi.csv`: Kontostände

```
datum;konto_id;betrag
2026-10-31;lohnkonto;11850.40
2026-10-31;lohnkonto;11805.40
```

- Die Datei ist **nur zum Anhängen** gedacht: Jede Erfassung ist eine neue Zeile.
- Gibt es für ein Konto mehrere Zeilen am selben Tag, gilt die **letzte**. So korrigierst du einen Fehler.
- Beträge dürfen `'` als Tausendertrennzeichen enthalten und `,` oder `.` als Dezimalzeichen.
- Zeilen, die mit `#` beginnen, sind Kommentare.

### Wechselkurse: online und `kurse.csv` (optional)

Für Konten in EUR oder USD holt das Finanzcockpit alle 6 Stunden die Referenzkurse der Europäischen Zentralbank (über die freie [Frankfurter-API](https://frankfurter.dev)), für Bitcoin den Kurs von [CoinGecko](https://www.coingecko.com). Beide brauchen kein Konto und keinen Schlüssel. Bitcoin-Beträge in `saldi.csv` dürfen bis zu 8 Nachkommastellen haben. Abgefragt wird nur der Kurs der Währung gegen CHF. Der zuletzt geholte Kurs wird gespeichert und gilt weiter, wenn die Abfrage einmal nicht klappt.

`kurse.csv` ist nur noch nötig, wenn du eigene Kurse verwenden willst, zum Beispiel die Kursliste der ESTV per 31.12. `kurs` ist der Preis einer Einheit in CHF. Es gilt der neueste Kurs je Währung, egal woher. Am selben Tag hat die Datei Vorrang vor dem Online-Kurs. Woher ein Kurs stammt, zeigt das Attribut `kurs_quelle` der Währungs-Sensoren.

```
datum;waehrung;kurs
2026-10-31;EUR;0.9320
2026-10-31;USD;0.7980
```

### `simulation.yaml`: Vorsorge-Simulation (optional)

Rechnet Jahr für Jahr bis Sie 95 ist: Lohn und Pensum, Säule 3a, Pensionskasse mit Einkauf, Umwandlungssatz und Kapitalbezug, AHV mit Ehepaar-Plafond und Vorbezug, deutsche Rente und Policen, Hypothek mit Zinsphasen, Amortisation und Tragbarkeit, Steuern (lineares Modell, auf heute kalibriert), Lebenshaltung je Lebensphase und die Witwenphase. Die Rechnung entspricht dem Numbers-Modell «Vorsorgeplanung».

Eine vollständige Vorlage mit Kommentaren liegt in [`examples/simulation.yaml`](examples/simulation.yaml). Der Aufbau:

| Abschnitt | Inhalt |
|---|---|
| `personen` | Geburtsjahr und Lohn bei 100 % für er und sie, Planungsalter Er |
| `wirtschaft`, `anlagen` | Lohnwachstum, Teuerung, Sozialabzüge, Renditen, Liquiditätsreserve |
| `lebenshaltung` | Ausgaben pro Jahr heute, wenn die Kinder selbständig sind und im Ruhestand |
| `ahv`, `pk`, `saeule3a`, `deutschland` | Renten und Vorsorgeausweise |
| `immobilie`, `steuern`, `ausgaben` | Hypozins-Phasen, Tragbarkeit, Eigenmietwert, Steuersätze, Auto, Dach, Erbschaft, Unterhalt |
| `startwerte` | Woher die Startwerte kommen (siehe unten) |
| `szenarien` | Pensionierung, Pensum-Phasen, AHV-Alter, PK-Kapitalbezug und -Einkauf, Amortisation |

Prozentwerte stehen als Prozent in der Datei (`3.5` = 3.5 %). Unbekannte Einträge sind ein Fehler, damit Tippfehler auffallen.

**Startwerte** kommen aus den neuesten Saldi. Jeder Startwert nennt Konten, Töpfe oder einen festen Betrag (oder eine Kombination):

```yaml
startwerte:
  frei:
    toepfe: [Frei verfügbar, Notgroschen, Vermögensaufbau]
  zweckgebunden: 25000      # wird vom freien Vermögen abgezogen
  pk_er:
    konten: [pk_er]         # Saldo per 1.1. gilt als Stand Ende Vorjahr
  pk_sie:
    wert: 48000             # ohne Konto
    jahr: 2025
  hypothek:
    toepfe: [Hypothek]      # negative Saldi
```

Mögliche Startwerte: `frei`, `saeule3a_er`, `saeule3a_sie`, `pk_er`, `pk_sie`, `de_policen`, `de_fonds`, `liegenschaft`, `hypothek`, `darlehen`. Jedes Konto darf nur in einem Startwert vorkommen. Fremdwährungen werden zum neuesten Kurs umgerechnet. Das Startjahr ist das Jahr des neuesten Saldos (ohne PK), die Rechnung beginnt im Jahr danach.

### `strategie.md`: Strategie und Aufgaben (optional)

Freier Markdown-Text, z.B. eure Anlagestrategie und ein Fahrplan. Zeilen mit `- [ ]` (offen) oder `- [x]` (erledigt) sind Aufgaben. Sie erscheinen als To-do-Liste `todo.finanzcockpit_aufgaben` und lassen sich in Home Assistant abhaken, umbenennen, hinzufügen und löschen. Home Assistant schreibt diese Änderungen in die Datei zurück; der übrige Text bleibt unverändert.

```markdown
## Leitplanken

- Notgroschen: 30'000 CHF auf dem Sparkonto.

## Aufgaben

- [x] Sparkonto eröffnen
- [ ] 3a-Einzahlung bis 20. Dezember
```

Neue Aufgaben kommen nach der letzten Aufgabe, ohne Aufgaben in einen neuen Abschnitt «Aufgaben». Die Überschrift über einer Aufgabe erscheint als deren Beschreibung.

## Was die Integration anlegt

| Entität | Inhalt |
|---|---|
| `sensor.finanzcockpit_<id>` | Neuester Saldo in Originalwährung. Attribute: `topf`, `anlageklasse`, `wert_chf`, `institut`, `eigentuemer`, `land`, `iban`, `rhythmus`, `stand` (Datum) |
| `sensor.finanzcockpit_summe_total` | Vermögen total in CHF |
| `sensor.finanzcockpit_summe_waehrung_<chf\|eur\|usd\|btc>` | Summe je Währung in CHF. Attribute: `anteil` (%), `betrag` (Originalwährung), `kurs`, `kurs_stand`, `kurs_quelle` (`EZB`, `CoinGecko` oder `kurse.csv`) |
| `sensor.finanzcockpit_summe_anlageklasse_<klasse>` | Summe je Anlageklasse in CHF, gemischte Konten anteilig. Attribut: `anteil` (%) |
| Label `Topf: <topf>` | Wird automatisch erstellt und dem Sensor zugewiesen |

Mit `simulation.yaml` zusätzlich:

| Entität | Inhalt |
|---|---|
| `select.finanzcockpit_sim_szenario` | Gewähltes Szenario. Ein Wechsel setzt die Regler auf die Werte des Szenarios. |
| `number.finanzcockpit_sim_<parameter>` | Regler für Pensionierung, Pensum (letzte Phase und ab Jahr), AHV-Alter, PK-Kapitalbezug, PK-Einkauf und Amortisation. Sie übersteuern das gewählte Szenario, ohne die Datei zu ändern. Attribute: `angepasst`, `szenario_wert` |
| `button.finanzcockpit_sim_zuruecksetzen` | Setzt alle Regler auf die Werte des Szenarios zurück |
| `sensor.finanzcockpit_sim_<kennzahl>` | Kennzahlen des gewählten Szenarios mit den Regler-Werten: `vorsorgeluecke` (pro Monat), `frei_pension_er`, `frei_pension_sie`, `frei_ende`, `tiefster_stand`, `erstes_negatives_jahr`, `belehnung`, `tragbarkeit`, `nettovermoegen_ende`, `steuern_summe`. Beträge in heutigen CHF, sofern das Attribut `heutige_chf` nicht `false` ist |
| `sensor.finanzcockpit_sim_verlauf` | Name des Szenarios; Attribut `jahre` mit den Jahreswerten für Diagramme, dazu `warnungen` |
| `sensor.finanzcockpit_sim_vergleich` | Anzahl Szenarien; Attribut `szenarien` mit den Kennzahlen aller Szenarien, so wie sie in der Datei stehen |

Mit `strategie.md` zusätzlich `todo.finanzcockpit_aufgaben`: die Aufgaben als To-do-Liste, Zustand = Anzahl offener Aufgaben. Das Attribut `strategie` enthält den Text ohne die Aufgaben und wird nicht in der Verlaufsdatenbank gespeichert.

Szenario und Regler-Werte bleiben über einen Neustart erhalten. Die Attribute `jahre` und `szenarien` werden nicht in der Verlaufsdatenbank gespeichert.

Summen pro Topf lassen sich z.B. mit einem Template bilden:

```jinja
{{ label_entities('topf_steuern') | map('states') | map('float', 0) | sum }}
```

Konto-IDs dürfen deshalb nicht mit `summe_` oder `sim_` beginnen.

Die Dateien werden alle 15 Minuten neu eingelesen. Mit der Aktion **`finanzcockpit.reload`** geht es sofort, und neue Konten bekommen dabei ihre Sensoren.

Sind die Dateien fehlerhaft, meldet das Log alle Fehler mit Zeilennummer, und die Sensoren sind «nicht verfügbar», bis der Fehler behoben ist.

## Dashboard

Das Finanzcockpit bringt ein eigenes Dashboard und eine Kuchendiagramm-Karte mit. Zusätzliche Karten aus HACS sind nicht nötig.

- **Automatisch:** Beim Einrichten ist die Option «Dashboard in der Seitenleiste anzeigen» eingeschaltet. Ändern lässt sie sich unter Einstellungen → Geräte & Dienste → Finanzcockpit → ⚙. Dieses Dashboard ist schreibgeschützt und verschwindet, wenn die Option aus ist oder die Integration entfernt wird.
- **Eigenes Dashboard:** Einstellungen → Dashboards → Dashboard hinzufügen → «Neu beginnen», dann ✎ → ⋮ → Raw-Konfigurationseditor:

  ```yaml
  strategy:
    type: custom:finanzcockpit
  ```

  Mit ✎ → «Kontrolle übernehmen» wird daraus ein frei bearbeitbares Dashboard.

Beide zeigen das Total, Kuchendiagramme nach Währungen, Anlageklassen und Töpfen, Balken je Institut mit der Grenze der Einlagensicherung und eine Tabelle aller Konten. Neue Konten und Währungen erscheinen ohne Anpassung. Mit `strategie.md` kommt die Ansicht «Strategie» mit dem Text und den Aufgaben dazu. Mit `simulation.yaml` kommt die Ansicht «Vorsorge» dazu: Szenario-Auswahl und Regler, Kennzahlen mit Warnungen, Verlauf von Vermögen, Hypothek, Renten und Ausgaben sowie ein Vergleich aller Szenarien.

Nach der Installation oder einem Update die Seite im Browser einmal vollständig neu laden (Cmd+Shift+R bzw. Ctrl+Shift+R). Sonst meldet das Dashboard «Timeout waiting for strategy element», weil der Browser die Karte noch nicht geladen hat.

### Karte `finanzcockpit-donut-card`

Zeigt beliebige Sensoren als Donut mit Total, Legende und Anteilen. Ein Klick auf ein Segment öffnet den Sensor.

```yaml
type: custom:finanzcockpit-donut-card
title: Anlageklassen
entities:
  - entity: sensor.finanzcockpit_summe_anlageklasse_liquiditaet
    name: Liquidität       # optional
    color: "#3BA7E0"       # optional
  - sensor.finanzcockpit_summe_anlageklasse_aktien
```

Statt `entities` gruppiert `gruppieren` die Konten nach einem Attribut und zeigt den Saldo in CHF netto je Gruppe, z.B. `gruppieren: topf`. Gruppen mit negativem Saldo (z.B. ein Darlehen) fallen weg.

### Karte `finanzcockpit-balken-card`

Zeigt die Guthaben je Institut als Balken, aufgeteilt in Liquidität und übrige Anlagen. Schulden zählen nicht. Die gestrichelte rote Linie markiert die `grenze`, z.B. die Einlagensicherung von 100'000 CHF pro Bank. Übersteigt die Liquidität bei einem Institut die Grenze, wird der Betrag rot.

```yaml
type: custom:finanzcockpit-balken-card
title: Guthaben je Institut
gruppieren: institut       # optional, Standard: institut
grenze: 100000             # optional
```

### Karte `finanzcockpit-aufgaben-card`

Zeigt die Aufgaben aus `strategie.md` gruppiert nach Abschnitt, mit ganzem Text statt abgeschnittener Zeilen. Abhaken schreibt direkt in die Datei. Neue Aufgaben fügst du in der Datei oder unter «To-do lists» hinzu.

```yaml
type: custom:finanzcockpit-aufgaben-card
entity: todo.finanzcockpit_aufgaben
title: Aufgaben            # optional
```

### Karte `finanzcockpit-verlauf-card`

Zeigt die Jahreswerte der Simulation als Liniendiagramm mit Marken bei den Pensionierungen. Beim Überfahren erscheinen die Werte des Jahres.

```yaml
type: custom:finanzcockpit-verlauf-card
title: Vermögen
entity: sensor.finanzcockpit_sim_verlauf
reihen:                    # optional, Standard: frei_real und hypothek_real
  - frei_real              # freies Vermögen
  - nettovermoegen_real    # inkl. 3a, PK, Liegenschaft, abzüglich Schulden
  - schluessel: renten_real
    name: Renten           # optional
    color: "#2FB67C"       # optional
```

Weitere Reihen: `hypothek_real`, `ausgaben_real`. Alle Werte in heutigen CHF.

## Datenschutz

Echte Finanzdaten gehören **nie** in dieses Repository. Die `.gitignore` schliesst `konten.yaml`, `saldi.csv`, `plan.yaml`, `kurse.csv`, `simulation.yaml` und `strategie.md` ausserhalb von `examples/` aus. Verwende keine vollständigen IBANs als Konto-ID oder Name. Die IBAN im Feld `iban` erscheint als Attribut und landet damit auch in der Verlaufsdatenbank von Home Assistant. Wer das nicht möchte, lässt das Feld weg.

## Entwicklung

Voraussetzung: [uv](https://docs.astral.sh/uv/).

| Befehl | Zweck |
|---|---|
| `scripts/setup` | Legt `.venv` mit Python 3.13, Home Assistant, pytest und Ruff an |
| `scripts/develop` | Startet eine lokale HA-Instanz mit der Integration unter http://localhost:8123. Fehlende Datendateien werden aus den Beispielen nach `config/finanzcockpit/` kopiert, vorhandene bleiben unverändert. |
| `scripts/lint` | Formatiert den Code und behebt Ruff-Befunde |
| `scripts/brand` | Erzeugt die Logo-PNGs in `brand/png/` aus den SVG-Quellen in `brand/` |
| `uv run pytest` | Tests der Integration |
| `node --test 'tests/js/*.test.mjs'` | Tests der Karte und der Dashboard-Strategie |

Die Integration ist per Symlink in `config/custom_components/` eingebunden. Nach einer Code-Änderung genügt ein Neustart von `scripts/develop`. Ausser `config/configuration.yaml` wird nichts aus `config/` eingecheckt.

## Release

1. Auf GitHub ein Release mit einem Tag wie `v0.2.0` veröffentlichen.
2. Der Workflow `release.yml` setzt die Version im Manifest und hängt `finanzcockpit.zip` an das Release an.
3. HACS bietet die neue Version danach als Update an.

## Geplant

- Import der Historie aus `saldi.csv` in die Langzeitstatistik
- Summen pro Topf und Eigentümer, Kennzahlen
- Soll/Ist-Vergleich: Ist-Saldi gegen den Verlauf der Simulation, mit Abweichung und Ampel
- Aktion `finanzcockpit.saldo_erfassen`
