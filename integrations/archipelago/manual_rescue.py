"""Queue one progression weapon in the local PBZArchipelago 0.9.2 file bridge."""

import argparse
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from .offline_bridge import LOCK, _check_directory, _lock_bridge, _read_optional


DEFAULT_BRIDGE = Path("platform/steam/ue4ss/Mods/PBZArchipelago/bridge")
IDLE_FILES = {".keep", LOCK, "alive.txt", "alive.txt.tmp"}
SESSION = re.compile(r"pbz_rescue_[0-9a-f]{32}")
SENDER = "PBZ Seed Randomizer"

# IDs and shachi grant type come from the pinned APWorld's data.json. The
# companion config.lua marks the corresponding traversal uses as confirmed.
WEAPONS = {
    "BrutalAxe": ("Phantom Weapon: Brutal Axe", "破坏粗锁链"),
    "ShachiHook": ("Phantom Weapon: Shachi Hook", "钩索攀越"),
    "LionHead": ("Phantom Weapon: Lion Head", "烧掉荆棘"),
    "TigerCannon": ("Phantom Weapon: Tiger Cannon", "轰开石墙"),
}


def _inbox_line(weapon):
    return f"shachi\t{weapon}\t{WEAPONS[weapon][0]}\t{SENDER}"


def _check_idle(directory):
    if not directory.is_dir():
        raise ValueError(f"找不到桥目录 {directory}")
    try:
        _check_directory(directory, IDLE_FILES)
    except ValueError as error:
        raise ValueError("桥目录已有会话、待处理操作或其他文件，请选用空闲的专用桥") from error
    heartbeat = _read_optional(directory / "alive.txt")
    parts = (heartbeat or "").splitlines()
    if len(parts) < 2 or parts[1] != "0.9.2" or not re.fullmatch(r"[0-9]{1,12}", parts[0]):
        raise ValueError("找不到 PBZArchipelago 0.9.2 的有效心跳，请确认 Mod 已启用且桥目录正确")
    if len(parts) > 2 and parts[2].strip():
        raise ValueError("游戏端仍使用现有会话，请换用专用桥后重启游戏")
    age = time.time() - int(parts[0])
    if not -5 <= age <= 20:
        raise ValueError("游戏端心跳已过期，请启动游戏并等待桥刷新")


def _publish_new(source, target):
    if os.name == "nt":
        # On Windows rename fails if the destination exists.
        source.rename(target)
    else:
        os.link(source, target)


def queue_rescue(directory, weapon):
    """Publish a single item request to an idle directory without replacing files."""
    if weapon not in WEAPONS:
        raise ValueError(f"未核验的推进武装 {weapon}")
    directory = Path(directory)
    _check_idle(directory)
    with _lock_bridge(directory):
        _check_idle(directory)
        session = f"pbz_rescue_{uuid4().hex}"
        with TemporaryDirectory(dir=directory, prefix="pbz-rescue-") as scratch:
            temporary = Path(scratch)
            inbox = temporary / "inbox.txt"
            marker = temporary / "session.txt"
            inbox.write_text(f"{session}\n{_inbox_line(weapon)}\n", encoding="utf-8", newline="\n")
            marker.write_text(f"{session}\n", encoding="utf-8", newline="\n")
            # The game recognizes this inbox only after it can read the session.
            _publish_new(inbox, directory / inbox.name)
            _publish_new(marker, directory / marker.name)
    return session


def rescue_status(directory):
    """Read the status of this tool's request from the stock mod's receipts."""
    directory = Path(directory)
    session = (_read_optional(directory / "session.txt") or "").strip()
    if not SESSION.fullmatch(session):
        raise ValueError("此目录没有本工具创建的补救会话")
    inbox = (_read_optional(directory / "inbox.txt") or "").splitlines()
    weapons = {_inbox_line(weapon): weapon for weapon in WEAPONS}
    if len(inbox) != 2 or inbox[0] != session or inbox[1] not in weapons:
        raise ValueError("当前桥请求与补救会话不匹配")
    weapon = weapons[inbox[1]]
    granted = (_read_optional(directory / f"granted_{session}.txt") or "").splitlines()
    if f"shachi:{weapon}" in granted:
        return weapon, "granted"
    applied = (_read_optional(directory / f"applied_{session}.txt") or "").strip()
    return weapon, "processed" if applied == "1" else "pending"


def main(argv=None):
    parser = argparse.ArgumentParser(description="通过 PBZArchipelago 0.9.2 文件桥手动补发一件推进武装")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="列出已核验的推进武装")
    grant = actions.add_parser("grant", help="提交一件武装的补发请求")
    grant.add_argument("weapon", choices=WEAPONS)
    status = actions.add_parser("status", help="读取此桥的补救回执")
    for action in (grant, status):
        location = action.add_mutually_exclusive_group(required=True)
        location.add_argument("--game", type=Path, help="Steam 游戏安装根目录")
        location.add_argument("--bridge", type=Path, help="指定 PBZArchipelago 配置使用的桥目录")

    args = parser.parse_args(argv)
    if args.action == "list":
        for weapon, (name, purpose) in WEAPONS.items():
            print(f"{weapon:12s}  {purpose}  ({name})")
        return
    directory = args.bridge or args.game / DEFAULT_BRIDGE
    try:
        if args.action == "grant":
            session = queue_rescue(directory, args.weapon)
            print(f"已入队 {args.weapon}，等待游戏端处理。会话 {session}")
        else:
            weapon, state = rescue_status(directory)
            labels = {
                "granted": "上游 Mod 已确认发放，请在当前存档检查背包",
                "processed": "游戏端已处理，请检查背包；可能原本已持有或发放失败",
                "pending": "游戏端尚未处理，请保持对应存档已加载",
            }
            print(f"{weapon}  {labels[state]}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
