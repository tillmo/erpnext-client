"""Testdaten-Fabriken: Firmen, Konten, synthetische PDFs, Kontoauszüge, Parser-Zeilen.

Alles hier ist bewusst frei erfunden (keine echten Lieferanten-, Kunden- oder
Kontodaten), orientiert sich aber an den Strukturen, die der Client erwartet.
"""
import codecs
import csv
import datetime
import io
from collections import defaultdict

# --------------------------------------------------------------- Konten
SOMIKO = "SoMiKo"
COMPANY = "Bremer SolidarStrom"
LADEN = "Laden"

ACCOUNTS_SOMIKO = [
    # name, root_type, is_group
    ("Bank - SoMiKo", "Asset", 0),
    ("1576 - Abziehbare VSt. 19% - SoMiKo", "Asset", 0),
    ("1400 - Forderungen aus Lieferungen und Leistungen - SoMiKo", "Asset", 0),
    ("1518 - Geleistete Anzahlungen, 19 % Vorsteuer - SoMiKo", "Asset", 0),
    ("I. Vorräte - SoMiKo", "Asset", 1),
    ("3980 - Warenbestand unsere Lager - SoMiKo", "Asset", 0),
    ("1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - SoMiKo", "Liability", 0),
    ("1718 - Erhaltene, versteuerte Anzahlungen 19 % USt (Verbindlichkeiten) - SoMiKo", "Liability", 0),
    ("1776 - Umsatzsteuer 19% - SoMiKo", "Liability", 0),
    ("1780 - Umsatzsteuer-Vorauszahlung - SoMiKo", "Liability", 0),
    ("A. Eigenkapital - SoMiKo", "Equity", 1),
    ("8401 - Selbstbauanlagen 19% - SoMiKo", "Income", 0),
    ("8403 - Balkonmodule 19% - SoMiKo", "Income", 0),
    ("8291 - Selbstbauanlagen 0% - SoMiKo", "Income", 0),
    ("4996 - Herstellungskosten - SoMiKo", "Expense", 0),
    ("4210 - Miete und Nebenkosten - SoMiKo", "Expense", 0),
    ("4985 - Werkzeuge und Kleingeräte - SoMiKo", "Expense", 0),
    ("3800 - Bezugsnebenkosten - SoMiKo", "Expense", 0),
    ("Aufwand - SoMiKo", "Expense", 1),
]

ACCOUNTS_LADEN = [
    ("Bank - Laden", "Asset", 0),
    ("1576 - Abziehbare VSt. 19% - Laden", "Asset", 0),
    ("1571 - Abziehbare VSt. 7% - Laden", "Asset", 0),
    ("1776 - Umsatzsteuer 19% - Laden", "Liability", 0),
    ("1771 - Umsatzsteuer 7% - Laden", "Liability", 0),
    ("1780 - Umsatzsteuer-Vorauszahlung - Laden", "Liability", 0),
    ("1600 - Verbindlichkeiten - Laden", "Liability", 0),
    ("1400 - Forderungen - Laden", "Asset", 0),
    ("8503 - Ladenkasse Ust. noch unklar - Laden", "Income", 0),
    ("8301 - Ladenkasse Ust.7% - Laden", "Income", 0),
    ("8401 - Ladenkasse Ust.19% - Laden", "Income", 0),
    ("8502 - Café an Laden USt. noch unklar - Laden", "Income", 0),
    ("8302 - Café an Laden Ust.7% - Laden", "Income", 0),
    ("8402 - Café an Laden Ust.19% - Laden", "Income", 0),
    ("8501 - Bieterrunde USt. noch unklar - Laden", "Income", 0),
    ("8303 - Bieterrunde Laden Ust.7% - Laden", "Income", 0),
    ("8403 - Bieterrunde Laden Ust.19% - Laden", "Income", 0),
    ("3300 - Wareneingang 7% Vorsteuer - Laden", "Expense", 0),
    ("3400 - Wareneingang 19% Vorsteuer - Laden", "Expense", 0),
    ("3401 - NKK 19% Vorsteuer - Laden", "Expense", 0),
    ("3301 - NKK 7% Vorsteuer - Laden", "Expense", 0),
    ("3402 - Kornkraft 19% Vorsteuer - Laden", "Expense", 0),
    ("3302 - Kornkraft 7% Vorsteuer - Laden", "Expense", 0),
]

