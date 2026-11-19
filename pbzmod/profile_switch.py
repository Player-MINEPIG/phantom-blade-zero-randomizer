"""Compile and activate a static reward layout for one campaign."""

import argparse
from dataclasses import dataclass
import json
import locale
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from .reward_layout import RewardLayout, resolve_layout
from .reward_receipts import read_receipts


@dataclass(frozen=True)
class Campaign:
    name: str
    seed: str
    layout: str
    fingerprint: str


@dataclass(frozen=True)
class SwitchSession:
    root: Path
    campaign: Campaign
    points: dict
    permutation: dict[str, str]
    enabled: bool
    vanilla_claimed: tuple[str, ...]
    claims: tuple[dict, ...]
    current: RewardLayout
    initial_vanilla: bool
    protected: frozenset[str]

    @property
    def seed_dir(self):
        return self.root / "Seeds" / self.campaign.seed

    def import_receipts(self, path):
        summary = read_receipts(path, _json(self.seed_dir / "receipts.json"))
        if self.current.granted.keys() & set(summary.unclaimed):
            raise ValueError("这份存档明确标记了先前已确认的奖励为未领取。请使用当前槽位的最新进度。")
        return summary


def _name(value):
    if not isinstance(value, str) or not value or value in {".", ".."} or PureWindowsPath(value).name != value:
        raise ValueError("启动器返回了无效的战役或布局名称。")
    return value


def _json(path):
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError(f"JSON 应为对象。{path}")
    return result


def _launcher(root, *args):
    executable = root / "PBZRandomizer.exe"
    completed = subprocess.run(
        [str(executable), *args], cwd=root, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
    )
    if completed.returncode:
        for encoding in ("utf-8-sig", locale.getpreferredencoding(False)):
            try:
                message = completed.stderr.decode(encoding).strip()
                break
            except UnicodeDecodeError:
                pass
        else:
            message = ""
        raise ValueError(message or f"启动器返回错误代码 {completed.returncode}。")
    return completed.stdout.decode("utf-8-sig").strip()


def _read_campaign(root, action, name, *args):
    response = json.loads(_launcher(root, action, name, *args))
    fields = response["profile"]
    campaign = Campaign(_name(fields["name"]), _name(fields["seed"]), _name(fields["layout"]), fields["fingerprint"])
    if campaign.name.casefold() != name.casefold() or not re.fullmatch(r"[0-9a-f]{64}", campaign.fingerprint):
        raise ValueError("启动器返回的战役信息与请求不符。")
    return campaign


def open_session(root, campaign_name):
    root = Path(root).resolve()
    campaign = _read_campaign(root, "--profile-info", _name(campaign_name))
    if _launcher(root, "--layout-fingerprint", campaign.layout) != campaign.fingerprint:
        raise ValueError("当前布局归档已修改。请先恢复启动器记录的布局。")

    seeds = root / "Seeds"
    seed = seeds / campaign.seed
    active = seeds / campaign.layout
    points = _json(seed / "points.json")
    permutation = _json(seed / "permutation.json")
    if points.keys() != permutation.keys() or any(
        not isinstance(point, dict) or not all(isinstance(point.get(key), str) for key in ("item", "source"))
        for point in points.values()
    ):
        raise ValueError("初始种子的点位目录与分配不符。")
    layout = _json(active / "layout.json")
    ledger = _json(active / "ledger.json")
    enabled = ledger["enabled"]
    vanilla_claimed = ledger["vanillaClaimed"]
    claims = ledger["claims"]
    if not isinstance(vanilla_claimed, list) or not isinstance(claims, list) or not all(
        isinstance(claim, dict) for claim in claims
    ):
        raise ValueError("当前布局的领取记录格式无效。")
    if layout.get("baseSeed") != campaign.seed:
        raise ValueError("当前布局属于另一初始种子。")
    if layout.get("parentFingerprint") is None:
        if claims or vanilla_claimed:
            raise ValueError("共享的初始布局包含领取记录。")
    elif layout.get("campaign") != campaign.name:
        raise ValueError("当前布局的领取记录属于另一战役。")

    protected = frozenset(ledger.get("protected", ()))
    current = resolve_layout(permutation, enabled=enabled, vanilla_claimed=vanilla_claimed, claims=claims, protected=protected)
    first_import = layout.get("vanilla") is True and layout.get("parentFingerprint") is None
    return SwitchSession(root, campaign, points, permutation, enabled, tuple(vanilla_claimed), tuple(claims),
                         current, first_import, protected)


def read_claimed_file(path):
    path = Path(path)
    if path.suffix.casefold() == ".sav":
        raise ValueError("请提供 UTF-8 点位清单。此入口不接受游戏 .sav 存档。")
    points = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(points) != len(set(points)):
        raise ValueError("领取清单包含相同点位多次。")
    return set(points)


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _discard_unused_layout(seeds, published):
    root = seeds.resolve(strict=True)
    target = published.resolve(strict=True)
    if (root != seeds or target != published or target.parent != root or
        re.fullmatch(r"layout-[0-9a-f]{32}", target.name) is None):
        raise ValueError(f"待清理目录不是本次创建的布局。{published}")
    shutil.rmtree(target)


