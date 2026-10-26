"""Galvas d'émission, style « galva de calage » : boîtier bakélite, cadran crème
en demi-cercle avec l'axe de l'aiguille visible, éclairage par ampoule.

  TxGalva       : les deux galvas côte à côte (même interface qu'avant pour Scope)
      - gauche : MODULATION, Po en W (échelle très dilatée, aiguille noire)
      - droite : COMPRESSION, COMP en dB (aiguille rouge)
  RedButton     : gros bouton rouge rond vintage (bouton poussoir lumineux)

Les aiguilles suivent un ressort amorti à 60 images/s : départ immédiat,
léger rebond, et redescente douce (elles tiennent entre les syllabes).
"""

import math

from PyQt5 import QtCore, QtGui, QtWidgets

import pump_glow

PO_MAX = 100.0
COMP_MAX = 30.0
PO_CURVE = 0.3                  # 8 W ≈ mi-course, 35 W ≈ 3/4
COMP_CURVE = 0.6
FALL_PER_S = 3.0                # redescente ≈ 1/3 s
SPAN = 60.0                     # degrés de part et d'autre du centre


def po_frac(watts):
    return (max(0.0, min(PO_MAX, watts)) / PO_MAX) ** PO_CURVE


def comp_frac(db):
    return (max(0.0, min(COMP_MAX, db)) / COMP_MAX) ** COMP_CURVE


class _Needle:
    """Aiguille à cadre mobile : ressort + amortisseur."""

    def __init__(self, stiffness, damping):
        self.k = stiffness
        self.c = 2 * math.sqrt(stiffness) * damping
        self.pos = 0.0
        self.vel = 0.0
        self.target = 0.0

    def step(self, dt):
        acc = self.k * (self.target - self.pos) - self.c * self.vel
        self.vel += acc * dt
        self.pos += self.vel * dt
        if self.pos < -0.02:
            self.pos, self.vel = -0.02, 0.0
        if self.pos > 1.04:
            self.pos, self.vel = 1.04, -self.vel * 0.3


def _mix(a, b, t):
    return QtGui.QColor.fromRgbF(*(a.getRgbF()[i] * (1 - t) + b.getRgbF()[i] * t
                                   for i in range(3)))


