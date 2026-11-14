"""Challenge services package."""

from flaresolverr.services.base import ChallengeService
from flaresolverr.services.brave import BraveService
from flaresolverr.services.cloudflare import CloudflareService
from flaresolverr.services.ddos_guard import DDoSGuardService
from flaresolverr.services.manager import ServiceManager
from flaresolverr.services.powblock import PowBlockService

__all__ = [
    "SERVICE_MANAGER",
    "BraveService",
    "ChallengeService",
    "CloudflareService",
    "DDoSGuardService",
    "PowBlockService",
    "ServiceManager",
]

SERVICE_MANAGER = ServiceManager()
SERVICE_MANAGER.register(CloudflareService())
SERVICE_MANAGER.register(DDoSGuardService())
SERVICE_MANAGER.register(PowBlockService())
SERVICE_MANAGER.register(BraveService())
