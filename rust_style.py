"""Style « tôle rouillée de surplus militaire » pour la plaque des pas fins :
plaque rouillée avec restes de peinture vert armée et rivets, interrupteurs
à levier en acier sur platine olive, voyants ambre."""

import math
import random

from PyQt5 import QtCore, QtGui, QtWidgets

from vintage_switch import BlueLed, LeverSwitch


def paint_rust(p, rect, seed, paint_cover=0.35):
    """Tôle rouillée dans rect : rouille marbrée, écailles vert armée
    (paint_cover ≈ part couverte), coulures, piqûres."""
    rnd = random.Random(seed)
    x0, y0, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    g = QtGui.QLinearGradient(0, y0, 0, y0 + h)
    g.setColorAt(0, QtGui.QColor("#8a4a1f"))
    g.setColorAt(0.5, QtGui.QColor("#6b3412"))
    g.setColorAt(1, QtGui.QColor("#3f1d08"))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(g)
    p.drawRect(rect)
    area = w * h
    for _ in range(int(area / 90)):
        x, y = x0 + rnd.uniform(0, w), y0 + rnd.uniform(0, h)
        r = rnd.uniform(2, 9)
        col = rnd.choice(((176, 88, 30), (140, 62, 20), (90, 40, 14), (196, 110, 45),
                          (50, 24, 8)))
        rg = QtGui.QRadialGradient(x, y, r)
        rg.setColorAt(0, QtGui.QColor(*col, rnd.randint(60, 140)))
        rg.setColorAt(1, QtGui.QColor(*col, 0))
        p.setBrush(rg)
        p.drawEllipse(QtCore.QPointF(x, y), r * rnd.uniform(1, 2), r)
    for _ in range(int(area * paint_cover / 900) + 1):          # écailles vert armée
        cx, cy = x0 + rnd.uniform(0, w), y0 + rnd.uniform(0, h)
        n = 14
        rx, ry = rnd.uniform(14, 40), rnd.uniform(10, 30)
        poly = QtGui.QPolygonF([QtCore.QPointF(
            cx + math.cos(2 * math.pi * k / n) * rx * rnd.uniform(0.55, 1.1),
            cy + math.sin(2 * math.pi * k / n) * ry * rnd.uniform(0.55, 1.1)) for k in range(n)])
        p.setBrush(QtGui.QColor(0, 0, 0, 70))
        p.drawPolygon(poly.translated(0.8, 1.2))
        p.setBrush(QtGui.QColor(rnd.randint(70, 88), rnd.randint(80, 95),
                                rnd.randint(40, 52), 235))
        p.drawPolygon(poly)
    for _ in range(int(w / 25)):                                # coulures
        x = x0 + rnd.uniform(0, w)
        ys = y0 + rnd.uniform(0, h * 0.6)
        lg = QtGui.QLinearGradient(x, ys, x, y0 + h)
        lg.setColorAt(0, QtGui.QColor(150, 70, 20, 0))
        lg.setColorAt(0.3, QtGui.QColor(150, 70, 20, 100))
        lg.setColorAt(1, QtGui.QColor(90, 40, 10, 40))
        p.setBrush(lg)
        p.drawRect(QtCore.QRectF(x, ys, rnd.uniform(1, 2.2), y0 + h - ys))
    for _ in range(int(area / 25)):                             # piqûres
        x, y = x0 + rnd.uniform(0, w), y0 + rnd.uniform(0, h)
        p.setBrush(QtGui.QColor(20, 8, 2, rnd.randint(40, 140)) if rnd.random() < 0.7
                   else QtGui.QColor(230, 150, 80, rnd.randint(30, 80)))
        p.drawEllipse(QtCore.QPointF(x, y), rnd.uniform(0.4, 1.0), rnd.uniform(0.4, 0.9))


def paint_rivet(p, c, r=4.2):
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 130))
    p.drawEllipse(c + QtCore.QPointF(1, 1.5), r + 0.5, r + 0.5)
    g = QtGui.QRadialGradient(c - QtCore.QPointF(r * 0.35, r * 0.4), r * 1.3)
    g.setColorAt(0, QtGui.QColor("#c9a184"))
    g.setColorAt(0.5, QtGui.QColor("#7a4a2a"))
    g.setColorAt(1, QtGui.QColor("#2e1a0c"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#1e1108"), 0.8))
    p.drawEllipse(c, r, r)


class RustPlate(QtWidgets.QFrame):
    """Plaque de tôle rouillée rivetée aux 4 coins."""

    def __init__(self):
        super().__init__()
        self._cache = None

    def resizeEvent(self, event):
        self._cache = None

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if self._cache is None or self._cache.size() != self.size():
            pm = QtGui.QPixmap(self.size())
            pm.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(pm)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            path = QtGui.QPainterPath()
            r = QtCore.QRectF(1, 1, w - 2, h - 2)
            path.addRoundedRect(r, 6, 6)
            p.setClipPath(path)
            paint_rust(p, r, 7300 + w + h, paint_cover=0.45)
            # éclaircie : la tôle rouillée reste visible mais bien plus claire
            p.fillPath(path, QtGui.QColor(255, 236, 205, 95))
            p.setClipping(False)
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor("#1a0c04"), 1.5))
            p.drawPath(path)
            p.setPen(QtGui.QPen(QtGui.QColor(230, 160, 100, 55), 1))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 5, 5)
            for sx, sy in ((9, 9), (w - 9, 9), (9, h - 9), (w - 9, h - 9)):
                paint_rivet(p, QtCore.QPointF(sx, sy))
            p.end()
            self._cache = pm
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.end()


