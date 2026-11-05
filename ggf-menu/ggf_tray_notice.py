"""First interactive launch: a small, non-activating card by the Windows clock."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)
from ggf_catalog_window import launch_catalog
from ggf_runtime import get_app_dir, get_resource_dir
from ggf_welcome_state import managed_install, tray_notice_marker


def clock_corner(screen):
    """Locate the clock on the primary taskbar, including top/side and RTL layouts."""
    api = ctypes.WinDLL("user32")
    api.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    api.FindWindowW.restype = wintypes.HWND
    api.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    api.FindWindowExW.restype = wintypes.HWND
    api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    rect = wintypes.RECT()
    taskbar = api.FindWindowW("Shell_TrayWnd", None)
    clock = api.FindWindowExW(taskbar, None, "TrayNotifyWnd", None) if taskbar else None
    full, work = screen.geometry(), screen.availableGeometry()
    if clock and api.GetWindowRect(clock, ctypes.byref(rect)):
        # Windows anchors the primary display at (0,0). Convert native to Qt pixels.
        scale = screen.devicePixelRatio()
        return ((rect.left + rect.right) / (2 * scale) >= full.width() / 2,
                (rect.top + rect.bottom) / (2 * scale) >= full.height() / 2)
    return (work.left() - full.left() <= full.right() - work.right(),
            work.top() - full.top() <= full.bottom() - work.bottom())


class TrayNotice(QDialog):
    def __init__(self, screen):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Get Going Fast Tray")
        self.setObjectName("card")
        self.setStyleSheet("""
            QDialog#card { background: #14232c; border: 1px solid #50707d; }
            QLabel { color: #e2edf0; }
            QLabel#title { color: #ffffff; font-weight: 700; font-size: 13pt; }
            QPushButton { background: #233b47; color: #f4fafb; border: 1px solid #68818c;
                          border-radius: 5px; padding: 5px 12px; }
            QPushButton#catalog { background: #63e6d1; color: #10282a; border-color: #63e6d1; font-weight: 600; }
            QPushButton:hover { border-color: #a3f6e8; }
            QPushButton:focus { border: 2px solid #ffffff; }
            QPushButton#folder { padding: 2px 0; color: #93e6d7; background: transparent;
                                 text-decoration: underline; border-color: transparent; }
            QPushButton#folder:focus { border-color: #ffffff; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        header = QHBoxLayout()
        mark = QLabel()
        icon = QIcon(str(Path(get_resource_dir()) / "ggf-mark.ico"))
        self.setWindowIcon(icon)
        mark.setPixmap(icon.pixmap(28, 28))
        header.addWidget(mark)
        title = QLabel("GGF Tray is installed" if managed_install() else "GGF Tray is running")
        title.setObjectName("title")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        layout.addLayout(header)
        self.copy = QLabel("Right-click the turquoise G by the clock for apps and tools. "
                           "If you don’t see it, click the up arrow by the clock first.")
        self.copy.setWordWrap(True)
        layout.addWidget(self.copy)
        folder = QPushButton("Open GGF Tray folder")
        folder.setObjectName("folder")
        folder.clicked.connect(lambda: self.open_action(lambda: os.startfile(get_app_dir())))
        folder.setToolTip(get_app_dir())
        layout.addWidget(folder, 0, Qt.AlignLeft)
        actions = QHBoxLayout()
        catalog = QPushButton("Open catalog")
        catalog.setObjectName("catalog")
        catalog.clicked.connect(lambda: self.open_action(launch_catalog))
        done = QPushButton("Got it")
        done.clicked.connect(self.accept)
        for button in (folder, catalog, done):
            button.setAutoDefault(False)
            button.setCursor(Qt.PointingHandCursor)
        actions.addWidget(catalog)
        actions.addWidget(done)
        actions.addStretch()
        layout.addLayout(actions)
        self.setTabOrder(catalog, done)
        self.setTabOrder(done, folder)
        self.place(screen)

    def place(self, screen):
        area = screen.availableGeometry().adjusted(10, 10, -10, -10)
        self.setFixedWidth(min(max(345, self.minimumSizeHint().width()), area.width()))
        self.adjustSize()
        right, bottom = clock_corner(screen)
        self.move(area.right() + 1 - self.width() if right else area.left(),
                  max(area.top(), area.bottom() + 1 - self.height()) if bottom else area.top())

    def open_action(self, action):
        try:
            action()
        except OSError as exc:
            self.copy.setText(f"Could not open it: {exc}")
            self.place(self.screen())
            return
        self.accept()

    def expire(self):
        # Give anyone reading with the pointer or keyboard time to finish.
        if self.underMouse() or self.isActiveWindow():
            QTimer.singleShot(10000, self.expire)
        else:
            self.accept()


def main():
    marker = tray_notice_marker()
    if marker.is_file():
        return 0
    app = QApplication(sys.argv[:1])
    notice = TrayNotice(app.primaryScreen())
    notice.finished.connect(app.quit)
    notice.show()
    def displayed():
        if not notice.windowHandle().isExposed():
            QTimer.singleShot(100, displayed)
            return
        try:
            marker.touch(exist_ok=True)
        except OSError:
            pass
        QTimer.singleShot(30000, notice.expire)
    QTimer.singleShot(0, displayed)
    return app.exec()
