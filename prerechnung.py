import json
import os
import PySimpleGUI as sg

import purchase_invoice
from api import Api, LIMIT

from google.cloud import documentai_v1beta3 as documentai
from google.api_core.client_options import ClientOptions


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
    entities = []
    for entity in document.entities:
        props = []
        for prop in entity.properties:
            props.append({
                "value": prop.normalized_value.text or prop.text_anchor.content or prop.mention_text,
                "type": prop.type_,
                "confidence": prop.confidence,
            })
        entities.append(
            {
                "value": entity.normalized_value.text or entity.text_anchor.content or entity.mention_text,
                "type": entity.type_,
                "properties": props,
                "confidence": entity.confidence,
            }
        )
    # Return the results as a dictionary
    return {"document_text": text, "entities": entities}


def process_inv(pr):
    print(pr['name'])
    pdf = pr['pdf']
    contents = Api.api.get_file(pdf)
    if sg.UserSettings().get('-google-credentials-'):
        pr['json'] = json.dumps(extract_invoice_info(contents))
        # todo: set pr['betrag'] to gross total, pr['auftragsnr']
    else:
        inv = purchase_invoice.PurchaseInvoice(pr['lager'])
        tmpfile = "/tmp/r.pdf"
        with open(tmpfile, "wb") as f:
            f.write(contents)
        try:
            inv.parse_invoice(tmpfile, account=pr['buchungskonto'],
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
    prs = Api.api.get_list("PreRechnung",filters={'company':company_name,
                                                  'vom_konto_überwiesen':False,
                                                  'zu_zahlen_am':['>','01-01-1980']},
                           limit_page_length=LIMIT)
    prs.sort(key=lambda pr : pr['zu_zahlen_am'])
    sum = 0.0
    for pr in prs:
        sum += pr['betrag']
        pr['summe'] = sum
    return prs
