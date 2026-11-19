"""Assemble the Windows player distribution and its offline layout compiler."""

from hashlib import sha256
from pathlib import Path
import re
import shutil
import subprocess

from .portable import dump, write_kit


ROOT = Path(__file__).resolve().parent.parent


def seed_id(seed):
    text = str(seed)
    if (len(text) <= 42 and re.fullmatch(r"[^\W_][\w -]*", text) and text == text.strip()
            and not re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", text)):
        return text
    return "seed-" + sha256(text.encode()).hexdigest()[:20]


def write_profile(stage, seed, vanilla, store, build, tools, player_runtime=None):
    from tools.build_switch_python import build_runtime, verify_runtime

    def save(path, data):
        path.write_bytes(dump(data))

    write_kit(seed / "kit.zip", store, tools / "pbz.usmap", build.recipe)
    for folder, enabled in ((seed, True), (vanilla, False)):
        save(folder / "layout.json", {"schema": 1, "baseSeed": seed.name, "vanilla": not enabled})
        save(folder / "ledger.json", {"enabled": enabled, "vanillaClaimed": [], "claims": []})
    save(seed / "points.json", build.recipe["points"])
    save(seed / "receipts.json", build.recipe["receipts"])
    save(seed / "permutation.json", build.recipe["permutation"])
    tools_dir = stage / "Tools"
    sources = (
        "pbzmod/__init__.py", "pbzmod/profile_switch.py", "pbzmod/portable.py",
        "pbzmod/container.py", "pbzmod/loot.py", "pbzmod/reward_layout.py",
        "pbzmod/reward_receipts.py", "pbzmod/usmap.py", "pbzmod/zen_names.py",
        "integrations/pickup_visuals/__init__.py", "integrations/pickup_visuals/table.py",
        "integrations/pickup_visuals/visuals.py", "integrations/weapons/zen.py",
        "integrations/weapons/movesets.py", "integrations/weapons/stats.py",
    )
    for path in sources:
        dest = tools_dir / path
        dest.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(ROOT / path, dest)
    shutil.copyfile(ROOT / "tools/switch_mode.pyw", tools_dir / "switch_mode.pyw")
    runtime_dir = tools_dir / "Python"
    if player_runtime is None:
        build_runtime(runtime_dir)
    else:
        shutil.copytree(player_runtime, runtime_dir)
    verify_runtime(runtime_dir, tools_dir / "switch_mode.pyw")
    shutil.copyfile(tools / "retoc/retoc.exe", tools_dir / "retoc.exe")
    shutil.copyfile(ROOT / "integrations/profile_launcher/retoc-LICENSE.txt", tools_dir / "retoc-LICENSE.txt")
    subprocess.run(["powershell", "-NoProfile", "-File", ROOT / "integrations/profile_launcher/build.ps1",
                    "-OutputDir", stage], check=True)
    site = (ROOT / "docs/architecture/index.html").read_text(encoding="utf8")
    # The release is already extracted. Historical developer downloads live in the repo.
    site = re.sub(r'<a href="../../build/[^"]+">([^<]*)</a>', r'\1', site)
    site = site.replace("../../README.md#游玩", "游玩说明.md").replace("../../README.md", "游玩说明.md")
    site = site.replace("../../", "").replace('href="../integration-research.md', 'href="docs/integration-research.md')
    site = site.replace('href="../游玩说明.md', 'href="游玩说明.md')
    for guide in ("archipelago", "gates", "grants", "monsters", "voices", "weapons"):
        path = Path("integrations") / guide / "README.md"
        (stage / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, stage / path)
    (stage / "docs").mkdir()
    shutil.copyfile(ROOT / "docs/integration-research.md", stage / "docs/integration-research.md")
    shutil.copyfile(ROOT / "随机 Mod 需求.md", stage / "随机 Mod 需求.md")
    (stage / "软件架构.html").write_text(site, encoding="utf8")
    shutil.copyfile(ROOT / "docs/游玩说明.md", stage / "游玩说明.md")
    for filename in ("README.md", "LICENSE", "integrations/archipelago/LICENSE-upstream.txt"):
        shutil.copyfile(ROOT / filename, stage / filename)
