"""Lucarne rétroéclairée vintage : ombre portée, cadre chromé aux bords
arrondis en relief (lumière en haut à gauche), vitre creusée, texte ambre
qui luit, reflet du verre. S'utilise comme un QLabel (setText / text)."""

from PyQt5 import QtCore, QtGui, QtWidgets


class BacklitWindow(QtWidgets.QLabel):
    def __init__(self, width=210, height=40, point_px=21):
        super().__init__()
        self.setFixedSize(width, height)
        self.point_px = point_px

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rad = h * 0.32
        outer = QtCore.QRectF(1, 1, w - 4, h - 4)
        # ombre portée sur la façade
        for i in range(4, 0, -1):
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 30))
            p.drawRoundedRect(outer.translated(i * 0.5, i * 0.6), rad, rad)
        # cadre chromé bombé
        g = QtGui.QLinearGradient(outer.topLeft(), outer.bottomRight())
        for stop, col in ((0, "#ffffff"), (0.18, "#c9ccc7"), (0.5, "#7d817b"),
                          (0.82, "#d3d6d1"), (1, "#3e413d")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1a1b19"), 1))
        p.drawRoundedRect(outer, rad, rad)
        # biseau : arête claire en haut-gauche, sombre en bas-droite
        bevel = outer.adjusted(1.5, 1.5, -1.5, -1.5)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 150), 1))
        p.drawRoundedRect(bevel, rad - 1, rad - 1)
        # vitre creusée (ombre intérieure en haut)
        glass = outer.adjusted(5, 5, -5, -5)
        grad = rad * 0.7
        bg = QtGui.QLinearGradient(0, glass.top(), 0, glass.bottom())
        bg.setColorAt(0, QtGui.QColor("#0c0601"))
        bg.setColorAt(0.25, QtGui.QColor("#2a1705"))
        bg.setColorAt(0.6, QtGui.QColor("#3a2108"))
        bg.setColorAt(1, QtGui.QColor("#1a0d02"))
        p.setBrush(bg)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.2))
        p.drawRoundedRect(glass, grad, grad)
        # lueur du rétroéclairage au centre
        glow = QtGui.QRadialGradient(glass.center(), glass.width() * 0.55)
        glow.setColorAt(0, QtGui.QColor(255, 140, 20, 70))
        glow.setColorAt(1, QtGui.QColor(255, 140, 20, 0))
        p.setBrush(glow)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(glass, grad, grad)
        # texte ambre : halo puis chiffres
        f = QtGui.QFont("DejaVu Sans Condensed")
        f.setPixelSize(self.point_px)
        f.setWeight(QtGui.QFont.Black)
        p.setFont(f)
        txt = self.text()
        p.setPen(QtGui.QColor(255, 150, 30, 70))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawText(glass.translated(dx * 1.5, dy * 1.5), QtCore.Qt.AlignCenter, txt)
        p.setPen(QtGui.QColor("#ffbf47"))
        p.drawText(glass, QtCore.Qt.AlignCenter, txt)
        # reflet du verre (moitié haute)
        p.save()
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(glass, grad, grad)
        p.setClipPath(clip)
        gl = QtGui.QLinearGradient(0, glass.top(), 0, glass.center().y())
        gl.setColorAt(0, QtGui.QColor(255, 255, 255, 55))
        gl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.fillRect(QtCore.QRectF(glass.left(), glass.top(), glass.width(), glass.height() / 2), gl)
        p.restore()
        p.end()
