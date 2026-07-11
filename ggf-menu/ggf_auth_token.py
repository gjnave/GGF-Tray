"""First-party Get Going Fast desktop authentication.

The tray creates a short random linking token, opens the current GGF member
login in the browser, and polls the site until the member explicitly links the
desktop app.  Cached bearer data is protected with Windows DPAPI.
"""

import ctypes
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
TOKEN_PATTERN_PREFIX = "ggf_tray_"
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
        self.cache_file = cache_file or os.path.join(get_state_dir(), "auth_cache.dat")
        self.legacy_cache_files = {
            os.path.join(get_state_dir(), "auth_cache.json"),
            os.path.join(get_app_dir(), "auth_cache.json"),
        }
        self.verify_url = "https://getgoingfast.pro/app-auth-check.php"
        self.login_url = "https://getgoingfast.pro/app-link.php"
        self.cached_auth = None
        self.load_cache()

    def _load_legacy_cache(self):
        for path in self.legacy_cache_files:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self.save_cache(data)
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return data
            except (OSError, ValueError, TypeError):
                continue
        return None

    def load_cache(self):
        """Load the current user's DPAPI-protected authentication cache."""
        data = None
        if os.path.isfile(self.cache_file):
            try:
                with open(self.cache_file, "rb") as handle:
                    encrypted = handle.read()
                data = json.loads(_dpapi_unprotect(encrypted).decode("utf-8"))
            except Exception as exc:
                print(f"Could not read protected login cache: {redact_secrets(exc)}")
        if not isinstance(data, dict):
            data = self._load_legacy_cache()
        if isinstance(data, dict) and data.get("expires", 0) > time.time():
            self.cached_auth = data
        else:
            self.cached_auth = None
            if os.path.exists(self.cache_file):
                try:
                    os.remove(self.cache_file)
                except OSError:
                    pass

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
        for path in {self.cache_file, *self.legacy_cache_files}:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    @staticmethod
    def generate_token():
        return TOKEN_PATTERN_PREFIX + secrets.token_urlsafe(32)

    def check_token(self, token):
        """Return verified auth data, or None while unlinked/unavailable."""
        try:
            # Send the token BOTH as a header (preferred -- keeps it out of most
            # logs) and as a ?token= query param (fallback for a server that only
            # reads the query). The token is URL-safe by construction, so it needs
            # no escaping. This makes login work whether or not the header-aware
            # app-auth-check.php has been deployed yet.
            sep = "&" if "?" in self.verify_url else "?"
            req = urllib.request.Request(
                f"{self.verify_url}{sep}token={token}",
                headers={
                    "User-Agent": "GGF-Tray-App/0.12",
                    "X-GGF-App-Token": token,
                    "Cache-Control": "no-store",
                },
            )
            with urlopen_with_ssl(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not data.get("authenticated"):
                return None
            server_expires = int(data.get("expires") or 0)
            if server_expires <= int(time.time()):
                return None
            return {
                "tier": data.get("tier", "free"),
                "name": data.get("name", "User"),
                "expires": server_expires,
                "token": token,
                "verified_at": time.time(),
            }
        except urllib.error.HTTPError as exc:
            if exc.code not in {400, 401, 403, 404}:
                print(f"Login check failed with HTTP {exc.code}")
            return None
        except urllib.error.URLError:
            return None
        except Exception as exc:
            print(f"Error checking login: {redact_secrets(exc)}")
            return None

    def get_auth(self, force_refresh=False):
        if not self.cached_auth:
            return None
        if self.cached_auth.get("expires", 0) <= time.time():
            self.clear_cache()
            return None
        if not force_refresh and self.cached_auth.get("verified_at", 0) > time.time() - 3600:
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

    def login(self):
        token = self.generate_token()
        login_url = f"{self.login_url}?app=tray&app_token={token}"
        print("Opening the browser for Get Going Fast login...")
        webbrowser.open(login_url)
        return token

    def poll_for_auth(self, token, timeout=300, interval=2):
        start_time = time.time()
        while time.time() - start_time < timeout:
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
