"""Invoice extraction with Claude (replacement for Google Document AI and the fixed parsers).

The PDF goes to the model as a document (text and page images, so scans work too); the answer
is forced into the client's purchase-data schema with structured outputs. The totals are checked
arithmetically; on a mismatch the model gets one chance to correct itself. The result feeds
``purchase_invoice.PurchaseInvoice.apply_purchase_data`` like an embedded e-invoice does.

Configuration: API key in the client settings (``--claude-key``) or the environment variable
ANTHROPIC_API_KEY; model via ``--claude-model`` (default settings.CLAUDE_MODEL).
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any

import PySimpleGUI as sg

import settings

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["supplier", "supplier_tax_id", "bill_no", "posting_date", "order_id", "total", "grand_total",
                 "shipping", "skonto_percent", "taxes", "items"],
    "properties": {
        "supplier": {"type": "string", "description": "the supplier (issuer of the invoice): exactly one of the known ERPNext "
                                                       "supplier names if the issuer is among them, otherwise the legal name as printed"},
        "supplier_tax_id": {"type": ["string", "null"], "description": "VAT ID of the supplier (USt-IdNr., e.g. DE123456789)"},
        "bill_no": {"type": "string", "description": "invoice number exactly as printed"},
        "posting_date": {"type": "string", "description": "invoice date as YYYY-MM-DD"},
        "order_id": {"type": ["string", "null"], "description": "the customer's order or reference number, if printed"},
        "total": {"type": "number", "description": "net total including shipping, before VAT"},
        "grand_total": {"type": "number", "description": "gross total payable before any early-payment discount"},
        "shipping": {"type": "number", "description": "sum of shipping, freight, packaging and insurance charges (net), 0 if none"},
        "skonto_percent": {"type": ["number", "null"], "description": "early-payment discount in percent if offered, else null"},
        "taxes": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "required": ["rate", "net", "tax_amount"],
                      "properties": {"rate": {"type": "number", "description": "VAT rate in percent"},
                                     "net": {"type": "number", "description": "taxable net amount at this rate"},
                                     "tax_amount": {"type": "number"}}},
        },
        "items": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False,
                      "required": ["item_code", "description", "qty", "uom", "rate", "amount"],
                      "properties": {"item_code": {"type": ["string", "null"], "description": "supplier's article number"},
                                     "description": {"type": "string"},
                                     "qty": {"type": "number"},
                                     "uom": {"type": "string", "description": "unit, e.g. Stk, m, kg, Paket"},
                                     "rate": {"type": "number", "description": "net unit price"},
                                     "amount": {"type": "number", "description": "net line amount"}}},
        },
    },
}

SYSTEM = """You extract bookkeeping data from purchase invoices (mostly German) for a small solar cooperative.
Return the data in the requested JSON schema and nothing else.

