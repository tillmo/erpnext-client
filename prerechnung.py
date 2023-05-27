import json
import os
import pdb

import PySimpleGUI as sg
import utils
import project
import doc
import settings
import purchase_invoice
from purchase_invoice import get_element_with_high_confidence
from api import Api, LIMIT
import json
import traceback

from google.cloud import documentai_v1beta3 as documentai
from google.api_core.client_options import ClientOptions


ENTITIES_DATA_SCHEMA = {
    "title": "Entities format",
    "required": ["total_amount"],
    "type": "object",
    "properties": {
        "supplier": {"type": "string"},
        "supplier_address": {"type": "string"},
        "bill_no": {"type": "string"},
        "order_id": {"type": "string"},
        "due_date": {"type": "string"},
        "posting_date": {"type": "string"},
        "ship_to_address": {"type": "string"},
        "net_amount": {"type": "string"},
        "total_tax_amount": {"type": "string"},
        "total_amount": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "required": ["item-description", "item-amount"],
                "type": "object",
                "properties": {
                    "item-pos": {"type": "string"},
                    "item-code": {"type": "string"},
                    "item-description": {"type": "string"},
                    "item-quantity": {"type": "string"},
                    "item-unit-price": {"type": "string"},
                    "item-amount": {"type": "string"},
                }
            },
            "minItems": 1,
        },
    }
}


def process(company_name):
    prs = Api.api.get_list(
        "PreRechnung",
        filters={'company': company_name, 'processed': False},
        limit_page_length=LIMIT
    )
    for pr in prs:
        process_inv(pr)
    print("Prerechnungen vorprozessiert")


def extract_invoice_info(pdf_file_content) -> dict:
    project_id = sg.UserSettings()['-google-credentials-']['project_id']
    processor_id = sg.UserSettings()['-invoice-processor-']
    location = "eu"
    mime_type = "application/pdf"

    # Instantiates a client
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'google-credentials.json'

    # Set endpoint to EU
    options = ClientOptions(api_endpoint="eu-documentai.googleapis.com")
    # Instantiates a client
    client = documentai.DocumentProcessorServiceClient(client_options=options)

    # The full resource name of the processor, e.g.:
    # projects/project-id/locations/location/processors/processor-id
    name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"

    # Construct a document object
    document = {"content": pdf_file_content, "mime_type": mime_type}

    # Configure the process request
    request = {"name": name, "document": document}

    # Use the Document AI API to process the document
    result = client.process_document(request=request)

    print("Document processing complete.")

    # Get all of the document text as one big string
    document = result.document

    # Read the text recognition output from the processor
    text = document.text

    # Get the entities from the document
    sub_entities = []
    for entity in document.entities:
        props = []
        for prop in entity.properties:
            if prop.confidence >= 0.2:
                props.append({
                    "value": prop.normalized_value.text or prop.text_anchor.content or prop.mention_text,
                    "type": prop.type_,
                    "confidence": prop.confidence,
                })
        if entity.type_ == "item" or entity.confidence >= 0.2:
            try:
                line_no = entity.text_anchor.text_segments[0].start_index
            except:
                line_no = 0
            sub_entities.append({
                "value": entity.normalized_value.text or entity.text_anchor.content or entity.mention_text,
                "type": entity.type_,
                "properties": props,
                "confidence": entity.confidence,
                "page_number": entity.page_anchor.page_refs[0].page,
                "line_number": line_no,
            })
    sub_entities = sorted(sub_entities, key=lambda x: (x['page_number'], x['line_number']))

    keys = []
    entities = []
    base_entity_info = {}
    for sub_entity in sub_entities:
        if sub_entity['type'] == 'item':
            prop_types = [d['type'] for d in sub_entity['properties']]
            if set(keys) & set(prop_types):
                entities.append(base_entity_info)
                keys = []
                base_entity_info = {}
            keys.extend(prop_types)
            if not base_entity_info.keys():
                base_entity_info = sub_entity
            else:
                base_entity_info['properties'].extend(sub_entity['properties'])
        else:
            entities.append(sub_entity)

    # Return the results as a dictionary
    return {"document_text": text, "entities": entities}


def process_inv(pr):
    print(pr['name'])
    pdf = pr['pdf']
    contents = Api.api.get_file(pdf)
    if sg.UserSettings().get('-google-credentials-'):
        try:
            pr['json'] = json.dumps(extract_invoice_info(contents))
            myjson = json.loads(pr['json'])    
            pr['auftragsnr'] = get_element_with_high_confidence(myjson, 'order_id')
            pr['betrag'] = get_element_with_high_confidence(myjson, 'total_amount')
            pr['processed'] = True
            pr['doctype'] = 'PreRechnung'
            Api.api.update(pr)
        except Exception as e:
            print(str(e)+"\n"+traceback.format_exc())
    else:
        inv = purchase_invoice.PurchaseInvoice(pr['lager'])
        tmpfile = "/tmp/r.pdf"
        with open(tmpfile, "wb") as f:
            f.write(contents)
        try:
            inv.parse_invoice(None,tmpfile,
                              account=pr['buchungskonto'],
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


def to_pay(company_name):
    prs = Api.api.get_list("PreRechnung", filters={'company': company_name,
                                                   'vom_konto_überwiesen': False,
                                                   'zu_zahlen_am': ['>', '01-01-1980']},
                           limit_page_length=LIMIT)
    prs.sort(key=lambda pr: pr['zu_zahlen_am'])
    sum = 0.0
    for pr in prs:
        sum += pr['betrag']
        pr['summe'] = sum
    return prs


def read_and_transfer(inv, check_dup=True):
    print("Lese ein {} {}:".format(inv['name'], inv['pdf']))
    json_str = inv.get('json')
    json_object = None
    if json_str:
        json_object = json.loads(json_str)
    pdf = Api.api.get_file(inv['pdf'])
    f = utils.store_temp_file(pdf, ".pdf")
    if utils.running_linux():
        os.system("evince "+f+" &")
    update_stock = 'chance' in inv and inv['chance'] and \
                   project.project_type(inv['chance']) in settings.STOCK_PROJECT_TYPES
    pinv = purchase_invoice.PurchaseInvoice.read_and_transfer(
        json_object, f, update_stock,
        account=inv.get('buchungskonto'), paid_by_submitter=inv.get('selbst_bezahlt', False),
        project=inv.get('chance'), supplier=inv.get('lieferant'), check_dup=check_dup
    )
    if pinv and not inv.get('purchase_invoice'):
        inv['eingepflegt'] = True
        inv['purchase_invoice'] = pinv.doc['name']
        inv_doc = doc.Doc(doc=inv, doctype='PreRechnung')
        inv_doc.update()
    if f:
        os.remove(f)
    return pinv
