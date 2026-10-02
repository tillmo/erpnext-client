# Client for ERPNext

## installation on Debian / Ubuntu:
* download `install-ubuntu.sh` and run `sh install-ubuntu.sh`

## installation on Windows:
* Install [Python](https://www.python.org/downloads/windows/)
* Install the [Xpdf command line tools](https://www.xpdfreader.com/download.html) by unpacking [this zip archive](https://dl.xpdfreader.com/xpdf-tools-win-4.04.zip) into some folder in the PATH, e.g. C:\Users\<your name>\AppData\Local\Microsoft\WindowsApps 
* Install [Git](https://git-scm.com/download/win)
* Open a [terminal](https://en.wikipedia.org/wiki/Windows_Terminal) or [console](https://en.wikipedia.org/wiki/Windows_Console), and in some folder of your choice, enter the following commands:
  * git clone https://github.com/tillmo/erpnext-client.git
  * cd erpnext-client
  * pip3 install -r requirements.txt

You now can start the client with `python3 erpnext.py` (or, in Windows 10, with `erpnext`)

The GUI uses [FreeSimpleGUI](https://github.com/spyoungtech/FreeSimpleGUI), the free fork of PySimpleGUI 4;
existing settings in `~/.config/PySimpleGUI/settings/erpnext.json` keep working.

## features
* GUI for ERPNext bank reconciliation and purchase invoice creation
  * accesses ERPNext via the API
* read in purchase invoices from some companies, store them in ERPNext
  * can be easily extended for more companies
* read in bank statements from some banks, store bank transactions in ERPNext
  * can be easily extended for more banks
* process bank transactions, create journal or payment entries
* submit or delete journal entries, payment entries, purchase invoices
* handle this for multiple companies
* process leads created from incoming e-mails: assign them to lead owners or mark them
  "Do Not Contact" (see below)
* currently, texts are in German only

## leads marked "Do Not Contact"
Frappe reopens a lead on every received e-mail, so leads marked "Do Not Contact" had to be
marked again and again. `lead_dnc_setup.py` installs a check field `custom_nicht_kontaktieren`
on Lead and a server script that keeps flagged leads closed; the client sets the flag when a
lead is marked "Do Not Contact". Run it once per instance (without `--apply` it only reports):

    python3 lead_dnc_setup.py --server URL --key KEY --secret SECRET --apply

The script is idempotent and also flags the leads that were marked manually before.

## sorting leads automatically
`lead_rules.py` decides for each open lead whether it can be marked "Do Not Contact" without
asking: sender domains and addresses on a block list (custom doctype "Lead Absenderregel",
maintained in ERPNext), e-mail domains of suppliers (field `custom_email_domains` on Supplier,
filled from invoice PDFs and updated whenever an invoice is read in) combined with a
transactional subject, and newsletter wording from bulk senders. Everything else is shown in the
dialog, where a suggestion is preselected. Automatic decisions leave a comment on the lead.
Rules with effect "Lead" protect a sender from automatic marking.

`lead_rules_setup.py` installs the doctype and the supplier field, derives the initial block list
from the decisions made so far, extracts the supplier domains and reports with `--backtest` how
the rules would have decided the leads decided manually before a given date:

    python3 lead_rules_setup.py --server URL --key KEY --secret SECRET --backtest
    python3 lead_rules_setup.py --server URL --key KEY --secret SECRET --apply

## contact data and vCard for real leads
When a lead is assigned to a lead owner, `lead_contact.py` extracts name, phone numbers and
address from the lead's e-mails (web form labels, signature, "PLZ Ort" lines; quoted earlier
mails are ignored), shows them in an editable dialog, fills the empty lead fields, creates a
linked Address if there is none, and attaches a vCard (`<lead>.vcf`, private) to the lead.
The lead owners open the lead in the ERPNext app on the phone and tap the vCard to add the
contact. The menu item "Kontaktdaten nachtragen" does the same for existing real leads without
a phone number.

## vCards of assigned leads in Nextcloud (CardDAV)
`vcard_export.py` mirrors the leads assigned to a lead owner into that owner's Nextcloud address
book (`settings.NEXTCLOUD_ADDRESSBOOK`, one book per owner). The phones subscribe to it via
CardDAV (DAVx5 on Android, CardDAV on iOS), so an assigned lead shows up in the contacts without
any import. A lead is exported as soon as it is assigned, even when name, phone number or address
are still missing - the display name then falls back to the e-mail address, and the owner can call
and complete the data later. The lead id is the card's UID, so a later export replaces the card
instead of duplicating it, `CATEGORIES:ERPNext Lead` marks the cards the export manages (other
cards in the book are never touched), and a lead that is no longer assigned or was marked
"Do Not Contact" loses its card again. The client exports at the end of "Leads bearbeiten" and
"Kontaktdaten nachtragen", and on demand via "Lead - vCards exportieren".

Credentials go in once under "Einstellungen - Nextcloud" (URL, the user owning the address books,
and an app password); the address books have to be shared with the lead owners in Nextcloud once.
The same export also runs standalone, e.g. from cron, with the credentials in
NEXTCLOUD_URL, NEXTCLOUD_USER and NEXTCLOUD_PASSWORD:

    python3 vcard_export.py --server URL --key KEY --secret SECRET
    python3 vcard_export.py --server URL --key KEY --secret SECRET --apply --create --delete

Without `--apply` it only reports what it would write. `cron/vcard_export.sh` wraps this for a
cron job on a server: it needs only python3 with `requests` (no GUI - `gui.py` provides headless
stand-ins when tkinter is missing), takes the credentials from
`~/.config/erpnext-client/vcard-export.env` (template `cron/vcard-export.env.example`) and is
meant to run every 15 minutes under `flock`; the crontab line is in the script's header.
On erpnext.bremer-solidarstrom.de it runs as user `docker` from `~/erpnext-client`, logging to
`~/logs/vcard-export.log`, which `cron/logrotate.conf` rotates monthly (twelve months kept).
 
## reading purchase invoices: e-invoice XML, Claude, fixed parsers
`purchase_invoice.parse_invoice` tries, in this order:

1. **Embedded e-invoice** (`einvoice.py`): if the PDF carries a ZUGFeRD / Factur-X / XRechnung XML
   (CII or UBL), totals per VAT rate, line items, shipping charges and the early-payment discount
   are taken from the XML - exact and free. Krannich, Memodo and Wagner Solar already send these.
   Prepayment lines ("Vorkasse", "Anzahlung") are deductions on a final invoice and ignored; if every
   line is one, it is a prepayment invoice (Wagner: "Vorkasse (100%) für 1 Palette Artikelnr. ...")
   and the lines become the items, with article number and quantity taken from the line text and the
   article description and freight lines from the PDF text below the line. Quantities in pallets are
   converted to pieces (`settings.PALLET_SIZE`, 30 modules per pallet) for every reader.
2. **Claude** (`claude_parser.py`): otherwise, if an Anthropic API key is configured, the PDF goes to
   Claude as a document (text and page images, so scans work too) and the answer is forced into the
   client's purchase-data schema; totals are checked arithmetically with one correction round. The
   key is entered under "Einstellungen - Claude" in the menu, passed once with `--claude-key KEY`
   (stored in the settings like the ERPNext key) or set as `ANTHROPIC_API_KEY`; the model can be
   overridden there as well or with `--claude-model` (default `settings.CLAUDE_MODEL`). Roughly
   2-5 cents per invoice. Clearing the key falls back to the parsers below.
3. The supplier-specific text parsers and the generic parser as before. (The Google Document AI
   processor used until September 2026 has been shut down and removed from the client.)

The confirmation dialog stays in every case. Both new paths fill the invoice via
`PurchaseInvoice.apply_purchase_data`; the supplier printed on the invoice is matched to the
ERPNext suppliers by VAT id or by name, tolerating legal forms and address suffixes in the
ERPNext name (`Api.find_supplier`). Claude additionally gets the list of ERPNext supplier names
as a cached part of the prompt and returns the matching name directly.

## VAT transfers (SKR03)
Per SKR03 the input VAT accounts (1571, 1576, 1577) and the output VAT accounts (1771, 1776,
1787) are transferred to 1780 "Umsatzsteuer-Vorauszahlung" at the end of every declaration
period; the payment or refund from the tax office then clears 1780. `vat_catchup.py` catches up
the transfers that are missing since 2023: every quarter from 2024 on at its quarter end to 1780,
and everything before 2024 in one entry dated 2024-01-01 to 1791 "Umsatzsteuer frühere Jahre" -
the periods before 2024 cannot be reconstructed quarter by quarter (a catch-up transfer in the
first quarter of 2023 mixed periods, the advance payments on 1718 shifted VAT across the year
boundary) and the fiscal years up to 2023 are closed by Period Closing Vouchers.

    python3 vat_catchup.py --server URL --key KEY --secret SECRET
    python3 vat_catchup.py --server URL --key KEY --secret SECRET --apply [--submit]

Without `--apply` it only reports. `--apply` creates drafts, `--submit` books them as well. The
script is idempotent (a period whose entry exists is skipped), covers all companies with VAT
balances unless `--company` restricts it, and stops at the last completed quarter unless
`--until 2026-Q3` says otherwise. What is left on 1780 and 1791 afterwards is the reconciliation
with the tax office's account, which the tax advisor has to do.

## mytools
* the `mytools/` directory holds private helper scripts, kept in a separate non-public repository
* it is not needed for using the client: no code in this repository depends on it, and the directory is git-ignored here

## running tests
The test suite lives in `tests/` and is split into offline tests (no ERPNext needed),
read-only tests against an ERPNext instance, and write tests against a dedicated test instance:

    python3 -m pytest tests/offline

See [tests/README.md](tests/README.md) for the environment variables that enable the online
tests, for the safety measures (no GUI dialogs, read-only guard, automatic cleanup) and for the
list of known findings documented as `xfail`.


