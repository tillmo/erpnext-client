from __future__ import annotations

import os
from typing import Any
from gui import sg
import utils
import project
import doc
import settings
import purchase_invoice
from api import Api, LIMIT
import args
import company
import tempfile


def process(company_name: str) -> None:
    prs = Api.api.get_list(
        "PreRechnung",
        filters={'company': company_name, 'processed': False},
        fields=['name','pdf'],
        limit_page_length=LIMIT
    )
    for pr in prs:
        process_inv(pr)
    print("Prerechnungen vorprozessiert")


def process_inv(pr: dict[str, Any]) -> None:
    """
    Preprocesses the pre invoice and updates the database with the extracted information.

    Args:
        pr: The pre invoice to be preprocessed
    """
    print(pr['name'])
    pdf = pr['pdf']
    contents = Api.api.get_file(pdf)
    inv = purchase_invoice.PurchaseInvoice(pr['lager'])
    tmpfile,tmpfilename = tempfile.mkstemp(suffix=".pdf")
    with open(tmpfilename, "wb") as f:
        f.write(contents)
    try:
        inv.parse_invoice(tmpfilename,
                          account_abbrv=pr['buchungskonto'],
                          paid_by_submitter=pr['selbst_bezahlt'],
                          given_supplier=pr['lieferant'],
                          is_test=True)
    except Exception as e:
        print(e)
        pass
    try:
        vat = sum(map(int, inv.vat.values()))
    except:
        vat = 0
    if not inv.gross_total:
        inv.gross_total = inv.total + vat
    print("{} {} {}".format(pr['name'], inv.gross_total, inv.order_id))
    if inv.gross_total:
        pr['betrag'] = inv.gross_total
    if inv.order_id:
        pr['auftragsnr'] = inv.order_id
    pr['processed'] = True
    pr['doctype'] = 'PreRechnung'
    Api.api.update(pr)


def to_pay(company_name: str) -> list[dict[str, Any]]:
    prs = Api.api.get_list("PreRechnung", filters={'company': company_name,
                                                   'vom_konto_überwiesen': False,
                                                   'zu_zahlen_am': ['>', '01-01-1980']},
                           fields=['zu_zahlen_am','name','lieferant',
                                   'auftragsnr','betrag','typ',
                                   'datum','kommentar'],
                           limit_page_length=LIMIT)
    prs.sort(key=lambda pr: pr['zu_zahlen_am'])
    sum = 0.0
    for pr in prs:
        sum += pr['betrag']
        pr['summe'] = sum
    return prs


def read_and_transfer(inv: dict[str, Any], check_dup: bool = True,
                      cli_overrides: dict[str, Any] | None = None) -> purchase_invoice.PurchaseInvoice | None:
    """
    Process a pre invoice and create an ERPNext invoice for it.

    Args:
        inv: the pre invoice
        check_dup: check for duplicates, and if found, do not create a new purchase invoice
        cli_overrides: dict of override values for CLI mode (betrag, mwst, konto, lieferant, etc.)
    """
    if not inv['processed']:
        process_inv(inv)
    print("Lese ein {} {}:".format(inv['name'], inv['pdf']))
    pdf = Api.api.get_file(inv['pdf'])
    f = utils.store_temp_file(pdf, ".pdf")
    utils.evince(f)
    update_stock = 'chance' in inv and inv['chance'] and \
                   project.project_type(inv['chance']) in settings.STOCK_PROJECT_TYPES and \
                   inv.get('buchungskonto') in settings.STOCK_PRE_ACCOUNTS
    pinv = purchase_invoice.PurchaseInvoice.read_and_transfer(
        f, update_stock,
        account_abbrv=inv.get('buchungskonto'), paid_by_submitter=inv.get('selbst_bezahlt', False),
        project=inv.get('chance'), supplier=inv.get('lieferant'), check_dup=check_dup,
        cli_overrides=cli_overrides,
        pre_invoice=inv
    )
    if pinv and not inv.get('purchase_invoice'):
        inv['eingepflegt'] = True
        inv['purchase_invoice'] = pinv.doc['name']
        inv_doc = doc.Doc(doc=inv, doctype='PreRechnung')
        inv_doc.update()
    if f:
        try:
            os.remove(f)
        except Exception:
            pass
    return pinv


