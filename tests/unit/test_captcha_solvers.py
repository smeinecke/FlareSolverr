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


class TestPerRequestCaptchaSolverValidation:
    """Unit tests for captchaSolver request parameter validation."""

    def _make_service(self):
        import flaresolverr_service as svc
        return svc

    def test_invalid_solver_raises_on_request_get(self):
        """_cmd_request_get raises Exception for unknown captchaSolver."""
        from flaresolverr_service import _cmd_request_get
        from dtos import V1RequestBase

        req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "captchaSolver": "no-such-solver"})
        with pytest.raises(Exception, match="no-such-solver"):
            _cmd_request_get(req)

    def test_invalid_solver_raises_on_request_post(self):
        """_cmd_request_post raises Exception for unknown captchaSolver."""
        from flaresolverr_service import _cmd_request_post
        from dtos import V1RequestBase

        req = V1RequestBase({"cmd": "request.post", "url": "https://example.com", "postData": "a=b", "captchaSolver": "no-such-solver"})
        with pytest.raises(Exception, match="no-such-solver"):
            _cmd_request_post(req)

    def test_invalid_solver_error_lists_available(self):
        """Error message for invalid captchaSolver includes available solvers."""
        from flaresolverr_service import _cmd_request_get
        from dtos import V1RequestBase

        req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "captchaSolver": "no-such-solver"})
        with pytest.raises(Exception, match="default"):
            _cmd_request_get(req)

    def test_valid_default_solver_passes_validation(self, monkeypatch):
        """captchaSolver='default' passes validation and reaches _resolve_challenge."""
        from flaresolverr_service import _cmd_request_get
        from dtos import V1RequestBase

        req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "captchaSolver": "default"})
        monkeypatch.setattr("flaresolverr_service._resolve_challenge", lambda req, method: (_ for _ in ()).throw(StopIteration("reached")))
        with pytest.raises((StopIteration, Exception), match="reached"):
            _cmd_request_get(req)

    def test_none_captcha_solver_passes_validation(self, monkeypatch):
        """captchaSolver=None (absent) passes validation and reaches _resolve_challenge."""
        from flaresolverr_service import _cmd_request_get
        from dtos import V1RequestBase

        req = V1RequestBase({"cmd": "request.get", "url": "https://example.com"})
        monkeypatch.setattr("flaresolverr_service._resolve_challenge", lambda req, method: (_ for _ in ()).throw(StopIteration("reached")))
        with pytest.raises((StopIteration, Exception), match="reached"):
            _cmd_request_get(req)


class TestEffectiveSolverSelection:
    """Unit tests for per-request vs global solver resolution in _evil_logic."""

    def _make_req(self, captcha_solver=None):
        from dtos import V1RequestBase
        payload = {"cmd": "request.get", "url": "https://example.com"}
        if captcha_solver is not None:
            payload["captchaSolver"] = captcha_solver
        return V1RequestBase(payload)

    def _stub_evil_logic_deps(self, monkeypatch, *, challenge_found=True, captcha_type="hcaptcha"):
        """Patch all I/O-touching helpers in _evil_logic so it runs without a browser."""
        import captcha_solvers as cs
        import flaresolverr_service as svc

        calls = []

        def spy_solve(driver, ct, solver_name=None):
            calls.append(solver_name)
            return False  # return False so _wait_for_challenge is still skipped below

        monkeypatch.setattr(cs.SOLVER_MANAGER, "solve", spy_solve)
        monkeypatch.setattr(svc, "_configure_blocked_media", lambda *a: None)
        monkeypatch.setattr(svc, "_set_custom_headers", lambda *a: None)
        monkeypatch.setattr(svc, "_navigate_request", lambda *a: None)
        monkeypatch.setattr(svc, "_set_request_cookies", lambda *a: None)
        monkeypatch.setattr(svc, "_raise_if_access_denied", lambda *a: None)
        monkeypatch.setattr(svc, "_challenge_found", lambda *a: challenge_found)
        monkeypatch.setattr(svc, "_detect_captcha_type", lambda *a: captcha_type)
        monkeypatch.setattr(svc, "_wait_for_challenge", lambda *a: None)
        monkeypatch.setattr(svc, "_build_challenge_result", lambda *a: None)
        monkeypatch.setattr(svc.utils, "get_config_log_html", lambda: False)

        mock_driver = MockWebDriver()
        mock_driver.title = ""
        mock_driver.find_element = lambda by, tag: MagicMock(get_attribute=lambda a: "")
        mock_driver.current_url = "https://example.com"
        mock_driver.page_source = "<html><body>ok</body></html>"
        mock_driver.get_cookies = lambda: []

        return mock_driver, calls

    def test_per_request_solver_overrides_global_on_challenge(self, monkeypatch):
        """When captchaSolver is set on req and a challenge is found, that solver
        name is passed to SOLVER_MANAGER.solve instead of the global env var."""
        import captcha_solvers as cs
        import flaresolverr_service as svc

        class _CustomSolverA(cs.CaptchaSolver):
            name = "custom-solver-a"
            def is_available(self): return True
            def solve(self, driver, captcha_type): return False

        class _CustomSolverB(cs.CaptchaSolver):
            name = "custom-solver-b"
            def is_available(self): return True
            def solve(self, driver, captcha_type): return False

        cs.SOLVER_MANAGER.register_solver(_CustomSolverA())
        cs.SOLVER_MANAGER.register_solver(_CustomSolverB())
        monkeypatch.setenv("CAPTCHA_SOLVER", "custom-solver-a")

        mock_driver, calls = self._stub_evil_logic_deps(monkeypatch, challenge_found=True, captcha_type="hcaptcha")

        req = self._make_req(captcha_solver="custom-solver-b")
        svc._evil_logic(req, mock_driver, "GET")

        assert calls == ["custom-solver-b"]

    def test_absent_captcha_solver_uses_global_on_challenge(self, monkeypatch):
        """When captchaSolver is None and a challenge is found, the global
        CAPTCHA_SOLVER env var name is passed to SOLVER_MANAGER.solve."""
        import captcha_solvers as cs
        import flaresolverr_service as svc

        class _CustomSolverC(cs.CaptchaSolver):
            name = "custom-solver-c"
            def is_available(self): return True
            def solve(self, driver, captcha_type): return False

        cs.SOLVER_MANAGER.register_solver(_CustomSolverC())
        monkeypatch.setenv("CAPTCHA_SOLVER", "custom-solver-c")

        mock_driver, calls = self._stub_evil_logic_deps(monkeypatch, challenge_found=True, captcha_type="hcaptcha")

        req = self._make_req()  # no captchaSolver
        svc._evil_logic(req, mock_driver, "GET")

        assert calls == ["custom-solver-c"]

    def test_absent_captcha_solver_falls_back_to_global(self, monkeypatch):
        """When captchaSolver is None, global CAPTCHA_SOLVER env var is used."""
        monkeypatch.setenv("CAPTCHA_SOLVER", "custom-solver-c")

        req = self._make_req()
        assert req.captchaSolver is None
        assert get_config_captcha_solver() == "custom-solver-c"
