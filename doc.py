from __future__ import annotations

from typing import Any

from api import Api
from api_wrapper import gui_api_wrapper

class Doc:
    erpnext: bool
    doctype: str
    name: str | None
    doc: dict[str, Any] | None

    # beware: do not call __init__ until there is a doc in ERPNext
    def __init__(self, name: str | None = None, doc: dict[str, Any] | None = None,
                 doctype: str | None = None) -> None:
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
    def insert(self) -> dict[str, Any] | None:
        doc = gui_api_wrapper(Api.api.insert,self.doc)
        if not doc:
            return None
        Doc.__init__(self,doc=doc)
        return self.doc
    def load(self) -> dict[str, Any] | None:
        self.doc = gui_api_wrapper(Api.api.get_doc,self.doctype,self.name)
        return self.doc
    def submit(self) -> None:
        #self.load()
        self.doc = gui_api_wrapper(Api.api.submit,self.doc)
    def update(self) -> None:
        self.doc = gui_api_wrapper(Api.api.update,self.doc)
