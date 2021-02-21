import json
import logging
import time
import uuid
from typing import Optional, Any, List

from kazoo.client import KazooClient
from kazoo.recipe.party import ShallowParty
from kazoo.exceptions import NoNodeError

from evohome_types import ZoneSchedule, Token, Temperatures

ZK_BASE_PATH = "/evohome"
ZK_PARTY_PATH = f"{ZK_BASE_PATH}/party"
ZK_SCHEDULES_PATH = f"{ZK_BASE_PATH}/schedules"

ZK_TEMPERATURES_NODE = "temperatures"
ZK_TOKEN_NODE = "token"
ZK_LOCK_NODE = "lock"

ZK_TOKEN_PATH = f"{ZK_BASE_PATH}/{ZK_TOKEN_NODE}"


class EvohomeZookeeper:
    def __init__(self, hosts):
        self._client_id = str(uuid.uuid4())
        self._logger = logging.getLogger(f"{__name__}-{self._client_id}")
        self._zk = KazooClient(hosts=hosts)
        self._zk.start()
        self._zk.ensure_path(ZK_BASE_PATH)
        self._zk.ensure_path(ZK_PARTY_PATH)
        self._zk.ensure_path(ZK_SCHEDULES_PATH)
        self._party = ShallowParty(self._zk, ZK_PARTY_PATH, identifier=self._client_id)
        self._party.join()

    def party_data(self):
        party = sorted(list(self._party))
        return len(party), party.index(self._client_id)

    def watch_party(self):
        party = sorted(list(self._party))
        return len(party), party.index(self._client_id)

    def get_temperatures(self, timeout: int = 59) -> Optional[Temperatures]:
        try:
            data, stat = self._zk.get(f"{ZK_BASE_PATH}/{ZK_TEMPERATURES_NODE}/")
            self._logger.debug(f"Last modified {stat.last_modified}")
            self._logger.debug(f"Time {int(time.time())}")
            self._logger.debug(f"Timeout {timeout}")
            self._logger.debug(f"Time - timeout {int(time.time()) - timeout}")
            if stat.last_modified < int(time.time()) - timeout:
                self._logger.info("Stored temperatures are stale")
                return None
            return json.loads(data.decode("utf-8"))
        except NoNodeError:
            self._logger.warn("No temperature node exists yet")
            return None

    def watch_temperatures(self, watcher) -> None:
        self._zk.get(f"{ZK_BASE_PATH}/{ZK_TEMPERATURES_NODE}", watcher)

    def set_temperatures(self, temperatures: Temperatures) -> None:
        self._zk.set(
            f"{ZK_BASE_PATH}/{ZK_TEMPERATURES_NODE}",
            json.dumps(temperatures).encode("utf-8"),
        )

    def lock_token(self) -> Any:
        return self._zk.Lock(ZK_BASE_PATH, ZK_LOCK_NODE)

    def get_token(self) -> Token:
        return json.loads(self._zk.get(ZK_TOKEN_PATH)[0].decode("utf-8"))

    def set_token(self, token: Token) -> None:
        self._zk.set(ZK_TOKEN_PATH, json.dumps(token).encode("utf-8"))

    def cleanup_schedule_zones(self, client_zone_ids: List[str]) -> None:
        stored_zone_ids = self._zk.get_children(ZK_SCHEDULES_PATH)
        to_delete = set(stored_zone_ids) - set(client_zone_ids)
        for zone_id in to_delete:
            self._zk.delete(f"{ZK_SCHEDULES_PATH}/{zone_id}")

    def get_schedule(self, zone_id: str, timeout: int = 3600) -> Optional[ZoneSchedule]:
        data, stat = self._zk.get(f"{ZK_SCHEDULES_PATH}/{zone_id}")
        self._logger.debug(f"Last modified {stat.last_modified}")
        self._logger.debug(f"Time {int(time.time())}")
        self._logger.debug(f"Timeout {timeout}")
        self._logger.debug(f"Time - timeout {int(time.time()) - timeout}")
        if stat.last_modified < int(time.time()) - timeout:
            self._logger.info("Stored schedule is stale")
            return None
        return json.loads(data.decode("utf-8"))

    def set_schedule(self, zone_id: str, schedule: ZoneSchedule) -> None:
        self._zk.set(
            f"{ZK_SCHEDULES_PATH}/{zone_id}", json.dumps(schedule).encode("utf-8")
        )

    def watch_schedule(self, zone_id, watcher) -> None:
        self._zk.get(f"{ZK_SCHEDULES_PATH}/{zone_id}", watcher)
