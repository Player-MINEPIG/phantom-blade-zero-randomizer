"""Find the local game, UnrealPak, and Oodle installations on Windows."""

import json
import os
from pathlib import Path
import re
import string

try:
    import winreg
except ImportError:
    winreg = None


APP_MANIFEST = "appmanifest_4115450.acf"
PAKS_DIR = Path("ProjectPBZ/Content/Paks")
CONTAINERS = (
    "ProjectPBZ-Windows.pak",
    "ProjectPBZ-Windows.utoc",
    "ProjectPBZ-Windows.ucas",
)
OODLE = "oo2core_9_win64.dll"


def _registry_paths(key, value):
    if winreg is None:
        return
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                    path, _ = winreg.QueryValueEx(handle, value)
            except OSError:
                continue
            if isinstance(path, str) and path:
                yield Path(os.path.expandvars(path))


def _text(path):
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def _vdf_values(data, key):
    pattern = r'"' + re.escape(key) + r'"\s*"((?:\\.|[^"\\])*)"'
    for value in re.findall(pattern, data, re.IGNORECASE):
        yield re.sub(r'\\(["\\])', r"\1", value)


def _steam_candidates():
    yield from _registry_paths(r"Software\Valve\Steam", "SteamPath")
    yield from _registry_paths(r"Software\Valve\Steam", "InstallPath")
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(variable):
            yield Path(os.environ[variable]) / "Steam"


def _game_candidates():
    libraries = set()
    for steam in _steam_candidates():
        paths = [steam]
        for location in ("steamapps/libraryfolders.vdf", "config/libraryfolders.vdf"):
            paths.extend(
                Path(value)
                for value in _vdf_values(_text(steam / location), "path")
                if value
            )
        for library in paths:
            if library in libraries:
                continue
            libraries.add(library)
            steamapps = library / "steamapps"
            manifest = _text(steamapps / APP_MANIFEST)
            for name in _vdf_values(manifest, "installdir"):
                if (
                    name
                    and name not in {".", ".."}
                    and not any(char in name for char in "/\\:")
                ):
                    yield steamapps / "common" / name
            for name in ("PBZ", "Phantom Blade Zero"):
                yield steamapps / "common" / name


def _ue_candidates():
    yield from _registry_paths(
        r"SOFTWARE\EpicGames\Unreal Engine\5.7", "InstalledDirectory"
    )
    if os.environ.get("ProgramData"):
        installed = (
            Path(os.environ["ProgramData"])
            / "Epic/UnrealEngineLauncher/LauncherInstalled.dat"
        )
        try:
            launcher = json.loads(_text(installed))
        except ValueError:
            launcher = {}
        entries = (
            launcher.get("InstallationList", []) if isinstance(launcher, dict) else []
        )
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or entry.get("AppName") != "UE_5.7":
                continue
            path = entry.get("InstallLocation")
            if isinstance(path, str) and path:
                yield Path(path)
    if os.name == "nt":
        for drive in string.ascii_uppercase:
            root = Path(f"{drive}:/")
            if root.is_dir():
                yield root / "Program Files/Epic Games/UE_5.7"
                yield root / "Epic Games/UE_5.7"


def _ue_tools(root):
    engine = root / "Engine"
    binaries = engine / "Binaries/Win64"
    unrealpak = binaries / "UnrealPak.exe"
    if not unrealpak.is_file():
        return None
    for location in (
        binaries,
        engine / "Source/Programs/UnrealBuildTool/bin/Development",
        engine / "Binaries/DotNET/UnrealBuildTool",
    ):
        oodle = location / OODLE
        if oodle.is_file():
            return unrealpak.resolve(), oodle.resolve()
    return None


def resolve_paths(game=None, ue=None):
    """Return (game root, UnrealPak executable, Oodle DLL) as absolute Paths."""
    game_candidates = _game_candidates() if game is None else (Path(game).expanduser(),)
    game_root = next(
        (
            path.resolve()
            for path in game_candidates
            if all((path / PAKS_DIR / name).is_file() for name in CONTAINERS)
        ),
        None,
    )
    if game_root is None:
        if game is not None:
            raise FileNotFoundError(
                f"Phantom Blade Zero containers were not found under {game}"
            )
        raise FileNotFoundError(
            "Could not find Phantom Blade Zero in the Steam libraries; set --game to its install root"
        )

    ue_candidates = _ue_candidates() if ue is None else (Path(ue).expanduser(),)
    for root in ue_candidates:
        tools = _ue_tools(root)
        if tools is not None:
            return game_root, *tools
    if ue is not None:
        raise FileNotFoundError(
            f"UnrealPak.exe and {OODLE} were not both found under {ue}"
        )
    raise FileNotFoundError(
        f"Could not find UnrealPak.exe and {OODLE}; set --ue to your UE 5.7 install root"
    )
