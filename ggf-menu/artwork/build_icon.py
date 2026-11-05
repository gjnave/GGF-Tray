"""Render the tray's vector mark into a multi-resolution Windows icon."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

here=Path(__file__).resolve().parent
renderer=QSvgRenderer(str(here/"ggf-mark.svg"))
assert renderer.isValid()
surface=QImage(1024,1024,QImage.Format.Format_RGBA8888)
surface.fill(Qt.GlobalColor.transparent)
painter=QPainter(surface)
renderer.render(painter)
painter.end()
pixels=surface.bits().asstring(surface.sizeInBytes())
master=Image.frombytes("RGBA",(surface.width(),surface.height()),pixels)
sizes=(16,20,24,28,32,40,48,64,96,128,256)
images=[master.resize((n,n),Image.Resampling.LANCZOS) for n in sizes]
images[-1].save(here.parent/"ggf-mark.ico",format="ICO",sizes=[(n,n) for n in sizes],append_images=images[:-1])

