"""Browse the first-party catalog, link a GGF account and hand packages to setup."""
import hashlib
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from PySide6.QtCore import QEvent,Qt,QThread,QTimer,Signal
from PySide6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,
    QListWidget,QListWidgetItem,QPushButton,QProgressBar,QMessageBox,QInputDialog,QFileDialog)
from ggf_auth_token import AuthManager
from ggf_catalog import catalog,fetch,Variants,membership_allows_download,ORIGIN
from ggf_runtime import get_state_dir,get_app_dir,redact_secrets

class Worker(QThread):
    result=Signal(object); error=Signal(str); progress=Signal(object,object)
    def __init__(self,fn,parent):
        super().__init__(parent);self.fn=fn
    def run(self):
        try: result=self.fn(self)
        except Exception as exc: self.error.emit(redact_secrets(exc));return
        self.result.emit(result)

def start_setup(path):
    args=[sys.executable]
    if not getattr(sys,"frozen",False): args.append(str(Path(get_app_dir())/"ggf-tray.py"))
    env=os.environ.copy();env["PYINSTALLER_RESET_ENVIRONMENT"]="1"
    subprocess.Popen(args+["--install-zip",str(path)],env=env,cwd=get_app_dir())

from PySide6.QtGui import QIcon
from ggf_runtime import get_resource_dir
from ggf_catalog_window import CatalogOwner, activate_existing
from ggf_welcome import Guide, remember_welcome


