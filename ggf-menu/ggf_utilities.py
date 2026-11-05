"""Qt entry points for the Windows tray's file, model and member utilities."""
import os
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, quote

from PySide6.QtCore import Qt, QThread, QTimer, QSettings, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QListWidget, QFileDialog, QProgressBar, QSpinBox,
    QSplitter, QAbstractItemView,
)
from ggf_auth_token import AuthManager
from ggf_runtime import get_resource_dir, get_state_dir, redact_secrets
import ggf_hub as hub
import ggf_media as media


def label(text=""):
    widget=QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def row(layout):
    result=QHBoxLayout()
    layout.addLayout(result)
    return result


def button(layout,text,callback):
    widget=QPushButton(text)
    widget.clicked.connect(callback)
    layout.addWidget(widget)
    return widget


class Job(QThread):
    progress=Signal(int,str)

    def __init__(self,work,parent):
        super().__init__(parent)
        self.work=work
        self.stop=threading.Event()
        self.value=None
        self.error=""

    def run(self):
        try:
            self.value=self.work(self.stop,self.progress.emit)
        except Exception as error:
            self.error="Cancelled" if self.stop.is_set() else redact_secrets(str(error) or type(error).__name__)


class ToolWindow(QWidget):
    def __init__(self,title):
        super().__init__()
        self.setWindowTitle("GGF • "+title)
        self.setWindowIcon(QIcon(os.path.join(get_resource_dir(),"ggf-mark.ico")))
        self.resize(780,560)
        self.task=None
        self.closing=False
        layout=QVBoxLayout(self)
        layout.setContentsMargins(18,16,18,16)
        heading=label(title)
        heading.setStyleSheet("font-size:18pt;font-weight:600")
        layout.addWidget(heading)
        self.panel=QWidget()
        self.body=QVBoxLayout(self.panel)
        self.body.setContentsMargins(0,4,0,4)
        layout.addWidget(self.panel,1)
        self.status=label()
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        footer=row(layout)
        self.bar=QProgressBar()
        footer.addWidget(self.bar,1)
        self.cancel=button(footer,"Cancel",self.interrupt)
        self.bar.hide()
        self.cancel.hide()

    def progress(self,percent,text):
        self.status.setText(text)
        self.bar.setRange(0,0 if percent<0 else 100)
        if percent>=0: self.bar.setValue(min(100,percent))

    def start(self,text,work,done):
        if self.task: return
        self.completed=done
        self.panel.setEnabled(False)
        self.bar.show()
        self.cancel.show()
        self.cancel.setEnabled(True)
        self.progress(-1,text)
        self.task=Job(work,self)
        self.task.progress.connect(self.progress)
        self.task.finished.connect(self.finish)
        self.task.start()

    def finish(self):
        job=self.task
        self.task=None
        self.panel.setEnabled(True)
        self.bar.hide()
        self.cancel.hide()
        job.deleteLater()
        if self.closing:
            self.close()
        elif job.error:
            self.status.setText(job.error)
        else:
            try: self.completed(job.value)
            except Exception as exc: self.status.setText(redact_secrets(exc))

    def interrupt(self):
        if self.task:
            self.task.stop.set()
            self.cancel.setEnabled(False)
            self.status.setText("Cancelling…")

    def closeEvent(self,event):
        if self.task:
            self.closing=True
            self.interrupt()
            event.ignore()
        else: event.accept()


def choose_directory(parent,initial):
    return QFileDialog.getExistingDirectory(parent,"Choose a folder",str(initial or Path.home()))


def show_folder(path):
    if path and Path(path).is_dir(): os.startfile(str(path))


def clipboard_paths():
    data=QApplication.clipboard().mimeData()
    if not data: return []
    names=[u.toLocalFile() for u in data.urls() if u.isLocalFile()]
    if not names and data.hasText():
        names=[line.strip().strip('"') for line in data.text().splitlines()]
    result=[]
    for name in names:
        try:
            if name and Path(name).is_absolute() and Path(name).is_file(): result.append(name)
        except (OSError,ValueError): pass
    return result


TITLES={"download":"Download video","convert_video":"Convert video or extract audio",
        "resize_image":"Resize images","shrink_video":"Shrink video",
        "save_first_frame":"Save first frame","save_last_frame":"Save last frame"}


