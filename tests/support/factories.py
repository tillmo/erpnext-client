"""Test data factories: companies, accounts, synthetic PDFs, bank statements, parser lines.

Everything here is deliberately made up (no real supplier, customer or
account data), but follows the structures the client expects.
"""
from __future__ import annotations

import codecs
import csv
import datetime
import io
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from os import PathLike

    from bank import BankAccount
    from company import Company
    from purchase_invoice import PurchaseInvoice
    from support.fakes import FakeFrappeClient

# ------------------------------------------------------------- Accounts
SOMIKO = "SoMiKo"
COMPANY = "Bremer SolidarStrom"
LADEN = "Laden"

ACCOUNTS_SOMIKO: list[tuple[str, str, int]] = [
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

ACCOUNTS_LADEN: list[tuple[str, str, int]] = [
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

TAXES_SOMIKO: dict[float, str] = {19.0: "1576 - Abziehbare VSt. 19% - SoMiKo"}
TAXES_LADEN: dict[float, str] = {19.0: "1576 - Abziehbare VSt. 19% - Laden", 7.0: "1571 - Abziehbare VSt. 7% - Laden"}


def account_docs(company_name: str, accounts: Iterable[tuple[str, str, int]]) -> list[dict[str, Any]]:
    return [{"name": name, "account_name": name.rsplit(" - ", 1)[0], "company": company_name,
             "is_group": is_group, "root_type": root_type}
            for name, root_type, is_group in accounts]


def company_doc(name: str = COMPANY, abbr: str = SOMIKO) -> dict[str, Any]:
    return {"name": name, "company_name": name, "abbr": abbr,
            "cost_center": "Haupt - " + abbr,
            "default_expense_account": "4996 - Herstellungskosten - " + abbr,
            "default_payable_account": "1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - " + abbr,
            "default_receivable_account": "1400 - Forderungen aus Lieferungen und Leistungen - " + abbr,
            "default_finance_book": None, "parent_company": None}


def make_company(name: str = COMPANY, abbr: str = SOMIKO, taxes: dict[float, str] | None = None,
                 accounts: list[tuple[str, str, int]] | None = None) -> Company:
    """Company object with the data that load_data() otherwise fetches from the server."""
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


def seed_company_data(api: FakeFrappeClient, name: str = COMPANY, abbr: str = SOMIKO,
                      taxes: dict[float, str] | None = None, accounts: list[tuple[str, str, int]] | None = None) -> None:
    """Creates everything in the fake that Company.load_data() queries."""
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


def iban_de(blz: int, kto: int) -> str:
    """Correct IBAN computation (with two-digit check digits) as reference."""
    bban = "{:08d}{:010d}".format(blz, kto)
    check = 98 - int(bban + "131400") % 97
    return "DE{:02d}{}".format(check, bban)


BLZ_SPARKASSE = 29050101
BLZ_SPARDA = 25090500
BLZ_ETHIK = 83094495
IBAN_SPARKASSE = iban_de(BLZ_SPARKASSE, 1234567890)
IBAN_SPARDA = iban_de(BLZ_SPARDA, 987654321)
IBAN_FREMD = iban_de(20050550, 1122334455)  # Haspa, not supported


def bank_account_doc(name: str = "Sparkasse Bremen - SoMiKo", company: str = COMPANY, iban: str = IBAN_SPARKASSE,
                     account: str = "Bank - SoMiKo", last_integration_date: str = "2026-08-01") -> dict[str, Any]:
    return {"name": name, "account_name": name, "company": company, "iban": iban, "account": account,
            "last_integration_date": last_integration_date}


def make_bank_account(api: FakeFrappeClient, comp: Company, **kwargs: Any) -> BankAccount:
    """Create a Bank Account in the fake and instantiate it as bank.BankAccount."""
    import bank
    doc = bank_account_doc(company=comp.name, **kwargs)
    api.add("Bank Account", **doc)
    return bank.BankAccount(doc)


def bank_transaction_doc(bank_account: str, company: str = COMPANY, date: str = "2026-08-15", deposit: float = 0.0,
                         withdrawal: float = 0.0, description: str = "Testbuchung", status: str = "Pending",
                         **extra: Any) -> dict[str, Any]:
    amount = deposit or withdrawal
    doc: dict[str, Any] = {"date": date, "deposit": deposit, "withdrawal": withdrawal, "description": description,
           "bank_account": bank_account, "company": company, "status": status,
           "allocated_amount": 0.0, "unallocated_amount": amount, "currency": "EUR",
           "payment_entries": [], "docstatus": 0}
    doc.update(extra)
    return doc


# ------------------------------------------------------------- Invoices
def make_purchase_invoice(comp: Company, update_stock: bool = False, aggregate_item_code: str | None = None,
                          parser_fields: bool = True) -> PurchaseInvoice:
    """PurchaseInvoice object for the company comp (sets -company- in the settings).

    The constructor does not create supplier/no/shipping/total_vat/items - only
    parse_invoice or the parsers do. So that individual methods can be tested in isolation,
    these fields are initialised here with their start values (parser_fields=True).
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


def write_pdf(path: str | PathLike[str], lines: Iterable[str], font: str = "Courier", size: int = 10) -> str:
    """Simple one-page PDF with fixed lines (Courier -> column-faithful with pdftotext)."""
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


def write_generic_invoice_pdf(path: str | PathLike[str], no: str = "2026-0815", date: str = "03.09.2026",
                              net: float = 100.0, vat: float = 19.0,
                              supplier: str = "Muster Solartechnik GmbH") -> str:
    def de(x: float) -> str:
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


# ------------------------------------------------------ Bank statements
def write_sparkasse_csv(path: str | PathLike[str], rows: Iterable[dict[str, str]], iban: str = IBAN_SPARKASSE) -> str:
    """CSV in the Sparkasse Bremen export format (ISO-8859-4, ';', 17 columns).

    rows: list of dicts with date ('dd.mm.yy'), purpose, partner, partner_iban, amount ('1.234,56' or '-12,00').
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


def write_sparda_csv(path: str | PathLike[str], rows: Iterable[dict[str, str]], iban: str = IBAN_SPARDA,
                     start_balance: str = "1.000,00") -> str:
    """CSV in the Sparda/Ethikbank format (UTF-8, ';', date dd.mm.yyyy in column 5, balance in column 13).

    The first transaction row contains the closing balance (newest transaction first).
    rows: dicts with date, partner, partner_iban, purpose, amount, balance.
    """
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    # no short preamble rows: read_sparda_ethik accesses row[5] on every row with >1 column
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


# ----------------------------------------------------- Parser test lines
def layout(columns: dict[int, Any], width: int | None = None, newline: bool = True) -> str:
    """Build a line with text at fixed column positions, as pdftotext -table delivers it.

    columns: {offset: text}. As with pdftotext, every line ends with '\\n'.
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


def right_aligned(prefix: str, value: str, width: int) -> str:
    """Fixed-width line whose last characters before the '\\n' are the value (for line[-9:-1] accesses)."""
    body = prefix.ljust(width - len(value)) + value
    return body + "\n"


def de_amount(x: float) -> str:
    return "{:,.2f}".format(x).replace(",", "X").replace(".", ",").replace("X", ".")


def krannich_lines(update_stock: bool = True) -> list[str]:
    """Synthetic Krannich invoice in the column geometry the parser expects.

    Positions: qty/unit from column 73, amount from column 157; VAT line: net from 146,
    tax right-aligned at the end of the line; freight right-aligned at the end of the line.
    Net 1.200,00 (2x 500,00 + 100,00 cable + 100,00 freight), VAT 228,00, total 1.428,00.
    """
    lines = [
        layout({0: "Krannich Solar GmbH & Co KG   Rechnung"}),
        layout({0: "Rechnung 41234567 15.03.2024"}),
        layout({0: "Auftragsbestätigung AB998877 vom 01.03.2024"}),
        layout({0: "Pos  Artikel-Nr.   Bezeichnung", 73: "Menge", 157: "Gesamt"}),
        # position 1: 2 pcs at 500,00
        layout({0: "1", 5: "KS-MOD-400", 73: "2 Stk", 157: de_amount(1000.0)}),
        layout({5: "Solarmodul 400 Wp schwarz"}),
        layout({5: "Einzelpreis 500,00"}),
        # position 2: roll of cable -> 50 metres
        layout({0: "2", 5: "KS-KAB-50", 73: "1 Rol", 157: de_amount(100.0)}),
        layout({5: "Solarkabel schwarz Rolle 50 m"}),
        # totals block (own group, starts with a digit)
        layout({0: "2024 Summenblock"}),
        right_aligned(layout({0: "Freight / Frachtkosten"}, newline=False), de_amount(100.0), 170),
        right_aligned(layout({0: "MwSt 19%", 146: de_amount(1200.0)}, newline=False), de_amount(228.0), 170),
        layout({0: "Endsumme EUR", 150: de_amount(1428.0)}),
    ]
    return lines


def heckert_lines() -> list[str]:
    """Synthetic Heckert invoice. qty from column 60, price from 98, amount from 135.

    2 modules at 300,00 = 600,00 less discount 50,00 -> 550,00; transport 30,00
    -> net 580,00; VAT 110,20; gross 690,20.
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


def wagner_lines(rechnung: bool = True) -> list[str]:
    """Synthetic Wagner Solar invoice (or pro forma invoice).

    3 pieces at 200,00 = 600,00 plus freight 45,00; net total 645,00; VAT 122,55.
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


def pvxchange_lines() -> list[str]:
    """Synthetic pvXchange invoice (raw text). 4 modules at 150,00 = 600,00; transport 40,00."""
    lines = [
        "pvXchange Trading GmbH\n",
        "Rechnung Nr. PVX-2024-100\n",
        "Rechnungsdatum: 12.05.2024\n",
        "Pos. Menge Bezeichnung Einzelpreis Gesamt\n",
        "1 4 Solarmodul Mono 410 Wp Artikelnummer: PVX-410 150,00 EUR 600,00 EUR\n",
        "2 1 Transportkosten 40,00 EUR 40,00 EUR\n",
        "3 1 Selbstabholer 0,00 EUR 0,00 EUR\n",
        "Nettosumme 640,00 EUR\n",
        "MwSt 19% 121,60 EUR\n",
        "Gesamt 761,60 EUR\n",
    ]
    return lines


def nkk_lines() -> list[str]:
    """Naturkost Kontor invoice (shop): date, then tax lines '19,00% netto rabatt ... steuer'."""
    lines = [
        "Naturkost Kontor Bremen GmbH Rechnung\n",
        "Rechnung 555123 12.06.2024\n",
        "Steuersatz Netto Rabatt Netto2 Steuerbasis Steuer\n",
        "19,00% 100,00 0,00 20,00 120,00 22,80\n",
        "7,00% 200,00 0,00 10,00 210,00 14,70\n",
    ]
    return lines


def kornkraft_lines() -> list[str]:
    """Kornkraft invoice (shop, multi): 'Rechnung <nr>', date, tax lines with rate in words[0:3]."""
    lines = [
        "Kornkraft Naturkost GmbH\n",
        "Rechnung 777001\n",
        "Datum 20.06.2024\n",
        "Zusammenfassung nach Steuersatz\n",
        "Steuer 19,0 % Netto 100,00 19,00 119,00\n",
        "Steuer 7,0 % Netto 300,00 21,00 321,00\n",
    ]
    return lines


def google_invoice_json(supplier: str = "Muster Solartechnik GmbH", bill_no: str = "RE 2024-77",
                        total: str = "1.190,00 EUR", net: str = "1.000,00", tax: str = "190,00",
                        posting_date: str = "15.03.2024", due_date: str | None = None, order_id: str = "BEST-1",
                        items: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Replica of the JSON returned by prerechnung.extract_invoice_info."""
    ents: list[dict[str, Any]] = []

    def ent(typ: str, value: str | None, conf: float = 0.9) -> None:
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
        props: list[dict[str, Any]] = []
        if "props" in item:   # explicit order (document order matters for the parser)
            props = [{"type": t, "value": v, "confidence": 0.8} for t, v in item["props"]]
        for key, typ in (("description", "item-description"), ("code", "item-code"), ("qty", "item-quantity"),
                         ("rate", "item-unit-price"), ("amount", "item-amount")):
            if key in item:
                props.append({"type": typ, "value": item[key], "confidence": 0.8})
        ents.append({"type": "item", "value": item.get("description"), "confidence": 0.8, "properties": props})
    return {"document_text": "...", "entities": ents}


def today() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")
