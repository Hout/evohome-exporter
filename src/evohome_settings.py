from dataclasses import dataclass
from typing import Optional
from os import environ
import logging

USERNAME_ENV_VAR = "EVOHOME_USERNAME"
PASSWORD_ENV_VAR = "EVOHOME_PASSWORD"

POLL_INTERVAL_ENV_VAR = "EVOHOME_POLL_INTERVAL"
SCRAPE_PORT_ENV_VAR = "EVOHOME_SCRAPE_PORT"
ZK_SERVICE_ENV_VAR = "EVOHOME_ZK_SERVICE"
EXPIRY_ENV_VAR = "EVOHOME_EXPIRY"


@dataclass
class EvohomeSettings:
    def __init__(self):
        try:
            self._username = environ[USERNAME_ENV_VAR].strip()
        except KeyError:
            logging.error(
                f"Environment variable ({USERNAME_ENV_VAR}) for Evohome username missing"
            )
            exit(1)

        try:
            self._password = environ[PASSWORD_ENV_VAR].strip()
        except KeyError:
            logging.error(
                f"Environment variable ({PASSWORD_ENV_VAR}) for Evohome password missing"
            )
            exit(1)

        self._poll_interval = int(environ.get(POLL_INTERVAL_ENV_VAR, 60))
        self._scrape_port = int(environ.get(SCRAPE_PORT_ENV_VAR, 8082))
        self._expiry = int(environ.get(EXPIRY_ENV_VAR, 30))
        self._zk_service = environ.get(ZK_SERVICE_ENV_VAR, "localhost").strip()

        logging.info("Evohome exporter settings:")
        logging.info(self)

    def __repr__(self) -> str:
        return (
            "Settings:\n"
            f"Username: {self._username}\n"
            f"Password length {len(self._password)}\n"
            f"Poll interval: {self._poll_interval}\n"
            f"Scrape port: {self._scrape_port}\n"
            f"Zookeeper service: {self._zk_service}\n"
            f"Expiry: {self._expiry}\n"
        )

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, username: str) -> None:
        self._username = username

    @property
    def password(self) -> Optional[str]:
        return self._password

    @password.setter
    def password(self, password: str) -> None:
        self._password = password

    @property
    def poll_interval(self) -> int:
        return self._poll_interval

    @poll_interval.setter
    def poll_interval(self, poll_interval: int) -> None:
        self._poll_interval = poll_interval

    @property
    def scrape_port(self) -> int:
        return self._scrape_port

    @scrape_port.setter
    def scrape_port(self, scrape_port: int) -> None:
        self._scrape_port = scrape_port

    @property
    def expiry(self) -> int:
        return self._expiry

    @expiry.setter
    def expiry(self, expiry: int) -> None:
        self._expiry = expiry

    @property
    def zk_service(self) -> str:
        return self._zk_service

    @zk_service.setter
    def zk_service(self, zk_service: str) -> None:
        self._zk_service = zk_service
