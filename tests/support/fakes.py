"""In-Memory-Nachbildung des Frappe-REST-Clients für Offline-Tests.

``FakeFrappeClient`` hat dieselbe Schnittstelle wie :class:`frappeclient.FrappeClient`
und hält Dokumente pro DocType in einem dict. Nachgebildet wird bewusst nur, was der
Client tatsächlich braucht - aber diese Punkte möglichst so, wie sich ein echter
Frappe-Server verhält, damit Tests reale Fehler finden:

* ``get_list`` liefert NUR die angeforderten Felder (Standard: ``name``) und
  ohne ``limit_page_length`` höchstens 20 Datensätze (Frappe-Default).
* Kindtabellen-Felder (``\\`tabJournal Entry Account\\`.account as account``)
  ergeben wie beim LEFT JOIN eine Zeile pro Kindzeile.
* ``insert`` berechnet die serverseitigen Felder (Summen, Status, Name),
  ``delete`` verweigert gebuchte Dokumente, unausgeglichene Buchungssätze
  werden abgelehnt.

``FakeSession``/``FakeResponse`` bilden ``requests`` nach, um den echten
``FrappeClient`` ohne Netz zu testen.
"""
import copy
import datetime
import io
import json
import os
import re
import urllib.parse

import frappe
from frappeclient import FrappeException

# Kind-DocType -> Feldname der Kindtabelle im Elterndokument
CHILD_TABLES = {
    "Journal Entry Account": "accounts",
    "Purchase Invoice Item": "items",
    "Sales Invoice Item": "items",
    "Sales Order Item": "items",
    "Stock Entry Detail": "items",
    "Item Supplier": "supplier_items",
    "Item Default": "item_defaults",
    "Bank Transaction Payments": "payment_entries",
    "Purchase Taxes and Charges": "taxes",
    "Sales Taxes and Charges": "taxes",
    "Payment Entry Reference": "references",
}

# Namensvergabe pro DocType (Frappe-Namensserien nachgebildet)
NAME_SERIES = {
    "Purchase Invoice": "EK {year}-{n:05d}",
    "Sales Invoice": "R {year}-{n:05d}",
    "Journal Entry": "ACC-JV-{year}-{n:05d}",
    "Payment Entry": "ACC-PAY-{year}-{n:05d}",
    "Bank Transaction": "ACC-BTN-{year}-{n:05d}",
    "Stock Entry": "MAT-STE-{year}-{n:05d}",
    "Stock Reconciliation": "MAT-RECO-{year}-{n:05d}",
    "PreRechnung": "PreR{n:05d}",
    "Project": "PROJ-{n:04d}",
    "Lead": "CRM-LEAD-{year}-{n:05d}",
    "File": "file{n:08x}",
}

# DocTypes, deren Name aus einem Feld gebildet wird
NATURAL_KEYS = {
    "Supplier": "supplier_name",
    "Customer": "customer_name",
    "Item": "item_code",
    "Company": "company_name",
    "Item Group": "item_group_name",
    "Supplier Group": "supplier_group_name",
    "Warehouse": "warehouse_name",
    "Price List": "price_list_name",
    "Account": "account_name",
    "Bank Account": "account_name",
    "User": "email",
}

CHILD_META = ("idx", "parent", "parenttype", "parentfield", "doctype")


def _sql_like(pattern, value):
    if pattern is None:
        return value in (None, "")
    if value is None:
        return False
    regex = re.escape(str(pattern)).replace("%", ".*").replace("_", ".")
    return re.fullmatch(regex, str(value), re.IGNORECASE) is not None


