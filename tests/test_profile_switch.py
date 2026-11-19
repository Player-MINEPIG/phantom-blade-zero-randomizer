from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pbzmod import profile_switch as profiles
from pbzmod.reward_layout import resolve_layout


class ProfileSwitchTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.seeds = self.root / "Seeds"
        self.base = self.seeds / "示例"
        self.base.mkdir(parents=True)
        self.saves = self.root / "Saves"
        self.saves.mkdir()
        self.save = self.saves / "PBZSaveGame.sav"
        self.save.write_bytes(b"save bytes owned by the game")
        self.name = "测试战役"
        self.permutation = {"地面": "首领", "首领": "地面"}
        self.original_ledger = {"enabled": True, "vanillaClaimed": [], "claims": []}
        self.write_json(self.base / "layout.json", {"schema": 1, "baseSeed": self.base.name})
        self.write_json(self.base / "ledger.json", self.original_ledger)
        self.write_json(self.base / "permutation.json", self.permutation)
        self.write_json(self.base / "points.json", {
            "地面": {"source": "map_pickup", "item": "钥匙"},
            "首领": {"source": "boss", "item": "武器"},
        })
        self.write_json(self.base / "receipts.json", {
            "地面": {"source": "map_pickup", "saveId": "area-ground"},
            "首领": {"source": "boss", "nodeGuid": "A" * 32},
        })
        self.active = profiles.Campaign(self.name, self.base.name, self.base.name, "0" * 64)
        self.calls = []
        self.switch_failure = None
        self.profile_unavailable = False
        self.compile_inputs = []
        launcher = patch.object(profiles, "_launcher", side_effect=self.launcher)
        launcher.start()
        self.addCleanup(launcher.stop)

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def launcher(self, root, *args):
        self.assertEqual(root, self.root)
        self.calls.append(args)
        if args[0] == "--profile-info" and self.profile_unavailable:
            raise OSError("无法读取战役状态")
        if args[0] == "--layout-fingerprint":
            self.assertEqual(args[1], self.active.layout)
            return self.active.fingerprint
        if args[0] == "--switch-layout":
            _, name, target = args
            self.assertEqual(name, self.active.name)
            layout = self.seeds / target
            metadata = json.loads((layout / "layout.json").read_bytes())
            self.assertEqual(metadata, {
                "schema": 1, "baseSeed": self.active.seed, "campaign": self.name,
                "parentLayout": self.active.layout, "parentFingerprint": self.active.fingerprint,
            })
            self.assertEqual(len(list((layout / "Saved" / "Paks").iterdir())), 3)
            if self.switch_failure == "rejected":
                raise ValueError("请退出游戏后再切换布局。")
            self.active = profiles.Campaign(name, self.base.name, target, "1" * 64)
            if self.switch_failure == "another_layout":
                self.active = profiles.Campaign(name, self.base.name, "another layout", "2" * 64)
            if self.switch_failure == "unreadable":
                self.profile_unavailable = True
            if self.switch_failure:
                raise OSError("启动器没有返回切换结果")
        return json.dumps({"profile": self.active.__dict__, "savesPath": str(self.saves)})

    def compiler(self, seed, out, kit, retoc, enabled, vanilla_claimed, claims, *, protected=()):
        self.assertEqual(seed, self.base)
        self.assertEqual(kit, seed / "kit.zip")
        self.assertEqual(retoc, self.root / "Tools" / "retoc.exe")
        self.assertEqual(out.parents[2], self.seeds)
        self.compile_inputs.append((enabled, list(claims)))
        out.mkdir(parents=True)
        for suffix in (".pak", ".utoc", ".ucas"):
            (out / ("switch_P" + suffix)).write_bytes(b"archive")
        return resolve_layout(self.permutation, enabled=enabled, vanilla_claimed=vanilla_claimed, claims=claims, protected=protected)

    def test_publishes_before_switch_and_preserves_the_game_save(self):
        session = profiles.open_session(self.root, self.name)
        self.assertEqual(session.current.remaining, self.permutation)
        selected = profiles.switch(session, enabled=False, claimed={"地面"}, confirm_complete=True, compiler=self.compiler)
        self.assertEqual(self.compile_inputs, [(False, [{"point": "地面", "enabled": True}])])
        result = profiles.open_session(self.root, self.name)
        self.assertEqual(result.campaign, selected)
        self.assertEqual(result.current.granted, {"地面": "首领"})
        self.assertEqual(result.current.remaining, {"首领": "地面"})
        self.assertEqual(self.save.read_bytes(), b"save bytes owned by the game")
        self.assertEqual(json.loads((self.base / "ledger.json").read_bytes()), self.original_ledger)
        self.assertFalse(list(self.seeds.glob(".switch-*")))

    def test_rejects_incomplete_and_rolled_back_lists(self):
        initial = profiles.open_session(self.root, self.name)
        for claims, complete in (({"地面"}, False), ({"不存在"}, True)):
            with self.assertRaises(ValueError):
                profiles.switch(initial, enabled=False, claimed=claims, confirm_complete=complete, compiler=self.compiler)
        self.assertEqual(self.compile_inputs, [])
        profiles.switch(initial, enabled=False, claimed={"地面"}, confirm_complete=True, compiler=self.compiler)
        current = profiles.open_session(self.root, self.name)
        with self.assertRaisesRegex(ValueError, "此前已确认"):
            profiles.switch(current, enabled=True, claimed=set(), confirm_complete=True, compiler=self.compiler)
        self.assertEqual(len(self.compile_inputs), 1)

    def test_unclassified_original_quest_keeps_its_reward_without_a_fake_receipt(self):
        self.write_json(self.base / "layout.json", {"schema": 1, "baseSeed": self.base.name, "vanilla": True})
        self.write_json(self.base / "ledger.json", {**self.original_ledger, "enabled": False})
        imported = profiles.open_session(self.root, self.name)
        profiles.switch(imported, enabled=True, claimed=set(), available={"地面"}, confirm_complete=True,
                        compiler=self.compiler)
        active = profiles.open_session(self.root, self.name)
        self.assertFalse(active.current.granted)
        self.assertEqual(active.protected, {"首领"})
        self.assertEqual(active.current.remaining, {"地面": "地面", "首领": "首领"})

    def test_import_bounds_json_and_rejects_a_confirmed_receipt_rollback(self):
        old = profiles.open_session(self.root, self.name)
        file = self.root / "slot.json"
        self.write_json(file, {"LevelActorManager": {"area-ground": {"Destroy": True}}})
        self.assertEqual(old.import_receipts(file).claimed, ("地面",))
        self.assertEqual(old.import_receipts(file).unknown, ("首领",))
        profiles.switch(old, enabled=False, claimed={"地面"}, confirm_complete=True, compiler=self.compiler)
        current = profiles.open_session(self.root, self.name)
        self.write_json(file, {"LevelActorManager": {"area-ground": {"Destroy": False}}})
        with self.assertRaisesRegex(ValueError, "标记了先前"):
            current.import_receipts(file)
        with self.assertRaisesRegex(ValueError, "json"):
            current.import_receipts(self.save)

    def test_switch_rejects_stale_sessions_and_keeps_previous_layout_on_launcher_failure(self):
        session = profiles.open_session(self.root, self.name)
        unrelated = self.seeds / ("layout-" + "7" * 32)
        unrelated.mkdir()
        self.switch_failure = "rejected"
        with self.assertRaisesRegex(ValueError, "退出游戏"):
            profiles.switch(session, enabled=False, claimed=set(), confirm_complete=True, compiler=self.compiler)
        self.assertEqual(self.active, session.campaign)
        self.assertEqual(list(self.seeds.glob("layout-*")), [unrelated])
        self.assertEqual(self.save.read_bytes(), b"save bytes owned by the game")
        self.active = profiles.Campaign(self.name, self.base.name, "other layout", "2" * 64)
        with self.assertRaisesRegex(ValueError, "布局已更改"):
            profiles.switch(session, enabled=False, claimed=set(), confirm_complete=True, compiler=self.compiler)

    def test_recovers_switch_if_the_reply_was_lost_after_activation(self):
        session = profiles.open_session(self.root, self.name)
        self.switch_failure = "lost_reply"
        result = profiles.switch(session, enabled=False, claimed=set(), confirm_complete=True, compiler=self.compiler)
        self.assertEqual(result, self.active)
        self.assertTrue((self.seeds / result.layout / "ledger.json").is_file())

    def test_preserves_new_layout_if_the_campaign_state_cannot_be_verified(self):
        session = profiles.open_session(self.root, self.name)
        self.switch_failure = "unreadable"
        with self.assertRaisesRegex(RuntimeError, "保留新布局"):
            profiles.switch(session, enabled=False, claimed=set(), confirm_complete=True, compiler=self.compiler)
        self.assertTrue((self.seeds / self.active.layout / "ledger.json").is_file())

    def test_preserves_new_layout_if_the_campaign_now_points_to_a_third_layout(self):
        session = profiles.open_session(self.root, self.name)
        self.switch_failure = "another_layout"
        with self.assertRaisesRegex(RuntimeError, "战役已指向另一布局"):
            profiles.switch(session, enabled=False, claimed=set(), confirm_complete=True, compiler=self.compiler)
        retained = list(self.seeds.glob("layout-*"))
        self.assertEqual(len(retained), 1)
        self.assertTrue((retained[0] / "ledger.json").is_file())

    def test_cleanup_refuses_to_remove_a_layout_outside_of_the_seed_directory(self):
        outside = self.root / ("layout-" + "8" * 32)
        outside.mkdir()
        with self.assertRaisesRegex(ValueError, "待清理目录"):
            profiles._discard_unused_layout(self.seeds, outside)
        self.assertTrue(outside.is_dir())

    def test_cli_accepts_an_empty_utf8_list_and_requires_confirmation(self):
        empty = self.root / "claimed.txt"
        empty.write_bytes(b"\xef\xbb\xbf")
        args = ["--campaign", self.name, "--mode", "off", "--claimed-file", str(empty)]
        stderr = StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(profiles.cli(self.root, args), 1)
        self.assertIn("--confirm-complete", stderr.getvalue())
        with patch.object(profiles, "switch", wraps=lambda *a, **kw: self.real_switch(*a, **kw)), redirect_stdout(StringIO()) as stdout:
            self.assertEqual(profiles.cli(self.root, [*args, "--confirm-complete"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["layout"], self.active.layout)

    def real_switch(self, *args, _switch=profiles.switch, **kwargs):
        return _switch(*args, **kwargs, compiler=self.compiler)


if __name__ == "__main__":
    unittest.main()
