import os
from unittest.mock import MagicMock

import pytest

from flaresolverr import backends
from flaresolverr.backends.base import BackendBase


class DummyBackend:
    def create_driver(self, proxy, stealth_mode):
        return MagicMock()


def test_register_and_get_backend():
    backends.register_backend("dummy", DummyBackend)
    instance = backends.get_backend("dummy")
    assert isinstance(instance, DummyBackend)


def test_get_backend_defaults_to_env_var(monkeypatch):
    monkeypatch.setenv("DRIVER_BACKEND", "undetected_chromedriver")
    instance = backends.get_backend()
    assert instance is not None


def test_get_backend_defaults_to_undetected_chromedriver():
    instance = backends.get_backend()
    assert instance is not None


def test_get_backend_raises_for_unknown_backend():
    with pytest.raises(ValueError, match="Unknown driver backend"):
        backends.get_backend("nonexistent")


def test_utils_get_webdriver_dispatches_to_backend(monkeypatch):
    from flaresolverr import utils

    mock_backend = MagicMock()
    mock_driver = MagicMock()
    mock_backend.create_driver.return_value = mock_driver
    monkeypatch.setattr(backends, "get_backend", lambda _name=None: mock_backend)

    driver = utils.get_webdriver(proxy={"url": "http://proxy"}, stealth_mode="standard")

    mock_backend.create_driver.assert_called_once_with({"url": "http://proxy"}, "standard")
    assert driver is mock_driver


def test_utils_get_webdriver_uses_config_stealth_mode(monkeypatch):
    from flaresolverr import utils

    mock_backend = MagicMock()
    mock_driver = MagicMock()
    mock_backend.create_driver.return_value = mock_driver
    monkeypatch.setattr(backends, "get_backend", lambda _name=None: mock_backend)
    monkeypatch.setattr(utils, "get_config_stealth_mode", lambda: "off")

    driver = utils.get_webdriver()

    mock_backend.create_driver.assert_called_once_with(None, "off")
    assert driver is mock_driver


def test_camoufox_backend_raises_import_error_when_not_installed():
    from flaresolverr.backends.camoufox import CamoufoxBackend

    backend = CamoufoxBackend()
    with pytest.raises(ImportError, match="camoufox is not installed"):
        backend.create_driver(None, "off")
