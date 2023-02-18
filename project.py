import stock
from api import Api
from api_wrapper import gui_api_wrapper
from settings import LUMP_SUM_STOCK_PROJECT_TYPES

def complete_project(pname):
    # close project
    doc = Api.api.get_doc("Project",pname)
    doc['status'] = 'Completed'
    gui_api_wrapper(Api.api.update,doc)
    if is_stock(doc):
        # withdraw material from stock
        stock.project_into_stock(pname,False)

def is_stock(doc):
    return 'project_type' in doc and doc['project_type'] in LUMP_SUM_STOCK_PROJECT_TYPES

def project_type(pname):
    doc = Api.api.get_doc("Project",pname)
    return doc['project_type']




