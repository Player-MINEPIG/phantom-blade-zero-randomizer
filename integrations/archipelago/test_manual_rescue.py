import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from integrations.archipelago.manual_rescue import DEFAULT_BRIDGE, SESSION, _publish_new, queue_rescue, rescue_status


class ManualRescueTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.game = Path(folder.name)
        self.bridge = self.game / DEFAULT_BRIDGE
        self.bridge.mkdir(parents=True)
        self.heartbeat()

    def heartbeat(self, version="0.9.2", session="", age=0):
        elapsed = int(time.time()) - age
        (self.bridge / "alive.txt").write_text(f"{elapsed}\n{version}\n{session}\n", encoding="utf-8")

    def snapshot(self):
        return {path.name: path.read_bytes() for path in self.bridge.iterdir()}

    def test_cli_uses_the_default_bridge_and_queues_only_one_item(self):
        cli = [sys.executable, "-B", "-m", "integrations.archipelago.manual_rescue"]
        env = {**os.environ, "PYTHONUTF8": "1"}
        result = subprocess.run(
            [*cli, "grant", "BrutalAxe", "--game", str(self.game)], capture_output=True, env=env, check=True,
        )
        self.assertIn(b"BrutalAxe", result.stdout)
        session = (self.bridge / "session.txt").read_text(encoding="utf-8").strip()
        self.assertRegex(session, SESSION)
        self.assertEqual(
            (self.bridge / "inbox.txt").read_bytes(),
            f"{session}\nshachi\tBrutalAxe\tPhantom Weapon: Brutal Axe\tPBZ Seed Randomizer\n".encode(),
        )
        files = self.snapshot()
        retry = subprocess.run([*cli, "grant", "LionHead", "--bridge", str(self.bridge)], capture_output=True, env=env)
        self.assertEqual(retry.returncode, 1)
        self.assertEqual(self.snapshot(), files)

    def test_refuses_existing_multiworld_session_and_preserves_pending_bytes(self):
        (self.bridge / "session.txt").write_bytes(b"multiworld\n")
        (self.bridge / "inbox.txt").write_bytes(b"multiworld\nprop\tItem_1\tMaterial\tSender\n")
        files = self.snapshot()
        with self.assertRaisesRegex(ValueError, "已有会话"):
            queue_rescue(self.bridge, "ShachiHook")
        self.assertEqual(self.snapshot(), files)

    def test_refuses_stale_wrong_version_or_preexisting_in_game_session(self):
        for heartbeat, error in (
            ({"version": "0.9.3"}, "0.9.2"),
            ({"age": 30}, "心跳已过期"),
            ({"session": "previous"}, "仍使用现有会话"),
        ):
            with self.subTest(heartbeat=heartbeat):
                self.heartbeat(**heartbeat)
                with self.assertRaisesRegex(ValueError, error):
                    queue_rescue(self.bridge, "TigerCannon")
                self.assertEqual(set(self.snapshot()), {"alive.txt"})

    def test_status_distinguishes_an_attempt_from_a_confirmed_grant(self):
        session = queue_rescue(self.bridge, "LionHead")
        self.assertEqual(rescue_status(self.bridge), ("LionHead", "pending"))
        (self.bridge / f"applied_{session}.txt").write_bytes(b"1")
        self.assertEqual(rescue_status(self.bridge), ("LionHead", "processed"))
        (self.bridge / f"granted_{session}.txt").write_bytes(b"shachi:LionHead\n")
        self.assertEqual(rescue_status(self.bridge), ("LionHead", "granted"))

    def test_atomic_publish_rejects_a_file_created_by_another_process(self):
        source = self.bridge / "temporary"
        target = self.bridge / "inbox.txt"
        source.write_bytes(b"our request")
        target.write_bytes(b"another producer's request")
        with self.assertRaises(FileExistsError):
            _publish_new(source, target)
        self.assertEqual(target.read_bytes(), b"another producer's request")


if __name__ == "__main__":
    unittest.main()
