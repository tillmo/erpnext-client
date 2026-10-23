# Server Script "Ertragskonten nach Rechnungskontext" - DocType Event "Before Save" on Sales Invoice.
#
# Items carry a default income account (8401/8403) that rarely matches the invoice: the account
# follows the business (EBay, Selbstbausets, Balkonmodule, Selbstbauanlagen) and the VAT of the
# invoice (0% or 19%). Set it for every item whose account is one of the generic sales accounts
# (or empty); deliberately chosen other accounts (8404 Ökostrom, 2700 Fördergelder, ...) stay.
# Company Bremer SolidarStrom only. Sandbox rules: plain loops (comprehensions do not see outer
# names), no str.format, %-formatting only.
if doc.company == "Bremer SolidarStrom" and doc.docstatus == 0:
    ACCOUNTS = {
        "EBay":             {0: "8294 - EBay 0% - SoMiKo",             19: "8406 - EBay 19% - SoMiKo"},
        "Selbstbausets":    {0: "8292 - Selbstbausets 0% - SoMiKo",    19: "8402 - Selbstbausets 19% - SoMiKo"},
        "Balkonmodule":     {0: "8293 - Balkonmodule 0% - SoMiKo",     19: "8403 - Balkonmodule 19% - SoMiKo"},
        "Selbstbauanlagen": {0: "8291 - Selbstbauanlagen 0% - SoMiKo", 19: "8401 - Selbstbauanlagen 19% - SoMiKo"},
    }
    generic = []
    for cat in ACCOUNTS:
        for rate in ACCOUNTS[cat]:
            generic.append(ACCOUNTS[cat][rate])
    # 1. business category: flags first, then the project type
    project_type = None
    if doc.project:
        project_type = frappe.db.get_value("Project", doc.project, "project_type")
    if doc.custom_ebay:
        category = "EBay"
    elif doc.material or project_type in ("Solaranlagenmaterial", "Materiallieferung"):
        category = "Selbstbausets"
    elif doc.balkonmodul or project_type == "Balkonmodule":
        category = "Balkonmodule"
    else:
        category = "Selbstbauanlagen"
    # 2. VAT of the invoice: tax template, else the tax rows
    vat = 0
    if doc.taxes_and_charges and "19%" in doc.taxes_and_charges:
        vat = 19
    elif not doc.taxes_and_charges:
        for t in doc.taxes:
            if "19%" in (t.account_head or "") or t.rate == 19:
                vat = 19
    account = ACCOUNTS[category][vat]
    # 3. set it
    changed = 0
    for item in doc.items:
        if not item.income_account or item.income_account in generic:
            if item.income_account != account:
                item.income_account = account
                changed = changed + 1  # no augmented assignment in the sandbox
    if changed:
        frappe.msgprint("Ertragskonto %s (%s, %d%% USt) für %d Position(en) gesetzt" % (account, category, vat, changed), alert=True)
