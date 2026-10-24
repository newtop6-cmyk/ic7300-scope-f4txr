"""Touches de bande façon poste à lampes des années 50 (Grundig, Telefunken) :
baguette de laiton derrière la rangée, touches en ivoire jauni et patiné
vues un peu de dessus (dessus + face avant, comme des touches de piano), nom
gravé en Bookman, et sous chaque touche un voyant en verre taillé à facettes
serti dans une bague chromée moletée, allumé en ambre sur la bande choisie."""

import math
import random

from PyQt5 import QtCore, QtGui, QtWidgets

TOP_H = 19                      # dessus de la touche
FRONT_H = 5                     # face avant visible (touche relâchée)
LAMP_R = 5.5                    # rayon de la bague du voyant
LAMP_GAP = 2                    # entre la baguette et le voyant
HEIGHT = int(4 + TOP_H + FRONT_H + 4 + LAMP_GAP + 2 * LAMP_R + 2)


class BandKey(QtWidgets.QAbstractButton):
    def __init__(self, text):
        super().__init__()
        self.setText(text)
        self.setCheckable(True)
        self.setMinimumWidth(54)
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._hover = False
        rnd = random.Random(hash(text) & 0xffff)  # patine propre à chaque touche
        self._specks = [(rnd.random(), rnd.random(), rnd.uniform(0.4, 1.1),
                         rnd.randint(18, 45)) for _ in range(14)]
        self._tone = rnd.uniform(-6, 6)           # jaunissement un peu inégal

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QtCore.QSize(64, HEIGHT)

    # --- dessin ----------------------------------------------------------
    def _ivory(self, base, extra=0):
        c = QtGui.QColor(base)
        h, s, v, a = c.getHsv()
        return QtGui.QColor.fromHsv(h, max(0, min(255, s + int(self._tone))),
                                    max(0, min(255, v + extra)), a)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w = self.width()
        on = self.isChecked()
        down = self.isDown()
        push = 1.0 if down else 0.75 if on else 0.0   # enfoncement (0 = relâchée)

        # baguette de laiton brossé derrière les touches (raccord d'une touche à l'autre)
        strip = QtCore.QRectF(0, 0, w, 4 + TOP_H + FRONT_H + 4)
        g = QtGui.QLinearGradient(strip.topLeft(), strip.bottomLeft())
        g.setColorAt(0, QtGui.QColor("#f3dc9a"))
        g.setColorAt(0.12, QtGui.QColor("#b38b3e"))
        g.setColorAt(0.5, QtGui.QColor("#7d5f26"))
        g.setColorAt(0.88, QtGui.QColor("#b38b3e"))
        g.setColorAt(1, QtGui.QColor("#e5c77c"))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawRect(strip)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 240, 200, 25), 1))
        for y in range(3, int(strip.height()) - 2, 2):            # brossage
            p.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(w, y))

        # lumière de la fente (logement de la touche)
        x0, x1 = 4, w - 4
        slot = QtCore.QRectF(x0 - 1, 3, x1 - x0 + 2, TOP_H + FRONT_H + 3)
        p.setPen(QtGui.QPen(QtGui.QColor("#3a2a0c"), 1))
        p.setBrush(QtGui.QColor("#140e05"))
        p.drawRoundedRect(slot, 3, 3)

        # touche : le dessus recule, la face avant raccourcit quand on l'enfonce
        front_h = FRONT_H * (1 - 0.7 * push)
        top_y = 4 + 2 * push
        top_rect = QtCore.QRectF(x0, top_y, x1 - x0, TOP_H)
        front = QtCore.QRectF(x0, top_y + TOP_H - 2, x1 - x0, front_h + 2)
        # face avant (plus sombre, éclairée par le bas d'ambiance)
        g = QtGui.QLinearGradient(front.topLeft(), front.bottomLeft())
        g.setColorAt(0, self._ivory("#d9c79a", -10 if on else 0))
        g.setColorAt(1, self._ivory("#9e8a5c", -10 if on else 0))
        p.setPen(QtGui.QPen(QtGui.QColor("#4a3a18"), 1))
        p.setBrush(g)
        p.drawRoundedRect(front, 3, 3)
        # dessus : ivoire jauni, légèrement bombé
        light = 10 if self._hover and not on else 0
        g = QtGui.QLinearGradient(top_rect.topLeft(), top_rect.bottomLeft())
        g.setColorAt(0, self._ivory("#f7ecc8", light - (14 if on else 0)))
        g.setColorAt(0.55, self._ivory("#eadbad", light - (14 if on else 0)))
        g.setColorAt(1, self._ivory("#d8c48e", light - (14 if on else 0)))
        p.setBrush(g)
        p.drawRoundedRect(top_rect, 3, 3)
        # arête avant arrondie, accrochant la lumière
        p.setPen(QtGui.QPen(QtGui.QColor(255, 250, 230, 160 if not on else 90), 1.3))
        p.drawLine(QtCore.QPointF(x0 + 3, top_y + TOP_H - 2.5),
                   QtCore.QPointF(x1 - 3, top_y + TOP_H - 2.5))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 110), 1))
        p.drawLine(QtCore.QPointF(x0 + 3, top_y + 1.2), QtCore.QPointF(x1 - 3, top_y + 1.2))
        # patine : petites taches et craquelures
        p.setPen(QtCore.Qt.NoPen)
        for fx, fy, r, a in self._specks:
            p.setBrush(QtGui.QColor(110, 80, 30, a))
            p.drawEllipse(QtCore.QPointF(x0 + 3 + fx * (x1 - x0 - 6),
                                         top_y + 3 + fy * (TOP_H - 6)), r, r)
        # ombre de la baguette sur la touche enfoncée
        if push:
            g = QtGui.QLinearGradient(top_rect.topLeft(), top_rect.topLeft() + QtCore.QPointF(0, 8))
            g.setColorAt(0, QtGui.QColor(0, 0, 0, int(110 * push)))
            g.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setBrush(g)
            p.drawRect(QtCore.QRectF(x0, top_y, x1 - x0, 8))

        # nom gravé (creux rempli de noir, liseré clair dessous)
        font = QtGui.QFont("URW Bookman", 9, QtGui.QFont.Bold)
        p.setFont(font)
        label = top_rect.adjusted(0, 1, 0, 0)
        p.setPen(QtGui.QColor(255, 248, 225, 150))
        p.drawText(label.translated(0, 1), QtCore.Qt.AlignCenter, self.text())
        p.setPen(QtGui.QColor("#24190a"))
        p.drawText(label, QtCore.Qt.AlignCenter, self.text())

        # voyant : bague chromée moletée + verre taillé à facettes
        c = QtCore.QPointF(w / 2, strip.bottom() + LAMP_GAP + LAMP_R)
        if on:                                                   # halo
            g = QtGui.QRadialGradient(c, LAMP_R * 2.8)
            g.setColorAt(0, QtGui.QColor(255, 160, 30, 160))
            g.setColorAt(1, QtGui.QColor(255, 110, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(c, LAMP_R * 2.8, LAMP_R * 2.8)
        g = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#777c82"), (0.5, "#e6e8ea"),
                          (0.75, "#585d63"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#16181a"), 0.8))
        p.drawEllipse(c, LAMP_R, LAMP_R)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 90), 0.7))     # moletage de la bague
        for i in range(36):
            a = math.radians(i * 10)
            u = QtCore.QPointF(math.cos(a), math.sin(a))
            p.drawLine(c + u * (LAMP_R - 1.8), c + u * (LAMP_R - 0.3))
        jr = LAMP_R - 2.6
        n = 8                                                    # facettes
        pts = [c + QtCore.QPointF(math.cos(2 * math.pi * k / n + math.pi / 8),
                                  math.sin(2 * math.pi * k / n + math.pi / 8)) * jr
               for k in range(n)]
        for k in range(n):
            tri = QtGui.QPolygonF([c, pts[k], pts[(k + 1) % n]])
            shade = (math.cos(2 * math.pi * k / n - math.radians(225)) + 1) / 2
            if on:
                col = QtGui.QColor.fromHsv(34, int(230 - 120 * shade), int(200 + 55 * shade))
            else:
                col = QtGui.QColor.fromHsv(25, 200, int(50 + 60 * shade))
            p.setBrush(col)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 0.4))
            p.drawPolygon(tri)
        table = jr * 0.42                                        # table centrale
        p.setBrush(QtGui.QColor("#fff3c4") if on else QtGui.QColor("#5a3a16"))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 0.4))
        p.drawEllipse(c, table, table)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 255, 255, 200 if on else 110))
        p.drawEllipse(c - QtCore.QPointF(jr / 2.5, jr / 2.5), 1.1, 1.1)
        p.end()


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setSpacing(0)
    for i, n in enumerate(("160m", "80m", "60m", "40m", "30m", "20m")):
        k = BandKey(n)
        k.setChecked(i == 0)
        lay.addWidget(k)
    w.show()
    sys.exit(app.exec_())
