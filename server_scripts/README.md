# Server Scripts installed in ERPNext

The scripts in this directory live in ERPNext (DocType "Server Script") and are kept here as the
reference copy. Install or update them with the web form (Server Script, script type "DocType Event")
or via the API (`Server Script` insert/update); `server_script_enabled` must be set in Frappe 15+.
The Frappe sandbox forbids `str.format`, augmented assignment (`x += 1`) and comprehensions that
use outer names - hence the plain loops.

| File | Name in ERPNext | DocType / event | Purpose |
|---|---|---|---|
| `sales_invoice_income_accounts.py` | Ertragskonten nach Rechnungskontext | Sales Invoice / Before Save | income account per item from the business (EBay, Selbstbausets, Balkonmodule, Selbstbauanlagen) and the VAT of the invoice |
| `purchase_invoice_stock_items_need_stock_update.py` | Keine Lagerartikel ohne Lagerbuchung | Purchase Invoice / Before Save | refuses stock items without "Update Stock" (they would be parked on 1702) |

The lead scripts ("Lead nicht kontaktieren halten") are installed by `lead_dnc_setup.py`.
