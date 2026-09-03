"""Shared test configuration.

Order matters: install the stubs first, only then import the project modules
(the project modules live in the repository root).

Three test categories (directory = marker):

* tests/offline       - no network, Api.api is a FakeFrappeClient
* tests/online_read   - read-only against an instance (ERPNEXT_TEST_SERVER/KEY/SECRET[/COMPANY])
* tests/online_write  - writing against a TEST instance (additionally ERPNEXT_TEST_WRITE=1)

The credentials are deliberately read ONLY from environment variables, never from
the user's erpnext.json - so that write tests never accidentally run against the
production instance.
"""
from __future__ import annotations

from collections import defaultdict
import os
import sys
from typing import TYPE_CHECKING, Any, Iterator

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for p in (TESTS, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from support import stubs  # noqa: E402

STUBS = stubs.install()

import PySimpleGUI as sg  # noqa: E402  (Stub)
import easygui  # noqa: E402  (Stub)

if TYPE_CHECKING:
    from pathlib import Path

    from company import Company
    from support.fakes import FakeFrappeClient


# ------------------------------------------------------------ Markers
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.fspath)
        if os.sep + "offline" + os.sep in path:
            item.add_marker(pytest.mark.offline)
        elif os.sep + "online_read" + os.sep in path:
            item.add_marker(pytest.mark.online_read)
        elif os.sep + "online_write" + os.sep in path:
            item.add_marker(pytest.mark.online_write)


# ------------------------------------------------------ Environment
class OnlineConfig:
    def __init__(self) -> None:
        self.server: str | None = os.environ.get("ERPNEXT_TEST_SERVER")
        self.key: str | None = os.environ.get("ERPNEXT_TEST_KEY")
        self.secret: str | None = os.environ.get("ERPNEXT_TEST_SECRET")
        self.company: str | None = os.environ.get("ERPNEXT_TEST_COMPANY")
        self.write: bool = os.environ.get("ERPNEXT_TEST_WRITE") == "1"
        self.allow_submit: bool = os.environ.get("ERPNEXT_TEST_ALLOW_SUBMIT") == "1"
        self.max_invoices: int = int(os.environ.get("ERPNEXT_TEST_MAX_INVOICES", "25"))
        self.parser_min_match: float = float(os.environ.get("ERPNEXT_TEST_PARSER_MIN_MATCH", "0.5"))

    @property
    def configured(self) -> bool:
        return bool(self.server and self.key and self.secret)


@pytest.fixture(scope="session")
def online_config() -> OnlineConfig:
    return OnlineConfig()


# ------------------------------------------------------- Reset state
DEFAULT_SETTINGS: dict[str, Any] = {
    "-company-": "Bremer SolidarStrom",
    "-server-": "https://erpnext.test.invalid",
    "-key-": "testkey",
    "-secret-": "testsecret",
    "-buchen-": False,
    "-setup-": False,
    "-year-": 2026,
    "-folder-": ROOT,
    "-google-credentials-": None,
    "-invoice-processor-": None,
}


def _reset_project_state() -> None:
    """Clear the class-wide caches of the project modules (only if already imported)."""
    api = sys.modules.get("api")
    if api is not None:
        api.Api.api = None
        api.Api.items_by_code = {}
        api.Api.item_code_translation = defaultdict(dict)
        api.Api.accounts_by_company = {}
    company = sys.modules.get("company")
    if company is not None:
        company.Company.companies_by_name = {}
    bank = sys.modules.get("bank")
    if bank is not None:
        bank.BankAccount.clear_baccounts()


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    stubs.UserSettings.store = dict(DEFAULT_SETTINGS)
    easygui.reset()
    _reset_project_state()
    yield
    _reset_project_state()


@pytest.fixture
def user_settings() -> stubs.UserSettings:
    """Access to the (stubbed) sg.UserSettings store."""
    return sg.UserSettings()


@pytest.fixture
def gui() -> stubs.EasyguiStub:
    """Provide answers for easygui dialogs: gui.answers['choicebox'] = 'value'."""
    return easygui


@pytest.fixture
def fake_api() -> FakeFrappeClient:
    """Install FakeFrappeClient as Api.api."""
    from support.fakes import FakeFrappeClient
    from api import Api
    client = FakeFrappeClient()
    Api.api = client
    return client


@pytest.fixture
def somiko(fake_api: FakeFrappeClient) -> Company:
    """Company 'Bremer SolidarStrom' offline, with accounts and tax rates."""
    from support import factories
    return factories.make_company()


@pytest.fixture
def laden(fake_api: FakeFrappeClient) -> Company:
    from support import factories
    return factories.make_company(factories.LADEN, "Laden")


@pytest.fixture
def restore_locale() -> Iterator[None]:
    import locale
    old = locale.setlocale(locale.LC_ALL)
    yield
    try:
        locale.setlocale(locale.LC_ALL, old)
    except locale.Error:
        locale.setlocale(locale.LC_ALL, "C")


@pytest.fixture
def in_tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tests that write files into the working directory run in tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
