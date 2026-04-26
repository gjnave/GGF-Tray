import sys
import json
import os
import numpy as np
import math
import subprocess
import time
import socket
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, 
                             QVBoxLayout, QLabel, QSlider, QPushButton,
                             QComboBox, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtWebEngineWidgets import QWebEngineView
import pyaudiowpatch as pyaudio
import threading
import queue

try:
    import psutil
except ImportError:
    psutil = None


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


SCRIPT_DIR = get_app_dir()
CONFIG_PATH = os.path.join(SCRIPT_DIR, "visualizer_config.json")
STATE_PATH = os.path.join(SCRIPT_DIR, "visualizer_state.json")
CLICK_THROUGH_TIMEOUT_MS = 30000
SHORTCUTS_CONFIG = os.path.join(SCRIPT_DIR, "shortcuts.txt")
TRAY_IPC_HOST = "127.0.0.1"
TRAY_IPC_PORT = 47653
TRAY_IPC_BUFFER = 65536
LOG_PATH = os.path.join(SCRIPT_DIR, "visualizer_debug.log")


def log_visualizer(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as file_handle:
            file_handle.write(line + "\n")
    except Exception:
        pass


class SettingsWindow(QWidget):
    """Settings window for visualizer configuration"""
    settings_changed = pyqtSignal(dict)
    audio_device_changed = pyqtSignal(int)
    
    def __init__(self, config, audio_devices, current_device_index, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.audio_devices = audio_devices
        self.current_device_index = current_device_index
        
        # Make this window independent - don't close parent when this closes
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        # Add in __init__ method:
        self.mouse_in_window = False  # Track mouse position manually
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Visualizer Settings")
        self.setFixedWidth(430)
        
        layout = QVBoxLayout()
        
        # Audio device selection
        layout.addWidget(QLabel("Audio Input Device:"))
        self.device_combo = QComboBox()
        for device in self.audio_devices:
            self.device_combo.addItem(device['name'])
        self.device_combo.setCurrentIndex(self.current_device_index)
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        layout.addWidget(self.device_combo)
        
        # Add separator
        layout.addWidget(QLabel(""))
        layout.addWidget(QLabel("Visualizer Settings:"))
        
        # Visual Mode selection
        layout.addWidget(QLabel("Visual Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Spark Fountain")
        self.mode_combo.addItem("Radial Burst")
        self.mode_combo.addItem("Equalizer Bars")
        self.mode_combo.addItem("Spiral Vortex")
        self.mode_combo.addItem("Traveling Wave")
        self.mode_combo.addItem("Flower Bloom")
        self.mode_combo.addItem("Psychedelic Face")
        self.mode_combo.setCurrentIndex(self.config.get('visualMode', 0))
        layout.addWidget(self.mode_combo)
        
        # Density slider
        layout.addWidget(QLabel("Particle Density:"))
        self.density_slider = QSlider(Qt.Orientation.Horizontal)
        self.density_slider.setMinimum(1)
        self.density_slider.setMaximum(8)
        self.density_slider.setValue(self.config.get('density', 3))
        self.density_label = QLabel(str(self.config.get('density', 3)))
        self.density_slider.valueChanged.connect(lambda v: self.density_label.setText(str(v)))
        layout.addWidget(self.density_slider)
        layout.addWidget(self.density_label)
        
        # Speed slider
        layout.addWidget(QLabel("Speed:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(50)
        self.speed_slider.setValue(int(self.config.get('speed', 10) * 10))
        self.speed_label = QLabel(str(self.config.get('speed', 1.0)))
        self.speed_slider.valueChanged.connect(lambda v: self.speed_label.setText(str(v/10)))
        layout.addWidget(self.speed_slider)
        layout.addWidget(self.speed_label)
        
        # Bass sensitivity
        layout.addWidget(QLabel("Bass Sensitivity:"))
        self.bass_slider = QSlider(Qt.Orientation.Horizontal)
        self.bass_slider.setMinimum(0)
        self.bass_slider.setMaximum(50)
        self.bass_slider.setValue(int(self.config.get('bassSensitivity', 15) * 10))
        self.bass_label = QLabel(str(self.config.get('bassSensitivity', 1.5)))
        self.bass_slider.valueChanged.connect(lambda v: self.bass_label.setText(str(v/10)))
        layout.addWidget(self.bass_slider)
        layout.addWidget(self.bass_label)
        
        # Color cycle speed
        layout.addWidget(QLabel("Color Cycle Speed:"))
        self.color_slider = QSlider(Qt.Orientation.Horizontal)
        self.color_slider.setMinimum(0)
        self.color_slider.setMaximum(100)
        self.color_slider.setValue(int(self.config.get('colorCycleSpeed', 10)))
        self.color_label = QLabel(str(self.config.get('colorCycleSpeed', 10)))
        self.color_slider.valueChanged.connect(lambda v: self.color_label.setText(str(v)))
        layout.addWidget(self.color_slider)
        layout.addWidget(self.color_label)
        
        # Bass explosion
        layout.addWidget(QLabel("Bass Explosion:"))
        self.explosion_slider = QSlider(Qt.Orientation.Horizontal)
        self.explosion_slider.setMinimum(0)
        self.explosion_slider.setMaximum(50)
        self.explosion_slider.setValue(int(self.config.get('bassExplosion', 10) * 10))
        self.explosion_label = QLabel(str(self.config.get('bassExplosion', 1.0)))
        self.explosion_slider.valueChanged.connect(lambda v: self.explosion_label.setText(str(v/10)))
        layout.addWidget(self.explosion_slider)
        layout.addWidget(self.explosion_label)
        
        # Audio sensitivity
        layout.addWidget(QLabel("Audio Sensitivity:"))
        self.sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity_slider.setMinimum(1)
        self.sensitivity_slider.setMaximum(200)
        self.sensitivity_slider.setValue(int(self.config.get('sensitivity', 100)))
        self.sensitivity_label = QLabel(str(self.config.get('sensitivity', 100)))
        self.sensitivity_slider.valueChanged.connect(lambda v: self.sensitivity_label.setText(str(v)))
        layout.addWidget(self.sensitivity_slider)
        layout.addWidget(self.sensitivity_label)
        
        # RANDOM MODE CHECKBOX
        layout.addWidget(QLabel(""))
        self.random_checkbox = QCheckBox("Random Mode (auto-change settings every 3 seconds)")
        self.random_checkbox.setChecked(self.config.get('randomMode', False))
        layout.addWidget(self.random_checkbox)

        self.random_background_checkbox = QCheckBox("Random Visual Backgrounds (cycle visual modes)")
        self.random_background_checkbox.setChecked(self.config.get('randomBackgrounds', False))
        layout.addWidget(self.random_background_checkbox)

        layout.addWidget(QLabel("Overlay:"))
        self.overlay_combo = QComboBox()
        self.overlay_combo.addItem("Audio Levels", "audio")
        self.overlay_combo.addItem("System Stats (CPU/GPU/FPS)", "system")
        self.overlay_combo.addItem("Hidden", "hidden")
        overlay_mode = self.config.get('overlayMode', 'audio')
        overlay_index = self.overlay_combo.findData(overlay_mode)
        self.overlay_combo.setCurrentIndex(overlay_index if overlay_index >= 0 else 0)
        layout.addWidget(self.overlay_combo)
        
        # Save and close buttons
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)  # Use hide() instead of close()
        
        layout.addWidget(save_btn)
        layout.addWidget(close_btn)
        
        self.setLayout(layout)
        
    def on_device_changed(self, index):
        self.current_device_index = index
        self.audio_device_changed.emit(index)
        
    def save_settings(self):
        self.config['visualMode'] = self.mode_combo.currentIndex()
        self.config['density'] = self.density_slider.value()
        self.config['speed'] = self.speed_slider.value() / 10
        self.config['bassSensitivity'] = self.bass_slider.value() / 10
        self.config['colorCycleSpeed'] = self.color_slider.value()
        self.config['bassExplosion'] = self.explosion_slider.value() / 10
        self.config['sensitivity'] = self.sensitivity_slider.value()
        self.config['randomMode'] = self.random_checkbox.isChecked()
        self.config['randomBackgrounds'] = self.random_background_checkbox.isChecked()
        self.config['overlayMode'] = self.overlay_combo.currentData()
        
        self.settings_changed.emit(self.config)
        
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
        
        # Use hide() instead of close() to avoid Qt lifecycle issues
        self.hide()


class VisualizerWindow(QMainWindow):
    device_error = pyqtSignal(str)
    device_success = pyqtSignal(str)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.click_effect_active = False
        self.click_hue_shift = 0
        self.click_settings_backup = None
        self.audio_data = {'bass': 0, 'mid': 0, 'treble': 0, 'overall': 0, 'rms': 0}
        self.js_ready = False
        self.audio_thread = None
        self.audio_stop_event = threading.Event()
        self.selected_device_index = None
        self.device_working = False
        self.audio_data_lock = threading.Lock()
        self.band_smooth = {'bass': 0.0, 'mid': 0.0, 'treble': 0.0}
        self.band_peaks = {'bass': 0.05, 'mid': 0.05, 'treble': 0.05}
        self.system_stats = {'cpu': 0.0, 'gpu': None}
        self.last_gpu_poll = 0.0
        self.gpu_available = None
        
        # Click-through mode (controlled from tray via file)
        self.click_through_mode = False
        self.state_file = STATE_PATH
        self.click_through_timer = QTimer()
        self.click_through_timer.setSingleShot(True)
        self.click_through_timer.timeout.connect(self.disable_click_through_timeout)
        
        # Timer to check for commands from tray
        self.state_check_timer = QTimer()
        self.state_check_timer.timeout.connect(self.check_state_file)
        self.state_check_timer.start(200)  # Check every 200ms for faster response
        
        # Auto-gain control
        self.auto_gain = 1.0
        self.gain_target = 0.3
        self.gain_adjust_rate = 0.01
        
        self.beat_history = []
        self.last_beat_time = 0
        self.current_bpm = 120
        
        self.init_ui()
        self.device_success.connect(lambda message: self.update_device_status(message, "active"))
        self.device_error.connect(lambda message: self.update_device_status(message, "error"))
        
        QTimer.singleShot(500, self.try_audio_devices_async)
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.push_audio_data)
        self.update_timer.start(33)

        self.system_stats_timer = QTimer()
        self.system_stats_timer.timeout.connect(self.push_system_stats)
        self.system_stats_timer.start(1000)
        
        # Write initial state file
        self.write_state_file()
        
    def init_ui(self):
        self.setWindowTitle("Audio Visualizer")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                           Qt.WindowType.WindowStaysOnTopHint |
                           Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        screen = QApplication.primaryScreen().geometry()
        width = 400
        height = 300
        x = screen.width() - width - 10
        y = screen.height() - height - 50
        self.setGeometry(x, y, width, height)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.web_view = QWebEngineView()
        self.web_view.loadFinished.connect(self.on_load_finished)
        # Enable simple right-click menu for dragging
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self.show_context_menu)
        
        self.load_visualizer()
        
        layout.addWidget(self.web_view)
        
        close_btn = QPushButton("X", self)
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 50, 50, 180);
                color: white;
                border-radius: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 80, 80, 220);
            }
        """)
        close_btn.move(width - 40, 10)
        close_btn.clicked.connect(self.close)
        close_btn.raise_()
        
        settings_btn = QPushButton("⚙", self)
        settings_btn.setFixedSize(30, 30)
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(50, 150, 255, 180);
                color: white;
                border-radius: 15px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(80, 180, 255, 220);
            }
        """)
        settings_btn.move(width - 80, 10)
        settings_btn.clicked.connect(self.show_settings)
        settings_btn.raise_()

        self.menu_btn = QPushButton("Menu", self)
        self.menu_btn.setFixedSize(54, 28)
        self.menu_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(20, 20, 20, 190);
                color: white;
                border: 1px solid rgba(255, 255, 255, 80);
                border-radius: 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(50, 150, 255, 220);
            }
        """)
        self.menu_btn.move(width - 64, height - 40)
        self.menu_btn.clicked.connect(self.show_tray_menu_popup)
        self.menu_btn.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'menu_btn'):
            self.menu_btn.move(self.width() - 64, self.height() - 40)
    
    def show_context_menu(self, pos):
        """Simple right-click menu - main controls are in tray"""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        
        # Show current mode
        current_mode_names = ["Spark Fountain", "Radial Burst", "Equalizer Bars", 
                              "Spiral Vortex", "Traveling Wave", "Flower Bloom", "Psychedelic Face"]
        current_mode = self.config.get('visualMode', 0)
        
        info_action = menu.addAction(f"Mode: {current_mode_names[current_mode]}")
        info_action.setEnabled(False)
        
        # Show click-through status
        click_through_status = "ON" if self.click_through_mode else "OFF"
        click_through_action = menu.addAction(f"Click Through: {click_through_status}")
        click_through_action.setEnabled(False)
        
        menu.addSeparator()
        close_action = menu.addAction("Close Visualizer")
        close_action.triggered.connect(self.close)
        
        menu.exec(self.web_view.mapToGlobal(pos))
        
    def menu_toggle_click_through(self):
        # Toggle internal state
        new_state = not self.click_through_mode
        self.toggle_click_through(new_state)

    def build_controls_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)

        mode_menu = menu.addMenu("Visual Mode")
        mode_names = ["Spark Fountain", "Radial Burst", "Equalizer Bars", "Spiral Vortex", "Traveling Wave", "Flower Bloom", "Psychedelic Face"]
        current_mode = self.config.get('visualMode', 0)

        for i, mode_name in enumerate(mode_names):
            action = mode_menu.addAction(mode_name)
            if i == current_mode:
                action.setText(f"* {mode_name}")
            action.triggered.connect(lambda checked, mode=i: self.switch_visual_mode(mode))

        overlay_menu = menu.addMenu("Overlay")
        for label, mode in [("Audio Levels", "audio"), ("System Stats", "system"), ("Hidden", "hidden")]:
            action = overlay_menu.addAction(label)
            if self.config.get('overlayMode', 'audio') == mode:
                action.setText(f"* {label}")
            action.triggered.connect(lambda checked, selected=mode: self.set_overlay_mode(selected))

        menu.addSeparator()

        click_label = "Click Through (30 sec)" if not self.click_through_mode else "Click Through On"
        click_through = menu.addAction(click_label)
        click_through.triggered.connect(self.menu_toggle_click_through)

        random_action = menu.addAction(
            "Random Settings On" if self.config.get('randomMode', False) else "Random Settings Off"
        )
        random_action.triggered.connect(self.toggle_random_mode)

        background_action = menu.addAction(
            "Random Backgrounds On" if self.config.get('randomBackgrounds', False) else "Random Backgrounds Off"
        )
        background_action.triggered.connect(self.toggle_random_backgrounds)

        refresh_action = menu.addAction("Refresh Visualizer")
        refresh_action.triggered.connect(self.load_visualizer)

        menu.addSeparator()

        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self.show_settings)

        close_action = menu.addAction("Close Visualizer")
        close_action.triggered.connect(self.close)

        return menu

    def send_tray_command(self, command, **payload):
        message = {"command": command, **payload}
        with socket.create_connection((TRAY_IPC_HOST, TRAY_IPC_PORT), timeout=2.0) as sock:
            sock.sendall(json.dumps(message).encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            response = sock.recv(TRAY_IPC_BUFFER)
        return json.loads(response.decode("utf-8")) if response else {"ok": True}

    def run_tray_command(self, command, **payload):
        try:
            response = self.send_tray_command(command, **payload)
            if response.get("ok"):
                return True
            error_message = response.get("error")
            if error_message:
                self.show_status_message(
                    "GGF Tray Error",
                    f"The tray returned an error:\n\n{error_message}"
                )
                return False
        except Exception as e:
            print(f"Tray command failed: {e}")

        self.show_status_message(
            "GGF Tray Not Available",
            "The visualizer menu could not reach the running GGF tray.\n\nStart the tray first, then try again."
        )
        return False

    def load_tray_shortcuts(self):
        shortcuts = {}
        if not os.path.exists(SHORTCUTS_CONFIG):
            return shortcuts

        try:
            with open(SHORTCUTS_CONFIG, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        name, filepath = line.split('=', 1)
                        shortcuts[name.strip()] = filepath.strip()
        except Exception as e:
            print(f"Error loading tray shortcuts: {e}")
        return shortcuts

    def show_status_message(self, title, message):
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()

    def build_tray_menu(self):
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        shortcuts = self.load_tray_shortcuts()

        if shortcuts:
            quick_launch_menu = menu.addMenu("Quick Launch")
            for name in sorted(shortcuts.keys(), key=lambda value: value.lower()):
                action = quick_launch_menu.addAction(name)
                action.triggered.connect(lambda checked=False, shortcut_name=name: self.run_tray_command("launch_shortcut", name=shortcut_name))
            quick_launch_menu.addSeparator()
            refresh_action = quick_launch_menu.addAction("Refresh List")
            refresh_action.triggered.connect(lambda: self.run_tray_command("refresh_shortcuts"))

        ai_apps_menu = menu.addMenu("A.I. Apps")
        search_action = ai_apps_menu.addAction("Search for Apps")
        search_action.triggered.connect(lambda: self.run_tray_command("open_app_search"))
        ai_apps_menu.addSeparator()
        for label, action_name in [
            ("Quick Launch Manager", "quick_launch"),
            ("Install GGF Apps", "install_app"),
            ("Delete GGF Apps", "delete_app"),
        ]:
            action = ai_apps_menu.addAction(label)
            action.triggered.connect(lambda checked=False, tray_action=action_name: self.run_tray_command("menu_action", action=tray_action))

        image_menu = menu.addMenu("Image Operations")
        for label, action_name in [
            ("Convert to JPG", "convert_jpg"),
            ("Convert to PNG", "convert_png"),
            ("Convert to WebP", "convert_webp"),
            ("Convert to BMP", "convert_bmp"),
            ("Resize Image", "resize_image"),
        ]:
            if label == "Resize Image":
                image_menu.addSeparator()
            action = image_menu.addAction(label)
            action.triggered.connect(lambda checked=False, tray_action=action_name: self.run_tray_command("menu_action", action=tray_action))

        audio_menu = menu.addMenu("Audio Operations")
        for label, action_name in [
            ("Convert to WAV", "convert_wav"),
            ("Convert to MP3", "convert_mp3"),
            ("Convert to AAC", "convert_aac"),
            ("Convert to FLAC", "convert_flac"),
            ("Convert to OGG", "convert_ogg"),
        ]:
            action = audio_menu.addAction(label)
            action.triggered.connect(lambda checked=False, tray_action=action_name: self.run_tray_command("menu_action", action=tray_action))

        video_menu = menu.addMenu("Video Operations")
        for label, action_name in [
            ("Convert Video", "convert_video"),
            ("Shrink Video", "shrink_video"),
            ("Download Video", "download"),
            ("Save First Frame", "save_first_frame"),
            ("Save Last Frame", "save_last_frame"),
        ]:
            if label == "Save First Frame":
                video_menu.addSeparator()
            action = video_menu.addAction(label)
            action.triggered.connect(lambda checked=False, tray_action=action_name: self.run_tray_command("menu_action", action=tray_action))

        visualizer_menu = menu.addMenu("Audio Visualizer")
        start_action = visualizer_menu.addAction("Start Visualizer")
        start_action.triggered.connect(lambda: self.run_tray_command("menu_action", action="audio_visualizer"))
        click_label = "Click Through Off" if self.click_through_mode else "Click Through"
        click_action = visualizer_menu.addAction(click_label)
        click_action.triggered.connect(lambda: self.run_tray_command("toggle_click_through"))

        utility_menu = menu.addMenu("Utility")
        hf_action = utility_menu.addAction("HuggingFace Model Browser")
        hf_action.triggered.connect(lambda: self.run_tray_command("menu_action", action="huggingface_browser"))
        utility_menu.addSeparator()
        config_action = utility_menu.addAction("Open Config File")
        config_action.triggered.connect(lambda: self.run_tray_command("open_config"))

        menu.addSeparator()

        website_action = menu.addAction("Member Site")
        website_action.triggered.connect(lambda: self.run_tray_command("open_website"))
        login_action = menu.addAction("Login / Logout")
        login_action.triggered.connect(lambda: self.run_tray_command("toggle_login"))
        restart_action = menu.addAction("Restart App")
        restart_action.triggered.connect(lambda: self.run_tray_command("restart_app"))
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(lambda: self.run_tray_command("quit_tray"))

        return menu

    def show_tray_menu_popup(self):
        menu = self.build_tray_menu()
        menu_pos = self.menu_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height()))
        menu.exec(menu_pos)
    
    def show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        
        mode_menu = menu.addMenu("Visual Mode")
        
        mode_names = ["Spark Fountain", "Radial Burst", "Equalizer Bars", "Spiral Vortex", "Traveling Wave", "Flower Bloom", "Psychedelic Face"]
        current_mode = self.config.get('visualMode', 0)
        
        for i, mode_name in enumerate(mode_names):
            action = mode_menu.addAction(mode_name)
            if i == current_mode:
                action.setText(f"● {mode_name}")
            action.triggered.connect(lambda checked, mode=i: self.switch_visual_mode(mode))
        
        menu.addSeparator()
        
        click_through = menu.addAction(
            "Click Through ✓" if self.click_through_mode else "Click Through"
        )
        click_through.triggered.connect(self.menu_toggle_click_through)

   
        refresh_action = menu.addAction("Refresh Visualizer")
        refresh_action.triggered.connect(self.load_visualizer)
        
        menu.addSeparator()
        
        random_action = menu.addAction("Toggle Random Mode")
        random_action.triggered.connect(self.toggle_random_mode)
        
        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self.show_settings)
        
        menu.addSeparator()
        
        close_action = menu.addAction("Close Visualizer")
        close_action.triggered.connect(self.close)
        
        menu.exec(self.web_view.mapToGlobal(pos))
    
    def switch_visual_mode(self, mode_index):
        print(f"\nSwitching to visual mode {mode_index}")
        self.config['visualMode'] = mode_index
        
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving mode: {e}")
        
        if self.js_ready:
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
        
        # Update state file
        self.write_state_file()
    
    def show_settings(self):
        # Create settings window only once - NO PARENT to avoid lifecycle issues
        if not hasattr(self, 'settings_window') or self.settings_window is None:
            devices = self.get_audio_devices()
            current_idx = 0
            for i, dev in enumerate(devices):
                if dev['index'] == self.selected_device_index:
                    current_idx = i
                    break
            
            # Pass None as parent to make it completely independent
            self.settings_window = SettingsWindow(self.config, devices, current_idx, parent=None)
            self.settings_window.settings_changed.connect(self.update_settings)
            self.settings_window.audio_device_changed.connect(self.on_device_changed)
        
        # Just show it (will create if first time, or unhide if hidden)
        self.settings_window.show()
        self.settings_window.raise_()
    
    def toggle_random_mode(self):
        self.config['randomMode'] = not self.config.get('randomMode', False)
        self.save_config()
        if self.js_ready:
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
        print(f"Random mode: {'ON' if self.config['randomMode'] else 'OFF'}")
        
        # Update state file
        self.write_state_file()

    def toggle_random_backgrounds(self):
        self.config['randomBackgrounds'] = not self.config.get('randomBackgrounds', False)
        self.save_config()
        if self.js_ready:
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
        print(f"Random backgrounds: {'ON' if self.config['randomBackgrounds'] else 'OFF'}")
        self.write_state_file()

    def set_overlay_mode(self, mode):
        self.config['overlayMode'] = mode
        self.save_config()
        if self.js_ready:
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")

    def save_config(self):
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.trigger_click_effect()
            self.drag_position = event.globalPosition().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if hasattr(self, 'drag_position'):
            delta = event.globalPosition().toPoint() - self.drag_position
            self.move(self.pos() + delta)
            self.drag_position = event.globalPosition().toPoint()
            event.accept()

    def trigger_click_effect(self):
        if not self.js_ready:
            return
        
        import random
        
        print("\n" + "="*60)
        print("LEFT-CLICK DETECTED - TRIGGERING COLOR/SETTINGS JUMP!")
        print("="*60)
        
        self.click_hue_shift = random.randint(0, 360)
        
        if self.click_settings_backup is None:
            self.click_settings_backup = self.config.copy()
        
        dramatic_settings = {
            'density': random.randint(5, 25),
            'speed': random.uniform(0.5, 3.0),
            'bassSensitivity': random.uniform(2.0, 8.0),
            'colorCycleSpeed': random.randint(50, 150),
            'bassExplosion': random.uniform(2.0, 6.0),
            'sensitivity': random.randint(150, 250),
            'emitterGlowSize': random.randint(10, 30)
        }
        
        js_code = f"""
            if (window.triggerClickEffect) {{
                window.triggerClickEffect({self.click_hue_shift}, {json.dumps(dramatic_settings)});
            }}
        """
        
        self.web_view.page().runJavaScript(js_code)
        QTimer.singleShot(3000, self.restore_settings)
        
        print(f"Applied dramatic settings: {dramatic_settings}")

    def restore_settings(self):
        if self.click_settings_backup:
            print("\nRESTORING SETTINGS AFTER CLICK EFFECT")
            
            for key, value in self.click_settings_backup.items():
                if key in self.config:
                    self.config[key] = value
            
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
            
            self.click_settings_backup = None
        
    def load_visualizer(self):
        html = self.get_visualizer_html()
        self.web_view.setHtml(html)
        
    def get_visualizer_html(self):
        config_json = json.dumps(self.config)
        
        js_code = """
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);
setTimeout(resizeCanvas, 100);

