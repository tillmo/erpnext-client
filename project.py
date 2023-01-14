import stock
from api import Api
from api_wrapper import gui_api_wrapper
from settings import STOCK_PROJECT_TYPES

def complete_project(pname):
    # close project
    doc = Api.api.get_doc("Project",pname)
    doc['status'] = 'Completed'
    gui_api_wrapper(Api.api.update,doc)
    if is_stock(doc):
        # withdraw material from stock
        stock.project_into_stock(pname,qty=0)

def is_stock(doc):
    return 'project_type' in doc and doc['project_type'] in STOCK_PROJECT_TYPES



