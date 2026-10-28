"""Bouton d'arrêt d'urgence : champignon rouge très en relief, sur une
collerette jaune où « EMERGENCY » est écrit en rouge tout autour (360°).

Signal pressed() à l'appui. set_flashing(True) : le champignon flashe par
cycles de 3 éclairs à intervalles réguliers (jusqu'à set_flashing(False))."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets


class EmergencyButton(QtWidgets.QWidget):
    pressed = QtCore.pyqtSignal()

    def __init__(self, size=78):
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("ARRÊT D'URGENCE : coupe immédiatement toute émission "
                        "(PTT, message, VOX, CW, accord). 5 s après, il flashe par "
                        "séries de 3 ; nouvel appui = fin des flashs.")
        self.down = False
        self.flashing = False
        self.lit = False
        self.step = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    # --- flashs : 3 éclairs (150 ms allumé / 150 ms éteint), puis 1,5 s de pause
    PATTERN = [1, 0, 1, 0, 1, 0] + [0] * 10      # pas de 150 ms

    def set_flashing(self, on):
        self.flashing = on
        self.step = 0
        if on:
            self.timer.start(150)
        else:
            self.timer.stop()
            self.lit = False
        self.update()

    def _tick(self):
        self.lit = bool(self.PATTERN[self.step % len(self.PATTERN)])
        self.step += 1
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.down = True
            self.update()
            self.pressed.emit()

    def mouseReleaseEvent(self, event):
        self.down = False
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s = self.width()
        c = QtCore.QPointF(s / 2, s / 2)
        R = s / 2 - 1
        # collerette jaune (étiquette circulaire) avec liseré noir
        p.setPen(QtCore.Qt.NoPen)
        sh = QtGui.QRadialGradient(c + QtCore.QPointF(0, 2), R)
        sh.setColorAt(0.85, QtGui.QColor(0, 0, 0, 90))
        sh.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(sh)
        p.drawEllipse(c + QtCore.QPointF(0, 2), R, R)
        ring = QtGui.QRadialGradient(c - QtCore.QPointF(R * 0.3, R * 0.3), R * 1.4)
        ring.setColorAt(0, QtGui.QColor("#fff27a"))
        ring.setColorAt(0.6, QtGui.QColor("#ffd200"))
        ring.setColorAt(1, QtGui.QColor("#c89400"))
        p.setBrush(ring)
        p.setPen(QtGui.QPen(QtGui.QColor("#1a1a1a"), 1.4))
        p.drawEllipse(c, R - 1, R - 1)
        # « EMERGENCY » en rouge sur tout le tour (360°) : en haut lu de
        # l'extérieur, en bas lu à l'endroit (comme un vrai arrêt d'urgence),
        # séparés par deux ✱ à gauche et à droite
        rb_ = R * 0.56                               # bord du socle noir
        f = QtGui.QFont("DejaVu Sans Condensed")
        f.setWeight(QtGui.QFont.Black)
        size = max(7, round((R - 1 - rb_) * 0.74))
        f.setPixelSize(size)
        fm = QtGui.QFontMetricsF(f)
        rt = (R - 1 + rb_) / 2                       # milieu de la collerette
        span = 150.0
        while size > 6 and fm.horizontalAdvance("EMERGENCY") > math.radians(span) * rt:
            size -= 1                                # rétrécit si ça ne tient pas
            f.setPixelSize(size)
            fm = QtGui.QFontMetricsF(f)
        p.setFont(f)
        p.setPen(QtGui.QColor("#c80000"))
        yoff = fm.ascent() * 0.36
        for top in (True, False):
            widths = [fm.horizontalAdvance(ch) for ch in "EMERGENCY"]
            per = span / sum(widths)
            a = (-90.0 - span / 2) if top else (90.0 + span / 2)
            for ch, wch in zip("EMERGENCY", widths):
                step = wch * per
                mid = a + step / 2 if top else a - step / 2
                p.save()
                p.translate(c)
                if top:
                    p.rotate(mid + 90)
                    p.translate(0, -rt)
                else:
                    p.rotate(mid - 90)
                    p.translate(0, rt)
                p.drawText(QtCore.QPointF(-wch / 2, yoff), ch)
                p.restore()
                a = a + step if top else a - step
        for ang in (0.0, 180.0):                     # ✱ à droite et à gauche
            p.save()
            p.translate(c)
            p.rotate(ang + 90)
            p.translate(0, -rt)
            w_ = fm.horizontalAdvance("✱")
            p.drawText(QtCore.QPointF(-w_ / 2, yoff), "✱")
            p.restore()
        # socle noir du champignon
        rb = R * 0.56
        g = QtGui.QRadialGradient(c - QtCore.QPointF(rb * 0.3, rb * 0.3), rb * 1.3)
        g.setColorAt(0, QtGui.QColor("#5a5a5a"))
        g.setColorAt(1, QtGui.QColor("#0a0a0a"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.setBrush(g)
        p.drawEllipse(c, rb, rb)
        # champignon rouge très en relief (enfoncé : plus bas, plus sombre)
        off = QtCore.QPointF(0, 1.5 if self.down else -1.5)
        rm = R * (0.46 if self.down else 0.5)
        mc = c + off
        shadow = QtGui.QRadialGradient(mc + QtCore.QPointF(2, 4), rm * 1.15)
        shadow.setColorAt(0.7, QtGui.QColor(0, 0, 0, 150))
        shadow.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(mc + QtCore.QPointF(2, 4), rm * 1.15, rm * 1.15)
        bright = self.lit
        if bright:                                   # éclair : halo rouge vif
            halo = QtGui.QRadialGradient(mc, rm * 1.9)
            halo.setColorAt(0, QtGui.QColor(255, 60, 40, 200))
            halo.setColorAt(1, QtGui.QColor(255, 0, 0, 0))
            p.setBrush(halo)
            p.drawEllipse(mc, rm * 1.9, rm * 1.9)
        dome = QtGui.QRadialGradient(mc - QtCore.QPointF(rm * 0.35, rm * 0.45), rm * 1.25)
        if bright:
            dome.setColorAt(0, QtGui.QColor("#ffffff"))
            dome.setColorAt(0.25, QtGui.QColor("#ff7a6a"))
            dome.setColorAt(0.7, QtGui.QColor("#ff1a00"))
            dome.setColorAt(1, QtGui.QColor("#a00000"))
        elif self.down:
            dome.setColorAt(0, QtGui.QColor("#d05050"))
            dome.setColorAt(0.5, QtGui.QColor("#8e0a0a"))
            dome.setColorAt(1, QtGui.QColor("#3a0000"))
        else:
            dome.setColorAt(0, QtGui.QColor("#ffb0a0"))
            dome.setColorAt(0.3, QtGui.QColor("#e8241a"))
            dome.setColorAt(0.75, QtGui.QColor("#a50a06"))
            dome.setColorAt(1, QtGui.QColor("#4a0000"))
        p.setBrush(dome)
        p.setPen(QtGui.QPen(QtGui.QColor("#2a0000"), 1))
        p.drawEllipse(mc, rm, rm)
        # reflets : grand reflet en haut à gauche + liseré bas
        hl = QtGui.QRadialGradient(mc - QtCore.QPointF(rm * 0.38, rm * 0.48), rm * 0.55)
        hl.setColorAt(0, QtGui.QColor(255, 255, 255, 210))
        hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(hl)
        p.drawEllipse(mc - QtCore.QPointF(rm * 0.38, rm * 0.48), rm * 0.55, rm * 0.4)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 140, 120, 120), 1.2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(QtCore.QRectF(mc.x() - rm + 3, mc.y() - rm + 3, 2 * rm - 6, 2 * rm - 6),
                  200 * 16, 140 * 16)
        p.end()
