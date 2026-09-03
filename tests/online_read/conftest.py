"""Fixtures for read-only tests against an ERPNext instance.

Activation via environment variables:

    ERPNEXT_TEST_SERVER=https://erpnext.example ERPNEXT_TEST_KEY=... ERPNEXT_TEST_SECRET=... \\
    [ERPNEXT_TEST_COMPANY="Bremer SolidarStrom"] python3 -m pytest tests/online_read

All tests run with a ReadOnlyClient: every write attempt fails.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

import pytest

from support.live import LiveState

if TYPE_CHECKING:
    from company import Company
    from conftest import OnlineConfig
    from frappeclient import FrappeClient
    from support.live import ReadOnlyClient


@pytest.fixture(scope="session")
def live(online_config: OnlineConfig) -> LiveState:
    return LiveState(online_config)


@pytest.fixture(autouse=True)
def _live_env(live: LiveState) -> Iterator[FrappeClient | ReadOnlyClient]:
    """Reinstate client and registries after the reset by tests/conftest.py."""
    yield live.install(read_only=True)


@pytest.fixture
def api(live: LiveState) -> ReadOnlyClient:
    """The read-only client (corresponds to Api.api)."""
    from api import Api
    return Api.api


@pytest.fixture
def comp(live: LiveState) -> Company:
    return live.company
