"""
GGF System Tray - A system tray icon for Get Going Fast Menu
"""
import os
import sys
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
from ctypes import wintypes
from ggf_runtime import (
    configure_ssl_environment,
    get_ffmpeg_executable,
    launch_console_command,
    urlopen_with_ssl,
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
ICON_PATH = os.path.join(RESOURCE_DIR, "logo.ico")
SHORTCUTS_CONFIG = os.path.join(SCRIPT_DIR, "shortcuts.txt")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.txt")
TRAY_UI_STATE_PATH = os.path.join(SCRIPT_DIR, "tray_ui_state.json")

# Windows mutex for single instance check
MUTEX_NAME = "Global\\GGF-Tray-Unique-Mutex-87A3F9B2"
mutex_handle = None
APP_ID = "audio-v"  # Audio_visualizer.py 
WHISPER_ENABLED = False
UTILITY_ARGS = {"--install-zip", "--show-visualizer-menu", "--show-companion-menu", "--run-app-search", "--run-visualizer"}
TRAY_IPC_HOST = "127.0.0.1"
TRAY_IPC_PORT = 47653
TRAY_IPC_BUFFER = 65536
configure_ssl_environment()

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
        print("GGF Tray is already running!")
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showwarning("Already Running", "GGF Tray is already running!", parent=root)
        root.destroy()
        sys.exit(0)

def get_config():
    """Read config"""
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
    return config

class GGFTray:
    def __init__(self):
        self.utility_mode = any(arg in UTILITY_ARGS for arg in sys.argv[1:])
        self.remote_menu_mode = "--show-companion-menu" in sys.argv or "--show-visualizer-menu" in sys.argv
        self.shortcuts = self.load_shortcuts()
        self.icon = None
        self.current_file = None
        self.failed_attempts = 0  # Track attempts without file
        self.command_server_socket = None
        self.command_server_thread = None
        self.command_server_stop = threading.Event()
        self.helper_processes = []
        self.ui_state = self.load_ui_state()
        self.tips_thread = None
        
        # Initialize auth manager
        if AUTH_AVAILABLE:
            auth_cache_path = os.path.join(SCRIPT_DIR, "auth_cache.json")
            self.auth = AuthManager(cache_file=auth_cache_path)
            
            # Trigger initial auth check (will read from cache or browser)
            auth_status = self.auth.get_auth()
            if auth_status:
                print(f"Logged in as: {auth_status['name']} ({self.auth.format_tier_name()})")
            else:
                print("Not logged in - use 'Login with Patreon' in app search")
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

    def iter_helper_processes(self):
        if psutil is None:
            return
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                if proc.pid == current_pid:
                    continue
                cmd = proc.info.get('cmdline') or []
                cmd_text = " ".join(str(part) for part in cmd).lower()
                exe_path = (proc.info.get('exe') or '').lower()
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
            if not cmd_text:
                continue
            if "--run-visualizer" in cmd_text or "--run-app-search" in cmd_text:
                yield proc
                continue
            if getattr(sys, 'frozen', False) and exe_path == sys.executable.lower():
                if "--show-companion-menu" in cmd_text or "--show-visualizer-menu" in cmd_text:
                    yield proc

    def cleanup_helper_processes(self):
        seen_pids = set()
        for process in list(self.helper_processes):
            try:
                if process and process.poll() is None and process.pid not in seen_pids:
                    seen_pids.add(process.pid)
                    process.kill()
            except Exception:
                pass

        for proc in self.iter_helper_processes() or []:
            try:
                if proc.pid in seen_pids:
                    continue
                seen_pids.add(proc.pid)
                proc.kill()
            except Exception:
                pass

        self.helper_processes = []

    def show_startup_tips_if_needed(self):
        if not self.ui_state.get("show_tips_on_startup", True):
            return
        if self.tips_thread and self.tips_thread.is_alive():
            return

        def tips_worker():
            time.sleep(1.5)
            root = tk.Tk()
            root.title("GGF Tray Tips")
            root.attributes('-topmost', True)
            root.resizable(False, False)
            root.configure(bg="#111111")

            width = 430
            height = 250
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            pos_x = max(20, screen_width - width - 20)
            pos_y = max(20, screen_height - height - 90)
            root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

            title = tk.Label(
                root,
                text="How to use GGF Tray",
                font=("Segoe UI", 12, "bold"),
                fg="white",
                bg="#111111"
            )
            title.pack(anchor="w", padx=14, pady=(12, 6))

            body = (
                "- Right-click the tray icon for A.I. Apps, conversions, utility tools, and restart/quit.\n\n"
                "- Double-click the tray icon to open the Audio Visualizer instantly.\n\n"
                "- Use the visualizer Menu button for quick access when the tray icon is hidden.\n\n"
                "- Clipboard-based conversions work after selecting a file in Explorer and pressing Ctrl+C."
            )
            label = tk.Label(
                root,
                text=body,
                justify="left",
                wraplength=400,
                fg="white",
                bg="#111111",
                font=("Segoe UI", 10)
            )
            label.pack(anchor="w", padx=14)

            show_again = tk.BooleanVar(value=self.ui_state.get("show_tips_on_startup", True))
            checkbox = tk.Checkbutton(
                root,
                text="Show this tip next launch",
                variable=show_again,
                fg="white",
                bg="#111111",
                activebackground="#111111",
                activeforeground="white",
                selectcolor="#222222"
            )
            checkbox.pack(anchor="w", padx=14, pady=(10, 6))

            def close_tips():
                self.ui_state["show_tips_on_startup"] = bool(show_again.get())
                self.save_ui_state()
                root.destroy()

            button = tk.Button(root, text="Close", command=close_tips, width=10)
            button.pack(anchor="e", padx=14, pady=(0, 12))
            root.protocol("WM_DELETE_WINDOW", close_tips)
            root.mainloop()

        self.tips_thread = threading.Thread(target=tips_worker, daemon=False)
        self.tips_thread.start()

    def start_command_server(self):
        """Listen for commands from helper processes like the visualizer popup."""
        if self.utility_mode or self.command_server_thread:
            return

        def server_loop():
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.command_server_socket = server
            try:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
        message = {"command": command, **payload}
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
        
        
    def check_clipboard_for_file(self):
        """Check if clipboard has a file path"""
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            clipboard = root.clipboard_get()
            root.destroy()
            
            if clipboard and os.path.isfile(clipboard):
                self.current_file = clipboard
                self.failed_attempts = 0  # Reset counter
                return True
            return False
        except:
            return False
   

    def iter_audio_visualizer_processes(self):
        if psutil is None:
            return
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmd = proc.info.get('cmdline') or []
                cmd_text = " ".join(str(part) for part in cmd).lower()
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
            if f"--app-id={APP_ID}" in cmd_text or "--run-visualizer" in cmd_text:
                yield proc

    def start_audio_visualizer(self):
        if not getattr(sys, 'frozen', False):
            visualizer_path = os.path.join(SCRIPT_DIR, "audio_visualizer_tray.py")
        else:
            visualizer_path = None

        if not getattr(sys, 'frozen', False) and not os.path.exists(visualizer_path):
            self.show_message("Error", "Audio visualizer not found!", "error")
            return

        try:
            if any(True for _ in self.iter_audio_visualizer_processes()):
                return

            creationflags = 0
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creationflags |= subprocess.DETACHED_PROCESS

            if getattr(sys, 'frozen', False):
                self.track_process(subprocess.Popen(
                    f'start "" /D "{SCRIPT_DIR}" "{sys.executable}" --run-visualizer --app-id={APP_ID}',
                    shell=True,
                    env=get_subprocess_env()
                ))
            else:
                self.track_process(subprocess.Popen([sys.executable, visualizer_path, f"--app-id={APP_ID}"], cwd=SCRIPT_DIR, close_fds=True, creationflags=creationflags))
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
        state_file = os.path.join(SCRIPT_DIR, "visualizer_state.json")
        try:
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}

    def toggle_click_through(self):
        """Toggle click-through mode for visualizer"""
        state_file = os.path.join(SCRIPT_DIR, "visualizer_state.json")
        
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
    
    def get_file_or_show_menu(self, operation_name):
        """Try to get file from clipboard"""
        if self.check_clipboard_for_file():
            return True
        
        self.failed_attempts += 1
        if self.failed_attempts >= 3:
            self.show_message("No File Selected",
                f"No file detected after {self.failed_attempts} attempts.\n\n" +
                "Please select a file in Windows Explorer, press Ctrl+C, and try again.",
                "error")
            self.failed_attempts = 0
            return False
        else:
            self.show_message("No File Selected",
                f"Please select a file:\n1. Click a file in Windows Explorer\n2. Press Ctrl+C\n3. Try again\n\n" +
                f"Attempt {self.failed_attempts}/3",
                "warning")
            return False
        
        
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
    
    def refresh_shortcuts(self):
        """Reload shortcuts"""
        self.shortcuts = self.load_shortcuts()
        # Rebuild menu (icon may not be ready yet during install)
        if self.icon:
            self.icon.menu = self.create_menu()
    
    def execute_menu_action(self, action):
        """Execute a menu action immediately in the current thread."""
        if action == 'download':
            self.download_video()
        elif action == 'install_app':
            self.install_ggf_app()
        elif action == 'delete_app':
            self.delete_ggf_app()
        elif action == 'quick_launch':
            self.quick_launch_manager()
        elif action == 'huggingface_browser':
            self.huggingface_model_browser()
        elif action == 'audio_visualizer':
            self.start_audio_visualizer()
        elif action in ['convert_jpg', 'convert_png', 'convert_webp', 'convert_bmp',
                        'convert_wav', 'convert_mp3', 'convert_aac', 'convert_flac', 'convert_ogg',
                        'resize_image', 'convert_video', 'shrink_video',
                        'save_first_frame', 'save_last_frame']:
            if self.get_file_or_show_menu(action):
                if action == 'convert_jpg':
                    self.convert_to_jpg()
                elif action == 'convert_png':
                    self.convert_to_format('png')
                elif action == 'convert_webp':
                    self.convert_to_format('webp')
                elif action == 'convert_bmp':
                    self.convert_to_format('bmp')
                elif action == 'convert_wav':
                    self.convert_audio_to_format('wav')
                elif action == 'convert_mp3':
                    self.convert_audio_to_format('mp3')
                elif action == 'convert_aac':
                    self.convert_audio_to_format('aac')
                elif action == 'convert_flac':
                    self.convert_audio_to_format('flac')
                elif action == 'convert_ogg':
                    self.convert_audio_to_format('ogg')
                elif action == 'resize_image':
                    self.resize_image()
                elif action == 'convert_video':
                    self.convert_video_window()
                elif action == 'shrink_video':
                    self.shrink_video()
                elif action == 'save_first_frame':
                    self.save_first_frame()
                elif action == 'save_last_frame':
                    self.save_last_frame()

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
        menu.add_cascade(label="Audio Visualizer", menu=visualizer_menu)

        utility_menu = tk.Menu(menu, tearoff=0)
        utility_menu.add_command(label="HuggingFace Model Browser", command=lambda: invoke_menu_action('huggingface_browser'))
        utility_menu.add_separator()
        utility_menu.add_command(label="Open Config File", command=lambda: invoke_command("open_config"))
        menu.add_cascade(label="Utility", menu=utility_menu)

        menu.add_separator()
        menu.add_command(label="Member Site", command=lambda: invoke_command("open_website"))
        auth_label = 'Logout from GGF' if (self.auth and self.auth.is_authenticated()) else 'Login to GGF'
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
    
    def download_video(self):
        """Download video with yt-dlp"""
        import tkinter as tk
        from tkinter import simpledialog
        
        # Try clipboard for URL
        try:
            root = tk.Tk()
            root.withdraw()
            clipboard = root.clipboard_get()
            if clipboard and any(clipboard.startswith(p) for p in ['http://', 'https://', 'www.']):
                initial_url = clipboard
            else:
                initial_url = ""
            root.destroy()
        except:
            initial_url = ""
        
        url = simpledialog.askstring("Download Video", "Enter video URL:", initialvalue=initial_url)
        if url:
            # Run yt-dlp
            try:
                download_dir = os.path.expanduser("~\\Downloads")
                command = ['yt-dlp', '-o', os.path.join(download_dir, '%(title)s.%(ext)s')]
                ffmpeg_exe = get_ffmpeg_executable()
                if ffmpeg_exe:
                    command.extend(['--ffmpeg-location', os.path.dirname(ffmpeg_exe)])
                command.append(url)
                launch_console_command(command, cwd=download_dir, env=get_subprocess_env())
            except Exception as e:
                self.show_message("Error", f"Failed to download:\n{str(e)}", "error")

    def get_ffmpeg_command_prefix(self):
        ffmpeg_exe = get_ffmpeg_executable()
        if not ffmpeg_exe:
            raise RuntimeError(
                "FFmpeg is not available in this build. Please rebuild the EXE with bundled FFmpeg support."
            )
        return [ffmpeg_exe]

    def launch_ffmpeg(self, args, keep_open=True):
        command = self.get_ffmpeg_command_prefix() + list(args)
        return launch_console_command(command, cwd=os.path.dirname(self.current_file), keep_open=keep_open)
    
    def convert_to_jpg(self):
        """Convert image to JPG"""
        try:
            from PIL import Image
            img = Image.open(self.current_file)
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            
            output = os.path.splitext(self.current_file)[0] + '_converted.jpg'
            img.save(output, 'JPEG', quality=95)
            self.show_message("Success", f"Converted to:\n{output}")
        except Exception as e:
            self.show_message("Error", f"Failed to convert:\n{str(e)}", "error")
    
    def convert_to_format(self, format_ext):
        """Convert image to specified format (png, webp, bmp)"""
        try:
            from PIL import Image
            img = Image.open(self.current_file)
            
            output = os.path.splitext(self.current_file)[0] + f'_converted.{format_ext}'
            
            if format_ext.lower() == 'webp':
                img.save(output, 'WEBP', quality=95)
            elif format_ext.lower() == 'png':
                img.save(output, 'PNG')
            elif format_ext.lower() == 'bmp':
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                img.save(output, 'BMP')
            
            self.show_message("Success", f"Converted to {format_ext.upper()}:\n{output}")
        except Exception as e:
            self.show_message("Error", f"Failed to convert:\n{str(e)}", "error")
    
    def convert_audio_to_format(self, format_ext):
        """Convert audio to specified format using ffmpeg"""
        try:
            output = os.path.splitext(self.current_file)[0] + f'_converted.{format_ext}'
            
            # Get audio settings from config
            config = get_config()
            audio_bitrate = config.get('Video', 'audio_bitrate', fallback='192k')
            
            ffmpeg_args = ["-i", self.current_file]
            if format_ext == 'mp3':
                ffmpeg_args += ["-acodec", "libmp3lame", "-b:a", audio_bitrate]
            elif format_ext == 'wav':
                ffmpeg_args += ["-acodec", "pcm_s16le"]
            elif format_ext == 'ogg':
                ffmpeg_args += ["-acodec", "libvorbis", "-b:a", audio_bitrate]
            elif format_ext == 'aac':
                ffmpeg_args += ["-acodec", "aac", "-b:a", audio_bitrate]
            elif format_ext == 'flac':
                ffmpeg_args += ["-acodec", "flac"]
            else:
                ffmpeg_args += ["-acodec", "copy"]

            ffmpeg_args += ["-y", output]
            self.launch_ffmpeg(ffmpeg_args)
            self.show_message("Converting", f"Converting to {format_ext.upper()}...\n\nOutput: {output}")
        except Exception as e:
            self.show_message("Error", f"Failed to convert audio:\n{str(e)}", "error")
    
    def resize_image(self):
        """Resize image"""
        import tkinter as tk
        from tkinter import simpledialog
        
        try:
            from PIL import Image
            
            # Create root properly
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            
            percent = simpledialog.askinteger("Resize Image", "Resize to what percent?", 
                                             initialvalue=50, parent=root)
            root.destroy()
            
            if not percent:
                return
            
            img = Image.open(self.current_file)
            new_width = int(img.width * (percent / 100))
            new_height = int(img.height * (percent / 100))
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            output = os.path.splitext(self.current_file)[0] + '_resized.jpg'
            resized.save(output, 'JPEG', quality=95)
            self.show_message("Success", f"Resized to {new_width}x{new_height}:\n{output}")
        except Exception as e:
            self.show_message("Error", f"Failed to resize:\n{str(e)}", "error")
    
    def convert_video_window(self):
        """Open video conversion window"""
        import tkinter as tk
        from tkinter import messagebox
        
        # Create standalone window
        window = tk.Tk()
        window.title("Convert Video")
        window.geometry("500x550")
        window.attributes('-topmost', True)
        
        # Set icon if available
        try:
            if os.path.exists(ICON_PATH):
                window.iconbitmap(ICON_PATH)
        except:
            pass
        
        def convert_video(output_ext):
            """Convert video to specified format"""
            output = os.path.splitext(self.current_file)[0] + output_ext
            
            # Get settings from config
            config = get_config()
            preset = config.get('Video', 'video_preset', fallback='medium')
            crf = config.get('Video', 'video_crf', fallback='23')
            video_codec = config.get('Video', 'video_codec', fallback='libx264')
            audio_codec = config.get('Video', 'audio_codec', fallback='aac')
            audio_bitrate = config.get('Video', 'audio_bitrate', fallback='192k')
            
            ffmpeg_args = ["-i", self.current_file]
            if output_ext == ".gif":
                fps = config.get('Video', 'gif_fps', fallback='10')
                scale = config.get('Video', 'gif_scale', fallback='480')
                ffmpeg_args += ["-vf", f"fps={fps},scale={scale}:-1:flags=lanczos"]
            elif output_ext == ".webm":
                ffmpeg_args += ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-c:a", "libopus", "-b:a", audio_bitrate]
            else:
                ffmpeg_args += ["-c:v", video_codec, "-preset", preset, "-crf", crf, "-c:a", audio_codec, "-b:a", audio_bitrate]

            ffmpeg_args += ["-y", output]
            self.launch_ffmpeg(ffmpeg_args)
            self.show_message("Converting", f"Converting to {output_ext.upper()}...\n\nOutput: {output}")
            window.destroy()
        
        def extract_audio(output_ext):
            """Extract audio from video"""
            output = os.path.splitext(self.current_file)[0] + output_ext
            
            # Get audio settings from config
            config = get_config()
            audio_bitrate = config.get('Video', 'audio_bitrate', fallback='192k')
            
            ffmpeg_args = ["-i", self.current_file, "-vn"]
            if output_ext == ".mp3":
                ffmpeg_args += ["-acodec", "libmp3lame", "-b:a", audio_bitrate]
            elif output_ext == ".wav":
                ffmpeg_args += ["-acodec", "pcm_s16le"]
            elif output_ext == ".ogg":
                ffmpeg_args += ["-acodec", "libvorbis", "-b:a", audio_bitrate]
            elif output_ext == ".aac":
                ffmpeg_args += ["-acodec", "aac", "-b:a", audio_bitrate]
            elif output_ext == ".flac":
                ffmpeg_args += ["-acodec", "flac"]
            elif output_ext == ".m4a":
                ffmpeg_args += ["-acodec", "aac", "-b:a", audio_bitrate]
            else:
                ffmpeg_args += ["-acodec", "copy"]

            ffmpeg_args += ["-y", output]
            self.launch_ffmpeg(ffmpeg_args)
            window.destroy()
        
        # Create UI
        title = tk.Label(window, text="Convert Video", font=("Arial", 14, "bold"))
        title.pack(pady=10)
        
        # File info
        filename = os.path.basename(self.current_file)
        file_label = tk.Label(window, text=f"File: {filename}", font=("Arial", 9), fg="#666")
        file_label.pack(pady=5)
        
        # Video Formats Section
        video_frame = tk.LabelFrame(window, text="Convert to Video Format", font=("Arial", 11, "bold"), padx=10, pady=10)
        video_frame.pack(pady=10, padx=20, fill="both")
        
        video_formats = [
            ("MP4", ".mp4"),
            ("AVI", ".avi"),
            ("WebM", ".webm"),
            ("MKV", ".mkv"),
            ("MOV", ".mov"),
            ("GIF", ".gif")
        ]
        
        for i, (name, ext) in enumerate(video_formats):
            row = i // 3
            col = i % 3
            btn = tk.Button(video_frame, text=name, 
                          command=lambda e=ext: convert_video(e),
                          bg="#2196F3", fg="white", width=12, height=2)
            btn.grid(row=row, column=col, padx=5, pady=5)
        
        # Audio Extraction Section
        audio_frame = tk.LabelFrame(window, text="Extract Audio", font=("Arial", 11, "bold"), padx=10, pady=10)
        audio_frame.pack(pady=10, padx=20, fill="both")
        
        audio_formats = [
            ("MP3", ".mp3"),
            ("WAV", ".wav"),
            ("OGG", ".ogg"),
            ("AAC", ".aac"),
            ("FLAC", ".flac"),
            ("M4A", ".m4a")
        ]
        
        for i, (name, ext) in enumerate(audio_formats):
            row = i // 3
            col = i % 3
            btn = tk.Button(audio_frame, text=name,
                          command=lambda e=ext: extract_audio(e),
                          bg="#4CAF50", fg="white", width=12, height=2)
            btn.grid(row=row, column=col, padx=5, pady=5)
        
        # Close button
        tk.Button(window, text="Close", command=window.destroy,
                 bg="#666", fg="white", width=15).pack(pady=15)
        
        # Run window
        window.mainloop()
    
    def shrink_video(self):
        """Shrink video"""
        try:
            output = os.path.splitext(self.current_file)[0] + '_shrunk.mp4'
            
            self.launch_ffmpeg([
                "-i", self.current_file,
                "-vf", "scale=-2:1080",
                "-c:v", "libx264",
                "-b:v", "2000k",
                "-c:a", "aac",
                "-b:a", "128k",
                "-y",
                output,
            ])
        except Exception as e:
            self.show_message("Error", f"Failed to shrink:\n{str(e)}", "error")
    
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
            check_cmd = f'"{venv_python}" -m whisper --help'
            result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                # Whisper not installed as module, try to install it
                install_msg = f"Whisper not installed in virtual environment.\n\nRun this command:\n{venv_python} -m pip install openai-whisper"
                self.show_message("Whisper Not Installed", install_msg, "error")
                return
            
            # Run whisper transcription
            cmd = f'start cmd /k "{venv_python}" -m whisper "{self.current_file}" --model {whisper_model} --output_format txt --output_dir "{os.path.dirname(self.current_file)}" && echo Transcription saved to: {output_file} && pause'
            
            print(f"Running whisper command: {cmd}")
            subprocess.Popen(cmd, shell=True)
            
            self.show_message("Transcribing", 
                f"Transcribing with Whisper ({whisper_model} model)...\n\n" +
                f"Output will be saved to:\n{output_file}\n\n" +
                "This may take several minutes for long videos.")
            
        except Exception as e:
            self.show_message("Error", f"Failed to start transcription:\n{str(e)}", "error")
            
        except Exception as e:
            self.show_message("Error", f"Failed to transcribe:\n{str(e)}", "error")
    
    def save_first_frame(self):
        """Save first frame of video as PNG"""
        try:
            # Get base name without extension
            base_name = os.path.splitext(self.current_file)[0]
            output = base_name + '_first_frame.png'
            
            self.launch_ffmpeg([
                "-i", self.current_file,
                "-vf", "select=eq(n\\,0)",
                "-vsync", "vfr",
                "-y",
                output,
            ])
           
            
        except Exception as e:
            self.show_message("Error", f"Failed to save first frame:\n{str(e)}", "error")
    
    def save_last_frame(self):
        """Save last frame of video as PNG"""
        try:
            # Get base name without extension
            base_name = os.path.splitext(self.current_file)[0]
            output = base_name + '_last_frame.png'
            
            self.launch_ffmpeg([
                "-sseof", "-1",
                "-i", self.current_file,
                "-vf", "select=eq(n\\,0)",
                "-vsync", "vfr",
                "-y",
                output,
            ])
            
        except Exception as e:
            self.show_message("Error", f"Failed to save last frame:\n{str(e)}", "error")
    
    def install_ggf_app(self, zip_path=None, auto_confirm=False):
        """Install a GGF app from zip file"""
        import tkinter as tk
        from tkinter import filedialog, simpledialog, messagebox
        import zipfile
        import shutil
        import ctypes
        
        # Create root for dialogs
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        
        # Select zip file (or use provided path)
        if zip_path and os.path.exists(zip_path):
            zip_file = zip_path
        else:
            zip_file = filedialog.askopenfilename(
                title="Select GGF App ZIP file",
                filetypes=[("ZIP files", "*.zip")],
                parent=root
            )
        
        if not zip_file:
            root.destroy()
            return
        
        zip_name = os.path.splitext(os.path.basename(zip_file))[0]
        
        # Ask for installation directory
        install_base = filedialog.askdirectory(
            title="Choose installation location",
            initialdir="C:\\",
            parent=root
        )
        
        if not install_base:
            root.destroy()
            return
        
        # Check if this is a ComfyUI installation
        is_comfyui_install = False
        comfyui_folders = ['comfyui', 'comfy', 'stable-diffusion', 'automatic1111']
        
        # Check if install_base contains ComfyUI-related folder names
        install_base_lower = install_base.lower()
        for folder in comfyui_folders:
            if folder in install_base_lower:
                # Check if we're in a ComfyUI folder structure
                if messagebox.askyesno(
                    "ComfyUI Detected",
                    f"The selected folder appears to be part of a ComfyUI installation.\n\n"
                    f"Selected: {install_base}\n\n"
                    f"Is this a model or extension for ComfyUI?\n\n"
                    f"If yes, files will be extracted directly without creating a subfolder.",
                    parent=root
                ):
                    is_comfyui_install = True
                    break
        
        if is_comfyui_install:
            # For ComfyUI, extract directly without subfolder
            install_dir = install_base
            folder_name = os.path.basename(install_base)
            
        else:
            # Regular installation - ask for folder name
            folder_name = simpledialog.askstring(
                "App Folder Name",
                f"Installation folder name:\n(Will install to: {install_base}\\...)",
                initialvalue=zip_name,
                parent=root
            )
            
            if not folder_name:
                root.destroy()
                return
            
            install_dir = os.path.join(install_base, folder_name)
        
        root.destroy()
        
        def extract_archive(src, dest):
            """Extract zip or rar to dest. Uses zipfile for .zip, bsdtar/7-zip for .rar"""
            ext = os.path.splitext(src)[1].lower()
            if ext == '.zip':
                with zipfile.ZipFile(src, 'r') as z:
                    z.extractall(dest)
            elif ext == '.rar':
                # Try Windows built-in bsdtar first (Win10+)
                result = subprocess.run(['tar', '-xf', src, '-C', dest],
                                        capture_output=True, text=True)
                if result.returncode != 0:
                    # Fall back to 7-zip
                    seven_zip = None
                    for path in [r'C:\Program Files\7-Zip\7z.exe',
                                 r'C:\Program Files (x86)\7-Zip\7z.exe']:
                        if os.path.exists(path):
                            seven_zip = path
                            break
                    if seven_zip:
                        subprocess.run([seven_zip, 'x', src, f'-o{dest}', '-y'],
                                       capture_output=True)
                    else:
                        raise RuntimeError(
                            f"Cannot extract RAR: bsdtar failed ({result.stderr.strip()}) "
                            "and 7-Zip not found. Install 7-Zip or re-upload as ZIP.")
            else:
                raise RuntimeError(f"Unsupported archive type: {ext}")

        try:
            # Extract archive (zip or rar)
            os.makedirs(install_dir, exist_ok=True)
            extract_archive(zip_file, install_dir)
            
            # Look for installer and launcher files - SIMPLIFIED LOGIC
            install_bat = None
            run_bat = None
            
            # Collect installer files
            installer_files = []
            for root_dir, dirs, files in os.walk(install_dir):
                for file in files:
                    if file.endswith('.bat'):
                        file_lower = file.lower()
                        # Look for installer files (but not uninstallers)
                        if ('install' in file_lower or 'setup' in file_lower) and 'uninstall' not in file_lower:
                            installer_files.append(os.path.join(root_dir, file))
            
            # Collect launcher files
            launcher_files = []
            for root_dir, dirs, files in os.walk(install_dir):
                for file in files:
                    if file.endswith('.bat') or file.endswith('.exe'):
                        file_lower = file.lower()
                        # Look for launcher files
                        if ('run' in file_lower or 'start' in file_lower or 'launch' in file_lower) and 'uninstall' not in file_lower:
                            launcher_files.append(os.path.join(root_dir, file))
            
            # Smart installer selection
            if installer_files:
                # Try to find the best installer using priority rules
                best_installer = None
                
                # Priority 1: Contains "installer" in name (highest priority)
                for installer in installer_files:
                    if 'installer' in os.path.basename(installer).lower():
                        best_installer = installer
                        break
                
                # Priority 2: Contains zip name in installer name
                if not best_installer:
                    for installer in installer_files:
                        if zip_name.lower() in os.path.basename(installer).lower():
                            best_installer = installer
                            break
                
                # Priority 3: First installer that doesn't contain "click" or "manual"
                if not best_installer:
                    for installer in installer_files:
                        installer_name = os.path.basename(installer).lower()
                        if 'click' not in installer_name and 'manual' not in installer_name:
                            best_installer = installer
                            break
                
                # Priority 4: Just use the first one
                if not best_installer:
                    best_installer = installer_files[0]
                
                # Ask user if this is the right installer
                installer_name = os.path.basename(best_installer)
                if auto_confirm or messagebox.askyesno(
                    "Installer Found",
                    f"Found installer: {installer_name}\n\n"
                    f"Is this the correct installer to run?",
                    parent=tk.Tk()
                ):
                    install_bat = best_installer
                else:
                    # Let user browse for the correct installer
                    browse_root = tk.Tk()
                    browse_root.withdraw()
                    browse_root.attributes('-topmost', True)
                    custom_installer = filedialog.askopenfilename(
                        title="Select the installer file",
                        initialdir=install_dir,
                        filetypes=[("Batch files", "*.bat"), ("Executables", "*.exe"), ("All files", "*.*")],
                        parent=browse_root
                    )
                    browse_root.destroy()
                    if custom_installer:
                        install_bat = custom_installer
            
            # Smart launcher selection (similar logic)
            if launcher_files and not is_comfyui_install:
                best_launcher = None
                
                # Priority 1: Contains "run" in name (highest priority)
                for launcher in launcher_files:
                    if 'run' in os.path.basename(launcher).lower():
                        best_launcher = launcher
                        break
                
                # Priority 2: Contains zip name in launcher name
                if not best_launcher:
                    for launcher in launcher_files:
                        if zip_name.lower() in os.path.basename(launcher).lower():
                            best_launcher = launcher
                            break
                
                # Priority 3: First launcher that doesn't contain "click" or "manual"
                if not best_launcher:
                    for launcher in launcher_files:
                        launcher_name = os.path.basename(launcher).lower()
                        if 'click' not in launcher_name and 'manual' not in launcher_name:
                            best_launcher = launcher
                            break
                
                # Priority 4: Just use the first one
                if not best_launcher:
                    best_launcher = launcher_files[0]
                
                # Ask user if this is the right launcher to add to shortcuts
                launcher_name = os.path.basename(best_launcher)
                if auto_confirm or messagebox.askyesno(
                    "Launcher Found",
                    f"Found launcher: {launcher_name}\n\n"
                    f"Add this to Quick Launch shortcuts?",
                    parent=tk.Tk()
                ):
                    run_bat = best_launcher
                else:
                    # Let user browse for a different launcher
                    browse_root = tk.Tk()
                    browse_root.withdraw()
                    browse_root.attributes('-topmost', True)
                    custom_launcher = filedialog.askopenfilename(
                        title="Select launcher file for shortcuts",
                        initialdir=install_dir,
                        filetypes=[("Batch files", "*.bat"), ("Executables", "*.exe"), ("All files", "*.*")],
                        parent=browse_root
                    )
                    browse_root.destroy()
                    if custom_launcher:
                        run_bat = custom_launcher
            
            # Run install.bat with admin privileges if found
            if install_bat:
                try:
                    # HARD SAFETY: never allow install scripts in ComfyUI folders
                    if is_comfyui_install and 'uninstall' in os.path.basename(install_bat).lower():
                        self.show_message("Safety Blocked",
                            "Uninstall scripts are blocked for ComfyUI installations for safety.",
                            "warning")
                        install_bat = None
                    
                    if install_bat:
                        # Run bat file with admin elevation
                        result = ctypes.windll.shell32.ShellExecuteW(
                            None,
                            "runas",  # Run as admin
                            install_bat,
                            None,
                            os.path.dirname(install_bat),
                            1  # SW_SHOWNORMAL
                        )
                        
                        if result is not None and result > 32:  # Success
                           pass
                        else:
                            self.show_message("Error", 
                                f"Failed to elevate installer.\n\n" +
                                f"You may need to run install.bat manually as administrator.",
                                "error")
                            
                except Exception as e:
                    self.show_message("Error", 
                        f"Could not run installer:\n{str(e)}",
                        "error")
            
            # HARD SAFETY: never allow uninstall scripts
            if run_bat and 'uninstall' in os.path.basename(run_bat).lower():
                run_bat = None          
                
            # Add run.bat to shortcuts if found (but not for ComfyUI installs)
            if run_bat and not is_comfyui_install:
                shortcuts_file = os.path.join(SCRIPT_DIR, 'shortcuts.txt')
                with open(shortcuts_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{folder_name}={run_bat}")
                self.refresh_shortcuts()
            
            # Register app in installed_apps.txt (but not for ComfyUI installs)
            if not is_comfyui_install:
                apps_config = os.path.join(SCRIPT_DIR, 'installed_apps.txt')
                with open(apps_config, 'a', encoding='utf-8') as f:
                    f.write(f"\n{folder_name}={install_dir}")
            
        except Exception as e:
            self.show_message("Error", f"Failed to install:\n{str(e)}", "error")
        
    def delete_ggf_app(self):
        """Delete an installed GGF app"""
        import tkinter as tk
        from tkinter import simpledialog
        import shutil
        import stat
        
        # Load installed apps
        apps_config = os.path.join(SCRIPT_DIR, 'installed_apps.txt')
        apps = {}
        
        if os.path.exists(apps_config):
            with open(apps_config, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        name, data = line.split('=', 1)
                        apps[name] = data
        
        if not apps:
            self.show_message("No Apps", "No installed apps found.", "warning")
            return
        
        # Create root for dialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        
        # Simple selection - show list
        app_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(apps.keys()))
        choice = simpledialog.askstring(
            "Delete App",
            f"Enter number to delete:\n\n{app_list}",
            parent=root
        )
        
        root.destroy()
        
        if not choice or not choice.isdigit():
            return
        
        idx = int(choice) - 1
        if idx < 0 or idx >= len(apps):
            return
        
        app_name = list(apps.keys())[idx]
        app_data = apps[app_name].split('|')
        install_dir = app_data[0] if app_data else None
        
        if not install_dir or not os.path.exists(install_dir):
            self.show_message("Error", "App directory not found", "error")
            return
        
        try:
            # Delete directory
            def handle_remove_readonly(func, path, exc):
                os.chmod(path, stat.S_IWRITE)
                func(path)
            
            shutil.rmtree(install_dir, onerror=handle_remove_readonly)
            
            # Remove from config
            with open(apps_config, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(apps_config, 'w', encoding='utf-8') as f:
                for line in lines:
                    if not line.strip().startswith(app_name + '='):
                        f.write(line)
            
            self.show_message("Success", f"Deleted: {app_name}")
            
        except Exception as e:
            self.show_message("Error", f"Failed to delete:\n{str(e)}", "error")
    
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
            with open(SHORTCUTS_CONFIG, 'a', encoding='utf-8') as f:
                f.write(f"\n{name}={filepath}")
            
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
                if filepath.lower().endswith('.bat'):
                    file_dir = os.path.dirname(filepath)
                    file_name = os.path.basename(filepath)
                    subprocess.Popen(f'start "GGF-{name}" cmd /k "cd /d "{file_dir}" && {file_name}"', shell=True)
                else:
                    os.startfile(filepath)
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
        config_path = os.path.join(SCRIPT_DIR, "config.txt")
        if os.path.exists(config_path):
            os.startfile(config_path)
    
    def open_website(self):
        """Open getgoingfast.pro in browser"""
        import webbrowser
        webbrowser.open('https://getgoingfast.pro')
    
    
    def open_website(self):
        """Open getgoingfast.pro in browser"""
        import webbrowser
        webbrowser.open('https://getgoingfast.pro')
    
    def open_app_search(self):
        """Open app search dialog as standalone process"""
        try:
            if getattr(sys, 'frozen', False):
                self._app_search_proc = self.track_process(subprocess.Popen(
                    [sys.executable, "--run-app-search"],
                    cwd=SCRIPT_DIR,
                    env=get_subprocess_env()
                ))
            else:
                app_search_script = os.path.join(SCRIPT_DIR, 'app_search.py')
                self._app_search_proc = self.track_process(subprocess.Popen([sys.executable, app_search_script]))
        except Exception as e:
            self.show_message("Error", f"Failed to open app search: {str(e)}", "error")
    
    
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
                if filepath.lower().endswith('.bat'):
                    file_dir = os.path.dirname(filepath)
                    file_name = os.path.basename(filepath)
                    subprocess.Popen(
                        f'start "GGF-{name}" cmd /k "cd /d "{file_dir}" && {file_name}"',
                        shell=True
                    )
                else:
                    os.startfile(filepath)
            except Exception as e:
                self.show_message("Error", f"Failed to launch {name}:\n{str(e)}", "error")
        
        self.run_background_task(do_launch)
    
    def huggingface_model_browser(self):
        """Browse and download HuggingFace models"""
        import tkinter as tk
        from tkinter import ttk, messagebox, filedialog
        import json
        import urllib.request
        import urllib.parse
        
        # Get ComfyUI path from config
        config = get_config()
        if not config.has_section('Paths'):
            config.add_section('Paths')
        comfyui_path = config.get('Paths', 'comfyui_path', fallback='')
        
        # Create window
        window = tk.Tk()
        window.title("HuggingFace Model Browser")
        window.geometry("600x750")
        window.attributes('-topmost', True)
        
        # State variables
        searched_models = []
        searched_files = []
        searched_sizes = []
        downloading = False
        
        # ComfyUI Path Section
        path_frame = tk.LabelFrame(window, text="ComfyUI Location", padx=10, pady=10)
        path_frame.pack(pady=10, padx=10, fill="x")
        
        path_var = tk.StringVar(value=comfyui_path)
        path_entry = tk.Entry(path_frame, textvariable=path_var, font=("Arial", 9))
        path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        def browse_comfyui():
            folder = filedialog.askdirectory(title="Select ComfyUI Folder", initialdir=path_var.get())
            if folder:
                path_var.set(folder)
                update_model_folders()
                # Save to config
                config.set('Paths', 'comfyui_path', folder)
                try:
                    with open(CONFIG_PATH, 'w') as f:
                        config.write(f)
                except:
                    pass
        
        tk.Button(path_frame, text="Browse", command=browse_comfyui, 
                 bg="#2196F3", fg="white", width=10).pack(side="right")
        
        # Search Section
        search_frame = tk.LabelFrame(window, text="Search HuggingFace", padx=10, pady=10)
        search_frame.pack(pady=10, padx=10, fill="x")
        
        # File Type Filter - at the top of search
        filter_frame = tk.Frame(search_frame)
        filter_frame.pack(fill="x", pady=(0, 10))
        tk.Label(filter_frame, text="File Type:", font=("Arial", 9, "bold")).pack(side="left", padx=(0, 10))
        
        filter_var = tk.StringVar(value=".safetensors")
        tk.Radiobutton(filter_frame, text=".safetensors", variable=filter_var, value=".safetensors",
                      font=("Arial", 9)).pack(side="left", padx=5)
        tk.Radiobutton(filter_frame, text=".gguf", variable=filter_var, value=".gguf", 
                      font=("Arial", 9)).pack(side="left", padx=5)
        tk.Radiobutton(filter_frame, text="All", variable=filter_var, value=".all",
                      font=("Arial", 9)).pack(side="left", padx=5)
        
        tk.Label(search_frame, text="Enter search term: (try 'kijai' or 'comfyui')", font=("Arial", 9)).pack(anchor="w")
        search_entry = tk.Entry(search_frame, font=("Arial", 10))
        search_entry.pack(fill="x", pady=5)
        
        # Track pagination
        current_offset = 0
        all_models = []

        def hf_json(url, timeout=15):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "GGF-Tray/1.0",
                    "Accept": "application/json"
                }
            )
            with urlopen_with_ssl(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        
        def search_huggingface(load_more=False):
            """Search HuggingFace for models"""
            nonlocal searched_models, searched_files, searched_sizes, current_offset, all_models
            
            query = search_entry.get().strip()
            if not query:
                messagebox.showwarning("No Query", "Please enter a search term", parent=window)
                return
            
            try:
                if not load_more:
                    # New search - reset
                    current_offset = 20
                    all_models = []
                    searched_models = []
                else:
                    # Increase offset for next batch
                    current_offset += 20
                
                status_label.config(text="Searching...")
                window.update()
                
                # Get filter selection
                file_filter = filter_var.get()
                
                # Search with appropriate prefix based on filter
                if file_filter == ".gguf":
                    search_query = f"GGUF {query}"
                else:
                    search_query = query
                
                # Use current_offset as limit to get all results up to that point
                urlcode = urllib.parse.urlencode({"search": search_query, "limit": current_offset})
                url = f"https://huggingface.co/api/models?{urlcode}"
                results = hf_json(url, timeout=15)
                
                initial_models = [m["id"] for m in results] if results else []
                
                # If few results, search without prefix
                if len(initial_models) <= 3:
                    urlcode2 = urllib.parse.urlencode({"search": query, "limit": 15})
                    url2 = f"https://huggingface.co/api/models?{urlcode2}"
                    results2 = hf_json(url2, timeout=15)
                    
                    if results2:
                        for m in results2:
                            if m["id"] not in initial_models:
                                initial_models.append(m["id"])
                
                if not initial_models:
                    status_label.config(text="No results found")
                    messagebox.showinfo("No Results", "No models found", parent=window)
                    return
                
                # Filter models by file type
                if file_filter != ".all":
                    status_label.config(text="Filtering by file type...")
                    window.update()
                    
                    filtered_models = []
                    for i, model_id in enumerate(initial_models):
                        try:
                            # Check if model has files of the selected type
                            encoded_model_id = urllib.parse.quote(model_id, safe='/')
                            url = f"https://huggingface.co/api/models/{encoded_model_id}/tree/main?recursive=true"
                            file_tree = hf_json(url, timeout=8)
                            
                            # Check if any file matches the filter
                            has_file_type = False
                            for item in file_tree:
                                if item["type"] == "file" and file_filter in item["path"].lower():
                                    has_file_type = True
                                    break
                            
                            if has_file_type:
                                filtered_models.append(model_id)
                            
                            # Update progress
                            status_label.config(text=f"Filtering... {i+1}/{len(initial_models)}")
                            window.update()
                        except:
                            # If we can't check, include it anyway
                            filtered_models.append(model_id)
                    
                    initial_models = filtered_models
                    
                    if not initial_models:
                        status_label.config(text=f"No models with {file_filter} files found")
                        messagebox.showinfo("No Results", f"No models found with {file_filter} files", parent=window)
                        return
                
                # Bias towards kijai and comfyui repos - sort them to the top
                def sort_key(model_id):
                    model_lower = model_id.lower()
                    if "kijai" in model_lower:
                        return 0  # Highest priority
                    elif "comfyui" in model_lower or "comfy" in model_lower:
                        return 1  # Second priority
                    else:
                        return 2  # Everything else
                
                initial_models.sort(key=sort_key)
                
                # Update with all results
                all_models = initial_models
                searched_models = all_models
                
                # Update model dropdown
                model_combo['values'] = searched_models
                model_combo.current(0)
                fetch_model_files()
                status_label.config(text=f"Found {len(searched_models)} models (showing up to {current_offset})")
                
            except Exception as e:
                status_label.config(text="Search failed")
                messagebox.showerror("Search Error", f"Failed to search:\n{str(e)}", parent=window)
        
        tk.Button(search_frame, text="Search", command=search_huggingface,
                 bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), width=20).pack(pady=5)
        
        # Model Selection
        model_frame = tk.LabelFrame(window, text="Model Selection", padx=10, pady=10)
        model_frame.pack(pady=10, padx=10, fill="both", expand=True)
        
        tk.Label(model_frame, text="Selected Model:", font=("Arial", 9, "bold")).pack(anchor="w")
        model_var = tk.StringVar()
        model_combo = ttk.Combobox(model_frame, textvariable=model_var, state="readonly", font=("Arial", 9))
        model_combo.pack(fill="x", pady=5)
        
        # Load More button
        def load_more_results():
            search_huggingface(load_more=True)
        
        tk.Button(model_frame, text="Load Next 20 Results", command=load_more_results,
                 bg="#2196F3", fg="white", font=("Arial", 9), width=25).pack(pady=(0, 10))
        
        # File filter textbox
        tk.Label(model_frame, text="Filter Files:", font=("Arial", 9, "bold")).pack(anchor="w", pady=(10, 0))
        file_filter_var = tk.StringVar()
        file_filter_entry = tk.Entry(model_frame, textvariable=file_filter_var, font=("Arial", 9))
        file_filter_entry.pack(fill="x", pady=5)
        
        tk.Label(model_frame, text="Selected File:", font=("Arial", 9, "bold")).pack(anchor="w", pady=(5, 0))
        file_var = tk.StringVar()
        file_combo = ttk.Combobox(model_frame, textvariable=file_var, state="readonly", font=("Arial", 9))
        file_combo.pack(fill="x", pady=5)
        
        size_label = tk.Label(model_frame, text="Size: ", font=("Arial", 9), fg="#FF9800")
        size_label.pack(anchor="w", pady=5)
        
        def fetch_model_files():
            """Fetch files from selected model"""
            nonlocal searched_files, searched_sizes
            
            model_id = model_var.get()
            if not model_id:
                return
            
            try:
                status_label.config(text="Loading files...")
                window.update()
                
                encoded_model_id = urllib.parse.quote(model_id, safe='/')
                url = f"https://huggingface.co/api/models/{encoded_model_id}/tree/main?recursive=true"
                file_tree = hf_json(url, timeout=15)
                
                searched_files = []
                searched_sizes = []
                
                # Get all common model file types
                for item in file_tree:
                    if item["type"] == "file":
                        path_lower = item["path"].lower()
                        
                        # Accept common model file types
                        if any(ext in path_lower for ext in [".gguf", ".safetensors", ".bin", ".pt", ".pth"]):
                            # Skip split files except first part
                            if "-of-0" in item["path"] and "00001" not in item["path"]:
                                continue
                            searched_files.append(item["path"])
                            searched_sizes.append(item.get("size", 0))
                
                if not searched_files:
                    status_label.config(text="No model files found")
                    file_combo['values'] = []
                    return
                
                # Clear filter and apply
                file_filter_var.set("")
                filter_files()
                
                status_label.config(text=f"Found {len(searched_files)} files")
                
            except Exception as e:
                status_label.config(text="Failed to load files")
                messagebox.showerror("Error", f"Failed to load files:\n{str(e)}", parent=window)
        
        def filter_files(*args):
            """Filter file list based on filter text"""
            if not searched_files:
                return
            
            filter_text = file_filter_var.get().lower()
            
            if filter_text:
                # Filter files that contain the filter text
                filtered = [f for f in searched_files if filter_text in f.lower()]
            else:
                # No filter, show all
                filtered = searched_files
            
            # Update dropdown
            file_combo['values'] = filtered
            
            if filtered:
                # Auto-select best file from filtered results
                best_file = auto_select_quant(filtered)
                file_var.set(best_file)
                update_file_size()
            else:
                file_var.set("")
                size_label.config(text="Size: (no matching files)")
        
        
        def auto_select_quant(filenames):
            """Auto-select best quantization"""
            quants = ["q4_k_m", "q4k", "q4_k", "q4", "q3", "q5", "q6", "q8"]
            for quant in quants:
                for filename in filenames:
                    if quant in filename.lower():
                        return filename
            return filenames[0] if filenames else ""
        
        def update_file_size(*args):
            """Update file size display"""
            try:
                selected = file_var.get()
                if selected in searched_files:
                    idx = searched_files.index(selected)
                    size_gb = round(searched_sizes[idx] / 1024 / 1024 / 1024, 2)
                    size_label.config(text=f"Size: {size_gb} GB")
                else:
                    size_label.config(text="Size: ")
            except:
                size_label.config(text="Size: ")
        
        # Destination Section
        dest_frame = tk.LabelFrame(window, text="Download Destination", padx=10, pady=10)
        dest_frame.pack(pady=10, padx=10, fill="x")
        
        tk.Label(dest_frame, text="Model Subfolder:", font=("Arial", 9, "bold")).pack(anchor="w")
        folder_var = tk.StringVar()
        folder_combo = ttk.Combobox(dest_frame, textvariable=folder_var, state="readonly", font=("Arial", 9))
        folder_combo.pack(fill="x", pady=5)
        
        def update_model_folders():
            """Update list of model folders from ComfyUI"""
            comfyui = path_var.get()
            if not comfyui or not os.path.exists(comfyui):
                folder_combo['values'] = []
                return
            
            models_dir = os.path.join(comfyui, "models")
            if not os.path.exists(models_dir):
                folder_combo['values'] = []
                return
            
            try:
                folders = [f for f in os.listdir(models_dir) 
                          if os.path.isdir(os.path.join(models_dir, f))]
                folders.sort()
                folder_combo['values'] = folders
                if folders:
                    # Try to default to common folders
                    for default in ["checkpoints", "unet", "diffusion_models"]:
                        if default in folders:
                            folder_var.set(default)
                            break
                    if not folder_var.get():
                        folder_var.set(folders[0])
            except:
                folder_combo['values'] = []
        
        # Progress Section
        progress_frame = tk.Frame(window)
        progress_frame.pack(pady=10, padx=10, fill="x")
        
        progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=400)
        progress_bar.pack(fill="x")
        
        status_label = tk.Label(window, text="Ready", font=("Arial", 9), fg="#4CAF50")
        status_label.pack(pady=5)
        
        def download_model():
            """Download the selected model"""
            nonlocal downloading
            
            if downloading:
                messagebox.showwarning("Download in Progress", "Please wait for current download to finish", parent=window)
                return
            
            model_id = model_var.get()
            filename = file_var.get()
            dest_folder = folder_var.get()
            comfyui = path_var.get()
            
            if not model_id or not filename:
                messagebox.showwarning("No Selection", "Please select a model and file", parent=window)
                return
            
            if not dest_folder or not comfyui:
                messagebox.showwarning("No Destination", "Please select ComfyUI path and destination folder", parent=window)
                return
            
            # Build paths
            dest_dir = os.path.join(comfyui, "models", dest_folder)
            if not os.path.exists(dest_dir):
                messagebox.showerror("Invalid Path", f"Destination folder not found:\n{dest_dir}", parent=window)
                return
            
            output_file = os.path.join(dest_dir, os.path.basename(filename))
            
            # Check if file exists
            if os.path.exists(output_file):
                if not messagebox.askyesno("File Exists", 
                    f"File already exists:\n{os.path.basename(filename)}\n\nOverwrite?", 
                    parent=window):
                    return
            
            downloading = True
            download_btn.config(state="disabled")
            
            def do_download():
                nonlocal downloading
                try:
                    encoded_model_id = urllib.parse.quote(model_id, safe='/')
                    encoded_filename = urllib.parse.quote(filename, safe='/')
                    url = f"https://huggingface.co/{encoded_model_id}/resolve/main/{encoded_filename}?download=true"
                    
                    status_label.config(text="Downloading...")
                    progress_bar['value'] = 0
                    window.update()
                    
                    # Download with progress
                    def reporthook(count, block_size, total_size):
                        if total_size > 0:
                            percent = min(100, int(count * block_size * 100 / total_size))
                            progress_bar['value'] = percent
                            status_label.config(text=f"Downloading... {percent}%")
                            window.update()
                    
                    request = urllib.request.Request(url, headers={"User-Agent": "GGF-Tray/1.0"})
                    with urlopen_with_ssl(request, timeout=30) as response, open(output_file, 'wb') as out_file:
                        total_size = int(response.headers.get('Content-Length') or 0)
                        block_size = 1024 * 1024
                        count = 0
                        while True:
                            chunk = response.read(block_size)
                            if not chunk:
                                break
                            out_file.write(chunk)
                            count += 1
                            reporthook(count, block_size, total_size)
                    
                    progress_bar['value'] = 100
                    status_label.config(text="Download complete!")
                    messagebox.showinfo("Success", 
                        f"Downloaded successfully to:\n{output_file}", 
                        parent=window)
                    
                except Exception as e:
                    status_label.config(text="Download failed")
                    messagebox.showerror("Download Error", 
                        f"Failed to download:\n{str(e)}", 
                        parent=window)
                finally:
                    downloading = False
                    download_btn.config(state="normal")
                    progress_bar['value'] = 0
            
            # Run download in thread
            threading.Thread(target=do_download, daemon=True).start()
        
        # Download Button
        download_btn = tk.Button(window, text="Download Model", command=download_model,
                 bg="#FF9800", fg="white", font=("Arial", 12, "bold"), 
                 width=20, height=2)
        download_btn.pack(pady=10)
        
        # Close Button
        tk.Button(window, text="Close", command=window.destroy,
                 bg="#666", fg="white", width=15).pack(pady=5)
        
        # Bind events
        model_combo.bind('<<ComboboxSelected>>', lambda e: fetch_model_files())
        file_combo.bind('<<ComboboxSelected>>', update_file_size)
        file_filter_var.trace_add('write', filter_files)
        
        # Initialize
        update_model_folders()
        
        window.mainloop()
    
    def toggle_login(self):
        """Login or logout based on current auth state"""
        if not self.auth:
            self.show_message("Auth Unavailable", "Authentication system not available", "error")
            return
        
        def do_logout():
            """Run logout in thread to avoid blocking"""
            import tkinter as tk
            from tkinter import messagebox
            
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            root.update()  # Force window to process
            
            user_name = self.auth.get_name()
            tier = self.auth.format_tier_name()
            
            result = messagebox.askyesno("Logout", 
                f"Logout from GGF?\n\nCurrently logged in as:\n{user_name} ({tier})",
                parent=root)
            
            if result:
                self.auth.clear_cache()
                root.destroy()
                
                # Auto-restart to refresh login state
                self.restart_app()
            else:
                root.destroy()
        
        def do_login():
            """Trigger Patreon login directly"""
            if not self.auth:
                return
            
            # Start login flow (opens browser)
            token = self.auth.login()
        
            # Poll for auth in background thread
            def poll_and_restart():
                result = self.auth.poll_for_auth(token, timeout=120, interval=2)
                if result:
                    # Login successful - auto-restart
                    self.restart_app()
            
            self.run_background_task(poll_and_restart)
        
        if self.auth.is_authenticated():
            # Run logout in thread
            self.run_background_task(do_logout)
        else:
            # Run login directly
            self.run_background_task(do_login)
    
    def restart_app(self):
        """Restart the tray application"""
        print("Restart button clicked")
        self.stop_command_server()
        
        # Close visualizer if running
        self.close_audio_visualizer()
        self.cleanup_helper_processes()
        
        # Kill app_search if open
        try:
            if getattr(self, '_app_search_proc', None) and self._app_search_proc.poll() is None:
                self._app_search_proc.kill()
        except:
            pass
        
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
            subprocess.Popen(f'start "" "{python}" "{script}"', shell=True)
        
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
            item('Convert to FLAC', lambda: self.open_menu_for('convert_flac')),
            item('Convert to OGG', lambda: self.open_menu_for('convert_ogg')),
        ]
        menu_items.append(item('Audio Operations', pystray.Menu(*audio_items)))
        
        # Audio Visualizer submenu (define BEFORE using it)
        audio_visualizer_menu = [
            item('Start Visualizer', lambda: self.open_menu_for('audio_visualizer')),
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
        menu_items.append(item('Audio Visualizer', pystray.Menu(*audio_visualizer_menu)))
        
        # UTILITY submenu
        utility_items = [
            item('HuggingFace Model Browser', lambda: self.open_menu_for('huggingface_browser')),
            pystray.Menu.SEPARATOR,
            item('Open Config File', self.open_config),
        ]
        menu_items.append(item('Utility', pystray.Menu(*utility_items)))
        
        menu_items.append(pystray.Menu.SEPARATOR)
        
        # Bottom items
        menu_items.extend([
            item('Open Visualizer', lambda: self.open_menu_for('audio_visualizer'), default=True, visible=False),
            item('Member Site', self.open_website),
            item(
                'Logout from GGF' if (self.auth and self.auth.is_authenticated()) else 'Login to GGF',
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
        self.show_startup_tips_if_needed()
        
        # Run the icon (blocks)
        self.icon.run()

if __name__ == "__main__":
    if "--run-app-search" in sys.argv:
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

        auto_confirm = "--auto-install" in sys.argv
        app = GGFTray()
        app.install_ggf_app(zip_path=zip_path, auto_confirm=auto_confirm)
    elif "--show-companion-menu" in sys.argv or "--show-visualizer-menu" in sys.argv:
        app = GGFTray()
        app.show_visualizer_companion_menu()
    else:
        app = GGFTray()
        app.run()