let settings = """ + config_json + """;
let audioData = {bass: 0, mid: 0, treble: 0, overall: 0, rms: 0, bpm: 120};
let systemStats = {cpu: 0, gpu: null, fps: 0};
let lastFpsTime = performance.now();
let frameCounter = 0;

window.updateSettings = function(newSettings) {
    settings = newSettings;
    sparks = [];
    bars = [];
    spiralParticles = [];
    psychedelicParticles = [];  // FOR PSYCHEDELIC FACE ONLY
    flowerParticles = [];       // FOR FLOWER BLOOM ONLY
    wavePoints = initWaveArray();
    applyOverlayMode();
};

window.updateAudio = function(data) {
    audioData = data;
    const bassPercent = Math.min(100, data.bass * 100);
    const midPercent = Math.min(100, data.mid * 100);
    const treblePercent = Math.min(100, data.treble * 100);
    
    const bassBar = document.getElementById('bassBar');
    if (!bassBar) return;
    bassBar.style.width = bassPercent + '%';
    document.getElementById('midBar').style.width = midPercent + '%';
    document.getElementById('trebleBar').style.width = treblePercent + '%';
    
    document.getElementById('bassValue').textContent = data.bass.toFixed(2);
    document.getElementById('midValue').textContent = data.mid.toFixed(2);
    document.getElementById('trebleValue').textContent = data.treble.toFixed(2);
};

