# Client for ERPNext

## easy installation on Debian / Ubuntu:
* download `install-ubuntu.sh` and run `sh install-ubuntu.sh`

## installation on Windows:
* Install [Python](https://www.python.org/downloads/windows/)
* Install the [Xpdf command line tools](https://www.xpdfreader.com/download.html) 
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
* currently, texts are in German only
 

