"""Install separately licensed Windows components directly from their upstream wheels."""
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import queue
import ssl
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile

RESOURCE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DLL_HANDLES = []

def open_license():
    path = RESOURCE / "LICENSE.txt"
    if not path.is_file():
        path = RESOURCE.parent / "LICENSE.txt"
    os.startfile(path)


def _install(base, target, rows, update):
    base.mkdir(parents=True, exist_ok=True)
    cache = base / "wheels"
    cache.mkdir(exist_ok=True)
    with (base / "setup.lock").open("a+b") as lock:
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                update("Waiting for another GGF setup…", 0)
                time.sleep(.5)
        if (target / "ready").is_file():
            return
        total = sum(row["size"] for row in rows)
        done = 0
        for row in rows:
            wheel = cache / row["file"]
            if wheel.is_file():
                with wheel.open("rb") as existing:
                    valid = hashlib.file_digest(existing, "sha256").hexdigest() == row["sha256"]
                if not valid:
                    wheel.rename(cache / (wheel.name + ".damaged-" + uuid.uuid4().hex[:10]))
            if not wheel.is_file():
                if not row["url"].startswith("https://files.pythonhosted.org/"):
                    raise ValueError("Unexpected component publisher")
                update("Downloading " + row["name"], done / total)
                digest = hashlib.sha256()
                received = 0
                # An interrupted transfer never becomes an installed or cached wheel.
                partial = cache / (wheel.name + ".partial")
                with partial.open("wb") as out:
                    with urllib.request.urlopen(row["url"], timeout=35, context=ssl.create_default_context()) as response:
                        while block := response.read(1024 * 1024):
                            received += len(block)
                            if received > row["size"]:
                                raise ValueError("Unexpected component size")
                            digest.update(block)
                            out.write(block)
                            update("Downloading " + row["name"], (done + received) / total)
                if received != row["size"] or digest.hexdigest() != row["sha256"]:
                    raise ValueError("The component did not match its published SHA-256")
                os.rename(partial, wheel)
            done += row["size"]
        stage = Path(tempfile.mkdtemp(prefix="setup-", dir=base))
        for row in rows:
            wheel = cache / row["file"]
            update("Installing " + row["name"], 1.0)
            with wheel.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                    raise ValueError("A cached component failed verification: " + str(wheel))
                stream.seek(0)
                with zipfile.ZipFile(stream) as archive:
                    for member in archive.infolist():
                        if not (stage / member.filename).resolve().is_relative_to(stage):
                            raise ValueError("Unexpected component path")
                    archive.extractall(stage)
        (stage / "ready").write_text("Publisher hashes verified before installation.\n", encoding="ascii")
        os.rename(stage, target)


def _interactive(base, target, rows):
    import tkinter as tk
    from tkinter import messagebox, ttk
    root = tk.Tk()
    root.title("Set up GGF Tray")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=18)
    frame.pack()
    message = tk.StringVar(value="Downloading the Windows interface and media components…")
    ttk.Label(frame, textvariable=message, wraplength=390).pack(anchor="w", pady=(0, 10))
    bar = ttk.Progressbar(frame, length=390, maximum=100)
    bar.pack()
    ttk.Button(frame, text="View GGF license", command=open_license).pack(anchor="e", pady=(8, 0))
    errors = []
    events = queue.Queue()
    def install():
        try:
            _install(base, target, rows, lambda text, value: events.put((text, value)))
        except Exception as exc:
            errors.append(exc)
        finally:
            events.put(None)
    def refresh():
        while not events.empty():
            item = events.get_nowait()
            if item is None:
                if errors:
                    messagebox.showerror("GGF setup", str(errors[0]) + "\n\nReopen GGF Tray to retry.", parent=root)
                root.destroy()
                return
            message.set(item[0])
            bar["value"] = 100 * item[1]
        root.after(80, refresh)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    threading.Thread(target=install, daemon=True).start()
    root.after(0, refresh)
    root.mainloop()
    if errors or not (target / "ready").is_file():
        raise SystemExit(1)


def activate():
    manifest = (RESOURCE / "windows-components.json").read_bytes()
    base = Path(os.environ["LOCALAPPDATA"]) / "GGF-Tray" / "components"
    target = base / hashlib.sha256(manifest.replace(b"\r\n", b"\n")).hexdigest()[:12]
    if not (target / "ready").is_file():
        if "--startup" in sys.argv:
            raise SystemExit(0)
        rows = json.loads(manifest)
        if "--setup-unattended" in sys.argv or "--self-test" in sys.argv:
            try:
                _install(base, target, rows, lambda text, value: None)
            except Exception as exc:
                (base / "setup-error.txt").write_text(str(exc), encoding="utf-8")
                raise SystemExit(1)
        else:
            _interactive(base, target, rows)
    # Keep the official application's own modules ahead of independently replaceable libraries.
    sys.path.append(str(target))
    qt = target / "PySide6"
    for directory in (qt, target / "shiboken6"):
        DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    os.environ["QT_PLUGIN_PATH"] = str(qt / "plugins")
    os.environ["QTWEBENGINEPROCESS_PATH"] = str(qt / "QtWebEngineProcess.exe")
    os.environ["QTWEBENGINE_RESOURCES_PATH"] = str(qt / "resources")
    os.environ["QTWEBENGINE_LOCALES_PATH"] = str(qt / "translations" / "qtwebengine_locales")
    return target
