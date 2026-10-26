"""Loupe ronde qui suit le pointeur de la souris (X11).

Seule la zone sous le pointeur est grossie, dans une lentille posée à côté
de lui (jamais dessus : elle ne cache pas ce qu'on vise et ne bloque aucun
clic). Un réticule rouge marque le pixel exact visé par le pointeur.
Grossissement réglable de ×2 à ×10 (set_zoom), gardé entre deux sessions.
"""

import json
import os

from PyQt5 import QtCore, QtGui, QtWidgets

CONFIG = os.path.expanduser("~/.config/ic7300-scope/loupe.json")
SIZE = 400                  # diamètre de la lentille (px)
ZOOM_MIN, ZOOM_MAX = 2, 10


class Loupe(QtWidgets.QWidget):
    zoom_changed = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowStaysOnTopHint
                         | QtCore.Qt.X11BypassWindowManagerHint
                         | QtCore.Qt.WindowTransparentForInput)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setFixedSize(SIZE, SIZE)
        self.zoom = self._load_zoom()
        self.image = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._follow)

    # --- réglages --------------------------------------------------------
    def _load_zoom(self):
        try:
            with open(CONFIG) as f:
                return max(ZOOM_MIN, min(ZOOM_MAX, int(json.load(f)["zoom"])))
        except (OSError, ValueError, KeyError, TypeError):
            return 3

    def set_zoom(self, zoom):
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, int(zoom)))
        if zoom == self.zoom:
            return
        self.zoom = zoom
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
            with open(CONFIG, "w") as f:
                json.dump({"zoom": zoom}, f)
        except OSError:
            pass
        self.zoom_changed.emit(zoom)
        self.update()

    def start(self):
        self._follow()
        self.show()
        self.timer.start(30)            # ~33 images par seconde

    def stop(self):
        self.timer.stop()
        self.hide()

    # --- suivi du pointeur ----------------------------------------------
    def _follow(self):
        pos = QtGui.QCursor.pos()
        screen = QtWidgets.QApplication.screenAt(pos) or QtWidgets.QApplication.primaryScreen()
        geo = screen.geometry()
        src = SIZE // self.zoom                     # côté de la zone grossie
        # lentille en bas à droite du pointeur, assez loin pour ne pas
        # recouvrir la zone qu'elle grossit ; retournée près des bords
        gap = src // 2 + 24
        x, y = pos.x() + gap, pos.y() + gap
        if x + SIZE > geo.right():
            x = pos.x() - gap - SIZE
        if y + SIZE > geo.bottom():
            y = pos.y() - gap - SIZE
        self.move(x, y)
        local = pos - geo.topLeft()
        self.image = screen.grabWindow(0, local.x() - src // 2, local.y() - src // 2,
                                       src, src)
        self.update()

    def paintEvent(self, _):
        if self.image is None:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(3, 3, SIZE - 6, SIZE - 6)
        clip = QtGui.QPainterPath()
        clip.addEllipse(rect)
        p.save()
        p.setClipPath(clip)
        p.fillRect(rect, QtGui.QColor("#000"))
        # pixels nets (pas de flou) : on voit chaque pixel pour viser juste
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, False)
        p.drawPixmap(rect.toRect(), self.image)
        # réticule rouge : la case centrale = le pixel visé par le pointeur
        c = rect.center()
        half = self.zoom / 2
        pen = QtGui.QPen(QtGui.QColor(255, 30, 30, 220), 1)
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(rect.left(), c.y()), QtCore.QPointF(c.x() - half - 3, c.y()))
        p.drawLine(QtCore.QPointF(c.x() + half + 3, c.y()), QtCore.QPointF(rect.right(), c.y()))
        p.drawLine(QtCore.QPointF(c.x(), rect.top()), QtCore.QPointF(c.x(), c.y() - half - 3))
        p.drawLine(QtCore.QPointF(c.x(), c.y() + half + 3), QtCore.QPointF(c.x(), rect.bottom()))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(QtCore.QRectF(c.x() - half, c.y() - half, self.zoom, self.zoom))
        self._paint_finger(p, c, half)
        p.restore()
        # monture en laiton et grossissement
        p.setPen(QtGui.QPen(QtGui.QColor("#2a1c06"), 5))
        p.drawEllipse(rect)
        p.setPen(QtGui.QPen(QtGui.QColor("#d8b45a"), 3))
        p.drawEllipse(rect)
        badge = QtCore.QRectF(SIZE / 2 - 22, SIZE - 30, 44, 20)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 170))
        p.drawRoundedRect(badge, 6, 6)
        p.setPen(QtGui.QColor("#ffd27a"))
        p.setFont(QtGui.QFont("DejaVu Sans", 9, QtGui.QFont.Bold))
        p.drawText(badge, QtCore.Qt.AlignCenter, f"× {self.zoom}")
        p.end()


    def _paint_finger(self, p, c, half):
        """Index tendu venant d'en bas à droite : le bout touche le pixel visé."""
        p.save()
        p.translate(c)
        p.rotate(-35)                   # le doigt part vers le bas à droite
        w = 30                          # largeur du doigt
        t = half + 1                    # bout du doigt juste sous la case rouge
        body = QtGui.QPainterPath()
        body.moveTo(-w / 2, t + w / 2)
        body.arcTo(QtCore.QRectF(-w / 2, t, w, w), 180, -180)
        body.lineTo(w / 2, SIZE)
        body.lineTo(-w / 2, SIZE)
        body.closeSubpath()
        p.setPen(QtGui.QPen(QtGui.QColor("#5a3a1a"), 1.5))
        p.setBrush(QtGui.QColor(241, 194, 125, 235))
        p.drawPath(body)
        # ongle
        p.setPen(QtGui.QPen(QtGui.QColor("#a0703a"), 1))
        p.setBrush(QtGui.QColor(255, 228, 200, 240))
        p.drawRoundedRect(QtCore.QRectF(-w / 2 + 6, t + 5, w - 12, 20), 7, 7)
        # plis des articulations
        p.setPen(QtGui.QPen(QtGui.QColor("#8a5a2a"), 1.2))
        p.setBrush(QtCore.Qt.NoBrush)
        for k in (60, 66, 125, 131):
            p.drawArc(QtCore.QRectF(-w / 2 + 6, t + k, w - 12, 6), 200 * 16, 140 * 16)
        p.restore()
        # point rouge au bout du doigt = l'endroit exact du clic
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 30, 30, 240))
        p.drawEllipse(c, 2.5, 2.5)


class AltWheel(QtCore.QObject):
    """Alt + molette (dans l'application) : grossissement de la loupe."""

    def __init__(self, loupe):
        super().__init__()
        self.loupe = loupe
        self.acc = 0

    def eventFilter(self, obj, event):
        if (event.type() == QtCore.QEvent.Wheel and self.loupe.isVisible()
                and event.modifiers() & QtCore.Qt.AltModifier):
            d = event.angleDelta()
            self.acc += d.y() or d.x()          # Alt peut rendre la molette « horizontale »
            steps = int(self.acc / 120)
            if steps:
                self.acc -= steps * 120
                self.loupe.set_zoom(self.loupe.zoom + steps)
            return True
        return False


if __name__ == "__main__":                       # essai seul : python3 loupe.py
    app = QtWidgets.QApplication([])
    loupe = Loupe()
    loupe.start()
    app.exec_()
