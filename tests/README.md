# Tests for the ERPNext client

The tests live in three directories, which are also pytest markers:

| Directory              | Marker         | Prerequisite                                                     |
|------------------------|----------------|------------------------------------------------------------------|
| `tests/offline/`       | `offline`      | none – ERPNext is replaced by an in-memory fake                  |
| `tests/online_read/`   | `online_read`  | ERPNext instance with **read** API access                        |
| `tests/online_write/`  | `online_write` | ERPNext **test** instance with **write** access                  |

Run them from the repository root, with the client's Python environment activated
(e.g. `source ~/programs/python/env3.14/bin/activate`; `pytest` is listed in `requirements-linux.txt`):

```bash
python3 -m pytest tests/offline
```

```bash
ERPNEXT_TEST_SERVER=https://erpnext-test.example ERPNEXT_TEST_KEY=... ERPNEXT_TEST_SECRET=... \
python3 -m pytest tests/online_read
```

```bash
ERPNEXT_TEST_SERVER=https://erpnext-test.example ERPNEXT_TEST_KEY=... ERPNEXT_TEST_SECRET=... \
ERPNEXT_TEST_WRITE=1 python3 -m pytest tests/online_write
```

Without the environment variables, the online tests are skipped, not run.

## Environment variables

| Variable                        | Meaning                                                                            |
|---------------------------------|------------------------------------------------------------------------------------|
| `ERPNEXT_TEST_SERVER`           | URL of the instance, e.g. `https://erpnext-test.example`                           |
| `ERPNEXT_TEST_KEY` / `_SECRET`  | API key/secret (ERPNext: Settings → My Settings → API Access)                      |
| `ERPNEXT_TEST_COMPANY`          | company used for testing (default: first company of the instance)                  |
| `ERPNEXT_TEST_WRITE=1`          | enable write tests                                                                 |
| `ERPNEXT_TEST_ALLOW_SUBMIT=1`   | additionally tests that submit documents and cancel them again                     |
| `ERPNEXT_TEST_MAX_INVOICES`     | number of invoices for the parser regression (default 25)                          |
| `ERPNEXT_TEST_PARSER_MIN_MATCH` | minimum match rate of the parser regression, 0–1 (default 0.5)                     |

The credentials are read **only** from these variables, never from the user's
`erpnext.json`. This way, write tests never accidentally run against the production instance.

## Safety net

* **No dialogs, no foreign settings.** `PySimpleGUI`, `PySimpleGUIWx` and `easygui`
  are replaced by stubs in all tests (`tests/support/stubs.py`). A test that would
  unexpectedly open a dialog fails with `GuiCalled`. The real `erpnext.json`
  is never touched.
* **Read-only tests cannot write.** In `tests/online_read`, `Api.api` is a
  `ReadOnlyClient` that aborts every writing call with `ReadOnlyViolation`.
* **Write tests clean up.** Created documents are named `pytest-<id>` (or carry the
  identifier in a reference/remark) and are deleted via the `cleanup` fixture; submitted
  documents are cancelled first. If something is left behind, pytest reports a warning with
  the document names. `test_bank_write.py` resets `last_integration_date` of the bank
  account used. `test_load_item_data_completes_item_defaults` adds – like the program does
  at startup – missing `item_defaults` to items; this persists.
* **Submitting leaves traces.** Documents submitted with `ERPNEXT_TEST_ALLOW_SUBMIT=1` are
  cancelled, but cannot be deleted (general ledger / payment ledger entries refer to them);
  they remain on the instance as cancelled `pytest-…` documents together with the test supplier.
  The server app `bremer_solidarstrom` only allows fixed short names for
  `PreRechnung.buchungskonto` (e.g. "Werkzeuge und Kleingeräte"); the tests use one of them.

## Optional dependencies

If `jsondiff`, `jsoneditor`, `anytree`, `plotly`, `datefinder` or
`google-cloud-documentai` are missing, they are replaced by stubs so that the project modules
remain importable. Tests that need the real package are skipped
(`requires_jsondiff`, `requires_datefinder`, … in `tests/support/deps.py`).
`pdftotext` (xpdf, as in `install-ubuntu.sh`) must be installed; without the program,
the modules around `purchase_invoice` are skipped. The Wagner tests need the
locale `de_DE.utf8`.

## Layout

```
tests/
├── conftest.py            install stubs, markers, reset state per test, fixtures
├── support/
│   ├── stubs.py           GUI and package stubs
│   ├── fakes.py           FakeFrappeClient (in-memory ERPNext), FakeSession/FakeResponse
│   ├── factories.py       companies, accounts, synthetic invoice PDFs, bank statements, parser lines
│   ├── deps.py            availability markers for optional dependencies
│   └── live.py            connection, ReadOnlyClient, LiveState, Cleanup for online tests
├── offline/               unit and integration tests per module (test_<module>.py) plus
│                          test_integration_pipeline.py (end-to-end workflows against the fake)
├── online_read/           basic API behaviour, master data, reports, parser regression
└── online_write/          create/modify/delete: supplier, journal entry, payment, bank statement,
                           purchase invoice from PDF, stock entry, item, PreRechnung, submit,
                           leads (server script of lead_dnc_setup.py, sender rules of
                           lead_rules_setup.py - skipped until they are installed -, contact
                           data and vCard)
```

The fake (`FakeFrappeClient`) reproduces the points where the client relies on
server behaviour: `get_list` returns only the requested fields (default `name`)
and, without `limit_page_length`, at most 20 rows; child table fields yield one row
per child row; `insert` computes totals/status; unbalanced journal entries and the
deletion of submitted documents are rejected. `tests/online_read/test_connection_live.py`
checks exactly these assumptions against the real server.

## Documenting findings (`xfail`)

A test that records a suspected bug in the client gets `@pytest.mark.xfail(strict=True,
reason=...)`: it "passes" as long as the bug is present, and fires as soon as it has been fixed
(then remove the marker). The 22 findings from building the suite (2026-09-03) have since been
fixed; currently there are no `xfail` tests. Overview at any time:
`python3 -m pytest tests/offline -ra | grep XFAIL`.

## Type checking

The entire code (client and tests) is type-annotated; `mypy.ini` in the root directory
configures the check (`mypy`, or `uvx mypy` without installation). The remaining
findings are not annotation errors but honest hints at places where the code uses
return values that may be `None` without checking (mainly results of `gui_api_wrapper`,
`Company.get_company`, parser fields before parsing). They are best fixed during the
respective refactoring, not by weakening the annotations.

## Parser regression with real invoices

`tests/online_read/test_parser_regression.py` replaces `test/test_pinv_parser.py`. It loads up to
`ERPNEXT_TEST_MAX_INVOICES` purchase invoice PDFs from the instance (or uses
`test/data/purchase_invoices.json` with its PDFs, if created with `test/get_purchase_invoices.py`),
parses them with `is_test=True` and compares the recognised invoice number with `bill_no`. The
output (`-s`) shows deviations per parser.
