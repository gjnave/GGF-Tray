"""Safe, testable installer helpers for GGF Tray.

This module contains no UI code.  The tray uses it to validate archives, choose
only unambiguous installer/launcher files, maintain the local app registry, and
refuse dangerous recursive-delete targets.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path, PureWindowsPath


MAX_ARCHIVE_FILES = 20_000
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024 * 1024  # 40 GiB safety ceiling
MARKER_NAME = ".ggf-install.json"
SKIP_SCAN_DIRS = {
    ".git", ".svn", "__pycache__", "node_modules", "venv", ".venv",
    "env", "site-packages", "models", "checkpoints",
}
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


from ggf_packages import PackageError as InstallSafetyError, extract as extract_archive, reparse
safe_extract_zip = extract_archive


def _commonpath_is_child(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(parent)]) == os.path.abspath(parent)
    except (OSError, ValueError):
        return False


def sanitize_folder_name(value: str) -> str:
    """Return a safe single Windows folder name or raise InstallSafetyError."""
    name = (value or "").strip().strip(". ")
    name = re.sub(r'[=<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"\s+", " ", name).strip().strip(". ")
    if not name or name in {".", ".."}:
        raise InstallSafetyError("Choose a non-empty app folder name.")
    if PureWindowsPath(name).is_reserved():
        raise InstallSafetyError(f"'{name}' is a reserved Windows folder name.")
    return name[:96].rstrip(". ")


def safe_install_path(base_dir: str, folder_name: str) -> str:
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, sanitize_folder_name(folder_name)))
    if target == base or not _commonpath_is_child(target, base):
        raise InstallSafetyError("The app folder must stay inside the selected installation location.")
    return target


def discover_install_files(install_dir: str) -> dict:
    """Only suggest an unambiguous entry point; show other candidates for review."""
    installers, launchers, other = [], [], []
    skip = SKIP_SCAN_DIRS | {"scripts-deps", ".github", "python", "python_embeded", "python_embedded",
                            "bin", "lib", "tools", "deps", "vendor", "__macosx", "tests", "build", "dist-packages"}
    for root, dirs, files in os.walk(install_dir):
        depth = len(Path(root).relative_to(install_dir).parts)
        dirs[:] = sorted(d for d in dirs if depth < 5 and d.casefold() not in skip and not reparse(os.path.join(root,d)))
        for file in sorted(files):
            path = os.path.join(root, file)
            name, ext = os.path.splitext(file.lower())
            if ext not in {".exe",".bat",".cmd"} or reparse(path): continue
            words = set(re.findall(r"[a-z]+", name))
            if words & {"uninstall","remove","reset","cleanup","repair","doctor","update","upgrade","configure","debug",
                        "test","uninstaller","helper","frozen","ffmpeg","ffprobe","aria","python","git","uv","pip"} or name.startswith("unins"):
                continue
            if words & {"install","installer","setup"}: installers.append((depth,path))
            elif words & {"run","start","launch","launcher"}: launchers.append((depth,path))
            else: other.append((depth,path))
    def best(group):
        if group:
            top = [path for depth,path in group if depth == min(d for d,_ in group)]
            return top[0] if len(top)==1 else None
    manual = sorted(path for _,path in other)
    standalone = best(other) if not installers and not launchers and len(other)==1 else None
    return {"installers":[v for _,v in installers], "launchers":[v for _,v in launchers],
            "executables":manual, "best_installer":best(installers), "best_launcher":best(launchers) or standalone}


def load_registry(path: str) -> dict[str, tuple[str, str | None]]:
    entries = {}
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, data = line.split("=", 1)
            parts = data.split("|", 1)
            entries[name.strip()] = (parts[0].strip(), parts[1].strip() if len(parts) > 1 else None)
    return entries


def _write_registry(path: str, entries: dict[str, tuple[str, str | None]]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="ggf-registry-", suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("# GGF Installed Apps\n# Format: name=install_dir|launcher\n")
            for name in sorted(entries, key=str.casefold):
                install_dir, launcher = entries[name]
                value = install_dir + (f"|{launcher}" if launcher else "")
                handle.write(f"{name}={value}\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def upsert_registry(path: str, name: str, install_dir: str, launcher: str | None = None) -> None:
    entries = load_registry(path)
    for existing_name in list(entries):
        existing_dir = entries[existing_name][0]
        if existing_name.casefold() == name.casefold() or os.path.normcase(os.path.abspath(existing_dir)) == os.path.normcase(os.path.abspath(install_dir)):
            del entries[existing_name]
    entries[name] = (os.path.abspath(install_dir), os.path.abspath(launcher) if launcher else None)
    _write_registry(path, entries)


def remove_registry_entry(path: str, name: str) -> None:
    entries = load_registry(path)
    entries = {key: value for key, value in entries.items() if key.casefold() != name.casefold()}
    _write_registry(path, entries)


def write_install_marker(install_dir: str, app_name: str, source_archive: str, launcher: str | None) -> None:
    marker = {
        "app_name": app_name,
        "install_dir": os.path.abspath(install_dir),
        "source_archive": os.path.basename(source_archive),
        "launcher": os.path.abspath(launcher) if launcher else None,
        "installed_at": int(time.time()),
    }
    marker_path = os.path.join(install_dir, MARKER_NAME)
    with open(marker_path, "w", encoding="utf-8") as handle:
        json.dump(marker, handle, indent=2)


def validate_delete_target(path: str, app_dir: str) -> tuple[bool, str, bool]:
    target = os.path.abspath(path)
    drive, tail = os.path.splitdrive(target)
    dangerous = {
        os.path.abspath(app_dir), os.path.abspath(os.path.expanduser("~")),
        os.path.abspath(os.environ.get("SystemRoot", r"C:\Windows")),
        os.path.abspath(os.environ.get("ProgramFiles", r"C:\Program Files")),
        os.path.abspath(os.environ.get("ProgramData", r"C:\ProgramData")),
    }
    if not target or not drive or tail in {"", os.sep}:
        return False, "Drive roots can never be removed by GGF Tray.", False
    if any(os.path.normcase(target) == os.path.normcase(item) for item in dangerous):
        return False, "This protected system or application folder cannot be removed.", False
    if _commonpath_is_child(app_dir, target):
        return False, "A folder containing GGF Tray cannot be removed.", False
    if len(Path(tail).parts) < 3:
        return False, "The registered path is too close to the drive root to remove safely.", False
    marker_path = os.path.join(target, MARKER_NAME)
    if any(reparse(node) for node in (Path(target), *Path(target).parents)):
        return False, "Cannot remove a linked folder or its contents.", False
    try:
        with open(marker_path, encoding="utf-8") as marker:
            owned = os.path.normcase(json.load(marker)["install_dir"]) == os.path.normcase(target)
    except (ValueError, OSError, KeyError, TypeError):
        owned = False
    return True, "", owned
