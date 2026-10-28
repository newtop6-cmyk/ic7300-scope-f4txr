"""Poussoir vintage en relief (écran MOBILE) : lunette chromée, gorge noire,
capuchon bombé ivoire façon bakélite, inscription gravée. Allumé (lamp) :
le capuchon devient un voyant coloré qui luit. Enfoncé : il descend."""

from PyQt5 import QtCore, QtGui, QtWidgets


class VintagePush(QtWidgets.QPushButton):
    def __init__(self, text, width, height):
        super().__init__(text)
        self.setFixedSize(width, height)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.lamp = None                # QColor : capuchon allumé de cette couleur

    def set_lamp(self, color):
        color = QtGui.QColor(color) if color else None
        if (color.name() if color else None) != (self.lamp.name() if self.lamp else None):
            self.lamp = color
            self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QtCore.QRectF(1, 1, w - 2, h - 3)
        rad = min(w, h) * 0.22
        # ombre portée sur la façade
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.drawRoundedRect(r.translated(1.2, 2), rad, rad)
        # lunette chromée
        g = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        for stop, col in ((0, "#ffffff"), (0.2, "#c9ccc7"), (0.5, "#7c807a"),
                          (0.8, "#d9dcd7"), (1, "#4c4f4a")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1d1f1c"), 0.8))
        p.drawRoundedRect(r, rad, rad)
        # gorge noire
        gap = r.adjusted(3.5, 3.5, -3.5, -3.5)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#0c0d0b"))
        p.drawRoundedRect(gap, rad * 0.8, rad * 0.8)
        # capuchon : bombé, descend quand on appuie
        down = self.isDown()
        cap = gap.adjusted(2.2, 1.6 + (1.4 if down else 0), -2.2, -3.2 + (1.4 if down else 0))
        lit = self.lamp is not None
        if lit:
            base = self.lamp
            top, mid, bot = base.lighter(170), base, base.darker(190)
        else:
            top, mid, bot = QtGui.QColor("#fffaea"), QtGui.QColor("#e9dcb8"), QtGui.QColor("#9c8a5e")
        if down:
            top, mid, bot = top.darker(115), mid.darker(115), bot.darker(115)
        g = QtGui.QLinearGradient(0, cap.top(), 0, cap.bottom())
        g.setColorAt(0, top)
        g.setColorAt(0.45, mid)
        g.setColorAt(1, bot)
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 0.8))
        crad = rad * 0.65
        p.drawRoundedRect(cap, crad, crad)
        if lit:                                     # lueur intérieure du voyant
            glow = QtGui.QRadialGradient(cap.center(), max(cap.width(), cap.height()) * 0.6)
            c = QtGui.QColor(self.lamp.lighter(190))
            c.setAlpha(150)
            glow.setColorAt(0, c)
            glow.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(cap, crad, crad)
        # reflet bombé en haut du capuchon
        shine = cap.adjusted(cap.width() * 0.08, 1.2, -cap.width() * 0.08, -cap.height() * 0.52)
        g = QtGui.QLinearGradient(0, shine.top(), 0, shine.bottom())
        g.setColorAt(0, QtGui.QColor(255, 255, 255, 150 if not down else 80))
        g.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(shine, crad * 0.8, crad * 0.8)
        # inscription gravée
        f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Bold)
        lines = self.text().count("\n") + 1
        longest = max(len(line) for line in self.text().split("\n")) or 1
        f.setPixelSize(max(7, int(min(cap.height() / (lines * 1.45),
                                      cap.width() / (longest * 0.72)))))
        p.setFont(f)
        if lit:
            p.setPen(QtGui.QColor(0, 0, 0, 120))
            p.drawText(cap.translated(0, 0.8), QtCore.Qt.AlignCenter, self.text())
            p.setPen(QtGui.QColor("#ffffff"))
        else:
            p.setPen(QtGui.QColor(255, 255, 255, 170))       # bord clair de la gravure
            p.drawText(cap.translated(0, 0.8), QtCore.Qt.AlignCenter, self.text())
            p.setPen(QtGui.QColor("#2a2114"))
        p.drawText(cap, QtCore.Qt.AlignCenter, self.text())
        p.end()