window.visualizerReady = true;
window.updateDeviceStatus = function(message, status) {
    const statusEl = document.getElementById('deviceStatus');
    if (!message) {
        statusEl.style.display = 'none';
        return;
    }
    statusEl.textContent = message;
    statusEl.className = status;
    statusEl.style.display = 'block';
    if (window.deviceStatusTimer) clearTimeout(window.deviceStatusTimer);
    if (status === 'active') {
        window.deviceStatusTimer = setTimeout(() => {
            statusEl.style.display = 'none';
        }, 4000);
    }
};

window.updateSystemStats = function(data) {
    systemStats = data;
    const cpuValue = document.getElementById('cpuValue');
    if (!cpuValue) return;
    const cpu = Number(data.cpu || 0);
    const gpu = data.gpu === null || data.gpu === undefined ? null : Number(data.gpu);
    document.getElementById('cpuBar').style.width = Math.min(100, cpu) + '%';
    document.getElementById('gpuBar').style.width = (gpu === null ? 0 : Math.min(100, gpu)) + '%';
    cpuValue.textContent = cpu.toFixed(0) + '%';
    document.getElementById('gpuValue').textContent = gpu === null ? '--' : gpu.toFixed(0) + '%';
};

function applyOverlayMode() {
    const overlay = document.getElementById('audioDebug');
    const audioPanel = document.getElementById('audioPanel');
    const systemPanel = document.getElementById('systemPanel');
    if (!overlay || !audioPanel || !systemPanel) return;
    const mode = settings.overlayMode || 'audio';
    overlay.style.display = mode === 'hidden' ? 'none' : 'block';
    audioPanel.style.display = mode === 'audio' ? 'block' : 'none';
    systemPanel.style.display = mode === 'system' ? 'block' : 'none';
};

let clickEffectActive = false;
let clickHueShift = 0;
let clickStartTime = 0;
let clickDuration = 3000;

window.triggerClickEffect = function(hueShift, newSettings) {
    if (newSettings) {
        for (let key in newSettings) {
            if (newSettings.hasOwnProperty(key)) {
                settings[key] = newSettings[key];
            }
        }
    }
    
    clickEffectActive = true;
    clickHueShift = hueShift;
    clickStartTime = Date.now();
    
    createClickParticles(30, hueShift);
    
    setTimeout(() => {
        clickEffectActive = false;
    }, clickDuration);
};

