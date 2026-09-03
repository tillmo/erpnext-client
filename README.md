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


