"""Effet « ampli qui pompe sur le secteur » pour les cadrans : en émission, une
lumière part du point central exact du cadran et s'étend vers l'extérieur.
light ≈ 1 : lampe normale ; < 1 : la lampe s'écroule (cadran assombri, petit
cœur) ; > 1 : surtension (flash blanc qui envahit tout le cadran)."""

from PyQt5 import QtCore, QtGui


def paint(p, face, light):
    """face : QRectF ou QPainterPath du cadran ; light : niveau de la lampe."""
    if light is None:
        return
    path = face if isinstance(face, QtGui.QPainterPath) else _rect_path(face)
    box = path.boundingRect()
    c = box.center()
    reach = max(box.width(), box.height()) * 0.75
    p.save()
    p.setClipPath(path)
    p.setPen(QtCore.Qt.NoPen)
    # la lampe baisse : le cadran entier s'assombrit
    sag = max(0.0, 1.0 - light)
    if sag > 0:
        p.setBrush(QtGui.QColor(20, 10, 0, int(200 * sag)))
        p.drawPath(path)
    # halo depuis le centre : rayon et éclat suivent la lampe
    k = max(0.0, min(2.2, light))
    radius = reach * (0.12 + 0.55 * min(k, 1.0) + 0.45 * max(0.0, k - 1.0))
    g = QtGui.QRadialGradient(c, max(2.0, radius))
    hot = max(0.0, k - 1.0)                      # surtension : cœur blanc
    g.setColorAt(0.0, QtGui.QColor(255, 255, int(200 + 55 * min(1, hot)),
                                   min(255, int(150 * k + 160 * hot))))
    g.setColorAt(0.35, QtGui.QColor(255, 215, 120, min(255, int(105 * k + 120 * hot))))
    g.setColorAt(1.0, QtGui.QColor(255, 170, 60, 0))
    p.setBrush(g)
    p.drawEllipse(c, radius, radius)
    p.restore()


def _rect_path(rect):
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, 8, 8)
    return path