function createClickParticles(count, hueShift) {
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    
    for(let i = 0; i < count; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 3 + Math.random() * 8;
        const hue = (hueShift + Math.random() * 120) % 360;
        const size = 2 + Math.random() * 4;
        
        const spark = new Spark(centerX, centerY, angle, speed, hue);
        spark.size = size;
        spark.life = 0.8 + Math.random() * 0.2;
        spark.decay = 0.005 + Math.random() * 0.01;
        
        sparks.push(spark);
    }
}

class Spark {
    constructor(x, y, angle, speed, hue) {
        this.x = x;
        this.y = y;
        this.vx = Math.cos(angle) * speed;
        this.vy = Math.sin(angle) * speed;
        this.life = 1.0;
        this.decay = 0.01;
        this.hue = hue;
        this.size = 1 + Math.random() * 2;
    }
    
    update() {
        this.x += this.vx;
        this.y += this.vy;
        this.vy += 0.1;
        this.life -= this.decay;
    }
    
    draw() {
        let drawHue = this.hue;
        if (clickEffectActive) {
            const elapsed = Date.now() - clickStartTime;
            if (elapsed < clickDuration) {
                const intensity = 1 - (elapsed / clickDuration);
                drawHue = (this.hue + clickHueShift * intensity) % 360;
            }
        }
        
        ctx.fillStyle = `hsla(${drawHue}, 100%, 50%, ${this.life})`;
        ctx.fillRect(this.x, this.y, this.size, this.size);
    }
    
    applyBassExplosion(centerX, centerY, force) {
        const dx = this.x - centerX;
        const dy = this.y - centerY;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        this.vx += (dx / dist) * force;
        this.vy += (dy / dist) * force;
    }
}

class EqualizerBar {
    constructor(x, index, total) {
        this.x = x;
        this.index = index;
        this.total = total;
        this.height = 0;
        this.targetHeight = 0;
        this.width = 0;
        this.hue = (index / total) * 360;
    }
    
    update(magnitude, barWidth) {
        this.width = barWidth;
        this.targetHeight = magnitude * canvas.height * 0.8;
        this.height += (this.targetHeight - this.height) * 0.3;
    }
    
    draw() {
        let drawHue = this.hue;
        if (clickEffectActive) {
            const elapsed = Date.now() - clickStartTime;
            if (elapsed < clickDuration) {
                const intensity = 1 - (elapsed / clickDuration);
                drawHue = (this.hue + clickHueShift * intensity) % 360;
            }
        }
        
        const gradient = ctx.createLinearGradient(0, canvas.height, 0, canvas.height - this.height);
        gradient.addColorStop(0, `hsla(${drawHue}, 100%, 50%, 0.8)`);
        gradient.addColorStop(1, `hsla(${drawHue}, 100%, 70%, 0.4)`);
        
        ctx.fillStyle = gradient;
        ctx.fillRect(this.x, canvas.height - this.height, this.width - 2, this.height);
        
        ctx.shadowBlur = 15;
        ctx.shadowColor = `hsla(${drawHue}, 100%, 50%, 0.5)`;
        ctx.fillRect(this.x, canvas.height - this.height, this.width - 2, this.height);
        ctx.shadowBlur = 0;
    }
}

class SpiralParticle {
    constructor(angle, radius, speed, hue) {
        this.angle = angle;
        this.radius = radius;
        this.speed = speed;
        this.hue = hue;
        this.life = 1.0;
        this.decay = 0.005;
        this.size = 2 + Math.random() * 3;
        this.spiralSpeed = 0.05 + Math.random() * 0.1;
    }
    
    update() {
        this.angle += this.spiralSpeed * settings.speed;
        this.radius += this.speed;
        this.life -= this.decay;
    }
    
    draw() {
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const x = centerX + Math.cos(this.angle) * this.radius;
        const y = centerY + Math.sin(this.angle) * this.radius;
        
        let drawHue = this.hue;
        if (clickEffectActive) {
            const elapsed = Date.now() - clickStartTime;
            if (elapsed < clickDuration) {
                const intensity = 1 - (elapsed / clickDuration);
                drawHue = (this.hue + clickHueShift * intensity) % 360;
            }
        }
        
        ctx.fillStyle = `hsla(${drawHue}, 100%, 50%, ${this.life})`;
        ctx.fillRect(x, y, this.size, this.size);
    }
}

function initWaveArray() {
    const arr = [];
    for (let i = 0; i < canvas.width + 50; i++) {
        arr.push({x: i, y: canvas.height / 2, targetY: canvas.height / 2});
    }
    return arr;
}

let sparks = [];
let bars = [];
let spiralParticles = [];
let psychedelicParticles = [];  // FOR PSYCHEDELIC FACE ONLY
let flowerParticles = [];       // FOR FLOWER BLOOM ONLY
let wavePoints = initWaveArray();
let waveOffset = 0;
let emitterAngle = 0;
let currentHue = 0;
let lastBass = 0;

// ========== EXISTING VISUAL MODES (0-4) ==========

function animateFountain() {
    if (settings.colorCycleSpeed > 0) {
        currentHue += settings.colorCycleSpeed * 0.1;
        if (currentHue >= 360) currentHue -= 360;
    }
    
    const bassHit = audioData.bass > 0.3 && audioData.bass > lastBass + 0.1;
    if (bassHit) {
        currentHue = Math.random() * 360;
    }
    lastBass = audioData.bass;
    
    const speedMultiplier = 1 + (audioData.treble * 2.0);
    const baseParticles = settings.density;
    const audioParticles = Math.floor(audioData.mid * settings.density * 2);
    const totalParticles = baseParticles + audioParticles;
    
    if (audioData.bass > 0.3 && settings.bassExplosion > 0) {
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const explosionForce = audioData.bass * settings.bassExplosion * 0.8;
        
        sparks.forEach(spark => {
            spark.applyBassExplosion(centerX, centerY, explosionForce);
        });
    }
    
    emitterAngle += 0.03 * settings.speed * speedMultiplier;
    
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const orbitRadius = Math.min(canvas.width, canvas.height) * 0.25;
    
    const emitX = centerX + Math.cos(emitterAngle) * orbitRadius;
    const emitY = centerY + Math.sin(emitterAngle) * orbitRadius;
    
    let hue = (180 + currentHue) % 360;
    if (clickEffectActive) {
        const elapsed = Date.now() - clickStartTime;
        if (elapsed < clickDuration) {
            const intensity = 1 - (elapsed / clickDuration);
            hue = (hue + clickHueShift * intensity) % 360;
        }
    }
    
    ctx.shadowBlur = 30;
    ctx.shadowColor = `hsla(${hue}, 100%, 50%, 0.8)`;
    ctx.fillStyle = `hsla(${hue}, 100%, 70%, 0.6)`;
    ctx.beginPath();
    ctx.arc(emitX, emitY, 5 + audioData.bass * 10, 0, Math.PI * 2);
    ctx.fill();
    
    for (let i = 0; i < totalParticles; i++) {
        const spreadAngle = (Math.random() - 0.5) * Math.PI * 0.5;
        const sparkAngle = emitterAngle + Math.PI + spreadAngle;
        
        const baseSpeed = 2 + Math.random() * 3;
        const audioBoost = 1 + audioData.bass * settings.bassSensitivity * 0.5;
        const speed = baseSpeed * settings.speed * 0.3 * audioBoost;
        
        const colorVariation = (i / totalParticles) * 60;
        const sparkColor = (180 + colorVariation) % 360;
        
        sparks.push(new Spark(emitX, emitY, sparkAngle, speed, sparkColor));
    }
    
    ctx.shadowBlur = 0;
    for (let i = sparks.length - 1; i >= 0; i--) {
        const spark = sparks[i];
        spark.update();
        spark.draw();
        
        if (spark.life <= 0) {
            sparks.splice(i, 1);
        }
    }
}

