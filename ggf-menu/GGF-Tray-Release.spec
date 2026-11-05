import os
import sys
from importlib import metadata
from pathlib import Path

system = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join(map(str, [Path(sys.base_prefix), system / "System32", system]))
base = Path(sys.base_prefix)
lib = base / "Lib"
hidden = {"app_search", "audio_visualizer_tray", "ggf_player", "ggf_setup"}
# Upstream wheels load as normal Python packages. Include the interpreter's stdlib
# so a dependency can import modules that GGF itself does not directly reference.
skip = {"test", "tests", "idlelib", "turtledemo", "ensurepip", "venv", "lib2to3", "distutils", "pydoc_data"}
for module in sorted(sys.stdlib_module_names - skip):
    hidden.add(module)
    folder = lib / module
    if folder.is_dir():
        for source in folder.rglob("*.py"):
            parts = source.relative_to(lib).with_suffix("").parts
            if skip.intersection(parts):
                continue
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if all(part.isidentifier() for part in parts):
                hidden.add(".".join(parts))

external = ["PyQt6", "PySide6", "shiboken6", "imageio_ffmpeg", "pystray", "numpy",
            "PIL", "psutil", "pyaudiowpatch", "yt_dlp", "certifi", "six", "packaging",
            "pkg_resources", "setuptools", "pip", "wheel", "pytest", "_distutils_hack"]
datas = [(f, ".") for f in ("ggf-mark.ico", "ggf-startup.js", "windows-components.json", "../LICENSE.txt")]
datas += [(str(base / "LICENSE.txt"), "notices/Python"),
          (str(base / "tcl/tk8.6/license.terms"), "notices/Tk")]
boot = metadata.distribution("pyinstaller")
for f in boot.files:
    if f.name == "COPYING.txt":
        datas.append((str(boot.locate_file(f)), "notices/PyInstaller"))
        break

a = Analysis(["ggf-tray.py"], pathex=[], binaries=[(str(base / "python3.dll"), ".")], datas=datas, hiddenimports=sorted(hidden),
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=external, noarchive=False)
# Refuse to bundle any external package, credential file, or unreviewed native library from site-packages.
for dest, source, kind in list(a.pure) + list(a.binaries) + list(a.datas):
    if "site-packages" in Path(source).parts and "notices" not in Path(dest).parts:
        if "PyInstaller" not in Path(source).parts:
            raise ValueError("Unexpected third-party file in executable: " + dest)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="GGF-Tray", debug=False, strip=False,
          upx=False, console=False, icon="ggf-mark.ico", version="version_info.txt")

