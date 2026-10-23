"""Petit potentiomètre rond « vintage » (bouton bakélite à index) pour un
réglage fin : molette = 1 cran, Maj+molette = 10 crans, glisser haut/bas."""

import math
import time

from PyQt5 import QtCore, QtGui, QtWidgets

SWEEP = 270.0                   # course du bouton (degrés)


class PotKnob(QtWidgets.QWidget):
    valueChanged = QtCore.pyqtSignal(int)       # seulement quand on le tourne

    def __init__(self, minimum=0, maximum=255, size=34):
        super().__init__()
        self.minimum, self.maximum = minimum, maximum
        self.value = minimum
        self.user_time = 0.0
        self._drag_y = None
        self._drag_value = 0.0
        self._wheel = 0
        self.setFixedSize(size, size)
        self.setCursor(QtCore.Qt.SizeVerCursor)

    def setValue(self, value):
        """Valeur lue dans la radio : ignorée pendant qu'on le règle."""
        if time.monotonic() - self.user_time < 1.5 or self._drag_y is not None:
            return
        self.value = max(self.minimum, min(self.maximum, int(value)))
        self.update()

    def _user_set(self, value):
        value = max(self.minimum, min(self.maximum, int(round(value))))
        self.user_time = time.monotonic()
        if value != self.value:
            self.value = value
            self.update()
            self.valueChanged.emit(value)

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            fine = 10 if event.modifiers() & QtCore.Qt.ShiftModifier else 1
            self._user_set(self.value + steps * fine)
        event.accept()

    def mousePressEvent(self, event):
        self._drag_y = event.pos().y()
        self._drag_value = self.value

    def mouseMoveEvent(self, event):
        if self._drag_y is None:
            return
        # 2 pixels = 1 cran : réglage fin à la souris
        self._user_set(self._drag_value + (self._drag_y - event.pos().y()) / 2)

    def mouseReleaseEvent(self, event):
        self._drag_y = None

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w = self.width()
        c = QtCore.QPointF(w / 2, w / 2)
        r = w / 2 - 1
        frac = (self.value - self.minimum) / max(1, self.maximum - self.minimum)
        # échelle : arc sombre + arc vert jusqu'à la valeur
        box = QtCore.QRectF(c.x() - r + 1.5, c.y() - r + 1.5, 2 * r - 3, 2 * r - 3)
        start = int((225) * 16)
        p.setPen(QtGui.QPen(QtGui.QColor("#263238"), 3, cap=QtCore.Qt.FlatCap))
        p.drawArc(box, start, int(-SWEEP * 16))
        p.setPen(QtGui.QPen(QtGui.QColor("#3ddc84"), 3, cap=QtCore.Qt.FlatCap))
        p.drawArc(box, start, int(-SWEEP * frac * 16))
        # corps bakélite en relief
        body = r - 5
        grad = QtGui.QRadialGradient(c - QtCore.QPointF(body / 3, body / 3), body * 1.6)
        grad.setColorAt(0, QtGui.QColor("#6b5a4a"))
        grad.setColorAt(0.5, QtGui.QColor("#2b211a"))
        grad.setColorAt(1, QtGui.QColor("#0d0906"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1))
        p.setBrush(grad)
        p.drawEllipse(c, body, body)
        # index blanc
        a = math.radians(225 - SWEEP * frac)
        tip = c + QtCore.QPointF(math.cos(a), -math.sin(a)) * (body - 2)
        base = c + QtCore.QPointF(math.cos(a), -math.sin(a)) * (body * 0.35)
        p.setPen(QtGui.QPen(QtGui.QColor("#f5f5f5"), 2, cap=QtCore.Qt.RoundCap))
        p.drawLine(base, tip)
        p.end()


