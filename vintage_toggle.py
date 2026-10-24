"""Interrupteur à levier vintage à deux positions (haut / bas), en relief :
plaque chromée vissée avec inscriptions gravées, écrou moleté, levier en
acier (« bat handle ») qui bascule avec une petite animation.
Clic ou molette = basculer."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets


class ToggleSwitch(QtWidgets.QWidget):
    toggled = QtCore.pyqtSignal(bool)          # True = levier en bas

    def __init__(self, up_text, down_text, width=88, height=88, tooltip=""):
        super().__init__()
        self.setFixedSize(width, height)
        self.up_text, self.down_text = up_text, down_text
        self.down = False
        self.pos_f = -1.0                       # -1 = haut, +1 = bas (animé)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    def setDown(self, down, emit=True):
        if down != self.down:
            self.down = down
            self.timer.start(16)
            if emit:
                self.toggled.emit(down)

    def mousePressEvent(self, event):
        self.setDown(not self.down)

    def wheelEvent(self, event):
        self.setDown(event.angleDelta().y() < 0)
        event.accept()

    def _tick(self):
        goal = 1.0 if self.down else -1.0
        self.pos_f += (goal - self.pos_f) * 0.35
        if abs(goal - self.pos_f) < 0.01:
            self.pos_f = goal
            self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = QtCore.QPointF(w / 2, h / 2)
        # plaque chromée vissée, ombre portée
        plate = QtCore.QRectF(6, 4, w - 12, h - 8)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 110))
        p.drawRoundedRect(plate.translated(2, 3), 8, 8)
        g = QtGui.QLinearGradient(plate.topLeft(), plate.bottomRight())
        for stop, col in ((0, "#fbfbfb"), (0.35, "#b9bdc2"), (0.55, "#e8eaec"),
                          (0.8, "#8d9297"), (1, "#c9ccd0")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#3a3d40"), 1.2))
        p.setBrush(g)
        p.drawRoundedRect(plate, 8, 8)
        for sy in (plate.top() + 8, plate.bottom() - 8):            # vis
            for sx in (plate.left() + 8, plate.right() - 8):
                sg = QtGui.QRadialGradient(sx - 1, sy - 1, 4)
                sg.setColorAt(0, QtGui.QColor("#ffffff"))
                sg.setColorAt(1, QtGui.QColor("#5e6266"))
                p.setPen(QtGui.QPen(QtGui.QColor("#2c2f31"), 0.8))
                p.setBrush(sg)
                p.drawEllipse(QtCore.QPointF(sx, sy), 3, 3)
                p.drawLine(QtCore.QPointF(sx - 2, sy - 2), QtCore.QPointF(sx + 2, sy + 2))
        # inscriptions gravées : la position active en rouge
        f = QtGui.QFont("DejaVu Sans Condensed", 7, QtGui.QFont.Black)
        p.setFont(f)
        for text, top, active in ((self.up_text, True, not self.down),
                                  (self.down_text, False, self.down)):
            r = QtCore.QRectF(plate.left(), plate.top() + 2 if top else plate.bottom() - 16,
                              plate.width(), 14)
            p.setPen(QtGui.QColor(255, 255, 255, 160))
            p.drawText(r.translated(0, 0.8), QtCore.Qt.AlignCenter, text)
            p.setPen(QtGui.QColor("#c62828" if active else "#1a1c1e"))
            p.drawText(r, QtCore.Qt.AlignCenter, text)
        # écrou moleté
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 100))
        p.drawEllipse(c + QtCore.QPointF(1, 2), 13, 13)
        g = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#6e7378"), (0.5, "#e6e8ea"),
                          (0.75, "#50555a"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1c1e20"), 1))
        p.drawEllipse(c, 12, 12)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 80), 0.8))
        for i in range(40):
            a = math.radians(i * 9)
            u = QtCore.QPointF(math.cos(a), math.sin(a))
            p.drawLine(c + u * 9.5, c + u * 12)
        g = QtGui.QRadialGradient(c - QtCore.QPointF(2, 2), 9)
        g.setColorAt(0, QtGui.QColor("#f0f1f2"))
        g.setColorAt(1, QtGui.QColor("#6a6f74"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#222"), 0.8))
        p.drawEllipse(c, 7, 7)
        # levier en acier, vu en perspective : il part du centre vers le haut ou le bas
        length = 15 * abs(self.pos_f) + 3
        tip = c + QtCore.QPointF(0, length * (1 if self.pos_f > 0 else -1))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 90), 7, cap=QtCore.Qt.RoundCap))
        p.drawLine(c + QtCore.QPointF(2, 3), tip + QtCore.QPointF(3, 4))
        stem = QtGui.QLinearGradient(c.x() - 4, 0, c.x() + 4, 0)
        stem.setColorAt(0, QtGui.QColor("#4a4d50"))
        stem.setColorAt(0.4, QtGui.QColor("#f4f5f6"))
        stem.setColorAt(1, QtGui.QColor("#5c6064"))
        path = QtGui.QPainterPath()                 # tige évasée (« bat handle »)
        sgn = 1 if self.pos_f > 0 else -1
        path.moveTo(c.x() - 3, c.y())
        path.lineTo(c.x() + 3, c.y())
        path.lineTo(tip.x() + 5, tip.y() - sgn * 4)
        path.quadTo(tip.x(), tip.y() + sgn * 4, tip.x() - 5, tip.y() - sgn * 4)
        path.closeSubpath()
        p.setPen(QtGui.QPen(QtGui.QColor("#26282a"), 0.9))
        p.setBrush(stem)
        p.drawPath(path)
        g = QtGui.QRadialGradient(tip - QtCore.QPointF(1.5, 1.5), 7)   # bout arrondi
        g.setColorAt(0, QtGui.QColor("#ffffff"))
        g.setColorAt(0.5, QtGui.QColor("#a9adb1"))
        g.setColorAt(1, QtGui.QColor("#3c3f42"))
        p.setBrush(g)
        p.drawEllipse(tip, 5.5, 5.5)
        p.end()
