"""
GGF System Tray - A system tray icon for Get Going Fast Menu
"""
import os
import sys
from ggf_components import open_license
if getattr(sys, "frozen", False):
    from ggf_components import activate
    activate()
import json
import subprocess
import tkinter as tk
from tkinter import messagebox
from PIL import Image
import psutil
import pystray
from pystray import MenuItem as item
import threading
import configparser
import ctypes
import socket
import time
import shutil
import secrets
from ggf_media import ACTIONS as MEDIA_ACTIONS
from ggf_catalog_window import launch_catalog
from ggf_welcome_state import tray_notice_marker
import ggf_startup
from ggf_runtime import user_file
from ggf_setup import prepare, launch_entry
from ctypes import wintypes
from ggf_runtime import (
    configure_ssl_environment,
    get_ffmpeg_executable,
    get_state_dir,
    launch_console_command,
    urlopen_with_ssl,
)
from ggf_installer import (
    InstallSafetyError,
    discover_install_files,
    extract_archive,
    load_registry,
    remove_registry_entry,
    safe_install_path,
    sanitize_folder_name,
    upsert_registry,
    validate_delete_target,
    write_install_marker,
)

# ============================================================================
# DISABLE ALL BEEPS - Multiple approaches to ensure silence
# ============================================================================
try:
    # Method 1: Disable Windows system sounds
    ctypes.windll.kernel32.Beep = lambda x, y: None
    
    # Method 2: Override MessageBeep
    original_beep = ctypes.windll.user32.MessageBeep
    ctypes.windll.user32.MessageBeep = lambda x: 0
    
    # Method 3: Monkey patch ALL tkinter messagebox functions to suppress beep
    import tkinter.messagebox as mb
    
    # Store originals
    _orig_showinfo = mb.showinfo
    _orig_showwarning = mb.showwarning
    _orig_showerror = mb.showerror
    _orig_askquestion = mb.askquestion
    _orig_askokcancel = mb.askokcancel
    _orig_askyesno = mb.askyesno
    _orig_askretrycancel = mb.askretrycancel
    
    # Create silent wrappers
    def silent_wrapper(func):
        def wrapper(*args, **kwargs):
            # Mute beep before showing
            ctypes.windll.user32.MessageBeep(0xFFFFFFFF)
            result = func(*args, **kwargs)
            return result
        return wrapper
    
    # Apply wrappers
    mb.showinfo = silent_wrapper(_orig_showinfo)
    mb.showwarning = silent_wrapper(_orig_showwarning)
    mb.showerror = silent_wrapper(_orig_showerror)
    mb.askquestion = silent_wrapper(_orig_askquestion)
    mb.askokcancel = silent_wrapper(_orig_askokcancel)
    mb.askyesno = silent_wrapper(_orig_askyesno)
    mb.askretrycancel = silent_wrapper(_orig_askretrycancel)
    
except Exception as e:
    print(f"Could not disable beeps: {e}")

# Import auth manager (will be in same directory)
try:
    from ggf_auth_token import AuthManager
    AUTH_AVAILABLE = True
except ImportError:
    print("Warning: Auth system not available")
    AUTH_AVAILABLE = False
    AuthManager = None

