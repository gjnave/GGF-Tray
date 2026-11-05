import json
from pathlib import Path
from ggf_runtime import get_state_dir


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
