from api import Api
from api_wrapper import gui_api_wrapper

class Doc:
    # beware: do not call __init__ until there is a doc in ERPNext
    def __init__(self,name=None,doc=None,doctype=None):
        self.erpnext = False
        if doctype:
            self.doctype = doctype
        if name:
            self.name = name
            if self.load():
                self.erpnext = True
        elif doc:
            self.doc = doc
            self.name = doc['name']
            if doctype:
                self.doc['doctype'] = doctype
            if self.name:
                self.erpnext = True
    def insert(self):
        doc = gui_api_wrapper(Api.api.insert,self.doc)
        if not doc:
            return None
        Doc.__init__(self,doc=doc)
        return self.doc
    def load(self):
        self.doc = gui_api_wrapper(Api.api.get_doc,self.doctype,self.name)
        return self.doc
    def submit(self):
        #self.load()
        self.doc = gui_api_wrapper(Api.api.submit,self.doc)
    def update(self):
        self.doc = gui_api_wrapper(Api.api.update,self.doc)