def get_resource_dir():
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_subprocess_env():
    env = os.environ.copy()
    if getattr(sys, 'frozen', False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return configure_ssl_environment(env)


RESOURCE_DIR = get_resource_dir()
SCRIPT_DIR = get_app_dir()
STATE_DIR = get_state_dir()
ICON_PATH = os.path.join(RESOURCE_DIR, "ggf-mark.ico")
SHORTCUTS_CONFIG = user_file("shortcuts.txt")
CONFIG_PATH = user_file("config.txt")
TRAY_UI_STATE_PATH = os.path.join(STATE_DIR, "tray_ui_state.json")
INSTALLED_APPS_CONFIG = user_file("installed_apps.txt")
DEFAULT_CONFIG_TEXT = """[General]
output_suffix = _converted
skip_comfyui_prompt = false
hide_to_tray = false
first_run = false

[Image]
resize_percent = 50
resize_max_width = 1920
convert_formats = jpg,png,webp

[Video]
video_preset = medium
video_crf = 23
video_codec = libx264
audio_codec = aac
audio_bitrate = 192k
shrink_bitrate = 2000k
shrink_resolution = 1080p
gif_fps = 10
gif_scale = 480
convert_formats = mp4,avi,webm,mkv,mov,gif
audio_extract_formats = mp3,wav,ogg,aac,flac,m4a

[Transcribe]
output_formats = txt,srt
whisper_model = base

[Download]
yt_dlp_format = bestvideo+bestaudio
output_template = %(title)s.%(ext)s
default_download_dir = Downloads

[Paths]
comfyui_path =
"""

# Windows mutex for single instance check
MUTEX_NAME = "Global\\GGF-Tray-Unique-Mutex-87A3F9B2"
mutex_handle = None
APP_ID = "audio-v"  # Audio_visualizer.py 
WHISPER_ENABLED = False
UTILITY_ARGS = {"--tray-notice","--register-startup","--utility","--ggf-ytdlp","--install-zip", "--show-visualizer-menu", "--show-companion-menu", "--run-app-search", "--run-visualizer", "--self-test"}
TRAY_IPC_HOST = "127.0.0.1"
TRAY_IPC_PORT = 47653
TRAY_IPC_BUFFER = 65536
configure_ssl_environment()


def ensure_config_file():
    try:
        if not os.path.exists(CONFIG_PATH) or os.path.getsize(CONFIG_PATH) == 0:
            with open(CONFIG_PATH, "w", encoding="utf-8") as file_handle:
                file_handle.write(DEFAULT_CONFIG_TEXT)
    except Exception as exc:
        print(f"Error ensuring config file: {exc}")

def check_already_running():
    """Check if another instance is already running using Windows mutex"""
    global mutex_handle
    
    # Load kernel32 functions
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    
    # Try to create mutex
    mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    
    if not mutex_handle:
        return True
    
    # Check if mutex already existed (ERROR_ALREADY_EXISTS = 183)
    last_error = ctypes.get_last_error()
    if last_error == 183:
        return True
    
    return False

# Check if already running - only for main tray app, not utility subprocesses
if __name__ == "__main__" and not any(arg in UTILITY_ARGS for arg in sys.argv[1:]):
    if check_already_running():
        if "--startup" not in sys.argv:
            launch_catalog()
        sys.exit(0)

def get_config():
    """Read config"""
    ensure_config_file()
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
    return config

class GGFTray:
    def __init__(self):
        ensure_config_file()
        self.utility_mode = any(arg in UTILITY_ARGS for arg in sys.argv[1:])
        self.remote_menu_mode = "--show-companion-menu" in sys.argv or "--show-visualizer-menu" in sys.argv
        self.shortcuts = self.load_shortcuts()
        self.icon = None
        self.current_file = None
        self.failed_attempts = 0  # Track attempts without file
        self.command_server_socket = None
        self.command_server_thread = None
        self.command_server_stop = threading.Event()
        inherited_ipc_token = os.environ.get('GGF_TRAY_IPC_TOKEN', '')
        self.ipc_token = inherited_ipc_token if self.utility_mode else secrets.token_urlsafe(32)
        if not self.utility_mode:
            os.environ['GGF_TRAY_IPC_TOKEN'] = self.ipc_token
        self.helper_processes = []
        self.ui_state = self.load_ui_state()
        self.tips_thread = None
        
        # Initialize auth manager
        if AUTH_AVAILABLE:
            auth_cache_path = os.path.join(STATE_DIR, "auth_desktop_v2.dat")
            self.auth = AuthManager(cache_file=auth_cache_path)
            
            # Trigger initial auth check (will read from cache or browser)
            auth_status = self.auth.get_auth()
            if auth_status:
                print(f"Logged in as: {auth_status['name']} ({self.auth.format_tier_name()})")
            else:
                print("Not logged in - use 'Login to GGF' in app search")
        else:
            self.auth = None
            print("Auth system not available")

    def run_background_task(self, target, *args):
        """Keep helper-mode actions alive long enough to finish."""
        thread = threading.Thread(target=target, args=args, daemon=not self.utility_mode)
        thread.start()
        return thread

    def load_ui_state(self):
        state = {
            "show_tips_on_startup": True
        }
        try:
            if os.path.exists(TRAY_UI_STATE_PATH):
                with open(TRAY_UI_STATE_PATH, "r", encoding="utf-8") as file_handle:
                    loaded = json.load(file_handle)
                if isinstance(loaded, dict):
                    state.update(loaded)
        except Exception as exc:
            print(f"Error loading tray UI state: {exc}")
        return state

    def save_ui_state(self):
        try:
            with open(TRAY_UI_STATE_PATH, "w", encoding="utf-8") as file_handle:
                json.dump(self.ui_state, file_handle, indent=2)
        except Exception as exc:
            print(f"Error saving tray UI state: {exc}")

    def track_process(self, process):
        if process is not None:
            self.helper_processes.append(process)
        return process

    def cleanup_helper_processes(self):
        seen_pids = set()
        for process in list(self.helper_processes):
            try:
                if process and process.poll() is None and process.pid not in seen_pids:
                    seen_pids.add(process.pid)
                    process.kill()
            except Exception:
                pass

        self.helper_processes = []

    def on_icon_ready(self, icon):
        icon.visible = True
        if "--startup" in sys.argv or tray_notice_marker().is_file():
            return
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args.append(os.path.abspath(__file__))
        env = get_subprocess_env()
        env.pop("GGF_TRAY_IPC_TOKEN", None)
        try:
            self.track_process(subprocess.Popen([*args, "--tray-notice"], cwd=SCRIPT_DIR, env=env))
        except OSError:
            # Keep the tray usable. A later interactive launch can try again.
            pass

    def toggle_startup(self):
        try:
            mode = "off" if ggf_startup.is_registered() else "on"
            ggf_startup.configure(mode)
            self.refresh_shortcuts()
        except Exception as exc:
            self.show_message("Windows startup", str(exc), "error")

    def start_command_server(self):
        """Listen for commands from helper processes like the visualizer popup."""
        if self.utility_mode or self.command_server_thread:
            return

        def server_loop():
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.command_server_socket = server
            try:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                server.bind((TRAY_IPC_HOST, TRAY_IPC_PORT))
                server.listen(5)
                server.settimeout(0.5)
                while not self.command_server_stop.is_set():
                    try:
                        conn, _addr = server.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break

                    with conn:
                        conn.settimeout(1.0)
                        chunks = []
                        while True:
                            try:
                                chunk = conn.recv(TRAY_IPC_BUFFER)
                            except socket.timeout:
                                break
                            if not chunk:
                                break
                            chunks.append(chunk)
                            if sum(map(len,chunks)) > TRAY_IPC_BUFFER: break

                        response = self.handle_command_message(b"".join(chunks))
                        try:
                            conn.sendall(json.dumps(response).encode("utf-8"))
                        except Exception:
                            pass
            except Exception as exc:
                print(f"Tray command server error: {exc}")
            finally:
                try:
                    server.close()
                except Exception:
                    pass
                self.command_server_socket = None

        self.command_server_thread = threading.Thread(target=server_loop, daemon=True)
        self.command_server_thread.start()

    def stop_command_server(self):
        self.command_server_stop.set()
        if self.command_server_socket:
            try:
                self.command_server_socket.close()
            except Exception:
                pass

    def send_command_to_running_tray(self, command, **payload):
        """Send a helper-menu command to the live tray process."""
        message = {
            "command": command,
            "ipc_token": os.environ.get('GGF_TRAY_IPC_TOKEN', ''),
            **payload,
        }
        try:
            with socket.create_connection((TRAY_IPC_HOST, TRAY_IPC_PORT), timeout=2.0) as sock:
                sock.sendall(json.dumps(message).encode("utf-8"))
                sock.shutdown(socket.SHUT_WR)
                response = sock.recv(TRAY_IPC_BUFFER)
            if response:
                return json.loads(response.decode("utf-8"))
            return {"ok": True}
        except Exception as exc:
            print(f"Unable to reach running tray: {exc}")
            return {"ok": False, "error": str(exc)}

    def handle_command_message(self, raw_message):
        """Decode and dispatch helper-process commands."""
        try:
            if not raw_message:
                return {"ok": False, "error": "empty command"}
            payload = json.loads(raw_message.decode("utf-8"))
            return self.dispatch_remote_command(payload)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def dispatch_remote_command(self, payload):
        """Execute a whitelisted command from a helper process."""
        if not isinstance(payload, dict) or not secrets.compare_digest(
            str(payload.get('ipc_token', '')), self.ipc_token
        ):
            return {"ok": False, "error": "unauthorized command"}
        command = payload.get("command")

        if command == "ping":
            return {"ok": True, "message": "tray online"}
        if command == "menu_action":
            action = payload.get("action")
            if not action:
                return {"ok": False, "error": "missing action"}
            self.run_background_task(self.execute_menu_action, action)
            return {"ok": True}
        if command == "launch_shortcut":
            shortcut_name = payload.get("name")
            if not shortcut_name:
                return {"ok": False, "error": "missing shortcut"}
            self.launch_shortcut(shortcut_name)
            return {"ok": True}
        if command == "refresh_shortcuts":
            if self.auth: self.auth.load_cache()
            self.refresh_shortcuts()
            return {"ok": True}
        if command == "toggle_click_through":
            self.toggle_click_through()
            return {"ok": True}
        if command == "open_app_search":
            self.open_app_search()
            return {"ok": True}
        if command == "open_config":
            self.open_config()
            return {"ok": True}
        if command == "open_website":
            self.open_website()
            return {"ok": True}
        if command == "toggle_login":
            self.toggle_login()
            return {"ok": True}
        if command == "restart_app":
            self.restart_app()
            return {"ok": True}
        if command == "quit_tray":
            self.quit_tray()
            return {"ok": True}

        return {"ok": False, "error": f"unknown command: {command}"}

    def run_companion_command(self, command, **payload):
        """Route companion popup actions back to the running tray."""
        response = self.send_command_to_running_tray(command, **payload)
        if response.get("ok"):
            return True
        self.show_message(
            "GGF Tray Not Responding",
            "The main tray process did not accept the command.\n\nPlease restart GGF Tray and try again.",
            "error"
        )
        return False
        
        
    def iter_audio_visualizer_processes(self):
        proc=getattr(self,"_visualizer_proc",None)
        if proc and proc.poll() is None: yield proc

    def start_audio_visualizer(self, force_tour=False, music=False):
        if not getattr(sys, 'frozen', False):
            visualizer_path = os.path.join(SCRIPT_DIR, "audio_visualizer_tray.py")
        else:
            visualizer_path = None

        if not getattr(sys, 'frozen', False) and not os.path.exists(visualizer_path):
            self.show_message("Error", "Music Visualizer not found!", "error")
            return

        try:
            if any(True for _ in self.iter_audio_visualizer_processes()):
                if music or force_tour:
                    path = os.path.join(STATE_DIR,"visualizer_state.json")
                    state = self.get_visualizer_state() or {}
                    state["command"]="open_player" if music else "tour"
                    with open(path+".tray-tmp","w",encoding="utf-8") as out: json.dump(state,out)
                    os.replace(path+".tray-tmp",path)
                return

            # Launch fully hidden -- no console flash. CREATE_NO_WINDOW stops the
            # child (python.exe in dev, the windowed exe when frozen) from creating
            # or attaching a console; we avoid shell=True / `start`, which spins up a
            # visible cmd.exe. The visualizer's own Qt window still appears normally.
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP

            if getattr(sys, 'frozen', False):
                args = [sys.executable, "--run-visualizer", f"--app-id={APP_ID}"]
            else:
                args = [sys.executable, visualizer_path, f"--app-id={APP_ID}"]
            if music: args.append("--music")
            if force_tour:
                args.append("--tour")

            self._visualizer_proc = self.track_process(subprocess.Popen(
                args,
                cwd=SCRIPT_DIR,
                close_fds=True,
                creationflags=creationflags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=get_subprocess_env(),
            ))
        except Exception as e:
            self.show_message("Error", f"Failed to start visualizer:\n{str(e)}", "error")

    def close_audio_visualizer(self):
        for proc in self.iter_audio_visualizer_processes():
            try:
                proc.kill()
            except:
                pass


    def get_visualizer_state(self):
        """Read visualizer state file"""
        state_file = os.path.join(STATE_DIR, "visualizer_state.json")
        try:
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}

    def toggle_click_through(self):
        """Toggle click-through mode for visualizer"""
        state_file = os.path.join(STATE_DIR, "visualizer_state.json")
        
        # Get current state
        state = self.get_visualizer_state()
        current_setting = state.get('click_through', False)
        new_setting = not current_setting
        
        # Send command
        try:
            state['command'] = 'toggle_click_through'
            state['enabled'] = new_setting
            # Also optimistically update the state for immediate UI feedback
            state['click_through'] = new_setting
            
            with open(state_file, 'w') as f:
                json.dump(state, f)
                
            print(f"Toggled click through to: {new_setting}")
        except Exception as e:
            print(f"Error toggling click through: {e}")


    
    def show_message(self, title, message, msg_type="info"):
        """Show non-blocking message dialog"""
        import tkinter as tk
        from tkinter import messagebox
        
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        
        if msg_type == "error":
            messagebox.showerror(title, message, parent=root)
        elif msg_type == "warning":
            messagebox.showwarning(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
        
        root.destroy()
    
    def load_shortcuts(self):
        """Load shortcuts from config"""
        shortcuts = {}
        print(f"Loading shortcuts from: {SHORTCUTS_CONFIG}")
        
        if not os.path.exists(SHORTCUTS_CONFIG):
            print(f"Shortcuts config not found: {SHORTCUTS_CONFIG}")
            return shortcuts
            
        try:
            with open(SHORTCUTS_CONFIG, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        name, filepath = line.split('=', 1)
                        name = name.strip()
                        filepath = filepath.strip()
                        shortcuts[name] = filepath
                        print(f"Loaded shortcut: {name} -> {filepath}")
        except Exception as e:
            print(f"Error loading shortcuts: {e}")
            
        print(f"Total shortcuts loaded: {len(shortcuts)}")
        return shortcuts

    def upsert_shortcut(self, name, filepath):
        """Add or replace one shortcut without creating duplicate records."""
        shortcuts = self.load_shortcuts()
        for existing in list(shortcuts):
            if existing.casefold() == name.casefold():
                del shortcuts[existing]
        shortcuts[name] = os.path.abspath(filepath)
        temp_path = SHORTCUTS_CONFIG + '.tmp'
        with open(temp_path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write('# GGF Quick Launch shortcuts\n# Format: name=path\n')
            for shortcut_name in sorted(shortcuts, key=str.casefold):
                handle.write(f"{shortcut_name}={shortcuts[shortcut_name]}\n")
        os.replace(temp_path, SHORTCUTS_CONFIG)

    def remove_shortcut(self, name):
        shortcuts = self.load_shortcuts()
        filtered = {key: value for key, value in shortcuts.items() if key.casefold() != name.casefold()}
        if len(filtered) == len(shortcuts):
            return
        temp_path = SHORTCUTS_CONFIG + '.tmp'
        with open(temp_path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write('# GGF Quick Launch shortcuts\n# Format: name=path\n')
            for shortcut_name in sorted(filtered, key=str.casefold):
                handle.write(f"{shortcut_name}={filtered[shortcut_name]}\n")
        os.replace(temp_path, SHORTCUTS_CONFIG)

    def refresh_shortcuts(self):
        """Reload shortcuts"""
        self.shortcuts = self.load_shortcuts()
        # Rebuild menu (icon may not be ready yet during install)
        if self.icon:
            self.icon.menu = self.create_menu()
    
    def open_utility(self, action):
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args.append(os.path.join(SCRIPT_DIR, "ggf-tray.py"))
        try:
            env = get_subprocess_env()
            env.pop("GGF_TRAY_IPC_TOKEN", None)
            subprocess.Popen([*args, "--utility", action], cwd=SCRIPT_DIR, env=env)
        except OSError as exc:
            self.show_message("Could not start utility", str(exc), "error")

    def execute_menu_action(self, action):
        if action in MEDIA_ACTIONS or action in {"huggingface_browser", "resources"}:
            self.open_utility(action)
        elif action == "install_app":
            self.install_ggf_app()
        elif action == "delete_app":
            self.delete_ggf_app()
        elif action == "quick_launch":
            self.quick_launch_manager()
        elif action == "audio_visualizer":
            self.start_audio_visualizer()
        elif action == "show_tour":
            launch_catalog(welcome=True)
        elif action == "open_app_folder":
            try:
                os.startfile(SCRIPT_DIR)
            except OSError as exc:
                self.show_message("GGF Tray folder", str(exc), "error")
        elif action == "visualizer_guide":
            self.start_audio_visualizer(force_tour=True)
        elif action == "startup_toggle":
            self.toggle_startup()

    def open_menu_for(self, action):
        """Execute operation based on action type - run in thread to avoid blocking"""
        if self.utility_mode:
            self.execute_menu_action(action)
        else:
            self.run_background_task(self.execute_menu_action, action)

    def show_visualizer_companion_menu(self):
        """Show a tray-style popup menu for visualizer and Explorer companion entry."""
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        menu = tk.Menu(root, tearoff=0)

        def invoke_menu_action(action):
            root.destroy()
            if self.remote_menu_mode:
                self.run_companion_command("menu_action", action=action)
            else:
                self.open_menu_for(action)

        def invoke_command(command, **payload):
            root.destroy()
            if self.remote_menu_mode:
                self.run_companion_command(command, **payload)
            else:
                local_actions = {
                    "refresh_shortcuts": self.refresh_shortcuts,
                    "toggle_click_through": self.toggle_click_through,
                    "open_app_search": self.open_app_search,
                    "open_config": self.open_config,
                    "open_website": self.open_website,
                    "toggle_login": self.toggle_login,
                    "restart_app": self.restart_app,
                    "quit_tray": self.quit_tray,
                }
                handler = local_actions.get(command)
                if handler:
                    handler()

        def invoke_shortcut(shortcut_name):
            root.destroy()
            if self.remote_menu_mode:
                self.run_companion_command("launch_shortcut", name=shortcut_name)
            else:
                self.launch_shortcut(shortcut_name)

        if self.shortcuts:
            quick_launch_menu = tk.Menu(menu, tearoff=0)
            for name in sorted(self.shortcuts.keys(), key=lambda value: value.lower()):
                quick_launch_menu.add_command(
                    label=name,
                    command=lambda shortcut_name=name: invoke_shortcut(shortcut_name)
                )
            quick_launch_menu.add_separator()
            quick_launch_menu.add_command(label="Refresh List", command=lambda: invoke_command("refresh_shortcuts"))
            menu.add_cascade(label="Quick Launch", menu=quick_launch_menu)

        ai_apps_menu = tk.Menu(menu, tearoff=0)
        ai_apps_menu.add_command(label="Search for Apps", command=lambda: invoke_command("open_app_search"))
        ai_apps_menu.add_separator()
        ai_apps_menu.add_command(label="Quick Launch Manager", command=lambda: invoke_menu_action('quick_launch'))
        ai_apps_menu.add_command(label="Install GGF Apps", command=lambda: invoke_menu_action('install_app'))
        ai_apps_menu.add_command(label="Delete GGF Apps", command=lambda: invoke_menu_action('delete_app'))
        menu.add_cascade(label="A.I. Apps", menu=ai_apps_menu)

        image_menu = tk.Menu(menu, tearoff=0)
        image_menu.add_command(label="Convert to JPG", command=lambda: invoke_menu_action('convert_jpg'))
        image_menu.add_command(label="Convert to PNG", command=lambda: invoke_menu_action('convert_png'))
        image_menu.add_command(label="Convert to WebP", command=lambda: invoke_menu_action('convert_webp'))
        image_menu.add_command(label="Convert to BMP", command=lambda: invoke_menu_action('convert_bmp'))
        image_menu.add_separator()
        image_menu.add_command(label="Resize Image", command=lambda: invoke_menu_action('resize_image'))
        menu.add_cascade(label="Image Operations", menu=image_menu)

        audio_menu = tk.Menu(menu, tearoff=0)
        audio_menu.add_command(label="Convert to WAV", command=lambda: invoke_menu_action('convert_wav'))
        audio_menu.add_command(label="Convert to MP3", command=lambda: invoke_menu_action('convert_mp3'))
        audio_menu.add_command(label="Convert to AAC", command=lambda: invoke_menu_action('convert_aac'))
        audio_menu.add_command(label="Convert to M4A", command=lambda: invoke_menu_action('convert_m4a'))
        audio_menu.add_command(label="Convert to FLAC", command=lambda: invoke_menu_action('convert_flac'))
        audio_menu.add_command(label="Convert to OGG", command=lambda: invoke_menu_action('convert_ogg'))
        menu.add_cascade(label="Audio Operations", menu=audio_menu)

        video_menu = tk.Menu(menu, tearoff=0)
        video_menu.add_command(label="Convert Video", command=lambda: invoke_menu_action('convert_video'))
        video_menu.add_command(label="Shrink Video", command=lambda: invoke_menu_action('shrink_video'))
        video_menu.add_command(label="Download Video", command=lambda: invoke_menu_action('download'))
        video_menu.add_separator()
        video_menu.add_command(label="Save First Frame", command=lambda: invoke_menu_action('save_first_frame'))
        video_menu.add_command(label="Save Last Frame", command=lambda: invoke_menu_action('save_last_frame'))
        menu.add_cascade(label="Video Operations", menu=video_menu)

        visualizer_menu = tk.Menu(menu, tearoff=0)
        visualizer_menu.add_command(label="Start Visualizer", command=lambda: invoke_menu_action('audio_visualizer'))
        click_label = "Click Through Off" if self.get_visualizer_state().get('click_through', False) else "Click Through"
        visualizer_menu.add_command(label=click_label, command=lambda: invoke_command("toggle_click_through"))
        menu.add_cascade(label="Music Visualizer", menu=visualizer_menu)

        utility_menu = tk.Menu(menu, tearoff=0)
        utility_menu.add_command(label="GGF Resource Search (members)", command=lambda: invoke_menu_action("resources"))
        utility_menu.add_command(label="HuggingFace Model Browser", command=lambda: invoke_menu_action('huggingface_browser'))
        utility_menu.add_separator()
        utility_menu.add_command(label="Open Config File", command=lambda: invoke_command("open_config"))
        menu.add_cascade(label="Utility", menu=utility_menu)

        menu.add_separator()
        menu.add_command(label="Welcome tour…", command=lambda: invoke_menu_action("show_tour"))
        menu.add_command(label="Open GGF Tray folder", command=lambda: invoke_menu_action("open_app_folder"))
        startup_value = tk.BooleanVar(root, value=ggf_startup.is_registered())
        menu.add_checkbutton(label="Start silently with Windows", variable=startup_value,
                             command=lambda: invoke_menu_action("startup_toggle"))
        menu.add_command(label="Member Site", command=lambda: invoke_command("open_website"))
        auth_label = 'Member account…'
        menu.add_command(label=auth_label, command=lambda: invoke_command("toggle_login"))
        menu.add_command(label="Restart App", command=lambda: invoke_command("restart_app"))
        menu.add_command(label="Quit", command=lambda: invoke_command("quit_tray"))

        root.update_idletasks()
        try:
            x, y = root.winfo_pointerxy()
        except Exception:
            x = root.winfo_screenwidth() - 80
            y = root.winfo_screenheight() - 120
        root.update_idletasks()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
            root.destroy()
    
    def transcribe_video(self):
        """Transcribe video with Whisper - SIMPLE DIRECT APPROACH"""
        try:
            # Use the same paths as main app
            venv_path = os.path.join(SCRIPT_DIR, "whisper_venv")
            venv_python = os.path.join(venv_path, "Scripts", "python.exe")
            
            # Check if venv exists
            if not os.path.exists(venv_python):
                self.show_message("Whisper Not Installed",
                    "Whisper environment not found.\n\n" +
                    "Please run install_whisper.bat first, or open the main menu to set it up.",
                    "warning")
                return
            
            # Get whisper model from config
            config = get_config()
            whisper_model = config.get('Transcribe', 'whisper_model', fallback='base')
            
            # Create output filename
            base_name = os.path.splitext(self.current_file)[0]
            output_file = base_name + '_transcription.txt'
            
            # Use whisper command line directly
            # First check if whisper command is available
            result = subprocess.run(
                [venv_python, '-m', 'whisper', '--help'],
                capture_output=True, text=True,
            )
            
            if result.returncode != 0:
                # Whisper not installed as module, try to install it
                install_msg = f"Whisper not installed in virtual environment.\n\nRun this command:\n{venv_python} -m pip install openai-whisper"
                self.show_message("Whisper Not Installed", install_msg, "error")
                return
            
            # Run whisper transcription
            launch_console_command(
                [
                    venv_python, '-m', 'whisper', self.current_file,
                    '--model', whisper_model,
                    '--output_format', 'txt',
                    '--output_dir', os.path.dirname(self.current_file),
                ],
                cwd=os.path.dirname(self.current_file),
                keep_open=True,
            )
            
            self.show_message("Transcribing", 
                f"Transcribing with Whisper ({whisper_model} model)...\n\n" +
                f"Output will be saved to:\n{output_file}\n\n" +
                "This may take several minutes for long videos.")
            
        except Exception as e:
            self.show_message("Error", f"Failed to start transcription:\n{str(e)}", "error")
            
        except Exception as e:
            self.show_message("Error", f"Failed to transcribe:\n{str(e)}", "error")
    
    def install_ggf_app(self, zip_path=None, auto_confirm=False):
        prepare(self, zip_path)

    def delete_ggf_app(self):
        """Delete only a confirmed, safely registered GGF app folder."""
        from tkinter import messagebox, simpledialog
        import stat

        apps = load_registry(INSTALLED_APPS_CONFIG)
        if not apps:
            self.show_message("No Apps", "No installed apps are registered.", "warning")
            return

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            names = sorted(apps, key=str.casefold)
            app_list = "\n".join(f"{index + 1}. {name}" for index, name in enumerate(names))
            choice = simpledialog.askstring(
                "Delete GGF app",
                f"Enter the number of the app to remove:\n\n{app_list}",
                parent=root,
            )
            if not choice or not choice.isdigit():
                return
            index = int(choice) - 1
            if index < 0 or index >= len(names):
                messagebox.showerror("Invalid selection", "That app number is not in the list.", parent=root)
                return

            app_name = names[index]
            install_dir, _launcher = apps[app_name]
            if not os.path.isdir(install_dir):
                if messagebox.askyesno(
                    "Remove stale entry?",
                    f"The registered folder no longer exists:\n\n{install_dir}\n\n"
                    "Remove only this broken entry from the GGF app list?",
                    parent=root,
                ):
                    remove_registry_entry(INSTALLED_APPS_CONFIG, app_name)
                    self.remove_shortcut(app_name)
                    self.refresh_shortcuts()
                return

            safe, reason, has_marker = validate_delete_target(install_dir, SCRIPT_DIR)
            if not safe:
                messagebox.showerror("Delete blocked for safety", reason, parent=root)
                return

            running = []
            target_norm = os.path.normcase(os.path.abspath(install_dir))
            for process in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    evidence = [process.info.get('exe') or '', *(process.info.get('cmdline') or [])]
                    if any(
                        value and os.path.commonpath([os.path.normcase(os.path.abspath(str(value))), target_norm]) == target_norm
                        for value in evidence
                    ):
                        running.append(process.info.get('name') or str(process.pid))
                except (OSError, ValueError, TypeError, psutil.Error):
                    continue
            if running:
                messagebox.showerror(
                    "App is still running",
                    "Close these processes before deleting the app:\n" + "\n".join(sorted(set(running))[:10]),
                    parent=root,
                )
                return

            if not has_marker:
                messagebox.showwarning("Folder kept", "This folder has no matching GGF install record. Manage its files in Explorer.", parent=root)
                return

            if not messagebox.askyesno(
                "Final delete confirmation",
                f"Permanently delete this entire folder?\n\n{install_dir}\n\nThis cannot be undone.",
                parent=root,
            ):
                return

            def handle_remove_readonly(func, path, _exc):
                os.chmod(path, stat.S_IWRITE)
                func(path)

            shutil.rmtree(install_dir, onerror=handle_remove_readonly)
            remove_registry_entry(INSTALLED_APPS_CONFIG, app_name)
            self.remove_shortcut(app_name)
            self.refresh_shortcuts()
            messagebox.showinfo("App deleted", f"Removed:\n{app_name}", parent=root)
        except Exception as exc:
            messagebox.showerror("Delete failed", str(exc), parent=root)
        finally:
            root.destroy()

    def quick_launch_manager(self):
        """Open standalone Quick Launch Manager"""
        import tkinter as tk
        from tkinter import messagebox, filedialog, simpledialog
        
        # Create standalone window
        window = tk.Tk()
        window.title("Quick Launch Manager")
        width, height = 500, 400
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = max(0, screen_width - width - 10)
        y = max(0, screen_height - height - 80)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.attributes('-topmost', True)
        
        # Set icon if available
        try:
            if os.path.exists(ICON_PATH):
                window.iconbitmap(ICON_PATH)
        except:
            pass
        
        shortcuts = {}
        
        def load_shortcuts_ui():
            """Load shortcuts into listbox"""
            listbox.delete(0, tk.END)
            shortcuts.clear()
            shortcuts.update(self.load_shortcuts())
            for name in sorted(shortcuts.keys()):
                listbox.insert(tk.END, name)
        
        def add_shortcut():
            """Add new shortcut"""
            filepath = filedialog.askopenfilename(
                title="Select application, batch file, or shortcut",
                filetypes=[("All files", "*.*"), ("Executables", "*.exe"), ("Batch files", "*.bat"), ("Shortcuts", "*.lnk")],
                parent=window
            )
            if not filepath:
                return
                
            filename = os.path.basename(filepath)
            name = simpledialog.askstring("Shortcut Name", 
                                         "Name for this shortcut:",
                                         initialvalue=os.path.splitext(filename)[0],
                                         parent=window)
            if not name:
                return
                
            # Add to file
            self.upsert_shortcut(sanitize_folder_name(name),filepath)
            
            load_shortcuts_ui()
            self.refresh_shortcuts()
            messagebox.showinfo("Success", f"Added shortcut: {name}", parent=window)
        
        def edit_selected():
            """Edit selected shortcut"""
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a shortcut to edit", parent=window)
                return
                
            name = listbox.get(selection[0])
            current_path = shortcuts.get(name)
            
            if messagebox.askyesno("Edit Shortcut", 
                f"Current shortcut: {name}\n\nCurrent file: {current_path}\n\nChoose a new file?",
                parent=window):
                
                new_filepath = filedialog.askopenfilename(
                    title=f"Select new file for '{name}'",
                    initialdir=os.path.dirname(current_path) if current_path and os.path.exists(os.path.dirname(current_path)) else None,
                    filetypes=[("All files", "*.*"), ("Executables", "*.exe"), ("Batch files", "*.bat"), ("Shortcuts", "*.lnk")],
                    parent=window
                )
                
                if new_filepath:
                    # Update in file
                    with open(SHORTCUTS_CONFIG, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    with open(SHORTCUTS_CONFIG, 'w', encoding='utf-8') as f:
                        for line in lines:
                            if line.strip().startswith(name + '='):
                                f.write(f"{name}={new_filepath}\n")
                            else:
                                f.write(line)
                    
                    load_shortcuts_ui()
                    self.refresh_shortcuts()
                    messagebox.showinfo("Success", f"Updated shortcut: {name}\n\nNew file: {new_filepath}", parent=window)
        
        def launch_selected():
            """Launch selected shortcut"""
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a shortcut to launch", parent=window)
                return
                
            name = listbox.get(selection[0])
            filepath = shortcuts.get(name)
            
            if not filepath or not os.path.exists(filepath):
                messagebox.showerror("Error", f"File not found:\n{filepath}\n\nShortcut may have been moved or deleted.", parent=window)
                return
                
            try:
                launch_entry(self, name, filepath)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to launch:\n{str(e)}", parent=window)
        
        def delete_selected():
            """Delete selected shortcut"""
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a shortcut to delete", parent=window)
                return
                
            name = listbox.get(selection[0])

            with open(SHORTCUTS_CONFIG, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(SHORTCUTS_CONFIG, 'w', encoding='utf-8') as f:
                for line in lines:
                    if not line.strip().startswith(name + '='):
                        f.write(line)

            load_shortcuts_ui()
            self.refresh_shortcuts()
        
        # Create UI
        title = tk.Label(window, text="Quick Launch Shortcuts", font=("Arial", 14, "bold"))
        title.pack(pady=10)
        
        # Listbox
        list_frame = tk.Frame(window)
        list_frame.pack(pady=10, padx=20, fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Arial", 10))
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)
        
        # Buttons
        btn_frame = tk.Frame(window)
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="Add Shortcut", command=add_shortcut, 
                 bg="#4CAF50", fg="white", width=15).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Edit Selected", command=edit_selected,
                 bg="#FF9800", fg="white", width=15).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Launch Selected", command=launch_selected,
                 bg="#2196F3", fg="white", width=15).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Delete Selected", command=delete_selected,
                 bg="#f44336", fg="white", width=15).pack(side="left", padx=5)
        
        tk.Button(window, text="Close", command=window.destroy,
                 bg="#666", fg="white", width=15).pack(pady=10)
        
        # Load shortcuts
        load_shortcuts_ui()
        
        # Run window
        window.mainloop()
    
    def open_config(self):
        """Open config file"""
        config_path = CONFIG_PATH
        if os.path.exists(config_path):
            os.startfile(config_path)
    
    def open_website(self):
        """Open getgoingfast.pro in browser"""
        import webbrowser
        webbrowser.open('https://getgoingfast.pro')
    
    def open_app_search(self):
        try:
            launch_catalog()
        except OSError as exc:
            self.show_message("App Catalog", str(exc), "error")

    def launch_shortcut(self, name):
        """Launch a shortcut - run in thread to avoid blocking"""
        def do_launch():
            print(f"Attempting to launch: {name}")
            print(f"Available shortcuts: {list(self.shortcuts.keys())}")
            
            filepath = self.shortcuts.get(name)
            if not filepath:
                self.show_message("Error", 
                    f"Shortcut '{name}' not found in config.\n\nAvailable: {', '.join(self.shortcuts.keys())}",
                    "error")
                return
                
            if not os.path.exists(filepath):
                self.show_message("Error",
                    f"File not found:\n{filepath}\n\nShortcut may have been moved or deleted.",
                    "error")
                return
                
            try:
                launch_entry(self, name, filepath)
            except Exception as e:
                self.show_message("Error", f"Failed to launch {name}:\n{str(e)}", "error")
        
        self.run_background_task(do_launch)
    
    def toggle_login(self):
        self.open_app_search()

    def restart_app(self):
        """Restart the tray application"""
        print("Restart button clicked")
        self.stop_command_server()
        
        # Close visualizer if running
        self.close_audio_visualizer()
        self.cleanup_helper_processes()
        
        # Stop icon first
        if self.icon:
            print("Stopping icon...")
            self.icon.stop()
        
        python = sys.executable

        import subprocess
        if getattr(sys, 'frozen', False):
            subprocess.Popen([python], cwd=SCRIPT_DIR, env=get_subprocess_env())
        else:
            script = os.path.abspath(__file__)
            print(f"Restarting: {python} {script}")
            subprocess.Popen([python, script], cwd=SCRIPT_DIR, env=get_subprocess_env())
        
        # Exit current process
        print("Exiting current instance...")
        os._exit(0)
    
    def quit_tray(self):
        """Quit the tray app HARD"""
        self.stop_command_server()
        self.close_audio_visualizer()
        self.cleanup_helper_processes()
        try:
            if self.icon:
                self.icon.stop()
        finally:
            
            os._exit(0)
            

    
    def create_menu(self):
        """Create the system tray menu"""
        menu_items = []
        
        # Quick Launch shortcuts submenu - at the top
        if self.shortcuts:
            shortcut_items = []
            # Sort names case-insensitively
            sorted_names = sorted(self.shortcuts.keys(), key=lambda x: x.lower())
            for name in sorted_names:
                # Use a function to properly capture the name
                def make_launcher(shortcut_name):
                    return lambda: self.launch_shortcut(shortcut_name)
                
                shortcut_items.append(
                    item(name, make_launcher(name))
                )
            shortcut_items.append(pystray.Menu.SEPARATOR)
            shortcut_items.append(item('Refresh List', self.refresh_shortcuts))
            
            menu_items.append(item('Quick Launch', pystray.Menu(*shortcut_items)))
            menu_items.append(pystray.Menu.SEPARATOR)
        
        # GGF TOOLS submenu
        ggf_tools_items = [
            item('Search for Apps', self.open_app_search),
            pystray.Menu.SEPARATOR,
            item('Quick Launch Manager', lambda: self.open_menu_for('quick_launch')),
            item('Install GGF Apps', lambda: self.open_menu_for('install_app')),
            item('Delete GGF Apps', lambda: self.open_menu_for('delete_app')),
        ]
        menu_items.append(item('A.I. Apps', pystray.Menu(*ggf_tools_items)))
        
        # IMAGE OPERATIONS submenu
        image_items = [
            item('Convert to JPG', lambda: self.open_menu_for('convert_jpg')),
            item('Convert to PNG', lambda: self.open_menu_for('convert_png')),
            item('Convert to WebP', lambda: self.open_menu_for('convert_webp')),
            item('Convert to BMP', lambda: self.open_menu_for('convert_bmp')),
            pystray.Menu.SEPARATOR,
            item('Resize Image', lambda: self.open_menu_for('resize_image')),
        ]
        menu_items.append(item('Image Operations', pystray.Menu(*image_items)))
        
        # AUDIO OPERATIONS submenu
        audio_items = [
            item('Convert to WAV', lambda: self.open_menu_for('convert_wav')),
            item('Convert to MP3', lambda: self.open_menu_for('convert_mp3')),
            item('Convert to AAC', lambda: self.open_menu_for('convert_aac')),
            item('Convert to M4A', lambda: self.open_menu_for('convert_m4a')),
            item('Convert to FLAC', lambda: self.open_menu_for('convert_flac')),
            item('Convert to OGG', lambda: self.open_menu_for('convert_ogg')),
        ]
        menu_items.append(item('Audio Operations', pystray.Menu(*audio_items)))
        
        # Audio Visualizer submenu (define BEFORE using it)
        audio_visualizer_menu = [
            item('Open Music Player', lambda: self.start_audio_visualizer(music=True)),
            item('Start Visualizer', lambda: self.open_menu_for('audio_visualizer')),
            item('Visualizer guide…', lambda: self.open_menu_for('visualizer_guide')),
            item(
                'Click Through',
                self.toggle_click_through,
                checked=lambda item: self.get_visualizer_state().get('click_through', False)
            )
        ]
        
        # VIDEO OPERATIONS submenu
        video_items = [
            item('Convert Video', lambda: self.open_menu_for('convert_video')),
            item('Shrink Video', lambda: self.open_menu_for('shrink_video')),
            item('Download Video', lambda: self.open_menu_for('download')),
            pystray.Menu.SEPARATOR,
            item('Save First Frame', lambda: self.open_menu_for('save_first_frame')),
            item('Save Last Frame', lambda: self.open_menu_for('save_last_frame')),
        ]
        menu_items.append(item('Video Operations', pystray.Menu(*video_items)))
        
        # AUDIO VISUALIZER as its own menu
        menu_items.append(item('Music Visualizer', pystray.Menu(*audio_visualizer_menu)))
        
        # UTILITY submenu
        utility_items = [
            item('GGF Resource Search (members)', lambda: self.open_menu_for('resources')),
            item('HuggingFace Model Browser', lambda: self.open_menu_for('huggingface_browser')),
            pystray.Menu.SEPARATOR,
            item('Open Config File', self.open_config),
        ]
        menu_items.append(item('Utility', pystray.Menu(*utility_items)))
        
        menu_items.append(pystray.Menu.SEPARATOR)
        
        # Bottom items
        menu_items.extend([
            item('Browse App Catalog', self.open_app_search, default=True),
            item('Welcome tour…', lambda: self.open_menu_for('show_tour')),
            item('Open GGF Tray folder', lambda: self.open_menu_for('open_app_folder')),
            item('Start silently with Windows', lambda: self.open_menu_for('startup_toggle'),
                 checked=lambda _: ggf_startup.is_registered()),
            item('Member Site', self.open_website),
            item('GGF license…', open_license),
            item(
                'Member account…',
                self.toggle_login
            ),
            item('Restart App', self.restart_app),
            item('Quit', self.quit_tray)
        ])

        
        return pystray.Menu(*menu_items)
    
    def run(self):
        """Run the system tray app"""
        self.start_command_server()

        # Load icon
        try:
            image = Image.open(ICON_PATH)
        except:
            # Create a simple colored square if icon not found
            image = Image.new('RGB', (64, 64), color='#4CAF50')
        
        # Create tray icon
        self.icon = pystray.Icon(
            "GGF",
            image,
            "Get Going Fast",
            menu=self.create_menu()
        )
        if "--startup" not in sys.argv:
            try:
                ggf_startup.configure("default")
            except Exception as exc:
                self.show_message("Windows startup", str(exc), "error")
        self.icon.run(setup=self.on_icon_ready)

if __name__ == "__main__":
    if "--tray-notice" in sys.argv:
        from ggf_tray_notice import main as notice_main
        sys.exit(notice_main())
    elif "--register-startup" in sys.argv:
        try:
            from ggf_catalog_window import ready_for_catalog_upgrade
            if not ready_for_catalog_upgrade(interactive="--setup-unattended" not in sys.argv):
                sys.exit(2)
            ggf_startup.configure("install")
        except Exception as exc:
            print(exc)
            sys.exit(1)
        sys.exit(0)
    elif "--ggf-ytdlp" in sys.argv:
        import yt_dlp
        yt_dlp.main(sys.argv[2:])
    elif "--self-test" in sys.argv:
        failures = []
        if not os.path.isfile(ICON_PATH):
            failures.append(f"missing icon: {ICON_PATH}")
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            probe = os.path.join(STATE_DIR, ".self-test")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("ok")
            # Retain the diagnostic marker for local release verification.
        except Exception as exc:
            failures.append(f"state directory is not writable: {exc}")
        try:
            sanitize_folder_name("GGF Test")
            AuthManager()
            from ggf_player import MusicPlayer
            import app_search
            import ggf_utilities
            if not os.path.isfile(get_ffmpeg_executable() or ""):
                failures.append("The installed FFmpeg component is missing")
            else:
                from ggf_release_check import check
                check(STATE_DIR, get_ffmpeg_executable())
            import audio_visualizer_tray
            if not app_search.membership_allows_download("farm-hand", "fh"):
                failures.append("catalog membership rules did not initialize")
        except Exception as exc:
            failures.append(f"helper initialization failed: {exc}")
        with open(os.path.join(STATE_DIR, "release-diagnostics.txt"),"w",encoding="utf-8") as report:
            report.write("; ".join(failures) if failures else "GGF Tray 1.0.0 self-test OK")
        if failures:
            print("GGF Tray self-test FAILED: " + "; ".join(failures))
            sys.exit(1)
        print("GGF Tray self-test OK")
        sys.exit(0)
    elif "--utility" in sys.argv:
        from ggf_utilities import main as utility_main
        action_index = sys.argv.index("--utility") + 1
        if action_index >= len(sys.argv):
            sys.exit(2)
        sys.exit(utility_main(sys.argv[action_index]))
    elif "--run-app-search" in sys.argv:
        import app_search
        app_search.main()
    elif "--run-visualizer" in sys.argv:
        import audio_visualizer_tray
        audio_visualizer_tray.main()
    elif "--install-zip" in sys.argv:
        try:
            zip_arg_index = sys.argv.index("--install-zip") + 1
            zip_path = sys.argv[zip_arg_index]
        except (ValueError, IndexError):
            messagebox.showerror("Installer Error", "Missing ZIP path for installer.")
            sys.exit(1)

        app = GGFTray()
        app.install_ggf_app(zip_path=zip_path)
    elif "--show-companion-menu" in sys.argv or "--show-visualizer-menu" in sys.argv:
        app = GGFTray()
        app.show_visualizer_companion_menu()
    else:
        app = GGFTray()
        app.run()
