"""S-mètre à aiguille « vintage » : cadran crème légèrement éclairé, échelle
S1…S9 puis +20/+40/+60 dB en rouge, échelle en dB dessous (0 dB = S9),
boîtier bakélite aux bords arrondis avec effet de profondeur."""

import math
import time

from PyQt5 import QtCore, QtGui, QtWidgets

import pump_glow

S9 = 120                        # valeurs brutes Icom : 0 = S0, 120 = S9
S9_PLUS_60 = 241                # 241 = S9 + 60 dB
SPAN = 48.0                     # degrés de part et d'autre du centre


def raw_of_db(db):
    """dB par rapport à S9 (6 dB par point S en dessous) → valeur brute."""
    if db <= 0:
        return S9 + db * S9 / 54
    return S9 + db * (S9_PLUS_60 - S9) / 60


def s_text(raw):
    if raw <= S9:
        return f"S{round(raw * 9 / S9)}"
    return f"S9+{round((raw - S9) * 60 / (S9_PLUS_60 - S9))}"


class VintageSMeter(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(300, 150)
        self.setToolTip("S-mètre de la radio")
        self.target = 0.0               # valeur brute reçue
        self.value = 0.0                # valeur affichée (inertie de l'aiguille)
        self.peak = 0.0
        self.peak_time = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def setValue(self, raw):
        self.target = max(0.0, min(float(S9_PLUS_60), float(raw)))

    def _tick(self):
        # galvanomètre : monte vite, redescend doucement
        speed = 0.45 if self.target > self.value else 0.08
        self.value += (self.target - self.value) * speed
        now = time.monotonic()
        if self.target >= self.peak:
            self.peak, self.peak_time = self.target, now
        elif now - self.peak_time > 1.5:
            self.peak = max(self.target, self.peak - 3)
        self.update()

    def _angle(self, raw):
        return math.radians(-SPAN + 2 * SPAN * raw / S9_PLUS_60)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QtCore.Qt.NoPen)
        # boîtier : arête claire en haut, sombre en bas
        rim = QtGui.QLinearGradient(0, 0, 0, h)
        rim.setColorAt(0, QtGui.QColor("#8a7058"))
        rim.setColorAt(0.5, QtGui.QColor("#3e3024"))
        rim.setColorAt(1, QtGui.QColor("#120c08"))
        p.setBrush(rim)
        p.drawRoundedRect(QtCore.QRectF(0, 0, w, h), 14, 14)
        case = QtGui.QLinearGradient(0, 0, 0, h)
        case.setColorAt(0, QtGui.QColor("#54422f"))
        case.setColorAt(1, QtGui.QColor("#21170f"))
        p.setBrush(case)
        p.drawRoundedRect(QtCore.QRectF(3, 3, w - 6, h - 6), 12, 12)
        # lunette creusée
        bezel = QtGui.QLinearGradient(0, 8, 0, h - 8)
        bezel.setColorAt(0, QtGui.QColor("#0a0604"))
        bezel.setColorAt(1, QtGui.QColor("#7a6450"))
        p.setBrush(bezel)
        p.drawRoundedRect(QtCore.QRectF(8, 8, w - 16, h - 16), 10, 10)
        # cadran crème, légèrement éclairé par en dessous
        face = QtCore.QRectF(11, 11, w - 22, h - 22)
        glow = QtGui.QRadialGradient(w / 2, h - 12, w * 0.7)
        glow.setColorAt(0, QtGui.QColor("#fff3cf"))
        glow.setColorAt(0.55, QtGui.QColor("#f1d999"))
        glow.setColorAt(1, QtGui.QColor("#c49c55"))
        p.setBrush(glow)
        p.drawRoundedRect(face, 8, 8)
        pump_glow.paint(p, face, getattr(self, "pump", None))
        # ombres intérieures : le cadran est en retrait
        shade = QtGui.QLinearGradient(0, 11, 0, 40)
        shade.setColorAt(0, QtGui.QColor(0, 0, 0, 130))
        shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawRoundedRect(face, 8, 8)
        for x0, x1 in ((11, 28), (w - 11, w - 28)):
            side = QtGui.QLinearGradient(x0, 0, x1, 0)
            side.setColorAt(0, QtGui.QColor(0, 0, 0, 80))
            side.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setBrush(side)
            p.drawRoundedRect(face, 8, 8)

        cx, cy = w / 2, h + 50                       # axe sous le cadran
        r_out = 150                                  # échelle S
        r_db = 128                                   # échelle dB
        ink = QtGui.QColor("#2b2116")
        red = QtGui.QColor("#b3261e")

        def arc(radius, raw0, raw1, color, width):
            a0 = 90 - math.degrees(self._angle(raw0))
            a1 = 90 - math.degrees(self._angle(raw1))
            p.setPen(QtGui.QPen(color, width, cap=QtCore.Qt.FlatCap))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawArc(QtCore.QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius),
                      int(a1 * 16), int((a0 - a1) * 16))

        def point(raw, radius):
            a = self._angle(raw)
            return QtCore.QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a))

        def label(raw, radius, text, color, size, bold=False):
            p.setPen(color)
            p.setFont(QtGui.QFont("DejaVu Serif", size, QtGui.QFont.Bold if bold else -1))
            pt = point(raw, radius)
            p.drawText(QtCore.QRectF(pt.x() - 16, pt.y() - 8, 32, 16),
                       QtCore.Qt.AlignCenter, text)

        # arcs : noir jusqu'à S9, bande rouge au-delà
        arc(r_out, 0, S9, ink, 1.4)
        arc(r_out, S9, S9_PLUS_60, red, 1.4)
        arc(r_out - 3, S9, S9_PLUS_60, red, 5)
        arc(r_db, 0, S9_PLUS_60, ink, 1)
        # graduations S
        for s in range(0, 10):
            raw = s * S9 / 9
            big = s % 2 == 1 or s == 9
            p.setPen(QtGui.QPen(ink, 1.4 if big else 1))
            p.drawLine(point(raw, r_out), point(raw, r_out + (9 if big else 5)))
            if big:
                label(raw, r_out + 18, str(s), ink, 9, bold=True)
        for db in (10, 20, 30, 40, 50, 60):
            raw = raw_of_db(db)
            big = db % 20 == 0
            p.setPen(QtGui.QPen(red, 1.4 if big else 1))
            p.drawLine(point(raw, r_out), point(raw, r_out + (9 if big else 5)))
            if big:
                label(raw, r_out + 18, f"+{db}", red, 8, bold=True)
        # échelle dB (0 dB = S9)
        for db in (-48, -36, -24, -12, 0, 20, 40, 60):
            raw = raw_of_db(db)
            p.setPen(QtGui.QPen(red if db > 0 else ink, 1))
            p.drawLine(point(raw, r_db), point(raw, r_db - 5))
            label(raw, r_db - 13, f"{db:+d}" if db else "0", red if db > 0 else ink, 6)
        # inscriptions
        p.setPen(ink)
        p.setFont(QtGui.QFont("DejaVu Serif", 10, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(18, h - 46, 40, 16), QtCore.Qt.AlignLeft, "S")
        p.setFont(QtGui.QFont("DejaVu Serif", 6))
        p.drawText(QtCore.QRectF(w - 58, h - 44, 40, 14), QtCore.Qt.AlignRight, "dB")
        p.setFont(QtGui.QFont("DejaVu Serif", 9, QtGui.QFont.Bold))
        p.setPen(red if self.peak > S9 else ink)
        p.drawText(QtCore.QRectF(cx - 50, h - 47, 100, 16), QtCore.Qt.AlignCenter,
                   s_text(self.peak))
        # aiguille avec son ombre portée sur le cadran
        tip = point(self.value, r_out + 4)
        base = point(self.value, 52)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 55), 2.4))
        p.drawLine(base + QtCore.QPointF(3, 2), tip + QtCore.QPointF(3, 2))
        p.setPen(QtGui.QPen(QtGui.QColor("#141414"), 1.7))
        p.drawLine(base, tip)
        # cache de l'axe (le pivot est sous le cadran)
        p.setPen(QtCore.Qt.NoPen)
        hub = QtGui.QLinearGradient(0, h - 26, 0, h - 11)
        hub.setColorAt(0, QtGui.QColor("#3a2e22"))
        hub.setColorAt(1, QtGui.QColor("#120c08"))
        p.setBrush(hub)
        p.drawRoundedRect(QtCore.QRectF(cx - 46, h - 26, 92, 15), 6, 6)
        # reflet du verre
        shine = QtGui.QLinearGradient(0, 11, 0, h * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 75))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawRoundedRect(QtCore.QRectF(13, 13, w - 26, h * 0.32), 7, 7)
        p.end()


