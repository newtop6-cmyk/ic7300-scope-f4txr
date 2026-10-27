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
        # échelle linéaire, comme la barre Po de l'IC-7300 : même lecture que la radio
        return max(0.0, min(self.PO_MAX, watts)) / self.PO_MAX

    def _tick(self):
        # comme la barre Po de la radio : monte vite, redescend un peu moins vite
        speed = 0.6 if self.target > self.value else 0.25
        self.value += (self.target - self.value) * speed
        self.update()

    def setValue(self, watts):
        """Reçoit des watts ; l'aiguille travaille en « brut » 0–241 comme le S-mètre."""
        # valeur du moment (pas de maintien de la pointe) : retombe de moitié en ~0,2 s
        self.watts_peak = max(self.watts_peak * 0.85, watts)
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
            big = watts in (0, 10, 20, 30, 50, 70, 100)
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


class SwrMicroGalva(QtWidgets.QWidget):
    """Micro-galva ROS : même boîtier et même largeur que le galva POWER, cadran
    bas en arc avec zones de couleur (vert ≤ 1,5, jaune ≤ 2, rouge au-delà),
    aiguille amortie, et petite LED rouge qui clignote si le ROS dépasse 2."""

    # (valeur brute de la radio, ROS) — même graduation que la barre de l'IC-7300
    POINTS = [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (255, 6.0)]
    SPAN_DEG = 12                   # demi-ouverture de l'arc (plat : tient dans 46 px)

    def __init__(self, width=300, height=62):
        super().__init__()
        self.setFixedSize(width, height)
        self.value = self.target = 0.0
        self.led_on = False
        self.ratio = None               # ROS mesuré, affiché « 1:x » dans la loupe
        self.setToolTip("ROS (rapport d'ondes stationnaires) en émission ; la loupe "
                        "donne la valeur mesurée (1:x), la LED rouge clignote si le "
                        "ROS dépasse 2")
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)

    def setValue(self, raw):
        self.target = max(0.0, min(255.0, float(raw)))

    def reset(self):
        self.target = 0.0
        self.set_ratio(None)

    def set_ratio(self, swr):
        """Valeur réelle mesurée (None = pas d'émission)."""
        if swr is not None:
            swr = round(swr, 1)
        if swr != self.ratio:
            self.ratio = swr
            self.update()

    def set_led(self, on):
        if on != self.led_on:
            self.led_on = on
            self.update()

    def _tick(self):
        speed = 0.5 if self.target > self.value else 0.2
        new = self.value + (self.target - self.value) * speed
        if abs(new - self.value) > 0.05 or (new != self.target and abs(new - self.target) < 0.05):
            self.value = new if abs(new - self.target) >= 0.05 else self.target
            self.update()

    def _geom(self):
        w = self.width()
        r = (w - 116) / 2 / math.sin(math.radians(self.SPAN_DEG))   # place : loupe | LED
        cx, cy = w / 2, 22 + r                  # pivot sous le cadran : arc très plat
        return cx, cy, r

    def _pt(self, raw, radius):
        cx, cy, _ = self._geom()
        a = math.radians(-self.SPAN_DEG + 2 * self.SPAN_DEG * raw / 255)
        return QtCore.QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # boîtier : même bois sombre que le galva POWER, bombé vers soi
        p.setPen(QtCore.Qt.NoPen)
        rim = QtGui.QLinearGradient(0, 0, 0, h)
        rim.setColorAt(0, QtGui.QColor("#c4a888"))         # arête haute éclairée
        rim.setColorAt(0.18, QtGui.QColor("#8a7058"))
        rim.setColorAt(0.55, QtGui.QColor("#3e3024"))
        rim.setColorAt(1, QtGui.QColor("#0a0604"))         # dessous dans l'ombre
        p.setBrush(rim)
        p.drawRoundedRect(QtCore.QRectF(0, 0, w, h), 10, 10)
        side = QtGui.QLinearGradient(0, 0, w, 0)            # côtés qui fuient
        side.setColorAt(0, QtGui.QColor(0, 0, 0, 110))
        side.setColorAt(0.08, QtGui.QColor(0, 0, 0, 0))
        side.setColorAt(0.92, QtGui.QColor(0, 0, 0, 0))
        side.setColorAt(1, QtGui.QColor(0, 0, 0, 110))
        p.setBrush(side)
        p.drawRoundedRect(QtCore.QRectF(0, 0, w, h), 10, 10)
        case = QtGui.QLinearGradient(0, 0, 0, h)
        case.setColorAt(0, QtGui.QColor("#54422f"))
        case.setColorAt(1, QtGui.QColor("#21170f"))
        p.setBrush(case)
        p.drawRoundedRect(QtCore.QRectF(3, 3, w - 6, h - 6), 8, 8)
        face = QtCore.QRectF(7, 7, w - 14, h - 14)
        glow = QtGui.QRadialGradient(w / 2, h, w * 0.7)
        glow.setColorAt(0, QtGui.QColor("#fff3cf"))
        glow.setColorAt(0.55, QtGui.QColor("#f1d999"))
        glow.setColorAt(1, QtGui.QColor("#c49c55"))
        p.setBrush(glow)
        p.drawRoundedRect(face, 6, 6)
        p.save()
        p.setClipRect(face)
        cx, cy, r = self._geom()
        # zones de couleur sur l'arc
        for lo, hi, col in ((0, 48, "#2e8b3a"), (48, 80, "#d8a300"), (80, 255, "#c62828")):
            path = QtGui.QPainterPath()
            n = 24
            outer = [self._pt(lo + (hi - lo) * i / n, r) for i in range(n + 1)]
            inner = [self._pt(hi - (hi - lo) * i / n, r - 6) for i in range(n + 1)]
            path.moveTo(outer[0])
            for q in outer[1:] + inner:
                path.lineTo(q)
            path.closeSubpath()
            p.fillPath(path, QtGui.QColor(col))
        # graduations et chiffres
        f = QtGui.QFont("DejaVu Sans Condensed", 7, QtGui.QFont.Bold)
        p.setFont(f)
        for raw, label in ((0, "1"), (48, "1.5"), (80, "2"), (120, "3"), (255, "∞")):
            p.setPen(QtGui.QPen(QtGui.QColor("#1a1208"), 1.4))
            p.drawLine(self._pt(raw, r + 1), self._pt(raw, r - 9))
            t = self._pt(raw, r + 8)
            p.drawText(QtCore.QRectF(t.x() - 14, t.y() - 6, 28, 11), QtCore.Qt.AlignCenter, label)
        for raw in (24, 64, 100, 180):
            p.setPen(QtGui.QPen(QtGui.QColor("#3a2c18"), 0.9))
            p.drawLine(self._pt(raw, r), self._pt(raw, r - 5))
        # (nom « R . O . S » au-dessus du galva : SwrTitle)
        # aiguille
        tip, base = self._pt(self.value, r + 4), self._pt(self.value, r - 40)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 2.4))
        p.drawLine(base + QtCore.QPointF(1.5, 1.5), tip + QtCore.QPointF(1.5, 1.5))
        p.setPen(QtGui.QPen(QtGui.QColor("#b01010"), 1.6))
        p.drawLine(base, tip)
        # surface bombée : haut éclairé, bas et bords dans l'ombre
        cyl = QtGui.QLinearGradient(0, face.top(), 0, face.bottom())
        cyl.setColorAt(0, QtGui.QColor(255, 255, 255, 60))
        cyl.setColorAt(0.3, QtGui.QColor(255, 255, 255, 0))
        cyl.setColorAt(0.55, QtGui.QColor(0, 0, 0, 0))
        cyl.setColorAt(1, QtGui.QColor(0, 0, 0, 150))
        p.fillRect(face, cyl)
        vig = QtGui.QRadialGradient(w / 2, face.top() + face.height() * 0.3, w * 0.55)
        vig.setColorAt(0, QtGui.QColor(0, 0, 0, 0))
        vig.setColorAt(0.62, QtGui.QColor(0, 0, 0, 0))
        vig.setColorAt(1, QtGui.QColor(0, 0, 0, 140))
        p.fillRect(face, vig)
        p.restore()
        # loupe ronde dans un anneau métallique, à gauche : ROS mesuré « 1:x »
        lc, lr = QtCore.QPointF(29, h / 2), 15.5
        g = QtGui.QConicalGradient(lc, 135)             # anneau chromé
        for stop, col in ((0, "#ffffff"), (0.2, "#8a8f95"), (0.45, "#e8eaec"),
                          (0.7, "#5c6167"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#1a1c1e"), 0.8))
        p.setBrush(g)
        p.drawEllipse(lc, lr, lr)
        glass = QtGui.QRadialGradient(lc + QtCore.QPointF(-3, -4), lr)
        glass.setColorAt(0, QtGui.QColor("#fffdf2"))
        glass.setColorAt(0.7, QtGui.QColor("#f3e7c4"))
        glass.setColorAt(1, QtGui.QColor("#cdb684"))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 120), 0.8))
        p.setBrush(glass)
        p.drawEllipse(lc, lr - 3, lr - 3)
        if self.ratio is None:
            text, col = "1:–", QtGui.QColor("#6a5a40")
        else:
            text = "1:∞" if self.ratio >= 6 else f"1:{self.ratio:.1f}"
            col = QtGui.QColor("#b01010" if self.ratio > 2 else "#1a1208")
        f = QtGui.QFont("DejaVu Sans Condensed", 8, QtGui.QFont.Bold)
        while QtGui.QFontMetricsF(f).horizontalAdvance(text) > 2 * (lr - 4) and f.pointSizeF() > 5:
            f.setPointSizeF(f.pointSizeF() - 0.25)  # grossi par la loupe, mais tient dedans
        p.setFont(f)
        p.setPen(col)
        p.drawText(QtCore.QRectF(lc.x() - lr, lc.y() - 7, 2 * lr, 14), QtCore.Qt.AlignCenter, text)
        shine = QtGui.QRadialGradient(lc + QtCore.QPointF(-5, -6), 7)    # reflet du verre
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 170))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(shine)
        p.drawEllipse(lc + QtCore.QPointF(-5, -6), 7, 5)
        # LED d'alarme, à droite dans le cadran
        c = QtCore.QPointF(w - 19, 15)
        g = QtGui.QRadialGradient(c - QtCore.QPointF(1.5, 1.5), 7)
        if self.led_on:
            halo = QtGui.QRadialGradient(c, 13)
            halo.setColorAt(0, QtGui.QColor(255, 40, 20, 170))
            halo.setColorAt(1, QtGui.QColor(255, 40, 20, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, 13, 13)
            g.setColorAt(0, QtGui.QColor("#ffd0c0"))
            g.setColorAt(1, QtGui.QColor("#ff1a0a"))
        else:
            g.setColorAt(0, QtGui.QColor("#6a2a20"))
            g.setColorAt(1, QtGui.QColor("#1e0604"))
        p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1))
        p.setBrush(g)
        p.drawEllipse(c, 5.5, 5.5)
        # verre bombé : reflet courbe en haut et liseré lumineux
        face = QtCore.QRectF(7, 7, w - 14, h - 14)
        p.save()
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(face, 6, 6)
        p.setClipPath(clip)
        sheen = QtGui.QPainterPath()
        sheen.moveTo(face.left() + 6, face.top() + 2)
        sheen.cubicTo(face.left() + w * 0.25, face.top() + face.height() * 0.42,
                      face.right() - w * 0.25, face.top() + face.height() * 0.42,
                      face.right() - 6, face.top() + 2)
        sheen.lineTo(face.right() - 6, face.top())
        sheen.lineTo(face.left() + 6, face.top())
        sheen.closeSubpath()
        sg = QtGui.QLinearGradient(0, face.top(), 0, face.top() + face.height() * 0.4)
        sg.setColorAt(0, QtGui.QColor(255, 255, 255, 95))
        sg.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(sg)
        p.drawPath(sheen)
        p.restore()
        p.setBrush(QtCore.Qt.NoBrush)
        lip = QtGui.QLinearGradient(0, face.bottom() - 7, 0, face.bottom())
        lip.setColorAt(0, QtGui.QColor(0, 0, 0, 0))
        lip.setColorAt(1, QtGui.QColor(0, 0, 0, 110))
        p.save()
        p.setClipPath(clip)
        p.fillRect(QtCore.QRectF(face.left(), face.bottom() - 7, face.width(), 7), lip)
        p.restore()
        edge = QtGui.QLinearGradient(0, face.top(), 0, face.bottom())
        edge.setColorAt(0, QtGui.QColor(255, 255, 255, 150))
        edge.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtGui.QPen(QtGui.QBrush(edge), 1.2))
        p.drawRoundedRect(face.adjusted(0.6, 0.6, -0.6, -0.6), 6, 6)
        p.end()


class SwrTitle(QtWidgets.QWidget):
    """« R . O . S » en lettres grasses espacées au-dessus du micro-galva ROS ;
    clignote en rouge (avec halo) quand le ROS dépasse 2."""

    def __init__(self, width=300, height=12):
        super().__init__()
        self.setFixedSize(width, height)
        self.red = False

    def set_alert(self, on):
        if on != self.red:
            self.red = on
            self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Black)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2.5)
        p.setFont(f)
        r = QtCore.QRectF(0, -1, self.width(), self.height() + 2)
        text = "R . O . S"
        if self.red:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):     # halo rouge
                p.setPen(QtGui.QColor(255, 60, 30, 110))
                p.drawText(r.translated(dx, dy), QtCore.Qt.AlignCenter, text)
            p.setPen(QtGui.QColor("#e01208"))
        else:
            p.setPen(QtGui.QColor(255, 255, 255, 160))                # gravure
            p.drawText(r.translated(0, 0.8), QtCore.Qt.AlignCenter, text)
            p.setPen(QtGui.QColor("#2a1c0c"))
        p.drawText(r, QtCore.Qt.AlignCenter, text)
        p.end()