class RoundGalva(QtWidgets.QWidget):
    """Galva en demi-cercle (dôme arrondi en haut, base plate), dans le style
    du galva de calage : bakélite, cadran crème, axe de l'aiguille visible."""

    def __init__(self, title, ticks, frac, red_from, needle_color,
                 width=116, height=80, stiffness=1000.0, damping=0.5):
        super().__init__()
        self.setFixedSize(width, height)
        self.title = title
        self.ticks = ticks              # [(valeur, libellé ou "")]
        self.frac = frac                # valeur → fraction 0..1 de l'échelle
        self.red_from = red_from
        self.needle_color = QtGui.QColor(needle_color)
        self.needle = _Needle(stiffness, damping)
        self.light = 0.0                # éclairage 0..1
        self.value_text = ""            # (non affiché à cette taille)
        self.lamp = None                # (libellé, allumé) : petit voyant
        self.corner_text = ""

    def angle(self, f):
        return math.radians(-SPAN + 2 * SPAN * f)

    def _shape(self, inset):
        """Contour en demi-cercle : arc en haut, côtés droits, base plate."""
        w, h = self.width(), self.height()
        R = w / 2 - inset
        cx, cy = w / 2, w / 2                  # centre du demi-cercle
        path = QtGui.QPainterPath()
        path.moveTo(inset, h - inset)
        path.lineTo(inset, cy)
        path.arcTo(QtCore.QRectF(cx - R, cy - R, 2 * R, 2 * R), 180, -180)
        path.lineTo(w - inset, h - inset)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QtCore.Qt.NoPen)
        # boîtier bakélite en relief
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
        # cadran crème éclairé par l'ampoule (plus fort en émission)
        face_path = self._shape(6)
        dim = (QtGui.QColor("#d8cca8"), QtGui.QColor("#bfae86"), QtGui.QColor("#8c7d5e"))
        bright = (QtGui.QColor("#fff8d8"), QtGui.QColor("#ffe08a"), QtGui.QColor("#d9a84c"))
        glow = QtGui.QRadialGradient(w / 2, h - 6, w * 0.75)
        for stop, a, b in zip((0, 0.6, 1), dim, bright):
            glow.setColorAt(stop, _mix(a, b, self.light))
        p.setBrush(glow)
        p.drawPath(face_path)
        pump_glow.paint(p, face_path, getattr(self, "pump", None))
        shade = QtGui.QLinearGradient(0, 6, 0, 22)
        shade.setColorAt(0, QtGui.QColor(0, 0, 0, 110))
        shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawPath(face_path)
        p.save()
        p.setClipPath(face_path)

        cx, cy = w / 2, h - 13                     # axe de l'aiguille, visible
        r = w * 0.30
        ink = QtGui.QColor("#2b2116")
        red = QtGui.QColor("#b3261e")

        def point(f, radius):
            a = self.angle(f)
            return QtCore.QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a))

        def arc(radius, f0, f1, color, width):
            a0 = 90 - math.degrees(self.angle(f0))
            a1 = 90 - math.degrees(self.angle(f1))
            p.setPen(QtGui.QPen(color, width, cap=QtCore.Qt.FlatCap))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawArc(QtCore.QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius),
                      int(a1 * 16), int((a0 - a1) * 16))

        red_f = self.frac(self.red_from)
        arc(r, 0, red_f, ink, 1.0)
        arc(r, red_f, 1, red, 1.0)
        arc(r - 1.5, red_f, 1, red, 2.5)
        p.setFont(QtGui.QFont("DejaVu Sans", 5, QtGui.QFont.Bold))
        for value, text in self.ticks:
            f = self.frac(value)
            color = red if value >= self.red_from else ink
            big = bool(text)
            p.setPen(QtGui.QPen(color, 1.0 if big else 0.7))
            p.drawLine(point(f, r), point(f, r + (4 if big else 2)))
            if big:
                pt = point(f, r + 9)
                p.setPen(color)
                p.drawText(QtCore.QRectF(pt.x() - 10, pt.y() - 5, 20, 10),
                           QtCore.Qt.AlignCenter, text)
        # titre sous l'arc
        p.setPen(ink)
        p.setFont(QtGui.QFont("DejaVu Serif", 5, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(cx - 20, cy - r * 0.42 - 5, 40, 10),
                   QtCore.Qt.AlignCenter, self.title)
        # voyant (ALC) en bas à droite
        if self.lamp:
            label, on = self.lamp
            lamp = QtCore.QPointF(w - 15, h - 11)
            g = QtGui.QRadialGradient(lamp - QtCore.QPointF(1, 1), 4)
            g.setColorAt(0, QtGui.QColor("#ffb0a0" if on else "#6a3a30"))
            g.setColorAt(1, QtGui.QColor("#ff2010" if on else "#2a0e08"))
            p.setPen(QtGui.QPen(QtGui.QColor("#1a0a04"), 0.8))
            p.setBrush(g)
            p.drawEllipse(lamp, 3, 3)
        # aiguille avec ombre portée, depuis l'axe visible
        f = self.needle.pos
        tip = point(f, r + 3)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1.8))
        p.drawLine(QtCore.QPointF(cx + 1.5, cy + 1.5), tip + QtCore.QPointF(1.5, 1.5))
        p.setPen(QtGui.QPen(self.needle_color, 1.3, cap=QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(cx, cy), tip)
        hub = QtGui.QRadialGradient(cx - 1, cy - 1, 4)
        hub.setColorAt(0, QtGui.QColor("#6a6a6a"))
        hub.setColorAt(1, QtGui.QColor("#0a0a0a"))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(hub)
        p.drawEllipse(QtCore.QPointF(cx, cy), 3.5, 3.5)
        # reflet du verre, dans le haut du dôme
        shine = QtGui.QLinearGradient(0, 6, 0, h * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 60))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawPath(face_path)
        p.restore()
        p.end()


