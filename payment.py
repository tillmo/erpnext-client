from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api import Api
from api_wrapper import gui_api_wrapper
from gui import sg

if TYPE_CHECKING:
    from company import Company

def create_payment(is_recv: bool | None, company: Company, account: str,
                   amount: float, date: str, party: str, party_type: str,
                   ref: str, references: list[dict[str, Any]]) -> dict[str, Any] | None:
    # convert to positive amount, changed payment type, if needed
    is_recv = bool(is_recv) != bool(amount < 0)
    amount = abs(amount)
    # the party account follows the party, not the direction: a refund from a supplier is
    # received against the payables, a refund to a customer paid against the receivables
    party_account = company.payable_account if party_type == 'Supplier' else company.receivable_account
    if is_recv:
        paid_from: str | None = party_account
        paid_to: str | None = account
        payment_type = 'Receive'
    else:
        paid_from = account
        paid_to = party_account
        payment_type = 'Pay'
    entry: dict[str, Any] = {'doctype' : 'Payment Entry',
             'title' : party+" "+ref,
             'payment_type': payment_type,
             'posting_date': date,
             'reference_no': ref,
             'reference_date': date,
             'party' : party,
             'party_type' : party_type,
             'company': company.name,
             'finance_book' : company.default_finance_book,
             'paid_from' : paid_from,
             'paid_to': paid_to,
             'paid_amount' : amount,
             'received_amount' : amount,
             'source_exchange_rate': 1.0,
             'target_exchange_rate': 1.0,
             'exchange_rate': 1.0,
             'references' : references}
    p = gui_api_wrapper(Api.api.insert,entry)
    if p:
        print("Zahlung {} erstellt".format(p['name']))
        if sg.UserSettings()['-buchen-']:
            gui_api_wrapper(Api.submit_doc,"Payment Entry",p['name'])
            print("Zahlung {} gebucht".format(p['name']))
    return p


