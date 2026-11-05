import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request

try:
    import certifi
except ImportError:
    certifi = None

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None


def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_state_dir():
    """Return the per-user writable state folder used by logs and credentials."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    state_dir = os.path.join(base, "GGF-Tray")
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def redact_secrets(value):
    """Remove bearer-style GGF tokens before a value reaches logs or errors."""
    text = str(value)
    text = re.sub(r"ggf_(?:tray|desktop)_[A-Za-z0-9_-]{24,}", "ggf_tray_[REDACTED]", text)
    text = re.sub(r"([?&](?:token|app_token)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
    return text


def configure_ssl_environment(env=None):
    target = env if env is not None else os.environ
    if certifi is not None:
        cert_path = certifi.where()
        target["SSL_CERT_FILE"] = cert_path
        target["REQUESTS_CA_BUNDLE"] = cert_path
        target["CURL_CA_BUNDLE"] = cert_path
    return target


def get_ssl_context():
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def urlopen_with_ssl(request_or_url, timeout=None):
    if isinstance(request_or_url, urllib.request.Request) and request_or_url.has_header("X-ggf-app-token"):
        from urllib.parse import urlsplit
        origin = urlsplit(request_or_url.full_url)
        if (origin.scheme,origin.netloc) != ("https","getgoingfast.pro"):
            raise ValueError("Invalid member API origin.")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args): return None
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=get_ssl_context()))
        return opener.open(request_or_url, timeout=timeout)
    kwargs = {"context": get_ssl_context()}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return urllib.request.urlopen(request_or_url, **kwargs)


def get_ffmpeg_executable():
    # Only use the encoder in the installed upstream component in a member build.
    if getattr(sys, "frozen", False) and imageio_ffmpeg:
        from pathlib import Path
        binaries = Path(imageio_ffmpeg.__file__).resolve().parent / "binaries"
        return next((str(path) for path in binaries.glob("ffmpeg-*.exe") if path.is_file()), None)
    if getattr(sys, "frozen", False):
        return None
    if imageio_ffmpeg is not None:
        try:
            candidate = imageio_ffmpeg.get_ffmpeg_exe()
            if candidate and os.path.exists(candidate):
                return candidate
        except Exception:
            pass

    return shutil.which("ffmpeg")


def launch_console_command(command_args, cwd=None, env=None, keep_open=True):
    launch_env = os.environ.copy()
    configure_ssl_environment(launch_env)
    if env:
        launch_env.update(env)

    # Expand quoted environment variables once, with delayed expansion off.
    # This also keeps literal %, &, ( and ) in Windows paths out of cmd syntax.
    launch_env.pop("GGF_TRAY_IPC_TOKEN",None)
    refs = []
    for i, part in enumerate(command_args):
        arg = str(part)
        if any(c in arg for c in ('"', '\r', '\n', '\x00')):
            raise ValueError("Unsupported character in command argument.")
        key = f"GGF_LAUNCH_ARG_{i}"
        launch_env[key] = arg
        refs.append('"%'+key+'%"')
    shell = os.path.join(os.environ["SystemRoot"],"System32","cmd.exe")
    command_line = '"'+shell+'" /d /v:off /s '+('/k' if keep_open else '/c')+' "'+' '.join(refs)+'"'
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(
        command_line, executable=shell,
        cwd=cwd,
        env=launch_env,
        creationflags=creationflags,
    )


def run_local_target(path):
    file = os.path.abspath(os.fspath(path))
    if not os.path.isfile(file): raise FileNotFoundError(file)
    if file.lower().endswith((".bat",".cmd")):
        return launch_console_command([file], cwd=os.path.dirname(file), keep_open=False)
    if file.lower().endswith(".exe"):
        return subprocess.Popen([file],cwd=os.path.dirname(file),env={k:v for k,v in os.environ.items() if k!="GGF_TRAY_IPC_TOKEN"})
    return os.startfile(file, cwd=os.path.dirname(file))

def user_file(name):
    target = os.path.join(get_state_dir(), name)
    old = os.path.join(get_app_dir(), name)
    if not os.path.exists(target) and os.path.isfile(old):
        try:
            with open(old,"rb") as src, open(target,"xb") as dst: shutil.copyfileobj(src,dst)
        except FileExistsError: pass
    return target
