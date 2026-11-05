# ERPNext Antwortentwurf – Thunderbird-Add-on

Ein Knopf „Antwort entwerfen“ in der Nachrichtenansicht. Er holt den bisherigen Mailverlauf mit
dem Absender aus ERPNext, die Wissensdatei und ähnliche frühere Antworten des Teams, lässt Claude
eine Antwort im eigenen Tonfall entwerfen und öffnet sie als normale Antwort-Mail (mit
In-Reply-To, Zitat und Signatur wie gewohnt). Der Entwurf wird wie jede Mail gelesen,
nachbearbeitet und gesendet; nichts geht automatisch raus.

## Voraussetzungen

- Thunderbird 128 oder neuer.
- Ein ERPNext-Benutzer mit API-Zugang: in ERPNext oben rechts „Meine Einstellungen“, Abschnitt
  „API-Zugang“, „Schlüssel erzeugen“. API Key und API Secret notieren.
- Ein Anthropic-API-Schlüssel (console.anthropic.com).
- In ERPNext müssen die Wissensdatei und der Antwortkorpus als private Dateien im Ordner
  „Home/Antworten“ liegen. Das erledigt `reply_material_upload.py` aus dem Client (einmalig und
  nach jeder Änderung der Wissensdatei).

## Installation

1. `thunderbird-addon/build.sh` erzeugt `antwortentwurf.xpi` (oder den Ordnerinhalt selbst als
   ZIP packen und in `.xpi` umbenennen).
2. Thunderbird: Menü „Add-ons und Themes“, Zahnrad, „Add-on aus Datei installieren“, die `.xpi`
   wählen. Alternativ zum Ausprobieren ohne Paket: „Add-ons debuggen“, „Temporäres Add-on laden“,
   die `manifest.json` wählen.
3. In den Add-on-Einstellungen eintragen: ERPNext-Server, API-Schlüssel und -Secret,
   Anthropic-Schlüssel, eigene Absenderadresse (sie wählt die eigenen früheren Antworten als
   Beispiele), optional Modell und Vorname. „Speichern“ fragt einmal nach der Erlaubnis, den
   ERPNext-Server anzusprechen. „Verbindung testen“ prüft Zugang und Wissensdatei, „Wissensdatei
   neu laden“ holt sie sofort (sonst wird einmal täglich auf eine neue Fassung geprüft).

## Benutzung

Mail öffnen, in der Kopfzeile der Nachricht auf „Antwort entwerfen“ klicken. Nach 10 bis 30
Sekunden öffnet sich das Antwortfenster mit dem Entwurf über dem zitierten Original. Bei Fehlern
erscheint eine Benachrichtigung (fehlende Einstellung, Absender ist das Team, ERPNext oder
Claude nicht erreichbar). Der Knopf ist nur für Mails von außen gedacht; interne Mails und
Automaten lehnt er ab.

## Was an Claude geht und was es kostet

Stilregeln, Fakten und Rückfragen der Wissensdatei als gecachter System-Prompt, dazu die zwei bis
drei passenden Musterantworten, die vier ähnlichsten früheren Anfrage-Antwort-Paare, die letzten
zwölf Mails mit dem Absender (ohne Zitate und Signaturen) und die Mail selbst. Rund 20.000 bis
30.000 Eingabe-Tokens, ein paar Cent pro Entwurf; der Verbrauch steht in der Konsole des Add-ons.
Anthropic trainiert laut API-Bedingungen nicht mit diesen Daten.

## Entwicklung

- `lib/material.js`: reine Logik (Zitate entfernen, Wissensdatei zerlegen, Auswahl, Prompt,
  HTML), 1:1 aus `reply_corpus.py` und `reply_draft.py` des Clients übertragen.
- `lib/erpnext.js`: REST-Zugriff und Zwischenspeicher für Wissensdatei und Korpus.
- `lib/claude.js`: der Aufruf der Messages-API.
- `background.js`: der Knopf; `options.*`: Einstellungen.
- Tests: `node --test thunderbird-addon/test/material.test.mjs`.
