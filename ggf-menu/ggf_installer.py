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
from pathlib import Path, PurePosixPath


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


class InstallSafetyError(RuntimeError):
    """Raised when an archive or destination fails a safety check."""


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
    if name.casefold() in WINDOWS_RESERVED_NAMES:
        raise InstallSafetyError(f"'{name}' is a reserved Windows folder name.")
    return name[:96]


def safe_install_path(base_dir: str, folder_name: str) -> str:
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, sanitize_folder_name(folder_name)))
    if target == base or not _commonpath_is_child(target, base):
        raise InstallSafetyError("The app folder must stay inside the selected installation location.")
    return target


def _safe_member_parts(member_name: str) -> tuple[str, ...]:
    raw = (member_name or "").replace("\\", "/")
    if not raw or "\x00" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise InstallSafetyError(f"Unsafe archive path: {member_name!r}")
    parts = tuple(part for part in PurePosixPath(raw).parts if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        raise InstallSafetyError(f"Unsafe archive path: {member_name!r}")
    return parts


def _safe_member_target(destination: str, member_name: str) -> str:
    target = os.path.abspath(os.path.join(destination, *_safe_member_parts(member_name)))
    if not _commonpath_is_child(target, destination):
        raise InstallSafetyError(f"Archive entry escapes the install folder: {member_name!r}")
    return target


def safe_extract_zip(archive_path: str, destination: str) -> tuple[int, int]:
    """Extract ZIP without Zip Slip, symlinks, or unbounded expansion."""
    with zipfile.ZipFile(archive_path, "r") as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            raise InstallSafetyError(f"Archive contains too many files ({len(members):,}).")
        total_size = sum(max(0, int(item.file_size)) for item in members)
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise InstallSafetyError("Archive expands beyond the 40 GiB safety limit.")

        planned = []
        for item in members:
            unix_mode = (item.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise InstallSafetyError(f"Archive contains a symbolic link: {item.filename}")
            planned.append((item, _safe_member_target(destination, item.filename)))

        for item, target in planned:
            if item.is_dir() or item.filename.endswith(("/", "\\")):
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(item, "r") as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return len(members), total_size


def safe_extract_external(archive_path: str, destination: str) -> tuple[int, int]:
    """Validate and extract RAR/7z with Windows bsdtar when available."""
    tar_exe = shutil.which("tar")
    if not tar_exe:
        raise InstallSafetyError("Windows archive support was not found. Re-download this app as ZIP.")
    listing = subprocess.run(
        [tar_exe, "-tf", archive_path], capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace",
    )
    if listing.returncode != 0:
        raise InstallSafetyError("This RAR/7z file could not be safely inspected. Re-download it as ZIP.")
    names = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    if len(names) > MAX_ARCHIVE_FILES:
        raise InstallSafetyError(f"Archive contains too many files ({len(names):,}).")
    for name in names:
        _safe_member_target(destination, name)
    verbose = subprocess.run(
        [tar_exe, "-tvf", archive_path], capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace",
    )
    if verbose.returncode != 0:
        raise InstallSafetyError("This RAR/7z file could not be safely inspected. Re-download it as ZIP.")
    total_size = 0
    for line in verbose.stdout.splitlines():
        if not line.strip():
            continue
        entry_type = line.lstrip()[:1].casefold()
        if entry_type in {"l", "h"}:
            raise InstallSafetyError("Archive links are not allowed in an automatic GGF installation.")
        size_match = re.match(r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+", line.lstrip())
        if not size_match:
            raise InstallSafetyError("Archive sizes could not be verified. Re-download this app as ZIP.")
        total_size += int(size_match.group(1))
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise InstallSafetyError("Archive expands beyond the 40 GiB safety limit.")
    free_space = shutil.disk_usage(destination).free
    if free_space < total_size + 512 * 1024 * 1024:
        raise InstallSafetyError("There is not enough verified free space to safely extract this archive.")
    result = subprocess.run(
        [tar_exe, "-xf", archive_path, "-C", destination],
        capture_output=True, text=True, timeout=3600,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise InstallSafetyError(f"Archive extraction failed: {result.stderr.strip()[:300]}")
    return len(names), total_size


def extract_archive(archive_path: str, destination: str) -> tuple[int, int | None]:
    extension = os.path.splitext(archive_path)[1].lower()
    if extension == ".zip":
        return safe_extract_zip(archive_path, destination)
    if extension in {".rar", ".7z"}:
        return safe_extract_external(archive_path, destination)
    raise InstallSafetyError(f"Unsupported archive type: {extension or '(none)'}")


def _walk_candidates(install_dir: str):
    for root, dirs, files in os.walk(install_dir):
        dirs[:] = [directory for directory in dirs if directory.casefold() not in SKIP_SCAN_DIRS]
        relative_root = os.path.relpath(root, install_dir)
        depth = 0 if relative_root == "." else len(Path(relative_root).parts)
        if depth > 5:
            dirs[:] = []
            continue
        for filename in files:
            yield os.path.join(root, filename), depth


def discover_install_files(install_dir: str) -> dict:
    """Return candidates plus only high-confidence automatic selections."""
    installers = []
    launchers = []
    executables = []
    for path, depth in _walk_candidates(install_dir):
        name = os.path.basename(path).casefold()
        ext = os.path.splitext(name)[1]
        if ext not in {".bat", ".cmd", ".exe"}:
            continue
        if "uninstall" in name or name.startswith("unins"):
            continue
        if ext == ".exe":
            executables.append(path)
        if any(word in name for word in ("install", "setup")):
            installers.append((path, depth))
        elif any(word in name for word in ("run", "start", "launch")):
            launchers.append((path, depth))

    def unique_best(candidates, preferred_names):
        ranked = []
        for path, depth in candidates:
            name = os.path.basename(path).casefold()
            try:
                name_rank = preferred_names.index(name)
            except ValueError:
                name_rank = len(preferred_names) + 10
            ranked.append(((name_rank, depth, len(path)), path))
        ranked.sort(key=lambda pair: pair[0])
        if not ranked:
            return None
        if len(ranked) == 1 or ranked[0][0] < ranked[1][0]:
            return ranked[0][1]
        return None

    best_installer = unique_best(
        installers,
        ["install.bat", "install.cmd", "setup.bat", "setup.cmd", "installer.exe", "setup.exe"],
    )
    best_launcher = unique_best(
        launchers,
        ["run.bat", "run.cmd", "start.bat", "start.cmd", "launch.bat", "launch.cmd"],
    )
    if not best_launcher:
        portable = [path for path in executables if path != best_installer]
        if len(portable) == 1:
            best_launcher = portable[0]

    return {
        "installers": [path for path, _depth in installers],
        "launchers": [path for path, _depth in launchers],
        "executables": executables,
        "best_installer": best_installer,
        "best_launcher": best_launcher,
    }


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
    return True, "", os.path.isfile(marker_path)