S9_RAW = 120                    # valeurs brutes Icom : 120 = S9
S60_RAW = 241                   # 241 = S9 + 60 dB


class SGalva(RoundGalva):
    """S-mètre dans le même style demi-cercle que les galvas d'émission.
    Reçoit la valeur brute de la radio (0 à 241) ; aiguille animée seule."""

    def __init__(self):
        ticks = [(i * S9_RAW / 9, "1" if i == 1 else "5" if i == 5 else
                  "9" if i == 9 else "") for i in range(1, 10)]
        ticks += [(S9_RAW + db * (S60_RAW - S9_RAW) / 60, f"+{db}" if db in (20, 60) else "")
                  for db in (20, 40, 60)]
        super().__init__("S", ticks, lambda raw: max(0.0, min(1.0, raw / S60_RAW)),
                         S9_RAW, "#141414", stiffness=500.0, damping=0.7)
        self.setToolTip("S-mètre de la radio")
        self.light = 0.35               # cadran légèrement éclairé en réception
        self._in = 0.0
        self.value = 0.0                # valeur brute affichée (pour Scope)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def setValue(self, raw):
        self._in = max(0.0, min(1.0, raw / S60_RAW))

    def _tick(self):
        n = self.needle
        n.target = max(self._in, n.target - 1.2 * 0.016)    # redescente douce
        n.step(0.016)
        self.value = max(0.0, n.pos) * S60_RAW
        self.update()


class TxGalva(QtWidgets.QWidget):
    """Les deux galvas d'émission côte à côte : MODULATION (Po) et COMPRESSION."""

    def __init__(self):
        super().__init__()
        self.setToolTip("Galvas d'émission : à gauche la modulation (puissance Po), "
                        "à droite le taux de compression. Voyant ALC rouge = trop fort.")
        # petits galvas : peu de chiffres pour rester lisibles
        po_ticks = [(0, "0"), (1, "1"), (2, ""), (5, "5"), (10, ""), (20, "20"),
                    (50, ""), (100, "100")]
        comp_ticks = [(0, "0"), (5, ""), (10, "10"), (15, ""), (20, "20"), (25, ""),
                      (30, "30")]
        self.po_g = RoundGalva("Po W", po_ticks, po_frac, 80, "#141414",
                               stiffness=1100.0, damping=0.5)
        self.comp_g = RoundGalva("COMP", comp_ticks, comp_frac, 20, "#b3261e",
                                 stiffness=800.0, damping=0.6)
        self.po_g.lamp = ("ALC", False)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.po_g)
        row.addWidget(self.comp_g)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.tx = False
        self.light = 0.0
        self.alc = 0.0
        self.swr = None
        self.po_peak = 0.0
        self.po_in = 0.0
        self.comp_in = 0.0
        self.comp_db = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # --- entrées (mêmes noms qu'avant) ---
    def set_po(self, watts):
        self.po_in = po_frac(watts)
        self.po_peak = max(self.po_peak * 0.985, watts)

    def set_comp(self, db):
        self.comp_in = comp_frac(db)
        self.comp_db = db

    def set_alc(self, percent):
        self.alc = percent

    def set_swr(self, swr):
        self.swr = swr

    def set_tx(self, on):
        self.tx = on
        if not on:
            self.po_in = self.comp_in = 0.0
            self.alc = 0.0
            self.po_peak = 0.0
            self.comp_db = 0.0

    # accès aux aiguilles (auto-test)
    @property
    def po(self):
        return self.po_g.needle

    @property
    def comp(self):
        return self.comp_g.needle

    def _tick(self):
        dt = 0.016
        for galva, value in ((self.po_g, self.po_in), (self.comp_g, self.comp_in)):
            n = galva.needle
            n.target = max(value, n.target - FALL_PER_S * dt)
            n.step(dt)
        # ampoule : s'allume en émission et respire avec la modulation
        want = (0.7 + 0.3 * max(0.0, self.po_g.needle.pos)) if self.tx else 0.0
        self.light += (want - self.light) * (0.25 if want > self.light else 0.05)
        for galva in (self.po_g, self.comp_g):
            galva.light = self.light
        self.po_g.value_text = f"crête {self.po_peak:.0f} W" if self.tx else "Po  W"
        self.comp_g.value_text = f"{self.comp_db:.0f} dB" if self.tx else "dB"
        self.po_g.lamp = ("ALC", self.tx and self.alc > 100)
        self.po_g.corner_text = (f"ROS {self.swr:.1f}"
                                 if self.tx and self.swr is not None else "")
        self.po_g.update()
        self.comp_g.update()


