"""Cadre en argent brossé, angles arrondis, avec son titre gravé sur une
plaquette en haut à gauche (famille de réglages : « RÉGLAGES AUDIO »)."""

from PyQt5 import QtCore, QtGui, QtWidgets

BORDER = 7                      # épaisseur du liseré d'argent
RADIUS = 14
TITLE_H = 16                    # hauteur de la plaquette de titre


class SilverFrame(QtWidgets.QFrame):
    def __init__(self, layout, title=""):
        super().__init__()
        self.title = title
        self.setLayout(layout)
        layout.setContentsMargins(BORDER + 6, TITLE_H + 2, BORDER + 6, BORDER + 3)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        top = TITLE_H / 2
        outer = QtCore.QRectF(1, top, w - 2, h - top - 1)
        # ombre portée
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 70))
        p.drawRoundedRect(outer.translated(2, 3), RADIUS, RADIUS)
        # argent brossé : dégradé clair en haut à gauche, sombre en bas à droite
        g = QtGui.QLinearGradient(0, top, w * 0.3, h)
        g.setColorAt(0.0, QtGui.QColor("#f4f4f2"))
        g.setColorAt(0.35, QtGui.QColor("#c3c5c4"))
        g.setColorAt(0.65, QtGui.QColor("#e2e3e1"))
        g.setColorAt(1.0, QtGui.QColor("#8b8d8e"))
        path = QtGui.QPainterPath()
        path.addRoundedRect(outer, RADIUS, RADIUS)
        inner = outer.adjusted(BORDER, BORDER, -BORDER, -BORDER)
        hole = QtGui.QPainterPath()
        hole.addRoundedRect(inner, RADIUS - 4, RADIUS - 4)
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#4a4c4e"), 1.2))
        p.drawPath(path.subtracted(hole))
        # fines rayures de brossage
        p.save()
        p.setClipPath(path.subtracted(hole))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 45), 1))
        for y in range(int(top), h, 2):
            p.drawLine(0, y, w, y)
        p.restore()
        # fond creusé (biseau sombre en haut, clair en bas)
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.setPen(QtGui.QPen(QtGui.QColor("#2a2b2c"), 1.5))
        p.drawRoundedRect(inner, RADIUS - 4, RADIUS - 4)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 60), 1))
        p.drawLine(QtCore.QPointF(inner.left() + 8, inner.bottom() + 0.5),
                   QtCore.QPointF(inner.right() - 8, inner.bottom() + 0.5))
        # plaquette de titre gravée
        if self.title:
            font = QtGui.QFont("Sans", 8, QtGui.QFont.Bold)
            font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.5)
            p.setFont(font)
            tw = QtGui.QFontMetrics(font).horizontalAdvance(self.title) + 22
            plate = QtCore.QRectF(RADIUS + 6, 0, tw, TITLE_H)
            pg = QtGui.QLinearGradient(0, 0, 0, TITLE_H)
            pg.setColorAt(0, QtGui.QColor("#fbfbfa"))
            pg.setColorAt(1, QtGui.QColor("#a9abab"))
            p.setBrush(pg)
            p.setPen(QtGui.QPen(QtGui.QColor("#3b3d3f"), 1))
            p.drawRoundedRect(plate, 4, 4)
            p.setPen(QtGui.QColor(255, 255, 255, 170))          # gravure : reflet
            p.drawText(plate.translated(0, 1), QtCore.Qt.AlignCenter, self.title)
            p.setPen(QtGui.QColor("#202224"))
            p.drawText(plate, QtCore.Qt.AlignCenter, self.title)
