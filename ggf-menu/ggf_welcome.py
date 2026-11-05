"""User-paced guides that size independently of the visualizer canvas."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from ggf_runtime import get_resource_dir

TRAY_STEPS = (
    ("Find GGF by the clock",
     "Look for the turquoise G in the Windows notification area. If it’s hidden, click the up arrow by the clock. Right-click the G to open the tray menu."),
    ("Build your app library",
     "Browse the catalog and sign in to download a tool. After setup, open Quick Launch from the tray to run it again."),
    ("Use the tray your way",
     "The tray menu has media converters, the music player and model tools. Start silently with Windows is on by default. You can change it in the tray menu."),
)
MUSIC_STEPS = (
    ("Visualize your audio",
     "Play music on your PC. The visualizer responds to your sound. Use the gear to choose speakers or change the visual style."),
    ("Open the player or tray tools",
     "Click Menu at the bottom right for the music player, app catalog and tray tools. Close the visualizer with the × when you’re done."),
)

from ggf_welcome_state import welcome_seen, remember_welcome


class Guide(QDialog):
    def __init__(self, parent, *, music=False):
        super().__init__(parent)
        self.steps = MUSIC_STEPS if music else TRAY_STEPS
        self.step = 0
        self.setWindowTitle("GGF • Visualizer guide" if music else "Welcome to GGF Tray")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        icon = QIcon(str(Path(get_resource_dir()) / "ggf-mark.ico"))
        self.setWindowIcon(icon)
        self.setStyleSheet("""
            QDialog, QWidget#page {background:#101b25;color:#eff5fb}
            QLabel {background:transparent;color:#eff5fb;font:11pt 'Segoe UI';border:none}
            QLabel#title {font:600 14pt 'Segoe UI'}
            QLabel#counter {color:#a4becb;font:10pt 'Segoe UI'}
            QPushButton {border:1px solid #526a76;border-radius:5px;padding:6px 13px;
                         color:#f4f7fa;background:#20303c;font:10pt 'Segoe UI'}
            QPushButton#next {background:#3ce4cb;color:#082425;border-color:#3ce4cb;font-weight:bold}
            QScrollArea {background:transparent;border:0}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        top = QHBoxLayout()
        brand = QLabel()
        brand.setPixmap(icon.pixmap(32, 32))
        top.addWidget(brand)
        top.addStretch()
        self.counter = QLabel()
        self.counter.setObjectName("counter")
        top.addWidget(self.counter)
        layout.addLayout(top)
        # Navigation always remains outside the scrollable reading area.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("page")
        content = QVBoxLayout(page)
        content.setContentsMargins(0, 8, 6, 8)
        self.heading = QLabel()
        self.heading.setObjectName("title")
        self.copy = QLabel()
        for widget in (self.heading, self.copy):
            widget.setWordWrap(True)
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            content.addWidget(widget)
        content.addStretch()
        self.scroll.setWidget(page)
        layout.addWidget(self.scroll, 1)
        footer = QHBoxLayout()
        self.skip = QPushButton("Skip")
        self.skip.clicked.connect(self.reject)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self.move_step(-1))
        self.next = QPushButton()
        self.next.setObjectName("next")
        self.next.clicked.connect(lambda: self.move_step(1))
        self.next.setDefault(True)
        footer.addWidget(self.skip)
        footer.addStretch()
        footer.addWidget(self.back)
        footer.addWidget(self.next)
        layout.addLayout(footer)
        available = parent.screen().availableGeometry()
        self.resize(min(410, available.width()-12), min(242, available.height()-18))
        self.render_step()

    def render_step(self):
        title, body = self.steps[self.step]
        self.heading.setText(title)
        self.copy.setText(body)
        self.counter.setText(f"{self.step + 1} of {len(self.steps)}")
        self.back.setVisible(self.step > 0)
        self.next.setText("Done" if self.step == len(self.steps)-1 else "Next")
        QTimer.singleShot(0, self.fit_page)

    def fit_page(self):
        # Qt must know the wrapped height, particularly at high text scaling.
        page = self.scroll.widget()
        width = max(1,self.scroll.viewport().width()-6)
        height = sum(max(w.sizeHint().height(),w.heightForWidth(width)) for w in (self.heading,self.copy))
        page.setMinimumHeight(height + 16 + 2*page.layout().spacing())
        self.scroll.verticalScrollBar().setValue(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.fit_page)

    def move_step(self, delta):
        if self.step + delta == len(self.steps):
            self.accept()
            return
        self.step = max(0, self.step + delta)
        self.render_step()

