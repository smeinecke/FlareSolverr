import os

from flaresolverr.backends.base import BackendBase
from flaresolverr.backends.browser_context import BrowserContext, get_browser_context

__all__ = ["BackendBase", "BrowserContext", "get_browser_context", "register_backend", "get_backend"]

_BACKENDS: dict[str, type[BackendBase]] = {}


def register_backend(name: str, backend_cls: type[BackendBase]) -> None:
    _BACKENDS[name] = backend_cls


def get_backend(name: str | None = None) -> BackendBase:
    if name is None:
        name = os.environ.get("DRIVER_BACKEND", "undetected_chromedriver")
    name = name.strip().lower()
    if name not in _BACKENDS:
        _register_defaults()
    if name not in _BACKENDS:
        raise ValueError(f"Unknown driver backend: {name!r}. Valid backends: {sorted(_BACKENDS)}")
    return _BACKENDS[name]()


def _register_defaults() -> None:
    from flaresolverr.backends.undetected_chrome import UndetectedChromeBackend
    from flaresolverr.backends.seleniumbase import SeleniumBaseBackend
    from flaresolverr.backends.camoufox import CamoufoxBackend

    register_backend("undetected_chromedriver", UndetectedChromeBackend)
    register_backend("seleniumbase", SeleniumBaseBackend)
    register_backend("camoufox", CamoufoxBackend)