class MediaWindow(ToolWindow):
    def __init__(self,action):
        super().__init__(TITLES.get(action,"Convert to "+action.removeprefix("convert_").upper()))
        self.action=action
        self.paths=[]
        self.folder=""
        self.last_folder=None
        self.results=[]
        self.url=QLineEdit()
        self.files=QListWidget()
        self.format=QComboBox()
        self.quality=QComboBox()
        for name in ("From settings","Compact","Balanced","High"):
            self.quality.addItem(name)
        self.percent=QSpinBox()
        self.percent.setRange(1,400)
        self.percent.setSuffix(" %")
        try: self.percent.setValue(media.settings().getint("Image","resize_percent",fallback=50))
        except ValueError: self.percent.setValue(50)
        if action=="download":
            self.folder=str(Path.home()/"Downloads")
            self.body.addWidget(label("Video URL"))
            self.url.setPlaceholderText("https://…")
            clip=QApplication.clipboard().text().strip()
            if clip.startswith(("https://","http://")): self.url.setText(clip)
            self.body.addWidget(self.url)
            self.body.addStretch(1)
            self.resize(660,255)
        else:
            actions=row(self.body)
            button(actions,"Add files…",self.browse)
            button(actions,"Paste files",lambda:self.add_files(clipboard_paths()))
            button(actions,"Remove from list",self.remove_selected)
            actions.addStretch()
            self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.body.addWidget(self.files,1)
            self.setAcceptDrops(True)
            self.add_files(clipboard_paths())
            if action=="convert_video" or action.removeprefix("convert_") in media.AUDIO:
                fmt=row(self.body)
                fmt.addWidget(label("Export as"))
                formats=media.VIDEO+media.AUDIO if action=="convert_video" else media.AUDIO
                for ext in formats:
                    self.format.addItem(ext.upper()+(" • audio only" if ext in media.AUDIO else ""),ext)
                if action!="convert_video":
                    self.format.setCurrentIndex(self.format.findData(action.removeprefix("convert_")))
                fmt.addWidget(self.format,1)
                fmt.addWidget(label("Quality"))
                fmt.addWidget(self.quality)
                def update_quality():
                    self.quality.setEnabled(self.format.currentData() not in ("wav","flac","gif","avi"))
                self.format.currentIndexChanged.connect(update_quality)
                update_quality()
            if action=="resize_image":
                r=row(self.body)
                r.addWidget(label("Scale"))
                r.addWidget(self.percent)
                r.addStretch()
        r=row(self.body)
        self.where=label(self.folder or "Save beside each original")
        r.addWidget(self.where,1)
        button(r,"Output folder…",self.pick_folder)
        if action!="download": button(r,"Beside originals",lambda:self.set_folder(""))
        r=row(self.body)
        self.reveal=button(r,"Open output folder",lambda:show_folder(self.last_folder))
        self.reveal.hide()
        r.addStretch()
        self.run_button=button(r,"Download" if action=="download" else "Export",self.run_task)
        self.status.setText("Ready." if action=="download" or self.paths else "Drop files here or choose Add files.")

    def dragEnterEvent(self,event):
        if not self.task and event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self,event):
        if not self.task:
            self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()

    def add_files(self,names):
        for name in names:
            path=Path(name).absolute()
            if path.is_file() and path not in self.paths:
                self.paths.append(path)
                self.files.addItem(str(path))

    def browse(self):
        files,_=QFileDialog.getOpenFileNames(self,"Choose files to export",str(self.paths[-1].parent if self.paths else Path.home()))
        self.add_files(files)

    def remove_selected(self):
        for i in sorted({self.files.row(item) for item in self.files.selectedItems()},reverse=True):
            self.files.takeItem(i)
            self.paths.pop(i)

    def set_folder(self,path):
        self.folder=path
        self.where.setText(path or "Save beside each original")

    def pick_folder(self):
        path=choose_directory(self,self.folder or (self.paths[0].parent if self.paths else None))
        if path: self.set_folder(path)

    def run_task(self):
        self.reveal.hide()
        folder=self.folder
        if self.action=="download":
            url=self.url.text().strip()
            self.start("Requesting video…",lambda stop,progress:media.download_video(url,folder,stop,progress),self.video_saved)
            return
        paths=list(self.paths)
        if not paths:
            self.browse()
            paths=list(self.paths)
            if not paths: return
        ext=self.format.currentData()
        percent=self.percent.value()
        quality=self.quality.currentText() if self.quality.isEnabled() and self.quality.currentIndex()>0 else None
        action=("convert_"+ext if self.action.removeprefix("convert_") in media.AUDIO else self.action)
        def batch(stop,progress):
            results=[]
            for i,path in enumerate(paths):
                if stop.is_set(): break
                prefix=f"{i+1} of {len(paths)} • {path.name}"
                def update(n,msg):
                    progress(-1 if n<0 else int((i+n/100)*100/len(paths)),prefix+" • "+msg)
                update(-1,"Starting")
                try:
                    out=media.convert(path,folder,action,ext,percent,stop,update,quality)
                    results.append((path,out,""))
                except InterruptedError as exc:
                    results.append((path,None,str(exc)))
                    break
                except Exception as exc:
                    results.append((path,None,str(exc)))
            return results,stop.is_set()
        self.start("Starting export…",batch,self.batch_done)

    def video_saved(self,path):
        self.last_folder=path.parent
        self.reveal.show()
        self.status.setText(f"Saved {path}")

    def batch_done(self,answer):
        results,cancelled=answer
        good=[out for _,out,_ in results if out]
        for path,out,error in results:
            item=self.files.item(self.paths.index(path))
            if out:
                note=f"Saved {out.name}"
                if self.action=="shrink_video":
                    a=path.stat().st_size
                    b=out.stat().st_size
                    note+=f" ({b/1024**2:.2f} MiB, {abs(b-a)/max(1,a):.0%} {'smaller' if b<a else 'larger'})"
            else: note="Failed • "+error
            item.setText(path.name+"  →  "+note)
            item.setToolTip(str(out or error))
        if good:
            self.last_folder=good[-1].parent
            self.reveal.show()
        issues=[err for _,_,err in results if err]
        self.status.setText(("Cancelled. " if cancelled else "")+f"Saved {len(good)} of {len(self.paths)}."+
                            (" "+issues[0][:300] if issues else " "+str(good[-1]) if good else ""))


