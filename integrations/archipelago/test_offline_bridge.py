from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from integrations.archipelago.offline_bridge import OfflineBridge
from randomizer.engine import generate
from test_catalog import load_data


class OfflineBridgeTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.bridge_dir = self.root / "bridge"
        self.bridge_dir.mkdir()
        self.save_dir = self.root / "ProjectPBZ" / "Saved" / "SaveGames" / "Steam" / "76561198000000000"
        self.save_dir.mkdir(parents=True)
        self.plan = generate(load_data("catalog"), {"seed": "offline-test", "item_mode": "collectibles"})

    def start(self):
        return OfflineBridge(self.bridge_dir, self.plan, "test", self.save_dir)

    def heartbeat(self, session):
        (self.bridge_dir / "alive.txt").write_text(f"0\n0.9.2\n{session}\n", encoding="utf-8")

    def snapshot(self, *check_ids):
        (self.bridge_dir / "outbox.txt").write_text("".join(f"{check_id}\n" for check_id in check_ids), encoding="utf-8")

    def inbox(self):
        return (self.bridge_dir / "inbox.txt").read_text(encoding="utf-8").splitlines()

    def test_refuses_existing_save_and_unowned_bridge(self):
        save = self.save_dir / "PBZSaveGame.sav"
        save.write_text("original", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already contains a save"):
            self.start()
        self.assertEqual(save.read_text(encoding="utf-8"), "original")
        self.assertEqual(list(self.bridge_dir.iterdir()), [])
        (self.bridge_dir / "session.txt").write_text("multiworld", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected entry"):
            self.start()
        self.assertEqual((self.bridge_dir / "session.txt").read_text(encoding="utf-8"), "multiworld")

    def test_waits_for_matching_heartbeat(self):
        bridge = self.start()
        check = min(bridge.assignments)
        self.snapshot(check)
        self.assertEqual(bridge.poll(), 0)
        self.assertEqual(self.inbox(), [bridge.session])
        self.heartbeat("another_session")
        with self.assertRaisesRegex(ValueError, "different bridge session"):
            bridge.poll()
        self.assertEqual(self.inbox(), [bridge.session])

    def test_appends_unique_checks_and_restores_missing_inbox(self):
        bridge = self.start()
        self.heartbeat(bridge.session)
        low, middle, high = sorted(bridge.assignments)[:3]
        self.snapshot(high)
        self.assertEqual(bridge.poll(), 1)
        initial = self.inbox()
        self.snapshot(high, low, high, middle)
        self.assertEqual(bridge.poll(), 2)
        self.assertEqual(bridge.poll(), 0)
        lines = self.inbox()
        self.assertEqual(lines[:2], initial)
        self.assertEqual([line.split("\t")[1] for line in lines[1:]], [bridge.assignments[key][0] for key in (high, low, middle)])

        (self.bridge_dir / "inbox.txt").unlink()
        (self.save_dir / "PBZSaveGame.sav").touch()
        restarted = OfflineBridge(self.bridge_dir, self.plan, "test")
        self.assertEqual(restarted.poll(), 0)
        self.assertEqual(self.inbox(), lines)

    def test_rejects_foreign_checks_and_different_run(self):
        bridge = self.start()
        self.heartbeat(bridge.session)
        self.snapshot(1)
        with self.assertRaisesRegex(ValueError, "unexpected reward check"):
            bridge.poll()
        with self.assertRaisesRegex(ValueError, "different plan or run ID"):
            OfflineBridge(self.bridge_dir, self.plan, "another-run")
        self.assertEqual(self.inbox(), [bridge.session])
