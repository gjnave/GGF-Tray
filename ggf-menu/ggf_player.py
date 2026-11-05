"""Local music queue. Audio output uses the system default; the visualizer listens via WASAPI."""
from pathlib import Path
from PySide6.QtCore import Qt,QUrl
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,QPushButton,QSlider,QFileDialog)

class MusicPlayer(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle("GGF Music Player");self.resize(490,340)
        self.paths=[];self.current=-1
        self.media=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(0.65);self.media.setAudioOutput(self.audio)
        layout=QVBoxLayout(self);self.now=QLabel("Open music files to start a queue.");self.now.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.now)
        self.list=QListWidget();layout.addWidget(self.list,1);self.list.itemDoubleClicked.connect(lambda _:self.play(self.list.currentRow()))
        self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.setRange(0,0);layout.addWidget(self.seek)
        self.seek.sliderMoved.connect(self.media.setPosition);self.media.durationChanged.connect(lambda n:self.seek.setRange(0,int(n)))
        self.media.positionChanged.connect(lambda n: None if self.seek.isSliderDown() else self.seek.setValue(int(n)))
        row=QHBoxLayout();layout.addLayout(row)
        def button(label,func):
            b=QPushButton(label);row.addWidget(b);b.clicked.connect(func);return b
        button("Add files…",self.choose);button("Previous",lambda:self.play(max(0,self.current-1)));self.toggle_btn=button("Play",self.toggle);button("Next",self.next)
        row.addWidget(QLabel("Volume"));volume=QSlider(Qt.Orientation.Horizontal);volume.setRange(0,100);volume.setValue(65);volume.valueChanged.connect(lambda n:self.audio.setVolume(n/100));row.addWidget(volume)
        self.media.playbackStateChanged.connect(lambda state:self.toggle_btn.setText("Pause" if state==QMediaPlayer.PlaybackState.PlayingState else "Play"))
        self.media.mediaStatusChanged.connect(lambda status:self.next() if status==QMediaPlayer.MediaStatus.EndOfMedia else None)
        self.media.errorOccurred.connect(lambda *args:self.now.setText("Cannot play this track: "+self.media.errorString()))
    def choose(self):
        files,_=QFileDialog.getOpenFileNames(self,"Add music",str(Path.home()/"Music"),"Audio (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma);;All files (*.*)")
        self.add(files)
    def add(self,files):
        for name in files:
            path=Path(name).absolute()
            if path.is_file():self.paths.append(path);self.list.addItem(path.name)
        if self.current==-1 and self.paths:self.play(0)
    def play(self,i):
        if not 0<=i<len(self.paths):return
        self.current=i;self.list.setCurrentRow(i);self.now.setText(self.paths[i].name)
        self.media.setSource(QUrl.fromLocalFile(str(self.paths[i])));self.media.play()
    def toggle(self):
        if not self.paths:self.choose()
        elif self.media.playbackState()==QMediaPlayer.PlaybackState.PlayingState:self.media.pause()
        elif self.current<0 or self.media.mediaStatus()==QMediaPlayer.MediaStatus.EndOfMedia:self.play(max(0,self.list.currentRow()))
        else:self.media.play()
    def next(self):
        if self.current+1<len(self.paths):self.play(self.current+1)
    def closeEvent(self,event):
        self.media.pause();super().closeEvent(event)

