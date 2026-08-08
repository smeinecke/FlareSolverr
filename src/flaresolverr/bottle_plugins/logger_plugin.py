import logging

logger = logging.getLogger(__name__)
import os

from bottle import request, response


def _get_remote_addr() -> str:
    if os.environ.get("TRUST_PROXY", "false").lower() == "true":
        forwarded = request.get_header("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def logger_plugin(callback):
    """
    Bottle plugin to use logging module
    https://bottlepy.org/docs/dev/plugindev.html

    Wrap a Bottle request so that a log line is emitted after it's handled.
    (This decorator can be extended to take the desired logger as a param.)
    """

    def wrapper(*args, **kwargs):
        actual_response = callback(*args, **kwargs)
        if not request.url.endswith("/health"):
            logger.info(f"{_get_remote_addr()} {request.method} {request.url} {response.status}")
        return actual_response

    return wrapper