TAXES_SOMIKO = {19.0: "1576 - Abziehbare VSt. 19% - SoMiKo"}
TAXES_LADEN = {19.0: "1576 - Abziehbare VSt. 19% - Laden", 7.0: "1571 - Abziehbare VSt. 7% - Laden"}


def account_docs(company_name, accounts):
    return [{"name": name, "account_name": name.rsplit(" - ", 1)[0], "company": company_name,
             "is_group": is_group, "root_type": root_type}
            for name, root_type, is_group in accounts]


def company_doc(name=COMPANY, abbr=SOMIKO):
    return {"name": name, "company_name": name, "abbr": abbr,
            "cost_center": "Haupt - " + abbr,
            "default_expense_account": "4996 - Herstellungskosten - " + abbr,
            "default_payable_account": "1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - " + abbr,
            "default_receivable_account": "1400 - Forderungen aus Lieferungen und Leistungen - " + abbr,
            "default_finance_book": None, "parent_company": None}


def make_company(name=COMPANY, abbr=SOMIKO, taxes=None, accounts=None):
    """Company-Objekt mit den Daten, die sonst load_data() vom Server holt."""
    import company as company_mod
    if taxes is None:
        taxes = TAXES_LADEN if name == LADEN else TAXES_SOMIKO
    if accounts is None:
        accounts = ACCOUNTS_LADEN if name == LADEN else ACCOUNTS_SOMIKO
    comp = company_mod.Company(company_doc(name, abbr))
    comp.taxes = dict(taxes)
    comp.default_vat = list(taxes.keys())[0]
    comp.accounts = account_docs(name, accounts)
    comp.leaf_accounts = [a for a in comp.accounts if a["is_group"] == 0]
    comp.leaf_accounts.sort(key=lambda acc: acc["root_type"])
    comp.leaf_accounts_by_root_type = defaultdict(list)
    for acc in comp.leaf_accounts:
        comp.leaf_accounts_by_root_type[acc["root_type"]].append(acc)
    comp.leaf_accounts_by_root_type = dict(comp.leaf_accounts_by_root_type)
    comp.leaf_accounts_for_debit = comp.leaf_accounts_starting_with_root_type("Income")
    comp.leaf_accounts_for_credit = comp.leaf_accounts_starting_with_root_type("Expense")
    comp.journal = []
    comp.purchase_invoices = defaultdict(list)
    comp.data_loaded = True
    return comp


def seed_company_data(api, name=COMPANY, abbr=SOMIKO, taxes=None, accounts=None):
    """Legt im Fake alles an, was Company.load_data() abfragt."""
    if taxes is None:
        taxes = TAXES_LADEN if name == LADEN else TAXES_SOMIKO
    if accounts is None:
        accounts = ACCOUNTS_LADEN if name == LADEN else ACCOUNTS_SOMIKO
    api.add("Company", **company_doc(name, abbr))
    api.add("Purchase Taxes and Charges Template", name="Vorsteuer {} - {}".format(
        "/".join(str(int(r)) for r in taxes), abbr), company=name,
        taxes=[{"rate": rate, "account_head": acc, "charge_type": "On Net Total"} for rate, acc in taxes.items()])
    for doc in account_docs(name, accounts):
        api.add("Account", **doc)


def iban_de(blz, kto):
    """Korrekte IBAN-Berechnung (mit zweistelliger Prüfziffer) als Referenz."""
    bban = "{:08d}{:010d}".format(blz, kto)
    check = 98 - int(bban + "131400") % 97
    return "DE{:02d}{}".format(check, bban)


BLZ_SPARKASSE = 29050101
BLZ_SPARDA = 25090500
BLZ_ETHIK = 83094495
IBAN_SPARKASSE = iban_de(BLZ_SPARKASSE, 1234567890)
IBAN_SPARDA = iban_de(BLZ_SPARDA, 987654321)
IBAN_FREMD = iban_de(20050550, 1122334455)  # Haspa, nicht unterstützt


