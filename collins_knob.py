"""Dessin d'un gros bouton d'accord façon Collins KWM-2 : bakélite noire
brillante, jupe conique cannelée, dessus légèrement bombé avec reflet,
creux pour le doigt (« spinner ») décentré qui tourne avec le bouton,
ombre portée sur la façade. paint_collins_knob(p, rect, angle, hooked)."""

import math

from PyQt5 import QtCore, QtGui


def paint_collins_knob(p, rect, angle, hooked=False):
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    c = QtCore.QPointF(rect.center())
    R = min(rect.width(), rect.height()) / 2 - 10
    # ombre portée sur la façade (lumière en haut à gauche)
    for i in range(16, 0, -1):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 14))
        p.drawEllipse(c + QtCore.QPointF(i * 0.45, i * 0.75), R + i * 0.35, R + i * 0.35)
    # anneau d'accrochage (VFO tenu à la souris) : lueur ambre discrète
    if hooked:
        glow = QtGui.QRadialGradient(c, R + 9)
        glow.setColorAt(0.85, QtGui.QColor(255, 190, 90, 0))
        glow.setColorAt(0.93, QtGui.QColor(255, 190, 90, 150))
        glow.setColorAt(1, QtGui.QColor(255, 190, 90, 0))
        p.setBrush(glow)
        p.drawEllipse(c, R + 9, R + 9)
    # jupe conique : bakélite noire, reflets latéraux
    skirt = QtGui.QConicalGradient(c, 120)
    for stop, col in ((0, "#3c3c3c"), (0.12, "#101010"), (0.3, "#1e1e1e"),
                      (0.5, "#050505"), (0.62, "#2a2a2a"), (0.8, "#070707"), (1, "#3c3c3c")):
        skirt.setColorAt(stop, QtGui.QColor(col))
    p.setBrush(skirt)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.2))
    p.drawEllipse(c, R, R)
    # cannelures de la jupe : tournent avec le bouton
    top_r = R * 0.80
    for i in range(90):
        a = math.radians(angle + i * 4)
        d = QtCore.QPointF(math.cos(a), math.sin(a))
        light = 0.5 + 0.5 * math.cos(a - math.radians(-135))      # face éclairée
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, int(18 + 70 * light ** 3)), 1.3))
        p.drawLine(c + d * (top_r + 3), c + d * (R - 1.5))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 1.0))
        d2 = QtCore.QPointF(math.cos(a + math.radians(2)), math.sin(a + math.radians(2)))
        p.drawLine(c + d2 * (top_r + 3), c + d2 * (R - 1.5))
    # arête vive entre la jupe et le dessus
    edge = QtGui.QLinearGradient(c - QtCore.QPointF(top_r, top_r), c + QtCore.QPointF(top_r, top_r))
    edge.setColorAt(0, QtGui.QColor(200, 200, 200))
    edge.setColorAt(0.5, QtGui.QColor(40, 40, 40))
    edge.setColorAt(1, QtGui.QColor(0, 0, 0))
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QBrush(edge), 2.4))
    p.drawEllipse(c, top_r + 1.5, top_r + 1.5)
    # dessus bombé, noir profond
    face = QtGui.QRadialGradient(c - QtCore.QPointF(top_r * 0.35, top_r * 0.4), top_r * 1.5)
    face.setColorAt(0, QtGui.QColor("#3a3a3a"))
    face.setColorAt(0.35, QtGui.QColor("#161616"))
    face.setColorAt(1, QtGui.QColor("#020202"))
    p.setBrush(face)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
    p.drawEllipse(c, top_r, top_r)
    # creux pour le doigt, décentré, tourne avec le bouton
    a = math.radians(angle - 90)
    dc = c + QtCore.QPointF(math.cos(a), math.sin(a)) * top_r * 0.58
    dr = top_r * 0.2
    hollow = QtGui.QRadialGradient(dc + QtCore.QPointF(dr * 0.35, dr * 0.45), dr * 1.25)
    hollow.setColorAt(0, QtGui.QColor("#4a4a4a"))       # fond du creux éclairé en bas à droite
    hollow.setColorAt(0.55, QtGui.QColor("#121212"))
    hollow.setColorAt(1, QtGui.QColor("#000000"))
    p.setBrush(hollow)
    p.setPen(QtCore.Qt.NoPen)
    p.drawEllipse(dc, dr, dr)
    lip = QtGui.QLinearGradient(dc - QtCore.QPointF(dr, dr), dc + QtCore.QPointF(dr, dr))
    lip.setColorAt(0, QtGui.QColor(0, 0, 0, 230))          # bord haut-gauche dans l'ombre
    lip.setColorAt(0.5, QtGui.QColor(60, 60, 60, 120))
    lip.setColorAt(1, QtGui.QColor(230, 230, 230, 200))    # bord bas-droit qui accroche la lumière
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QBrush(lip), 1.8))
    p.drawEllipse(dc, dr, dr)
    # reflet brillant doux (la lampe du shack sur la bakélite)
    gc = c - QtCore.QPointF(top_r * 0.42, top_r * 0.48)
    gloss = QtGui.QRadialGradient(gc, top_r * 0.75)
    gloss.setColorAt(0, QtGui.QColor(255, 255, 255, 70))
    gloss.setColorAt(0.5, QtGui.QColor(255, 255, 255, 22))
    gloss.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    clip = QtGui.QPainterPath()
    clip.addEllipse(c, top_r - 1, top_r - 1)
    p.setClipPath(clip)
    p.setBrush(gloss)
    p.setPen(QtCore.Qt.NoPen)
    p.drawEllipse(gc, top_r * 0.75, top_r * 0.75)
    # liseré de lumière sur le bord bombé, en haut à gauche
    rim = QtGui.QConicalGradient(c, 135)
    rim.setColorAt(0, QtGui.QColor(255, 255, 255, 120))
    rim.setColorAt(0.18, QtGui.QColor(255, 255, 255, 0))
    rim.setColorAt(0.82, QtGui.QColor(255, 255, 255, 0))
    rim.setColorAt(1, QtGui.QColor(255, 255, 255, 120))
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QBrush(rim), 3))
    p.drawEllipse(c, top_r - 3, top_r - 3)
    p.setClipping(False)
    # petit point de lumière vive
    spot = QtGui.QRadialGradient(c - QtCore.QPointF(top_r * 0.45, top_r * 0.5), top_r * 0.14)
    spot.setColorAt(0, QtGui.QColor(255, 255, 255, 170))
    spot.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(spot)
    p.drawEllipse(c - QtCore.QPointF(top_r * 0.45, top_r * 0.5), top_r * 0.14, top_r * 0.14)
    # reflet bas de la jupe (lumière renvoyée par la façade)
    low = QtGui.QRadialGradient(c + QtCore.QPointF(R * 0.3, R * 0.85), R * 0.45)
    low.setColorAt(0, QtGui.QColor(160, 170, 160, 45))
    low.setColorAt(1, QtGui.QColor(160, 170, 160, 0))
    p.setBrush(low)
    ring = QtGui.QPainterPath()
    ring.addEllipse(c, R, R)
    inner = QtGui.QPainterPath()
    inner.addEllipse(c, top_r + 2, top_r + 2)
    p.drawPath(ring.subtracted(inner))
    p.restore()