def size_text(size):
    return f"{size/1024**3:.2f} GiB" if size>=1024**3 else f"{size/1024**2:.2f} MiB"


class HubWindow(ToolWindow):
    def __init__(self):
        super().__init__("Hugging Face Model Browser")
        self.resize(900,620)
        self.cursor=None
        self.query=""
        self.models=[]
        self.items=[]
        self.repo=""
        self.preferences=QSettings(str(Path(get_state_dir())/"model-browser.ini"),QSettings.Format.IniFormat)
        r=row(self.body)
        self.term=QLineEdit()
        self.term.setPlaceholderText("Search models, paste a repository ID or a Hugging Face model URL")
        r.addWidget(self.term,1)
        button(r,"Search",self.find)
        self.term.returnPressed.connect(self.find)
        splitter=QSplitter(Qt.Orientation.Horizontal)
        self.repos=QListWidget()
        self.repos.currentTextChanged.connect(self.load_files)
        splitter.addWidget(self.repos)
        self.weights=QListWidget()
        self.weights.currentRowChanged.connect(self.selection)
        splitter.addWidget(self.weights)
        splitter.setStretchFactor(1,2)
        self.body.addWidget(splitter,1)
        r=row(self.body)
        self.more=button(r,"More repositories",lambda:self.find(True))
        self.more.setEnabled(False)
        self.repo_page=button(r,"Model page",self.open_page)
        self.repo_page.setEnabled(False)
        self.types=QComboBox()
        for name,ext in [("SafeTensors",".safetensors"),("GGUF",".gguf"),("All weight formats","")]: self.types.addItem(name,ext)
        self.types.currentIndexChanged.connect(self.filter)
        r.addWidget(self.types)
        self.file_filter=QLineEdit()
        self.file_filter.setPlaceholderText("Filter filenames or quantizations")
        self.file_filter.textChanged.connect(self.filter)
        r.addWidget(self.file_filter,1)
        r=row(self.body)
        self.dest=QComboBox()
        r.addWidget(self.dest,1)
        button(r,"Choose folder…",self.pick_dir)
        button(r,"Use ComfyUI…",self.pick_comfy)
        self.where=str(self.preferences.value("directory","") or "")
        self.comfy=str(self.preferences.value("comfy","") or "")
        if not self.where and not self.comfy:
            self.comfy=media.settings().get("Paths","comfyui_path",fallback="")
        self.destinations()
        self.dest.currentIndexChanged.connect(self.save_folder_choice)
        controls=row(self.body)
        self.info=label("Choose a repository and a file.")
        controls.addWidget(self.info,1)
        self.reveal=button(controls,"Open folder",lambda:show_folder(self.dest.currentData()))
        self.get=button(controls,"Download",self.download)
        self.get.setEnabled(False)
        self.status.setText("Search public Hugging Face models.")

    def destinations(self):
        self.dest.clear()
        if self.comfy and (Path(self.comfy)/"models").is_dir():
            folders=sorted((p for p in (Path(self.comfy)/"models").iterdir() if p.is_dir()),key=lambda p:p.name.casefold())
            for p in folders: self.dest.addItem("ComfyUI / models / "+p.name,str(p))
            i=self.dest.findData(self.where)
            if i<0: i=self.dest.findData(str(Path(self.comfy)/"models/checkpoints"))
            if i>=0: self.dest.setCurrentIndex(i)
        else:
            fallback=Path.home()/"Downloads"
            self.dest.addItem(self.where or str(fallback),self.where or str(fallback))

    def save_folder_choice(self):
        if self.dest.currentData():
            self.where=self.dest.currentData()
            self.preferences.setValue("directory",self.where)

    def pick_dir(self):
        folder=choose_directory(self,self.dest.currentData())
        if folder:
            self.comfy="";self.where=folder
            self.preferences.setValue("comfy","")
            self.destinations()
            self.save_folder_choice()

    def pick_comfy(self):
        folder=choose_directory(self,self.comfy)
        if not folder: return
        models=Path(folder)/"models"
        if not models.is_dir() or not any(p.is_dir() for p in models.iterdir()):
            self.status.setText("Choose the ComfyUI folder that contains models and its subfolders.")
            return
        self.comfy=folder
        self.preferences.setValue("comfy",folder)
        self.dest.blockSignals(True)
        self.destinations()
        self.dest.blockSignals(False)
        self.save_folder_choice()

    def find(self,more=False):
        query=self.query if more else self.term.text().strip()
        if not query: self.status.setText("Enter a model name or repository ID.");return
        cursor=self.cursor if more else None
        if not more:
            self.query=query
            self.cursor=None
            self.more.setEnabled(False)
            self.repos.clear()
            self.load_files("")
        def listed(answer):
            repos,self.cursor=answer
            self.more.setEnabled(bool(self.cursor))
            known={self.repos.item(i).text() for i in range(self.repos.count())}
            for repo in repos:
                if repo not in known: self.repos.addItem(repo)
            self.status.setText(f"{self.repos.count()} repositories. Select one to inspect its files.")
            if self.repos.count() and self.repos.currentRow()<0: self.repos.setCurrentRow(0)
        fmt=self.types.currentData()
        self.start("Searching Hugging Face…",lambda stop,p:hub.search(query,cursor,fmt),listed)

    def load_files(self,repo):
        self.repo=repo
        self.models=[]
        self.filter()
        self.repo_page.setEnabled(bool(repo))
        if not repo: return
        def loaded(items):
            self.models=items
            self.filter()
            self.status.setText(f"{len(items)} weight choices in {repo}." if items else "This repository lists no supported weights. Open Model page for other files.")
        self.start("Reading repository files…",lambda stop,p:hub.list_files(repo,stop),loaded)

    def filter(self,*_):
        ext=self.types.currentData() or ""
        term=self.file_filter.text().casefold()
        self.items=[m for m in self.models if m.files[0].path.lower().endswith(ext) and term in m.label.casefold()]
        self.weights.clear()
        for m in self.items:
            self.weights.addItem(m.label+"   •   "+size_text(m.size)+(" • incomplete set" if m.missing else ""))
        if self.items: self.weights.setCurrentRow(0)
        else: self.selection(-1)

    def selection(self,index):
        m=self.items[index] if 0<=index<len(self.items) else None
        self.get.setEnabled(bool(m and not m.missing))
        self.info.setText(f"{len(m.files)} file(s) • {size_text(m.size)}" if m else "No matching weights. Try another file filter.")

    def open_page(self):
        if self.repo: webbrowser.open(hub.ORIGIN+"/"+quote(self.repo,safe="/"))

    def download(self):
        i=self.weights.currentRow()
        if not 0<=i<len(self.items): return
        model=self.items[i]
        target=self.dest.currentData()
        if not target: self.status.setText("Choose a download folder.");return
        def complete(paths):
            self.status.setText(f"Verified {len(paths)} file(s) in {Path(paths[0]).parent}")
        self.start("Checking destination…",lambda stop,p:hub.download(model,target,stop,p),complete)


