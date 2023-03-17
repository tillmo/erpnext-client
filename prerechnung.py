import json
import os

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
    project_id = "quantum-idiom-379621"
    processor_id = "b9f742465e96697"
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

    # For a full list of Document object attributes, please reference this page:
    # https://googleapis.dev/python/documentai/latest/_modules/google/cloud/documentai_v1beta3/types/document.html#Document
    document_pages = document.pages

    # Read the text recognition output from the processor
    text = document.text

    # Get the entities from the document
    entities = []
    for entity in document.entities:
        entities.append(
            {
                "content": entity.text_anchor.content,
                "type": entity.type_,
                "confidence": entity.confidence,
            }
        )
    # Return the results as a dictionary
    return {"document_text": text, "entities": entities}


def process_inv(pr):
    print(pr['name'])
    pdf = pr['pdf']
    contents = Api.api.get_file(pdf)
    pr['json'] = json.dumps(extract_invoice_info(contents))
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