class ScaleKnob(QtWidgets.QWidget):
    """Gros bouton bakélite à jupe, avec échelle 0 à 10 imprimée autour.
    Molette = 0,1 ; Maj + molette = 1 ; glisser haut/bas ; double-clic = 5."""
    valueChanged = QtCore.pyqtSignal(float)

    def __init__(self, value=5.0, size=84):
        super().__init__()
        self.value = value
        self._drag_y = None
        self._drag_value = 0.0
        self._wheel = 0
        self.setFixedSize(size, size)
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def setValue(self, value):
        value = round(max(0.0, min(10.0, value)), 1)
        if value != self.value:
            self.value = value
            self.update()
            self.valueChanged.emit(value)

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            fine = 1.0 if event.modifiers() & QtCore.Qt.ShiftModifier else 0.1
            self.setValue(self.value + steps * fine)
        event.accept()

    def _value_at(self, pos):
        """Valeur montrée par la direction de la souris (index vers la souris)."""
        c = self.rect().center()
        dx, dy = pos.x() - c.x(), c.y() - pos.y()
        if dx * dx + dy * dy < 16:
            return None                     # trop près du centre : direction floue
        deg = math.degrees(math.atan2(dy, dx))          # 0 à droite, sens trigo
        travel = (225 - deg) % 360                      # 0 = repère 0, 270 = 10
        if travel > SWEEP:                              # zone morte en bas
            travel = 0.0 if travel - SWEEP > (360 - SWEEP) / 2 else SWEEP
        return travel / SWEEP * 10

    def mousePressEvent(self, event):
        self._drag_y = event.pos().y()
        self.setCursor(QtCore.Qt.ClosedHandCursor)
        value = self._value_at(event.pos())
        if value is not None:
            self.setValue(value)

    def mouseMoveEvent(self, event):
        if self._drag_y is None:
            return
        value = self._value_at(event.pos())
        if value is None:
            return
        # pas de saut 0 ↔ 10 en passant par la zone morte du bas
        if abs(value - self.value) > 5:
            return
        self.setValue(value)

    def mouseReleaseEvent(self, event):
        self._drag_y = None
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.setValue(5.0)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w = self.width()
        c = QtCore.QPointF(w / 2, w / 2)
        r = w / 2 - 1
        # échelle 0…10 sur 270°
        font = QtGui.QFont("DejaVu Sans", 6, QtGui.QFont.Bold)
        p.setFont(font)
        for k in range(0, 21):
            a = math.radians(225 - SWEEP * k / 20)
            u = QtCore.QPointF(math.cos(a), -math.sin(a))
            big = k % 2 == 0
            p.setPen(QtGui.QPen(QtGui.QColor("#cfd8dc" if big else "#78909c"),
                                1.4 if big else 1))
            p.drawLine(c + u * (r - 11), c + u * (r - (15 if big else 13)))
            if big:
                p.setPen(QtGui.QColor("#ffd54a" if k // 2 >= 8 else "#e0e0e0"))
                pos = c + u * (r - 5)
                p.drawText(QtCore.QRectF(pos.x() - 8, pos.y() - 6, 16, 12),
                           QtCore.Qt.AlignCenter, str(k // 2))
        # jupe métallique
        skirt = r - 17
        g = QtGui.QConicalGradient(c, 120)
        for pos, col in ((0, "#e8e8e8"), (0.25, "#6d6d6d"), (0.5, "#d0d0d0"),
                         (0.75, "#5a5a5a"), (1, "#e8e8e8")):
            g.setColorAt(pos, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1))
        p.setBrush(g)
        p.drawEllipse(c, skirt, skirt)
        # corps bakélite bombé
        body = skirt - 5
        grad = QtGui.QRadialGradient(c - QtCore.QPointF(body / 3, body / 3), body * 1.7)
        grad.setColorAt(0, QtGui.QColor("#6b5a4a"))
        grad.setColorAt(0.45, QtGui.QColor("#2b211a"))
        grad.setColorAt(1, QtGui.QColor("#0d0906"))
        p.setBrush(grad)
        p.drawEllipse(c, body, body)
        # index : trait blanc sur la jupe jusqu'au bord
        frac = self.value / 10
        a = math.radians(225 - SWEEP * frac)
        u = QtCore.QPointF(math.cos(a), -math.sin(a))
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.2, cap=QtCore.Qt.RoundCap))
        p.drawLine(c + u * (body * 0.35), c + u * (skirt + 1))
        p.end()