PAID = {"prairie-dog","farm-hand","rancher","gunslinger"}
RESOURCE_URL="https://getgoingfast.pro/resources/"

def resource_access(manager):
    manager.load_cache()
    cached=manager.cached_auth or {}
    token=cached.get("token")
    if not token: return "guest"
    current=manager.check_token(token)
    manager.load_cache()
    if not current or (manager.cached_auth or {}).get("token")!=token: return "unverified"
    return "paid" if current.get("tier") in PAID else "locked"


class ResourcesWindow(ToolWindow):
    def __init__(self):
        super().__init__("GGF Resource Search")
        self.resize(640,255)
        self.term=QLineEdit()
        self.term.setPlaceholderText("Search workflows, LoRAs, prompts and presets")
        self.body.addWidget(self.term)
        self.member=label()
        self.body.addWidget(self.member)
        controls=row(self.body)
        self.check=button(controls,"Check membership",self.verify)
        self.account=button(controls,"Sign in to GGF",self.open_account)
        controls.addStretch()
        self.search=button(controls,"Open Resource Search",lambda:self.verify(True))
        self.search.setEnabled(False)
        self.term.returnPressed.connect(lambda:self.verify(True))
        self.body.addStretch(1)
        QTimer.singleShot(0,self.verify)

    def open_account(self):
        if self.account.text()=="View memberships":
            webbrowser.open("https://getgoingfast.pro/membership/")
        else:
            from ggf_catalog_window import launch_catalog
            launch_catalog()

    def verify(self,opening=False):
        self.search.setEnabled(False)
        def checked(state):
            self.search.setEnabled(state=="paid")
            self.account.setVisible(state!="paid")
            self.account.setText("View memberships" if state=="locked" else "Sign in to GGF")
            self.member.setText({"guest":"Sign in with your paid GGF account, then check membership.",
                                 "unverified":"Your desktop session could not be verified. Check your connection or sign in again.",
                                 "locked":"Resource Search requires Prairie Dog membership or higher.",
                                 "paid":"Paid access verified. Results open in your browser under your GGF member session."}[state])
            self.status.setText("")
            if opening and state=="paid":
                query=self.term.text().strip()
                webbrowser.open(RESOURCE_URL+("?"+urlencode({"q":query}) if query else ""))
        self.start("Checking your GGF membership…",lambda stop,p:resource_access(AuthManager()),checked)


def main(action):
    app=QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet("QWidget{background:#17212b;color:#f0f3f7;font:10pt 'Segoe UI'} QLineEdit,QComboBox,QListWidget,QSpinBox{background:#101923;border:1px solid #526477;padding:5px;border-radius:4px} QPushButton{background:#31597a;border:0;border-radius:4px;padding:7px 12px} QPushButton:disabled{background:#273542;color:#8b99a8} QListWidget::item{padding:4px} QListWidget::item:selected{background:#2d5477}")
    if action in media.ACTIONS: window=MediaWindow(action)
    elif action=="huggingface_browser": window=HubWindow()
    elif action=="resources": window=ResourcesWindow()
    else: raise ValueError("Unknown tray utility.")
    window.show()
    return app.exec()