def _matches(value, op, target):
    op = op.lower()
    if op in ("=", "=="):
        return value == target
    if op == "!=":
        return value != target
    if op in ("in",):
        return value in (target or [])
    if op == "not in":
        return value not in (target or [])
    if op == "like":
        return _sql_like(target, value)
    if op == "not like":
        return not _sql_like(target, value)
    if op == "is":
        is_set = value not in (None, "", [], 0) if isinstance(value, (list, str, type(None))) else value is not None
        if target == "set":
            return value not in (None, "")
        return value in (None, "")
    if op == "between":
        if value is None:
            return False
        return target[0] <= value <= target[1]
    if value is None:
        return False
    if op == ">":
        return value > target
    if op == "<":
        return value < target
    if op == ">=":
        return value >= target
    if op == "<=":
        return value <= target
    raise ValueError("Unbekannter Filter-Operator {!r}".format(op))


def _parse_fields(fields):
    """Liefert (Elternfelder, [(kind_doctype, feld, alias)])."""
    if fields is None:
        fields = ["name"]
    if isinstance(fields, str):
        fields = json.loads(fields)
    parent_fields, child_fields = [], []
    for f in fields:
        m = re.match(r"`tab(.+?)`\.(\w+)(?:\s+as\s+(\w+))?$", f.strip())
        if m:
            child_fields.append((m.group(1), m.group(2), m.group(3) or m.group(2)))
        else:
            m2 = re.match(r"(\w+)\s+as\s+(\w+)$", f.strip())
            if m2:
                parent_fields.append((m2.group(1), m2.group(2)))
            else:
                parent_fields.append((f.strip(), f.strip()))
    return parent_fields, child_fields


