import logging

logger = logging.getLogger(__name__)

from bottle import response


def error_plugin(callback):
    """
    Bottle plugin to handle exceptions
    https://stackoverflow.com/a/32764250
    """

    def wrapper(*args, **kwargs):
        try:
            actual_response = callback(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error(str(e))
            actual_response = {"error": str(e)}
            response.status = 500
        return actual_response

    return wrapper
