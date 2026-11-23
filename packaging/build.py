"""Build a single-file executable for the current OS: python packaging/build.py

Output: dist/slsk-reborn-<os>-<arch>[.exe]. Needs `pip install pyinstaller`.
"""
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
osname = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
    platform.machine().lower(), platform.machine().lower())
name = f"slsk-reborn-{osname}-{arch}"

sep = ";" if sys.platform == "win32" else ":"
cmd = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
    "--name", name,
    "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    "--add-data", f"{ROOT / 'slsk_reborn' / 'app.tcss'}{sep}slsk_reborn",
    "--collect-all", "textual",      # CSS, widget data
    "--collect-submodules", "rich",  # unicode width tables are imported dynamically
    "--collect-all", "aioslsk",
    "--collect-all", "miniaudio",    # cffi extension for the built-in player
    str(ROOT / "packaging" / "entry.py"),
]
print(" ".join(cmd))
subprocess.run(cmd, check=True)
exe = ROOT / "dist" / (name + (".exe" if sys.platform == "win32" else ""))
print(f"built {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
