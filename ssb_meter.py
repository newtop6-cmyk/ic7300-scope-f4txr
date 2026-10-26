"""Petit vu-mètre « vintage » du calage BLU : l'aiguille balaie pendant la
recherche, montre l'écart estimé, puis se pose sur le 0 central quand c'est calé."""

import math
import time

from PyQt5 import QtCore, QtGui, QtWidgets

import pump_glow

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
            # pas de mesure : aiguille au repos (plus de balayage simulé)
            goal, speed = -SPAN - 8, 0.08
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
        """Éclairage du cadran : toujours allumé ; plus on approche du calage
        exact (écart mesuré), plus il brille ; plein éclat quand c'est calé."""
        if self.state == "locked":
            return 1.0
        if self.state == "measure":
            return 0.45 + 0.5 * (1.0 - min(self.needle_hz(), 60.0) / 60.0)
        return 0.4                              # allumé, sans mesure en cours

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


class SsbMeterSmall(SsbMeter):
    """Même galva de calage, au format des galvas Po W / COMP : petit cadre
    en demi-cercle (dôme en haut, base plate), cadran crème, aiguille rouge."""

    W, H = 116, 80

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.pull_led = "off"           # rattrapage : off, search (flash), locked (fixe)

    def _shape(self, inset):
        w, h = self.width(), self.height()
        r = w / 2 - inset
        cx, cy = w / 2, w / 2
        path = QtGui.QPainterPath()
        path.moveTo(inset, h - inset)
        path.lineTo(inset, cy)
        path.arcTo(QtCore.QRectF(cx - r, cy - r, 2 * r, 2 * r), 180, -180)
        path.lineTo(w - inset, h - inset)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QtCore.Qt.NoPen)
        rim = QtGui.QLinearGradient(0, 0, 0, h)
        rim.setColorAt(0, QtGui.QColor("#8a7058"))
        rim.setColorAt(0.5, QtGui.QColor("#3e3024"))
        rim.setColorAt(1, QtGui.QColor("#120c08"))
        p.setBrush(rim)
        p.drawPath(self._shape(0))
        case = QtGui.QLinearGradient(0, 0, 0, h)
        case.setColorAt(0, QtGui.QColor("#54422f"))
        case.setColorAt(1, QtGui.QColor("#21170f"))
        p.setBrush(case)
        p.drawPath(self._shape(2))
        bezel = QtGui.QLinearGradient(0, 4, 0, h - 4)
        bezel.setColorAt(0, QtGui.QColor("#0a0604"))
        bezel.setColorAt(1, QtGui.QColor("#7a6450"))
        p.setBrush(bezel)
        p.drawPath(self._shape(4))
        # cadran éclairé : plus on approche du 0, plus il s'allume
        face = self._shape(6)
        light = self.light()
        dim = (QtGui.QColor("#cfc4a4"), QtGui.QColor("#b2a585"), QtGui.QColor("#857a62"))
        bright = (QtGui.QColor("#fff8d8"), QtGui.QColor("#ffe08a"), QtGui.QColor("#d9a84c"))

        def mix(a, b, t):
            return QtGui.QColor.fromRgbF(*(a.getRgbF()[i] * (1 - t) + b.getRgbF()[i] * t
                                           for i in range(3)))
        glow = QtGui.QRadialGradient(w / 2, h - 6, w * 0.75)
        for stop, a, b in zip((0, 0.6, 1), dim, bright):
            glow.setColorAt(stop, mix(a, b, light))
        p.setBrush(glow)
        p.drawPath(face)
        pump_glow.paint(p, face, getattr(self, "pump", None))
        shade = QtGui.QLinearGradient(0, 6, 0, 22)
        shade.setColorAt(0, QtGui.QColor(0, 0, 0, 110))
        shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawPath(face)
        p.save()
        p.setClipPath(face)

        cx, cy = w / 2, h - 13
        radius = w * 0.30
        ink = QtGui.QColor("#2b2116")
        locked = self.state == "locked"
        if locked:                          # halo vert autour du 0
            halo = QtGui.QRadialGradient(cx, cy - radius - 6, 18)
            halo.setColorAt(0, QtGui.QColor(120, 255, 120, 150))
            halo.setColorAt(1, QtGui.QColor(120, 255, 120, 0))
            p.setBrush(halo)
            p.drawEllipse(QtCore.QPointF(cx, cy - radius - 6), 18, 18)
        p.setPen(QtGui.QPen(ink, 1.0))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(QtCore.QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius),
                  int((90 - SPAN) * 16), int(2 * SPAN * 16))
        good = angle_of(15)                 # zone « calé » ± 15 Hz
        p.setPen(QtGui.QPen(QtGui.QColor("#2e7d32"), 2.5))
        p.drawArc(QtCore.QRectF(cx - radius + 1.5, cy - radius + 1.5,
                                2 * radius - 3, 2 * radius - 3),
                  int((90 - good) * 16), int(2 * good * 16))
        p.setFont(QtGui.QFont("DejaVu Sans", 5, QtGui.QFont.Bold))
        for hz, label in TICKS:
            for sign in ((1,) if hz == 0 else (-1, 1)):
                a = math.radians(angle_of(sign * hz))
                big = bool(label)
                r1, r2 = radius, radius + (4 if big else 2)
                p.setPen(QtGui.QPen(ink, 1.0 if big else 0.7))
                p.drawLine(QtCore.QPointF(cx + r1 * math.sin(a), cy - r1 * math.cos(a)),
                           QtCore.QPointF(cx + r2 * math.sin(a), cy - r2 * math.cos(a)))
                if big and hz in (100, 200):
                    r3 = radius + 9
                    pt = QtCore.QPointF(cx + r3 * math.sin(a), cy - r3 * math.cos(a))
                    p.drawText(QtCore.QRectF(pt.x() - 10, pt.y() - 5, 20, 10),
                               QtCore.Qt.AlignCenter, label)
        p.setFont(QtGui.QFont("DejaVu Serif", 6, QtGui.QFont.Bold))
        p.setPen(QtGui.QColor("#1b5e20" if locked else ink))
        p.drawText(QtCore.QRectF(cx - 8, cy - radius - 14, 16, 10), QtCore.Qt.AlignCenter, "0")
        text = {"off": "CALE", "search": "rech.",
                "measure": f"{self.target:+.0f} Hz", "locked": "CALÉ"}[self.state]
        p.setFont(QtGui.QFont("DejaVu Serif", 5, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(cx - 20, cy - radius * 0.42 - 5, 40, 10),
                   QtCore.Qt.AlignCenter, text)
        # aiguille rouge depuis l'axe visible
        a = math.radians(self.needle)
        tip = QtCore.QPointF(cx + (radius + 3) * math.sin(a), cy - (radius + 3) * math.cos(a))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1.8))
        p.drawLine(QtCore.QPointF(cx + 1.5, cy + 1.5), tip + QtCore.QPointF(1.5, 1.5))
        p.setPen(QtGui.QPen(QtGui.QColor("#b3261e"), 1.3, cap=QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(cx, cy), tip)
        hub = QtGui.QRadialGradient(cx - 1, cy - 1, 4)
        hub.setColorAt(0, QtGui.QColor("#6a6a6a"))
        hub.setColorAt(1, QtGui.QColor("#0a0a0a"))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(hub)
        p.drawEllipse(QtCore.QPointF(cx, cy), 3.5, 3.5)
        shine = QtGui.QLinearGradient(0, 6, 0, h * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 60))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawPath(face)
        if self.state == "off":             # voile quand le calage est arrêté
            p.setBrush(QtGui.QColor(0, 0, 0, 60))
            p.drawPath(face)
        p.restore()
        # petite LED bleue dans l'angle : flash pendant le rattrapage, fixe si calé
        # voyant bleu : fixe si calé, flash si un écart est mesuré (ou rattrapage)
        flash = int(time.monotonic() / 0.12) % 2 == 0
        lit = self.state == "locked" or (
            (self.state == "measure" or self.pull_led == "search") and flash)
        led = QtCore.QPointF(w - 9, h - 9)
        if lit:
            halo = QtGui.QRadialGradient(led, 9)
            halo.setColorAt(0, QtGui.QColor(160, 210, 255, 255))
            halo.setColorAt(0.5, QtGui.QColor(40, 130, 255, 200))
            halo.setColorAt(1, QtGui.QColor(30, 100, 255, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(led, 9, 9)
        g = QtGui.QRadialGradient(led - QtCore.QPointF(1, 1), 4)
        g.setColorAt(0, QtGui.QColor("#ffffff" if lit else "#1c2638"))
        g.setColorAt(0.5, QtGui.QColor("#4aa0ff" if lit else "#0e1626"))
        g.setColorAt(1, QtGui.QColor("#0a3a9a" if lit else "#05080f"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 0.8))
        p.setBrush(g)
        p.drawEllipse(led, 3.5, 3.5)
        p.end()
