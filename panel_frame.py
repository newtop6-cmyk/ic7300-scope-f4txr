"""Cadre gris métallisé pailleté, angles arrondis, en relief marqué : ombre
portée, biseau épais (clair en haut, sombre en bas), fond creusé où se posent
les boutons."""

import random

from PyQt5 import QtCore, QtGui, QtWidgets

MARGIN = 12                     # place du biseau autour des boutons
RADIUS = 13


class PanelFrame(QtWidgets.QFrame):
    def __init__(self, layout):
        super().__init__()
        self.setLayout(layout)
        layout.setContentsMargins(MARGIN + 2, MARGIN - 1, MARGIN + 2, MARGIN + 1)
        self._sparkles = []
        self._size = None

    def _make_sparkles(self):
        """Paillettes fixes (même tirage à chaque fois pour une taille donnée)."""
        w, h = self.width(), self.height()
        rnd = random.Random(w * 7919 + h)
        count = int(w * h / 45)
        self._sparkles = [(rnd.uniform(3, w - 3), rnd.uniform(3, h - 3),
                           rnd.choice((0.6, 0.8, 1.0, 1.3)), rnd.randint(40, 200),
                           rnd.random() < 0.5) for _ in range(count)]
        self._size = (w, h)

    def paintEvent(self, event):
        if self._size != (self.width(), self.height()):
            self._make_sparkles()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QtCore.Qt.NoPen)
        # ombre portée sous le cadre
        for i, alpha in enumerate((60, 40, 22)):
            p.setBrush(QtGui.QColor(0, 0, 0, alpha))
            p.drawRoundedRect(QtCore.QRectF(2 + i, 4 + i, w - 4 - i, h - 4 - i),
                              RADIUS, RADIUS)
        outer = QtCore.QRectF(0, 0, w - 4, h - 5)
        # biseau extérieur : arête claire en haut à gauche, sombre en bas à droite
        bevel = QtGui.QLinearGradient(0, 0, w * 0.15, h)
        bevel.setColorAt(0, QtGui.QColor("#ffffff"))
        bevel.setColorAt(0.35, QtGui.QColor("#c8c8c8"))
        bevel.setColorAt(1, QtGui.QColor("#3a3a3a"))
        p.setBrush(bevel)
        p.drawRoundedRect(outer, RADIUS, RADIUS)
        # corps gris métallisé dégradé
        body = outer.adjusted(3, 3, -3, -3)
        metal = QtGui.QLinearGradient(0, body.top(), 0, body.bottom())
        metal.setColorAt(0, QtGui.QColor("#e2e2e2"))
        metal.setColorAt(0.25, QtGui.QColor("#b9b9b9"))
        metal.setColorAt(0.55, QtGui.QColor("#8f8f8f"))
        metal.setColorAt(0.8, QtGui.QColor("#a9a9a9"))
        metal.setColorAt(1, QtGui.QColor("#6c6c6c"))
        p.setBrush(metal)
        p.drawRoundedRect(body, RADIUS - 2, RADIUS - 2)
        # paillettes
        for x, y, r, alpha, light in self._sparkles:
            c = QtGui.QColor(255, 255, 255, alpha) if light else QtGui.QColor(40, 40, 40, alpha // 2)
            p.setBrush(c)
            p.drawEllipse(QtCore.QPointF(x, y), r, r)
        # quelques éclats plus brillants (en croix)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 210), 0.8))
        for x, y, r, alpha, light in self._sparkles[::37]:
            p.drawLine(QtCore.QPointF(x - 2.5, y), QtCore.QPointF(x + 2.5, y))
            p.drawLine(QtCore.QPointF(x, y - 2.5), QtCore.QPointF(x, y + 2.5))
        p.setPen(QtCore.Qt.NoPen)
        # fond creusé : rainure sombre en haut, claire en bas (profondeur)
        well = outer.adjusted(MARGIN - 7, MARGIN - 7, -(MARGIN - 9), -(MARGIN - 8))
        groove = QtGui.QLinearGradient(0, well.top(), 0, well.bottom())
        groove.setColorAt(0, QtGui.QColor("#0c0c0c"))
        groove.setColorAt(0.5, QtGui.QColor("#2a2a2a"))
        groove.setColorAt(1, QtGui.QColor("#f2f2f2"))
        p.setBrush(groove)
        p.drawRoundedRect(well, RADIUS - 5, RADIUS - 5)
        inner = well.adjusted(2, 2, -2, -2)
        floor = QtGui.QLinearGradient(0, inner.top(), 0, inner.bottom())
        floor.setColorAt(0, QtGui.QColor("#15181c"))
        floor.setColorAt(1, QtGui.QColor("#2b3036"))
        p.setBrush(floor)
        p.drawRoundedRect(inner, RADIUS - 6, RADIUS - 6)
        # ombre intérieure en haut du creux
        shade = QtGui.QLinearGradient(0, inner.top(), 0, inner.top() + 10)
        shade.setColorAt(0, QtGui.QColor(0, 0, 0, 170))
        shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawRoundedRect(inner, RADIUS - 6, RADIUS - 6)
        p.end()