class VintagePowerMeter(VintageSMeter):
    """Même galva que le S-mètre (boîtier, cadran, aiguille, taille), gradué
    en watts (0 à 100 W, échelle dilatée pour la voix), POWER au centre."""

    PO_MAX = 100.0

    def __init__(self):
        super().__init__()
        self.setToolTip("Puissance émise (Po) en watts")
        self.watts_peak = 0.0

    def frac(self, watts):
        # échelle très dilatée en bas : la moindre puissance réelle fait bouger l'aiguille
        return (max(0.0, min(self.PO_MAX, watts)) / self.PO_MAX) ** 0.4

    def _tick(self):
        # galva de puissance très vif : monte presque d'un coup, retombe vite
        speed = 0.8 if self.target > self.value else 0.3
        self.value += (self.target - self.value) * speed
        self.update()

    def setValue(self, watts):
        """Reçoit des watts ; l'aiguille travaille en « brut » 0–241 comme le S-mètre."""
        self.watts_peak = max(self.watts_peak * 0.98, watts)
        self.target = self.frac(watts) * S9_PLUS_60

    def reset(self):
        self.target = 0.0
        self.watts_peak = 0.0

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
        p.drawRoundedRect(QtCore.QRectF(0, 0, w, h), 14, 14)
        case = QtGui.QLinearGradient(0, 0, 0, h)
        case.setColorAt(0, QtGui.QColor("#54422f"))
        case.setColorAt(1, QtGui.QColor("#21170f"))
        p.setBrush(case)
        p.drawRoundedRect(QtCore.QRectF(3, 3, w - 6, h - 6), 12, 12)
        bezel = QtGui.QLinearGradient(0, 8, 0, h - 8)
        bezel.setColorAt(0, QtGui.QColor("#0a0604"))
        bezel.setColorAt(1, QtGui.QColor("#7a6450"))
        p.setBrush(bezel)
        p.drawRoundedRect(QtCore.QRectF(8, 8, w - 16, h - 16), 10, 10)
        face = QtCore.QRectF(11, 11, w - 22, h - 22)
        glow = QtGui.QRadialGradient(w / 2, h - 12, w * 0.7)
        glow.setColorAt(0, QtGui.QColor("#fff3cf"))
        glow.setColorAt(0.55, QtGui.QColor("#f1d999"))
        glow.setColorAt(1, QtGui.QColor("#c49c55"))
        p.setBrush(glow)
        p.drawRoundedRect(face, 8, 8)
        shade = QtGui.QLinearGradient(0, 11, 0, 40)
        shade.setColorAt(0, QtGui.QColor(0, 0, 0, 130))
        shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawRoundedRect(face, 8, 8)
        for x0, x1 in ((11, 28), (w - 11, w - 28)):
            side = QtGui.QLinearGradient(x0, 0, x1, 0)
            side.setColorAt(0, QtGui.QColor(0, 0, 0, 80))
            side.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setBrush(side)
            p.drawRoundedRect(face, 8, 8)

        cx, cy = w / 2, h + 50
        r_out, r_in = 150, 128
        ink = QtGui.QColor("#2b2116")
        red = QtGui.QColor("#b3261e")

        def ang(f):
            return math.radians(-SPAN + 2 * SPAN * f)

        def arc(radius, f0, f1, color, width):
            a0 = 90 - math.degrees(ang(f0))
            a1 = 90 - math.degrees(ang(f1))
            p.setPen(QtGui.QPen(color, width, cap=QtCore.Qt.FlatCap))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawArc(QtCore.QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius),
                      int(a1 * 16), int((a0 - a1) * 16))

        def point(f, radius):
            a = ang(f)
            return QtCore.QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a))

        def label(f, radius, text, color, size, bold=False):
            p.setPen(color)
            p.setFont(QtGui.QFont("DejaVu Serif", size, QtGui.QFont.Bold if bold else -1))
            pt = point(f, radius)
            p.drawText(QtCore.QRectF(pt.x() - 16, pt.y() - 8, 32, 16),
                       QtCore.Qt.AlignCenter, text)

        red_f = self.frac(80)
        arc(r_out, 0, red_f, ink, 1.4)
        arc(r_out, red_f, 1, red, 1.4)
        arc(r_out - 3, red_f, 1, red, 5)
        arc(r_in, 0, 1, ink, 1)
        for watts in (0, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100):
            f = self.frac(watts)
            big = watts in (0, 2, 5, 10, 20, 30, 50, 70, 100)
            color = red if watts >= 80 else ink
            p.setPen(QtGui.QPen(color, 1.4 if big else 1))
            p.drawLine(point(f, r_out), point(f, r_out + (9 if big else 5)))
            if big:
                label(f, r_out + 18, str(watts), color, 9, bold=True)
        for pct in (0, 25, 50, 75, 100):                 # échelle intérieure en %
            f = self.frac(pct)
            p.setPen(QtGui.QPen(ink, 1))
            p.drawLine(point(f, r_in), point(f, r_in - 5))
            label(f, r_in - 13, f"{pct}%" if pct in (0, 100) else str(pct), ink, 6)
        p.setPen(ink)
        p.setFont(QtGui.QFont("DejaVu Serif", 10, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(18, h - 46, 40, 16), QtCore.Qt.AlignLeft, "W")
        p.setFont(QtGui.QFont("DejaVu Serif", 6))
        p.drawText(QtCore.QRectF(w - 58, h - 44, 40, 14), QtCore.Qt.AlignRight, "Po")
        # POWER au centre, et la crête dessous
        p.setFont(QtGui.QFont("DejaVu Serif", 11, QtGui.QFont.Bold))
        p.setPen(red if self.watts_peak >= 80 else ink)
        p.drawText(QtCore.QRectF(cx - 60, h - 62, 120, 18), QtCore.Qt.AlignCenter, "POWER")
        p.setFont(QtGui.QFont("DejaVu Serif", 8))
        p.setPen(ink)
        p.drawText(QtCore.QRectF(cx - 60, h - 46, 120, 14), QtCore.Qt.AlignCenter,
                   f"{self.watts_peak:.0f} W" if self.watts_peak >= 1 else "")
        tip = point(self.value / S9_PLUS_60, r_out + 4)
        base = point(self.value / S9_PLUS_60, 52)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 55), 2.4))
        p.drawLine(base + QtCore.QPointF(3, 2), tip + QtCore.QPointF(3, 2))
        p.setPen(QtGui.QPen(QtGui.QColor("#141414"), 1.7))
        p.drawLine(base, tip)
        p.setPen(QtCore.Qt.NoPen)
        hub = QtGui.QLinearGradient(0, h - 26, 0, h - 11)
        hub.setColorAt(0, QtGui.QColor("#3a2e22"))
        hub.setColorAt(1, QtGui.QColor("#120c08"))
        p.setBrush(hub)
        p.drawRoundedRect(QtCore.QRectF(cx - 46, h - 26, 92, 15), 6, 6)
        shine = QtGui.QLinearGradient(0, 11, 0, h * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 75))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawRoundedRect(QtCore.QRectF(13, 13, w - 26, h * 0.32), 7, 7)
        p.end()