class SearchDialog(QWidget):
    LINK_WINDOW = 20 * 60  # Allow time to receive and use a website login email.
    LINK_HELP = ("Sign in on the website, match the code, then choose Link Desktop App. "
                 "Already signed in somewhere else? Choose Continue in browser.")

    def __init__(self):
        super().__init__()
        self.guide = None
        self.setWindowIcon(QIcon(str(Path(get_resource_dir()) / "ggf-mark.ico")))
        self.auth=AuthManager();self.tools=[];self.jobs={};self.closing=False;self.offline=False
        self.pending_token=None
        self.link_timer=QTimer(self)
        self.link_timer.setSingleShot(True)
        self.link_timer.timeout.connect(self.check_pending)
        self.setWindowTitle("Get Going Fast • App catalog");self.resize(680,600); self.setMinimumSize(520,400)
        self.setStyleSheet("QWidget{background:#18202b;color:#e8edf4;font:10pt 'Segoe UI'} QLineEdit,QComboBox,QListWidget{background:#101822;border:1px solid #425267;border-radius:4px;padding:5px} QListWidget::item{padding:6px} QListWidget::item:selected{background:#294b70} QPushButton{padding:7px 12px;background:#315577;border:0;border-radius:4px} QPushButton:disabled{background:#273341;color:#8793a0} QPushButton:hover:enabled{background:#386c98}")
        box=QVBoxLayout(self);box.setContentsMargins(16,14,16,14)
        def row(): r=QHBoxLayout();box.addLayout(r);return r
        top=row(); heading=QLabel("GGF App Catalog");heading.setStyleSheet("font-size:17pt;font-weight:600");top.addWidget(heading,1)
        self.member=QLabel();top.addWidget(self.member)
        self.link=QPushButton();self.link.clicked.connect(self.signin);top.addWidget(self.link)
        r=row();self.link_hint=QLabel();self.link_hint.setWordWrap(True);self.link_hint.setTextFormat(Qt.TextFormat.PlainText);r.addWidget(self.link_hint,1)
        self.stop_link=QPushButton("Cancel sign-in");self.stop_link.clicked.connect(self.cancel_link);r.addWidget(self.stop_link)
        self.link_hint.hide();self.stop_link.hide()
        r=row();self.search=QLineEdit();self.search.setPlaceholderText("Search names and descriptions");r.addWidget(self.search,1)
        self.refresh=QPushButton("Refresh");self.refresh.clicked.connect(self.reload);r.addWidget(self.refresh)
        r=row()
        membership_label=QLabel("&Membership")
        self.membership=QComboBox()
        self.membership.setAccessibleName("Filter by membership access")
        self.membership.setToolTip("All shows every listing. Choose a membership to see everything it includes.")
        for title,tier in (("All",""),("Included with my membership","mine"),("Free","free"),
                           ("Prairie Dog","prairie-dog"),("Farm Hand","farm-hand")):
            self.membership.addItem(title,tier)
        membership_label.setBuddy(self.membership)
        r.addWidget(membership_label);r.addWidget(self.membership)
        self.type=QComboBox();self.type.setAccessibleName("Category");self.type.addItem("All categories","");r.addWidget(self.type)
        r.addStretch()
        self.results=QListWidget();box.addWidget(self.results,1);self.results.currentItemChanged.connect(self.select)
        self.details=QLabel("Select a tool.");self.details.setWordWrap(True);self.details.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.details)
        r=row();self.page=QPushButton("Tool page");self.page.clicked.connect(self.open_page);r.addWidget(self.page)
        self.get=QPushButton("Download");self.get.clicked.connect(lambda:self.download());r.addWidget(self.get)
        self.cancel=QPushButton("Cancel transfer");self.cancel.clicked.connect(lambda:self.jobs["transfer"].requestInterruption() if "transfer" in self.jobs else None);r.addWidget(self.cancel);self.cancel.hide()
        self.bar=QProgressBar();box.addWidget(self.bar);self.bar.hide()
        self.status=QLabel("Loading catalog…");self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.status)
        self.search.textChanged.connect(self.filter);self.type.currentIndexChanged.connect(self.filter);self.membership.currentIndexChanged.connect(self.filter);self.results.itemDoubleClicked.connect(self.open_page)
        self.update_auth();self.select();QTimer.singleShot(0,self.reload)
    def job(self,key,fn,done,failed=None):
        if key in self.jobs:return
        worker=Worker(fn,self);self.jobs[key]=worker
        # Deliver after QThread.finished: a continuation may safely start a new job with the same key.
        reply={}
        worker.result.connect(lambda value:reply.update(value=value))
        worker.error.connect(lambda error:reply.update(error=error))
        def finish():
            self.jobs.pop(key,None)
            if self.closing:
                if not self.jobs: self.close()
            elif "error" in reply: (failed or self.status.setText)(reply["error"])
            elif "value" in reply: done(reply["value"])
            self.select();worker.deleteLater()
        worker.finished.connect(finish);worker.progress.connect(self.progress);worker.start()
    def update_auth(self):
        previous_tier = getattr(self, "user", {}).get("tier")
        self.auth.load_cache();self.user=self.auth.cached_auth or {}
        if self.membership.currentData()=="mine" and previous_tier!=self.user.get("tier"):
            if self.user:
                self.filter()
            else:
                self.membership.setCurrentIndex(0)
        self.member.setTextFormat(Qt.TextFormat.PlainText)
        if self.pending_token:
            code=hashlib.sha256(self.pending_token.encode()).hexdigest()[:8].upper()
            self.member.setText("Link code: "+code)
            self.link.setText("Continue in browser")
            return
        self.member.setText(self.auth.format_tier_name(self.user["tier"]) if self.user else "Browsing as guest")
        self.link.setText("Sign out" if self.user else "Sign in")
    def refresh_membership(self):
        # Re-read the effective tier after upgrades. An offline catalog stays usable.
        if not self.user or self.pending_token or "auth" in self.jobs: return
        token=self.user.get("token")
        def apply(data):
            self.auth.load_cache()
            if "auth" in self.jobs or (self.auth.cached_auth or {}).get("token")!=token:return
            try:
                if data:self.auth.save_cache(data)
                else:
                    self.auth.clear_cache()
                    self.link_hint.setText("This desktop link is no longer active. Choose Sign in to link your account again.")
                    self.link_hint.show()
            except (OSError, RuntimeError, ValueError):
                self.status.setText("Windows could not update the saved account.")
            self.update_auth()
        def verify(w):
            try:return self.auth.verify_link(token)
            except PermissionError:return None
        self.job("membership",verify,apply)
    def signin(self):
        if "auth" in self.jobs or "transfer" in self.jobs:return
        if self.user and not self.pending_token:
            self.link.setEnabled(False)
            self.link_hint.hide()
            def signed(ok):
                self.link.setEnabled(True);self.update_auth();self.status.setText("Signed out." if ok else "Signed out here. Server revocation could not be confirmed.")
            def failed(message):
                self.link.setEnabled(True);self.update_auth();self.status.setText("Sign-out did not finish: "+message)
            self.job("auth",lambda w:self.auth.logout(),signed,failed);return
        if not self.pending_token or time.monotonic() >= self.link_deadline:
            self.pending_token=self.auth.generate_token()
            self.link_deadline=time.monotonic()+self.LINK_WINDOW
        self.update_auth()
        self.stop_link.show();self.link_hint.show();self.link_hint.setText(self.LINK_HELP)
        try: opened=self.auth.open_link(self.pending_token)
        except (OSError, webbrowser.Error): opened=False
        self.pending_help=self.LINK_HELP if opened else "The browser did not open. Check your default browser, then choose Continue in browser."
        self.link_hint.setText(self.pending_help)
        self.check_pending()

    def end_link(self, message):
        self.pending_token=None
        self.link_timer.stop()
        self.stop_link.hide()
        self.link_hint.setText(message);self.link_hint.show()
        self.update_auth();self.select()

    def cancel_link(self):
        self.end_link("Sign-in cancelled. You can start again whenever you’re ready.")

    def check_pending(self):
        token=self.pending_token
        if not token or self.closing:return
        if time.monotonic() >= self.link_deadline:
            self.end_link("The link timed out. Choose Sign in for a new code.")
            return
        if "check-link" in self.jobs:return
        self.link_timer.stop()
        def checked(data=None, error=None):
            # A slow response from a cancelled attempt must never sign in a new one.
            if self.pending_token != token:
                if self.pending_token: self.check_pending()
                return
            if data:
                try: self.auth.save_cache(data)
                except (OSError, RuntimeError, ValueError):
                    self.link_hint.setText("GGF confirmed the link, but Windows could not save it. Choose Refresh to retry.")
                else:
                    self.end_link("Account linked. Select a tool to download.")
                    return
            elif error:
                self.link_hint.setText(error+" Choose Refresh to check again, or cancel sign-in.")
            else:
                self.link_hint.setText(self.pending_help)
            # A one-shot poll leaves the controls available and never overlaps requests.
            self.link_timer.start(15000 if error or data else 4000)
        self.job("check-link",lambda w:self.auth.verify_link(token),checked,lambda error:checked(error=error))

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.Type.ActivationChange and self.isActiveWindow() and getattr(self,"pending_token",None):
            self.check_pending()

    def reload(self):
        if self.pending_token: self.check_pending()
        else:
            self.update_auth();self.refresh_membership()
        self.status.setText("Loading catalog…")
        def loaded(result):
            self.tools,self.offline=result
            codes=sorted({str(t[k]).lower() for t in self.tools for k in ("type1","type2","type3") if t.get(k)})
            old=self.type.currentData();self.type.blockSignals(True);self.type.clear();self.type.addItem("All categories","")
            for code in codes:self.type.addItem(code.upper() if code in ("llm","tts") else code.title(),code)
            self.type.setCurrentIndex(max(0,self.type.findData(old)));self.type.blockSignals(False);self.filter()
        self.job("catalog",lambda w:catalog(get_state_dir()),loaded)
    def filter(self,*_):
        prior=self.selected()
        self.results.clear();q=self.search.text().strip().casefold();category=self.type.currentData()
        membership=self.membership.currentData()
        preview_tier=self.user.get("tier") if membership=="mine" else membership
        rows=[t for t in self.tools if q in (t["name"]+" "+str(t.get("description") or "")).casefold() and
              (not membership or (t.get("slug") and membership_allows_download(preview_tier,t.get("membership")))) and
              (not category or category in [str(t.get(k,"")).lower() for k in ("type1","type2","type3")])]
        rows.sort(key=lambda t:(str(t.get("fav","")).lower() not in ("true","1","yes","y","fav"), t["name"].casefold()))
        for t in rows:
            item=QListWidgetItem(t["name"]);item.setData(Qt.ItemDataRole.UserRole,t);self.results.addItem(item)
        if rows:self.results.setCurrentRow(next((i for i,t in enumerate(rows) if t==prior),0))
        if "auth" not in self.jobs and "transfer" not in self.jobs:self.status.setText(("Offline catalog • " if self.offline else "")+f"{len(rows)} of {len(self.tools)} tools")
        self.select()
    def selected(self):
        item=self.results.currentItem();return item.data(Qt.ItemDataRole.UserRole) if item else {}
    def select(self,*_):
        t=self.selected();code=t.get("membership");label={"pd":"Prairie Dog+","fh":"Farm Hand+","free":"Free members","fs":"Website purchase"}.get(code,"See tool page")
        if t:
            self.details.setText(f"{label}   •   {t['name']}\n{str(t.get('description') or '')[:280]}")
        elif self.membership.currentData()=="mine" and not self.user:
            self.details.setText("Sign in to see what your membership includes, or choose All to browse.")
        else:
            self.details.setText("No matching tools. Try another membership, category, or search." if self.tools else "Select a tool.")
        self.page.setEnabled(bool(t.get("url")));self.get.setEnabled(bool(self.user and not self.pending_token and t.get("slug") and membership_allows_download(self.user.get("tier"),code) and "transfer" not in self.jobs and "auth" not in self.jobs))
    def open_page(self,*_):
        url=urljoin(ORIGIN+"/",self.selected().get("url") or "")
        if urlsplit(url).scheme=="https":webbrowser.open(url)
    def progress(self,n,total):
        self.bar.setRange(0,100 if total else 0)
        if total:self.bar.setValue(int(n*100/total))
        self.status.setText(f"Downloading • {n/1024**2:.1f} MiB"+(f" of {total/1024**2:.1f} MiB" if total else ""))
    def download(self,variant=None,tool=None):
        t=tool or self.selected();self.update_auth()
        if not self.user or not membership_allows_download(self.user.get("tier"),t.get("membership")):self.select();return
        token=self.user["token"];self.bar.show();self.bar.setRange(0,0);self.cancel.show();self.link.setEnabled(False);self.get.setEnabled(False)
        self.status.setText("Requesting "+t["name"]+"…")
        def transfer(w):
            try:return fetch(t["slug"],token,Path.home()/"Downloads"/"GGF",w.progress.emit,w.isInterruptionRequested,variant)
            except Variants as v:return v.names
        def reset():
            self.bar.hide();self.cancel.hide();self.link.setEnabled(True)
        def failed(message):
            reset();self.status.setText("Download stopped: "+message);self.refresh_membership()
        def saved(path):
            reset()
            if isinstance(path,list):
                choice,ok=QInputDialog.getItem(self,"Choose a package",t["name"],path,0,False)
                if ok:self.download(choice,t)
                else:self.status.setText("Package selection cancelled.")
                return
            self.status.setText(f"Saved to {path}")
            if path.suffix.lower() in (".zip",".7z",".rar",".exe",".bat"):
                if QMessageBox.question(self,"Add to GGF library?",f"{path.name} is in Downloads\\GGF.\n\nPrepare this app and set up Quick Launch?",defaultButton=QMessageBox.StandardButton.Yes)==QMessageBox.StandardButton.Yes:
                    try:start_setup(path)
                    except OSError as exc:self.status.setText(f"Saved to {path}. Could not open setup: {exc}")
            else:
                if QMessageBox.question(self,"Download complete",f"Saved to:\n{path}\n\nOpen the download folder?",defaultButton=QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:os.startfile(path.parent)
        self.job("transfer",transfer,saved,failed)
    def show_welcome(self):
        if self.guide is None:
            self.guide = Guide(self)
            self.guide.finished.connect(self.finish_welcome)
            self.guide.show()
        self.guide.raise_()
        self.guide.activateWindow()

    def finish_welcome(self, result):
        self.guide = None
        try:
            remember_welcome()
        except OSError as exc:
            self.status.setText("Could not save the welcome preference: " + str(exc))

    def bring_forward(self, tour=False):
        self.closing = False
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        if tour or self.guide:
            self.show_welcome()
        else:
            modal = QApplication.activeModalWidget()
            if modal:
                modal.raise_()
                modal.activateWindow()

    def closeEvent(self,event):
        if self.pending_token: self.cancel_link()
        if self.jobs:
            self.closing=True
            for worker in self.jobs.values():worker.requestInterruption()
            event.ignore();self.hide()
        else:event.accept()

def main():
    tour = "--welcome" in sys.argv
    owner = CatalogOwner()
    try:
        if not owner.primary:
            activate_existing(tour)
            return 0
        app = QApplication(sys.argv)
        window = SearchDialog()
        owner.attach(window)
        def activated():
            requested, replay = owner.consume()
            if requested:
                window.bring_forward(replay)
        timer = QTimer(window)
        timer.timeout.connect(activated)
        timer.start(125)
        window.show()
        if tour:
            QTimer.singleShot(0, window.show_welcome)
        return app.exec()
    finally:
        owner.release()

if __name__ == "__main__":
    sys.exit(main())