function animateRadialBurst() {
    if (settings.colorCycleSpeed > 0) {
        currentHue += settings.colorCycleSpeed * 0.1;
        if (currentHue >= 360) currentHue -= 360;
    }
    
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    
    const pulseSize = 10 + audioData.bass * 40 + audioData.overall * 20;
    ctx.shadowBlur = 40;
    ctx.shadowColor = `hsla(${currentHue}, 100%, 50%, 0.8)`;
    ctx.fillStyle = `hsla(${currentHue}, 100%, 70%, 0.6)`;
    ctx.beginPath();
    ctx.arc(centerX, centerY, pulseSize, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    
    const shouldEmit = audioData.overall > 0.1;
    const particleCount = Math.floor(settings.density * (1 + audioData.bass * 3));
    
    if (shouldEmit) {
        for (let i = 0; i < particleCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const speed = (2 + Math.random() * 4) * settings.speed * (1 + audioData.bass * 2);
            const hue = (currentHue + Math.random() * 60 - 30) % 360;
            
            sparks.push(new Spark(centerX, centerY, angle, speed, hue));
        }
    }
    
    for (let i = sparks.length - 1; i >= 0; i--) {
        const spark = sparks[i];
        spark.update();
        spark.draw();
        
        if (spark.life <= 0 || spark.x < 0 || spark.x > canvas.width || spark.y < 0 || spark.y > canvas.height) {
            sparks.splice(i, 1);
        }
    }
}

function animateEqualizer() {
    const numBars = 32;
    
    if (bars.length !== numBars) {
        bars = [];
        const barWidth = canvas.width / numBars;
        for (let i = 0; i < numBars; i++) {
            bars.push(new EqualizerBar(i * barWidth, i, numBars));
        }
    }
    
    const magnitudes = [];
    for (let i = 0; i < numBars; i++) {
        const t = i / numBars;
        let mag = 0;
        
        if (t < 0.3) {
            mag = audioData.bass * (0.5 + Math.random() * 0.5);
        } else if (t < 0.7) {
            mag = audioData.mid * (0.5 + Math.random() * 0.5);
        } else {
            mag = audioData.treble * (0.5 + Math.random() * 0.5);
        }
        
        magnitudes.push(mag * settings.bassSensitivity);
    }
    
    const barWidth = canvas.width / numBars;
    bars.forEach((bar, i) => {
        bar.update(magnitudes[i], barWidth);
        bar.draw();
    });
}

function animateSpiralVortex() {
    if (settings.colorCycleSpeed > 0) {
        currentHue += settings.colorCycleSpeed * 0.1;
        if (currentHue >= 360) currentHue -= 360;
    }
    
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    
    const pulseSize = 8 + audioData.overall * 15;
    ctx.shadowBlur = 30;
    ctx.shadowColor = `hsla(${currentHue}, 100%, 50%, 0.8)`;
    ctx.fillStyle = `hsla(${currentHue}, 100%, 70%, 0.6)`;
    ctx.beginPath();
    ctx.arc(centerX, centerY, pulseSize, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    
    const shouldEmit = audioData.overall > 0.05;
    if (shouldEmit) {
        const particleCount = Math.floor(settings.density * (1 + audioData.mid * 2));
        
        for (let i = 0; i < particleCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const speed = (0.5 + Math.random() * 1.5) * settings.speed;
            const hue = (currentHue + Math.random() * 120) % 360;
            
            spiralParticles.push(new SpiralParticle(angle, 5, speed, hue));
        }
    }
    
    for (let i = spiralParticles.length - 1; i >= 0; i--) {
        const particle = spiralParticles[i];
        particle.update();
        particle.draw();
        
        if (particle.life <= 0 || particle.radius > Math.max(canvas.width, canvas.height)) {
            spiralParticles.splice(i, 1);
        }
    }
}

function animateTravelingWave() {
    if (settings.colorCycleSpeed > 0) {
        currentHue += settings.colorCycleSpeed * 0.1;
        if (currentHue >= 360) currentHue -= 360;
    }
    
    const baseSpeed = settings.speed * 2;
    const tempoMultiplier = 1 + (audioData.treble * 0.5);
    const scrollSpeed = baseSpeed * tempoMultiplier;
    
    waveOffset += scrollSpeed;
    
    const amplitude = 50 + (audioData.overall * 150);
    const bassAmp = audioData.bass * 80;
    const midAmp = audioData.mid * 60;
    
    const centerY = canvas.height / 2;
    
    for (let i = 0; i < wavePoints.length - 1; i++) {
        wavePoints[i].targetY = wavePoints[i + 1].targetY;
        wavePoints[i].y += (wavePoints[i].targetY - wavePoints[i].y) * 0.3;
    }
    
    const lastPoint = wavePoints[wavePoints.length - 1];
    const freq = 0.05 * (1 + audioData.mid * 0.5);
    const time = Date.now() * 0.001;
    
    let newY = centerY;
    newY += Math.sin(time * freq * 2) * amplitude;
    newY += Math.sin(time * freq * 3 + 1) * (amplitude * 0.5);
    newY += bassAmp * Math.sin(time * 0.5);
    newY += midAmp * Math.sin(time * 2);
    
    lastPoint.targetY = newY;
    lastPoint.y += (lastPoint.targetY - lastPoint.y) * 0.3;
    
    let drawHue = currentHue;
    if (clickEffectActive) {
        const elapsed = Date.now() - clickStartTime;
        if (elapsed < clickDuration) {
            const intensity = 1 - (elapsed / clickDuration);
            drawHue = (currentHue + clickHueShift * intensity) % 360;
        }
    }
    
    const glowLayers = [
        {blur: 40, alpha: 0.2, width: 8},
        {blur: 20, alpha: 0.4, width: 5},
        {blur: 10, alpha: 0.6, width: 3},
        {blur: 0, alpha: 1.0, width: 2}
    ];
    
    glowLayers.forEach(layer => {
        ctx.shadowBlur = layer.blur;
        ctx.shadowColor = `hsla(${drawHue}, 100%, 50%, ${layer.alpha})`;
        ctx.strokeStyle = `hsla(${drawHue}, 100%, 60%, ${layer.alpha})`;
        ctx.lineWidth = layer.width;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        
        ctx.beginPath();
        for (let i = 0; i < wavePoints.length; i++) {
            const point = wavePoints[i];
            if (i === 0) {
                ctx.moveTo(point.x - waveOffset, point.y);
            } else {
                ctx.lineTo(point.x - waveOffset, point.y);
            }
        }
        ctx.stroke();
    });
    
    ctx.shadowBlur = 0;
    
    if (waveOffset > canvas.width) {
        waveOffset = 0;
    }
    
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, canvas.height / 2);
    ctx.lineTo(canvas.width, canvas.height / 2);
    ctx.stroke();
}

// ========== FLOWER BLOOM (MODE 5) ==========
// FLOWER PARTICLE CLASS - ORIGINAL KALEIDOSCOPE FLOWERS
class FlowerParticle {
    constructor(x, y, angle, speed, hue, size) {
        this.x = x;
        this.y = y;
        this.vx = Math.cos(angle) * speed;
        this.vy = Math.sin(angle) * speed;
        this.life = 1.0;
        this.decay = 0.003 + Math.random() * 0.007;
        this.hue = hue;
        this.size = size;
        this.rotation = Math.random() * Math.PI * 2;
        this.rotationSpeed = (Math.random() - 0.5) * 0.2;
    }
    
    update() {
        this.x += this.vx;
        this.y += this.vy;
        this.rotation += this.rotationSpeed;
        this.life -= this.decay;
        
        // Slight curve
        this.vx *= 0.99;
        this.vy *= 0.99;
    }
    
    draw() {
        let drawHue = this.hue;
        if (clickEffectActive) {
            const elapsed = Date.now() - clickStartTime;
            if (elapsed < clickDuration) {
                const intensity = 1 - (elapsed / clickDuration);
                drawHue = (this.hue + clickHueShift * intensity) % 360;
            }
        }
        
        ctx.save();
        ctx.translate(this.x, this.y);
        ctx.rotate(this.rotation);
        
        // Draw kaleidoscope-style flower shape (ORIGINAL FLOWER BLOOM)
        ctx.shadowBlur = 15;
        ctx.shadowColor = `hsla(${drawHue}, 100%, 50%, ${this.life * 0.8})`;
        
        // Draw flower petals (kaleidoscope effect)
        for (let i = 0; i < 6; i++) {
            ctx.rotate(Math.PI / 3);
            ctx.fillStyle = `hsla(${(drawHue + i * 20) % 360}, 100%, 50%, ${this.life * 0.6})`;
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(this.size, 0);
            ctx.lineTo(this.size * 0.8, this.size * 0.5);
            ctx.closePath();
            ctx.fill();
        }
        
        // Draw flower center
        ctx.fillStyle = `hsla(${drawHue}, 100%, 70%, ${this.life * 0.9})`;
        ctx.beginPath();
        ctx.arc(0, 0, this.size * 0.3, 0, Math.PI * 2);
        ctx.fill();
        
        ctx.shadowBlur = 0;
        ctx.restore();
    }
}

// FLOWER BLOOM FUNCTION - USES FLOWER PARTICLES ONLY
function animateFlowerBloom() {
    if (settings.colorCycleSpeed > 0) {
        currentHue += settings.colorCycleSpeed * 0.1;
        if (currentHue >= 360) currentHue -= 360;
    }
    
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    
    // Emit flower particles from center
    const shouldEmit = audioData.overall > 0.05;
    if (shouldEmit) {
        const particleCount = Math.floor(settings.density * 0.5 * (1 + audioData.bass * 3));
        
        for (let i = 0; i < particleCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const speed = (1 + Math.random() * 3) * settings.speed * (1 + audioData.mid * 2);
            
            // Rainbow spectrum shifting with audio
            const hue = (currentHue + Math.random() * 120 + audioData.treble * 60) % 360;
            const size = 3 + Math.random() * 8 + audioData.bass * 10;
            
            flowerParticles.push(new FlowerParticle(centerX, centerY, angle, speed, hue, size));
        }
    }
    
    // Add bass burst effect
    if (audioData.bass > 0.5) {
        for (let i = 0; i < 15; i++) {
            const angle = (Math.PI * 2 * i) / 15;
            const speed = 5 + audioData.bass * 10;
            const hue = (currentHue + i * 24) % 360;
            const size = 5 + audioData.bass * 12;
            
            flowerParticles.push(new FlowerParticle(centerX, centerY, angle, speed, hue, size));
        }
    }
    
    // Update and draw FLOWER particles
    for (let i = flowerParticles.length - 1; i >= 0; i--) {
        const particle = flowerParticles[i];
        particle.update();
        particle.draw();
        
        if (particle.life <= 0) {
            flowerParticles.splice(i, 1);
        }
    }
    
    // Draw center glow that pulses
    const glowSize = 20 + audioData.overall * 50 + audioData.bass * 80;
    ctx.shadowBlur = 60;
    ctx.shadowColor = `hsla(${currentHue}, 100%, 50%, ${audioData.overall})`;
    ctx.fillStyle = `hsla(${currentHue}, 100%, 70%, ${audioData.overall * 0.3})`;
    ctx.beginPath();
    ctx.arc(centerX, centerY, glowSize, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
}

// ========== PSYCHEDELIC FACE (MODE 6) ==========
// PSYCHEDELIC PARTICLE CLASS - PEACE/CROSS SYMBOLS
class PsychedelicParticle {
    constructor(x, y, angle, speed, hue, size, shapeType) {
        this.x = x;
        this.y = y;
        this.vx = Math.cos(angle) * speed;
        this.vy = Math.sin(angle) * speed;
        this.life = 1.0;
        this.decay = 0.003 + Math.random() * 0.007;
        this.hue = hue;
        this.size = size;
        this.rotation = Math.random() * Math.PI * 2;
        this.rotationSpeed = (Math.random() - 0.5) * 0.2;
        this.shapeType = shapeType || (Math.random() > 0.5 ? 'peace' : 'cross');
        this.pulse = 0;
        this.pulseSpeed = 0.05 + Math.random() * 0.1;
    }
    
    update() {
        this.x += this.vx;
        this.y += this.vy;
        this.rotation += this.rotationSpeed;
        this.life -= this.decay;
        this.pulse = Math.sin(Date.now() * 0.001 * this.pulseSpeed) * 0.3 + 0.7;
        
        // Slight curve
        this.vx *= 0.99;
        this.vy *= 0.99;
    }
    
    drawPeaceSign(ctx, drawHue, scale = 1.0) {
        const radius = this.size * 0.5 * scale;
        const pulseScale = this.pulse;
        
        // Draw outer circle with pulse effect
        ctx.beginPath();
        ctx.arc(0, 0, radius * pulseScale, 0, Math.PI * 2);
        ctx.strokeStyle = `hsla(${drawHue}, 100%, 60%, ${this.life * 0.8})`;
        ctx.lineWidth = 2 * pulseScale;
        ctx.stroke();
        
        // Draw peace sign lines
        ctx.beginPath();
        // Center vertical line
        ctx.moveTo(0, -radius * 0.7 * pulseScale);
        ctx.lineTo(0, radius * 0.7 * pulseScale);
        
        // Left angled line
        ctx.moveTo(-radius * 0.3 * pulseScale, -radius * 0.3 * pulseScale);
        ctx.lineTo(0, 0);
        ctx.lineTo(radius * 0.3 * pulseScale, -radius * 0.3 * pulseScale);
        
        ctx.stroke();
    }
    
    drawCross(ctx, drawHue, scale = 1.0) {
        const size = this.size * 0.8 * scale;
        const pulseScale = this.pulse;
        
        // Draw basic cross
        ctx.beginPath();
        // Vertical line
        ctx.moveTo(0, -size * pulseScale);
        ctx.lineTo(0, size * pulseScale);
        // Horizontal line
        ctx.moveTo(-size * pulseScale, 0);
        ctx.lineTo(size * pulseScale, 0);
        
        ctx.strokeStyle = `hsla(${drawHue}, 100%, 60%, ${this.life * 0.8})`;
        ctx.lineWidth = 2 * pulseScale;
        ctx.stroke();
        
        // Add decorative circles at ends
        ['-size', 'size', '0,-size', '0,size'].forEach(pos => {
            ctx.beginPath();
            const [x, y] = pos.split(',').map(v => eval(v) * pulseScale);
            ctx.arc(x, y, size * 0.1, 0, Math.PI * 2);
            ctx.fillStyle = `hsla(${drawHue}, 100%, 50%, ${this.life * 0.6})`;
            ctx.fill();
        });
    }
    
    drawBoth(ctx, drawHue) {
        // Draw peace sign and cross combined
        this.drawPeaceSign(ctx, drawHue, 0.6);
        this.drawCross(ctx, (drawHue + 60) % 360, 0.4);
    }
    
    draw() {
        let drawHue = this.hue;
        if (clickEffectActive) {
            const elapsed = Date.now() - clickStartTime;
            if (elapsed < clickDuration) {
                const intensity = 1 - (elapsed / clickDuration);
                drawHue = (this.hue + clickHueShift * intensity) % 360;
            }
        }
        
        ctx.save();
        ctx.translate(this.x, this.y);
        ctx.rotate(this.rotation);
        
        ctx.shadowBlur = 20;
        ctx.shadowColor = `hsla(${drawHue}, 100%, 50%, ${this.life * 0.5})`;
        
        switch(this.shapeType) {
            case 'peace':
                this.drawPeaceSign(ctx, drawHue);
                break;
            case 'cross':
                this.drawCross(ctx, drawHue);
                break;
            case 'both':
                this.drawBoth(ctx, drawHue);
                break;
            default:
                this.drawPeaceSign(ctx, drawHue);
        }
        
        ctx.shadowBlur = 0;
        ctx.restore();
    }
}

// CREATE SYMBOL PARTICLE FUNCTION
function createSymbolParticle(x, y, angle, speed, hue, size) {
    // Randomly choose between peace sign, cross, or occasionally both
    let shapeType;
    const rand = Math.random();
    
    if (rand < 0.45) {
        shapeType = 'peace';
    } else if (rand < 0.9) {
        shapeType = 'cross';
    } else {
        shapeType = 'both'; // Special mixed symbol
    }
    
    return new PsychedelicParticle(x, y, angle, speed, hue, size, shapeType);
}

let faceImage = null;
let faceImageLoaded = false;

// Load face image from base64
function loadFaceImage() {
    faceImage = new Image();
    faceImage.onload = function() {
        faceImageLoaded = true;
        console.log('Face image loaded successfully');
    };
    faceImage.onerror = function() {
        console.error('Failed to load face image');
    };
    faceImage.src = 'data:image/jpeg;base64,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';
}

loadFaceImage();

// PSYCHEDELIC FACE FUNCTION - USES PSYCHEDELIC PARTICLES ONLY
function animatePsychedelicFace() {
    if (settings.colorCycleSpeed > 0) {
        currentHue += settings.colorCycleSpeed * 0.1;
        if (currentHue >= 360) currentHue -= 360;
    }
    
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    
    // Clear with a darker background to make face more visible
    ctx.fillStyle = 'rgba(0, 0, 0, 0.1)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Draw face image if loaded
    if (faceImageLoaded && faceImage) {
        const scale = Math.min(canvas.width / faceImage.width, canvas.height / faceImage.height) * 0.7;
        const imgWidth = faceImage.width * scale;
        const imgHeight = faceImage.height * scale;
        const imgX = centerX - imgWidth / 2;
        const imgY = centerY - imgHeight / 2;
        
        // Save context state
        ctx.save();
        
        // Apply psychedelic effects - but keep the image static
        const hueRotation = currentHue;
        const saturation = 150 + (audioData.bass * 100);
        const brightness = 100 + (audioData.overall * 50);
        
        // Apply color filter (keep colors changing but image static)
        ctx.filter = `hue-rotate(${hueRotation}deg) saturate(${saturation}%) brightness(${brightness}%)`;
        
        // Add glow effect (this can still pulse with audio)
        ctx.shadowBlur = 40 + (audioData.bass * 100);
        ctx.shadowColor = `hsla(${currentHue}, 100%, 50%, ${0.5 + audioData.overall * 0.3})`;
        
        // Draw the face with psychedelic effects - STATIC SIZE
        ctx.globalAlpha = 0.9 + (audioData.bass * 0.1);
        ctx.drawImage(faceImage, imgX, imgY, imgWidth, imgHeight);
        
        // Restore context
        ctx.restore();
        
        // Add a subtle outline glow (can pulse with audio)
        ctx.shadowBlur = 20 + (audioData.bass * 40);
        ctx.shadowColor = `hsla(${currentHue}, 100%, 60%, 0.5)`;
        ctx.strokeStyle = `hsla(${currentHue}, 80%, 50%, 0.3)`;
        ctx.lineWidth = 3 + (audioData.bass * 5);
        ctx.strokeRect(imgX, imgY, imgWidth, imgHeight);
        ctx.shadowBlur = 0;
    }
    
    // Emit particles AROUND the face (not from center)
    const shouldEmit = audioData.overall > 0.05;
    if (shouldEmit) {
        const particleCount = Math.floor(settings.density * 0.2 * (1 + audioData.bass * 3));
        
        for (let i = 0; i < particleCount; i++) {
            // Create particles around the face perimeter, not from center
            const angle = Math.random() * Math.PI * 2;
            
            // Calculate distance from center (face edge)
            const faceRadius = Math.min(canvas.width, canvas.height) * 0.25;
            const distanceFromCenter = faceRadius + (Math.random() * 30);
            
            const x = centerX + Math.cos(angle) * distanceFromCenter;
            const y = centerY + Math.sin(angle) * distanceFromCenter;
            
            // Particles move outward from face
            const speed = (0.5 + Math.random() * 1.5) * settings.speed;
            const hue = (currentHue + Math.random() * 120) % 360;
            const size = 2 + Math.random() * 6 + (audioData.bass * 8);
            
            // Add some randomness to angle to create radiation effect
            const particleAngle = angle + (Math.random() - 0.5) * 0.5;
            
            psychedelicParticles.push(createSymbolParticle(x, y, particleAngle, speed, hue, size));
        }
    }
    
    // Update and draw PSYCHEDELIC particles
    for (let i = psychedelicParticles.length - 1; i >= 0; i--) {
        const particle = psychedelicParticles[i];
        particle.update();
        particle.draw();
        
        if (particle.life <= 0) {
            psychedelicParticles.splice(i, 1);
        }
    }
    
    // Add center glow that pulses with audio
    const glowSize = 5 + audioData.bass * 20;
    ctx.shadowBlur = 30;
    ctx.shadowColor = `hsla(${currentHue}, 100%, 50%, ${0.3 + audioData.bass * 0.5})`;
    ctx.fillStyle = `hsla(${currentHue}, 100%, 70%, ${0.2})`;
    ctx.beginPath();
    ctx.arc(centerX, centerY, glowSize, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
}

// ========== MAIN ANIMATION LOOP ==========
function animate() {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.08)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    if (settings.randomMode) {
        if (!window.lastRandomChange) window.lastRandomChange = Date.now();
        if (Date.now() - window.lastRandomChange > 3000) {
            const randomProp = ['density', 'speed', 'bassSensitivity', 'colorCycleSpeed', 'bassExplosion'][Math.floor(Math.random() * 5)];
            
            if (randomProp === 'density') settings.density = 1 + Math.floor(Math.random() * 7);
            else if (randomProp === 'speed') settings.speed = 0.1 + Math.random() * 4.9;
            else if (randomProp === 'bassSensitivity') settings.bassSensitivity = Math.random() * 5;
            else if (randomProp === 'colorCycleSpeed') settings.colorCycleSpeed = Math.floor(Math.random() * 100);
            else if (randomProp === 'bassExplosion') settings.bassExplosion = Math.random() * 5;
            
            window.lastRandomChange = Date.now();
        }
    }

    if (settings.randomBackgrounds) {
        if (!window.lastBackgroundChange) window.lastBackgroundChange = Date.now();
        if (Date.now() - window.lastBackgroundChange > 10000) {
            const currentMode = settings.visualMode || 0;
            let nextMode = Math.floor(Math.random() * 7);
            if (nextMode === currentMode) nextMode = (nextMode + 1) % 7;
            settings.visualMode = nextMode;
            sparks = [];
            bars = [];
            spiralParticles = [];
            psychedelicParticles = [];
            flowerParticles = [];
            wavePoints = initWaveArray();
            window.lastBackgroundChange = Date.now();
        }
    }

    frameCounter++;
    const now = performance.now();
    if (now - lastFpsTime >= 500) {
        systemStats.fps = Math.round(frameCounter * 1000 / (now - lastFpsTime));
        frameCounter = 0;
        lastFpsTime = now;
        const fpsValue = document.getElementById('fpsValue');
        if (fpsValue) fpsValue.textContent = systemStats.fps;
    }
    
    const mode = settings.visualMode || 0;
    
    switch(mode) {
        case 0: animateFountain(); break;
        case 1: animateRadialBurst(); break;
        case 2: animateEqualizer(); break;
        case 3: animateSpiralVortex(); break;
        case 4: animateTravelingWave(); break;
        case 5: animateFlowerBloom(); break;      // Uses FlowerParticle class ONLY
        case 6: animatePsychedelicFace(); break;  // Uses PsychedelicParticle class ONLY
        default: animateFountain();
    }
    
    requestAnimationFrame(animate);
}

applyOverlayMode();
animate();
"""
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #000; overflow: hidden; cursor: pointer; }}
        #canvas {{ display: block; background: #000; }}
        #audioDebug {{
            position: absolute; top: 10px; left: 10px;
            background: rgba(0, 0, 0, 0.7); color: #0ff;
            padding: 10px; font-family: monospace; font-size: 11px;
            border-radius: 5px; pointer-events: none; opacity: 0.85;
            min-width: 185px;
        }}
        #deviceStatus {{
            position: absolute; bottom: 10px; left: 10px;
            background: rgba(0, 0, 0, 0.7); color: #888;
            padding: 8px 12px; font-family: monospace; font-size: 10px;
            border-radius: 5px; pointer-events: none; opacity: 0.8;
            display: none;
        }}
        #deviceStatus.active {{ color: #0f0; }}
        #deviceStatus.error {{ color: #f00; }}
        .debug-bar {{ display: flex; align-items: center; margin: 3px 0; }}
        .debug-label {{ width: 60px; color: #0ff; }}
        .debug-meter {{
            flex: 1; height: 8px; background: #222;
            border-radius: 4px; overflow: hidden; margin-left: 5px;
        }}
        .debug-fill {{ height: 100%; transition: width 0.05s; }}
        .debug-fill.bass {{ background: #f0f; }}
        .debug-fill.mid {{ background: #0ff; }}
        .debug-fill.treble {{ background: #ff0; }}
        .debug-fill.cpu {{ background: #4CAF50; }}
        .debug-fill.gpu {{ background: #FF9800; }}
        .debug-value {{ width: 40px; text-align: right; margin-left: 5px; color: #0ff; }}
        .stat-line {{ display: flex; justify-content: space-between; margin: 3px 0; color: #0ff; }}
    </style>
</head>
<body>
    <canvas id="canvas"></canvas>
    <div id="deviceStatus"></div>
    <div id="audioDebug">
        <div id="audioPanel">
            <div class="debug-bar">
                <span class="debug-label">Bass:</span>
                <div class="debug-meter"><div class="debug-fill bass" id="bassBar" style="width: 0%"></div></div>
                <span class="debug-value" id="bassValue">0.00</span>
            </div>
            <div class="debug-bar">
                <span class="debug-label">Mid:</span>
                <div class="debug-meter"><div class="debug-fill mid" id="midBar" style="width: 0%"></div></div>
                <span class="debug-value" id="midValue">0.00</span>
            </div>
            <div class="debug-bar">
                <span class="debug-label">Treble:</span>
                <div class="debug-meter"><div class="debug-fill treble" id="trebleBar" style="width: 0%"></div></div>
                <span class="debug-value" id="trebleValue">0.00</span>
            </div>
        </div>
        <div id="systemPanel" style="display: none;">
            <div class="debug-bar">
                <span class="debug-label">CPU:</span>
                <div class="debug-meter"><div class="debug-fill cpu" id="cpuBar" style="width: 0%"></div></div>
                <span class="debug-value" id="cpuValue">0%</span>
            </div>
            <div class="debug-bar">
                <span class="debug-label">GPU:</span>
                <div class="debug-meter"><div class="debug-fill gpu" id="gpuBar" style="width: 0%"></div></div>
                <span class="debug-value" id="gpuValue">--</span>
            </div>
            <div class="stat-line"><span>FPS:</span><span id="fpsValue">0</span></div>
        </div>
    </div>
    <script>{js_code}</script>
</body>
</html>"""
        
        return html
    
    def get_audio_devices(self):
        print("\n" + "="*60)
        print("GETTING AUDIO DEVICES")
        print("="*60)
        devices = []
        try:
            p = pyaudio.PyAudio()
            
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                log_visualizer(f"WASAPI host API index: {wasapi_info['index']}")
            except OSError:
                log_visualizer("WASAPI not available")
                p.terminate()
                return devices
            
            loopback_devices = list(p.get_loopback_device_info_generator())
            log_visualizer(f"Found {len(loopback_devices)} loopback devices")
            
            for i, loopback in enumerate(loopback_devices):
                channels = int(loopback['maxInputChannels'])
                
                if channels > 0:
                    devices.append({
                        'index': loopback['index'],
                        'name': loopback['name'],
                        'channels': channels,
                        'rate': int(loopback['defaultSampleRate'])
                    })
                    log_visualizer(
                        f"Loopback device ready: index={loopback['index']} "
                        f"name={loopback['name']} channels={channels} rate={int(loopback['defaultSampleRate'])}"
                    )
            
            p.terminate()
        except Exception as e:
            log_visualizer(f"Error getting audio devices: {e}")
            
        return devices
    
    def try_audio_devices_async(self):
        search_thread = threading.Thread(target=self.try_audio_devices, daemon=True)
        search_thread.start()
    
    def try_audio_devices(self):
        devices = self.get_audio_devices()
        
        if not devices:
            self.device_error.emit("No audio loopback devices found.")
            log_visualizer("No loopback devices found during startup")
            return
        
        saved_device_name = self.config.get('selectedDeviceName')
        
        if saved_device_name:
            for device in devices:
                if device['name'] == saved_device_name:
                    self.selected_device_index = device['index']
                    
                    if self.quick_test_audio_device():
                        self.device_working = True
                        log_visualizer(f"Using saved audio device: {device['name']} ({device['index']})")
                        self.device_success.emit(f"Audio device: {device['name']}")
                        self.start_audio_capture()
                        return
        
        for device in devices:
            self.selected_device_index = device['index']
            
            if self.quick_test_audio_device():
                self.device_working = True
                self.config['selectedDeviceName'] = device['name']
                self.config['selectedDeviceIndex'] = device['index']
                log_visualizer(f"Using fallback audio device: {device['name']} ({device['index']})")
                
                try:
                    with open(CONFIG_PATH, 'w') as f:
                        json.dump(self.config, f, indent=2)
                except:
                    pass
                
                self.device_success.emit(f"Audio device: {device['name']}")
                self.start_audio_capture()
                return

        log_visualizer("Loopback devices were found but none could be opened successfully")
        self.device_error.emit("Audio loopback device could not be opened.")
    
    def quick_test_audio_device(self):
        try:
            p = pyaudio.PyAudio()
            device_info = p.get_device_info_by_index(self.selected_device_index)
            
            CHANNELS = int(device_info["maxInputChannels"])
            if CHANNELS == 0:
                p.terminate()
                return False
            
            stream = p.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=int(device_info["defaultSampleRate"]),
                input=True,
                frames_per_buffer=256,
                input_device_index=self.selected_device_index
            )
            
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            log_visualizer(
                f"Device probe succeeded: index={self.selected_device_index} "
                f"name={device_info.get('name')}"
            )
            return True
        except Exception as exc:
            log_visualizer(f"Device probe failed for index={self.selected_device_index}: {exc}")
            return False
        
    def start_audio_capture(self):
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_stop_event.set()
            self.audio_thread.join(timeout=2)
        
        self.audio_queue = queue.Queue()
        self.audio_stop_event.clear()
        self.audio_thread = threading.Thread(target=self.audio_capture_thread, daemon=True)
        self.audio_thread.start()
        self.device_working = True
        log_visualizer(f"Started audio capture thread for device index={self.selected_device_index}")
        
    def on_device_changed(self, device_index):
        devices = self.get_audio_devices()
        device_name = ""
        for device in devices:
            if device['index'] == device_index:
                device_name = device['name']
                break
        
        if not device_name:
            return
        
        self.selected_device_index = device_index
        self.config['selectedDeviceName'] = device_name
        self.config['selectedDeviceIndex'] = device_index
        
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(self.config, f, indent=2)
        except:
            pass
        
        self.start_audio_capture()
        self.device_success.emit(f"Audio device: {device_name}")

    def calculate_audio_levels(self, audio_float, rate):
        if len(audio_float) < 8:
            return {'bass': 0.0, 'mid': 0.0, 'treble': 0.0, 'overall': 0.0, 'rms': 0.0, 'bpm': self.current_bpm}

        window = np.hanning(len(audio_float))
        audio_windowed = audio_float * window
        magnitudes = np.abs(np.fft.rfft(audio_windowed)) / max(1, len(audio_windowed))
        freqs = np.fft.rfftfreq(len(audio_windowed), d=1.0 / rate)

        sensitivity_factor = max(0.05, float(self.config.get('sensitivity', 100)) / 100.0)
        bands = {
            'bass': (20, 180, 85.0),
            'mid': (180, 2200, 115.0),
            'treble': (2200, min(10000, rate / 2), 165.0),
        }

        rms = float(np.sqrt(np.mean(audio_float ** 2)))
        rms_db = 20 * math.log10(rms + 1e-10)
        rms_norm = max(0.0, min(1.0, (rms_db + 55) / 45))
        noise_gate = min(1.0, rms_norm * 4.0)

        levels = {}
        for band_name, (low_freq, high_freq, scale) in bands.items():
            mask = (freqs >= low_freq) & (freqs < high_freq)
            if not np.any(mask):
                raw_level = 0.0
            else:
                band_energy = float(np.sqrt(np.mean(magnitudes[mask] ** 2)))
                raw_level = math.log1p(band_energy * scale * sensitivity_factor)

            decayed_peak = max(0.05, self.band_peaks.get(band_name, 0.05) * 0.995)
            peak = max(decayed_peak, raw_level)
            self.band_peaks[band_name] = peak

            normalized = max(0.0, min(1.0, raw_level / (peak * 1.12 + 1e-9)))
            normalized *= noise_gate

            previous = self.band_smooth.get(band_name, 0.0)
            alpha = 0.55 if normalized > previous else 0.16
            smoothed = previous + (normalized - previous) * alpha
            self.band_smooth[band_name] = smoothed
            levels[band_name] = float(max(0.0, min(1.0, smoothed)))

        overall = max(
            (levels['bass'] * 1.15 + levels['mid'] + levels['treble'] * 0.9) / 3.05,
            rms_norm * 0.55
        )

        return {
            'bass': levels['bass'],
            'mid': levels['mid'],
            'treble': levels['treble'],
            'overall': float(max(0.0, min(1.0, overall))),
            'rms': float(rms_norm),
            'bpm': self.current_bpm
        }
        
    def audio_capture_thread(self):
        stream = None
        p = None
        try:
            p = pyaudio.PyAudio()
            device_info = p.get_device_info_by_index(self.selected_device_index)
            log_visualizer(f"Opening audio capture stream for {device_info.get('name')} ({device_info.get('index')})")
            
            CHANNELS = int(device_info["maxInputChannels"])
            if CHANNELS == 0:
                log_visualizer("Audio capture aborted because the selected device has zero input channels")
                return
            
            if CHANNELS > 2:
                CHANNELS = 2
            
            CHUNK = 1024
            FORMAT = pyaudio.paInt16
            RATE = int(device_info["defaultSampleRate"])
            
            if RATE == 0:
                RATE = 44100
            
            stream = p.open(format=FORMAT,
                          channels=CHANNELS,
                          rate=RATE,
                          input=True,
                          frames_per_buffer=CHUNK,
                          input_device_index=device_info["index"])
            
            frame_count = 0
            
            while not self.audio_stop_event.is_set():
                try:
                    frame_count += 1
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_int = np.frombuffer(data, dtype=np.int16)
                    
                    if CHANNELS == 2:
                        audio_int = audio_int.reshape(-1, 2)
                        audio_int = audio_int.mean(axis=1).astype(np.int16)
                    
                    audio_float = audio_int.astype(np.float32) / 32768.0
                    levels = self.calculate_audio_levels(audio_float, RATE)
                    
                    with self.audio_data_lock:
                        self.audio_data = levels
                    
                except Exception as e:
                    if not self.audio_stop_event.is_set():
                        log_visualizer(f"Audio stream read error: {e}")
                        continue
                    else:
                        break
                    
        except Exception as exc:
            log_visualizer(f"Audio capture startup failed: {exc}")
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass
            if p:
                p.terminate()
            
    def on_load_finished(self, success):
        if success:
            self.js_ready = True
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
            if self.device_working:
                self.device_success.emit(f"Audio device connected")

    def update_device_status(self, message, status):
        if self.js_ready:
            self.web_view.page().runJavaScript(
                f"window.updateDeviceStatus({json.dumps(message)}, {json.dumps(status)})"
            )

    def push_system_stats(self):
        if psutil is not None:
            try:
                self.system_stats['cpu'] = float(psutil.cpu_percent(interval=None))
            except Exception:
                self.system_stats['cpu'] = 0.0
        else:
            self.system_stats['cpu'] = 0.0

        now = time.time()
        if self.gpu_available is not False and now - self.last_gpu_poll >= 2.0:
            self.last_gpu_poll = now
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu",
                        "--format=csv,noheader,nounits"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                )
                if result.returncode == 0:
                    first_value = result.stdout.strip().splitlines()[0].strip()
                    self.system_stats['gpu'] = float(first_value)
                    self.gpu_available = True
                else:
                    self.system_stats['gpu'] = None
                    self.gpu_available = False
            except Exception:
                self.system_stats['gpu'] = None
                self.gpu_available = False

        if self.js_ready:
            stats_json = json.dumps(self.system_stats)
            self.web_view.page().runJavaScript(f"window.updateSystemStats({stats_json})")
            
    def push_audio_data(self):
        if not self.js_ready:
            return
        
        with self.audio_data_lock:
            audio_dict = {
                'bass': float(self.audio_data['bass']),
                'mid': float(self.audio_data['mid']),
                'treble': float(self.audio_data['treble']),
                'overall': float(self.audio_data.get('overall', 0)),
                'rms': float(self.audio_data.get('rms', 0)),
                'bpm': float(self.audio_data.get('bpm', 120))
            }
        
        audio_json = json.dumps(audio_dict)
        self.web_view.page().runJavaScript(f"window.updateAudio({audio_json})")
        
    def update_settings(self, new_config):
        self.config = new_config
        if self.js_ready:
            config_json = json.dumps(new_config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
    
    def closeEvent(self, event):
        # Clean up state file
        try:
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
        except:
            pass
        
        self.audio_stop_event.set()
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1)
        event.accept()
    
    def mousePressEvent(self, event):
        """Handle left click to cycle through visual modes"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if click is on the web_view (not on buttons)
            click_pos = event.pos()
            if self.web_view.geometry().contains(click_pos):
                # Cycle to next visual mode
                current_mode = self.config.get('visualMode', 0)
                next_mode = (current_mode + 1) % 7  # 7 visual modes total
                self.switch_visual_mode(next_mode)
        
        super().mousePressEvent(event)
    
    def toggle_click_through(self, enabled):
        """Toggle click-through mode (called from tray menu)"""
        self.click_through_mode = enabled
        
        # Reset to base flags
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        
        if enabled:
            self.setWindowOpacity(0.3)
            flags |= Qt.WindowType.WindowTransparentForInput
            self.click_through_timer.start(CLICK_THROUGH_TIMEOUT_MS)
        else:
            self.setWindowOpacity(1.0)
            self.click_through_timer.stop()
        
        self.setWindowFlags(flags)
        self.show()
        self.write_state_file()

    def disable_click_through_timeout(self):
        if self.click_through_mode:
            self.toggle_click_through(False)
    
    def get_visual_mode(self):
        """Get current visual mode index"""
        return self.config.get('visualMode', 0)
    
    def is_random_mode(self):
        """Check if random mode is enabled"""
        return self.config.get('randomMode', False)
    
    def write_state_file(self):
        """Write current state to file for tray to read"""
        try:
            state = {
                'running': True,
                'click_through': self.click_through_mode,
                'visual_mode': self.config.get('visualMode', 0),
                'random_mode': self.config.get('randomMode', False),
                'random_backgrounds': self.config.get('randomBackgrounds', False),
                'overlay_mode': self.config.get('overlayMode', 'audio')
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except:
            pass
    
    def check_state_file(self):
        """Check for commands from tray"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                
                # Check for command
                if 'command' in state and state['command'] == 'toggle_click_through':
                    enabled = state.get('enabled', False)
                    self.toggle_click_through(enabled)
                
                # Clear the command
                if 'command' in state:
                    state.pop('command', None)
                    state.pop('mode', None)
                    state.pop('enabled', None)
                    with open(self.state_file, 'w') as f:
                        json.dump(state, f)
        except:
            pass


def load_config():
    default_config = {
        'visualMode': 0,
        'density': 3,
        'speed': 1.0,
        'bassSensitivity': 1.5,
        'colorCycleSpeed': 10,
        'bassExplosion': 1.0,
        'sensitivity': 100,
        'randomMode': True,
        'randomBackgrounds': False,
        'overlayMode': 'audio',
        'selectedDeviceIndex': None,
        'emitterGlowSize': 3
    }
    
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                loaded_config = json.load(f)
            
            for key in default_config:
                if key not in loaded_config:
                    loaded_config[key] = default_config[key]
            
            return loaded_config
    except:
        pass
    
    return default_config


def main():
    print("\n" + "="*60)
    print("STARTING AUDIO VISUALIZER (7 Modes)")
    print("="*60)
    log_visualizer("Launching visualizer")
    
    app = QApplication(sys.argv)
    config = load_config()
    window = VisualizerWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
