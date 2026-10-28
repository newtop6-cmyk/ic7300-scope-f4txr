"""Fond de l'écran MOBILE façon Collins KWM-2 : façade en peinture granitée
(« wrinkle finish ») deux tons, haut gris clair, bas gris Collins foncé,
baguettes d'aluminium brossé, vis, cadres chromés et inscriptions blanches
gravées au-dessus des commandes."""

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

UPPER = np.array([156, 160, 150], float)     # gris clair légèrement vert
LOWER = np.array([74, 82, 76], float)        # gris Collins foncé
ENGRAVE = QtGui.QColor("#f2efe4")            # peinture blanche des inscriptions


def _box_blur(a, r):
    """Flou rapide (deux passes de moyenne glissante)."""
    for axis in (0, 1):
        c = np.cumsum(np.pad(a, [(r + 1, r) if i == axis else (0, 0) for i in (0, 1)],
                             mode="edge"), axis=axis)
        if axis == 0:
            a = (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)
        else:
            a = (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)
    return a


def wrinkle(w, h, base, seed=7):
    """Peinture granitée : petites rides en relief + grain, éclairée d'en haut."""
    rng = np.random.default_rng(seed)
    n = _box_blur(rng.standard_normal((h, w)), 2) + 0.6 * _box_blur(rng.standard_normal((h, w)), 5)
    relief = n - np.roll(np.roll(n, 1, 0), 1, 1)           # lumière en haut à gauche
    relief /= max(1e-6, np.abs(relief).std()) * 3
    grain = rng.standard_normal((h, w)) * 0.025
    shade = 1 + 0.16 * np.clip(relief, -2, 2) + grain
    shade *= 1 - 0.10 * (np.linspace(0, 1, h)[:, None])   # un peu plus sombre en bas
    rgb = np.clip(base[None, None, :] * shade[:, :, None], 0, 255).astype(np.uint8)
    img = np.empty((h, w, 4), np.uint8)
    img[:, :, 0], img[:, :, 1], img[:, :, 2], img[:, :, 3] = rgb[:, :, 2], rgb[:, :, 1], rgb[:, :, 0], 255
    q = QtGui.QImage(img.data, w, h, 4 * w, QtGui.QImage.Format_RGB32)
    return q.copy()


class CollinsPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.labels = []            # (widget, texte) : inscription au-dessus
        self.bezels = []            # widgets entourés d'un cadre chromé
        self.split_widget = None    # le bas foncé commence au-dessus de ce widget
        self._cache = None

    def resizeEvent(self, event):
        self._cache = None
        super().resizeEvent(event)

    def _split_y(self):
        if self.split_widget is None:
            return self.height() // 3
        return self.split_widget.mapTo(self, QtCore.QPoint(0, 0)).y() - 20

    def _background(self):
        w, h = self.width(), self.height()
        split = self._split_y()
        if self._cache and self._cache[0] == (w, h, split):
            return self._cache[1]
        pix = QtGui.QPixmap(w, h)
        p = QtGui.QPainter(pix)
        p.drawImage(0, 0, wrinkle(w, max(1, split), UPPER, 3))
        p.drawImage(0, split, wrinkle(w, max(1, h - split), LOWER, 11))
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # baguettes d'aluminium brossé : en haut, au milieu, en bas
        for y, t in ((0, 7), (split - 5, 10), (h - 7, 7)):
            self._alu(p, QtCore.QRectF(0, y, w, t))
        # vis aux quatre coins de chaque zone
        for y in (22, split - 22, split + 26, h - 24):
            for x in (22, w - 22):
                self._screw(p, QtCore.QPointF(x, y))
        p.end()
        self._cache = ((w, h, split), pix)
        return pix

    @staticmethod
    def _alu(p, r):
        g = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        for stop, col in ((0, "#f4f5f2"), (0.3, "#c6c9c4"), (0.55, "#8d918b"),
                          (0.8, "#d8dbd6"), (1, "#5c605a")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawRect(r)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 0.6))       # brossage
        for x in range(0, int(r.width()), 5):
            p.drawLine(QtCore.QPointF(x, r.top() + 1), QtCore.QPointF(x + 30, r.bottom() - 1))

    @staticmethod
    def _screw(p, c):
        g = QtGui.QRadialGradient(c - QtCore.QPointF(1.5, 1.5), 7)
        g.setColorAt(0, QtGui.QColor("#fbfbf8"))
        g.setColorAt(0.6, QtGui.QColor("#a4a8a0"))
        g.setColorAt(1, QtGui.QColor("#4a4e48"))
        p.setPen(QtGui.QPen(QtGui.QColor("#262924"), 0.8))
        p.setBrush(g)
        p.drawEllipse(c, 6, 6)
        p.setPen(QtGui.QPen(QtGui.QColor("#3a3d38"), 1.4))
        p.drawLine(c + QtCore.QPointF(-4, 1.2), c + QtCore.QPointF(4, -1.2))

    def _bezel(self, p, r):
        """Cadre chromé arrondi + joint noir autour d'une fenêtre."""
        outer = QtCore.QRectF(r).adjusted(-10, -10, 10, 10)
        g = QtGui.QLinearGradient(0, outer.top(), 0, outer.bottom())
        for stop, col in ((0, "#fbfbf9"), (0.25, "#aeb2ac"), (0.5, "#e4e6e2"),
                          (0.75, "#7b7f79"), (1, "#d2d5d0")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#2b2e2a"), 1))
        p.setBrush(g)
        p.drawRoundedRect(outer, 10, 10)
        p.setBrush(QtGui.QColor("#0b0d0c"))
        p.drawRoundedRect(QtCore.QRectF(r).adjusted(-4, -4, 4, 4), 6, 6)

    def _engrave(self, p, widget, text):
        top_left = widget.mapTo(self, QtCore.QPoint(0, 0))
        up = 34 if widget in self.bezels else 24          # au-dessus du cadre chromé
        r = QtCore.QRectF(top_left.x() - 40, top_left.y() - up, widget.width() + 80, 20)
        f = QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Bold)
        f.setPixelSize(13)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2.5)
        p.setFont(f)
        p.setPen(QtGui.QColor(0, 0, 0, 120))                  # creux de la gravure
        p.drawText(r.translated(0, 1), QtCore.Qt.AlignCenter, text)
        p.setPen(ENGRAVE)
        p.drawText(r, QtCore.Qt.AlignCenter, text)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._background())
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        for widget in self.bezels:
            if widget.isVisible():
                tl = widget.mapTo(self, QtCore.QPoint(0, 0))
                self._bezel(p, QtCore.QRect(tl, widget.size()))
        for widget, text in self.labels:
            if widget.isVisible():
                self._engrave(p, widget, text)
        p.end()