def cli_read_and_transfer(name: str | None = None, advance: bool = False,
                          overrides: dict[str, Any] | None = None) -> purchase_invoice.PurchaseInvoice | None:
    """List open PreRechnungen and process the selected one (or a named one directly).

    Args:
        name: optional PreRechnung name; if None or empty, list open ones and let user pick
        advance: if True, show Anzahlungsrechnungen instead of regular invoices
        overrides: dict of override values (betrag, mwst, konto, lieferant, projekt,
                   selbst_bezahlt, rechnungsnr)
    """
    company_name = sg.UserSettings()['-company-']
    comp = company.Company.get_company(company_name)
    if not comp:
        print("Kein Bereich gefunden")
        return None

    if name:
        invs = Api.api.get_list(
            'PreRechnung',
            filters={'name': name},
            fields=['datum', 'name', 'chance', 'lieferant', 'pdf',
                    'lager', 'selbst_bezahlt', 'vom_konto_überwiesen', 'typ',
                    'processed', 'balkonmodule', 'buchungskonto',
                    'nuruk', 'nurelektromaterial'],
            limit_page_length=1
        )
        if not invs:
            print("PreRechnung {} nicht gefunden".format(name))
            return None
        inv = invs[0]
    else:
        invs = comp.get_open_pre_invoices(advance)
        if not invs:
            typ = 'Anzahlungsrechnungen' if advance else 'Prerechnungen'
            print("Keine offenen {} gefunden".format(typ))
            return None
        invs.sort(key=lambda x: x['datum'], reverse=True)
        print("\nOffene {}:".format('Anzahlungsrechnungen' if advance else 'Prerechnungen'))
        for i, inv in enumerate(invs):
            print("  {:3d}: {} {:30s} {:25s} {}".format(
                i, inv['datum'], inv['name'],
                (inv.get('lieferant') or '')[:25],
                inv.get('chance') or ''))
        print()
        val = input("Bitte Nummer wählen (leer = Abbrechen): ").strip()
        if not val:
            return None
        try:
            inv = invs[int(val)]
        except (ValueError, IndexError):
            print("Ungültige Auswahl")
            return None

    if overrides:
        if overrides.get('konto'):
            inv['buchungskonto'] = overrides['konto']
        if overrides.get('lieferant'):
            inv['lieferant'] = overrides['lieferant']
        if overrides.get('projekt'):
            inv['chance'] = overrides['projekt']
        if overrides.get('selbst_bezahlt'):
            inv['selbst_bezahlt'] = overrides['selbst_bezahlt']

    return read_and_transfer(inv, cli_overrides=overrides)


def read_and_transfer_pdf(file: str, update_stock: bool = True, account: str | None = None,
                          paid_by_submitter: bool = False, project: str | None = None,
                          supplier: str | None = None,
                          check_dup: bool = True) -> purchase_invoice.PurchaseInvoice | None:
    """
    Process a PDF and directly create an ERPNext invoice for it (without using pre invoices).
    Standalone function to be called from the command line.

    Args:
        file: the PDF file name
        update_stock: update stock if True
        account: default account (abbreviated)
        paid_by_submitter: if the invoice was paid by the submitter
        project: the project
        supplier: the supplier
        check_dup: check for duplicates, and if found, do not create a new purchase invoice
    """
    args.init()
    company.Company.init_companies()
    pinv = purchase_invoice.PurchaseInvoice.read_and_transfer(
        file, update_stock,
        account_abbrv=account, paid_by_submitter=paid_by_submitter,
        project=project, supplier=supplier, check_dup=check_dup)
    return pinv
