# Stock items on a purchase invoice without "Update Stock" are booked by ERPNext to the
# "Stock Received But Not Billed" account (1702) and stay there, because no purchase receipt
# ever clears it. Refuse such invoices (installed by Till/Claude, 2026-10-22).
# (plain loop: comprehensions do not see outer names in the server script sandbox)
if doc.docstatus < 2:
    srbnb = frappe.db.get_value("Company", doc.company, "stock_received_but_not_billed")
    bad = []
    for d in doc.items:
        if srbnb and d.expense_account == srbnb:
            bad.append(d.item_code)
    if bad:
        frappe.throw("Lagerartikel ohne Lagerbuchung: %s wuerde auf %s gebucht. Bitte 'Lager aktualisieren' einschalten oder einen Nicht-Lagerartikel verwenden." % (", ".join(bad), srbnb))
