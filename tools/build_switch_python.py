"""Copy the Windows Python and Tcl/Tk runtime required by the switch tool."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile


STDLIB_EXCLUDED = {
    "__pycache__", "ensurepip", "idlelib", "site-packages", "test", "tests",
    "turtledemo", "venv",
}
NATIVE = {
    "python.exe": "python.exe",
    "pythonw.exe": "pythonw.exe",
    "python312.dll": "python312.dll",
    "DLLs/_tkinter.pyd": "_tkinter.pyd",
    "DLLs/_queue.pyd": "_queue.pyd",
    "DLLs/unicodedata.pyd": "unicodedata.pyd",
    "Library/bin/tcl86t.dll": "tcl86t.dll",
    "Library/bin/tk86t.dll": "tk86t.dll",
    "Library/bin/zlib.dll": "zlib.dll",
}
TCL_ENV = '''from os import environ
from pathlib import Path
import sys

libraries = Path(__file__).resolve().parent / "tcl"
environ["TCL_LIBRARY"] = str(libraries / "tcl8.6")
environ["TK_LIBRARY"] = str(libraries / "tk8.6")
sys.dont_write_bytecode = True
'''


def _package_license(prefix, package, filename):
    (installed,) = (prefix / "conda-meta").glob(f"{package}-*.json")
    base = prefix / "pkgs" / installed.stem / "info" / "licenses"
    (license_path,) = base.rglob(filename)
    return license_path


def _zip_stdlib(prefix, output):
    library = prefix / "Lib"
    manifest, = (prefix / "conda-meta").glob("python-3.12.*.json")
    shipped = {name.replace("\\", "/").casefold() for name in json.loads(manifest.read_bytes())["files"]}
    with ZipFile(output, "x", ZIP_DEFLATED, compresslevel=8) as archive:
        for root, folders, files in os.walk(library):
            directory = Path(root)
            folders[:] = sorted(folder for folder in folders if folder not in STDLIB_EXCLUDED)
            for filename in sorted(files):
                if filename.endswith(".py"):
                    path = directory / filename
                    if path.relative_to(prefix).as_posix().casefold() in shipped:
                        archive.write(path, path.relative_to(library).as_posix())


def build_runtime(output):
    """Publish an isolated runtime from the installed x64 Conda Python 3.12."""
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or sys.maxsize < 2**32:
        raise ValueError("便携运行时需要从已安装的 Windows x64 Conda Python 3.12 构建。")
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"输出目录已存在。{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = Path(sys.base_prefix)
    with TemporaryDirectory(prefix=".switch-python-", dir=output.parent) as tmp:
        stage = Path(tmp)
        for original, destination in NATIVE.items():
            shutil.copyfile(prefix / original, stage / destination)
        for name in ("tcl8.6", "tk8.6"):
            shutil.copytree(prefix / "Library" / "lib" / name, stage / "tcl" / name,
                            ignore=shutil.ignore_patterns("demos"))
        notices = stage / "licenses"
        notices.mkdir()
        for source, name in (
            (prefix / "LICENSE_PYTHON.txt", "Python.txt"),
            (_package_license(prefix, "tk", "license.terms"), "Tcl-Tk.txt"),
            (_package_license(prefix, "libzlib", "license.txt"), "zlib.txt"),
        ):
            shutil.copyfile(source, notices / name)
        _zip_stdlib(prefix, stage / "python312.zip")
        (stage / "python312._pth").write_text("python312.zip\n.\nimport site\n", encoding="ascii")
        (stage / "sitecustomize.py").write_text(TCL_ENV, encoding="utf-8")
        (stage / "runtime.txt").write_text(
            f"CPython {sys.version.split()[0]} x64\nTcl/Tk 8.6\n"
            "Windows x64 Microsoft Visual C++ Runtime is loaded from the system.\n",
            encoding="utf-8",
        )
        stage.rename(output)


def verify_runtime(output, switch_tool):
    """Check the CLI and Tk with no PATH, user packages or host Tcl paths."""
    output = Path(output).resolve()
    env = {key: value for key, value in os.environ.items() if not (
        key.upper().startswith(("PYTHON", "CONDA")) or key.upper() in {"PATH", "TCL_LIBRARY", "TK_LIBRARY"}
    )}
    env["PATH"] = ""
    subprocess.run([output / "python.exe", "-B", Path(switch_tool).resolve(), "--help"],
                   check=True, env=env, cwd=output, capture_output=True, timeout=30)
    with TemporaryDirectory(prefix=".verify-tk-", dir=output.parent) as tmp:
        result = Path(tmp) / "result.txt"
        code = '''
from pathlib import Path
from queue import Queue
import sys
import tkinter
from zipfile import ZipFile
root = tkinter.Tk()
root.withdraw()
runtime = Path(sys.executable).parent
assert sys.flags.isolated
assert all(Path(entry).is_relative_to(runtime) for entry in sys.path)
assert Path(root.tk.eval("info library")).parent == runtime / "tcl"
assert Path(str(root.tk.globalgetvar("tk_library"))).parent == runtime / "tcl"
with ZipFile(runtime / "python312.zip") as archive:
    assert archive.testzip() is None
root.destroy()
Path(sys.argv[1]).write_text("verified", encoding="ascii")
'''
        subprocess.run([output / "pythonw.exe", "-B", "-c", code, result],
                       check=True, env=env, cwd=output, capture_output=True, timeout=30)
        if not result.exists() or result.read_text(encoding="ascii") != "verified":
            raise RuntimeError("便携版 Python 未完成 Tk 自检。")


def main():
    parser = argparse.ArgumentParser(description="构建独立战役切换工具的 Windows 便携 Python。")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    build_runtime(args.out)
    if args.verify:
        verify_runtime(args.out, Path(__file__).with_name("switch_mode.pyw"))
    print(args.out.resolve())


if __name__ == "__main__":
    main()
