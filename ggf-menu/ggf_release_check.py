"""Exercise the installed Windows libraries in the executable's --self-test."""
import os
from pathlib import Path
import subprocess
import wave


def check(state, encoder):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from ggf_player import MusicPlayer

    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    app = QApplication.instance() or QApplication(["GGF self-test", "-platform", "offscreen"])
    player = MusicPlayer()
    browser = QWebEngineView()
    loop = QEventLoop()
    results = []

    def done(value):
        results.append(value)
        loop.quit()

    def loaded(ok):
        if ok:
            browser.page().runJavaScript("document.title", 0, done)
        else:
            done(None)

    browser.loadFinished.connect(loaded)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(30000)
    browser.setHtml("<title>GGF WebEngine test</title>")
    loop.exec()
    timeout.stop()
    player.close()
    browser.close()
    if results != ["GGF WebEngine test"]:
        raise RuntimeError("The visualizer browser engine did not render its test page")

    # A real encode catches missing encoder dependencies on a clean Windows system.
    import tempfile
    with tempfile.NamedTemporaryFile(dir=state, suffix=".wav", delete=False) as output:
        path = Path(output.name)
    subprocess.run([encoder, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=0.2", "-ar", "16000", "-ac", "1",
                    "-c:a", "pcm_s16le", "-y", str(path)], check=True, timeout=20,
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    with wave.open(str(path)) as audio:
        if audio.getnframes() != 3200 or audio.getframerate() != 16000:
            raise RuntimeError("The installed encoder produced unexpected WAV audio")
