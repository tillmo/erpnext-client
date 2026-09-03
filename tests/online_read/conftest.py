"""Fixtures für lesende Tests gegen eine ERPNext-Instanz.

Aktivierung über Umgebungsvariablen:

    ERPNEXT_TEST_SERVER=https://erpnext.example ERPNEXT_TEST_KEY=... ERPNEXT_TEST_SECRET=... \\
    [ERPNEXT_TEST_COMPANY="Bremer SolidarStrom"] python3 -m pytest tests/online_read

Alle Tests laufen mit einem ReadOnlyClient: jeder Schreibversuch schlägt fehl.
"""
import pytest

from support.live import LiveState


@pytest.fixture(scope="session")
def live(online_config):
    return LiveState(online_config)


@pytest.fixture(autouse=True)
def _live_env(live):
    """Nach dem Zurücksetzen durch tests/conftest.py Client und Registries wieder einsetzen."""
    yield live.install(read_only=True)


@pytest.fixture
def api(live):
    """Der Nur-Lese-Client (entspricht Api.api)."""
    from api import Api
    return Api.api


@pytest.fixture
def comp(live):
    return live.company
