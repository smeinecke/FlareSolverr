"""Tests for the pluggable captcha solver framework.

References: https://github.com/FlareSolverr/FlareSolverr/issues/738
"""

import os
from unittest.mock import MagicMock, patch

import pytest

import captcha_solvers as solvers_module
from captcha_solvers import (
    CaptchaSolver,
    DefaultSolver,
    HCaptchaChallengerSolver,
    ReCaptchaChallengerSolver,
    SolverManager,
    get_config_captcha_solver,
    get_available_solvers,
    SOLVER_MANAGER,
)


class MockWebDriver:
    """Mock WebDriver for testing."""

    def __init__(self):
        self.current_url = "https://example.com"
        self.page_source = "<html></html>"

    def find_elements(self, by, value):
        return []


class TestCaptchaSolverBase:
    """Tests for the abstract CaptchaSolver base class."""

    def test_captcha_solver_is_abstract(self):
        """Test that CaptchaSolver cannot be instantiated directly."""
        with pytest.raises(TypeError):
            CaptchaSolver()

    def test_custom_solver_can_be_created(self):
        """Test that a custom solver can be created by subclassing."""

        class TestSolver(CaptchaSolver):
            name = "test-solver"

            def is_available(self):
                return True

            def solve(self, driver, captcha_type):
                return True

        solver = TestSolver()
        assert solver.name == "test-solver"
        assert solver.is_available()
        assert solver.solve(None, "test")


class TestDefaultSolver:
    """Tests for the DefaultSolver implementation."""

    def test_default_solver_always_available(self):
        """Test that DefaultSolver is always available."""
        solver = DefaultSolver()
        assert solver.is_available()

    def test_default_solver_returns_false(self):
        """Test that DefaultSolver.solve returns False (uses built-in mechanisms)."""
        solver = DefaultSolver()
        mock_driver = MockWebDriver()
        result = solver.solve(mock_driver, "hcaptcha")
        assert result is False

    def test_default_solver_name(self):
        """Test DefaultSolver has correct name."""
        solver = DefaultSolver()
        assert solver.name == "default"


class TestHCaptchaChallengerSolver:
    """Tests for HCaptchaChallengerSolver."""

    def test_hcaptcha_solver_name(self):
        """Test HCaptchaChallengerSolver has correct name."""
        solver = HCaptchaChallengerSolver()
        assert solver.name == "hcaptcha-challenger"

    def test_hcaptcha_solver_unavailable_without_library(self):
        """Test that solver is unavailable when library not installed."""
        # The solver checks for import, which should fail in test environment
        solver = HCaptchaChallengerSolver()
        # Should be unavailable since we don't have the actual library
        assert not solver.is_available()

    def test_hcaptcha_solver_returns_false_when_unavailable(self):
        """Test solve returns False when solver unavailable."""
        solver = HCaptchaChallengerSolver()
        mock_driver = MockWebDriver()
        result = solver.solve(mock_driver, "hcaptcha")
        assert result is False

    def test_hcaptcha_solver_only_handles_hcaptcha(self):
        """Test that solver only attempts to solve hcaptcha type."""
        solver = HCaptchaChallengerSolver()
        mock_driver = MockWebDriver()
        # Should return False for non-hcaptcha types
        result = solver.solve(mock_driver, "recaptcha")
        assert result is False


class TestReCaptchaChallengerSolver:
    """Tests for ReCaptchaChallengerSolver."""

    def test_recaptcha_solver_name(self):
        """Test ReCaptchaChallengerSolver has correct name."""
        solver = ReCaptchaChallengerSolver()
        assert solver.name == "recaptcha-challenger"

    def test_recaptcha_solver_unavailable_without_library(self):
        """Test that solver is unavailable when library not installed."""
        solver = ReCaptchaChallengerSolver()
        assert not solver.is_available()

    def test_recaptcha_solver_returns_false_when_unavailable(self):
        """Test solve returns False when solver unavailable."""
        solver = ReCaptchaChallengerSolver()
        mock_driver = MockWebDriver()
        result = solver.solve(mock_driver, "recaptcha")
        assert result is False

    def test_recaptcha_solver_handles_recaptcha_types(self):
        """Test that solver handles various recaptcha types."""
        solver = ReCaptchaChallengerSolver()
        mock_driver = MockWebDriver()

        # Should attempt recaptcha types
        for captcha_type in ["recaptcha", "recaptcha-v2", "recaptcha-v3"]:
            # Since solver is unavailable, should still return False
            result = solver.solve(mock_driver, captcha_type)
            assert result is False

    def test_recaptcha_solver_ignores_other_types(self):
        """Test that solver ignores non-recaptcha types."""
        solver = ReCaptchaChallengerSolver()
        mock_driver = MockWebDriver()
        result = solver.solve(mock_driver, "hcaptcha")
        assert result is False


