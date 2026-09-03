"""Regression test of the invoice parsers against real purchase invoice PDFs of the instance.

Successor of test/test_pinv_parser.py: for up to ERPNEXT_TEST_MAX_INVOICES (default 25)
purchase invoices with an attached PDF, the PDF is loaded, parsed with is_test=True and the
recognised invoice number is compared with bill_no (same variant rule as in the old script:
'22' and '22a' count as equal). If test/data/purchase_invoices.json with its PDFs is present
(created by test/get_purchase_invoices.py), that data set is used instead.

The test fails if a parser raises an exception or the match rate falls below
ERPNEXT_TEST_PARSER_MIN_MATCH (default 0.5); the details are printed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from api import Api
from company import Company
from support.deps import skip_module_without_pdftotext
from support.live import LiveState
from support.stubs import UserSettings

skip_module_without_pdftotext()

import purchase_invoice  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "test", "data")


def same_number(parsed: str | None, expected: str | None) -> bool:
    expected = (expected or "").strip()       # bill_no in ERPNext sometimes contains a trailing '\n'
    if not expected:
        return parsed in (None, "", "???")
    if parsed == expected:
        return True
    return bool(parsed) and parsed == expected[0:-1] and expected[-1] in "abcdefgh"


def load_candidates(api: Any, live: LiveState, tmp_path: Path) -> tuple[list[tuple[dict[str, Any], str]], str]:
    json_file = os.path.join(DATA_DIR, "purchase_invoices.json")
    if os.path.isfile(json_file):
        with open(json_file) as f:
            docs = json.load(f)
        cands = []
        for name, doc in docs.items():
            pdf = os.path.join(DATA_DIR, doc["name"] + ".pdf")
            if os.path.isfile(pdf):
                cands.append((doc, pdf))
        return cands[:live.config.max_invoices], "test/data"
    rows = api.get_list("Purchase Invoice",
                        filters={"status": ["in", ["Paid", "Unpaid", "Overdue", "Partly Paid"]],
                                 "supplier_invoice": ["is", "set"]},
                        fields=["name", "bill_no", "supplier", "company", "grand_total", "supplier_invoice", "update_stock"],
                        limit_page_length=live.config.max_invoices, order_by="posting_date desc")
    cands = []
    for row in rows:
        pdf = os.path.join(str(tmp_path), row["name"].replace(" ", "_") + ".pdf")
        with open(pdf, "wb") as f:
            f.write(api.get_file(row["supplier_invoice"]))
        cands.append((row, pdf))
    return cands, "Instanz"


def test_parsers_against_real_invoices(api: Any, live: LiveState, tmp_path: Path, user_settings: UserSettings,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    cands = [(doc, pdf) for doc, pdf in load_candidates(api, live, tmp_path)[0]
             if purchase_invoice.pdf_to_text(pdf)]
    if not cands:
        pytest.skip("keine Einkaufsrechnungen mit Text-PDF")
    loaded = {live.company_name}
    results = []
    for doc, pdf in cands:
        comp_name = doc.get("company") or live.company_name
        if comp_name not in loaded:
            Company.get_company(comp_name).load_data()
            loaded.add(comp_name)
        user_settings["-company-"] = comp_name
        pinv = purchase_invoice.PurchaseInvoice(False)
        entry = {"name": doc["name"], "supplier": doc.get("supplier"), "expected": doc.get("bill_no"),
                 "parsed": None, "parser": None, "error": None, "gross": None, "expected_gross": doc.get("grand_total")}
        try:
            pinv.parse_invoice(None, pdf, given_supplier=doc.get("supplier"), is_test=True)
            entry["parsed"], entry["parser"], entry["gross"] = pinv.no, pinv.parser, pinv.gross_total
        except Exception as e:  # noqa: BLE001 - every exception is a finding here
            entry["error"] = "{}: {}".format(type(e).__name__, e)
        entry["ok"] = entry["error"] is None and same_number(entry["parsed"], entry["expected"])
        results.append(entry)
    user_settings["-company-"] = live.company_name

    errors = [r for r in results if r["error"]]
    mismatches = [r for r in results if not r["ok"] and not r["error"]]
    matches = len(results) - len(errors) - len(mismatches)
    print("\nParser-Regression ({} Rechnungen): {} Treffer, {} Abweichungen, {} Fehler".format(
        len(results), matches, len(mismatches), len(errors)))
    for r in mismatches:
        print("  {:20s} {:30s} parser={:10s} erkannt={!r:20s} erwartet={!r}".format(
            r["name"], (r["supplier"] or "")[:30], str(r["parser"]), r["parsed"], r["expected"]))
    for r in errors:
        print("  {:20s} {:30s} FEHLER {}".format(r["name"], (r["supplier"] or "")[:30], r["error"][:150]))
    by_parser: dict[str, list[int]] = {}
    for r in results:
        by_parser.setdefault(r["parser"], [0, 0])
        by_parser[r["parser"]][0] += int(r["ok"])
        by_parser[r["parser"]][1] += 1
    print("  nach Parser: " + ", ".join("{}: {}/{}".format(p, ok, n) for p, (ok, n) in sorted(by_parser.items(), key=str)))

    assert not errors, "Parser-Ausnahmen bei {} Rechnungen (siehe Ausgabe)".format(len(errors))
    ratio = matches / len(results)
    assert ratio >= live.config.parser_min_match, \
        "Trefferquote {:.0%} unter der Schwelle {:.0%}".format(ratio, live.config.parser_min_match)
