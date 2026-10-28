"""Lucarne en arc (demi-cercle aplati) posée au-dessus du VFO : fenêtre
rétroéclairée ambre où les 4 pas ×1, ×10, ×100, ×1000 sont gravés le long de
l'arc ; le pas en cours luit, les autres restent sombres. Clic sur un pas =
ce pas (signal chosen(hz))."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets

STEPS = ((1, "×1"), (10, "×10"), (100, "×100"), (1000, "×1000"))


class ArcStepWindow(QtWidgets.QWidget):
    chosen = QtCore.pyqtSignal(int)

    W, H = 250, 50
    RO, BAND = 360.0, 25.0              # rayon extérieur de l'arc, épaisseur
    SPAN = 17.5                          # demi-ouverture (degrés)

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.current = 1000
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Pas du VFO : le pas allumé est celui en cours ; "
                        "cliquer sur un pas pour le choisir")

    def set_current(self, hz):
        if hz != self.current:
            self.current = hz
            self.update()

    def _center(self):
        return QtCore.QPointF(self.W / 2, 4 + self.RO)

    def _angles(self):
        """Angle (degrés depuis le haut) de chaque pas, de gauche à droite."""
        n = len(STEPS)
        return [-self.SPAN * 0.74 + i * (2 * self.SPAN * 0.74) / (n - 1) for i in range(n)]

    def _band(self, grow=0.0):
        c, ro, ri = self._center(), self.RO + grow, self.RO - self.BAND - grow
        path = QtGui.QPainterPath()
        a0, a1 = 90 - self.SPAN - grow * 0.2, 90 + self.SPAN + grow * 0.2
        out = QtCore.QRectF(c.x() - ro, c.y() - ro, 2 * ro, 2 * ro)
        inn = QtCore.QRectF(c.x() - ri, c.y() - ri, 2 * ri, 2 * ri)
        path.arcMoveTo(out, a0)
        path.arcTo(out, a0, a1 - a0)
        path.arcTo(inn, a1, -(a1 - a0))
        path.closeSubpath()
        return path

    def mousePressEvent(self, event):
        c = self._center()
        d = event.pos() - c
        deg = math.degrees(math.atan2(d.x(), -d.y()))
        best = min(zip(self._angles(), STEPS), key=lambda t: abs(t[0] - deg))
        self.chosen.emit(best[1][0])
        event.accept()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = self._center()
        # cadre chromé, puis verre sombre rétroéclairé
        frame = self._band(3.0)
        g = QtGui.QLinearGradient(0, 0, 0, self.H)
        for stop, col in ((0, "#f2f3f1"), (0.4, "#8c8f8b"), (0.7, "#d5d7d3"), (1, "#5d605c")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1))
        p.drawPath(frame)
        glass = self._band()
        bg = QtGui.QRadialGradient(c, self.RO)
        bg.setColorAt(1 - (self.BAND + 4) / self.RO, QtGui.QColor("#120a02"))
        bg.setColorAt(1 - self.BAND / 2 / self.RO, QtGui.QColor("#2e1a06"))
        bg.setColorAt(1.0, QtGui.QColor("#140b02"))
        p.setBrush(bg)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawPath(glass)
        # les 4 pas gravés le long de l'arc
        r_text = self.RO - self.BAND / 2
        f = QtGui.QFont("DejaVu Sans Condensed")
        f.setPixelSize(15)
        f.setWeight(QtGui.QFont.Black)
        p.setFont(f)
        fm = QtGui.QFontMetricsF(f)
        p.save()
        p.setClipPath(glass)                            # halo et texte dans la vitre
        for ang, (hz, txt) in zip(self._angles(), STEPS):
            lit = hz == self.current
            p.save()
            p.translate(c)
            p.rotate(ang)
            p.translate(0, -r_text)
            w = fm.horizontalAdvance(txt)
            box = QtCore.QRectF(-w / 2 - 4, -fm.height() / 2, w + 8, fm.height())
            if lit:                                     # halo du pas en cours
                halo = QtGui.QRadialGradient(QtCore.QPointF(0, 0), w * 0.9)
                halo.setColorAt(0, QtGui.QColor(255, 160, 40, 150))
                halo.setColorAt(1, QtGui.QColor(255, 160, 40, 0))
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(halo)
                p.drawEllipse(QtCore.QPointF(0, 0), w * 0.9, fm.height() * 0.9)
            p.setPen(QtGui.QColor("#ffc04a" if lit else "#5a3d16"))
            p.drawText(box, QtCore.Qt.AlignCenter, txt)
            p.restore()
        p.restore()
        # reflet du verre en haut de l'arc
        p.save()
        p.setClipPath(glass)
        gl = QtGui.QLinearGradient(0, 0, 0, self.H * 0.6)
        gl.setColorAt(0, QtGui.QColor(255, 255, 255, 45))
        gl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), gl)
        p.restore()
        p.end()
