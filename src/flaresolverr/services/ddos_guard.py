"""DDoS-Guard challenge service."""

import logging

from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import staleness_of, title_is
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr.services.base import ChallengeService

SHORT_TIMEOUT = 1

DDOS_GUARD_TITLES = [
    "DDoS-Guard",
]


class DDoSGuardService(ChallengeService):
    name = "ddos_guard"

    def detect(self, driver: WebDriver) -> bool:
        page_title = (driver.title or "").strip()
        for title in DDOS_GUARD_TITLES:
            if title.lower() == page_title.lower():
                logging.info("Challenge detected. Title found: " + page_title)
                return True
        return False

    def resolve(self, driver: WebDriver) -> None:
        html_element = driver.find_element(By.TAG_NAME, "html")
        attempt = 0

        while True:
            attempt += 1
            try:
                for title in DDOS_GUARD_TITLES:
                    logging.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                    WebDriverWait(driver, SHORT_TIMEOUT).until_not(title_is(title))
                break
            except TimeoutException:
                logging.debug("Timeout waiting for selector")
                html_element = driver.find_element(By.TAG_NAME, "html")

        logging.debug("Waiting for redirect")
        try:
            WebDriverWait(driver, SHORT_TIMEOUT).until(staleness_of(html_element))
        except Exception:
            logging.debug("Timeout waiting for redirect")
