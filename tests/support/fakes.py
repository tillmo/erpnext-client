"""In-memory replica of the Frappe REST client for offline tests.

``FakeFrappeClient`` has the same interface as :class:`frappeclient.FrappeClient`
and keeps documents per DocType in a dict. Deliberately, only what the client
actually needs is simulated - but those points as closely as possible to how a
real Frappe server behaves, so that tests find real errors:

* ``get_list`` returns ONLY the requested fields (default: ``name``) and,
  without ``limit_page_length``, at most 20 records (Frappe default).
* child table fields (``\\`tabJournal Entry Account\\`.account as account``)
  yield one row per child row, as with a LEFT JOIN.
* ``insert`` computes the server-side fields (totals, status, name),
  ``delete`` refuses submitted documents, unbalanced journal entries
  are rejected.

``FakeSession``/``FakeResponse`` simulate ``requests`` in order to test the real
``FrappeClient`` without a network.
"""
from __future__ import annotations

import copy
import datetime
import io
import json
import os
import re
import urllib.parse
from typing import Any, Iterable, Iterator

import frappe
from frappeclient import FrappeException

# child DocType -> field name of the child table in the parent document
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

# naming per DocType (simulating Frappe naming series)
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

# DocTypes whose name is formed from a field
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


def _sql_like(pattern: Any, value: Any) -> bool:
    if pattern is None:
        return value in (None, "")
    if value is None:
        return False
    regex = re.escape(str(pattern)).replace("%", ".*").replace("_", ".")
    return re.fullmatch(regex, str(value), re.IGNORECASE) is not None


def _matches(value: Any, op: str, target: Any) -> bool:
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


