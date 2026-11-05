"""First-party Get Going Fast desktop authentication.

The tray creates a short random linking token, opens the current GGF member
login in the browser, and polls the site until the member explicitly links the
desktop app.  Cached bearer data is protected with Windows DPAPI.
"""

import ctypes
import hashlib
import re
import json
import os
import secrets
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from ctypes import wintypes

from ggf_runtime import (
    configure_ssl_environment,
    get_app_dir,
    get_state_dir,
    redact_secrets,
    urlopen_with_ssl,
)


configure_ssl_environment()
TOKEN_PATTERN_PREFIX = "ggf_desktop_"
DPAPI_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


if os.name == "nt":
    ctypes.windll.crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    ctypes.windll.crypt32.CryptProtectData.restype = wintypes.BOOL
    ctypes.windll.crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    ctypes.windll.crypt32.CryptUnprotectData.restype = wintypes.BOOL
    ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p


def _dpapi_protect(payload: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("GGF Tray authentication requires Windows DPAPI.")
    buffer = ctypes.create_string_buffer(payload)
    in_blob = _DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), "GGF Tray authentication", None, None, None,
        DPAPI_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(payload: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("GGF Tray authentication requires Windows DPAPI.")
    buffer = ctypes.create_string_buffer(payload)
    in_blob = _DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        DPAPI_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


class AuthManager:
    def __init__(self, cache_file=None):
        self.cache_file = cache_file or os.path.join(get_state_dir(), "auth_desktop_v2.dat")
        self.verify_url = "https://getgoingfast.pro/app-auth-check.php"
        self.login_url = "https://getgoingfast.pro/app-link.php"
        self.cached_auth = None
        self.load_cache()

    def load_cache(self):
        self.cached_auth = None
        try:
            with open(self.cache_file,"rb") as stream:
                data = json.loads(_dpapi_unprotect(stream.read()).decode())
            if isinstance(data,dict) and data.get("expires",0)>time.time() and re.fullmatch(r"ggf_desktop_[A-Za-z0-9_-]{43}",data.get("token","")):
                self.cached_auth = data
        except (OSError, TypeError, ValueError): pass

    def save_cache(self, auth_data):
        """Atomically save auth data encrypted for the current Windows user."""
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_file)), exist_ok=True)
        encoded = json.dumps(auth_data, separators=(",", ":")).encode("utf-8")
        protected = _dpapi_protect(encoded)
        fd, temp_path = tempfile.mkstemp(prefix="ggf-auth-", suffix=".tmp", dir=os.path.dirname(self.cache_file))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(protected)
            os.replace(temp_path, self.cache_file)
            self.cached_auth = auth_data
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def clear_cache(self):
        self.cached_auth = None
        self.save_cache({})
        self.cached_auth = None

    def logout(self):
        self.load_cache()
        token = (self.cached_auth or {}).get("token")
        self.clear_cache()
        if not token: return True
        try:
            req=urllib.request.Request(self.verify_url,data=b"action=revoke",headers={"X-GGF-App-Token":token,"User-Agent":"GGF-Tray/0.13 (Windows; Member Catalog)"})
            with urlopen_with_ssl(req,timeout=8) as reply:
                return json.load(reply).get("revoked") is True
        except Exception:
            return False

    @staticmethod
    def generate_token():
        return TOKEN_PATTERN_PREFIX + secrets.token_urlsafe(32)

    def check_token(self, token):
        """Return verified auth data, or None while unlinked/unavailable."""
        try:
            return self.verify_link(token)
        except (OSError, ValueError):
            return None

    def verify_link(self, token):
        """A 401 means the browser has not confirmed. Other failures are actionable."""
        try:
            req = urllib.request.Request(
                self.verify_url,
                headers={
                    "User-Agent": "GGF-Tray-App/0.13",
                    "X-GGF-App-Token": token,
                    "Cache-Control": "no-store",
                },
            )
            with urlopen_with_ssl(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict) or data.get("protocol") != 2 or data.get("authenticated") is not True:
                raise ValueError("The website did not confirm the desktop link.")
            server_expires = int(data.get("expires") or 0)
            if server_expires <= int(time.time()):
                raise ValueError("The website returned an expired link. Cancel and sign in again.")
            return {
                "tier": data.get("tier", "free"),
                "name": data.get("name", "User"),
                "expires": server_expires,
                "token": token,
                "verified_at": time.time(),
            }
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 401:
                return None
            if exc.code == 403:
                raise PermissionError("GGF could not approve this account for desktop access.") from None
            raise ConnectionError(f"GGF could not check the link (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            raise ConnectionError("Could not reach GGF to check the link.") from None

    def get_auth(self, force_refresh=False):
        self.load_cache()
        if not self.cached_auth:
            return None
        if self.cached_auth.get("expires", 0) <= time.time():
            self.clear_cache()
            return None
        if not force_refresh:  # Display only; each transfer rechecks the live account on the server.
            return self.cached_auth
        token = self.cached_auth.get("token")
        if not token:
            self.clear_cache()
            return None
        refreshed = self.check_token(token)
        if refreshed:
            self.save_cache(refreshed)
            return refreshed
        return None

    def open_link(self, token):
        """Reopen the same public challenge; never send the bearer to a browser."""
        login_url = f"{self.login_url}?link_id={hashlib.sha256(token.encode()).hexdigest()}"
        return webbrowser.open(login_url)

    def login(self):
        token = self.generate_token()
        self.open_link(token)
        return token

    def poll_for_auth(self, token, timeout=300, interval=4, cancelled=lambda:False):
        start_time = time.time()
        while time.time() - start_time < timeout and not cancelled():
            auth_data = self.check_token(token)
            if auth_data:
                self.save_cache(auth_data)
                print(f"Login successful for {auth_data['name']} ({auth_data['tier']}).")
                return auth_data
            time.sleep(interval)
        print("Login timed out. Please try again.")
        return None

    def get_tier(self):
        auth = self.get_auth()
        return auth["tier"] if auth else "free"

    def get_name(self):
        auth = self.get_auth()
        return auth["name"] if auth else None

    def is_authenticated(self):
        return self.get_auth() is not None

    def has_tier_access(self, required_tier):
        tier_levels = {
            "free": 0,
            "prairie-dog": 1,
            "farm-hand": 2,
            "rancher": 3,
            "gunslinger": 4,
        }
        return tier_levels.get(self.get_tier(), 0) >= tier_levels.get(required_tier, 99)

    def format_tier_name(self, tier=None):
        tier = self.get_tier() if tier is None else tier
        names = {
            "free": "Free",
            "prairie-dog": "Prairie Dog",
            "farm-hand": "Farm Hand",
            "rancher": "Rancher",
            "gunslinger": "Gunslinger",
        }
        return names.get(tier, str(tier).replace("-", " ").title())


if __name__ == "__main__":
    manager = AuthManager()
    if manager.is_authenticated():
        print(f"Authenticated as {manager.get_name()} ({manager.format_tier_name()}).")
    else:
        print("Not authenticated.")
