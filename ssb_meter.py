"""Petit vu-mètre « vintage » du calage BLU : l'aiguille balaie pendant la
recherche, montre l'écart estimé, puis se pose sur le 0 central quand c'est calé."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets

FULL = 200.0                    # Hz au bout de l'échelle
SPAN = 55.0                     # degrés de part et d'autre du 0
TICKS = [(0, "0"), (25, ""), (50, "50"), (100, "100"), (200, "200")]


def angle_of(hz):
    """Échelle dilatée près du 0 : on voit bien les petits écarts."""
    x = max(-1.0, min(1.0, hz / FULL))
    return math.copysign(math.sqrt(abs(x)), x) * SPAN


class SsbMeter(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(176, 110)
        self.setToolTip("Calage automatique BLU : écart entre la radio et la voix "
                        "du correspondant")
        self.state = "off"              # off, search, measure, locked
        self.target = 0.0               # Hz visés par l'aiguille
        self.needle = -SPAN             # angle affiché (degrés)
        self.phase = 0.0
        self.status = ""
        self.followers = []             # voyants qui suivent l'aiguille
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def set_state(self, state, hz=None, status=""):
        self.state = state
        if hz is not None:
            self.target = hz
        self.status = status
        self.setToolTip(f"Calage automatique BLU : {status}" if status else
                        "Calage automatique BLU")

    def _tick(self):
        if not self.isVisible():
            return
        if self.state == "search":
            # balayage lent, comme une recherche
            self.phase += 0.033 * 2 * math.pi / 3.0
            goal = SPAN * 0.85 * math.sin(self.phase)
            speed = 0.15
        elif self.state == "off":
            goal, speed = -SPAN - 8, 0.08            # au repos, à gauche
        else:
            goal = angle_of(0 if self.state == "locked" else self.target)
            speed = 0.12
        self.needle += (goal - self.needle) * speed
        self.update()
        for widget in self.followers:
            widget.update()

    def light(self):
        """Éclairage du cadran, 0 (éteint) à 1 (calé) : suit l'aiguille."""
        if self.state == "off":
            return 0.0
        if self.state == "locked":
            return 1.0
        return 0.25 + 0.6 * (1.0 - min(self.needle_hz(), 60.0) / 60.0)

    def needle_hz(self):
        """Écart (Hz) que montre l'aiguille en ce moment."""
        x = max(-1.0, min(1.0, self.needle / SPAN))
        return x * x * FULL

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # boîtier bakélite en relief : arête claire en haut, sombre en bas
        p.setPen(QtCore.Qt.NoPen)
        rim = QtGui.QLinearGradient(0, 0, 0, h)
        rim.setColorAt(0, QtGui.QColor("#8a7058"))
        rim.setColorAt(0.5, QtGui.QColor("#3e3024"))
        rim.setColorAt(1, QtGui.QColor("#120c08"))
        p.setBrush(rim)
        p.drawRoundedRect(QtCore.QRectF(0, 0, w, h), 10, 10)
        case = QtGui.QLinearGradient(0, 0, 0, h)
        case.setColorAt(0, QtGui.QColor("#54422f"))
        case.setColorAt(1, QtGui.QColor("#21170f"))
        p.setBrush(case)
        p.drawRoundedRect(QtCore.QRectF(3, 3, w - 6, h - 6), 8, 8)
        # lunette creusée : sombre en haut, claire en bas (le cadran est en retrait)
        bezel = QtGui.QLinearGradient(0, 6, 0, h - 6)
        bezel.setColorAt(0, QtGui.QColor("#0a0604"))
        bezel.setColorAt(1, QtGui.QColor("#7a6450"))
        p.setBrush(bezel)
        p.drawRoundedRect(QtCore.QRectF(6, 6, w - 12, h - 12), 7, 7)
        # cadran crème éclairé par l'ampoule : plus on approche du 0, plus il
        # s'allume ; calé = pleine lumière, fixe
        face = QtCore.QRectF(8, 8, w - 16, h - 16)
        lit = self.state != "off"
        light = self.light()
        dim = (QtGui.QColor("#cfc4a4"), QtGui.QColor("#b2a585"), QtGui.QColor("#857a62"))
        bright = (QtGui.QColor("#fff8d8"), QtGui.QColor("#ffe08a"), QtGui.QColor("#d9a84c"))

        def mix(a, b, t):
            return QtGui.QColor.fromRgbF(*(a.getRgbF()[i] * (1 - t) + b.getRgbF()[i] * t
                                           for i in range(3)))
        glow = QtGui.QRadialGradient(w / 2, h - 10, w * 0.75)
        for stop, a, b in zip((0, 0.6, 1), dim, bright):
            glow.setColorAt(stop, mix(a, b, light))
        p.setBrush(glow)
        p.drawRoundedRect(face, 6, 6)
        # ombre intérieure en haut et sur les côtés : profondeur
        shade = QtGui.QLinearGradient(0, 8, 0, 30)
        shade.setColorAt(0, QtGui.QColor(0, 0, 0, 120))
        shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawRoundedRect(face, 6, 6)
        for x0, x1 in ((8, 20), (w - 8, w - 20)):
            side = QtGui.QLinearGradient(x0, 0, x1, 0)
            side.setColorAt(0, QtGui.QColor(0, 0, 0, 70))
            side.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setBrush(side)
            p.drawRoundedRect(face, 6, 6)

        cx, cy = w / 2, h - 14                       # axe de l'aiguille
        if self.state == "locked":
            # halo vert fixe autour du 0 : fréquence parfaitement calée
            halo = QtGui.QRadialGradient(cx, cy - (h - 50) - 6, 34)
            halo.setColorAt(0, QtGui.QColor(120, 255, 120, 150))
            halo.setColorAt(1, QtGui.QColor(120, 255, 120, 0))
            p.setBrush(halo)
            p.drawEllipse(QtCore.QPointF(cx, cy - (h - 50) - 6), 34, 34)
        radius = h - 50
        # arc de l'échelle
        p.setPen(QtGui.QPen(QtGui.QColor("#2b2116"), 1.4))
        arc = QtCore.QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
        p.drawArc(arc, int((90 - SPAN) * 16), int(2 * SPAN * 16))
        # zone « calé » (± 15 Hz) en vert
        good = angle_of(15)
        p.setPen(QtGui.QPen(QtGui.QColor("#2e7d32"), 4))
        inner = QtCore.QRectF(cx - radius + 3, cy - radius + 3,
                              2 * radius - 6, 2 * radius - 6)
        p.drawArc(inner, int((90 - good) * 16), int(2 * good * 16))
        # graduations
        font = QtGui.QFont("DejaVu Serif", 6)
        p.setFont(font)
        for hz, label in TICKS:
            for sign in ((1,) if hz == 0 else (-1, 1)):
                a = math.radians(angle_of(sign * hz))
                big = bool(label)
                r1, r2 = radius, radius + (7 if big else 4)
                p.setPen(QtGui.QPen(QtGui.QColor("#2b2116"), 1.3 if big else 1))
                p.drawLine(QtCore.QPointF(cx + r1 * math.sin(a), cy - r1 * math.cos(a)),
                           QtCore.QPointF(cx + r2 * math.sin(a), cy - r2 * math.cos(a)))
                if big and hz:
                    r3 = radius + 13
                    pt = QtCore.QPointF(cx + r3 * math.sin(a), cy - r3 * math.cos(a))
                    p.drawText(QtCore.QRectF(pt.x() - 12, pt.y() - 6, 24, 12),
                               QtCore.Qt.AlignCenter, label)
        # le 0 central, vert et lumineux quand c'est calé
        locked = self.state == "locked"
        zero = QtGui.QFont("DejaVu Serif", 10 if locked else 8, QtGui.QFont.Bold)
        p.setFont(zero)
        p.setPen(QtGui.QColor("#1b5e20" if locked else "#2b2116"))
        p.drawText(QtCore.QRectF(cx - 15, cy - radius - 24, 30, 14),
                   QtCore.Qt.AlignCenter, "0")
        p.setFont(QtGui.QFont("DejaVu Serif", 6))
        p.setPen(QtGui.QColor("#5a4630"))
        p.drawText(QtCore.QRectF(12, cy - 20, 30, 12), QtCore.Qt.AlignLeft, "−")
        p.drawText(QtCore.QRectF(w - 42, cy - 20, 30, 12), QtCore.Qt.AlignRight, "+")
        text = {"off": "BLU", "search": "recherche…",
                "measure": f"{self.target:+.0f} Hz", "locked": "CALÉ"}[self.state]
        p.setPen(QtGui.QColor("#1b5e20" if locked else "#5a4630"))
        p.setFont(QtGui.QFont("DejaVu Serif", 7, QtGui.QFont.Bold if locked else -1))
        p.drawText(QtCore.QRectF(cx - 40, cy - 26, 80, 12), QtCore.Qt.AlignCenter, text)
        # aiguille avec une ombre légère
        a = math.radians(self.needle)
        tip = QtCore.QPointF(cx + (radius + 4) * math.sin(a), cy - (radius + 4) * math.cos(a))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 2.2))
        p.drawLine(QtCore.QPointF(cx + 2, cy + 1), tip + QtCore.QPointF(2, 1))
        p.setPen(QtGui.QPen(QtGui.QColor("#b71c1c"), 1.6))
        p.drawLine(QtCore.QPointF(cx, cy), tip)
        # axe
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#1a1410"))
        p.drawEllipse(QtCore.QPointF(cx, cy), 5, 5)
        # reflet du verre
        shine = QtGui.QLinearGradient(0, 8, 0, h * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 70))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawRoundedRect(QtCore.QRectF(10, 10, w - 20, h * 0.35), 5, 5)
        # voile quand le calage est arrêté
        if not lit:
            p.setBrush(QtGui.QColor(0, 0, 0, 70))
            p.drawRoundedRect(face, 6, 6)
        p.end()


