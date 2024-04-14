from api import Api
from doc import Doc
import payment
import company

class Invoice(Doc):
    def __init__(self,doc,is_sales):
        self.doctype = 'Sales Invoice' if is_sales else 'Purchase Invoice'
        super().__init__(doc=doc)
        self.is_sales = is_sales
        self.company_name = doc['company']
        self.date = doc['posting_date']
        self.status = doc['status']
        self.amount = doc['grand_total']
        self.outstanding = doc['outstanding_amount']
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
            
    def payment_from_bank_transaction(self,bt):
        print("Erstelle und buche Zahlung")
        p = bt.payment(self)
        if p:
            Api.submit_doc('Payment Entry',p['name'])
            
    def payment(self,account,amount,date):
        ref = self.reference if self.reference else ""
        references =  \
            [{'reference_doctype' : 'Sales Invoice' if self.is_sales else 'Purchase Invoice',
              'reference_name' : self.name,
              'allocated_amount' : amount}]
        comp = company.Company.get_company(self.company_name)
        return payment.create_payment(self.is_sales,comp,account,
                                      amount,date,self.party,self.party_type,
                                      ref,references)
    
    def use_advance_payment(self,py):
        print("Verwende Anzahlung")
        advance =\
            {'reference_type': 'Payment Entry',
             'reference_name': py.name,
             'remarks': py.doc['remarks'],
             'advance_amount': py.doc['paid_amount'],
             'allocated_amount': py.doc['paid_amount']}
        self.doc['advances'] = [advance]
        self.update()


