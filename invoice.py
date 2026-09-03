from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api import Api, LIMIT
from doc import Doc
import payment
import company

if TYPE_CHECKING:
    from bank import BankTransaction

class Invoice(Doc):
    is_sales: bool
    company_name: str
    date: str
    status: str
    amount: float
    outstanding: float
    is_return: bool
    reference: str
    party: str
    party_type: str

    def __init__(self,doc: dict[str, Any],is_sales: bool) -> None:
        self.doctype = 'Sales Invoice' if is_sales else 'Purchase Invoice'
        super().__init__(doc=doc)
        self.is_sales = is_sales
        self.company_name = doc['company']
        self.date = doc['posting_date']
        self.status = doc['status']
        self.amount = doc['grand_total']
        self.outstanding = doc['outstanding_amount']
        if 'is_return' in doc:
            self.is_return = doc['is_return']
        if self.is_sales:
            self.reference = doc['name']
            self.party = doc['customer']
            self.party_type = 'Customer'
        else:    
            if 'bill_no' in doc and doc['bill_no']:
                self.reference = doc['bill_no']
            else:
                self.reference = doc['name']
            self.amount = -self.amount
            self.party = doc['supplier']
            self.party_type = 'Supplier'
            
    def payment_from_bank_transaction(self,bt: BankTransaction) -> None:
        print("Erstelle und buche Zahlung")
        p = bt.payment(self)
        if p:
            Api.submit_doc('Payment Entry',p['name'])
            
    def payment(self,account: str,amount: float,date: str) -> dict[str, Any] | None:
        if not amount:
            print("Ausstehender Betrag ist 0")
            return None
        ref = self.reference if self.reference else ""
        references =  \
            [{'reference_doctype' : 'Sales Invoice' if self.is_sales else 'Purchase Invoice',
              'reference_name' : self.name,
              'allocated_amount' : amount}]
        comp = company.Company.get_company(self.company_name)
        return payment.create_payment(self.is_sales,comp,account,
                                      amount,date,self.party,self.party_type,
                                      ref,references)
    
    def use_advance_payment(self,py: Doc) -> None:
        print("Verwende Anzahlung")
        advance =\
            {'reference_type': 'Payment Entry',
             'reference_name': py.name,
             'remarks': py.doc['remarks'],
             'advance_amount': py.doc['paid_amount'],
             'allocated_amount': py.doc['paid_amount']}
        self.doc['advances'] = [advance]
        self.update()

def accrual(company: str,year: int) -> tuple[list[str], list[str], list[str], list[str]]:
    start_date = '{}-01-01'.format(year)
    end_date = '{}-12-31'.format(year)
    sinvs = Api.api.get_list("Sales Invoice",
                        filters={'company':company,
                                 'docstatus':1,
                                 'total':['>',0],
                                 'posting_date':['Between',[start_date, end_date]]},
                        fields=['name'],
                        limit_page_length=LIMIT)
    sinvs = [s['name'] for s in sinvs]
    print(".",end="")
    #print(sinvs)
    pinvs = Api.api.get_list("Purchase Invoice",
                        filters={'company':company,
                                 'docstatus':1,
                                 'total':['>',0],
                                 'posting_date':['Between',[start_date, end_date]]},
                        fields=['name'],
                        limit_page_length=LIMIT)
    pinvs = [p['name'] for p in pinvs]
    print(".",end="")
    #print(pinvs)
    ps = Api.api.get_list('Payment Entry',
                        filters={'company':company,
                                 'docstatus':1,
                                 'posting_date':['Between',[start_date, end_date]]},
                        fields=['name'],
                        limit_page_length=LIMIT)
    print(".",end="")
    paid_sinvs: list[str] = []
    paid_pinvs: list[str] = []
    sinvs_old: list[str] = []
    pinvs_old: list[str] = []
    for p1 in ps:
        p = Api.api.get_doc('Payment Entry',p1['name'])
        for r in p['references']:
            if r['reference_doctype'] == 'Sales Invoice':
                paid_sinvs.append(r['reference_name'])
            if r['reference_doctype'] == 'Purchase Invoice':
                paid_pinvs.append(r['reference_name'])
    print(".",end="")
    for sinv in set(paid_sinvs):
        if sinv in sinvs:
            sinvs.remove(sinv)
        else:
            sinvs_old.append(sinv)        
    print(".",end="")
    for pinv in set(paid_pinvs):
        if pinv in pinvs:
            pinvs.remove(pinv)
        else:
            pinvs_old.append(pinv)
    # dump purchase invoices
    print(".",end="")
    for inv in pinvs + pinvs_old:
        print(".",end="")
        inv1 = Api.api.get_doc("Purchase Invoice",inv)
        pdf = inv1.get('supplier_invoice')
        if pdf:
            contents = Api.api.get_file(pdf)
            with open(inv+".pdf","wb") as f:
                f.write(contents)
    print(".")
    print("Verkaufsrechnungen aus {} oder {}, die {} bezahlt wurden: {}".format(year-1,year+1,year,', '.join(sinvs_old)))
    print("Einkaufsrechnungen aus {} oder {}, die {} bezahlt wurden: {}".format(year-1,year+1,year,', '.join(pinvs_old)))
    print("Verkaufsrechnungen aus {}, die {} bezahlt wurden: {}".format(year,year+1,', '.join(sinvs)))
    print("Einkaufsrechnungen aus {}, die {} bezahlt wurden: {}".format(year,year+1,', '.join(pinvs)))
    return (sinvs,sinvs_old,pinvs,pinvs_old)
