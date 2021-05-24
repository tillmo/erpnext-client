from api import Api
from doc import Doc

class Invoice(Doc):
    def __init__(self,doc,is_sales):
        self.doctype = 'Sales Invoice' if is_sales else 'Purchase Invoice'
        super().__init__(doc=doc)
        self.is_sales = is_sales
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
    def payment(self,bt):
        print("Erstelle und buche Zahlung")
        p = bt.payment(self)
        if p:
            Api.submit_doc('Payment Entry',p['name'])

