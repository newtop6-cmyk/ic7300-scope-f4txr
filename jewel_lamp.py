"""Voyant « bijou » vintage : lentille de verre bombée taillée en facettes,
dans une bague chromée moletée. Allumé : la lentille luit et projette un
halo ; éteint : verre sombre qui accroche seulement les reflets."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets


class JewelLamp(QtWidgets.QWidget):
    def __init__(self, color, size=78, tooltip="", text=""):
        super().__init__()
        self.setFixedSize(size, size)
        self.text = text                    # nom gravé au centre (TUNE…)
        self.color = QtGui.QColor(color)
        self.on = False
        self.glow = 0.0                     # 0 éteint → 1 allumé (allumage progressif)
        if tooltip:
            self.setToolTip(tooltip)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    def set_on(self, on):
        on = bool(on)
        if on != self.on:
            self.on = on
            self.timer.start(16)

    def _tick(self):
        goal = 1.0 if self.on else 0.0
        self.glow += (goal - self.glow) * (0.35 if self.on else 0.18)   # filament : s'éteint plus doucement
        if abs(goal - self.glow) < 0.01:
            self.glow = goal
            self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s = self.width()
        c = QtCore.QPointF(s / 2, s / 2)
        R = s / 2 - 2
        col, g = self.color, self.glow
        # halo autour du voyant allumé
        if g > 0.02:
            halo = QtGui.QRadialGradient(c, R)
            h = QtGui.QColor(col)
            h.setAlpha(int(110 * g))
            halo.setColorAt(0.55, h)
            halo.setColorAt(1, QtGui.QColor(col.red(), col.green(), col.blue(), 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, R, R)
        # bague chromée moletée
        rb = R * 0.80
        ring = QtGui.QConicalGradient(c, 135)
        for stop, cc in ((0, "#ffffff"), (0.25, "#6f736e"), (0.5, "#e6e8e4"),
                         (0.75, "#4f534e"), (1, "#ffffff")):
            ring.setColorAt(stop, QtGui.QColor(cc))
        p.setBrush(ring)
        p.setPen(QtGui.QPen(QtGui.QColor("#1b1d1a"), 1))
        p.drawEllipse(c, rb, rb)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 0.8))        # moletage
        for i in range(48):
            a = math.radians(i * 7.5)
            d = QtCore.QPointF(math.cos(a), math.sin(a))
            p.drawLine(c + d * (rb - 3.2), c + d * (rb - 0.6))
        # lentille bombée taillée en facettes
        rl = rb * 0.74
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#050505"))
        p.drawEllipse(c, rl + 1.5, rl + 1.5)
        dark = QtGui.QColor(col).darker(420)
        lit = QtGui.QColor(col)

        def mix(a, b, t):
            return QtGui.QColor(int(a.red() + (b.red() - a.red()) * t),
                                int(a.green() + (b.green() - a.green()) * t),
                                int(a.blue() + (b.blue() - a.blue()) * t))

        base = mix(dark, lit, g)
        rings = (1.0, 0.72, 0.42)            # 3 couronnes de facettes + table centrale
        sides = 12
        for k in range(len(rings)):
            r_out, r_in = rl * rings[k], rl * (rings[k + 1] if k + 1 < len(rings) else 0.2)
            for i in range(sides):
                off = (k % 2) * 0.5
                a0 = math.radians((i + off) * 360 / sides - 90)
                a1 = math.radians((i + 1 + off) * 360 / sides - 90)
                am = (a0 + a1) / 2
                poly = QtGui.QPolygonF([
                    c + QtCore.QPointF(math.cos(a0), math.sin(a0)) * r_out,
                    c + QtCore.QPointF(math.cos(a1), math.sin(a1)) * r_out,
                    c + QtCore.QPointF(math.cos(am), math.sin(am)) * r_in])
                # chaque facette renvoie la lumière selon son orientation
                light = 0.5 + 0.5 * math.cos(am - math.radians(-135))
                f = base.lighter(int(55 + 75 * light + 15 * g * (1 - k / 3)))
                p.setBrush(f)
                p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, int(40 + 50 * light)), 0.6))
                p.drawPolygon(poly)
        table = QtGui.QRadialGradient(c, rl * 0.3)
        table.setColorAt(0, mix(dark, lit.lighter(160), 0.25 + 0.75 * g))
        table.setColorAt(1, base)
        p.setBrush(table)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 70), 0.6))
        sides_t = QtGui.QPolygonF([c + QtCore.QPointF(math.cos(math.radians(i * 30 - 90)),
                                                      math.sin(math.radians(i * 30 - 90))) * rl * 0.22
                                   for i in range(12)])
        p.drawPolygon(sides_t)
        # cœur lumineux quand allumé
        if g > 0.02:
            core = QtGui.QRadialGradient(c, rl * 0.8)
            core.setColorAt(0, QtGui.QColor(255, 255, 230, int(120 * g)))
            core.setColorAt(0.4, QtGui.QColor(lit.red(), lit.green(), lit.blue(), int(110 * g)))
            core.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(core)
            p.drawEllipse(c, rl, rl)
        # reflet de la verrière (bombé)
        hl = QtGui.QRadialGradient(c - QtCore.QPointF(rl * 0.38, rl * 0.42), rl * 0.5)
        hl.setColorAt(0, QtGui.QColor(255, 255, 255, 200))
        hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawEllipse(c - QtCore.QPointF(rl * 0.38, rl * 0.42), rl * 0.42, rl * 0.3)
        if self.text:                       # nom gravé au centre de la lentille
            f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Bold)
            f.setPixelSize(max(8, int(rl * 0.42)))
            f.setLetterSpacing(QtGui.QFont.PercentageSpacing, 104)
            p.setFont(f)
            box = QtCore.QRectF(c.x() - rl, c.y() - rl, 2 * rl, 2 * rl)
            p.setPen(QtGui.QColor(0, 0, 0, 200))
            p.drawText(box.translated(0.9, 1.1), QtCore.Qt.AlignCenter, self.text)
            p.setPen(QtGui.QColor(255, 248, 225, int(170 + 85 * g)))
            p.drawText(box, QtCore.Qt.AlignCenter, self.text)
        p.end()


if __name__ == "__main__":                       # essai seul
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    for colr, on in (("#22e05a", True), ("#ff2a1a", False)):
        lamp = JewelLamp(colr)
        lamp.set_on(on)
        lay.addWidget(lamp)
    w.show()
    sys.exit(app.exec_())
