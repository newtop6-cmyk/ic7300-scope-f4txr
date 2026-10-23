"""Œil magique vintage (façon tube EM34) : écran fluorescent vert dans une
lunette chromée en relief. Ses deux secteurs d'ombre se referment quand on
approche de l'accord, en phase exacte avec l'aiguille du galvanomètre de calage
(il lit needle_hz() à chaque image du cadran). Très sensible près du 0."""

import math
import random

from PyQt5 import QtCore, QtGui, QtWidgets

FULL_HZ = 200.0             # écart pour lequel l'œil est grand ouvert
SENSITIVITY = 0.4           # < 1 : échelle dilatée près du 0 (très sensible)
OPEN_DEG = 62.0             # demi-angle de chaque ombre, loin de l'accord
CLOSED_DEG = 0.6            # demi-angle à l'accord parfait


class MagicEye(QtWidgets.QWidget):
    def __init__(self, meter, size=124):
        super().__init__()
        self.meter = meter
        meter.followers.append(self)            # repeint avec l'aiguille
        self.setFixedSize(size, size)
        self.setToolTip("Œil magique : les ombres se referment à l'accord parfait")
        self._flicker = 1.0

    def closeness(self):
        """0 (loin) → 1 (accord parfait), suit l'aiguille du cadran."""
        state = self.meter.state
        if state == "off":
            return 0.0
        if state == "locked":
            return 1.0
        x = min(self.meter.needle_hz(), FULL_HZ) / FULL_HZ
        return 1.0 - x ** SENSITIVITY

    def brightness(self):
        return 0.35 if self.meter.state == "off" else 1.0

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w = self.width()
        c = QtCore.QPointF(w / 2, w / 2)
        R = w / 2 - 2
        close = self.closeness()
        self._flicker = 0.9 * self._flicker + 0.1 * random.uniform(0.96, 1.04)
        glow = self.brightness() * self._flicker

        # --- ombre portée sous la lunette (relief) ---
        shadow = QtGui.QRadialGradient(c + QtCore.QPointF(2, 3), R + 2)
        shadow.setColorAt(0.85, QtGui.QColor(0, 0, 0, 150))
        shadow.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(c + QtCore.QPointF(2, 3), R + 2, R + 2)

        # --- lunette chromée : dégradé conique (reflets métal) ---
        chrome = QtGui.QConicalGradient(c, 135)
        for pos, col in ((0.0, "#f4f4f4"), (0.12, "#8c8c8c"), (0.25, "#e6e6e6"),
                         (0.4, "#5a5a5a"), (0.55, "#d8d8d8"), (0.7, "#6e6e6e"),
                         (0.85, "#cfcfcf"), (1.0, "#f4f4f4")):
            chrome.setColorAt(pos, QtGui.QColor(col))
        p.setBrush(chrome)
        p.drawEllipse(c, R, R)
        # arête du biseau : claire en haut, sombre en bas
        bevel = QtGui.QLinearGradient(0, c.y() - R, 0, c.y() + R)
        bevel.setColorAt(0, QtGui.QColor(255, 255, 255, 120))
        bevel.setColorAt(0.5, QtGui.QColor(255, 255, 255, 0))
        bevel.setColorAt(1, QtGui.QColor(0, 0, 0, 140))
        p.setBrush(bevel)
        p.drawEllipse(c, R, R)

        # --- creux : le verre est enfoncé dans la lunette ---
        r_well = R - 9
        well = QtGui.QLinearGradient(0, c.y() - r_well, 0, c.y() + r_well)
        well.setColorAt(0, QtGui.QColor("#050505"))
        well.setColorAt(1, QtGui.QColor("#4a4a4a"))
        p.setBrush(well)
        p.drawEllipse(c, r_well, r_well)
        r_glass = r_well - 3
        inner = QtGui.QRadialGradient(c, r_glass)
        inner.setColorAt(0.0, QtGui.QColor("#0b1a0d"))
        inner.setColorAt(0.8, QtGui.QColor("#061008"))
        inner.setColorAt(1.0, QtGui.QColor("#010301"))
        p.setBrush(inner)
        p.drawEllipse(c, r_glass, r_glass)

        # --- écran fluorescent (anneau vert) ---
        r_out = r_glass - 4
        r_in = r_glass * 0.30
        phosphor = QtGui.QRadialGradient(c, r_out)
        green_hi = QtGui.QColor.fromRgbF(0.55 * glow, 1.0 * glow, 0.45 * glow)
        green_mid = QtGui.QColor.fromRgbF(0.15 * glow, 0.85 * glow, 0.22 * glow)
        green_lo = QtGui.QColor.fromRgbF(0.04 * glow, 0.40 * glow, 0.10 * glow)
        phosphor.setColorAt(r_in / r_out, green_hi)
        phosphor.setColorAt(0.7, green_mid)
        phosphor.setColorAt(1.0, green_lo)
        ring = QtGui.QPainterPath()
        ring.addEllipse(c, r_out, r_out)
        hole = QtGui.QPainterPath()
        hole.addEllipse(c, r_in, r_in)
        ring = ring.subtracted(hole)
        p.setBrush(phosphor)
        p.drawPath(ring)
        # stries radiales fines (aspect du tube)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 35), 1))
        for k in range(48):
            a = math.radians(k * 7.5)
            p.drawLine(QtCore.QPointF(c.x() + r_in * math.cos(a), c.y() + r_in * math.sin(a)),
                       QtCore.QPointF(c.x() + r_out * math.cos(a), c.y() + r_out * math.sin(a)))
        p.setPen(QtCore.Qt.NoPen)

        # --- les deux secteurs d'ombre (haut et bas) ---
        half = CLOSED_DEG + (OPEN_DEG - CLOSED_DEG) * (1.0 - close)
        box = QtCore.QRectF(c.x() - r_out - 1, c.y() - r_out - 1,
                            2 * r_out + 2, 2 * r_out + 2)
        for centre_deg in (90.0, 270.0):
            # bord flou : deux passes, la plus large à demi transparente
            for extra, alpha in ((2.5, 110), (0.0, 235)):
                wedge = QtGui.QPainterPath()
                wedge.moveTo(c)
                wedge.arcTo(box, centre_deg - half - extra, 2 * (half + extra))
                wedge.closeSubpath()
                wedge = wedge.intersected(ring)
                p.setBrush(QtGui.QColor(4, 18, 6, alpha))
                p.drawPath(wedge)
            # liserés lumineux sur les bords des ombres
            edge_pen = QtGui.QPen(QtGui.QColor.fromRgbF(
                min(1, 0.7 * glow), min(1, 1.0 * glow), min(1, 0.6 * glow), 0.9), 1.4)
            p.setPen(edge_pen)
            for side in (-1, 1):
                a = math.radians(centre_deg + side * half)
                p.drawLine(QtCore.QPointF(c.x() + r_in * math.cos(a),
                                          c.y() - r_in * math.sin(a)),
                           QtCore.QPointF(c.x() + r_out * math.cos(a),
                                          c.y() - r_out * math.sin(a)))
            p.setPen(QtCore.Qt.NoPen)

        # à l'accord parfait : les bords se touchent et s'illuminent
        if close > 0.97:
            flash = (close - 0.97) / 0.03
            p.setPen(QtGui.QPen(QtGui.QColor.fromRgbF(0.8, 1.0, 0.7, 0.9 * flash * glow), 2.4))
            for centre_deg in (90.0, 270.0):
                a = math.radians(centre_deg)
                p.drawLine(QtCore.QPointF(c.x() + r_in * math.cos(a), c.y() - r_in * math.sin(a)),
                           QtCore.QPointF(c.x() + r_out * math.cos(a), c.y() - r_out * math.sin(a)))
            p.setPen(QtCore.Qt.NoPen)

        # --- halo vert dans le verre ---
        halo = QtGui.QRadialGradient(c, r_glass)
        halo.setColorAt(0.5, QtGui.QColor(60, 255, 90, int(40 * glow * (0.5 + close))))
        halo.setColorAt(1.0, QtGui.QColor(60, 255, 90, 0))
        p.setBrush(halo)
        p.drawEllipse(c, r_glass, r_glass)

        # --- chapeau central noir (cathode), légèrement bombé ---
        cap_r = r_in - 1
        cap = QtGui.QRadialGradient(c - QtCore.QPointF(cap_r * 0.35, cap_r * 0.35), cap_r * 1.3)
        cap.setColorAt(0.0, QtGui.QColor("#5a5a5a"))
        cap.setColorAt(0.35, QtGui.QColor("#1c1c1c"))
        cap.setColorAt(1.0, QtGui.QColor("#000000"))
        p.setBrush(cap)
        p.drawEllipse(c, cap_r, cap_r)
        p.setPen(QtGui.QPen(QtGui.QColor(110, 110, 110, 160), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(c, cap_r, cap_r)
        p.setPen(QtCore.Qt.NoPen)

        # --- reflet du verre bombé ---
        shine = QtGui.QLinearGradient(c.x() - r_glass, c.y() - r_glass, c.x(), c.y())
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 95))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawEllipse(QtCore.QRectF(c.x() - r_glass * 0.82, c.y() - r_glass * 0.88,
                                    r_glass * 1.1, r_glass * 0.62))
        p.end()
