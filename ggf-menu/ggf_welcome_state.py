import json
import os
from pathlib import Path
import re
from ggf_runtime import get_app_dir, get_state_dir


def managed_install():
    folder = Path(get_app_dir()).resolve()
    local = os.environ.get("LOCALAPPDATA")
    return bool(local and re.fullmatch(r"Tray-\d+\.\d+\.\d+", folder.name, re.I)
                and folder.parent == (Path(local) / "Programs/Get Going Fast").resolve())


def tray_notice_marker():
    # Running the standalone EXE should not consume the actual installation welcome.
    kind = "installed" if managed_install() else "standalone"
    return Path(get_state_dir()) / f"tray-notice-{kind}.seen"


def welcome_seen():
    state = Path(get_state_dir())
    if (state / "welcome-v1.seen").is_file():
        return True
    try:
        # Older releases marked intro_shown before displaying anything. Only
        # tourSeen recorded actual completion of the original toolbar tour.
        return json.loads((state / "visualizer_config.json").read_text(encoding="utf-8")).get("tourSeen") is True
    except (OSError, ValueError, AttributeError):
        return False


def remember_welcome():
    (Path(get_state_dir()) / "welcome-v1.seen").touch(exist_ok=True)
