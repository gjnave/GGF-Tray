"""Manage GGF's per-user Startup shortcut without elevation."""
import os
from pathlib import Path
import subprocess
import sys
import threading

from ggf_runtime import get_app_dir, get_resource_dir, get_state_dir

_lock = threading.Lock()
LINK_NAME = "GGF Tray.lnk"


def paths():
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    parked = Path(get_state_dir()) / "startup-preference" / LINK_NAME
    return startup / LINK_NAME, parked


def is_registered():
    active, _ = paths()
    return active.is_file()


def configure(mode="default"):
    if mode not in {"default","install","on","off"}:
        raise ValueError("Invalid startup mode.")
    active, parked = paths()
    if mode == "default" and parked.exists() and not active.exists():
        return False
    with _lock:
        target = Path(sys.executable)
        arguments = "--startup"
        if not getattr(sys,"frozen",False):
            pythonw = target.with_name("pythonw.exe")
            if not pythonw.is_file():
                raise OSError("The windowless Python launcher is missing.")
            target = pythonw
            arguments = subprocess.list2cmdline([str(Path(get_app_dir())/"ggf-tray.py"),"--startup"])
        active.parent.mkdir(parents=True,exist_ok=True)
        parked.parent.mkdir(parents=True,exist_ok=True)
        helper = Path(get_resource_dir()) / "ggf-startup.js"
        cscript = Path(os.environ["SystemRoot"]) / "System32/cscript.exe"
        result = subprocess.run(
            [str(cscript),"//nologo","//E:JScript",str(helper),mode,str(active),str(parked),
             str(target),arguments,get_app_dir()],
            capture_output=True,text=True,errors="replace",timeout=15,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
        )
        if result.returncode:
            raise OSError((result.stdout or result.stderr).strip() or "Windows could not update the GGF Startup shortcut.")
        return active.is_file()