class TestSolverManager:
    """Tests for SolverManager."""

    def test_solver_manager_has_default_solver(self):
        """Test that SolverManager always has default solver."""
        manager = SolverManager()
        default = manager.get_solver("default")
        assert isinstance(default, DefaultSolver)

    def test_solver_manager_registers_solvers(self):
        """Test that solvers can be registered."""
        manager = SolverManager()

        class TestSolver(CaptchaSolver):
            name = "test"

            def is_available(self):
                return True

            def solve(self, driver, captcha_type):
                return True

        test_solver = TestSolver()
        manager.register_solver(test_solver)

        retrieved = manager.get_solver("test")
        assert retrieved is test_solver

    def test_solver_manager_get_solver_default(self):
        """Test getting solver with default fallback."""
        manager = SolverManager()
        solver = manager.get_solver()
        assert isinstance(solver, DefaultSolver)

    def test_solver_manager_get_solver_unknown_returns_default(self):
        """Test that unknown solver name returns default."""
        manager = SolverManager()
        solver = manager.get_solver("nonexistent")
        assert isinstance(solver, DefaultSolver)

    def test_solver_manager_list_available(self):
        """Test listing available solvers."""
        manager = SolverManager()
        available = manager.list_available_solvers()
        assert "default" in available

    def test_solver_manager_solve_routes_to_solver(self):
        """Test that solve method routes to appropriate solver."""
        manager = SolverManager()

        mock_driver = MockWebDriver()
        result = manager.solve(mock_driver, "hcaptcha", "default")
        # Default solver returns False
        assert result is False


class TestEnvironmentConfiguration:
    """Tests for environment-based configuration."""

    def test_get_config_captcha_solver_default(self):
        """Test default captcha solver configuration."""
        # Ensure environment is clean
        with patch.dict(os.environ, {}, clear=True):
            solver = get_config_captcha_solver()
            assert solver == "default"

    def test_get_config_captcha_solver_from_env(self):
        """Test captcha solver from environment variable."""
        with patch.dict(os.environ, {"CAPTCHA_SOLVER": "hcaptcha-challenger"}):
            solver = get_config_captcha_solver()
            assert solver == "hcaptcha-challenger"

    def test_get_config_captcha_solver_case_insensitive(self):
        """Test that solver name is lowercased."""
        with patch.dict(os.environ, {"CAPTCHA_SOLVER": "HCAPTCHA-CHALLENGER"}):
            solver = get_config_captcha_solver()
            assert solver == "hcaptcha-challenger"


class TestGlobalSolverManager:
    """Tests for the global SOLVER_MANAGER instance."""

    def test_global_solver_manager_exists(self):
        """Test that global SOLVER_MANAGER exists."""
        assert SOLVER_MANAGER is not None
        assert isinstance(SOLVER_MANAGER, SolverManager)

    def test_get_available_solvers(self):
        """Test get_available_solvers helper function."""
        available = get_available_solvers()
        assert isinstance(available, list)
        assert "default" in available


class TestCaptchaDetection:
    """Tests for captcha detection functionality."""

    def test_detect_captcha_type_hcaptcha(self, monkeypatch):
        """Test detection of hCaptcha on page."""
        from flaresolverr_service import _detect_captcha_type

        mock_driver = MockWebDriver()

        # Mock find_elements to return hCaptcha element
        def mock_find_hcaptcha(by, value):
            if "hcaptcha" in value or "h-captcha" in value:
                return [MagicMock()]  # Simulate found element
            return []

        mock_driver.find_elements = mock_find_hcaptcha

        result = _detect_captcha_type(mock_driver)
        assert result == "hcaptcha"

    def test_detect_captcha_type_recaptcha(self, monkeypatch):
        """Test detection of reCAPTCHA on page."""
        from flaresolverr_service import _detect_captcha_type

        mock_driver = MockWebDriver()

        # Mock find_elements to return reCAPTCHA element
        def mock_find_recaptcha(by, value):
            if "recaptcha" in value or "g-recaptcha" in value:
                return [MagicMock()]
            return []

        mock_driver.find_elements = mock_find_recaptcha

        result = _detect_captcha_type(mock_driver)
        assert result == "recaptcha"

    def test_detect_captcha_type_turnstile(self, monkeypatch):
        """Test detection of Turnstile on page."""
        from flaresolverr_service import _detect_captcha_type

        mock_driver = MockWebDriver()

        # Mock find_elements to return Turnstile element
        def mock_find_turnstile(by, value):
            if "turnstile" in value or "cf-turnstile" in value:
                return [MagicMock()]
            return []

        mock_driver.find_elements = mock_find_turnstile

        result = _detect_captcha_type(mock_driver)
        assert result == "turnstile"

    def test_detect_captcha_type_none(self, monkeypatch):
        """Test detection when no captcha present."""
        from flaresolverr_service import _detect_captcha_type

        mock_driver = MockWebDriver()

        # Mock find_elements to always return empty
        def mock_find_none(by, value):
            return []

        mock_driver.find_elements = mock_find_none

        result = _detect_captcha_type(mock_driver)
        assert result is None


class TestIntegration:
    """Integration tests for the captcha solver framework."""

    def test_full_solver_flow_with_default(self):
        """Test complete flow with default solver."""
        manager = SolverManager()
        mock_driver = MockWebDriver()

        # Test full flow
        captcha_type = "unknown"
        result = manager.solve(mock_driver, captcha_type)

        # Default solver should return False
        assert result is False

    def test_solver_manager_with_configured_solver(self, monkeypatch):
        """Test solver manager respects configured solver."""
        monkeypatch.setenv("CAPTCHA_SOLVER", "default")

        configured = get_config_captcha_solver()
        assert configured == "default"

        # Get solver using configured name
        solver = SOLVER_MANAGER.get_solver(configured)
        assert isinstance(solver, DefaultSolver)