def bank_account_doc(name="Sparkasse Bremen - SoMiKo", company=COMPANY, iban=IBAN_SPARKASSE,
                     account="Bank - SoMiKo", last_integration_date="2026-08-01"):
    return {"name": name, "account_name": name, "company": company, "iban": iban, "account": account,
            "last_integration_date": last_integration_date}


def make_bank_account(api, comp, **kwargs):
    """Bank Account im Fake anlegen und als bank.BankAccount instanziieren."""
    import bank
    doc = bank_account_doc(company=comp.name, **kwargs)
    api.add("Bank Account", **doc)
    return bank.BankAccount(doc)


def bank_transaction_doc(bank_account, company=COMPANY, date="2026-08-15", deposit=0.0, withdrawal=0.0,
                         description="Testbuchung", status="Pending", **extra):
    amount = deposit or withdrawal
    doc = {"date": date, "deposit": deposit, "withdrawal": withdrawal, "description": description,
           "bank_account": bank_account, "company": company, "status": status,
           "allocated_amount": 0.0, "unallocated_amount": amount, "currency": "EUR",
           "payment_entries": [], "docstatus": 0}
    doc.update(extra)
    return doc


# ------------------------------------------------------------ Rechnungen
def make_purchase_invoice(comp, update_stock=False, aggregate_item_code=None, parser_fields=True):
    """PurchaseInvoice-Objekt für die Firma comp (setzt -company- in den Settings).

    Der Konstruktor legt supplier/no/shipping/total_vat/items nicht an - das tun erst
    parse_invoice bzw. die Parser. Damit einzelne Methoden isoliert testbar sind,
    werden diese Felder hier mit ihren Startwerten belegt (parser_fields=True).
    """
    import PySimpleGUI as sg
    import purchase_invoice
    sg.UserSettings()["-company-"] = comp.name
    pinv = purchase_invoice.PurchaseInvoice(update_stock, aggregate_item_code=aggregate_item_code)
    if parser_fields:
        pinv.supplier = None
        pinv.no = None
        pinv.shipping = 0.0
        pinv.total_vat = 0.0
        pinv.items = []
    return pinv


GENERIC_INVOICE_LINES = [
    "Muster Solartechnik GmbH",
    "Sonnenallee 12, 28199 Bremen",
    "",
    "Rechnungsnummer: 2026-0815",
    "Rechnungsdatum 03.09.2026",
    "Ihre Bestellung 4711",
    "",
    "Pos  Artikel                    Menge   Einzelpreis   Betrag",
    "1    Montageschiene 2m           4       25,00        100,00",
    "",
    "Nettobetrag                                          100,00",
    "MwSt. 19%                                             19,00",
    "Gesamtbetrag                                        119,00 EUR",
]


