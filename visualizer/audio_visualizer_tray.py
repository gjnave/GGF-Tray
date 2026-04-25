import sys
import json
import os
import numpy as np
import math
import multiprocessing
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, 
                             QVBoxLayout, QLabel, QSlider, QPushButton, QColorDialog,
                             QComboBox, QHBoxLayout, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, QUrl, QRect, pyqtSignal
from PyQt6.QtGui import QIcon, QColor, QPixmap, QPainter
from PyQt6.QtWebEngineWidgets import QWebEngineView
import pyaudiowpatch as pyaudio
import threading
import queue


class SettingsWindow(QWidget):
    """Settings window for visualizer configuration"""
    settings_changed = pyqtSignal(dict)
    audio_device_changed = pyqtSignal(int)
    
    def __init__(self, config, audio_devices, current_device_index):
        super().__init__()
        self.config = config.copy()
        self.audio_devices = audio_devices
        self.current_device_index = current_device_index
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Visualizer Settings")
        self.setFixedWidth(400)
        
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
        self.mode_combo.setCurrentIndex(self.config.get('visualMode', 0))
        layout.addWidget(self.mode_combo)
        
        # Density slider
        layout.addWidget(QLabel("Particle Density:"))
        self.density_slider = QSlider(Qt.Orientation.Horizontal)
        self.density_slider.setMinimum(1)
        self.density_slider.setMaximum(20)
        self.density_slider.setValue(self.config.get('density', 5))
        self.density_label = QLabel(str(self.config.get('density', 5)))
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
        layout.addWidget(QLabel(""))  # Spacer
        self.random_checkbox = QCheckBox("Random Mode (auto-change settings every 3 seconds)")
        self.random_checkbox.setChecked(self.config.get('randomMode', False))
        layout.addWidget(self.random_checkbox)
        
        # Save and close buttons
        btn_layout = QVBoxLayout()
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        
    def on_device_changed(self, index):
        """Handle audio device change"""
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
        
        self.settings_changed.emit(self.config)
        
        # Save to file
        try:
            with open('visualizer_config.json', 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
        
        self.close()


class VisualizerWindow(QMainWindow):
    """Main visualizer window - standalone without tray"""
    device_error = pyqtSignal(str)  # Signal when device fails
    device_success = pyqtSignal(str)  # Signal when device works
    
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
        
        # Auto-gain control
        self.auto_gain = 1.0
        self.gain_target = 0.3  # Target average level
        self.gain_adjust_rate = 0.01
        
        # Beat detection for tempo
        self.beat_history = []
        self.last_beat_time = 0
        self.current_bpm = 120  # Default BPM
        
        self.init_ui()
        
        # Start audio device search in background after a short delay
        QTimer.singleShot(500, self.try_audio_devices_async)
        
        # Timer to update audio data to JavaScript
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.push_audio_data)
        self.update_timer.start(33)  # ~30fps
        
    def init_ui(self):
        self.setWindowTitle("Audio Visualizer")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                           Qt.WindowType.WindowStaysOnTopHint |
                           Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        # Position above system tray (bottom-right of screen)
        screen = QApplication.primaryScreen().geometry()
        width = 400
        height = 300
        x = screen.width() - width - 10
        y = screen.height() - height - 50  # Leave space for taskbar
        self.setGeometry(x, y, width, height)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # WebEngine view for visualizer
        self.web_view = QWebEngineView()
        self.web_view.loadFinished.connect(self.on_load_finished)
        
        # Enable context menu on web view
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self.show_context_menu)
        
        self.load_visualizer()
        
        layout.addWidget(self.web_view)
        
        # Add a close button at bottom right
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
        
        # Settings button
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
    
    def show_context_menu(self, pos):
        """Show context menu on right-click"""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        
        # Visual Mode submenu
        mode_menu = menu.addMenu("Visual Mode")
        
        mode_names = ["Spark Fountain", "Radial Burst", "Equalizer Bars", "Spiral Vortex", "Traveling Wave"]
        current_mode = self.config.get('visualMode', 0)
        
        for i, mode_name in enumerate(mode_names):
            action = mode_menu.addAction(mode_name)
            if i == current_mode:
                action.setText(f"● {mode_name}")
            action.triggered.connect(lambda checked, mode=i: self.switch_visual_mode(mode))
        
        menu.addSeparator()
        
        # Refresh visualizer
        refresh_action = menu.addAction("Refresh Visualizer")
        refresh_action.triggered.connect(self.load_visualizer)
        
        menu.addSeparator()
        
        # Toggle random mode
        random_action = menu.addAction("Toggle Random Mode")
        random_action.triggered.connect(self.toggle_random_mode)
        
        # Settings
        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self.show_settings)
        
        menu.addSeparator()
        
        # Close
        close_action = menu.addAction("Close Visualizer")
        close_action.triggered.connect(self.close)
        
        menu.exec(self.web_view.mapToGlobal(pos))
    
    def switch_visual_mode(self, mode_index):
        """Switch to a different visual mode"""
        print(f"\nSwitching to visual mode {mode_index}")
        self.config['visualMode'] = mode_index
        
        # Save to config file
        try:
            with open('visualizer_config.json', 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving mode: {e}")
        
        # Update visualizer
        if self.js_ready:
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
    
    def show_settings(self):
        """Show settings window"""
        if not hasattr(self, 'settings_window') or not self.settings_window:
            # Get audio devices
            devices = self.get_audio_devices()
            current_idx = 0
            for i, dev in enumerate(devices):
                if dev['index'] == self.selected_device_index:
                    current_idx = i
                    break
            
            self.settings_window = SettingsWindow(self.config, devices, current_idx)
            self.settings_window.settings_changed.connect(self.update_settings)
            self.settings_window.audio_device_changed.connect(self.on_device_changed)
        
        self.settings_window.show()
        self.settings_window.raise_()
    
    def toggle_random_mode(self):
        """Toggle random mode on/off"""
        self.config['randomMode'] = not self.config.get('randomMode', False)
        if self.js_ready:
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
        print(f"Random mode: {'ON' if self.config['randomMode'] else 'OFF'}")
    
    def mousePressEvent(self, event):
        """Handle mouse clicks"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Trigger click effect
            self.trigger_click_effect()
            
            # Also allow dragging (existing functionality)
            self.drag_position = event.globalPosition().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle window dragging"""
        if hasattr(self, 'drag_position'):
            delta = event.globalPosition().toPoint() - self.drag_position
            self.move(self.pos() + delta)
            self.drag_position = event.globalPosition().toPoint()
            event.accept()

    def trigger_click_effect(self):
        """Trigger dramatic color change and settings jump on click"""
        if not self.js_ready:
            return
        
        import random
        
        print("\n" + "="*60)
        print("LEFT-CLICK DETECTED - TRIGGERING COLOR/SETTINGS JUMP!")
        print("="*60)
        
        # Generate dramatic color shift
        self.click_hue_shift = random.randint(0, 360)
        
        # Backup current settings if not already backed up
        if self.click_settings_backup is None:
            self.click_settings_backup = self.config.copy()
        
        # Generate random dramatic settings
        dramatic_settings = {
            'density': random.randint(5, 25),
            'speed': random.uniform(0.5, 3.0),
            'bassSensitivity': random.uniform(2.0, 8.0),
            'colorCycleSpeed': random.randint(50, 150),
            'bassExplosion': random.uniform(2.0, 6.0),
            'sensitivity': random.randint(150, 250),
            'emitterGlowSize': random.randint(10, 30)
        }
        
        # Call JavaScript function
        js_code = f"""
            if (window.triggerClickEffect) {{
                window.triggerClickEffect({self.click_hue_shift}, {json.dumps(dramatic_settings)});
            }} else {{
                console.error('triggerClickEffect not found!');
            }}
        """
        
        self.web_view.page().runJavaScript(js_code)
        
        # Schedule restoration to original settings
        QTimer.singleShot(3000, self.restore_settings)
        
        print(f"Applied dramatic settings: {dramatic_settings}")
        print(f"Hue shift: {self.click_hue_shift}°")

    def restore_settings(self):
        """Restore settings after click effect"""
        if self.click_settings_backup:
            print("\n" + "="*60)
            print("RESTORING SETTINGS AFTER CLICK EFFECT")
            print("="*60)
            
            # Restore original settings
            for key, value in self.click_settings_backup.items():
                if key in self.config:
                    self.config[key] = value
            
            # Update visualizer
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
            
            # Clear backup (will be recreated on next click)
            self.click_settings_backup = None
            
            print("Settings restored to normal")

    
    def randomize_settings(self):
        """Randomize all visualizer settings"""
        import random
        self.config['density'] = random.randint(1, 20)
        self.config['bassSensitivity'] = random.random() * 5
        self.config['colorCycleSpeed'] = random.randint(0, 100)
        self.config['bassExplosion'] = random.random() * 5
        self.config['emitterGlowSize'] = random.randint(0, 20)
        
        if self.js_ready:
            config_json = json.dumps(self.config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
        print("Settings randomized!")
        
    def load_visualizer(self):
        """Load the visualizer HTML with embedded audio bridge"""
        html = self.get_visualizer_html()
        self.web_view.setHtml(html)
        
    def get_visualizer_html(self):
        """Generate HTML with visualizer and audio bridge"""
        config_json = json.dumps(self.config)
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                body {{
                    background: #000;
                    overflow: hidden;
                    cursor: pointer;
                }}
                #canvas {{
                    display: block;
                    background: #000;
                }}
                #audioDebug {{
                    position: absolute;
                    top: 10px;
                    left: 10px;
                    background: rgba(0, 0, 0, 0.7);
                    color: #0ff;
                    padding: 10px;
                    font-family: monospace;
                    font-size: 11px;
                    border-radius: 5px;
                    pointer-events: none;
                    opacity: 0.8;
                }}
                #deviceStatus {{
                    position: absolute;
                    bottom: 10px;
                    left: 10px;
                    background: rgba(0, 0, 0, 0.7);
                    color: #888;
                    padding: 8px 12px;
                    font-family: monospace;
                    font-size: 10px;
                    border-radius: 5px;
                    pointer-events: none;
                    opacity: 0.8;
                }}
                #deviceStatus.active {{
                    color: #0f0;
                }}
                #deviceStatus.error {{
                    color: #f00;
                }}
                .debug-bar {{
                    display: flex;
                    align-items: center;
                    margin: 3px 0;
                }}
                .debug-label {{
                    width: 60px;
                    color: #0ff;
                }}
                .debug-meter {{
                    flex: 1;
                    height: 8px;
                    background: #222;
                    border-radius: 4px;
                    overflow: hidden;
                    margin-left: 5px;
                }}
                .debug-fill {{
                    height: 100%;
                    transition: width 0.05s;
                    min-width: 1px;
                }}
                .debug-fill.bass {{ background: #f0f; }}
                .debug-fill.mid {{ background: #0ff; }}
                .debug-fill.treble {{ background: #ff0; }}
                .debug-value {{
                    width: 40px;
                    text-align: right;
                    margin-left: 5px;
                    color: #0ff;
                }}
                
                /* Click Ripple Effect */
                .click-ripple {{
                    position: absolute;
                    border-radius: 50%;
                    background: radial-gradient(circle, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0) 70%);
                    transform: translate(-50%, -50%) scale(0);
                    pointer-events: none;
                    z-index: 1000;
                    opacity: 0;
                    transition: all 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                }}
            </style>
        </head>
        <body>
            <canvas id="canvas"></canvas>
            <div id="deviceStatus">Searching for audio device...</div>
            <div id="audioDebug">
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
            <script>
                console.log('Visualizer script starting...');
                
                const canvas = document.getElementById('canvas');
                const ctx = canvas.getContext('2d');
                
                function resizeCanvas() {{
                    canvas.width = window.innerWidth;
                    canvas.height = window.innerHeight;
                    console.log('Canvas resized to:', canvas.width, 'x', canvas.height);
                    initWavePoints();  // Reinit wave points on resize
                }}
                resizeCanvas();
                window.addEventListener('resize', resizeCanvas);
                
                // Settings from Python
                let settings = {config_json};
                console.log('Settings loaded:', settings);
                
                // Audio data bridge (updated from Python)
                let audioData = {{bass: 0, mid: 0, treble: 0, overall: 0, rms: 0, bpm: 120}};
                
                // Update settings
                window.updateSettings = function(newSettings) {{
                    settings = newSettings;
                    console.log('Settings updated:', newSettings);
                    // Clear particles when switching modes
                    sparks = [];
                    bars = [];
                    spiralParticles = [];
                    waveOffset = 0;
                    initWavePoints();
                }};
                
                // Update audio data from Python
                window.updateAudio = function(data) {{
                    audioData = data;
                    // Update debug display
                    const bassPercent = Math.min(100, data.bass * 100);
                    const midPercent = Math.min(100, data.mid * 100);
                    const treblePercent = Math.min(100, data.treble * 100);
                    
                    document.getElementById('bassBar').style.width = bassPercent + '%';
                    document.getElementById('midBar').style.width = midPercent + '%';
                    document.getElementById('trebleBar').style.width = treblePercent + '%';
                    
                    document.getElementById('bassValue').textContent = data.bass.toFixed(2);
                    document.getElementById('midValue').textContent = data.mid.toFixed(2);
                    document.getElementById('trebleValue').textContent = data.treble.toFixed(2);
                }};
                
                // Mark as ready for Python
                window.visualizerReady = true;
                console.log('Visualizer ready!');
                
                // Update device status display
                window.updateDeviceStatus = function(message, status) {{
                    const statusEl = document.getElementById('deviceStatus');
                    statusEl.textContent = message;
                    statusEl.className = status;
                    console.log('Device status:', message, status);
                }};
                
                // Initial device status
                window.updateDeviceStatus('Loading...', '');
                
                // Click effect variables
                let clickEffectActive = false;
                let clickHueShift = 0;
                let clickStartTime = 0;
                let clickDuration = 3000;
                
                // Function to trigger click effect from Python
                window.triggerClickEffect = function(hueShift, newSettings) {{
                    console.log('Click effect triggered with hue shift:', hueShift, 'and settings:', newSettings);
                    
                    // Apply new settings immediately
                    if (newSettings) {{
                        for (let key in newSettings) {{
                            if (newSettings.hasOwnProperty(key)) {{
                                settings[key] = newSettings[key];
                            }}
                        }}
                    }}
                    
                    // Activate click effect
                    clickEffectActive = true;
                    clickHueShift = hueShift;
                    clickStartTime = Date.now();
                    
                    // Create ripple effect
                    createRippleEffect(canvas.width / 2, canvas.height / 2);
                    
                    // Add extra explosion particles
                    createClickParticles(30, hueShift);
                    
                    // Schedule restoration
                    setTimeout(() => {{
                        clickEffectActive = false;
                        console.log('Click effect ended');
                    }}, clickDuration);
                }};
                
                // Create ripple effect at click location
                function createRippleEffect(x, y) {{
                    const ripple = document.createElement('div');
                    ripple.className = 'click-ripple';
                    ripple.style.left = x + 'px';
                    ripple.style.top = y + 'px';
                    ripple.style.width = '100px';
                    ripple.style.height = '100px';
                    document.body.appendChild(ripple);
                    
                    setTimeout(() => {{
                        ripple.style.transform = 'translate(-50%, -50%) scale(3)';
                        ripple.style.opacity = '0.8';
                    }}, 10);
                    
                    setTimeout(() => {{
                        ripple.style.opacity = '0';
                        ripple.style.transform = 'translate(-50%, -50%) scale(5)';
                    }}, 100);
                    
                    setTimeout(() => {{
                        if (ripple.parentNode) {{
                            ripple.parentNode.removeChild(ripple);
                        }}
                    }}, 700);
                }};
                
                // Create extra particles for click explosion
                function createClickParticles(count, hueShift) {{
                    const centerX = canvas.width / 2;
                    const centerY = canvas.height / 2;
                    
                    for(let i = 0; i < count; i++) {{
                        const angle = Math.random() * Math.PI * 2;
                        const speed = 3 + Math.random() * 8;
                        const hue = (hueShift + Math.random() * 120) % 360;
                        const size = 2 + Math.random() * 4;
                        
                        const spark = new Spark(centerX, centerY, angle, speed, hue);
                        spark.size = size;
                        spark.life = 0.8 + Math.random() * 0.2;
                        spark.decay = 0.005 + Math.random() * 0.01;
                        
                        sparks.push(spark);
                    }}
                }};
                
                // ============================================
                // PARTICLE CLASSES FOR DIFFERENT MODES
                // ============================================
                
                // Spark class - for Fountain and Radial modes
                class Spark {{
                    constructor(x, y, angle, speed, hue) {{
                        this.x = x;
                        this.y = y;
                        this.vx = Math.cos(angle) * speed;
                        this.vy = Math.sin(angle) * speed;
                        this.life = 1.0;
                        this.decay = 0.01;
                        this.hue = hue;
                        this.size = 1 + Math.random() * 2;
                    }}
                    
                    update() {{
                        this.x += this.vx;
                        this.y += this.vy;
                        this.vy += 0.1; // gravity
                        this.life -= this.decay;
                    }}
                    
                    draw() {{
                        let drawHue = this.hue;
                        if (clickEffectActive) {{
                            const elapsed = Date.now() - clickStartTime;
                            if (elapsed < clickDuration) {{
                                const intensity = 1 - (elapsed / clickDuration);
                                drawHue = (this.hue + clickHueShift * intensity) % 360;
                            }}
                        }}
                        
                        ctx.fillStyle = `hsla(${{drawHue}}, 100%, 50%, ${{this.life}})`;
                        ctx.fillRect(this.x, this.y, this.size, this.size);
                    }}
                    
                    applyBassExplosion(centerX, centerY, force) {{
                        const dx = this.x - centerX;
                        const dy = this.y - centerY;
                        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                        this.vx += (dx / dist) * force;
                        this.vy += (dy / dist) * force;
                    }}
                }}
                
                // Equalizer Bar class
                class EqualizerBar {{
                    constructor(x, index, total) {{
                        this.x = x;
                        this.index = index;
                        this.total = total;
                        this.height = 0;
                        this.targetHeight = 0;
                        this.width = 0;
                        this.hue = (index / total) * 360;
                    }}
                    
                    update(magnitude, barWidth) {{
                        this.width = barWidth;
                        this.targetHeight = magnitude * canvas.height * 0.8;
                        this.height += (this.targetHeight - this.height) * 0.3;
                    }}
                    
                    draw() {{
                        let drawHue = this.hue;
                        if (clickEffectActive) {{
                            const elapsed = Date.now() - clickStartTime;
                            if (elapsed < clickDuration) {{
                                const intensity = 1 - (elapsed / clickDuration);
                                drawHue = (this.hue + clickHueShift * intensity) % 360;
                            }}
                        }}
                        
                        const gradient = ctx.createLinearGradient(0, canvas.height, 0, canvas.height - this.height);
                        gradient.addColorStop(0, `hsla(${{drawHue}}, 100%, 50%, 0.8)`);
                        gradient.addColorStop(1, `hsla(${{drawHue}}, 100%, 70%, 0.4)`);
                        
                        ctx.fillStyle = gradient;
                        ctx.fillRect(this.x, canvas.height - this.height, this.width - 2, this.height);
                        
                        // Glow effect
                        ctx.shadowBlur = 15;
                        ctx.shadowColor = `hsla(${{drawHue}}, 100%, 50%, 0.5)`;
                        ctx.fillRect(this.x, canvas.height - this.height, this.width - 2, this.height);
                        ctx.shadowBlur = 0;
                    }}
                }}
                
                // Spiral Particle class
                class SpiralParticle {{
                    constructor(angle, radius, speed, hue) {{
                        this.angle = angle;
                        this.radius = radius;
                        this.speed = speed;
                        this.hue = hue;
                        this.life = 1.0;
                        this.decay = 0.005;
                        this.size = 2 + Math.random() * 3;
                        this.spiralSpeed = 0.05 + Math.random() * 0.1;
                    }}
                    
                    update() {{
                        this.angle += this.spiralSpeed * settings.speed;
                        this.radius += this.speed;
                        this.life -= this.decay;
                    }}
                    
                    draw() {{
                        const centerX = canvas.width / 2;
                        const centerY = canvas.height / 2;
                        const x = centerX + Math.cos(this.angle) * this.radius;
                        const y = centerY + Math.sin(this.angle) * this.radius;
                        
                        let drawHue = this.hue;
                        if (clickEffectActive) {{
                            const elapsed = Date.now() - clickStartTime;
                            if (elapsed < clickDuration) {{
                                const intensity = 1 - (elapsed / clickDuration);
                                drawHue = (this.hue + clickHueShift * intensity) % 360;
                            }}
                        }}
                        
                        ctx.fillStyle = `hsla(${{drawHue}}, 100%, 50%, ${{this.life}})`;
                        ctx.fillRect(x, y, this.size, this.size);
                    }}
                }}
                
                // ============================================
                // VISUALIZATION MODES
                // ============================================
                
                let sparks = [];
                let bars = [];
                let spiralParticles = [];
                let wavePoints = [];  // For traveling wave mode
                let waveOffset = 0;
                let emitterAngle = 0;
                let currentHue = 0;
                let lastBass = 0;
                
                // Initialize wave points for traveling wave mode
                function initWavePoints() {{
                    wavePoints = [];
                    const numPoints = canvas.width + 50;  // Extra points for smooth scrolling
                    for (let i = 0; i < numPoints; i++) {{
                        wavePoints.push({{
                            x: i,
                            y: canvas.height / 2,
                            targetY: canvas.height / 2
                        }});
                    }}
                }}
                
                initWavePoints();
                
                // Mode 0: Spark Fountain (original)
                function animateFountain() {{
                    // Color cycling
                    if (settings.colorCycleSpeed > 0) {{
                        currentHue += settings.colorCycleSpeed * 0.1;
                        if (currentHue >= 360) currentHue -= 360;
                    }}
                    
                    // Bass hit detection
                    const bassHit = audioData.bass > 0.3 && audioData.bass > lastBass + 0.1;
                    if (bassHit) {{
                        currentHue = Math.random() * 360;
                    }}
                    lastBass = audioData.bass;
                    
                    const audioLevel = audioData.rms !== undefined ? audioData.rms : audioData.overall;
                    const speedMultiplier = 1 + (audioData.treble * 2.0);
                    
                    const baseParticles = settings.density;
                    const audioParticles = Math.floor(audioData.mid * settings.density * 2);
                    const totalParticles = baseParticles + audioParticles;
                    
                    // Bass explosion
                    if (audioData.bass > 0.3 && settings.bassExplosion > 0) {{
                        const centerX = canvas.width / 2;
                        const centerY = canvas.height / 2;
                        const explosionForce = audioData.bass * settings.bassExplosion * 0.8;
                        
                        sparks.forEach(spark => {{
                            spark.applyBassExplosion(centerX, centerY, explosionForce);
                        }});
                    }}
                    
                    // Rotate emission point
                    emitterAngle += 0.03 * settings.speed * speedMultiplier;
                    
                    const centerX = canvas.width / 2;
                    const centerY = canvas.height / 2;
                    const orbitRadius = Math.min(canvas.width, canvas.height) * 0.25;
                    
                    const emitX = centerX + Math.cos(emitterAngle) * orbitRadius;
                    const emitY = centerY + Math.sin(emitterAngle) * orbitRadius;
                    
                    // Draw emission point glow
                    let hue = (180 + currentHue) % 360;
                    if (clickEffectActive) {{
                        const elapsed = Date.now() - clickStartTime;
                        if (elapsed < clickDuration) {{
                            const intensity = 1 - (elapsed / clickDuration);
                            hue = (hue + clickHueShift * intensity) % 360;
                        }}
                    }}
                    
                    ctx.shadowBlur = 30;
                    ctx.shadowColor = `hsla(${{hue}}, 100%, 50%, 0.8)`;
                    ctx.fillStyle = `hsla(${{hue}}, 100%, 70%, 0.6)`;
                    ctx.beginPath();
                    ctx.arc(emitX, emitY, 5 + audioData.bass * 10, 0, Math.PI * 2);
                    ctx.fill();
                    
                    // Emit sparks
                    for (let i = 0; i < totalParticles; i++) {{
                        const spreadAngle = (Math.random() - 0.5) * Math.PI * 0.5;
                        const sparkAngle = emitterAngle + Math.PI + spreadAngle;
                        
                        const baseSpeed = 2 + Math.random() * 3;
                        const audioBoost = 1 + audioData.bass * settings.bassSensitivity * 0.5;
                        const speed = baseSpeed * settings.speed * 0.3 * audioBoost;
                        
                        const colorVariation = (i / totalParticles) * 60;
                        const sparkColor = (180 + colorVariation) % 360;
                        
                        sparks.push(new Spark(emitX, emitY, sparkAngle, speed, sparkColor));
                    }}
                    
                    // Update and draw sparks
                    ctx.shadowBlur = 0;
                    for (let i = sparks.length - 1; i >= 0; i--) {{
                        const spark = sparks[i];
                        spark.update();
                        spark.draw();
                        
                        if (spark.life <= 0) {{
                            sparks.splice(i, 1);
                        }}
                    }}
                }}
                
                // Mode 1: Radial Burst
                function animateRadialBurst() {{
                    // Color cycling
                    if (settings.colorCycleSpeed > 0) {{
                        currentHue += settings.colorCycleSpeed * 0.1;
                        if (currentHue >= 360) currentHue -= 360;
                    }}
                    
                    const centerX = canvas.width / 2;
                    const centerY = canvas.height / 2;
                    
                    // Draw center pulse
                    const pulseSize = 10 + audioData.bass * 40 + audioData.overall * 20;
                    ctx.shadowBlur = 40;
                    ctx.shadowColor = `hsla(${{currentHue}}, 100%, 50%, 0.8)`;
                    ctx.fillStyle = `hsla(${{currentHue}}, 100%, 70%, 0.6)`;
                    ctx.beginPath();
                    ctx.arc(centerX, centerY, pulseSize, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.shadowBlur = 0;
                    
                    // Emit particles on bass or continuous
                    const shouldEmit = audioData.overall > 0.1;
                    const particleCount = Math.floor(settings.density * (1 + audioData.bass * 3));
                    
                    if (shouldEmit) {{
                        for (let i = 0; i < particleCount; i++) {{
                            const angle = Math.random() * Math.PI * 2;
                            const speed = (2 + Math.random() * 4) * settings.speed * (1 + audioData.bass * 2);
                            const hue = (currentHue + Math.random() * 60 - 30) % 360;
                            
                            sparks.push(new Spark(centerX, centerY, angle, speed, hue));
                        }}
                    }}
                    
                    // Update and draw particles
                    for (let i = sparks.length - 1; i >= 0; i--) {{
                        const spark = sparks[i];
                        spark.update();
                        spark.draw();
                        
                        if (spark.life <= 0 || spark.x < 0 || spark.x > canvas.width || spark.y < 0 || spark.y > canvas.height) {{
                            sparks.splice(i, 1);
                        }}
                    }}
                }}
                
                // Mode 2: Equalizer Bars
                function animateEqualizer() {{
                    const numBars = 32;
                    
                    // Initialize bars if needed
                    if (bars.length !== numBars) {{
                        bars = [];
                        const barWidth = canvas.width / numBars;
                        for (let i = 0; i < numBars; i++) {{
                            bars.push(new EqualizerBar(i * barWidth, i, numBars));
                        }}
                    }}
                    
                    // Generate frequency magnitudes (simulated from audio bands)
                    const magnitudes = [];
                    for (let i = 0; i < numBars; i++) {{
                        const t = i / numBars;
                        let mag = 0;
                        
                        // Map frequency bands
                        if (t < 0.3) {{
                            mag = audioData.bass * (0.5 + Math.random() * 0.5);
                        }} else if (t < 0.7) {{
                            mag = audioData.mid * (0.5 + Math.random() * 0.5);
                        }} else {{
                            mag = audioData.treble * (0.5 + Math.random() * 0.5);
                        }}
                        
                        magnitudes.push(mag * settings.bassSensitivity);
                    }}
                    
                    // Update and draw bars
                    const barWidth = canvas.width / numBars;
                    bars.forEach((bar, i) => {{
                        bar.update(magnitudes[i], barWidth);
                        bar.draw();
                    }});
                }}
                
                // Mode 3: Spiral Vortex
                function animateSpiralVortex() {{
                    // Color cycling
                    if (settings.colorCycleSpeed > 0) {{
                        currentHue += settings.colorCycleSpeed * 0.1;
                        if (currentHue >= 360) currentHue -= 360;
                    }}
                    
                    const centerX = canvas.width / 2;
                    const centerY = canvas.height / 2;
                    
                    // Draw center
                    const pulseSize = 8 + audioData.overall * 15;
                    ctx.shadowBlur = 30;
                    ctx.shadowColor = `hsla(${{currentHue}}, 100%, 50%, 0.8)`;
                    ctx.fillStyle = `hsla(${{currentHue}}, 100%, 70%, 0.6)`;
                    ctx.beginPath();
                    ctx.arc(centerX, centerY, pulseSize, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.shadowBlur = 0;
                    
                    // Emit spiral particles
                    const shouldEmit = audioData.overall > 0.05;
                    if (shouldEmit) {{
                        const particleCount = Math.floor(settings.density * (1 + audioData.mid * 2));
                        
                        for (let i = 0; i < particleCount; i++) {{
                            const angle = Math.random() * Math.PI * 2;
                            const speed = (0.5 + Math.random() * 1.5) * settings.speed;
                            const hue = (currentHue + Math.random() * 120) % 360;
                            
                            spiralParticles.push(new SpiralParticle(angle, 5, speed, hue));
                        }}
                    }}
                    
                    // Update and draw spiral particles
                    for (let i = spiralParticles.length - 1; i >= 0; i--) {{
                        const particle = spiralParticles[i];
                        particle.update();
                        particle.draw();
                        
                        if (particle.life <= 0 || particle.radius > Math.max(canvas.width, canvas.height)) {{
                            spiralParticles.splice(i, 1);
                        }}
                    }}
                }}
                
                // Mode 4: Traveling Wave
                function animateTravelingWave() {{
                    // Color cycling
                    if (settings.colorCycleSpeed > 0) {{
                        currentHue += settings.colorCycleSpeed * 0.1;
                        if (currentHue >= 360) currentHue -= 360;
                    }}
                    
                    // Scroll speed based on tempo and audio
                    const baseSpeed = settings.speed * 2;
                    const tempoMultiplier = 1 + (audioData.treble * 0.5);  // Treble affects speed
                    const scrollSpeed = baseSpeed * tempoMultiplier;
                    
                    waveOffset += scrollSpeed;
                    
                    // Calculate wave amplitude based on audio
                    const amplitude = 50 + (audioData.overall * 150);
                    const bassAmp = audioData.bass * 80;
                    const midAmp = audioData.mid * 60;
                    
                    // Update wave points - create scrolling effect
                    const centerY = canvas.height / 2;
                    
                    // Shift all points left
                    for (let i = 0; i < wavePoints.length - 1; i++) {{
                        wavePoints[i].targetY = wavePoints[i + 1].targetY;
                        wavePoints[i].y += (wavePoints[i].targetY - wavePoints[i].y) * 0.3;
                    }}
                    
                    // Add new point at the end
                    const lastPoint = wavePoints[wavePoints.length - 1];
                    const freq = 0.05 * (1 + audioData.mid * 0.5);  // Mid frequencies affect wave frequency
                    const time = Date.now() * 0.001;
                    
                    // Create wave with multiple components
                    let newY = centerY;
                    newY += Math.sin(time * freq * 2) * amplitude;
                    newY += Math.sin(time * freq * 3 + 1) * (amplitude * 0.5);
                    newY += bassAmp * Math.sin(time * 0.5);  // Bass creates slower waves
                    newY += midAmp * Math.sin(time * 2);     // Mid creates faster ripples
                    
                    lastPoint.targetY = newY;
                    lastPoint.y += (lastPoint.targetY - lastPoint.y) * 0.3;
                    
                    // Draw the traveling wave with glow effect
                    let drawHue = currentHue;
                    if (clickEffectActive) {{
                        const elapsed = Date.now() - clickStartTime;
                        if (elapsed < clickDuration) {{
                            const intensity = 1 - (elapsed / clickDuration);
                            drawHue = (currentHue + clickHueShift * intensity) % 360;
                        }}
                    }}
                    
                    // Draw multiple layers for glow effect
                    const glowLayers = [
                        {{ blur: 40, alpha: 0.2, width: 8 }},
                        {{ blur: 20, alpha: 0.4, width: 5 }},
                        {{ blur: 10, alpha: 0.6, width: 3 }},
                        {{ blur: 0, alpha: 1.0, width: 2 }}
                    ];
                    
                    glowLayers.forEach(layer => {{
                        ctx.shadowBlur = layer.blur;
                        ctx.shadowColor = `hsla(${{drawHue}}, 100%, 50%, ${{layer.alpha}})`;
                        ctx.strokeStyle = `hsla(${{drawHue}}, 100%, 60%, ${{layer.alpha}})`;
                        ctx.lineWidth = layer.width;
                        ctx.lineCap = 'round';
                        ctx.lineJoin = 'round';
                        
                        ctx.beginPath();
                        for (let i = 0; i < wavePoints.length; i++) {{
                            const point = wavePoints[i];
                            if (i === 0) {{
                                ctx.moveTo(point.x - waveOffset, point.y);
                            }} else {{
                                ctx.lineTo(point.x - waveOffset, point.y);
                            }}
                        }}
                        ctx.stroke();
                    }});
                    
                    ctx.shadowBlur = 0;
                    
                    // Reset offset when it gets too large
                    if (waveOffset > canvas.width) {{
                        waveOffset = 0;
                    }}
                    
                    // Draw center reference line (subtle)
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(0, canvas.height / 2);
                    ctx.lineTo(canvas.width, canvas.height / 2);
                    ctx.stroke();
                }}
                
                // ============================================
                // MAIN ANIMATION LOOP
                // ============================================
                
                function animate() {{
                    // Clear canvas with fade effect
                    ctx.fillStyle = 'rgba(0, 0, 0, 0.08)';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    
                    // Random mode - change settings periodically
                    if (settings.randomMode) {{
                        if (!window.lastRandomChange) window.lastRandomChange = Date.now();
                        if (Date.now() - window.lastRandomChange > 3000) {{
                            const randomProp = ['density', 'speed', 'bassSensitivity', 'colorCycleSpeed', 'bassExplosion'][Math.floor(Math.random() * 5)];
                            
                            if (randomProp === 'density') settings.density = 1 + Math.floor(Math.random() * 20);
                            else if (randomProp === 'speed') settings.speed = 0.1 + Math.random() * 4.9;
                            else if (randomProp === 'bassSensitivity') settings.bassSensitivity = Math.random() * 5;
                            else if (randomProp === 'colorCycleSpeed') settings.colorCycleSpeed = Math.floor(Math.random() * 100);
                            else if (randomProp === 'bassExplosion') settings.bassExplosion = Math.random() * 5;
                            
                            window.lastRandomChange = Date.now();
                        }}
                    }}
                    
                    // Run appropriate animation based on mode
                    const mode = settings.visualMode || 0;
                    
                    switch(mode) {{
                        case 0:
                            animateFountain();
                            break;
                        case 1:
                            animateRadialBurst();
                            break;
                        case 2:
                            animateEqualizer();
                            break;
                        case 3:
                            animateSpiralVortex();
                            break;
                        case 4:
                            animateTravelingWave();
                            break;
                        default:
                            animateFountain();
                    }}
                    
                    requestAnimationFrame(animate);
                }}
                
                animate();
            </script>
        </body>
        </html>
        """
        return html
        
    def get_audio_devices(self):
        """Get list of available loopback audio devices"""
        print("\n" + "="*60)
        print("GETTING AUDIO DEVICES")
        print("="*60)
        devices = []
        try:
            p = pyaudio.PyAudio()
            
            # Get WASAPI info
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                print(f"WASAPI host API index: {wasapi_info['index']}")
                print(f"WASAPI device count: {wasapi_info['deviceCount']}")
            except OSError:
                print("WASAPI not available")
                p.terminate()
                return devices
            
            # Get all loopback devices with valid input channels
            print("\nLoopback devices found:")
            loopback_devices = list(p.get_loopback_device_info_generator())
            print(f"Total loopback devices: {len(loopback_devices)}")
            
            for i, loopback in enumerate(loopback_devices):
                channels = int(loopback['maxInputChannels'])
                print(f"\nDevice {i}:")
                print(f"  Name: {loopback['name']}")
                print(f"  Index: {loopback['index']}")
                print(f"  Max Input Channels: {channels}")
                print(f"  Default Sample Rate: {loopback['defaultSampleRate']}")
                
                if channels > 0:  # Only add devices with valid channels
                    devices.append({
                        'index': loopback['index'],
                        'name': loopback['name'],
                        'channels': channels,
                        'rate': int(loopback['defaultSampleRate'])
                    })
                    print(f"  ✓ Added to available devices")
                else:
                    print(f"  ✗ Skipped (0 input channels)")
            
            p.terminate()
        except Exception as e:
            print(f"Error getting audio devices: {e}")
            import traceback
            traceback.print_exc()
            
        print(f"\nTotal available devices: {len(devices)}")
        print("="*60)
        return devices
    
    def try_audio_devices_async(self):
        """Start audio device search in background thread"""
        print("\n" + "="*60)
        print("STARTING ASYNC DEVICE SEARCH")
        print("="*60)
        search_thread = threading.Thread(target=self.try_audio_devices, daemon=True)
        search_thread.start()
    
    def try_audio_devices(self):
        """Try to initialize audio, falling back through all devices if needed"""
        print("\n" + "="*60)
        print("STARTING AUDIO DEVICE SEARCH")
        print("="*60)
        
        devices = self.get_audio_devices()
        
        if not devices:
            print("ERROR: No audio devices found!")
            self.device_error.emit("No audio loopback devices found. Make sure you have audio output devices enabled.")
            return
        
        print(f"Found {len(devices)} audio device(s):")
        for i, dev in enumerate(devices):
            print(f"  [{i}] Index {dev['index']}: {dev['name']}")
            print(f"      Channels: {dev['channels']}, Rate: {dev['rate']}")
        
        # Get the saved device name from config
        saved_device_name = self.config.get('selectedDeviceName')
        saved_device_index = self.config.get('selectedDeviceIndex')
        
        # First, try to find device by NAME
        if saved_device_name:
            print(f"\nLooking for saved device with name: {saved_device_name}")
            for device in devices:
                if device['name'] == saved_device_name:
                    print(f"✓ Found saved device by name: {device['name']}")
                    self.selected_device_index = device['index']
                    
                    print(f"Testing saved device...")
                    if self.quick_test_audio_device():
                        print(f"✓ SUCCESS: Saved device works!")
                        self.device_working = True
                        self.device_success.emit(f"Audio device: {device['name']}")
                        
                        self.config['selectedDeviceIndex'] = device['index']
                        try:
                            with open('visualizer_config.json', 'w') as f:
                                json.dump(self.config, f, indent=2)
                            print(f"Updated device index to {device['index']} in config")
                        except Exception as e:
                            print(f"Error saving device: {e}")
                        
                        print(f"Starting audio capture with saved device...")
                        self.start_audio_capture()
                        return
                    else:
                        print(f"✗ Saved device failed to initialize")
                        break
            else:
                print(f"✗ Saved device name not found in current devices")
        
        # Try by index if needed
        elif saved_device_index is not None:
            print(f"\nLooking for saved device with index {saved_device_index}...")
            for device in devices:
                if device['index'] == saved_device_index:
                    print(f"✓ Found saved device by index: {device['name']}")
                    self.selected_device_index = device['index']
                    
                    print(f"Testing saved device...")
                    if self.quick_test_audio_device():
                        print(f"✓ SUCCESS: Saved device works!")
                        self.device_working = True
                        self.device_success.emit(f"Audio device: {device['name']}")
                        
                        self.config['selectedDeviceName'] = device['name']
                        self.config['selectedDeviceIndex'] = device['index']
                        try:
                            with open('visualizer_config.json', 'w') as f:
                                json.dump(self.config, f, indent=2)
                            print(f"Saved device name '{device['name']}' and index {device['index']} to config")
                        except Exception as e:
                            print(f"Error saving device: {e}")
                        
                        print(f"Starting audio capture with saved device...")
                        self.start_audio_capture()
                        return
                    else:
                        print(f"✗ Saved device failed to initialize")
                        break
            else:
                print(f"✗ Saved device index not found in current devices")
        
        # Try all devices in order
        print(f"\nTrying all available devices in order...")
        for i, device in enumerate(devices):
            print(f"\nTrying device {i+1}/{len(devices)}:")
            print(f"  Name: {device['name']}")
            print(f"  Index: {device['index']}")
            self.selected_device_index = device['index']
            
            print(f"  Testing device...")
            if self.quick_test_audio_device():
                print(f"✓ SUCCESS: Device works!")
                self.device_working = True
                
                self.config['selectedDeviceName'] = device['name']
                self.config['selectedDeviceIndex'] = device['index']
                try:
                    with open('visualizer_config.json', 'w') as f:
                        json.dump(self.config, f, indent=2)
                    print(f"  Saved device name '{device['name']}' and index {device['index']} to config")
                except Exception as e:
                    print(f"  Error saving device: {e}")
                
                self.device_success.emit(f"Audio device: {device['name']}")
                print(f"Starting audio capture...")
                self.start_audio_capture()
                return
            else:
                print(f"✗ Device failed to open")
        
        print("\n" + "="*60)
        print("ERROR: No working audio devices found!")
        print("="*60)
        device_list = "\n".join([f"- {d['name']}" for d in devices])
        self.device_error.emit(
            f"Could not initialize audio capture with any device.\n\n"
            f"Devices tried:\n{device_list}\n\n"
            f"Please select a device manually in Settings."
        )
    
    def quick_test_audio_device(self):
        """Quick test if audio device works"""
        import pyaudiowpatch as pyaudio
        try:
            p = pyaudio.PyAudio()
            device_info = p.get_device_info_by_index(self.selected_device_index)
            
            CHANNELS = int(device_info["maxInputChannels"])
            if CHANNELS == 0:
                p.terminate()
                return False
            
            FORMAT = pyaudio.paInt16
            RATE = int(device_info["defaultSampleRate"])
            
            stream = p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=256,
                input_device_index=self.selected_device_index
            )
            
            data = stream.read(128, exception_on_overflow=False)
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            audio_int = np.frombuffer(data, dtype=np.int16)
            max_val = np.max(np.abs(audio_int))
            return max_val > 0
        except Exception as e:
            print(f"  Device test failed: {e}")
            return False
        
    def start_audio_capture(self):
        """Start audio capture with current selected device"""
        print("\n" + "="*60)
        print("STARTING AUDIO CAPTURE")
        print("="*60)
        
        if self.audio_thread and self.audio_thread.is_alive():
            print("Stopping existing audio thread...")
            self.audio_stop_event.set()
            self.audio_thread.join(timeout=2)
            print("Existing audio thread stopped.")
        
        self.audio_queue = queue.Queue()
        self.audio_stop_event.clear()
        self.audio_thread = threading.Thread(target=self.audio_capture_thread, daemon=True)
        self.audio_thread.start()
        
        self.device_working = True
        print(f"Started audio capture thread for device index {self.selected_device_index}")
        print("="*60)
        
    def on_device_changed(self, device_index):
        """Change the audio input device"""
        print(f"\n" + "="*60)
        print(f"USER MANUALLY SELECTED DEVICE INDEX {device_index}")
        print("="*60)
        
        devices = self.get_audio_devices()
        device_name = ""
        for device in devices:
            if device['index'] == device_index:
                device_name = device['name']
                break
        
        if not device_name:
            print(f"ERROR: Could not find device with index {device_index}")
            return
        
        self.selected_device_index = device_index
        
        self.config['selectedDeviceName'] = device_name
        self.config['selectedDeviceIndex'] = device_index
        try:
            with open('visualizer_config.json', 'w') as f:
                json.dump(self.config, f, indent=2)
            print(f"Saved device name '{device_name}' and index {device_index} to config file")
        except Exception as e:
            print(f"Error saving device selection: {e}")
        
        self.start_audio_capture()
        self.device_success.emit(f"Audio device: {device_name}")
        
    def audio_capture_thread(self):
        """Background thread for audio capture"""
        stream = None
        p = None
        try:
            print("\n" + "="*60)
            print("STARTING AUDIO CAPTURE THREAD")
            print("="*60)
            
            p = pyaudio.PyAudio()
            
            if self.selected_device_index is not None:
                print(f"Using selected device index: {self.selected_device_index}")
                device_info = p.get_device_info_by_index(self.selected_device_index)
            else:
                print("No device index selected, trying default WASAPI loopback")
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
                
                if not default_speakers["isLoopbackDevice"]:
                    print("Default speakers not loopback, searching for loopback device...")
                    for loopback in p.get_loopback_device_info_generator():
                        if default_speakers["name"] in loopback["name"]:
                            default_speakers = loopback
                            break
                
                device_info = default_speakers
                self.selected_device_index = device_info["index"]
                print(f"Using default device index: {self.selected_device_index}")
            
            print(f"\nDEVICE INFO:")
            print(f"  Name: {device_info['name']}")
            print(f"  Index: {device_info['index']}")
            print(f"  Max Input Channels: {device_info['maxInputChannels']}")
            print(f"  Default Sample Rate: {device_info['defaultSampleRate']}")
            
            CHANNELS = int(device_info["maxInputChannels"])
            if CHANNELS == 0:
                print(f"\nERROR: Device has 0 input channels!")
                return
            
            if CHANNELS > 2:
                CHANNELS = 2
            
            CHUNK = 1024
            FORMAT = pyaudio.paInt16
            RATE = int(device_info["defaultSampleRate"])
            
            if RATE == 0:
                RATE = 44100
            
            print(f"\nAUDIO PARAMETERS:")
            print(f"  Chunk size: {CHUNK}")
            print(f"  Sample Rate: {RATE}")
            
            stream = p.open(format=FORMAT,
                          channels=CHANNELS,
                          rate=RATE,
                          input=True,
                          frames_per_buffer=CHUNK,
                          input_device_index=device_info["index"])
            
            print("Stream opened successfully!")
            
            frame_count = 0
            silent_frames = 0
            
            while not self.audio_stop_event.is_set():
                try:
                    frame_count += 1
                    
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_int = np.frombuffer(data, dtype=np.int16)
                    
                    max_val = np.max(np.abs(audio_int))
                    
                    if max_val == 0:
                        silent_frames += 1
                        if silent_frames > 10:
                            print("  ERROR: Too many consecutive silent frames!")
                        continue
                    else:
                        silent_frames = 0
                    
                    if CHANNELS == 2:
                        audio_int = audio_int.reshape(-1, 2)
                        audio_int = audio_int.mean(axis=1).astype(np.int16)
                    
                    audio_float = audio_int.astype(np.float32) / 32768.0
                    window = np.hanning(len(audio_float))
                    audio_windowed = audio_float * window
                    
                    fft = np.fft.rfft(audio_windowed)
                    magnitude = np.abs(fft)
                    
                    if np.max(magnitude) == 0:
                        continue
                    
                    nyquist = RATE / 2
                    bin_width = nyquist / (len(magnitude) - 1)
                    
                    bass_end_bin = int(250 / bin_width) + 1
                    mid_start_bin = int(250 / bin_width) + 1
                    mid_end_bin = int(2000 / bin_width) + 1
                    treble_start_bin = int(2000 / bin_width) + 1
                    treble_end_bin = min(int(8000 / bin_width) + 1, len(magnitude))
                    
                    bass_end_bin = min(max(2, bass_end_bin), len(magnitude))
                    mid_start_bin = min(mid_start_bin, len(magnitude))
                    mid_end_bin = min(max(mid_start_bin + 1, mid_end_bin), len(magnitude))
                    treble_start_bin = min(treble_start_bin, len(magnitude))
                    treble_end_bin = min(max(treble_start_bin + 1, treble_end_bin), len(magnitude))
                    
                    sensitivity_factor = self.config.get('sensitivity', 100) / 100.0
                    
                    bass_energy = np.sum(magnitude[0:bass_end_bin]) if bass_end_bin > 0 else 0
                    mid_energy = np.sum(magnitude[mid_start_bin:mid_end_bin]) if mid_end_bin > mid_start_bin else 0
                    treble_energy = np.sum(magnitude[treble_start_bin:treble_end_bin]) if treble_end_bin > treble_start_bin else 0
                    
                    bass_scaled = bass_energy * 0.01 * sensitivity_factor
                    mid_scaled = mid_energy * 0.005 * sensitivity_factor
                    treble_scaled = treble_energy * 0.003 * sensitivity_factor
                    
                    bass_log = math.log10(bass_scaled + 1) * 2
                    mid_log = math.log10(mid_scaled + 1) * 2
                    treble_log = math.log10(treble_scaled + 1) * 2
                    
                    current_level = (bass_log + mid_log + treble_log) / 3
                    if current_level > 0:
                        gain_error = self.gain_target - current_level
                        self.auto_gain += gain_error * self.gain_adjust_rate
                        self.auto_gain = max(0.1, min(10.0, self.auto_gain))
                        
                        bass_log *= self.auto_gain
                        mid_log *= self.auto_gain
                        treble_log *= self.auto_gain
                    
                    rms = np.sqrt(np.mean(audio_float**2))
                    rms_db = 20 * math.log10(rms + 1e-10)
                    rms_norm = max(0.0, min(1.0, (rms_db + 60) / 40))
                    
                    bass_final = float(min(1.0, max(0.0, bass_log)))
                    mid_final = float(min(1.0, max(0.0, mid_log)))
                    treble_final = float(min(1.0, max(0.0, treble_log)))
                    overall_final = (bass_final + mid_final + treble_final) / 3
                    
                    with self.audio_data_lock:
                        self.audio_data = {
                            'bass': bass_final,
                            'mid': mid_final,
                            'treble': treble_final,
                            'overall': overall_final,
                            'rms': rms_norm,
                            'bpm': self.current_bpm
                        }
                    
                    if frame_count % 10 == 0:
                        print(f"\n[Frame {frame_count}] Bass: {bass_final:.3f}, Mid: {mid_final:.3f}, Treble: {treble_final:.3f}, RMS: {rms_norm:.3f}")
                    
                except Exception as e:
                    print(f"\nERROR in audio processing frame {frame_count}: {e}")
                    if not self.audio_stop_event.is_set():
                        continue
                    else:
                        break
                    
        except OSError as e:
            print(f"\nOSError opening audio stream: {e}")
        except Exception as e:
            print(f"\nFATAL ERROR in audio capture thread: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\n" + "="*60)
            print("STOPPING AUDIO CAPTURE THREAD")
            print("="*60)
            
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass
            if p:
                p.terminate()
            
            print("Audio capture thread stopped.")
            
    def on_load_finished(self, success):
        """Called when the web page finishes loading"""
        if success:
            self.js_ready = True
            print("Visualizer loaded successfully")
            if self.device_working:
                self.device_success.emit(f"Audio device connected")
        else:
            print("Failed to load visualizer")
            
    def push_audio_data(self):
        """Push audio data to JavaScript"""
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
        """Update visualizer settings"""
        self.config = new_config
        if self.js_ready:
            config_json = json.dumps(new_config)
            self.web_view.page().runJavaScript(f"window.updateSettings({config_json})")
    
    def closeEvent(self, event):
        """Handle window close"""
        self.audio_stop_event.set()
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1)
        event.accept()


def load_config():
    """Load configuration from file"""
    print("\n" + "="*60)
    print("LOADING CONFIG")
    print("="*60)
    
    default_config = {
        'visualMode': 0,
        'density': 5,
        'speed': 1.0,
        'bassSensitivity': 1.5,
        'colorCycleSpeed': 10,
        'bassExplosion': 1.0,
        'sensitivity': 100,
        'randomMode': True,
        'selectedDeviceIndex': None,
        'emitterGlowSize': 3
    }
    
    try:
        if os.path.exists('visualizer_config.json'):
            print("Config file found, loading...")
            with open('visualizer_config.json', 'r') as f:
                loaded_config = json.load(f)
            print(f"Loaded config: {loaded_config}")
            
            for key in default_config:
                if key not in loaded_config:
                    loaded_config[key] = default_config[key]
                    print(f"  Added missing key: {key} = {default_config[key]}")
            
            print("="*60)
            return loaded_config
        else:
            print("No config file found, using defaults")
    except Exception as e:
        print(f"Error loading config: {e}")
        import traceback
        traceback.print_exc()
    
    print("="*60)
    return default_config


if __name__ == '__main__':
    print("\n" + "="*60)
    print("STARTING AUDIO VISUALIZER (Multi-Mode)")
    print("="*60)
    
    app = QApplication(sys.argv)
    config = load_config()
    window = VisualizerWindow(config)
    window.show()
    sys.exit(app.exec())
