"""Afficheur de fréquence à tubes Nixie (écran MOBILE) : 8 tubes en verre,
grille en nid d'abeille, chiffre orange qui luit, points néon entre MHz, kHz
et Hz. Même usage que DrumDisplay : setText("7.100.000"), molette = tuned."""

import math
import random

from PyQt5 import QtCore, QtGui, QtWidgets

GLOW = QtGui.QColor(255, 120, 30)         # orange néon
CORE = QtGui.QColor(255, 226, 170)        # cœur du chiffre, presque blanc


class NixieDisplay(QtWidgets.QWidget):
    tuned = QtCore.pyqtSignal(int)

    TUBES = 8                              # 2 MHz + 3 kHz + 3 Hz

    def __init__(self, width=820, height=180):
        super().__init__()
        self.setFixedSize(width, height)
        self.setToolTip("Molette : changer la fréquence")
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self.digits = [None] * self.TUBES  # None = tube éteint
        self.dots = set()                  # tubes suivis d'un point allumé
        self._angle = 0
        self.level = 1.0                   # luminosité (léger scintillement)
        self.voice = None
        self.flicker = QtCore.QTimer(self)
        self.flicker.timeout.connect(self._flicker)
        self.flicker.start(90)
        self.setText("--.---.---")

    # --- même interface que DrumDisplay ------------------------------------
    def setText(self, text):
        self._text = text
        digits, dots = [], set()
        for ch in text:
            if ch == ".":
                if digits:
                    dots.add(len(digits) - 1)
            else:
                digits.append(int(ch) if ch.isdigit() else None)
        pad = self.TUBES - len(digits)     # < 10 MHz : premier tube éteint
        self.digits = [None] * pad + digits[-self.TUBES:]
        self.dots = {d + pad for d in dots}
        self.update()

    def text(self):
        return self._text

    def set_voice(self, level):
        self.voice = level

    def set_tx(self, on, watts=None):
        pass

    def wheelEvent(self, event):
        self._angle += event.angleDelta().y()
        steps = int(self._angle / 120)
        if steps:
            self._angle -= steps * 120
            self.tuned.emit(steps)
        event.accept()

    def _flicker(self):
        goal = 0.93 + random.random() * 0.07
        if self.voice is not None:         # la voix fait un peu « respirer » les tubes
            goal = min(1.0, 0.82 + 0.25 * self.voice)
        self.level += (goal - self.level) * 0.5
        self.update()

    # --- dessin ---------------------------------------------------------------
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # socle : bois sombre verni, cadre laiton
        frame = QtCore.QRectF(2, 2, w - 4, h - 4)
        brass = QtGui.QLinearGradient(0, 0, 0, h)
        for stop, col in ((0, "#f3d98a"), (0.45, "#b8892e"), (0.55, "#8a6420"), (1, "#e2c06a")):
            brass.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#3a2a08"), 1.5))
        p.setBrush(brass)
        p.drawRoundedRect(frame, 14, 14)
        inner = frame.adjusted(10, 10, -10, -10)
        wood = QtGui.QLinearGradient(0, inner.top(), 0, inner.bottom())
        wood.setColorAt(0, QtGui.QColor("#2a1a10"))
        wood.setColorAt(0.5, QtGui.QColor("#160d07"))
        wood.setColorAt(1, QtGui.QColor("#0a0503"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.setBrush(wood)
        p.drawRoundedRect(inner, 8, 8)
        # vis aux coins du cadre
        for x, y in ((frame.left() + 9, frame.top() + 9), (frame.right() - 9, frame.top() + 9),
                     (frame.left() + 9, frame.bottom() - 9), (frame.right() - 9, frame.bottom() - 9)):
            g = QtGui.QRadialGradient(QtCore.QPointF(x - 1, y - 1), 4)
            g.setColorAt(0, QtGui.QColor("#fff4cc"))
            g.setColorAt(1, QtGui.QColor("#6b4c12"))
            p.setBrush(g)
            p.setPen(QtGui.QPen(QtGui.QColor("#2a1d05"), 0.6))
            p.drawEllipse(QtCore.QPointF(x, y), 3.5, 3.5)
        # tubes : groupes MHz | kHz | Hz un peu écartés
        gap_group = inner.width() * 0.035
        avail = inner.width() - 24 - 2 * gap_group
        tube_w = avail / self.TUBES
        x = inner.left() + 12
        for i in range(self.TUBES):
            if i in (2, 5):
                x += gap_group
            self._tube(p, QtCore.QRectF(x + 3, inner.top() + 8, tube_w - 6,
                                        inner.height() - 16), self.digits[i], i in self.dots)
            x += tube_w
        p.end()

    def _tube(self, p, r, digit, dot):
        lit = digit is not None
        # ampoule de verre : sombre, reflet sur le bord gauche
        glass = QtGui.QLinearGradient(r.left(), 0, r.right(), 0)
        glass.setColorAt(0, QtGui.QColor(70, 60, 55, 200))
        glass.setColorAt(0.15, QtGui.QColor(25, 18, 14, 230))
        glass.setColorAt(0.85, QtGui.QColor(18, 12, 9, 230))
        glass.setColorAt(1, QtGui.QColor(55, 45, 40, 200))
        p.setPen(QtGui.QPen(QtGui.QColor(120, 100, 90, 160), 1.2))
        p.setBrush(glass)
        p.drawRoundedRect(r, r.width() * 0.45, r.width() * 0.45)
        if lit:                                    # lueur orange dans tout le tube
            halo = QtGui.QRadialGradient(r.center(), r.height() * 0.55)
            c = QtGui.QColor(GLOW)
            c.setAlpha(int(70 * self.level))
            halo.setColorAt(0, c)
            halo.setColorAt(1, QtGui.QColor(255, 90, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(halo)
            p.drawRoundedRect(r, r.width() * 0.45, r.width() * 0.45)
        # grille en nid d'abeille devant les chiffres
        p.save()
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(r.adjusted(3, 3, -3, -3), r.width() * 0.4, r.width() * 0.4)
        p.setClipPath(clip)
        p.setPen(QtGui.QPen(QtGui.QColor(150, 120, 90, 45 if not lit else 70), 0.7))
        s = 6.0
        for row in range(int(r.height() / (s * 0.87)) + 2):
            y = r.top() + row * s * 0.87
            off = (s / 2) if row % 2 else 0
            xx = r.left() - s + off
            while xx < r.right() + s:
                hexa = QtGui.QPolygonF([QtCore.QPointF(xx + s / 2 * math.cos(math.radians(a)),
                                                       y + s / 2 * math.sin(math.radians(a)))
                                        for a in range(30, 390, 60)])
                p.drawPolygon(hexa)
                xx += s
        # chiffres éteints empilés (fils de cathode visibles)
        font = QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Light)
        font.setPixelSize(int(r.height() * 0.72))
        p.setFont(font)
        fm = QtGui.QFontMetricsF(font)
        p.setPen(QtGui.QColor(110, 85, 65, 55))
        for d in "0123456789":
            p.drawText(r, QtCore.Qt.AlignCenter, d)
        # chiffre allumé : lueur large puis cœur clair
        if lit:
            path = QtGui.QPainterPath()
            txt = str(digit)
            tw = fm.horizontalAdvance(txt)
            base = QtCore.QPointF(r.center().x() - tw / 2,
                                  r.center().y() + (fm.ascent() - fm.descent()) / 2)
            path.addText(base, font, txt)
            p.setBrush(QtCore.Qt.NoBrush)
            for width, alpha in ((14, 28), (9, 45), (5, 90), (2.5, 170)):
                c = QtGui.QColor(GLOW)
                c.setAlpha(int(alpha * self.level))
                p.setPen(QtGui.QPen(c, width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap,
                                    QtCore.Qt.RoundJoin))
                p.drawPath(path)
            core = QtGui.QColor(CORE)
            core.setAlpha(int(255 * self.level))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(core)
            p.drawPath(path)
        p.restore()
        # point néon en bas à droite (séparateur MHz / kHz / Hz)
        at = QtCore.QPointF(r.right() - r.width() * 0.16, r.bottom() - r.height() * 0.13)
        if dot and lit:
            g = QtGui.QRadialGradient(at, 9)
            c = QtGui.QColor(GLOW)
            c.setAlpha(int(220 * self.level))
            g.setColorAt(0, QtGui.QColor(255, 235, 200))
            g.setColorAt(0.35, c)
            g.setColorAt(1, QtGui.QColor(255, 90, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(at, 9, 9)
        else:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(110, 85, 65, 70))
            p.drawEllipse(at, 2.5, 2.5)
        # reflet vertical sur le verre
        shine = QtGui.QLinearGradient(r.left(), 0, r.left() + r.width() * 0.3, 0)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QtGui.QColor(255, 255, 255, 38))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawRoundedRect(QtCore.QRectF(r.left() + r.width() * 0.08, r.top() + r.height() * 0.08,
                                        r.width() * 0.25, r.height() * 0.84), 6, 6)
        # culot noir en bas
        p.setBrush(QtGui.QColor(10, 8, 6))
        p.setPen(QtGui.QPen(QtGui.QColor(70, 60, 50), 0.8))
        p.drawRoundedRect(QtCore.QRectF(r.left() + 2, r.bottom() - 7, r.width() - 4, 9), 3, 3)


if __name__ == "__main__":                       # essai seul
    import sys
    app = QtWidgets.QApplication(sys.argv)
    d = NixieDisplay()
    d.setText(sys.argv[1] if len(sys.argv) > 1 else "7.100.000")
    d.show()
    sys.exit(app.exec_())
