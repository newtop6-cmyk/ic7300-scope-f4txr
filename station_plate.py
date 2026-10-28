"""Plaque de stations (écran MOBILE) : plaque rectangulaire en aluminium
brossé à bords arrondis, en relief, vissée, avec des micro-poussoirs. Sous
chaque poussoir, l'indicatif et la fréquence sont gravés dans le métal.
Clic = aller sur la station ; appui long (1 s) = y mettre la fréquence du
moment."""

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets


class MicroPush(QtWidgets.QAbstractButton):
    """Tout petit poussoir rond : bague chromée, capuchon bombé."""

    def __init__(self, cap="#b11d12", size=30):
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.cap = QtGui.QColor(cap)
        self.lit = False                    # radio sur cette station : capuchon qui luit

    def set_lit(self, on):
        if on != self.lit:
            self.lit = on
            self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s = self.width()
        c = QtCore.QPointF(s / 2, s / 2)
        R = s / 2 - 1.5
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 80))                 # ombre
        p.drawEllipse(c + QtCore.QPointF(0.8, 1.4), R, R)
        ring = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#70746f"), (0.5, "#e8eae6"),
                          (0.75, "#4c504b"), (1, "#ffffff")):
            ring.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(ring)
        p.setPen(QtGui.QPen(QtGui.QColor("#1c1e1b"), 0.7))
        p.drawEllipse(c, R, R)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#0a0a0a"))                   # gorge
        p.drawEllipse(c, R * 0.74, R * 0.74)
        down = self.isDown()
        cc = c + QtCore.QPointF(0, 0.9 if down else 0)
        rc = R * (0.62 if down else 0.66)
        base = self.cap.lighter(150) if self.lit else self.cap
        g = QtGui.QRadialGradient(cc - QtCore.QPointF(rc * 0.35, rc * 0.4), rc * 1.4)
        g.setColorAt(0, base.lighter(170))
        g.setColorAt(0.5, base)
        g.setColorAt(1, base.darker(260))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 0.6))
        p.drawEllipse(cc, rc, rc)
        if self.lit:                                          # lueur
            glow = QtGui.QRadialGradient(cc, rc * 1.6)
            col = QtGui.QColor(base.lighter(160))
            col.setAlpha(120)
            glow.setColorAt(0, col)
            glow.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(cc, rc * 1.6, rc * 1.6)
        hl = QtGui.QRadialGradient(cc - QtCore.QPointF(rc * 0.35, rc * 0.42), rc * 0.5)
        hl.setColorAt(0, QtGui.QColor(255, 255, 255, 170 if not down else 90))
        hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(hl)
        p.drawEllipse(cc - QtCore.QPointF(rc * 0.35, rc * 0.42), rc * 0.5, rc * 0.4)
        p.end()


def _brushed(w, h, seed=21):
    """Aluminium brossé : fines stries horizontales."""
    rng = np.random.default_rng(seed)
    rows = rng.standard_normal((h, 1)) * 9 + rng.standard_normal((h, w)) * 3
    rows = np.cumsum(rows, axis=1) * 0.02 + rows                # stries étirées
    rows -= rows.mean()
    tone = 196 + np.clip(rows, -22, 22) - np.linspace(0, 26, h)[:, None]
    v = np.clip(tone, 0, 255).astype(np.uint8)
    img = np.empty((h, w, 4), np.uint8)
    img[:, :, 0] = np.clip(v.astype(int) + 4, 0, 255)          # B : un rien froid
    img[:, :, 1] = v
    img[:, :, 2] = v
    img[:, :, 3] = 255
    return QtGui.QImage(img.data, w, h, 4 * w, QtGui.QImage.Format_RGB32).copy()


