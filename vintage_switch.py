"""Interrupteur à bascule vintage et voyants bleus pour le pas du bouton VFO.

  LeverSwitch : levier métallique argenté horizontal, petite boule au bout,
                sur une platine graduée ; deux positions (gauche / droite).
  BlueLed     : voyant bleu rond ; allumé fixe ou clignotant.
"""

import math

from PyQt5 import QtCore, QtGui, QtWidgets


class LeverSwitch(QtWidgets.QWidget):
    """Interrupteur à levier : clic n'importe où = bascule. Position False =
    gauche, True = droite. Le levier pivote au centre avec une petite animation."""

    toggled = QtCore.pyqtSignal(bool)

    def __init__(self, left_text, right_text, width=150, height=46, vertical=False):
        super().__init__()
        self.vertical = vertical        # debout : levier en haut = enclenché
        self.setFixedSize(height, width) if vertical else self.setFixedSize(width, height)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.left_text, self.right_text = left_text, right_text
        self.state = False
        self.pos_f = -1.0               # -1 = gauche, +1 = droite (animé)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    def setChecked(self, on):
        if on != self.state:
            self.state = on
            self.timer.start(16)
            self.toggled.emit(on)

    def isChecked(self):
        return self.state

    def mousePressEvent(self, event):
        self.setChecked(not self.state)

    def _tick(self):
        goal = 1.0 if self.state else -1.0
        self.pos_f += (goal - self.pos_f) * 0.35
        if abs(goal - self.pos_f) < 0.01:
            self.pos_f = goal
            self.timer.stop()
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self.vertical:               # on dessine couché puis on redresse (-90°)
            w, h = h, w
            p.translate(self.width() / 2, self.height() / 2)
            p.rotate(-90)
            p.translate(-w / 2, -h / 2)
        cx, cy = w / 2, h / 2 + 2
        # platine argentée brossée, vissée
        plate = QtCore.QRectF(4, 6, w - 8, h - 10)
        g = QtGui.QLinearGradient(0, plate.top(), 0, plate.bottom())
        g.setColorAt(0, QtGui.QColor("#f2f2f2"))
        g.setColorAt(0.45, QtGui.QColor("#b9bcc0"))
        g.setColorAt(0.55, QtGui.QColor("#a4a8ad"))
        g.setColorAt(1, QtGui.QColor("#6e7378"))
        p.setPen(QtGui.QPen(QtGui.QColor("#3a3d40"), 1))
        p.setBrush(g)
        p.drawRoundedRect(plate, 5, 5)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 35), 1))
        for y in range(int(plate.top()) + 3, int(plate.bottom()) - 2, 2):   # brossage
            p.drawLine(QtCore.QPointF(plate.left() + 3, y), QtCore.QPointF(plate.right() - 3, y))
        for sx in (plate.left() + 7, plate.right() - 7):                    # vis
            sg = QtGui.QRadialGradient(sx - 1, cy - 1, 4)
            sg.setColorAt(0, QtGui.QColor("#ffffff"))
            sg.setColorAt(1, QtGui.QColor("#6a6e72"))
            p.setPen(QtGui.QPen(QtGui.QColor("#45484b"), 0.8))
            p.setBrush(sg)
            p.drawEllipse(QtCore.QPointF(sx, cy), 3, 3)
            p.drawLine(QtCore.QPointF(sx - 2, cy), QtCore.QPointF(sx + 2, cy))
        # graduations gravées et inscriptions
        ink = QtGui.QColor("#1e2124")
        p.setPen(QtGui.QPen(ink, 1))
        for i in range(-4, 5):
            x = cx + i * w / 17
            big = i in (-4, 0, 4)
            p.drawLine(QtCore.QPointF(x, plate.top() + 3),
                       QtCore.QPointF(x, plate.top() + (8 if big else 5)))
        p.setFont(QtGui.QFont("DejaVu Sans", 7, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(plate.left() + 12, plate.bottom() - 13, 60, 11),
                   QtCore.Qt.AlignLeft, self.left_text)
        p.drawText(QtCore.QRectF(plate.right() - 72, plate.bottom() - 13, 60, 11),
                   QtCore.Qt.AlignRight, self.right_text)
        # bague du pivot, au centre
        ring = QtGui.QRadialGradient(cx - 2, cy - 2, 10)
        ring.setColorAt(0, QtGui.QColor("#ffffff"))
        ring.setColorAt(0.6, QtGui.QColor("#9a9ea2"))
        ring.setColorAt(1, QtGui.QColor("#3e4144"))
        p.setPen(QtGui.QPen(QtGui.QColor("#2c2f31"), 1))
        p.setBrush(ring)
        p.drawEllipse(QtCore.QPointF(cx, cy), 8, 8)
        # levier : tige chromée en perspective, boule au bout
        # levier parfaitement horizontal : pointe à gauche ou à droite
        length = w * 0.30
        tip = QtCore.QPointF(cx + length * self.pos_f, cy)
        # ombre du levier sur la platine
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 80), 5, cap=QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(cx + 2, cy + 3), tip + QtCore.QPointF(3, 5))
        stem = QtGui.QLinearGradient(0, cy - 4, 0, cy + 4)
        stem.setColorAt(0, QtGui.QColor("#ffffff"))
        stem.setColorAt(0.5, QtGui.QColor("#a6aaae"))
        stem.setColorAt(1, QtGui.QColor("#4a4d50"))
        p.setPen(QtGui.QPen(QtGui.QBrush(stem), 4.5, cap=QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(cx, cy), tip)
        # petite boule chromée
        ball = QtGui.QRadialGradient(tip - QtCore.QPointF(2, 2), 7)
        ball.setColorAt(0, QtGui.QColor("#ffffff"))
        ball.setColorAt(0.5, QtGui.QColor("#b8bcc0"))
        ball.setColorAt(1, QtGui.QColor("#3c3f42"))
        p.setPen(QtGui.QPen(QtGui.QColor("#2a2c2e"), 0.8))
        p.setBrush(ball)
        p.drawEllipse(tip, 5.5, 5.5)
        p.end()


class BlueLed(QtWidgets.QWidget):
    """Voyant bleu : éteint, allumé fixe, ou clignotant."""

    def __init__(self, size=22, period_ms=250):
        super().__init__()
        self.setFixedSize(size, size)
        self.mode = "off"               # off, on, blink
        self.phase = True
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._blink)
        self.timer.start(period_ms)     # 250 ms = 2 éclats/s ; 70 ms = flash rapide

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def _blink(self):
        self.phase = not self.phase
        if self.mode == "blink":
            self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s = self.width()
        c = QtCore.QPointF(s / 2, s / 2)
        lit = self.mode == "on" or (self.mode == "blink" and self.phase)
        p.setPen(QtCore.Qt.NoPen)
        if lit:
            # grand halo bleu éclatant
            halo = QtGui.QRadialGradient(c, s / 2)
            halo.setColorAt(0.0, QtGui.QColor(150, 210, 255, 255))
            halo.setColorAt(0.35, QtGui.QColor(60, 150, 255, 200))
            halo.setColorAt(1.0, QtGui.QColor(30, 110, 255, 0))
            p.setBrush(halo)
            p.drawEllipse(c, s / 2, s / 2)
        r = s * 0.24
        g = QtGui.QRadialGradient(c - QtCore.QPointF(r * 0.3, r * 0.3), r * 1.2)
        if lit:                         # cœur presque blanc : très lumineux
            g.setColorAt(0, QtGui.QColor("#ffffff"))
            g.setColorAt(0.4, QtGui.QColor("#9fd4ff"))
            g.setColorAt(1, QtGui.QColor("#1e6bff"))
        else:                           # éteint : presque noir
            g.setColorAt(0, QtGui.QColor("#1a2030"))
            g.setColorAt(1, QtGui.QColor("#05070c"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.setBrush(g)
        p.drawEllipse(c, r, r)
        p.end()


class SilverPlate(QtWidgets.QFrame):
    """Plaque d'aluminium argenté brossé, vissée aux 4 coins (fond pour
    des interrupteurs)."""

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QtCore.QRectF(1, 1, w - 2, h - 2)
        g = QtGui.QLinearGradient(0, 0, w, h)
        g.setColorAt(0, QtGui.QColor("#e9e9e6"))
        g.setColorAt(0.5, QtGui.QColor("#b3b4b2"))
        g.setColorAt(1, QtGui.QColor("#7d7f80"))
        p.setPen(QtGui.QPen(QtGui.QColor("#3b3d3f"), 1.2))
        p.setBrush(g)
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 30), 1))
        for y in range(4, h - 3, 2):                     # brossage
            p.drawLine(QtCore.QPointF(4, y), QtCore.QPointF(w - 4, y))
        for sx, sy in ((9, 9), (w - 9, 9), (9, h - 9), (w - 9, h - 9)):
            sg = QtGui.QRadialGradient(sx - 1, sy - 1, 4)
            sg.setColorAt(0, QtGui.QColor("#ffffff"))
            sg.setColorAt(1, QtGui.QColor("#6a6e72"))
            p.setPen(QtGui.QPen(QtGui.QColor("#45484b"), 0.8))
            p.setBrush(sg)
            p.drawEllipse(QtCore.QPointF(sx, sy), 3.2, 3.2)
            p.drawLine(QtCore.QPointF(sx - 2, sy - 2), QtCore.QPointF(sx + 2, sy + 2))
        p.end()