class SsbLed(QtWidgets.QWidget):
    """Voyant du calage BLU, en phase avec l'aiguille du cadran : rouge loin
    du 0, orange, jaune, puis vert ; vert fixe et brillant quand c'est calé."""

    def __init__(self, meter):
        super().__init__()
        self.meter = meter
        meter.followers.append(self)
        self.setFixedSize(22, 22)
        self.setToolTip("Rouge : loin du calage · vert fixe : calage parfait")

    def color(self):
        state = self.meter.state
        if state == "off":
            return QtGui.QColor("#3a3a3a"), 0.0
        if state == "locked":
            return QtGui.QColor.fromHsvF(1 / 3, 0.9, 1.0), 1.0
        # très sensible : rouge dès 60 Hz, jaune vers 30 Hz, vert près du 0
        hz = self.meter.needle_hz()
        closeness = 1.0 - min(hz, 60.0) / 60.0
        hue = closeness / 3                             # 0 rouge → 1/3 vert
        return QtGui.QColor.fromHsvF(hue, 0.95, 0.95), 0.6

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        color, glow = self.color()
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        if glow:                                        # halo lumineux
            halo = QtGui.QRadialGradient(c, 11)
            edge = QtGui.QColor(color)
            edge.setAlpha(0)
            inner = QtGui.QColor(color)
            inner.setAlpha(int(140 * glow))
            halo.setColorAt(0, inner)
            halo.setColorAt(1, edge)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, 11, 11)
        bulb = QtGui.QRadialGradient(c - QtCore.QPointF(2, 2), 8)
        bulb.setColorAt(0, color.lighter(170))
        bulb.setColorAt(0.5, color)
        bulb.setColorAt(1, color.darker(200))
        p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1))
        p.setBrush(bulb)
        p.drawEllipse(c, 6.5, 6.5)
        p.end()


class PlainLed(QtWidgets.QWidget):
    """Voyant simple d'une couleur donnée (vert / rouge)."""

    def __init__(self, color="#c62828"):
        super().__init__()
        self.setFixedSize(20, 20)
        self.color = QtGui.QColor(color)

    def set_color(self, color):
        self.color = QtGui.QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        halo = QtGui.QRadialGradient(c, 10)
        inner = QtGui.QColor(self.color)
        inner.setAlpha(110)
        edge = QtGui.QColor(self.color)
        edge.setAlpha(0)
        halo.setColorAt(0, inner)
        halo.setColorAt(1, edge)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, 10, 10)
        bulb = QtGui.QRadialGradient(c - QtCore.QPointF(2, 2), 7)
        bulb.setColorAt(0, self.color.lighter(170))
        bulb.setColorAt(0.5, self.color)
        bulb.setColorAt(1, self.color.darker(200))
        p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1))
        p.setBrush(bulb)
        p.drawEllipse(c, 6, 6)
        p.end()