def _parse_fields(fields: str | list[str] | None) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Returns (parent fields, [(child_doctype, field, alias)])."""
    if fields is None:
        fields = ["name"]
    if isinstance(fields, str):
        fields = json.loads(fields)
    parent_fields: list[tuple[str, str]] = []
    child_fields: list[tuple[str, str, str]] = []
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

    def __init__(self, url: str = "https://fake.example", api_key: str | None = None, api_secret: str | None = None,
                 **kwargs: Any) -> None:
        self.url: str = url
        self.api_key: str | None = api_key
        self.api_secret: str | None = api_secret
        self.store: dict[str, dict[str, dict[str, Any]]] = {}          # doctype -> {name: doc}
        self.counters: dict[str, int] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []          # (method, args, kwargs)
        self.files: dict[str, bytes] = {}          # file_url -> bytes
        self.attachments: list[tuple[str, str, str]] = []    # (doctype, docname, file_url)
        self.report_handlers: dict[str, Any] = {}  # lower(report_name) -> callable(filters)
        self.versions: dict[str, list[dict[str, Any]]] = {}       # docname -> [version dicts] for load_doc
        self.communications: dict[str, list[dict[str, Any]]] = {}  # docname -> [comm dicts]
        self.assignments: list[tuple[str, str, list[str]]] = []
        self.background_jobs: list[Any] = []
        self.year: int = datetime.date.today().year

    # ----------------------------------------------------------- Helpers
    def _log(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, args, kwargs))

    def calls_of(self, method: str) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
        return [c for c in self.calls if c[0] == method]

    def docs(self, doctype: str) -> dict[str, dict[str, Any]]:
        return self.store.setdefault(doctype, {})

    def add(self, doctype: str, **fields: Any) -> str:
        """Store a document directly (without server logic); returns the name."""
        doc = dict(fields)
        doc["doctype"] = doctype
        doc.setdefault("docstatus", 0)
        if "name" not in doc:
            doc["name"] = self._new_name(doctype, doc)
        self._defaults(doc)
        self.docs(doctype)[doc["name"]] = doc
        return doc["name"]

    def add_file(self, file_url: str, content: bytes) -> str:
        self.files[file_url] = content
        return file_url

    def set_report(self, report_name: str, handler_or_result: Any) -> None:
        self.report_handlers[report_name.lower()] = handler_or_result

    def _new_name(self, doctype: str, doc: dict[str, Any]) -> str:
        key = NATURAL_KEYS.get(doctype)
        if key and doc.get(key):
            return doc[key]
        n = self.counters.get(doctype, 0) + 1
        self.counters[doctype] = n
        pattern = NAME_SERIES.get(doctype, doctype.replace(" ", "-").upper() + "-{n:05d}")
        return pattern.format(year=self.year, n=n)

    def _number_children(self, doc: dict[str, Any]) -> None:
        for field, value in doc.items():
            if isinstance(value, list):
                for i, row in enumerate(value):
                    if isinstance(row, dict):
                        row.setdefault("idx", i + 1)
                        row.setdefault("parent", doc.get("name"))
                        row.setdefault("parenttype", doc.get("doctype"))
                        row.setdefault("parentfield", field)

    def _get(self, doctype: str, name: str) -> dict[str, Any]:
        docs = self.docs(doctype)
        if name not in docs:
            raise FrappeException("FrappeClient Request Failed\n\n{} {} not found (DoesNotExistError)".format(doctype, name))
        return docs[name]

    # ------------------------------------------------ Server side effects
    def _defaults(self, doc: dict[str, Any]) -> None:
        """Field defaults as Frappe sets them on creation (only missing fields)."""
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

    def _compute(self, doc: dict[str, Any]) -> None:
        """Computed fields and validations as the server performs them on insert/update."""
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

    def _server_side(self, doc: dict[str, Any]) -> None:
        self._defaults(doc)
        self._compute(doc)
        self._number_children(doc)

    # ------------------------------------------------------------ Queries
    def _filter(self, doctype: str, docs: list[dict[str, Any]], filters: Any) -> list[dict[str, Any]]:
        if not filters:
            return docs
        if isinstance(filters, str):
            filters = json.loads(filters)
        conds: list[tuple[Any, ...]]
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
        result: list[dict[str, Any]] = []
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
    def _order(docs: list[dict[str, Any]], order_by: str | None) -> list[dict[str, Any]]:
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

    def get_list(self, doctype: str, fields: str | list[str] = '["name"]', filters: Any = None, limit_start: int = 0,
                 limit_page_length: int | None = None, order_by: str | None = None) -> list[dict[str, Any]]:
        self._log("get_list", doctype, fields=fields, filters=filters, limit_start=limit_start,
                  limit_page_length=limit_page_length, order_by=order_by)
        docs = list(self.docs(doctype).values())
        docs = self._filter(doctype, docs, filters)
        docs = self._order(docs, order_by)
        parent_fields, child_fields = _parse_fields(fields)
        rows: list[dict[str, Any]] = []
        for doc in docs:
            base: dict[str, Any] = {}
            for field, alias in parent_fields:
                if field == "*":
                    base.update(copy.deepcopy(doc))
                else:
                    base[alias] = copy.deepcopy(doc.get(field, 0 if field == "docstatus" else None))
            if child_fields:
                child_rows: list[dict[str, Any]] = []
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

    def get_doc(self, doctype: str, name: str = "", filters: Any = None,
                fields: Any = None) -> dict[str, Any] | list[dict[str, Any]]:
        self._log("get_doc", doctype, name)
        name = urllib.parse.unquote(str(name))
        if not name:
            docs = self._filter(doctype, list(self.docs(doctype).values()), filters)
            return [copy.deepcopy(d) for d in docs]
        return copy.deepcopy(self._get(doctype, name))

    def load_doc(self, doctype: str, name: str = "") -> dict[str, Any]:
        self._log("load_doc", doctype, name)
        doc = copy.deepcopy(self._get(doctype, name))
        return {"docs": [doc],
                "docinfo": {"versions": copy.deepcopy(self.versions.get(name, [])),
                            "communications": copy.deepcopy(self.communications.get(name, []))}}

    def get_value(self, doctype: str, fieldname: str | None = None, filters: Any = None) -> dict[str, Any] | None:
        self._log("get_value", doctype, fieldname, filters)
        docs = self._filter(doctype, list(self.docs(doctype).values()), filters)
        if not docs:
            return None
        fieldname = fieldname or "name"
        return {fieldname: docs[0].get(fieldname)}

    def reportview_get(self, doctype: str, filters: Any = None, fields: list[str] | None = None,
                       params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._log("reportview_get", doctype, filters, fields)
        rows = self.get_list(doctype, fields=fields or ["name"], filters=filters,
                             limit_page_length=(params or {}).get("page_length"))
        keys = list(rows[0].keys()) if rows else []
        return {"keys": keys, "values": [[r[k] for k in keys] for r in rows]}

    # ------------------------------------------------------ Modifications
    def insert(self, doc: dict[str, Any]) -> frappe._dict:
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

    def insert_many(self, docs: Iterable[dict[str, Any]]) -> list[str]:
        return [self.insert(d)["name"] for d in docs]

    def update(self, doc: dict[str, Any]) -> frappe._dict:
        self._log("update", copy.deepcopy(doc))
        doctype = doc.get("doctype")
        if not doctype:
            raise FrappeException("FrappeClient Request Failed\n\nDocType None not found")
        stored = self._get(doctype, frappe.cstr(doc.get("name")))
        if doc.get("modified") and stored.get("modified") and doc["modified"] != stored["modified"]:
            raise FrappeException("FrappeClient Request Failed\n\nTimestampMismatchError: Dokument wurde geändert, "
                                  "nachdem es geöffnet wurde")
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

    def update_with_doctype(self, doc: dict[str, Any], doctype: str) -> frappe._dict:
        doc1 = dict(doc)
        doc1["doctype"] = doctype
        return self.update(doc1)

    def bulk_update(self, docs: Iterable[dict[str, Any]]) -> list[frappe._dict]:
        return [self.update(d) for d in docs]

    def set_value(self, doctype: str, docname: str, fieldname: str, value: Any) -> dict[str, Any]:
        self._log("set_value", doctype, docname, fieldname, value)
        stored = self._get(doctype, docname)
        stored[fieldname] = value
        return copy.deepcopy(stored)

    def delete(self, doctype: str, name: str) -> str:
        self._log("delete", doctype, name)
        stored = self._get(doctype, name)
        if stored.get("docstatus", 0) == 1:
            raise FrappeException("FrappeClient Request Failed\n\nCannot delete submitted document {} {}".format(doctype, name))
        del self.docs(doctype)[name]
        return "ok"

    def submit(self, doc: dict[str, Any]) -> dict[str, Any]:
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

    def cancel(self, doctype: str, name: str) -> dict[str, Any]:
        self._log("cancel", doctype, name)
        stored = self._get(doctype, name)
        stored["docstatus"] = 2
        stored["status"] = "Cancelled"
        return copy.deepcopy(stored)

    def rename_doc(self, doctype: str, old_name: str, new_name: str) -> str:
        stored = self._get(doctype, old_name)
        del self.docs(doctype)[old_name]
        stored["name"] = new_name
        self.docs(doctype)[new_name] = stored
        return new_name

    # ----------------------------------------------------------- Files etc.
    def get_file(self, path: str) -> bytes:
        self._log("get_file", path)
        if path not in self.files:
            raise FrappeException("FrappeClient Request Failed\n\nFile {} not found".format(path))
        return self.files[path]

    def attach_file(self, doctype: str, docname: str, filename: str, filedata: bytes, is_private: bool | int,
                    docfield: str | None = None) -> frappe._dict:
        self._log("attach_file", doctype, docname, filename, is_private, docfield=docfield)
        stored = self._get(doctype, docname)
        file_url = ("/private/files/" if is_private else "/files/") + filename
        self.files[file_url] = filedata
        self.attachments.append((doctype, docname, file_url))
        if docfield:
            stored[docfield] = file_url
            stored["modified"] = datetime.datetime.now().isoformat(sep=" ", timespec="microseconds")
        file_doc: dict[str, Any] = {"doctype": "File", "file_name": filename, "file_url": file_url,
                    "attached_to_doctype": doctype, "attached_to_name": docname,
                    "attached_to_field": docfield, "is_private": 1 if is_private else 0}
        file_doc["name"] = self._new_name("File", file_doc)
        self.docs("File")[file_doc["name"]] = file_doc
        return frappe._dict(copy.deepcopy(file_doc))

    def read_and_attach_file(self, doctype: str, docname: str, filename: str, is_private: bool | int,
                             docfield: str | None = None) -> frappe._dict:
        with open(filename, "rb") as f:
            data = f.read()
        return self.attach_file(doctype, docname, os.path.basename(filename), data, is_private, docfield)

    def get_pdf(self, doctype: str, name: str, print_format: str = "Standard", letterhead: bool = True,
                language: str = "de") -> io.BytesIO:
        self._log("get_pdf", doctype, name, print_format)
        self._get(doctype, name)
        return io.BytesIO(b"%PDF-1.4\n% fake pdf for " + name.encode() + b"\n")

    def get_html(self, doctype: str, name: str, print_format: str = "Standard", letterhead: bool = True) -> io.BytesIO:
        return io.BytesIO(b"<html>fake</html>")

    def get_attachments(self, doctype: str, name: str) -> list[str]:
        return [a[2] for a in self.attachments if a[0] == doctype and a[1] == name]

    def query_report(self, report_name: str = "", filters: dict[str, Any] | None = None,
                     ignore_prepared_report: bool = False) -> Any:
        self._log("query_report", report_name, filters, ignore_prepared_report=ignore_prepared_report)
        handler = self.report_handlers.get(report_name.lower())
        if handler is None:
            raise FrappeException("FrappeClient Request Failed\n\nReport {} not found".format(report_name))
        if callable(handler):
            return copy.deepcopy(handler(filters or {}))
        return copy.deepcopy(handler)

    def assign_to(self, doctype: str, name: str, assign_to: Iterable[str]) -> str:
        self._log("assign_to", doctype, name, assign_to)
        stored = self._get(doctype, name)
        stored["_assign"] = json.dumps(list(assign_to))
        self.assignments.append((doctype, name, list(assign_to)))
        return stored["_assign"]

    def get_background_jobs(self) -> list[Any]:
        self._log("get_background_jobs")
        return list(self.background_jobs)

    def get_open_activities(self, doctype: str, name: str) -> dict[str, Any]:
        return {"open_activities": []}

    def get_unreconciled_entries(self, name: str) -> dict[str, Any]:
        return {}

    def get_api(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._log("get_api", method, params)
        return None

    def post_api(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._log("post_api", method, params)
        return None

    def logout(self) -> None:
        pass


# -------------------------------------------------- requests simulation
class FakeResponse:
    def __init__(self, payload: Any = None, status_code: int = 200, text: str | None = None, ok: bool | None = None,
                 content: bytes = b"") -> None:
        self._payload: Any = payload
        self.status_code: int = status_code
        self.text: str = text if text is not None else (json.dumps(payload) if payload is not None else "")
        self.ok: bool = ok if ok is not None else status_code < 400
        self.content: bytes = content

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("No JSON")
        return self._payload

    def iter_content(self, size: int) -> Iterator[bytes]:
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]


class FakeSession:
    """Records requests and returns prepared responses (FIFO)."""

    def __init__(self, responses: Iterable[FakeResponse | Exception] | None = None) -> None:
        self.responses: list[FakeResponse | Exception] = list(responses or [])
        self.requests: list[tuple[str, str, dict[str, Any]]] = []   # (method, url, kwargs)

    def _pop(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if not self.responses:
            return FakeResponse({"data": []})
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._pop("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._pop("POST", url, kwargs)

    def put(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._pop("PUT", url, kwargs)
