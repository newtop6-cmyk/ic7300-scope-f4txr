"""Bouton poussoir vintage posé sur une plaque d'aluminium brossé vissée :
gros bouton rouge bombé dans une bague chromée, qui s'enfonce au clic, nom
gravé en noir sous le bouton, petit voyant ambre (allumé pendant l'action)."""

from PyQt5 import QtCore, QtGui, QtWidgets


class PushPlate(QtWidgets.QWidget):
    clicked = QtCore.pyqtSignal()

    def __init__(self, text, width=100, height=112, tooltip=""):
        super().__init__()
        self.text = text
        self.setFixedSize(width, height)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.pressed = False
        self.lit = False                        # voyant ambre
        self.blink = True
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._blink)

    def set_lit(self, on):
        self.lit = on
        if on:
            self.blink = True
            self.timer.start(550)               # clignotement lent et franc
        else:
            self.timer.stop()
        self.update()

    def _blink(self):
        self.blink = not self.blink
        self.update()

    def mousePressEvent(self, event):
        if self.isEnabled():
            self.pressed = True
            self.update()

    def mouseReleaseEvent(self, event):
        if self.pressed:
            self.pressed = False
            self.update()
            if self.rect().contains(event.pos()):
                self.clicked.emit()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # plaque d'aluminium brossé, ombre portée, 4 vis
        plate = QtCore.QRectF(4, 3, w - 9, h - 8)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 120))
        p.drawRoundedRect(plate.translated(3, 4), 9, 9)
        g = QtGui.QLinearGradient(plate.topLeft(), plate.bottomRight())
        for stop, col in ((0, "#fafbfb"), (0.4, "#c3c7cb"), (0.6, "#e3e5e7"), (1, "#8e9398")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#3a3d40"), 1.2))
        p.setBrush(g)
        p.drawRoundedRect(plate, 9, 9)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 45), 0.7))     # brossage
        for y in range(int(plate.top()) + 4, int(plate.bottom()) - 3, 2):
            p.drawLine(QtCore.QPointF(plate.left() + 4, y), QtCore.QPointF(plate.right() - 4, y))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 140), 1))       # arête claire
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(plate.adjusted(1.5, 1.5, -1.5, -1.5), 8, 8)
        for sx, sy in ((plate.left() + 9, plate.top() + 9), (plate.right() - 9, plate.top() + 9),
                       (plate.left() + 9, plate.bottom() - 9), (plate.right() - 9, plate.bottom() - 9)):
            sg = QtGui.QRadialGradient(sx - 1, sy - 1, 4)
            sg.setColorAt(0, QtGui.QColor("#ffffff"))
            sg.setColorAt(1, QtGui.QColor("#5e6266"))
            p.setPen(QtGui.QPen(QtGui.QColor("#2c2f31"), 0.8))
            p.setBrush(sg)
            p.drawEllipse(QtCore.QPointF(sx, sy), 3.2, 3.2)
            p.drawLine(QtCore.QPointF(sx - 2.2, sy), QtCore.QPointF(sx + 2.2, sy))
        # voyant ambre en haut
        lc = QtCore.QPointF(plate.center().x(), plate.top() + 12)
        on = self.lit and self.blink
        if on:
            hg = QtGui.QRadialGradient(lc, 13)
            hg.setColorAt(0, QtGui.QColor(255, 160, 30, 210))
            hg.setColorAt(1, QtGui.QColor(255, 120, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(hg)
            p.drawEllipse(lc, 13, 13)
        rg = QtGui.QConicalGradient(lc, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#777c82"), (0.5, "#e6e8ea"),
                          (0.75, "#585d63"), (1, "#ffffff")):
            rg.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(rg)
        p.setPen(QtGui.QPen(QtGui.QColor("#16181a"), 0.8))
        p.drawEllipse(lc, 5.5, 5.5)
        lg = QtGui.QRadialGradient(lc - QtCore.QPointF(1, 1), 4.5)
        lg.setColorAt(0, QtGui.QColor("#fff6d0" if on else "#7a5a32"))
        lg.setColorAt(1, QtGui.QColor("#e07000" if on else "#201508"))
        p.setBrush(lg)
        p.drawEllipse(lc, 3.6, 3.6)
        # bague chromée du poussoir
        c = QtCore.QPointF(plate.center().x(), plate.top() + 50)
        flash_on = self.lit and self.blink      # action en cours : grand éclat rouge
        if flash_on:
            hg = QtGui.QRadialGradient(c, 50)
            hg.setColorAt(0, QtGui.QColor(255, 40, 20, 255))
            hg.setColorAt(0.5, QtGui.QColor(230, 10, 0, 210))
            hg.setColorAt(1, QtGui.QColor(200, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(hg)
            p.drawEllipse(c, 50, 50)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 100))
        p.drawEllipse(c + QtCore.QPointF(1.5, 2.5), 25, 25)
        g = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#6e7378"), (0.5, "#eceef0"),
                          (0.75, "#4f5459"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1c1e20"), 1))
        p.drawEllipse(c, 24, 24)
        p.setBrush(QtGui.QColor("#121314"))                        # creux de la bague
        p.drawEllipse(c, 18.5, 18.5)
        # poussoir rouge bombé : il s'enfonce (plus petit, plus sombre, sans ombre)
        sink = 1.5 if self.pressed else 0.0
        r = 17 - sink
        bc = c + QtCore.QPointF(0, sink * 0.6)
        if not self.pressed:
            p.setBrush(QtGui.QColor(0, 0, 0, 120))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(bc + QtCore.QPointF(1, 2), r, r)
        g = QtGui.QRadialGradient(bc - QtCore.QPointF(r * 0.35, r * 0.4), r * 1.5)
        enabled = self.isEnabled()
        if self.lit:                            # action en cours : flash rouge
            if flash_on:
                g.setColorAt(0, QtGui.QColor("#ffffff"))
                g.setColorAt(0.25, QtGui.QColor("#ffb09a"))
                g.setColorAt(0.6, QtGui.QColor("#ff2a10"))
                g.setColorAt(1, QtGui.QColor("#a00800"))
            else:
                g.setColorAt(0, QtGui.QColor("#5a1a14"))
                g.setColorAt(1, QtGui.QColor("#1a0302"))
        elif self.pressed:
            g.setColorAt(0, QtGui.QColor("#d84a3a"))
            g.setColorAt(1, QtGui.QColor("#4a0a04"))
        elif enabled:
            g.setColorAt(0, QtGui.QColor("#ff8a75"))
            g.setColorAt(0.45, QtGui.QColor("#d0281a"))
            g.setColorAt(1, QtGui.QColor("#5a0d06"))
        else:
            g.setColorAt(0, QtGui.QColor("#9a7a76"))
            g.setColorAt(1, QtGui.QColor("#3a2a28"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#2a0502"), 1))
        p.drawEllipse(bc, r, r)
        hl = QtCore.QRectF(bc.x() - r * 0.6, bc.y() - r * 0.75, r * 0.9, r * 0.55)   # reflet
        hg = QtGui.QLinearGradient(hl.topLeft(), hl.bottomLeft())
        hg.setColorAt(0, QtGui.QColor(255, 255, 255, 60 if self.pressed else 150))
        hg.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(hg)
        p.drawEllipse(hl)
        # nom gravé
        f = QtGui.QFont("DejaVu Sans Condensed", 10, QtGui.QFont.Black)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        tr = QtCore.QRectF(plate.left(), plate.bottom() - 26, plate.width(), 16)
        p.setPen(QtGui.QColor(255, 255, 255, 170))
        p.drawText(tr.translated(0, 1), QtCore.Qt.AlignCenter, self.text)
        p.setPen(QtGui.QColor("#121212"))
        p.drawText(tr, QtCore.Qt.AlignCenter, self.text)
        p.end()
