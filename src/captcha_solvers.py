"""Captcha solver plugins for FlareSolverr.

This module provides a pluggable interface for captcha solving services.
Currently supported:
- Built-in manual/automatic click (default)
- hcaptcha-challenger (AI-based hCaptcha solver)
- recaptcha-challenger (AI-based reCAPTCHA solver)

Upstream references:
- https://github.com/FlareSolverr/FlareSolverr/issues/738
- https://github.com/QIN2DIM/hcaptcha-challenger
- https://github.com/QIN2DIM/recaptcha-challenger
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


class HCaptchaChallengerSolver(CaptchaSolver):
    """Solver using hcaptcha-challenger library.

    This is an AI-based solver that uses multimodal large language models
    to solve hCaptcha challenges without third-party services.

    Install: pip install hcaptcha-challenger
    Docs: https://github.com/QIN2DIM/hcaptcha-challenger
    """

    name = "hcaptcha-challenger"

    def __init__(self):
        self._solver = None
        self._init_solver()

    def _init_solver(self) -> None:
        """Initialize the hcaptcha-challenger solver if available."""
        try:
            # Try to import hcaptcha-challenger
            import hcaptcha_challenger as solver  # type: ignore[import]

            self._solver = solver
            logging.info("hcaptcha-challenger solver loaded successfully")
        except ImportError:
            logging.debug("hcaptcha-challenger not installed, solver unavailable")
            self._solver = None

    def is_available(self) -> bool:
        return self._solver is not None

    def solve(self, driver: WebDriver, captcha_type: str) -> bool:
        """Attempt to solve hCaptcha using hcaptcha-challenger.

        Note: This is a placeholder implementation. Full integration would
        require:
        1. Proper initialization with API keys if needed
        2. Challenge detection and classification
        3. Image processing and model inference
        4. Challenge response submission

        See: https://github.com/QIN2DIM/hcaptcha-challenger for full API
        """
        if not self.is_available():
            logging.warning("hcaptcha-challenger not available")
            return False

        if captcha_type != "hcaptcha":
            return False

        try:
            logging.info("Attempting to solve hCaptcha with hcaptcha-challenger")
            # Placeholder: Actual implementation would use the solver's API
            # Example (pseudo-code):
            # challenge = self._solver.classify(driver.page_source)
            # result = self._solver.solve(challenge, driver)
            # return result.success

            logging.warning("hcaptcha-challenger integration is a work in progress")
            return False
        except Exception as e:
            logging.error(f"hcaptcha-challenger solve failed: {e}")
            return False


class ReCaptchaChallengerSolver(CaptchaSolver):
    """Solver using recaptcha-challenger library.

    This is an AI-based solver for reCAPTCHA challenges.

    Install: pip install recaptcha-challenger
    Docs: https://github.com/QIN2DIM/recaptcha-challenger
    """

    name = "recaptcha-challenger"

    def __init__(self):
        self._solver = None
        self._init_solver()

    def _init_solver(self) -> None:
        """Initialize the recaptcha-challenger solver if available."""
        try:
            # Try to import recaptcha-challenger
            import recaptcha_challenger as solver  # type: ignore[import]

            self._solver = solver
            logging.info("recaptcha-challenger solver loaded successfully")
        except ImportError:
            logging.debug("recaptcha-challenger not installed, solver unavailable")
            self._solver = None

    def is_available(self) -> bool:
        return self._solver is not None

    def solve(self, driver: WebDriver, captcha_type: str) -> bool:
        """Attempt to solve reCAPTCHA using recaptcha-challenger."""
        if not self.is_available():
            logging.warning("recaptcha-challenger not available")
            return False

        if captcha_type not in ["recaptcha", "recaptcha-v2", "recaptcha-v3"]:
            return False

        try:
            logging.info("Attempting to solve reCAPTCHA with recaptcha-challenger")
            # Placeholder: Full implementation would use the solver's API
            logging.warning("recaptcha-challenger integration is a work in progress")
            return False
        except Exception as e:
            logging.error(f"recaptcha-challenger solve failed: {e}")
            return False


class SolverManager:
    """Manages available captcha solvers and routes to the appropriate one."""

    _solvers: dict[str, CaptchaSolver] = {}
    _default_solver: CaptchaSolver = DefaultSolver()

    def __init__(self):
        self._register_builtin_solvers()

    def _register_builtin_solvers(self) -> None:
        """Register built-in solver implementations."""
        # Register hcaptcha-challenger
        hc_solver = HCaptchaChallengerSolver()
        if hc_solver.is_available():
            self.register_solver(hc_solver)
            logging.info(f"Registered captcha solver: {hc_solver.name}")

        # Register recaptcha-challenger
        rc_solver = ReCaptchaChallengerSolver()
        if rc_solver.is_available():
            self.register_solver(rc_solver)
            logging.info(f"Registered captcha solver: {rc_solver.name}")

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
