import os
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
    kwargs = {"context": get_ssl_context()}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return urllib.request.urlopen(request_or_url, **kwargs)


def get_ffmpeg_executable():
    candidate_dirs = [get_app_dir(), get_resource_dir()]
    for directory in candidate_dirs:
        candidate = os.path.join(directory, "ffmpeg.exe")
        if os.path.exists(candidate):
            return candidate

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

    command_line = subprocess.list2cmdline([str(part) for part in command_args])
    cmd_switch = "/k" if keep_open else "/c"
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(
        ["cmd.exe", cmd_switch, command_line],
        cwd=cwd,
        env=launch_env,
        creationflags=creationflags,
    )

