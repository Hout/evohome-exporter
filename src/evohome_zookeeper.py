import json
import logging
import time
import uuid
from typing import Optional, Any, List

from kazoo.client import KazooClient
from kazoo.recipe.party import Party

from evohome_types import ZoneSchedule, Token

ZK_BASE_PATH = "/evohome"
ZK_PARTY_PATH = f"{ZK_BASE_PATH}/party"
ZK_SCHEDULES_PATH = f"{ZK_BASE_PATH}/schedules"

ZK_TOKEN_NODE = "token"
ZK_LOCK_NODE = "lock"

ZK_TOKEN_PATH = f"{ZK_BASE_PATH}/{ZK_TOKEN_NODE}"


class EvohomeZookeeper:
    def __init__(self, hosts):
        self.zk = KazooClient(hosts=hosts)
        self.zk.start()
        self.zk.ensure_path(ZK_BASE_PATH)
        self.zk.ensure_path(ZK_PARTY_PATH)
        self.zk.ensure_path(ZK_SCHEDULES_PATH)
        self.client_id = uuid.uuid4()
        self.party = Party(self.zk, ZK_PARTY_PATH, identifier=self.client_id)
        self.party.join()

    def party_size(self):
        return len(self.party)

    def party_position(self):
        sorted_nodes = sorted(list(self.party))
        return sorted_nodes.index(self.client_id)

    def lock_token(self) -> Any:
        return self.zk.Lock(ZK_BASE_PATH, ZK_LOCK_NODE)

    def get_token(self) -> Token:
        return json.loads(self.zk.get(ZK_TOKEN_PATH)[0].decode("utf-8"))

    def set_token(self, token: Token) -> None:
        self.zk.set(ZK_TOKEN_PATH, json.dumps(token).encode("utf-8"))

    def cleanup_schedule_zones(self, client_zone_ids: List[str]) -> None:
        stored_zone_ids = self.zk.get_children(ZK_SCHEDULES_PATH)
        to_delete = set(stored_zone_ids) - set(client_zone_ids)
        for zone_id in to_delete:
            self.zk.delete(f"{ZK_SCHEDULES_PATH}/{zone_id}")

    def get_schedule(
        self, zone_id: str, timeout: float = 1.0 / 24
    ) -> Optional[ZoneSchedule]:
        data, stat = self.zk.get(f"{ZK_SCHEDULES_PATH}/{zone_id}")
        if stat.last_modified < time.time() - timeout:
            logging.info("Stored schedule is stale")
            return None
        return json.loads(data.decode("utf-8"))

    def set_schedule(self, zone_id: str, schedule: ZoneSchedule) -> None:
        self.zk.set(
            f"{ZK_SCHEDULES_PATH}/{zone_id}", json.dumps(schedule).encode("utf-8")
        )
