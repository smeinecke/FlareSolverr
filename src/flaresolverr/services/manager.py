"""Service manager for challenge detection/resolution."""

import logging

from flaresolverr.backends.browser_context import BrowserContext
from flaresolverr.services.base import ChallengeService


class ServiceManager:
    """Manages registered challenge services and routes detection/resolution."""

    def __init__(self):
        self._services: dict[str, ChallengeService] = {}
        self._register_builtin_services()

    def _register_builtin_services(self) -> None:
        """Register built-in challenge services."""
        pass

    def register(self, service: ChallengeService) -> None:
        """Register a challenge service."""
        self._services[service.name] = service

    def get_service(self, name: str) -> ChallengeService | None:
        """Get a registered challenge service by name."""
        return self._services.get(name)

    def detect(self, driver: BrowserContext, enabled_services: list[str]) -> str | None:
        """Detect which enabled service has an active challenge.

        Returns:
            Name of the detected service, or None if no challenge found.
        """
        for name in enabled_services:
            svc = self._services.get(name)
            if svc is None:
                logging.warning("Enabled service '%s' is not registered", name)
                continue
            if svc.detect(driver):
                logging.info("Challenge detected for service: %s", name)
                return name
        return None

    def resolve(self, driver: BrowserContext, service_name: str) -> None:
        """Resolve the challenge for the given service.

        Raises:
            Exception if the service is not registered or resolution fails.
        """
        svc = self._services.get(service_name)
        if svc is None:
            raise Exception(f"Challenge service '{service_name}' not found")
        svc.resolve(driver)