class StationPlate(QtWidgets.QWidget):
    tune = QtCore.pyqtSignal(int)           # clic sur le poussoir n
    store = QtCore.pyqtSignal(int)          # appui long sur le poussoir n

    COLS = 3
    CELL_W, CELL_H = 82, 66

    def __init__(self, count=6, title="STATIONS"):
        super().__init__()
        self.title = title
        self.slots = [{"name": "", "hz": None, "mode": ""} for _ in range(count)]
        rows = (count + self.COLS - 1) // self.COLS
        self.setFixedSize(self.COLS * self.CELL_W + 28, rows * self.CELL_H + 44)
        self.buttons = []
        self._long = QtCore.QTimer(self)
        self._long.setSingleShot(True)
        self._long.timeout.connect(self._long_press)
        self._held = None
        self._stored = False
        for i in range(count):
            b = MicroPush("#b11d12" if i == 0 else "#2b2b2b")
            b.setParent(self)
            col, row = i % self.COLS, i // self.COLS
            b.move(int(14 + col * self.CELL_W + (self.CELL_W - b.width()) / 2),
                   int(30 + row * self.CELL_H))
            b.pressed.connect(lambda i=i: self._press(i))
            b.released.connect(lambda i=i: self._release(i))
            self.buttons.append(b)
        self._bg = None

    def set_slots(self, slots):
        for i, s in enumerate(slots[:len(self.slots)]):
            self.slots[i] = dict(s)
        self._refresh_tips()
        self.update()

    def _refresh_tips(self):
        for b, s in zip(self.buttons, self.slots):
            if s.get("hz"):
                b.setToolTip(f"{s.get('name') or 'Mémoire'} : {s['hz'] / 1e6:.3f} MHz "
                             f"{s.get('mode', '')}\nClic = y aller tout de suite ; "
                             "appui long = y mettre la fréquence du moment")
            else:
                b.setToolTip("Libre : appui long (1 s) = mémoriser la fréquence du moment")

    def set_current(self, hz):
        """Allume le poussoir de la station où se trouve la radio."""
        for b, s in zip(self.buttons, self.slots):
            b.set_lit(bool(hz and s.get("hz") and abs(s["hz"] - hz) < 500))

    def _press(self, i):
        self._held, self._stored = i, False
        self._long.start(1000)

    def _long_press(self):
        if self._held is not None:
            self._stored = True
            self.store.emit(self._held)

    def _release(self, i):
        self._long.stop()
        if not self._stored and self._held == i:
            self.tune.emit(i)
        self._held = None

    # --- dessin -------------------------------------------------------------
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QtCore.QRectF(4, 3, w - 10, h - 10)
        rad = 14
        for i in range(8, 0, -1):                              # ombre portée
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 22))
            p.drawRoundedRect(r.translated(i * 0.4, i * 0.7), rad, rad)
        if self._bg is None or self._bg.size() != r.size().toSize():
            self._bg = _brushed(int(r.width()), int(r.height()))
        path = QtGui.QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(path)
        p.drawImage(r.topLeft(), self._bg)
        for k in range(7):                                     # bords arrondis en relief
            fade = (1 - k / 7) ** 1.5
            ring = r.adjusted(k + 0.5, k + 0.5, -k - 0.5, -k - 0.5)
            g = QtGui.QLinearGradient(ring.topLeft(), ring.bottomRight())
            g.setColorAt(0, QtGui.QColor(255, 255, 255, int(210 * fade)))
            g.setColorAt(0.5, QtGui.QColor(255, 255, 255, 0))
            g.setColorAt(1, QtGui.QColor(0, 0, 0, int(170 * fade)))
            p.setPen(QtGui.QPen(QtGui.QBrush(g), 1.2))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRoundedRect(ring, rad - k * 0.8, rad - k * 0.8)
        p.restore()
        p.setPen(QtGui.QPen(QtGui.QColor(40, 42, 40), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(r, rad, rad)
        for x, y in ((r.left() + 11, r.top() + 11), (r.right() - 11, r.top() + 11),
                     (r.left() + 11, r.bottom() - 11), (r.right() - 11, r.bottom() - 11)):
            g = QtGui.QRadialGradient(QtCore.QPointF(x - 1, y - 1), 4.5)
            g.setColorAt(0, QtGui.QColor("#ffffff"))
            g.setColorAt(1, QtGui.QColor("#5d615c"))
            p.setBrush(g)
            p.setPen(QtGui.QPen(QtGui.QColor("#2a2c29"), 0.6))
            p.drawEllipse(QtCore.QPointF(x, y), 3.6, 3.6)
            p.setPen(QtGui.QPen(QtGui.QColor("#3a3d39"), 1))
            p.drawLine(QtCore.QPointF(x - 2.6, y + 0.8), QtCore.QPointF(x + 2.6, y - 0.8))
        # titre et inscriptions gravées (creux sombre + bord clair)
        def engrave(rect, text, px, bold=True, spacing=1.5):
            f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Bold if bold else QtGui.QFont.Normal)
            f.setPixelSize(px)
            f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, spacing)
            p.setFont(f)
            p.setPen(QtGui.QColor(255, 255, 255, 190))
            p.drawText(rect.translated(0, 0.9), QtCore.Qt.AlignCenter, text)
            p.setPen(QtGui.QColor("#1f211e"))
            p.drawText(rect, QtCore.Qt.AlignCenter, text)

        engrave(QtCore.QRectF(r.left(), r.top() + 5, r.width(), 16), self.title, 11, spacing=3)
        for i, s in enumerate(self.slots):
            col, row = i % self.COLS, i // self.COLS
            x = 14 + col * self.CELL_W
            y = 30 + row * self.CELL_H + 31
            name = s.get("name") or (f"M{i + 1}" if s.get("hz") else "—")
            engrave(QtCore.QRectF(x, y, self.CELL_W, 14), name, 11, spacing=0.5)
            if s.get("hz"):
                engrave(QtCore.QRectF(x, y + 13, self.CELL_W, 12),
                        f"{s['hz'] / 1e6:.3f} {s.get('mode', '')}".strip(), 9,
                        bold=False, spacing=0)
        p.end()
