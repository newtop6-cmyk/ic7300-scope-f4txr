"""Mode DÉMO : la souris devient un gros doigt (X11).

Le doigt est une fenêtre transparente posée sur l'écran, qui suit le
pointeur : le bout de l'index est exactement à la pointe de la souris. Elle
se voit donc aussi dans un partage d'écran ou une vidéo de l'écran. La
flèche habituelle est cachée pendant la démo (XFixes). À chaque clic, le
doigt s'enfonce et une onde rouge part du point touché.
Taille réglable (set_size), gardée entre deux sessions.
Essai seul : python3 demo_finger.py
"""

import ctypes
import ctypes.util
import json
import os
import time

from PyQt5 import QtCore, QtGui, QtWidgets

CONFIG = os.path.expanduser("~/.config/ic7300-scope/demo.json")
SIZES = {"Moyen": 110, "Gros": 160, "Très gros": 230}
EMOJI = "\U0001F446\U0001F3FC"    # 👆 index pointé vers le haut, couleur de peau claire
TILT = -18                      # doigt un peu penché, comme une vraie main droite
RIPPLE_S = 0.6


class _X11:
    """Accès direct à X11 : position + boutons de la souris, flèche cachée."""

    class _Pointer(ctypes.Structure):
        pass

    def __init__(self):
        self.ok = False
        try:
            self.x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
            self.xf = ctypes.CDLL(ctypes.util.find_library("Xfixes") or "libXfixes.so.3")
        except OSError:
            return
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.x.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + \
            [ctypes.POINTER(ctypes.c_ulong)] * 2 + [ctypes.POINTER(ctypes.c_int)] * 4 + \
            [ctypes.POINTER(ctypes.c_uint)]
        self.x.XDefaultScreen.argtypes = [ctypes.c_void_p]
        self.x.XIconifyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int]
        self.xf.XFixesHideCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.xf.XFixesShowCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.dpy = self.x.XOpenDisplay(None)
        if not self.dpy:
            return
        self.root = self.x.XDefaultRootWindow(self.dpy)
        self.hidden = False
        self.ok = True

    def buttons(self):
        """True si un bouton de la souris est enfoncé."""
        if not self.ok:
            return False
        r, c = ctypes.c_ulong(), ctypes.c_ulong()
        a, b, d, e = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        self.x.XQueryPointer(self.dpy, self.root, ctypes.byref(r), ctypes.byref(c),
                             ctypes.byref(a), ctypes.byref(b), ctypes.byref(d),
                             ctypes.byref(e), ctypes.byref(mask))
        return bool(mask.value & (0x100 | 0x200 | 0x400))   # boutons 1, 2, 3

    def iconify(self, window):
        """Réduit une fenêtre (de n'importe quelle appli) dans le dock."""
        if self.ok:
            self.x.XIconifyWindow(self.dpy, window, self.x.XDefaultScreen(self.dpy))
            self.x.XFlush(self.dpy)

    def hide_cursor(self, hide):
        if not self.ok or hide == self.hidden:
            return
        (self.xf.XFixesHideCursor if hide else self.xf.XFixesShowCursor)(self.dpy, self.root)
        self.x.XFlush(self.dpy)
        self.hidden = hide