Rules:
- Amounts are numbers in EUR; German notation "1.234,56" means 1234.56.
- "taxes": one entry per VAT rate with the taxable net amount ("net") and the VAT amount at that rate.
- "total" is the net total including shipping; "grand_total" is the gross amount payable before any early-payment discount (Skonto).
- Shipping, freight, packaging, insurance and similar service charges go into "shipping" (net) and are NOT items.
- Prepayment lines ("Vorkasse", "Anzahlung") and their deductions are NOT items.
- "items": every product or service position with quantity, unit (Stk, m, kg, Paket, Std ...), net unit price, net line amount and the supplier's article number if printed. Discounts on a line are already reflected in its amount.
- "bill_no" exactly as printed (invoice number, not order or customer number). "posting_date" is the invoice date.
- "order_id": the customer's order/reference number (Bestellnummer, Auftragsnummer, Ihre Referenz) if printed, else null.
- If a value is not on the invoice, use null where the schema allows it and 0 for missing shipping.
- The arithmetic must hold: total + sum of VAT amounts = grand_total; sum of item amounts + shipping = total (up to rounding of a few cents)."""


def api_key() -> str | None:
    try:
        key = sg.UserSettings().get('-claude-key-')
    except Exception:
        key = None
    return key or os.environ.get('ANTHROPIC_API_KEY') or None


def model() -> str:
    try:
        return sg.UserSettings().get('-claude-model-') or settings.CLAUDE_MODEL
    except Exception:
        return settings.CLAUDE_MODEL


def configured() -> bool:
    return bool(api_key())


def _client() -> Any:
    import anthropic
    return anthropic.Anthropic(api_key=api_key())


def check(data: dict[str, Any]) -> list[str]:
    """Arithmetic consistency; returns the problems found (empty if consistent)."""
    problems: list[str] = []
    taxes = data.get('taxes') or []
    items = data.get('items') or []
    total = float(data.get('total') or 0)
    grand = float(data.get('grand_total') or 0)
    shipping = float(data.get('shipping') or 0)
    tax_sum = sum(float(t.get('tax_amount') or 0) for t in taxes)
    net_sum = sum(float(t.get('net') or 0) for t in taxes)
    if abs(total + tax_sum - grand) > 0.05:
        problems.append(f"total {total:.2f} + Steuern {tax_sum:.2f} ergibt {total + tax_sum:.2f}, grand_total ist {grand:.2f}")
    if taxes and abs(net_sum - total) > 0.05:
        problems.append(f"Summe der Steuerbasen {net_sum:.2f} weicht von total {total:.2f} ab")
    if items:
        item_sum = sum(float(i.get('amount') or 0) for i in items)
        if abs(item_sum + shipping - total) > 0.05:
            problems.append(f"Positionen {item_sum:.2f} + Versand {shipping:.2f} ergibt {item_sum + shipping:.2f}, total ist {total:.2f}")
        for i in items:
            qty, rate, amount = float(i.get('qty') or 0), float(i.get('rate') or 0), float(i.get('amount') or 0)
            if qty and rate and abs(qty * rate - amount) > max(0.05, 0.005 * abs(amount)):
                problems.append(f"Position '{str(i.get('description'))[:40]}': {qty} x {rate} ist nicht {amount}")
    for t in taxes:
        net, tax, rate = float(t.get('net') or 0), float(t.get('tax_amount') or 0), float(t.get('rate') or 0)
        if net and abs(net * rate / 100 - tax) > 0.05:
            problems.append(f"Steuer {rate}% auf {net:.2f} wäre {net * rate / 100:.2f}, angegeben {tax:.2f}")
    return problems


def system_blocks(suppliers: list[str] | None) -> list[dict[str, Any]]:
    """Rules plus the ERPNext supplier list; the list is cached across calls (prompt caching)."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": SYSTEM}]
    if suppliers:
        blocks.append({"type": "text",
                       "text": "Known ERPNext supplier names (return exactly one of these as \"supplier\" when the invoice "
                               "issuer is among them, tolerating different spelling, legal form or an address in the name):\n"
                               + "\n".join(suppliers),
                       "cache_control": {"type": "ephemeral"}})
    return blocks


def _call(client: Any, messages: list[dict[str, Any]], suppliers: list[str] | None = None) -> tuple[dict[str, Any], str]:
    response = client.beta.messages.create(
        model=model(),
        max_tokens=16000,
        system=system_blocks(suppliers),
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == 'refusal':
        details = getattr(response, 'stop_details', None)
        raise RuntimeError("Claude hat die Anfrage abgelehnt: {}".format(getattr(details, 'explanation', '') or ''))
    text = next((b.text for b in response.content if b.type == 'text'), '')
    usage = getattr(response, 'usage', None)
    if usage is not None:
        cached = getattr(usage, 'cache_read_input_tokens', 0) or 0
        print(f"Claude ({response.model}): {usage.input_tokens} Eingabe-, {usage.output_tokens} Ausgabe-Tokens"
              + (f", {cached} aus dem Cache" if cached else ""))
    return json.loads(text), text


def extract(pdf: bytes, supplier_hint: str | None = None, client: Any = None,
            suppliers: list[str] | None = None) -> dict[str, Any]:
    """Purchase data of an invoice PDF. Raises on API errors or refusal.
    ``suppliers``: known ERPNext supplier names, so that the model returns the matching one."""
    client = client or _client()
    prompt = "Extract the invoice data from this PDF."
    if supplier_hint:
        prompt += f" The supplier is expected to be '{supplier_hint}'."
    messages: list[dict[str, Any]] = [{"role": "user", "content": [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                        "data": base64.standard_b64encode(pdf).decode('ascii')}},
        {"type": "text", "text": prompt}]}]
    data, text = _call(client, messages, suppliers)
    problems = check(data)
    if problems:
        print("Claude-Ergebnis unstimmig, zweiter Versuch: " + "; ".join(problems))
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "The arithmetic check found problems:\n- " + "\n- ".join(problems)
                      + "\nRe-read the invoice carefully and return the corrected JSON."}]
        data2, _ = _call(client, messages, suppliers)
        problems2 = check(data2)
        if len(problems2) <= len(problems):
            data, problems = data2, problems2
    for p in problems:
        print("Warnung: " + p)
    data['source'] = 'claude'
    data['problems'] = problems
    return data


def extract_file(path: str, supplier_hint: str | None = None, client: Any = None) -> dict[str, Any]:
    """Like ``extract``, with the ERPNext supplier names as hint (if the API is available)."""
    from api import Api
    try:
        suppliers = Api.supplier_names() if Api.api else None
    except Exception:
        suppliers = None
    with open(path, 'rb') as f:
        return extract(f.read(), supplier_hint, client, suppliers)
