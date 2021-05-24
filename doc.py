from api import Api

class Doc:
    # beware: do not call __init__ until there is a doc in ERPNext
    def __init__(self,name=None,doc=None):
        self.erpnext = False
        if name:
            self.name = name
            if self.load():
                self.erpnext = True
        elif doc:
            self.doc = doc
            self.name = doc['name']
            if self.name:
                self.erpnext = True
    def insert(self):
        doc = gui_api_wrapper(Api.api.insert,self.doc)
        if not doc:
            return None
        self.__init__(doc=doc)
        return self.doc
    def load(self):
        self.doc = gui_api_wrapper(Api.api.get_doc,self.doctype,self.name)
        return self.doc
    def submit(self):
        #self.load()
        self.doc = gui_api_wrapper(Api.api.submit,self.doc)
    def update(self):
        self.doc = gui_api_wrapper(Api.api.update,self.doc)