class FakeFrappeClient:
    DEFAULT_PAGE_LENGTH = 20

    def __init__(self, url="https://fake.example", api_key=None, api_secret=None, **kwargs):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.store = {}          # doctype -> {name: doc}
        self.counters = {}
        self.calls = []          # (methode, args, kwargs)
        self.files = {}          # file_url -> bytes
        self.attachments = []    # (doctype, docname, file_url)
        self.report_handlers = {}  # lower(report_name) -> callable(filters)
        self.versions = {}       # docname -> [version dicts] für load_doc
        self.communications = {}  # docname -> [comm dicts]
        self.assignments = []
        self.background_jobs = []
        self.year = datetime.date.today().year

    # ------------------------------------------------------------ Hilfen
    def _log(self, method, *args, **kwargs):
        self.calls.append((method, args, kwargs))

    def calls_of(self, method):
        return [c for c in self.calls if c[0] == method]

    def docs(self, doctype):
        return self.store.setdefault(doctype, {})

    def add(self, doctype, **fields):
        """Dokument direkt (ohne Server-Logik) ablegen; liefert den Namen."""
        doc = dict(fields)
        doc["doctype"] = doctype
        doc.setdefault("docstatus", 0)
        if "name" not in doc:
            doc["name"] = self._new_name(doctype, doc)
        self._defaults(doc)
        self.docs(doctype)[doc["name"]] = doc
        return doc["name"]

    def add_file(self, file_url, content):
        self.files[file_url] = content
        return file_url

    def set_report(self, report_name, handler_or_result):
        self.report_handlers[report_name.lower()] = handler_or_result

    def _new_name(self, doctype, doc):
        key = NATURAL_KEYS.get(doctype)
        if key and doc.get(key):
            return doc[key]
        n = self.counters.get(doctype, 0) + 1
        self.counters[doctype] = n
        pattern = NAME_SERIES.get(doctype, doctype.replace(" ", "-").upper() + "-{n:05d}")
        return pattern.format(year=self.year, n=n)

    def _number_children(self, doc):
        for field, value in doc.items():
            if isinstance(value, list):
                for i, row in enumerate(value):
                    if isinstance(row, dict):
                        row.setdefault("idx", i + 1)
                        row.setdefault("parent", doc.get("name"))
                        row.setdefault("parenttype", doc.get("doctype"))
                        row.setdefault("parentfield", field)

    def _get(self, doctype, name):
        docs = self.docs(doctype)
        if name not in docs:
            raise FrappeException("FrappeClient Request Failed\n\n{} {} not found (DoesNotExistError)".format(doctype, name))
        return docs[name]

    # ----------------------------------------------- Server-Seiteneffekte
    def _defaults(self, doc):
        """Feld-Defaults, wie sie Frappe beim Anlegen setzt (nur fehlende Felder)."""
        doctype = doc["doctype"]
        doc.setdefault("docstatus", 0)
        doc.setdefault("owner", "test@example.com")
        doc.setdefault("creation", datetime.datetime.now().isoformat(sep=" ", timespec="seconds"))
        doc["modified"] = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        if doctype in ("Purchase Invoice", "Sales Invoice"):
            doc.setdefault("status", "Draft")
            doc.setdefault("is_return", 0)
            doc.setdefault("items", [])
            doc.setdefault("taxes", [])
            doc.setdefault("title", doc.get("supplier") or doc.get("customer") or doc["name"])
        elif doctype == "Journal Entry":
            doc.setdefault("status", "Draft")
            doc.setdefault("accounts", [])
        elif doctype == "Payment Entry":
            doc.setdefault("status", "Draft")
            doc.setdefault("references", [])
        elif doctype == "Bank Transaction":
            if not doc.get("company") and doc.get("bank_account") in self.docs("Bank Account"):
                doc["company"] = self.docs("Bank Account")[doc["bank_account"]].get("company")
            doc.setdefault("status", "Pending")
            doc.setdefault("allocated_amount", 0.0)
            doc.setdefault("deposit", 0.0)
            doc.setdefault("withdrawal", 0.0)
            doc.setdefault("unallocated_amount", doc["deposit"] or doc["withdrawal"])
            doc.setdefault("payment_entries", [])
        elif doctype == "Item":
            doc.setdefault("disabled", 0)
            doc.setdefault("supplier_items", [])
            doc.setdefault("item_defaults", [])
            doc.setdefault("item_name", doc.get("item_code"))
        elif doctype == "Supplier":
            doc.setdefault("supplier_group", None)
        self._number_children(doc)

    def _compute(self, doc):
        """Berechnete Felder und Validierungen, wie sie der Server bei insert/update ausführt."""
        doctype = doc["doctype"]
        if doctype in ("Purchase Invoice", "Sales Invoice"):
            total = 0.0
            for item in doc.get("items", []):
                item.setdefault("qty", 1)
                item.setdefault("rate", 0.0)
                item["amount"] = round(item["qty"] * item["rate"], 2)
                total += item["amount"]
            taxes = sum(t.get("tax_amount", 0.0) for t in doc.get("taxes", []))
            grand = round(total + taxes, 2)
            if doc.get("apply_discount_on") == "Grand Total" and doc.get("discount_amount"):
                grand = round(grand - doc["discount_amount"], 2)
            doc["total"] = round(total, 2)
            doc["net_total"] = round(total, 2)
            doc["total_taxes_and_charges"] = round(taxes, 2)
            doc["grand_total"] = grand
            doc["base_grand_total"] = grand
            doc["rounded_total"] = round(grand)
            if doc["docstatus"] == 0:
                doc["outstanding_amount"] = grand
        elif doctype == "Journal Entry":
            debit = round(sum(a.get("debit", 0.0) or 0.0 for a in doc.get("accounts", [])), 2)
            credit = round(sum(a.get("credit", 0.0) or 0.0 for a in doc.get("accounts", [])), 2)
            if abs(debit - credit) > 0.005:
                raise FrappeException("FrappeClient Request Failed\n\nTotal Debit must be equal to Total Credit. "
                                      "The difference is {}".format(round(debit - credit, 2)))
            doc["total_debit"] = debit
            doc["total_credit"] = credit
        elif doctype == "Payment Entry":
            paid = doc.get("paid_amount", 0.0)
            allocated = sum(r.get("allocated_amount", 0.0) for r in doc.get("references", []))
            doc["unallocated_amount"] = round(paid - allocated, 2)

    def _server_side(self, doc):
        self._defaults(doc)
        self._compute(doc)
        self._number_children(doc)

    # ----------------------------------------------------------- Abfragen
    def _filter(self, doctype, docs, filters):
        if not filters:
            return docs
        if isinstance(filters, str):
            filters = json.loads(filters)
        if isinstance(filters, dict):
            conds = []
            for key, cond in filters.items():
                if isinstance(cond, (list, tuple)):
                    conds.append((doctype, key, cond[0], cond[1]))
                else:
                    conds.append((doctype, key, "=", cond))
        else:
            conds = []
            for cond in filters:
                if len(cond) == 4:
                    conds.append(tuple(cond))
                elif len(cond) == 3:
                    conds.append((doctype, cond[0], cond[1], cond[2]))
                else:
                    raise ValueError("Filter nicht verstanden: {!r}".format(cond))
        result = []
        for doc in docs:
            ok = True
            for dt, field, op, target in conds:
                if dt == doctype:
                    value = doc.get(field, 0 if field == "docstatus" else None)
                    if not _matches(value, op, target):
                        ok = False
                        break
                else:
                    rows = doc.get(CHILD_TABLES.get(dt, ""), []) or []
                    if not any(_matches(row.get(field), op, target) for row in rows):
                        ok = False
                        break
            if ok:
                result.append(doc)
        return result

    @staticmethod
    def _order(docs, order_by):
        if not order_by:
            return docs
        parts = [p.strip() for p in order_by.split(",") if p.strip()]
        for part in reversed(parts):
            tokens = part.split()
            field = tokens[0].strip("`")
            if "." in field:
                field = field.split(".")[-1].strip("`")
            desc = len(tokens) > 1 and tokens[1].lower() == "desc"
            docs = sorted(docs, key=lambda d: (d.get(field) is None, d.get(field) if d.get(field) is not None else ""),
                          reverse=desc)
        return docs

    def get_list(self, doctype, fields='["name"]', filters=None, limit_start=0, limit_page_length=None,
                 order_by=None):
        self._log("get_list", doctype, fields=fields, filters=filters, limit_start=limit_start,
                  limit_page_length=limit_page_length, order_by=order_by)
        docs = list(self.docs(doctype).values())
        docs = self._filter(doctype, docs, filters)
        docs = self._order(docs, order_by)
        parent_fields, child_fields = _parse_fields(fields)
        rows = []
        for doc in docs:
            base = {}
            for field, alias in parent_fields:
                if field == "*":
                    base.update(copy.deepcopy(doc))
                else:
                    base[alias] = copy.deepcopy(doc.get(field, 0 if field == "docstatus" else None))
            if child_fields:
                child_rows = []
                for child_dt, field, alias in child_fields:
                    table = CHILD_TABLES.get(child_dt)
                    child_rows = doc.get(table, []) or []
                    break
                if not child_rows:
                    row = dict(base)
                    for _, _, alias in child_fields:
                        row[alias] = None
                    rows.append(row)
                else:
                    for child in child_rows:
                        row = dict(base)
                        for _, field, alias in child_fields:
                            row[alias] = copy.deepcopy(child.get(field))
                        rows.append(row)
            else:
                rows.append(base)
        length = limit_page_length if limit_page_length is not None else self.DEFAULT_PAGE_LENGTH
        return rows[limit_start:limit_start + length]

    def get_doc(self, doctype, name="", filters=None, fields=None):
        self._log("get_doc", doctype, name)
        name = urllib.parse.unquote(str(name))
        if not name:
            docs = self._filter(doctype, list(self.docs(doctype).values()), filters)
            return [copy.deepcopy(d) for d in docs]
        return copy.deepcopy(self._get(doctype, name))

    def load_doc(self, doctype, name=""):
        self._log("load_doc", doctype, name)
        doc = copy.deepcopy(self._get(doctype, name))
        return {"docs": [doc],
                "docinfo": {"versions": copy.deepcopy(self.versions.get(name, [])),
                            "communications": copy.deepcopy(self.communications.get(name, []))}}

    def get_value(self, doctype, fieldname=None, filters=None):
        self._log("get_value", doctype, fieldname, filters)
        docs = self._filter(doctype, list(self.docs(doctype).values()), filters)
        if not docs:
            return None
        fieldname = fieldname or "name"
        return {fieldname: docs[0].get(fieldname)}

    def reportview_get(self, doctype, filters=None, fields=None, params=None):
        self._log("reportview_get", doctype, filters, fields)
        rows = self.get_list(doctype, fields=fields or ["name"], filters=filters,
                             limit_page_length=(params or {}).get("page_length"))
        keys = list(rows[0].keys()) if rows else []
        return {"keys": keys, "values": [[r[k] for k in keys] for r in rows]}

    # ---------------------------------------------------------- Änderungen
    def insert(self, doc):
        self._log("insert", copy.deepcopy(doc))
        doc = copy.deepcopy(dict(doc))
        doctype = doc.get("doctype")
        if not doctype:
            raise FrappeException("FrappeClient Request Failed\n\nDocType None not found")
        if not doc.get("name"):
            doc["name"] = self._new_name(doctype, doc)
        if doc["name"] in self.docs(doctype):
            raise FrappeException("FrappeClient Request Failed\n\nDuplicateEntryError: {} {}".format(doctype, doc["name"]))
        self._server_side(doc)
        self.docs(doctype)[doc["name"]] = doc
        return frappe._dict(copy.deepcopy(doc))

    def insert_many(self, docs):
        return [self.insert(d)["name"] for d in docs]

    def update(self, doc):
        self._log("update", copy.deepcopy(doc))
        doctype = doc.get("doctype")
        if not doctype:
            raise FrappeException("FrappeClient Request Failed\n\nDocType None not found")
        stored = self._get(doctype, frappe.cstr(doc.get("name")))
        if stored.get("docstatus", 0) == 1:
            allowed = {"name", "doctype", "docstatus", "modified", "supplier_invoice", "last_integration_date",
                       "status", "payment_entries", "allocated_amount", "unallocated_amount", "_assign"}
            changed = {k for k, v in doc.items() if stored.get(k) != v}
            if changed - allowed:
                raise FrappeException("FrappeClient Request Failed\n\nUpdateAfterSubmitError: {}".format(sorted(changed - allowed)))
        stored.update(copy.deepcopy(dict(doc)))
        if doctype in ("Purchase Invoice", "Sales Invoice", "Journal Entry", "Payment Entry"):
            self._server_side(stored)
        else:
            self._number_children(stored)
        return frappe._dict(copy.deepcopy(stored))

    def update_with_doctype(self, doc, doctype):
        doc1 = dict(doc)
        doc1["doctype"] = doctype
        return self.update(doc1)

    def bulk_update(self, docs):
        return [self.update(d) for d in docs]

    def set_value(self, doctype, docname, fieldname, value):
        self._log("set_value", doctype, docname, fieldname, value)
        stored = self._get(doctype, docname)
        stored[fieldname] = value
        return copy.deepcopy(stored)

    def delete(self, doctype, name):
        self._log("delete", doctype, name)
        stored = self._get(doctype, name)
        if stored.get("docstatus", 0) == 1:
            raise FrappeException("FrappeClient Request Failed\n\nCannot delete submitted document {} {}".format(doctype, name))
        del self.docs(doctype)[name]
        return "ok"

    def submit(self, doc):
        self._log("submit", copy.deepcopy(doc))
        stored = self._get(doc["doctype"], doc["name"])
        if stored.get("docstatus", 0) != 0:
            raise FrappeException("FrappeClient Request Failed\n\nCannot submit document with docstatus {}".format(stored["docstatus"]))
        stored["docstatus"] = 1
        if doc["doctype"] in ("Purchase Invoice", "Sales Invoice"):
            stored["status"] = "Unpaid" if stored.get("outstanding_amount") else "Paid"
        elif doc["doctype"] == "Bank Transaction":
            stored["status"] = stored.get("status", "Pending")
        else:
            stored["status"] = "Submitted"
        return copy.deepcopy(stored)

    def cancel(self, doctype, name):
        self._log("cancel", doctype, name)
        stored = self._get(doctype, name)
        stored["docstatus"] = 2
        stored["status"] = "Cancelled"
        return copy.deepcopy(stored)

    def rename_doc(self, doctype, old_name, new_name):
        stored = self._get(doctype, old_name)
        del self.docs(doctype)[old_name]
        stored["name"] = new_name
        self.docs(doctype)[new_name] = stored
        return new_name

    # -------------------------------------------------------- Dateien etc.
    def get_file(self, path):
        self._log("get_file", path)
        if path not in self.files:
            raise FrappeException("FrappeClient Request Failed\n\nFile {} not found".format(path))
        return self.files[path]

    def attach_file(self, doctype, docname, filename, filedata, is_private):
        self._log("attach_file", doctype, docname, filename, is_private)
        self._get(doctype, docname)
        file_url = ("/private/files/" if is_private else "/files/") + filename
        self.files[file_url] = filedata
        self.attachments.append((doctype, docname, file_url))
        file_doc = {"doctype": "File", "file_name": filename, "file_url": file_url,
                    "attached_to_doctype": doctype, "attached_to_name": docname,
                    "is_private": 1 if is_private else 0}
        file_doc["name"] = self._new_name("File", file_doc)
        self.docs("File")[file_doc["name"]] = file_doc
        return frappe._dict(copy.deepcopy(file_doc))

    def read_and_attach_file(self, doctype, docname, filename, is_private):
        with open(filename, "rb") as f:
            data = f.read()
        return self.attach_file(doctype, docname, os.path.basename(filename), data, is_private)

    def get_pdf(self, doctype, name, print_format="Standard", letterhead=True, language="de"):
        self._log("get_pdf", doctype, name, print_format)
        self._get(doctype, name)
        return io.BytesIO(b"%PDF-1.4\n% fake pdf for " + name.encode() + b"\n")

    def get_html(self, doctype, name, print_format="Standard", letterhead=True):
        return io.BytesIO(b"<html>fake</html>")

    def get_attachments(self, doctype, name):
        return [a[2] for a in self.attachments if a[0] == doctype and a[1] == name]

    def query_report(self, report_name="", filters=None):
        self._log("query_report", report_name, filters)
        handler = self.report_handlers.get(report_name.lower())
        if handler is None:
            raise FrappeException("FrappeClient Request Failed\n\nReport {} not found".format(report_name))
        if callable(handler):
            return copy.deepcopy(handler(filters or {}))
        return copy.deepcopy(handler)

    def assign_to(self, doctype, name, assign_to):
        self._log("assign_to", doctype, name, assign_to)
        stored = self._get(doctype, name)
        stored["_assign"] = json.dumps(list(assign_to))
        self.assignments.append((doctype, name, list(assign_to)))
        return stored["_assign"]

    def get_background_jobs(self):
        self._log("get_background_jobs")
        return list(self.background_jobs)

    def get_open_activities(self, doctype, name):
        return {"open_activities": []}

    def get_unreconciled_entries(self, name):
        return {}

    def get_api(self, method, params=None):
        self._log("get_api", method, params)
        return None

    def post_api(self, method, params=None):
        self._log("post_api", method, params)
        return None

    def logout(self):
        pass


# ------------------------------------------------ requests-Nachbildung
class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=None, ok=None, content=b""):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")
        self.ok = ok if ok is not None else status_code < 400
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON")
        return self._payload

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]


class FakeSession:
    """Zeichnet Requests auf und liefert vorbereitete Antworten (FIFO)."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []   # (methode, url, kwargs)

    def _pop(self, method, url, kwargs):
        self.requests.append((method, url, kwargs))
        if not self.responses:
            return FakeResponse({"data": []})
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def get(self, url, **kwargs):
        return self._pop("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._pop("POST", url, kwargs)

    def put(self, url, **kwargs):
        return self._pop("PUT", url, kwargs)
