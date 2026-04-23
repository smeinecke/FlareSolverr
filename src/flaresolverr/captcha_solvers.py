"""Captcha solver plugins for FlareSolverr.

This module provides a pluggable interface for captcha solving services.
Currently supported:
- Built-in manual/automatic click (default)

Custom solvers can be added by subclassing CaptchaSolver and registering
them with SOLVER_MANAGER.register_solver().

Upstream references:
- https://github.com/FlareSolverr/FlareSolverr/issues/738
"""

import logging
import os
from abc import ABC, abstractmethod

from selenium.webdriver.chrome.webdriver import WebDriver


class CaptchaSolver(ABC):
    """Abstract base class for captcha solvers."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the solver is available/installed."""
        pass

    @abstractmethod
    def solve(self, driver: WebDriver, captcha_type: str) -> bool:
        """Attempt to solve the captcha.

        Args:
            driver: The WebDriver instance
            captcha_type: Type of captcha (e.g., 'hcaptcha', 'recaptcha', 'turnstile')

        Returns:
            True if solved successfully, False otherwise
        """
        pass


class DefaultSolver(CaptchaSolver):
    """Default solver that relies on FlareSolverr's built-in mechanisms."""

    name = "default"

    def is_available(self) -> bool:
        return True

    def solve(self, driver: WebDriver, captcha_type: str) -> bool:
        # Default solver doesn't do anything special
        # The main flaresolverr_service.py handles this
        logging.debug(f"Using default solver for {captcha_type}")
        return False


class SolverManager:
    """Manages available captcha solvers and routes to the appropriate one."""

    _solvers: dict[str, CaptchaSolver] = {}
    _default_solver: CaptchaSolver = DefaultSolver()

    def __init__(self):
        self._register_builtin_solvers()

    def _register_builtin_solvers(self) -> None:
        """Register built-in solver implementations."""
        pass

    def register_solver(self, solver: CaptchaSolver) -> None:
        """Register a new captcha solver."""
        self._solvers[solver.name] = solver

    def get_solver(self, name: str | None = None) -> CaptchaSolver:
        """Get a captcha solver by name.

        Args:
            name: Name of the solver. If None, returns the configured default.

        Returns:
            The requested captcha solver or the default solver if not found.
        """
        if name is None:
            name = get_config_captcha_solver()

        if name in self._solvers:
            return self._solvers[name]

        if name != "default":
            logging.warning(f"Captcha solver '{name}' not found, using default")

        return self._default_solver

    def list_available_solvers(self) -> list[str]:
        """List names of all available captcha solvers."""
        available = [name for name, solver in self._solvers.items() if solver.is_available()]
        available.append("default")
        return available

    def solve(self, driver: WebDriver, captcha_type: str, solver_name: str | None = None) -> bool:
        """Attempt to solve a captcha using the specified or default solver.

        Args:
            driver: The WebDriver instance
            captcha_type: Type of captcha to solve
            solver_name: Specific solver to use, or None for configured default

        Returns:
            True if solved successfully, False otherwise
        """
        solver = self.get_solver(solver_name)
        return solver.solve(driver, captcha_type)


# Global solver manager instance
SOLVER_MANAGER = SolverManager()


def get_config_captcha_solver() -> str:
    """Get the configured captcha solver from environment.

    Returns:
        Name of the captcha solver to use. Defaults to 'default'.
    """
    return os.environ.get("CAPTCHA_SOLVER", "default").lower()


def get_available_solvers() -> list[str]:
    """Get list of available captcha solver names."""
    return SOLVER_MANAGER.list_available_solvers()
