"""One catalog per Windows user session across every tray and helper entry point."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading

from ggf_runtime import get_app_dir, get_state_dir

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
user = ctypes.WinDLL("user32", use_last_error=True)

def signature(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype = result
    fn.argtypes = args
    return fn

create = signature(kernel, "CreateEventW", wintypes.HANDLE, ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
open_event = signature(kernel, "OpenEventW", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
signal = signature(kernel, "SetEvent", wintypes.BOOL, wintypes.HANDLE)
wait = signature(kernel, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
close = signature(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
set_property = signature(user, "SetPropW", wintypes.BOOL, wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE)
get_property = signature(user, "GetPropW", wintypes.HANDLE, wintypes.HWND, wintypes.LPCWSTR)
process_id = signature(user, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
allow_foreground = signature(user, "AllowSetForegroundWindow", wintypes.BOOL, wintypes.DWORD)
foreground = signature(user, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
is_iconic = signature(user, "IsIconic", wintypes.BOOL, wintypes.HWND)
show_async = signature(user, "ShowWindowAsync", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
enumerate_windows = signature(user, "EnumWindows", wintypes.BOOL, callback_type, wintypes.LPARAM)
launch_lock = threading.Lock()
pending = None


def namespace():
    profile = os.path.normcase(os.path.realpath(get_state_dir()))
    return "GGF.Catalog." + hashlib.sha256(profile.encode("utf-8")).hexdigest()[:24]


def event_name(action):
    return "Local\\" + namespace() + "." + action


def ready_for_catalog_upgrade(*, interactive):
    """Older catalogs can outlive their tray. Wait for the owner to release its event."""
    while True:
        handle = open_event(0x00100000, False, event_name("show"))  # SYNCHRONIZE, no signal
        if not handle:
            error = ctypes.get_last_error()
            if error == 2:  # ERROR_FILE_NOT_FOUND
                return True
            raise ctypes.WinError(error)
        close(handle)  # Our own handle must not keep the old owner's event alive.
        if not interactive:
            return False
        answer = user.MessageBoxW(None,
            "The GGF App Catalog is still open. Finish any download or sign-in, "
            "close the catalog window, then choose Retry to continue installing.",
            "Close the GGF App Catalog", 0x10045)  # Set foreground, information, Retry/Cancel
        if answer != 4:  # IDRETRY
            return False


def activate_existing(welcome=False):
    handle = open_event(2, False, event_name("show"))
    if not handle:
        return False
    try:
        if welcome:
            tour = open_event(2, False, event_name("welcome"))
            if tour:
                signal(tour)
                close(tour)
        # Transfer focus eligibility from the process which received the click.
        marker = namespace()
        @callback_type
        def visit(hwnd, unused):
            if not get_property(hwnd, marker):
                return True
            pid = wintypes.DWORD()
            process_id(hwnd, ctypes.byref(pid))
            allow_foreground(pid.value)
            if is_iconic(hwnd):
                show_async(hwnd, 9)  # SW_RESTORE
            foreground(hwnd)
            return False
        enumerate_windows(visit, 0)
        signal(handle)
        return True
    finally:
        close(handle)


def launch_catalog(welcome=False):
    global pending
    with launch_lock:
        if activate_existing(welcome):
            return
        # A double click may arrive while the one-file EXE is still unpacking.
        if not welcome and pending is not None and pending.poll() is None:
            return
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args.append(str(Path(get_app_dir()) / "app_search.py"))
        else:
            args.append("--run-app-search")
        if welcome:
            args.append("--welcome")
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        pending = subprocess.Popen(args, cwd=get_app_dir(), env=env)


class CatalogOwner:
    def __init__(self):
        # Publish the optional tour event before making the activation event visible.
        self.tour = create(None, False, False, event_name("welcome"))
        if not self.tour:
            raise ctypes.WinError(ctypes.get_last_error())
        self.show = create(None, False, False, event_name("show"))
        existed = ctypes.get_last_error() == 183
        if not self.show:
            close(self.tour)
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = not existed

    def attach(self, window):
        set_property(int(window.winId()), namespace(), 1)

    def consume(self):
        show = wait(self.show, 0) == 0
        tour = wait(self.tour, 0) == 0
        return show or tour, tour

    def release(self):
        close(self.show)
        close(self.tour)

