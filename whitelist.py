"""Vulture whitelist for public API names and dynamically-used symbols.  # noqa: B018

These are referenced dynamically (e.g. bottle plugin loading, public client  # noqa: B018
library methods, model fields populated by dict unpacking) and appear unused  # noqa: B018
to static analysis, but are required at runtime.  # noqa: B018
"""

from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

from flaresolverr.bottle_plugins import error_plugin, logger_plugin, prometheus_plugin
from flaresolverr.client.actions import ActionQueue
from flaresolverr.client.client import _SessionManager
from flaresolverr.client.models import ChallengeSolution
from flaresolverr.dtos import ChallengeResolutionResultT
from flaresolverr.sessions import SessionsStorage

# Public _SessionManager API methods (called by users of the client library)
_SessionManager.cdp  # noqa: B018
_SessionManager.create  # noqa: B018
_SessionManager.destroy  # noqa: B018
_SessionManager.eval  # noqa: B018
_SessionManager.get  # noqa: B018
_SessionManager.list  # noqa: B018
_SessionManager.network  # noqa: B018
_SessionManager.screenshot  # noqa: B018
_SessionManager.click  # noqa: B018
_SessionManager.action  # noqa: B018
_SessionManager.clear  # noqa: B018

# Public ActionQueue fluent builder methods
ActionQueue.clear_context  # noqa: B018

# Model fields populated dynamically from API responses
ChallengeResolutionResultT.isBinary  # noqa: B018
ChallengeResolutionResultT.har  # noqa: B018
ChallengeSolution.evalResult  # noqa: B018
ChallengeSolution.networkLogs  # noqa: B018
ChallengeSolution.screenshot  # noqa: B018

# Bottle plugin entry points (loaded dynamically by Bottle framework)
error_plugin.plugin  # noqa: B018
logger_plugin.plugin  # noqa: B018
prometheus_plugin.plugin  # noqa: B018
prometheus_plugin.setup  # noqa: B018

# SessionsStorage internals
SessionsStorage.session_ids  # noqa: B018
SessionsStorage.stop_cleanup  # noqa: B018

# Attribute set on driver options by undetected_chromedriver
Options.binary_location  # noqa: B018

# Proxy extension attributes stored on WebDriver instances
WebDriver._proxy_ext_id  # noqa: B018

# Agent-check TCP server (handle is called by socketserver framework, daemon_threads by ThreadingMixIn)
from flaresolverr.agent_check import AgentCheckHandler, ThreadedTCPServer

AgentCheckHandler.handle  # noqa: B018
ThreadedTCPServer.daemon_threads  # noqa: B018

# HealthResponse model fields populated dynamically from dict unpacking
from flaresolverr.dtos import HealthResponse

HealthResponse.sessionsCount  # noqa: B018
HealthResponse.activeParallelRequests  # noqa: B018
HealthResponse.maxParallelRequests  # noqa: B018
HealthResponse.maxSessionCount  # noqa: B018
HealthResponse.sessionMaxRuntime  # noqa: B018
HealthResponse.sessionIdleTimeout  # noqa: B018
HealthResponse.version  # noqa: B018
HealthResponse.config  # noqa: B018
HealthResponse.activeRequests  # noqa: B018
HealthResponse.sessions  # noqa: B018

from flaresolverr.client.models import HealthResponse as ClientHealthResponse

ClientHealthResponse.sessionsCount  # noqa: B018
ClientHealthResponse.activeParallelRequests  # noqa: B018
ClientHealthResponse.maxParallelRequests  # noqa: B018
ClientHealthResponse.maxSessionCount  # noqa: B018
ClientHealthResponse.sessionMaxRuntime  # noqa: B018
ClientHealthResponse.sessionIdleTimeout  # noqa: B018
ClientHealthResponse.version  # noqa: B018
ClientHealthResponse.config  # noqa: B018
ClientHealthResponse.activeRequests  # noqa: B018
ClientHealthResponse.sessions  # noqa: B018
