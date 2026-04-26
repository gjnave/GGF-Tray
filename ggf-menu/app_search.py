"""
GGF App Search - Standalone PyQt6 Application
Searches and downloads tools from getgoingfast.pro
"""
import sys
import os
import json
import urllib.request
import urllib.parse
import webbrowser
import zipfile
import tempfile
import shutil
import threading
import time
import subprocess
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QComboBox, QListWidget, QLabel, 
                             QPushButton, QListWidgetItem, QProgressBar, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, QUrl, QThread, pyqtSignal

# --- Logging ---
import datetime


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_subprocess_env():
    env = os.environ.copy()
    if getattr(sys, 'frozen', False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


APP_DIR = get_app_dir()
_LOG_FILE = os.path.join(APP_DIR, 'app_search_log.txt')
def _log(msg):
    ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(_LOG_FILE, 'a', encoding='utf-8') as _f:
            _f.write(line + '\n')
    except:
        pass

# Clear log on startup
try:
    with open(_LOG_FILE, 'w', encoding='utf-8') as _f:
        _f.write(f"=== app_search started {datetime.datetime.now()} ===\n")
except:
    pass

from PyQt6.QtGui import QDesktopServices

# Import auth manager
try:
    from ggf_auth_token import AuthManager
except ImportError:
    # If running from different directory, try to import from same directory
    script_dir = APP_DIR
    sys.path.insert(0, script_dir)
    from ggf_auth_token import AuthManager

# Initialize auth manager (shared instance)
auth_manager = AuthManager()


class DownloadWorker(QThread):
    """Background thread for downloading files"""
    progress = pyqtSignal(int, str)  # (percent, status_message)
    finished = pyqtSignal(bool, str, str, str)  # (success, message, file_path, file_type)
    
    def __init__(self, download_url, tool_slug):
        super().__init__()
        self.download_url = download_url
        self.tool_slug = tool_slug
    
    def run(self):
        _log(f"=== DownloadWorker.run START slug={self.tool_slug} ===")
        _log(f"download_url = {self.download_url}")
        try:
            temp_dir = tempfile.mkdtemp()
            _log(f"temp_dir = {temp_dir}")
            self.progress.emit(0, "Starting download...")

            # Single request - read header AND body from same connection
            _log("Opening URL connection...")
            req = urllib.request.Request(self.download_url, headers={'User-Agent': 'GGF-AppSearch/1.0'})
            response = urllib.request.urlopen(req)
            _log(f"Response status: {response.status}")
            _log(f"Response URL (after redirects): {response.url}")
            _log(f"Response headers: {dict(response.headers)}")

            content_disposition = response.headers.get('Content-Disposition', '')
            content_type = response.headers.get('Content-Type', '')
            content_length = response.headers.get('Content-Length', 'unknown')
            _log(f"Content-Disposition: {repr(content_disposition)}")
            _log(f"Content-Type: {content_type}")
            _log(f"Content-Length: {content_length}")

            if 'filename=' in content_disposition:
                actual_filename = content_disposition.split('filename=')[1].strip('"; ')
                _log(f"Filename from header: {actual_filename}")
            else:
                actual_filename = f"{self.tool_slug}.zip"
                _log(f"No filename in header, using fallback: {actual_filename} (server should set Content-Disposition)")

            file_path = os.path.join(temp_dir, actual_filename)
            _log(f"Writing to: {file_path}")

            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 8192
            with open(file_path, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = min(100, int(downloaded * 100 / total_size))
                        self.progress.emit(pct, f"Downloading... {pct}%")
                    else:
                        kb = downloaded // 1024
                        self.progress.emit(50, f"Downloading... {kb} KB")

            _log(f"Download complete. Total bytes written: {downloaded}")
            actual_size = os.path.getsize(file_path)
            _log(f"File size on disk: {actual_size}")

            # Peek at first bytes to detect if server returned error HTML instead of file
            with open(file_path, 'rb') as f:
                head = f.read(200)
            _log(f"First 200 bytes (repr): {repr(head)}")
            if head.strip().lower().startswith(b'<!doctype') or head.strip().lower().startswith(b'<html'):
                _log("WARNING: response looks like HTML error page, not a real file!")

            file_ext = os.path.splitext(actual_filename)[1].lower()
            _log(f"file_ext = {file_ext}")
            self.progress.emit(100, "Download complete!")
            _log("Emitting finished(True)")
            self.finished.emit(True, "Download complete", file_path, file_ext)

        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read(500).decode('utf-8', errors='replace')
            except: pass
            _log(f"HTTPError: code={e.code} reason={e.reason}")
            _log(f"Error headers: {dict(e.headers) if hasattr(e,'headers') else 'n/a'}")
            _log(f"Error body (first 500): {body}")
            self.finished.emit(False, f"Download failed: HTTP {e.code} {e.reason}\n\nServer said:\n{body[:300]}", "", "")
        except Exception as e:
            import traceback
            _log(f"Exception: {type(e).__name__}: {e}")
            _log(traceback.format_exc())
            self.finished.emit(False, f"Download failed:\n{str(e)}", "", "")


class LoginPoller(QThread):
    """Background thread for polling login status"""
    success = pyqtSignal(dict)
    failed = pyqtSignal()
    
    def __init__(self, token, auth_manager):
        super().__init__()
        self.token = token
        self.auth_manager = auth_manager
    
    def run(self):
        result = self.auth_manager.poll_for_auth(self.token, timeout=120, interval=2)
        if result:
            self.success.emit(result)
        else:
            self.failed.emit()


class SearchDialog(QWidget):
    """Main search dialog window"""
    
    def __init__(self):
        super().__init__()
        self.tools_data = []
        self.url_mapping = {}
        self.current_selection = None
        self.download_worker = None
        self.login_poller = None
        self.init_ui()
        QTimer.singleShot(100, self.load_tools)
    
    def init_ui(self):
        self.setWindowTitle("GGF App Search")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                           Qt.WindowType.WindowStaysOnTopHint |
                           Qt.WindowType.Tool)
        
        # Position above taskbar in bottom-right
        screen = QApplication.primaryScreen().geometry()
        width = 450
        height = 480
        x = screen.width() - width - 10
        y = screen.height() - height - 50
        self.setGeometry(x, y, width, height)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Set background
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: white;
            }
        """)
        
        # Auth header (tier display)
        if auth_manager and auth_manager.is_authenticated():
            tier_name = auth_manager.format_tier_name()
            user_name = auth_manager.get_name()
            auth_header = QLabel(f"🎯 {tier_name} - {user_name}")
            auth_header.setStyleSheet("""
                QLabel {
                    background-color: #4a90e2;
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                    border-radius: 4px;
                }
            """)
        else:
            auth_header = QLabel("🔓 Not Logged In")
            auth_header.setStyleSheet("""
                QLabel {
                    background-color: #666;
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                    border-radius: 4px;
                }
            """)
        
        auth_layout = QHBoxLayout()
        auth_layout.addWidget(auth_header, 1)
        
        # Login button if not authenticated
        if not (auth_manager and auth_manager.is_authenticated()):
            login_btn = QPushButton("Login with Patreon")
            login_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF424D;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #E0383F;
                }
            """)
            login_btn.clicked.connect(self.open_login)
            auth_layout.addWidget(login_btn)
        
        layout.addLayout(auth_layout)
        
        # Title
        title = QLabel("Search Apps")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(title)
        
        # Search row
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3b3b3b;
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        self.search_input.textChanged.connect(self.filter_results)
        search_layout.addWidget(self.search_input, 2)
        
        # Type filter
        self.type_filter = QComboBox()
        self.type_filter.addItems(["Type (all)", "Faceswap", "Image", "Video", 
                                  "Audio", "LLM", "TTS", "LipSync", "Utility", "ComfyUI"])
        self.type_filter.setStyleSheet("""
            QComboBox {
                background-color: #3b3b3b;
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #3b3b3b;
                color: white;
                selection-background-color: #4a90e2;
            }
        """)
        self.type_filter.currentTextChanged.connect(self.filter_results)
        search_layout.addWidget(self.type_filter, 1)
        
        layout.addLayout(search_layout)
        
        # Results list
        self.results_list = QListWidget()
        self.results_list.setStyleSheet("""
            QListWidget {
                background-color: #3b3b3b;
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #444;
            }
            QListWidget::item:hover {
                background-color: #4a4a4a;
            }
            QListWidget::item:selected {
                background-color: #4a90e2;
            }
        """)
        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)
        self.results_list.itemDoubleClicked.connect(self.open_app_url)
        # self.results_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # self.results_list.customContextMenuRequested.connect(self.show_app_context_menu)
        layout.addWidget(self.results_list)
        
        # Selected item info panel (for download button)
        self.selection_panel = QWidget()
        selection_layout = QHBoxLayout(self.selection_panel)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet("color: #aaa; font-size: 11px;")
        selection_layout.addWidget(self.selection_label, 1)
        
        self.download_btn = QPushButton("Download & Install")
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.download_btn.clicked.connect(self.download_selected)
        self.download_btn.hide()
        selection_layout.addWidget(self.download_btn)
        
        layout.addWidget(self.selection_panel)
        
        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #3b3b3b;
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Loading tools...")
        self.status_label.setStyleSheet("color: #888; font-size: 11px; padding: 4px;")
        layout.addWidget(self.status_label)
        
        # Buttons row
        btn_layout = QHBoxLayout()
        
        open_btn = QPushButton("Open Tool Page")
        open_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        open_btn.clicked.connect(lambda: self.open_app_url(self.results_list.currentItem()))
        btn_layout.addWidget(open_btn)
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def open_login(self):
        """Open Patreon login in browser and wait for validation"""
        if not auth_manager:
            return
        
        # Start login flow
        token = auth_manager.login()
        
        def on_success(result):
            # Show message to restart the tray app
            QMessageBox.information(self, "Login Successful!", 
                f"Welcome {result['name']}!\n\n" +
                f"Tier: {auth_manager.format_tier_name(result['tier'])}\n\n" +
                "Please restart the GGF Tray app to see your new tier in the tray menu.")
            # Close this window
            self.close()
        
        def on_failed():
            QMessageBox.warning(self, "Login Timeout", 
                "Login timed out after 2 minutes.\n\n" +
                "Please try again and complete the login faster.")
        
        poller = LoginPoller(token, auth_manager)
        poller.success.connect(on_success)
        poller.failed.connect(on_failed)
        poller.start()
        
        # Store reference so it doesn't get garbage collected
        self.login_poller = poller
    
    def load_tools(self):
        """Load tools from JSON"""
        try:
            with urllib.request.urlopen('https://getgoingfast.pro/tools/tools-list.json', timeout=10) as response:
                data = json.loads(response.read().decode())
                self.tools_data = data.get('tools', [])
                self.filter_results()
                self.status_label.setText(f"Loaded {len(self.tools_data)} tools")
        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
    
    def on_selection_changed(self):
        """Handle selection change - show/hide download button"""
        item = self.results_list.currentItem()
        if not item:
            self.download_btn.hide()
            self.selection_label.setText("")
            self.current_selection = None
            return
        
        # Find the full tool data
        tool_name = item.text()
        tool_data = next((t for t in self.tools_data if t.get('name') == tool_name), None)
        
        if not tool_data:
            self.download_btn.hide()
            self.selection_label.setText("")
            self.current_selection = None
            return
        
        self.current_selection = tool_data
        
        # Check tier access
        # JSON membership values: free, pd (prairie dog only), fh (farm hand/premium only)
        # User tiers: free, prairie-dog, farm-hand, rancher, gunslinger
        required_membership = tool_data.get('membership', 'free')
        user_tier = auth_manager.get_tier() if auth_manager else 'free'
        
        # Determine access based on user tier and required membership
        has_access = False
        if user_tier in ['farm-hand', 'rancher', 'gunslinger']:
            # Farm Hand/Rancher/Gunslinger get everything (all are Farm Hand tier or above)
            has_access = True
        elif user_tier == 'prairie-dog':
            # Prairie Dog gets free and pd
            has_access = required_membership in ['free', 'pd']
        else:  # free
            # Free only gets free
            has_access = required_membership == 'free'
        
        # Show selection info
        self.selection_label.setText(f"Selected: {tool_name}")
        
        # Show download button only if:
        # 1. Tool has a slug (needed for download API)
        # 2. User has tier access to this tool
        tool_slug = tool_data.get('slug', '')
        if tool_slug and has_access:
            self.download_btn.show()
            self.download_btn.setEnabled(True)
        else:
            self.download_btn.hide()
    
    def download_selected(self):
        """Download and install selected tool"""
        if not self.current_selection:
            return
        
        tool_slug = self.current_selection.get('slug', '')
        tool_name = self.current_selection.get('name', 'tool')
        
        if not tool_slug:
            QMessageBox.warning(self, "No Slug", "This tool doesn't have a slug identifier.")
            return
        
        # Get user's auth token
        user_token = ''
        if auth_manager and auth_manager.is_authenticated():
            auth_data = auth_manager.get_auth()
            user_token = auth_data.get('token', '') if auth_data else ''
        
        if not user_token:
            QMessageBox.warning(self, "Not Authenticated", 
                "You need to be logged in to download.\n\n" +
                "Click 'Login with Patreon' first.")
            return
        
        # Build download URL using the API
        encoded_slug = urllib.parse.quote(tool_slug)
        encoded_token = urllib.parse.quote(user_token)
        download_url = f"https://getgoingfast.pro/download-api.php?slug={encoded_slug}&token={encoded_token}"
        _log(f"download_selected: slug={tool_slug} url={download_url}")
        
        # Disable UI during download
        self.download_btn.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        
        # Start download in thread
        self.download_worker = DownloadWorker(download_url, tool_slug)
        self.download_worker.progress.connect(self.on_download_progress)
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.start()
    
    def on_download_progress(self, percent, message):
        """Update progress bar"""
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)
    
    def on_download_finished(self, success, message, file_path, file_ext):
        """Handle download completion"""
        self.progress_bar.hide()
        self.download_btn.setEnabled(True)
        
        if not success:
            QMessageBox.critical(self, "Error", message)
            self.status_label.setText("Download failed")
            return
        
        # Handle based on file type
        if file_ext in ('.zip', '.rar'):
            # ZIP file - save to Downloads\ggf first
            downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads', 'ggf')
            os.makedirs(downloads_dir, exist_ok=True)
            
            zip_filename = os.path.basename(file_path)
            permanent_path = os.path.join(downloads_dir, zip_filename)
            shutil.move(file_path, permanent_path)
            installer_opened = False
            try:
                script_dir = APP_DIR
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0
                if getattr(sys, 'frozen', False):
                    subprocess.Popen(
                        [sys.executable, "--install-zip", permanent_path, "--auto-install"],
                        cwd=script_dir,
                        creationflags=creationflags,
                        env=get_subprocess_env()
                    )
                else:
                    tray_script = os.path.join(script_dir, "ggf-tray.py")
                    subprocess.Popen(
                        [sys.executable, tray_script, "--install-zip", permanent_path, "--auto-install"],
                        cwd=script_dir,
                        creationflags=creationflags
                    )
                installer_opened = True
            except Exception as e:
                QMessageBox.warning(self, "Installer Error",
                    f"Downloaded: {zip_filename}\n\n" +
                    f"Saved to: {downloads_dir}\n\n" +
                    f"Could not open installer:\n{str(e)}")
            if installer_opened:
                QMessageBox.information(self, "Download Complete",
                    f"Downloaded: {zip_filename}\n\n" +
                    "Opening the GGF installer now.")
                self.status_label.setText("Download complete - installer opened")
                return
            
            # Inform user where file was saved and how to install
            QMessageBox.information(self, "Download Complete",
                f"Downloaded: {zip_filename}\n\n" +
                f"Saved to: {downloads_dir}\n\n" +
                "To install this app:\n" +
                "1. Right-click the GGF Tray icon\n" +
                "2. Select 'A.I. Apps → Install GGF Apps'\n" +
                "3. Browse to the downloaded ZIP file")
            
            self.status_label.setText("Download complete!")
        else:
            # Non-ZIP file - ask where to save (default to ~/Downloads/ggf)
            from PyQt6.QtWidgets import QFileDialog
            default_name = os.path.basename(file_path)
            downloads_ggf = os.path.join(os.path.expanduser('~'), 'Downloads', 'ggf')
            os.makedirs(downloads_ggf, exist_ok=True)
            save_path, _ = QFileDialog.getSaveFileName(self, "Save File",
                os.path.join(downloads_ggf, default_name), "All Files (*.*)")
            
            if save_path:
                shutil.move(file_path, save_path)
                _log(f"File saved to: {save_path}")
                
                if file_ext in ['.exe', '.bat']:
                    reply = QMessageBox.question(self, "Run Now?",
                        f"File saved to:\n{save_path}\n\n" +
                        f"Would you like to run this {file_ext[1:].upper()} now?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        try:
                            file_dir = os.path.dirname(save_path)
                            file_name = os.path.basename(save_path)
                            _log(f"Launching: {save_path}")
                            if file_ext == '.bat':
                                subprocess.Popen(
                                    f'start "GGF" cmd /k "cd /d "{file_dir}" && "{file_name}""',
                                    shell=True
                                )
                            else:
                                subprocess.Popen(save_path, shell=True)
                            QMessageBox.information(self, "Launched", "Script/application started!")
                        except Exception as e:
                            _log(f"Launch error: {e}")
                            QMessageBox.warning(self, "Error", f"Failed to launch:\n{str(e)}")
                else:
                    QMessageBox.information(self, "Success", f"File saved to:\n{save_path}")
                
                self.status_label.setText("File saved!")
            else:
                try:
                    os.remove(file_path)
                except:
                    pass
                self.status_label.setText("Download cancelled")
    
    def filter_results(self):
        """Filter results based on search criteria"""
        self.results_list.clear()
        self.url_mapping.clear()
        self.current_selection = None
        self.download_btn.hide()
        
        search_text = self.search_input.text().lower()
        type_filter = self.type_filter.currentText().lower()
        
        index = 0
        for tool in self.tools_data:
            name = tool.get('name', '').lower()
            type1 = tool.get('type1', '').lower()
            
            # Check search text
            if search_text and search_text not in name:
                continue
            
            # Check type filter
            if type_filter != "type (all)":
                if type_filter == "comfyui":
                    if type1 != "comfy":
                        continue
                elif type1 != type_filter:
                    continue
            
            # Add to results
            item = QListWidgetItem(tool.get('name', ''))
            item.setData(Qt.ItemDataRole.UserRole, tool.get('url', ''))
            self.results_list.addItem(item)
            self.url_mapping[index] = tool.get('url', '')
            index += 1
        
        if self.results_list.count() == 0:
            self.results_list.addItem("No results found")
            self.status_label.setText("No matching apps")
        else:
            self.status_label.setText(f"Found {self.results_list.count()} apps")
    
    def open_app_url(self, item):
        """Open selected app in browser"""
        if item:
            url = item.data(Qt.ItemDataRole.UserRole)
            if url:
                # Check if URL already contains a full domain (starts with http)
                if url.startswith('http://') or url.startswith('https://'):
                    full_url = url
                # Check for special domains
                elif '/rope' in url.lower():
                    full_url = f"https://ropedownload.com{url}"
                elif '/roop' in url.lower():
                    full_url = f"https://roopdownload.com{url}"
                else:
                    # Standard apps use getgoingfast.pro
                    full_url = f"https://getgoingfast.pro{url}"
                webbrowser.open(full_url)


    def show_app_context_menu(self, pos):
        """Right-click context menu on app list - show URLs for debugging (disabled)"""
        return  # commented out - re-enable for debugging
        from PyQt6.QtWidgets import QMenu
        item = self.results_list.itemAt(pos)
        if not item:
            return
        tool_name = item.text()
        tool_data = next((t for t in self.tools_data if t.get('name') == tool_name), None)
        if not tool_data:
            return

        slug = tool_data.get('slug', '')
        page_url = tool_data.get('url', '')
        if slug:
            dl_url = f"https://getgoingfast.pro/download-api.php?slug={urllib.parse.quote(slug)}&token=<token>"
        else:
            dl_url = "(no slug)"

        if page_url:
            full_page = page_url if page_url.startswith('http') else f"https://getgoingfast.pro{page_url}"
        else:
            full_page = "(no page url)"

        _log(f"Right-click: {tool_name} | slug={slug} | dl_url={dl_url} | page={full_page}")

        menu = QMenu(self)
        act_dl   = menu.addAction(f"📋 Copy Download URL  (slug: {slug or 'none'})")
        act_page = menu.addAction(f"🌐 Copy Page URL")
        act_open = menu.addAction(f"🔗 Open Page in Browser")
        action = menu.exec(self.results_list.mapToGlobal(pos))

        if action == act_dl:
            QApplication.clipboard().setText(dl_url)
            self.status_label.setText(f"Copied download URL for: {tool_name}")
        elif action == act_page:
            QApplication.clipboard().setText(full_page)
            self.status_label.setText(f"Copied page URL for: {tool_name}")
        elif action == act_open:
            webbrowser.open(full_page)


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    
    # Create and show dialog
    dialog = SearchDialog()
    dialog.show()
    
    # Run the Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
