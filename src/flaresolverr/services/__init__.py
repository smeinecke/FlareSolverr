"""Challenge services package."""

from flaresolverr.services.base import ChallengeService
from flaresolverr.services.brave import BraveService
from flaresolverr.services.cloudflare import CloudflareService
from flaresolverr.services.ddos_guard import DDoSGuardService
from flaresolverr.services.manager import ServiceManager

__all__ = [
    "SERVICE_MANAGER",
    "BraveService",
    "ChallengeService",
    "CloudflareService",
    "DDoSGuardService",
    "ServiceManager",
]

SERVICE_MANAGER = ServiceManager()
SERVICE_MANAGER.register(CloudflareService())
SERVICE_MANAGER.register(DDoSGuardService())
SERVICE_MANAGER.register(BraveService())