class MilitaryLever(LeverSwitch):
    """Interrupteur à levier en acier sur platine olive écaillée, écrou hexagonal."""

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 + 1
        plate = QtCore.QRectF(4, 5, w - 8, h - 9)
        # platine olive drab, peinture mate usée
        g = QtGui.QLinearGradient(0, plate.top(), 0, plate.bottom())
        g.setColorAt(0, QtGui.QColor("#9aa166"))
        g.setColorAt(1, QtGui.QColor("#6a7140"))
        p.setPen(QtGui.QPen(QtGui.QColor("#15170b"), 1))
        p.setBrush(g)
        p.drawRoundedRect(plate, 4, 4)
        rnd = random.Random(int(w * 31 + h))
        p.setPen(QtCore.Qt.NoPen)
        for _ in range(40):                                     # usure : rouille et acier
            x = rnd.uniform(plate.left() + 2, plate.right() - 2)
            y = rnd.uniform(plate.top() + 2, plate.bottom() - 2)
            p.setBrush(QtGui.QColor(150, 75, 25, rnd.randint(50, 130)) if rnd.random() < 0.6
                       else QtGui.QColor(200, 200, 185, rnd.randint(30, 80)))
            p.drawEllipse(QtCore.QPointF(x, y), rnd.uniform(0.5, 1.8), rnd.uniform(0.4, 1.2))
        # repères au pochoir : OFF à gauche, ON à droite
        p.setFont(QtGui.QFont("DejaVu Sans Condensed", 6, QtGui.QFont.Black))
        p.setPen(QtGui.QColor(232, 226, 207, 210))
        p.drawText(QtCore.QRectF(plate.left() + 4, plate.top(), 22, plate.height()),
                   QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, "OFF")
        p.drawText(QtCore.QRectF(plate.right() - 22, plate.top(), 18, plate.height()),
                   QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, "ON")
        # écrou hexagonal en acier
        hexa = QtGui.QPolygonF([QtCore.QPointF(cx + 8 * math.cos(math.radians(60 * k + 30)),
                                               cy + 8 * math.sin(math.radians(60 * k + 30)))
                                for k in range(6)])
        g = QtGui.QLinearGradient(cx - 8, cy - 8, cx + 8, cy + 8)
        g.setColorAt(0, QtGui.QColor("#d7d9d6"))
        g.setColorAt(0.5, QtGui.QColor("#80837f"))
        g.setColorAt(1, QtGui.QColor("#3a3c39"))
        p.setPen(QtGui.QPen(QtGui.QColor("#1b1c1a"), 0.9))
        p.setBrush(g)
        p.drawPolygon(hexa)
        p.setBrush(QtGui.QColor("#2a2b29"))
        p.drawEllipse(QtCore.QPointF(cx, cy), 3.2, 3.2)
        # levier : tige d'acier effilée, embout plus sombre
        length = w * 0.30
        tip = QtCore.QPointF(cx + length * self.pos_f, cy)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 90), 5, cap=QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(cx + 2, cy + 3), tip + QtCore.QPointF(3, 4))
        stem = QtGui.QLinearGradient(0, cy - 4, 0, cy + 4)
        stem.setColorAt(0, QtGui.QColor("#eceeea"))
        stem.setColorAt(0.5, QtGui.QColor("#8d908b"))
        stem.setColorAt(1, QtGui.QColor("#3a3c38"))
        p.setPen(QtGui.QPen(QtGui.QBrush(stem), 5, cap=QtCore.Qt.FlatCap))
        p.drawLine(QtCore.QPointF(cx, cy), tip)
        g = QtGui.QRadialGradient(tip - QtCore.QPointF(1.5, 1.5), 6)
        g.setColorAt(0, QtGui.QColor("#d0d2ce"))
        g.setColorAt(0.5, QtGui.QColor("#6d706b"))
        g.setColorAt(1, QtGui.QColor("#262825"))
        p.setPen(QtGui.QPen(QtGui.QColor("#161715"), 0.8))
        p.setBrush(g)
        p.drawRoundedRect(QtCore.QRectF(tip.x() - 4, tip.y() - 4.5, 8, 9), 2.5, 2.5)
        p.end()


class AmberLed(BlueLed):
    """Même voyant que BlueLed, mais ambre dans une bague d'acier."""

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s = self.width()
        c = QtCore.QPointF(s / 2, s / 2)
        lit = self.mode == "on" or (self.mode == "blink" and self.phase)
        p.setPen(QtCore.Qt.NoPen)
        if lit:
            halo = QtGui.QRadialGradient(c, s / 2)
            halo.setColorAt(0.0, QtGui.QColor(255, 220, 140, 255))
            halo.setColorAt(0.35, QtGui.QColor(255, 150, 30, 200))
            halo.setColorAt(1.0, QtGui.QColor(255, 110, 0, 0))
            p.setBrush(halo)
            p.drawEllipse(c, s / 2, s / 2)
        ring = s * 0.33
        g = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#e6e8e4"), (0.25, "#6c6f6a"), (0.5, "#cfd1cd"),
                          (0.75, "#4c4f4a"), (1, "#e6e8e4")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#161715"), 0.8))
        p.drawEllipse(c, ring, ring)
        r = s * 0.22
        g = QtGui.QRadialGradient(c - QtCore.QPointF(r * 0.3, r * 0.3), r * 1.2)
        if lit:
            g.setColorAt(0, QtGui.QColor("#fffbe8"))
            g.setColorAt(0.4, QtGui.QColor("#ffc85a"))
            g.setColorAt(1, QtGui.QColor("#e07000"))
        else:
            g.setColorAt(0, QtGui.QColor("#5a3a14"))
            g.setColorAt(1, QtGui.QColor("#1c1005"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 0.8))
        p.setBrush(g)
        p.drawEllipse(c, r, r)
        p.end()