def _finger_pixmap(size):
    """Le 👆 de la police emoji en couleur, penché ; renvoie (image, bout du doigt)."""
    base = QtGui.QImage(150, 150, QtGui.QImage.Format_ARGB32_Premultiplied)
    base.fill(0)
    p = QtGui.QPainter(base)
    font = QtGui.QFont("Noto Color Emoji")
    font.setPixelSize(109)              # taille native de la police (images)
    p.setFont(font)
    p.drawText(base.rect(), QtCore.Qt.AlignCenter, EMOJI)
    p.end()
    side = int(size * 1.5)
    img = QtGui.QImage(side, side, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.translate(side / 2, side / 2)
    p.rotate(TILT)
    scale = size / 109
    p.scale(scale, scale)
    p.drawImage(QtCore.QPointF(-75, -75), base)
    p.end()
    # bout du doigt = point opaque le plus haut (moyenne de sa rangée)
    tip = QtCore.QPoint(side // 2, 0)
    for y in range(side):
        xs = [x for x in range(side) if QtGui.qAlpha(img.pixel(x, y)) > 140]
        if xs:
            tip = QtCore.QPoint(sum(xs) // len(xs), y + 2)
            break
    return QtGui.QPixmap.fromImage(img), tip


class DemoFinger(QtWidgets.QWidget):
    size_changed = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowStaysOnTopHint
                         | QtCore.Qt.X11BypassWindowManagerHint
                         | QtCore.Qt.WindowTransparentForInput)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.x11 = _X11()
        self.size_name = self._load_size()
        self._build()
        self.pressed = False
        self.ripples = []               # instants des clics
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._follow)

    def _build(self):
        self.pix, self.tip = _finger_pixmap(SIZES[self.size_name])
        self.margin = 70                # place pour l'onde autour du bout du doigt
        self.setFixedSize(self.pix.width() + self.margin, self.pix.height() + self.margin)

    def _load_size(self):
        try:
            with open(CONFIG) as f:
                name = json.load(f)["taille"]
            return name if name in SIZES else "Gros"
        except (OSError, ValueError, KeyError, TypeError):
            return "Gros"

    def set_size(self, name):
        if name not in SIZES or name == self.size_name:
            return
        self.size_name = name
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
            with open(CONFIG, "w") as f:
                json.dump({"taille": name}, f)
        except OSError:
            pass
        self._build()
        self.size_changed.emit(name)

    def start(self):
        self.x11.hide_cursor(True)
        self._follow()
        self.show()
        self.timer.start(12)

    def stop(self):
        self.timer.stop()
        self.hide()
        self.x11.hide_cursor(False)

    def _origin(self):
        """Point de la fenêtre où se trouve le bout du doigt."""
        return QtCore.QPoint(self.tip.x() + self.margin // 2, self.tip.y() + self.margin // 2)

    def _follow(self):
        pos = QtGui.QCursor.pos()
        self.move(pos - self._origin())
        pressed = self.x11.buttons()
        if pressed and not self.pressed:
            self.ripples.append(time.monotonic())
        self.pressed = pressed
        now = time.monotonic()
        self.ripples = [t for t in self.ripples if now - t < RIPPLE_S]
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        o = QtCore.QPointF(self._origin())
        now = time.monotonic()
        for t in self.ripples:              # onde du clic
            k = (now - t) / RIPPLE_S
            p.setPen(QtGui.QPen(QtGui.QColor(255, 40, 40, int(230 * (1 - k))), 3))
            p.setBrush(QtCore.Qt.NoBrush)
            r = 6 + 30 * k
            p.drawEllipse(o, r, r)
        # ombre portée légère, puis le doigt (enfoncé : un peu plus petit)
        p.save()
        p.translate(o)
        if self.pressed:
            p.scale(0.9, 0.9)
        p.translate(-QtCore.QPointF(self.tip))
        p.setOpacity(0.25)
        shadow = self.pix.copy()
        sp = QtGui.QPainter(shadow)
        sp.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        sp.fillRect(shadow.rect(), QtGui.QColor(0, 0, 0))
        sp.end()
        p.drawPixmap(QtCore.QPointF(7, 9), shadow)
        p.setOpacity(1.0)
        p.drawPixmap(0, 0, self.pix)
        p.restore()
        # point rouge = l'endroit exact visé
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 30, 30, 230))
        p.drawEllipse(o, 3, 3)
        p.end()


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    finger = DemoFinger()
    if "--shot" in sys.argv:
        finger._follow()
        finger.ripples = [time.monotonic() - 0.15]
        finger.grab().save(sys.argv[-1])
        sys.exit()
    finger.start()
    QtCore.QTimer.singleShot(15000, app.quit)       # essai : 15 s
    app.exec_()
    finger.stop()
