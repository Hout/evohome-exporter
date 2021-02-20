import unittest
from unittest.mock import MagicMock

import evohome_zookeeper


class TestZookeeper(unittest.TestCase):
    def test_partysize():
        zk = EvohomeZookeeper("hosts")


if __name__ == "__main__":
    unittest.main()