class RedButton(QtWidgets.QAbstractButton):
    """Gros bouton rond vintage lumineux : lunette chromée, dôme en relief.
    Rouge vif en émission (enclenché), vert allumé en réception."""

    def __init__(self, text="TX", size=96, halo_room=2.3):
        super().__init__()
        self.setCheckable(True)
        self.setText(text)
        self.core = size                    # taille du bouton lui-même
        self.setFixedSize(int(size * halo_room), int(size * halo_room))   # place du halo
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.toggled.connect(lambda _: self.update())
        self.pressed.connect(self.update)
        self.released.connect(self.update)
        # en émission : flash rouge rapide (rouge vif / rouge sombre)
        self.flash = True
        self.flash_timer = QtCore.QTimer(self)
        self.flash_timer.timeout.connect(self._flash)
        self.flash_timer.start(400)      # clignotement lent : 0,4 s allumé / 0,4 s éteint
        self.alert = False               # TUNE : flash rouge rapide sans émettre le PTT

    def hitButton(self, pos):
        """Seul le bouton rond lui-même lance l'émission (pas la place du halo)."""
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        d = QtCore.QPointF(pos) - c
        return d.x() * d.x() + d.y() * d.y() <= (self.core / 2) ** 2

    def set_alert(self, on):
        """Flash rouge RAPIDE (accord TUNE en cours), sans toucher au bouton."""
        if on != self.alert:
            self.alert = on
            self.flash = True
            self.flash_timer.setInterval(110 if on else 400)
            self.update()

    def _flash(self):
        if self.isChecked() or self.alert:
            self.flash = not self.flash
            self.update()
        elif not self.flash:
            self.flash = True
            self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        full = self.width()                 # zone du halo
        s = self.core                       # bouton
        c = QtCore.QPointF(full / 2, full / 2)
        on = self.isChecked() or self.alert
        down = self.isDown()
        if on:                              # émission : flash rouge incandescent / noir
            base = QtGui.QColor(255, 30, 10) if self.flash else QtGui.QColor(28, 2, 1)
        else:
            base = QtGui.QColor(40, 230, 70)
        hot = on and self.flash
        p.setPen(QtCore.Qt.NoPen)
        # halo lumineux autour du bouton
        if not on or hot:                   # pas de halo dans la phase noire
            radius = full / 2 if hot else s / 2 + 4
            halo = QtGui.QRadialGradient(c, radius)
            if hot:                         # éclat : cœur blanc-orangé, grand rayonnement rouge
                halo.setColorAt(0.0, QtGui.QColor(255, 255, 255, 255))
                halo.setColorAt(0.22, QtGui.QColor(255, 120, 60, 255))
                halo.setColorAt(0.45, QtGui.QColor(255, 25, 0, 255))
                halo.setColorAt(0.75, QtGui.QColor(255, 0, 0, 170))
                halo.setColorAt(1.0, QtGui.QColor(255, 0, 0, 0))
            else:
                halo.setColorAt(0.7, QtGui.QColor(base.red(), base.green(), base.blue(), 110))
                halo.setColorAt(1, QtGui.QColor(base.red(), base.green(), base.blue(), 0))
            p.setBrush(halo)
            p.drawEllipse(c, radius, radius)
        # embase chromée, fine
        ring = s * 0.44
        chrome = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#f8f8f8"), (0.25, "#6a6a6a"), (0.5, "#e8e8e8"),
                          (0.75, "#4a4a4a"), (1, "#f8f8f8")):
            chrome.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(chrome)
        p.drawEllipse(c, ring, ring)
        p.setBrush(QtGui.QColor("#0c0c0c"))
        p.drawEllipse(c, ring - 4, ring - 4)
        # ombre portée du dôme sur l'embase : il sort de la façade
        r = ring - (7 if down else 5)
        # ombre douce tout autour, un peu plus marquée en bas : le dôme ressort
        shadow = QtGui.QRadialGradient(c + QtCore.QPointF(0, 2), r * 1.12)
        shadow.setColorAt(0.8, QtGui.QColor(0, 0, 0, 170))
        shadow.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shadow)
        p.drawEllipse(c + QtCore.QPointF(0, 2), r * 1.1, r * 1.1)
        # dôme très bombé, exactement au centre de sa bague
        dc = QtCore.QPointF(c)
        dome = QtGui.QRadialGradient(dc - QtCore.QPointF(r * 0.38, r * 0.45), r * 1.55,
                                     dc - QtCore.QPointF(r * 0.38, r * 0.45))
        light = base.lighter(170)
        dark = base.darker(330)
        dome.setColorAt(0.0, QtGui.QColor("#ffffff") if hot else light)   # cœur blanc éblouissant
        dome.setColorAt(0.08, light)
        dome.setColorAt(0.45, base)
        dome.setColorAt(0.85, base.darker(180))
        dome.setColorAt(1.0, dark)
        p.setBrush(dome)
        p.drawEllipse(dc, r, r)
        # lumière intérieure (lampe allumée sous le dôme)
        inner = QtGui.QRadialGradient(dc + QtCore.QPointF(0, r * 0.25), r * 0.8)
        inner.setColorAt(0, QtGui.QColor(base.red(), base.green(), base.blue(), 140))
        inner.setColorAt(1, QtGui.QColor(base.red(), base.green(), base.blue(), 0))
        p.setBrush(inner)
        p.drawEllipse(dc, r * 0.95, r * 0.95)
        # inscription seulement en émission
        if on and self.text():
            p.setPen(QtGui.QColor(255, 235, 225, 230))
            p.setFont(QtGui.QFont("DejaVu Serif", int(s / 7), QtGui.QFont.Bold))
            p.drawText(QtCore.QRectF(dc.x() - r, dc.y() - r, 2 * r, 2 * r),
                       QtCore.Qt.AlignCenter, self.text())
        p.end()


if __name__ == "__main__":         # essai : python3 tx_galva.py
    import sys
    app = QtWidgets.QApplication(sys.argv)
    box = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(box)
    g = TxGalva()
    b = RedButton()
    lay.addWidget(g)
    lay.addWidget(b)
    b.toggled.connect(g.set_tx)
    t = [0.0]

    def demo():
        t[0] += 0.05
        voice = abs(math.sin(t[0] * 3.1) * math.sin(t[0] * 0.7))
        g.set_po(voice * 60)
        g.set_comp(voice * 18)
        g.set_alc(voice * 120)
        g.set_swr(1.3)
    timer = QtCore.QTimer()
    timer.timeout.connect(demo)
    timer.start(40)
    box.show()
    sys.exit(app.exec_())
