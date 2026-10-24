"""Bandeau de titre vintage (remplace la barre blanche du bureau) : plaque
métallique vieillie et oxydée — rouille, vert-de-gris, rayures, rivets —
avec « MADE IN F4TXR » frappé en gros. À droite, trois boutons ronds en
laiton : réduire, agrandir/restaurer, fermer. Glisser = déplacer la fenêtre,
double-clic = agrandir/restaurer."""

import math
import random

from PyQt5 import QtCore, QtGui, QtWidgets

HEIGHT = 40
TEXT = "MADE IN F4TXR"


class TitlePlate(QtWidgets.QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setFixedHeight(HEIGHT)
        self._cache = None
        self._drag = None
        self._hover = None              # bouton survolé
        self.setMouseTracking(True)

    # --- boutons ---------------------------------------------------------
    def _buttons(self):
        """(nom, centre) des trois boutons, de droite à gauche."""
        y = HEIGHT / 2
        x = self.width() - 24
        return [("close", QtCore.QPointF(x, y)),
                ("max", QtCore.QPointF(x - 30, y)),
                ("min", QtCore.QPointF(x - 60, y))]

    def _button_at(self, pos):
        for name, c in self._buttons():
            if (QtCore.QPointF(pos) - c).manhattanLength() < 14:
                return name
        return None

    def mousePressEvent(self, event):
        name = self._button_at(event.pos())
        if name == "close":
            self.window.close()
        elif name == "max":
            self._toggle_max()
        elif name == "min":
            self.window.showMinimized()
        elif event.button() == QtCore.Qt.LeftButton:
            handle = self.window.windowHandle()
            if handle and hasattr(handle, "startSystemMove") and handle.startSystemMove():
                return                  # le bureau déplace la fenêtre
            self._drag = event.globalPos() - self.window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and not self.window.isMaximized():
            self.window.move(event.globalPos() - self._drag)
        hover = self._button_at(event.pos())
        if hover != self._hover:
            self._hover = hover
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        if not self._button_at(event.pos()):
            self._toggle_max()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def _toggle_max(self):
        if self.window.isMaximized() or self.window.isFullScreen():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    # --- dessin ----------------------------------------------------------
    def resizeEvent(self, event):
        self._cache = None

    def _paint_plate(self):
        """Tôle très rouillée de surplus militaire : restes de peinture vert
        armée écaillée, coulures, piqûres, texte au pochoir blanc écaillé."""
        w, h = self.width(), HEIGHT
        pm = QtGui.QPixmap(w, h)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        rnd = random.Random(1944)
        # fond : rouille
        g = QtGui.QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QtGui.QColor("#8a4a1f"))
        g.setColorAt(0.5, QtGui.QColor("#6b3412"))
        g.setColorAt(1, QtGui.QColor("#3f1d08"))
        p.fillRect(0, 0, w, h, g)
        p.setPen(QtCore.Qt.NoPen)
        # rouille marbrée : orange vif, brun, noir
        for _ in range(int(w / 3)):
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            r = rnd.uniform(2, 10)
            col = rnd.choice(((176, 88, 30), (140, 62, 20), (90, 40, 14), (196, 110, 45),
                              (50, 24, 8)))
            rg = QtGui.QRadialGradient(x, y, r)
            rg.setColorAt(0, QtGui.QColor(*col, rnd.randint(60, 140)))
            rg.setColorAt(1, QtGui.QColor(*col, 0))
            p.setBrush(rg)
            p.drawEllipse(QtCore.QPointF(x, y), r * rnd.uniform(1, 2.2), r)
        # restes de peinture vert armée (plaques écaillées aux bords irréguliers)
        for _ in range(int(w / 70)):
            cx, cy = rnd.uniform(0, w), rnd.uniform(-4, h + 4)
            n = 14
            rx, ry = rnd.uniform(18, 60), rnd.uniform(8, 18)
            poly = QtGui.QPolygonF([QtCore.QPointF(
                cx + math.cos(2 * math.pi * k / n) * rx * rnd.uniform(0.55, 1.1),
                cy + math.sin(2 * math.pi * k / n) * ry * rnd.uniform(0.55, 1.1)) for k in range(n)])
            p.setBrush(QtGui.QColor(0, 0, 0, 70))                 # bord de l'écaille
            p.drawPolygon(poly.translated(0.8, 1.2))
            p.setBrush(QtGui.QColor(rnd.randint(70, 88), rnd.randint(80, 95),
                                    rnd.randint(40, 52), 235))
            p.drawPolygon(poly)
        # coulures de rouille verticales
        for _ in range(int(w / 40)):
            x = rnd.uniform(0, w)
            y0 = rnd.uniform(0, h * 0.5)
            lg = QtGui.QLinearGradient(x, y0, x, h)
            lg.setColorAt(0, QtGui.QColor(150, 70, 20, 0))
            lg.setColorAt(0.3, QtGui.QColor(150, 70, 20, 110))
            lg.setColorAt(1, QtGui.QColor(90, 40, 10, 40))
            p.setBrush(lg)
            p.drawRect(QtCore.QRectF(x, y0, rnd.uniform(1, 2.5), h - y0))
        # piqûres et grain
        for _ in range(int(w * 2)):
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            p.setBrush(QtGui.QColor(20, 8, 2, rnd.randint(40, 140)) if rnd.random() < 0.7
                       else QtGui.QColor(230, 150, 80, rnd.randint(30, 80)))
            p.drawEllipse(QtCore.QPointF(x, y), rnd.uniform(0.4, 1.1), rnd.uniform(0.4, 0.9))
        # bords bosselés
        p.setPen(QtGui.QPen(QtGui.QColor(230, 160, 100, 60), 1))
        p.drawLine(0, 1, w, 1)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 180), 2))
        p.drawLine(0, h - 1, w, h - 1)
        for x in (14, 34, w - 120):
            self._rivet(p, QtCore.QPointF(x, h / 2))
        # texte au pochoir : lettres pleines coupées par des ponts verticaux
        font = QtGui.QFont("DejaVu Sans Condensed", 21, QtGui.QFont.Black)
        font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 10)
        fm = QtGui.QFontMetricsF(font)
        tx = (w - fm.horizontalAdvance(TEXT)) / 2
        ty = h / 2 + (fm.ascent() - fm.descent()) / 2 - 1
        path = QtGui.QPainterPath()
        path.addText(tx, ty, font, TEXT)
        bridges = QtGui.QPainterPath()
        x = tx
        for ch in TEXT:
            adv = fm.horizontalAdvance(ch) + 10
            if ch in "ADRO4":                                    # ponts du pochoir
                bridges.addRect(QtCore.QRectF(x + fm.horizontalAdvance(ch) / 2 - 1.2,
                                              ty - fm.ascent(), 2.4, fm.ascent() + 2))
            x += adv
        stencil = path.subtracted(bridges)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 60))                    # peinture un peu bavée
        p.drawPath(stencil.translated(0.6, 0.8))
        p.setBrush(QtGui.QColor("#e8e2cf"))
        p.drawPath(stencil)
        # peinture écaillée sur les lettres : la rouille réapparaît
        p.setClipPath(stencil)
        for _ in range(420):
            x = rnd.uniform(tx, tx + fm.horizontalAdvance(TEXT) + 20)
            y = rnd.uniform(ty - fm.ascent(), ty + 2)
            col = rnd.choice(((120, 55, 18), (80, 36, 10), (170, 90, 40), (150, 140, 120)))
            p.setBrush(QtGui.QColor(*col, rnd.randint(110, 230)))
            p.drawEllipse(QtCore.QPointF(x, y), rnd.uniform(0.5, 2.6), rnd.uniform(0.4, 1.6))
        lg = QtGui.QLinearGradient(0, ty - fm.ascent(), 0, ty)  # salissure
        lg.setColorAt(0, QtGui.QColor(60, 30, 10, 0))
        lg.setColorAt(1, QtGui.QColor(90, 45, 15, 90))
        p.setBrush(lg)
        p.drawRect(QtCore.QRectF(0, 0, w, h))
        p.setClipping(False)
        p.end()
        self._cache = pm

    @staticmethod
    def _rivet(p, c):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 120))
        p.drawEllipse(c + QtCore.QPointF(1, 1.5), 5, 5)
        g = QtGui.QRadialGradient(c - QtCore.QPointF(1.6, 1.8), 6)
        g.setColorAt(0, QtGui.QColor("#d8d2c2"))
        g.setColorAt(0.5, QtGui.QColor("#8c8574"))
        g.setColorAt(1, QtGui.QColor("#3e3a31"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#26231d"), 0.8))
        p.drawEllipse(c, 4.6, 4.6)

    def paintEvent(self, _):
        if self._cache is None or self._cache.width() != self.width():
            self._paint_plate()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.drawPixmap(0, 0, self._cache)
        for name, c in self._buttons():
            hot = name == self._hover
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 130))
            p.drawEllipse(c + QtCore.QPointF(1, 2), 11, 11)
            g = QtGui.QRadialGradient(c - QtCore.QPointF(4, 4), 16)
            if name == "close":
                g.setColorAt(0, QtGui.QColor("#f4a07a" if hot else "#d8806a"))
                g.setColorAt(1, QtGui.QColor("#6e1f12"))
            else:
                g.setColorAt(0, QtGui.QColor("#ffe9a8" if hot else "#e9cd84"))
                g.setColorAt(1, QtGui.QColor("#6b4c18"))
            p.setBrush(g)
            p.setPen(QtGui.QPen(QtGui.QColor("#1e160a"), 1))
            p.drawEllipse(c, 10, 10)
            p.setPen(QtGui.QPen(QtGui.QColor("#1e160a"), 2, cap=QtCore.Qt.RoundCap))
            if name == "close":
                d = 4
                p.drawLine(c + QtCore.QPointF(-d, -d), c + QtCore.QPointF(d, d))
                p.drawLine(c + QtCore.QPointF(-d, d), c + QtCore.QPointF(d, -d))
            elif name == "max":
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRect(QtCore.QRectF(c.x() - 4, c.y() - 4, 8, 8))
            else:
                p.drawLine(c + QtCore.QPointF(-4, 3), c + QtCore.QPointF(4, 3))
        p.end()
