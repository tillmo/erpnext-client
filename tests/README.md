# Tests für den ERPNext-Client

Die Tests liegen in drei Verzeichnissen, die zugleich pytest-Marker sind:

| Verzeichnis            | Marker         | Voraussetzung                                                    |
|------------------------|----------------|------------------------------------------------------------------|
| `tests/offline/`       | `offline`      | nichts – ERPNext wird durch einen In-Memory-Fake ersetzt         |
| `tests/online_read/`   | `online_read`  | ERPNext-Instanz mit **lesendem** API-Zugriff                     |
| `tests/online_write/`  | `online_write` | ERPNext-**Test**instanz mit **schreibendem** Zugriff             |

Ausführen (aus dem Repo-Wurzelverzeichnis, mit aktivierter Python-Umgebung des Clients,
z. B. `source ~/programs/python/env3.14/bin/activate`; `pytest` steht in `requirements-linux.txt`):

```bash
python3 -m pytest tests/offline
```

```bash
ERPNEXT_TEST_SERVER=https://erpnext-test.example ERPNEXT_TEST_KEY=... ERPNEXT_TEST_SECRET=... \
python3 -m pytest tests/online_read
```

```bash
ERPNEXT_TEST_SERVER=https://erpnext-test.example ERPNEXT_TEST_KEY=... ERPNEXT_TEST_SECRET=... \
ERPNEXT_TEST_WRITE=1 python3 -m pytest tests/online_write
```

Ohne die Umgebungsvariablen werden die Online-Tests übersprungen, nicht ausgeführt.

## Umgebungsvariablen

| Variable                        | Bedeutung                                                                          |
|---------------------------------|------------------------------------------------------------------------------------|
| `ERPNEXT_TEST_SERVER`           | URL der Instanz, z. B. `https://erpnext-test.example`                              |
| `ERPNEXT_TEST_KEY` / `_SECRET`  | API-Schlüssel/-Geheimnis (ERPNext: Einstellungen → My Settings → API-Zugriff)      |
| `ERPNEXT_TEST_COMPANY`          | Firma, mit der getestet wird (Standard: erste Firma der Instanz)                   |
| `ERPNEXT_TEST_WRITE=1`          | Schreibtests freischalten                                                          |
| `ERPNEXT_TEST_ALLOW_SUBMIT=1`   | zusätzlich Tests, die Dokumente buchen und wieder abbrechen                        |
| `ERPNEXT_TEST_MAX_INVOICES`     | Anzahl Rechnungen für die Parser-Regression (Standard 25)                          |
| `ERPNEXT_TEST_PARSER_MIN_MATCH` | Mindest-Trefferquote der Parser-Regression, 0–1 (Standard 0.5)                     |

Die Zugangsdaten werden **nur** aus diesen Variablen gelesen, nie aus der `erpnext.json`
des Benutzers. Schreibtests laufen so nicht versehentlich gegen die Produktivinstanz.

## Sicherheitsnetz

* **Keine Dialoge, keine Fremdeinstellungen.** `PySimpleGUI`, `PySimpleGUIWx` und `easygui`
  werden in allen Tests durch Stubs ersetzt (`tests/support/stubs.py`). Ein Test, der
  unerwartet einen Dialog öffnen würde, scheitert mit `GuiCalled`. Die echte `erpnext.json`
  wird nie angefasst.
* **Nur-Lese-Tests können nicht schreiben.** In `tests/online_read` ist `Api.api` ein
  `ReadOnlyClient`, der jeden schreibenden Aufruf mit `ReadOnlyViolation` abbricht.
* **Schreibtests räumen auf.** Angelegte Dokumente heißen `pytest-<id>` (oder tragen die
  Kennung in Referenz/Bemerkung) und werden über die `cleanup`-Fixture gelöscht; gebuchte
  Dokumente werden zuvor abgebrochen. Bleibt etwas liegen, meldet pytest eine Warnung mit
  den Dokumentnamen. `test_bank_write.py` setzt `last_integration_date` des benutzten
  Bankkontos zurück. `test_load_item_data_completes_item_defaults` ergänzt – wie das Programm
  beim Start – fehlende `item_defaults` an Artikeln; das bleibt bestehen.