def write_pdf(path, lines, font="Courier", size=10):
    """Einfaches einseitiges PDF mit festen Zeilen (Courier -> spaltentreu bei pdftotext)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(font, size)
    y = A4[1] - 60
    for line in lines:
        c.drawString(40, y, line)
        y -= size * 1.4
        if y < 40:
            c.showPage()
            c.setFont(font, size)
            y = A4[1] - 60
    c.save()
    return str(path)


def write_generic_invoice_pdf(path, no="2026-0815", date="03.09.2026", net=100.0, vat=19.0,
                              supplier="Muster Solartechnik GmbH"):
    def de(x):
        return "{:,.2f}".format(x).replace(",", "X").replace(".", ",").replace("X", ".")
    lines = [
        supplier,
        "Sonnenallee 12, 28199 Bremen",
        "",
        "Rechnungsnummer: " + no,
        "Rechnungsdatum " + date,
        "",
        "Pos  Artikel                    Menge   Einzelpreis   Betrag",
        "1    Montageschiene 2m           1       {:>10}   {:>10}".format(de(net), de(net)),
        "",
        "Nettobetrag                                         {:>10}".format(de(net)),
        "MwSt. 19%                                           {:>10}".format(de(vat)),
        "Gesamtbetrag                                        {:>10} EUR".format(de(net + vat)),
    ]
    return write_pdf(path, lines)


# ---------------------------------------------------------- Kontoauszüge
def write_sparkasse_csv(path, rows, iban=IBAN_SPARKASSE):
    """CSV im Sparkasse-Bremen-Export-Format (ISO-8859-4, ';', 17 Spalten).

    rows: Liste von dicts mit date ('dd.mm.yy'), purpose, partner, partner_iban, amount ('1.234,56' oder '-12,00').
    """
    header = ["Auftragskonto", "Buchungstag", "Valutadatum", "Buchungstext", "Verwendungszweck",
              "Glaeubiger ID", "Mandatsreferenz", "Kundenreferenz (End-to-End)", "Sammlerreferenz",
              "Lastschrift Ursprungsbetrag", "Auslagenersatz Ruecklastschrift", "Beguenstigter/Zahlungspflichtiger",
              "Kontonummer/IBAN", "BIC (SWIFT-Code)", "Betrag", "Waehrung", "Info"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(header)
    for r in rows:
        w.writerow([iban, r["date"], r["date"], "UEBERWEISUNG", r["purpose"], "", "", "", "", "", "",
                    r["partner"], r.get("partner_iban", IBAN_FREMD), "SPKBREXX", r["amount"], "EUR", "Umsatz gebucht"])
    with codecs.open(str(path), "w", "iso-8859-4") as f:
        f.write(buf.getvalue())
    return str(path)


def write_sparda_csv(path, rows, iban=IBAN_SPARDA, start_balance="1.000,00"):
    """CSV im Sparda/Ethikbank-Format (UTF-8, ';', Datum dd.mm.yyyy in Spalte 5, Saldo in Spalte 13).

    Die erste Buchungszeile enthält den Endsaldo (neueste Buchung zuerst).
    rows: dicts mit date, partner, partner_iban, purpose, amount, balance.
    """
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    # keine kurzen Vorspann-Zeilen: read_sparda_ethik greift bei jeder Zeile mit >1 Spalte auf row[5] zu
    w.writerow(["Kontonummer", "IBAN", "Konto", "Bank", "Buchungstag", "Valuta", "Auftraggeber/Empfänger",
                "IBAN Gegenkonto", "BIC", "Buchungstext", "Verwendungszweck", "Betrag", "Währung", "Saldo",
                "Währung Saldo"])
    for r in rows:
        w.writerow(["987654321", iban, "Giro", "Sparda", r["date"], r["date"], r["partner"],
                    r.get("partner_iban", IBAN_FREMD), "GENODEF1S05", "Überweisung", r["purpose"], r["amount"],
                    "EUR", r["balance"], "EUR"])
    with open(str(path), "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    return str(path)


# ---------------------------------------------------- Parser-Testzeilen
def layout(columns, width=None, newline=True):
    """Zeile mit Text an festen Spaltenpositionen bauen, wie pdftotext -table sie liefert.

    columns: {offset: text}. Wie bei pdftotext endet jede Zeile mit '\\n'.
    """
    s = ""
    for offset in sorted(columns):
        text = str(columns[offset])
        if len(s) > offset:
            raise ValueError("Spalte {} überlappt: {!r}".format(offset, s))
        s = s.ljust(offset) + text
    if width:
        s = s.ljust(width)
    return s + ("\n" if newline else "")


def right_aligned(prefix, value, width):
    """Zeile fester Breite, deren letzte Zeichen vor dem '\\n' der Wert ist (für line[-9:-1]-Zugriffe)."""
    body = prefix.ljust(width - len(value)) + value
    return body + "\n"


def de_amount(x):
    return "{:,.2f}".format(x).replace(",", "X").replace(".", ",").replace("X", ".")


def krannich_lines(update_stock=True):
    """Synthetische Krannich-Rechnung in der Spaltengeometrie, die der Parser erwartet.

    Positionen: qty/unit ab Spalte 73, Betrag ab Spalte 157; MwSt-Zeile: Netto ab 146,
    Steuer rechtsbündig am Zeilenende; Fracht rechtsbündig am Zeilenende.
    Netto 1.200,00 (2x 500,00 + 100,00 Kabel + 100,00 Fracht), MwSt 228,00, Endsumme 1.428,00.
    """
    lines = [
        layout({0: "Krannich Solar GmbH & Co KG   Rechnung"}),
        layout({0: "Rechnung 41234567 15.03.2024"}),
        layout({0: "Auftragsbestätigung AB998877 vom 01.03.2024"}),
        layout({0: "Pos  Artikel-Nr.   Bezeichnung", 73: "Menge", 157: "Gesamt"}),
        # Position 1: 2 Stk à 500,00
        layout({0: "1", 5: "KS-MOD-400", 73: "2 Stk", 157: de_amount(1000.0)}),
        layout({5: "Solarmodul 400 Wp schwarz"}),
        layout({5: "Einzelpreis 500,00"}),
        # Position 2: Rolle Kabel -> 50 Meter
        layout({0: "2", 5: "KS-KAB-50", 73: "1 Rol", 157: de_amount(100.0)}),
        layout({5: "Solarkabel schwarz Rolle 50 m"}),
        # Summenblock (eigene Gruppe, beginnt mit Ziffer)
        layout({0: "2024 Summenblock"}),
        right_aligned(layout({0: "Freight / Frachtkosten"}, newline=False), de_amount(100.0), 170),
        right_aligned(layout({0: "MwSt 19%", 146: de_amount(1200.0)}, newline=False), de_amount(228.0), 170),
        layout({0: "Endsumme EUR", 150: de_amount(1428.0)}),
    ]
    return lines


def heckert_lines():
    """Synthetische Heckert-Rechnung. qty ab Spalte 60, Preis ab 98, Betrag ab 135.

    2 Module à 300,00 = 600,00 abzüglich Rabatt 50,00 -> 550,00; Transport 30,00
    -> Netto 580,00; MwSt 110,20; Brutto 690,20.
    """
    lines = [
        layout({0: "Heckert Solar GmbH", 60: "Schlußrechnung"}),
        layout({0: "Belegnummer / Document Number", 60: "RE-2024-555"}),
        layout({0: "Belegdatum", 60: "12.04.2024"}),
        layout({0: "Auftrag ", 120: "AU-77001 Kunde"}),
        layout({0: "Pos Artikel", 60: "Menge", 98: "Preis", 135: "Betrag"}),
        layout({0: "10", 4: "HS-MOD-380", 60: "2 ST", 98: de_amount(300.0), 135: de_amount(600.0)}),
        layout({4: "Modul NeMo 380 Wp"}),
        layout({4: "Rabatt 8,33%", 135: de_amount(-50.0)}),
        layout({0: "20", 4: "TRANSPORT", 60: "1 ST", 98: de_amount(30.0), 135: de_amount(30.0)}),
        layout({4: "Transportkosten pauschal"}),
        layout({0: "28100 Summen"}),
        layout({0: "Zwischensumme", 135: de_amount(580.0)}),
        layout({0: "MwSt 19%", 135: de_amount(110.20)}),
        layout({0: "Gesamt", 135: de_amount(690.20)}),
    ]
    return lines


def wagner_lines(rechnung=True):
    """Synthetische Wagner-Solar-Rechnung (bzw. Vorkasserechnung).

    3 Stück à 200,00 = 600,00 plus Fracht 45,00; Nettosumme 645,00; MwSt 122,55.
    """
    if rechnung:
        kopf = layout({0: "Rechnung RE-88001", 50: "BEGeno / SolidarStrom"})
        pos1 = layout({0: "1 WS-ART-1 Wechselrichter 3 Stück 200,00 600,00"})
        pos2 = layout({0: "2 WS-FR-1 Fracht 1 Stück 45,00 45,00"})
    else:
        kopf = layout({0: "1. Vorkasserechnung VOR20841", 50: "BEGeno / SolidarStrom"})
        pos1 = layout({0: "1 Wechselrichter Artikelnr. WS-ART-1 3 200,00 600,00"})
        pos2 = layout({0: "2 Fracht Artikelnr. WS-FR-1 1 45,00 45,00"})
    lines = [
        layout({0: "Wagner Solar GmbH", 60: "Seite 1 von 1"}),
        layout({0: "Datum 15. März 2024"}),
        layout({0: "Auftragsnummer AUF-4242"}),
        kopf,
        pos1,
        layout({4: "Hybrid-Wechselrichter 5 kW"}),
        layout({4: "12 Jahre Produktgarantie"}),
        pos2,
        layout({0: "Nettosumme 645,00"}),
        layout({0: "MwSt 19% 122,55"}),
        layout({0: "Gesamtbetrag 767,55"}),
    ]
    return lines


def pvxchange_lines():
    """Synthetische pvXchange-Rechnung (raw-Text). 4 Module à 150,00 = 600,00; Transport 40,00."""
    lines = [
        "pvXchange Trading GmbH\n",
        "Rechnung Nr. PVX-2024-100 12.05.2024\n",
        "Pos. Menge Bezeichnung Einzelpreis Gesamt\n",
        "1 4 Solarmodul Mono 410 Wp Artikelnummer: PVX-410 150,00 EUR 600,00 EUR\n",
        "2 1 Transportkosten 40,00 EUR 40,00 EUR\n",
        "3 1 Selbstabholer 0,00 EUR 0,00 EUR\n",
        "Nettosumme 640,00 EUR\n",
        "MwSt 19% 121,60 EUR\n",
        "Gesamt 761,60 EUR\n",
    ]
    return lines


def nkk_lines():
    """Naturkost-Kontor-Rechnung (Laden): Datum, dann Steuerzeilen '19,00% netto rabatt ... steuer'."""
    lines = [
        "Naturkost Kontor Bremen GmbH Rechnung\n",
        "Rechnung 555123 12.06.2024\n",
        "Steuersatz Netto Rabatt Netto2 Steuerbasis Steuer\n",
        "19,00% 100,00 0,00 20,00 120,00 22,80\n",
        "7,00% 200,00 0,00 10,00 210,00 14,70\n",
    ]
    return lines


def kornkraft_lines():
    """Kornkraft-Rechnung (Laden, multi): 'Rechnung <nr>', Datum, Steuerzeilen mit Satz in words[0:3]."""
    lines = [
        "Kornkraft Naturkost GmbH\n",
        "Rechnung 777001\n",
        "Datum 20.06.2024\n",
        "Zusammenfassung nach Steuersatz\n",
        "Steuer 19,0 % Netto 100,00 19,00 119,00\n",
        "Steuer 7,0 % Netto 300,00 21,00 321,00\n",
    ]
    return lines


def google_invoice_json(supplier="Muster Solartechnik GmbH", bill_no="RE 2024-77", total="1.190,00 EUR",
                        net="1.000,00", tax="190,00", posting_date="15.03.2024", due_date=None,
                        order_id="BEST-1", items=None):
    """Nachbildung des von prerechnung.extract_invoice_info gelieferten JSON."""
    ents = []

    def ent(typ, value, conf=0.9):
        if value is not None:
            ents.append({"type": typ, "value": value, "confidence": conf, "properties": []})
    ent("supplier", supplier)
    ent("supplier", "Falscher Lieferant", 0.3)
    ent("bill_no", bill_no)
    ent("total_amount", total)
    ent("net_amount", net)
    ent("total_tax_amount", tax)
    ent("posting_date", posting_date)
    ent("due_date", due_date)
    ent("order_id", order_id)
    for item in items or []:
        props = []
        if "props" in item:   # explizite Reihenfolge (Dokumentreihenfolge ist für den Parser relevant)
            props = [{"type": t, "value": v, "confidence": 0.8} for t, v in item["props"]]
        for key, typ in (("description", "item-description"), ("code", "item-code"), ("qty", "item-quantity"),
                         ("rate", "item-unit-price"), ("amount", "item-amount")):
            if key in item:
                props.append({"type": typ, "value": item[key], "confidence": 0.8})
        ents.append({"type": "item", "value": item.get("description"), "confidence": 0.8, "properties": props})
    return {"document_text": "...", "entities": ents}


def today():
    return datetime.date.today().strftime("%Y-%m-%d")