def _activate_layout(session, published):
    previous = session.campaign
    try:
        result = _read_campaign(session.root, "--switch-layout", previous.name, published.name)
        if result.layout != published.name or result.seed != previous.seed:
            raise ValueError("启动器未确认新布局已生效。")
        return result
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        try:
            active = _read_campaign(session.root, "--profile-info", previous.name)
        except (KeyError, OSError, TypeError, ValueError, RuntimeError, subprocess.SubprocessError) as query_error:
            raise RuntimeError(f"无法确认战役当前布局，保留新布局供恢复。{published}\n{error}\n{query_error}") from error
        if active.layout == published.name and active.seed == previous.seed:
            return active
        if active != previous:
            raise RuntimeError(f"战役已指向另一布局，保留本次生成的布局。{published}\n{error}") from error
        try:
            _discard_unused_layout(session.root / "Seeds", published)
        except (OSError, ValueError, RuntimeError) as cleanup_error:
            raise RuntimeError(f"布局切换失败，自动清理未完成。{published}\n{error}\n{cleanup_error}") from error
        raise


def switch(session, *, enabled, claimed, confirm_complete, available=None, compiler=None):
    if not confirm_complete:
        raise ValueError("请先确认已完整核对当前槽位的领取记录。")
    if type(enabled) is not bool or enabled == session.enabled:
        raise ValueError("请选择与当前布局不同的随机模式。")

    claimed = set(claimed)
    unknown = claimed - session.points.keys()
    if unknown:
        raise ValueError(f"领取清单包含未知点位。{min(unknown)}")
    history = session.current.granted.keys()
    protected = session.protected
    if session.initial_vanilla:
        available = set(available or ())
        if available - session.points.keys() or claimed & available:
            raise ValueError("仍可领取清单包含未知点位或与已领取清单重叠。")
        protected = session.points.keys() - claimed - available
    elif available is not None:
        raise ValueError("只能在原版战役首次启用时确认可领取点。")
    missing = history - claimed
    if missing:
        raise ValueError(f"领取清单缺少此前已确认的点位。请继续使用原槽位的最新进度。缺少 {min(missing)}。")
    claims = [*session.claims, *(
        {"point": point, "enabled": session.enabled} for point in sorted(claimed - history)
    )]
    expected = resolve_layout(session.permutation, enabled=enabled, vanilla_claimed=session.vanilla_claimed,
                              claims=claims, protected=protected)
    campaign = session.campaign
    if _read_campaign(session.root, "--profile-info", campaign.name) != campaign:
        raise ValueError("战役布局已更改。请重新打开切换窗口并核对点位。")

    if compiler is None:
        from .portable import compile_layout as compiler

    seeds = session.root / "Seeds"
    published = seeds / ("layout-" + uuid4().hex)
    with TemporaryDirectory(prefix=".switch-", dir=seeds) as temporary:
        stage = Path(temporary)
        paks = stage / "Saved" / "Paks"
        compiled = compiler(
            session.seed_dir, paks, session.seed_dir / "kit.zip", session.root / "Tools" / "retoc.exe",
            enabled, session.vanilla_claimed, claims, protected=protected,
        )
        if compiled != expected:
            raise ValueError("编译后的奖励分配与领取记录不符。")
        _write_json(stage / "ledger.json", {
            "enabled": enabled, "vanillaClaimed": session.vanilla_claimed, "claims": claims,
            "protected": sorted(protected),
        })
        _write_json(stage / "layout.json", {
            "schema": 1, "baseSeed": campaign.seed, "campaign": campaign.name,
            "parentLayout": campaign.layout, "parentFingerprint": campaign.fingerprint,
        })
        stage.rename(published)

    return _activate_layout(session, published)


def cli(root, argv):
    parser = argparse.ArgumentParser(description="编译并切换独立随机战役的奖励布局。")
    parser.add_argument("--campaign", required=True, help="启动器中的战役名")
    parser.add_argument("--mode", choices=("on", "off"), required=True)
    parser.add_argument("--claimed-file", type=Path, required=True, help="完整领取清单。UTF-8，每行一个点位 ID，可为空文件。")
    parser.add_argument("--available-file", type=Path, help="原版战役首次开启时能确认仍可领取的点；未归类点终生保留原位")
    parser.add_argument("--confirm-complete", action="store_true", help="确认清单包含当前槽位至今已领的全部点位")
    args = parser.parse_args(argv)
    try:
        if not args.confirm_complete:
            raise ValueError("核对完整领取清单后，添加 --confirm-complete。")
        session = open_session(root, args.campaign)
        active = switch(session, enabled=args.mode == "on", claimed=read_claimed_file(args.claimed_file), confirm_complete=True,
                        available=read_claimed_file(args.available_file) if args.available_file else None)
    except (ImportError, KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 1
    # The Windows console and redirected pipes can use different code pages.
    print(json.dumps(active.__dict__, ensure_ascii=True))
    return 0