## Optionale Abhängigkeiten

Fehlen `jsondiff`, `jsoneditor`, `anytree`, `plotly`, `datefinder` oder
`google-cloud-documentai`, werden sie durch Stubs ersetzt, damit die Projektmodule
importierbar bleiben. Tests, die das echte Paket brauchen, werden übersprungen
(`requires_jsondiff`, `requires_datefinder`, … in `tests/support/deps.py`).
`pdftotext` (xpdf, wie in `install-ubuntu.sh`) muss installiert sein; ohne das Programm
werden die Module rund um `purchase_invoice` übersprungen. Die Wagner-Tests brauchen die
Locale `de_DE.utf8`.

## Aufbau

```
tests/
├── conftest.py            Stubs installieren, Marker, Zustand pro Test zurücksetzen, Fixtures
├── support/
│   ├── stubs.py           GUI- und Paket-Stubs
│   ├── fakes.py           FakeFrappeClient (In-Memory-ERPNext), FakeSession/FakeResponse
│   ├── factories.py       Firmen, Konten, synthetische Rechnungs-PDFs, Kontoauszüge, Parserzeilen
│   ├── deps.py            Verfügbarkeits-Marker für optionale Abhängigkeiten
│   └── live.py            Verbindung, ReadOnlyClient, LiveState, Cleanup für Online-Tests
├── offline/               Unit- und Integrationstests je Modul (test_<modul>.py) plus
│                          test_integration_pipeline.py (Abläufe Ende-zu-Ende gegen den Fake)
├── online_read/           Grundverhalten der API, Stammdaten, Berichte, Parser-Regression
└── online_write/          Anlegen/Ändern/Löschen: Lieferant, Buchungssatz, Zahlung, Kontoauszug,
                           Einkaufsrechnung aus PDF, Lagerbuchung, Artikel, PreRechnung, Buchen
```

Der Fake (`FakeFrappeClient`) bildet die Punkte nach, an denen sich der Client auf
Server-Verhalten verlässt: `get_list` liefert nur die angeforderten Felder (Standard `name`)
und ohne `limit_page_length` höchstens 20 Zeilen; Kindtabellen-Felder ergeben eine Zeile
pro Kindzeile; `insert` berechnet Summen/Status; unausgeglichene Buchungssätze und das
Löschen gebuchter Dokumente werden abgelehnt. `tests/online_read/test_connection_live.py`
prüft genau diese Annahmen gegen den echten Server.

## Befunde dokumentieren (`xfail`)

Ein Test, der einen vermuteten Fehler im Client festhält, bekommt `@pytest.mark.xfail(strict=True,
reason=...)`: Er „besteht“, solange der Fehler da ist, und schlägt an, sobald er behoben wurde
(dann Marker entfernen). Die 22 Befunde aus dem Aufbau der Suite (2026-09-03) sind inzwischen
korrigiert; aktuell gibt es keine `xfail`-Tests. Übersicht jederzeit:
`python3 -m pytest tests/offline -ra | grep XFAIL`.

## Parser-Regression mit echten Rechnungen

`tests/online_read/test_parser_regression.py` ersetzt `test/test_pinv_parser.py`. Es lädt bis zu
`ERPNEXT_TEST_MAX_INVOICES` Einkaufsrechnungs-PDFs von der Instanz (oder nutzt
`test/data/purchase_invoices.json` samt PDFs, falls mit `test/get_purchase_invoices.py` erzeugt),
parst sie mit `is_test=True` und vergleicht die erkannte Rechnungsnummer mit `bill_no`. Die
Ausgabe (`-s`) zeigt Abweichungen je Parser.
