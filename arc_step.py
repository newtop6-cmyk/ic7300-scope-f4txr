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
    RO, BAND = 360.0, 22.0              # rayon extérieur de l'arc, épaisseur
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
        return QtCore.QPointF(self.W / 2, 9 + self.RO)

    def _angles(self):
        """Angle (degrés depuis le haut) de chaque pas, de gauche à droite."""
        n = len(STEPS)
        return [-self.SPAN * 0.66 + i * (2 * self.SPAN * 0.66) / (n - 1) for i in range(n)]

    def _band(self, grow=0.0):
        """Bande en arc aux extrémités ARRONDIES (tracé épais à bouts ronds)."""
        c = self._center()
        r = self.RO - self.BAND / 2
        line = QtGui.QPainterPath()
        rect = QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        span = self.SPAN - (self.BAND / 2) / r * 57.3      # place pour les bouts ronds
        line.arcMoveTo(rect, 90 - span)
        line.arcTo(rect, 90 - span, 2 * span)
        st = QtGui.QPainterPathStroker()
        st.setWidth(self.BAND + 2 * grow)
        st.setCapStyle(QtCore.Qt.RoundCap)
        return st.createStroke(line).simplified()

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
        # ombre portée marquée du cadre sur la façade
        frame = self._band(6.5)
        for i in range(8, 0, -1):
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 24))
            p.drawPath(frame.translated(i * 0.35, i * 0.6))
        # cadre chromé ÉPAIS, bombé : lumière en haut, sombre en bas
        g = QtGui.QLinearGradient(0, 0, 0, self.H)
        for stop, col in ((0, "#ffffff"), (0.22, "#c7cac6"), (0.45, "#6f736e"),
                          (0.7, "#dadcd8"), (1, "#3c3f3b")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#0f100e"), 1.2))
        p.drawPath(frame)
        p.setBrush(QtCore.Qt.NoBrush)                   # arête de lumière extérieure
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 170), 1.1))
        p.drawPath(self._band(5.4))
        # gorge sombre entre le cadre et la vitre (la vitre est enfoncée)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#050505"))
        p.drawPath(self._band(1.8))
        p.setBrush(QtCore.Qt.NoBrush)                   # lèvre claire au fond de la gorge
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 0.8))
        p.drawPath(self._band(1.0))
        # vitre creusée, rétroéclairée
        glass = self._band()
        bg = QtGui.QRadialGradient(c, self.RO)
        bg.setColorAt(1 - (self.BAND + 4) / self.RO, QtGui.QColor("#1a0d02"))
        bg.setColorAt(1 - self.BAND / 2 / self.RO, QtGui.QColor("#3e2309"))
        bg.setColorAt(1.0, QtGui.QColor("#0c0601"))
        p.setBrush(bg)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.2))
        p.drawPath(glass)
        # ombre intérieure forte : haut de la vitre et bouts dans l'ombre du cadre
        p.save()
        p.setClipPath(glass)
        inner = QtGui.QRadialGradient(c, self.RO)
        inner.setColorAt(1 - 11 / self.RO, QtGui.QColor(0, 0, 0, 0))
        inner.setColorAt(1.0, QtGui.QColor(0, 0, 0, 235))
        p.fillPath(glass, inner)
        for side in (-1, 1):                            # bouts assombris
            x = self.W / 2 + side * self.W / 2
            sg = QtGui.QLinearGradient(x, 0, self.W / 2, 0)
            sg.setColorAt(0, QtGui.QColor(0, 0, 0, 200))
            sg.setColorAt(0.16, QtGui.QColor(0, 0, 0, 0))
            p.fillPath(glass, sg)
        p.restore()
        # les 4 pas gravés le long de l'arc
        r_text = self.RO - self.BAND / 2
        f = QtGui.QFont("DejaVu Sans Condensed")
        f.setPixelSize(14)
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
