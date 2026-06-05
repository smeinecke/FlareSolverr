"""Vulture whitelist for public API names and dynamically-used symbols.

These are referenced dynamically (e.g. bottle plugin loading, public client
library methods, model fields populated by dict unpacking) and appear unused
to static analysis, but are required at runtime.
"""

from flaresolverr.bottle_plugins import error_plugin, logger_plugin, prometheus_plugin
from flaresolverr.client.actions import ActionQueue
from flaresolverr.client.client import _SessionManager
from flaresolverr.client.models import ChallengeSolution
from flaresolverr.dtos import ChallengeResolutionResultT
from flaresolverr.sessions import SessionsStorage
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

# Public _SessionManager API methods (called by users of the client library)
_SessionManager.cdp
_SessionManager.create
_SessionManager.destroy
_SessionManager.eval
_SessionManager.get
_SessionManager.list
_SessionManager.network
_SessionManager.screenshot
_SessionManager.click
_SessionManager.action
_SessionManager.clear

# Public ActionQueue fluent builder methods
ActionQueue.clear_context

# Model fields populated dynamically from API responses
ChallengeResolutionResultT.isBinary
ChallengeSolution.evalResult
ChallengeSolution.networkLogs
ChallengeSolution.screenshot

# Bottle plugin entry points (loaded dynamically by Bottle framework)
error_plugin.plugin
logger_plugin.plugin
prometheus_plugin.plugin
prometheus_plugin.setup

# SessionsStorage internals
SessionsStorage.session_ids
SessionsStorage.stop_cleanup

# Attribute set on driver options by undetected_chromedriver
Options.binary_location

# Proxy extension attributes stored on WebDriver instances
WebDriver._proxy_ext_id
