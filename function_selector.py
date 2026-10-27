"""Sélecteur rotatif « FONCTION » vintage : bouton bakélite à bec (pointeur)
sur platine sombre, positions gravées en arc au-dessus. Les positions sans
nom (« · ») sont réservées aux fonctions à venir et ne sont pas sélectionnables.
Clic sur une position = y aller ; clic sur le bouton ou molette = cran suivant."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets

ANGLES = (-64, -32, 0, 32, 64)          # degrés depuis la verticale


class FunctionSelector(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal(str)

    def __init__(self, positions=("OFF", "ZOOM", "", "", ""), scale=1.0):
        super().__init__()
        self.k = scale                  # échelle : dessin et clics prévus pour 150 × 172
        self.positions = list(positions)
        self.index = 0
        self.shown = float(ANGLES[0])   # angle affiché (animation du cran)
        self.setFixedSize(round(150 * scale), round(172 * scale))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Sélecteur de fonction : clic sur une position, "
                        "ou molette / clic sur le bouton pour changer de cran")
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._wheel = 0
        self.alerts = set()             # positions signalées (voyant rouge clignotant)
        self.flash = True               # voyant bleu au-dessus de la position choisie
        self.flash_timer = QtCore.QTimer(self)
        self.flash_timer.timeout.connect(self._flash)
        self.flash_timer.start(180)

    @property
    def center(self):
        return QtCore.QPointF(75, 100)          # coordonnées du dessin (avant échelle)

    def current(self):
        return self.positions[self.index]

    def _usable(self):
        return [i for i, name in enumerate(self.positions) if name]

    def set_index(self, index, emit=True):
        if not self.positions[index]:
            return
        if index == self.index:
            self.timer.start(16)                # revient se poser en douceur sur son cran
            return
        self.index = index
        self.timer.start(16)
        if emit:
            self.changed.emit(self.positions[index])

    def _step(self, direction):
        usable = self._usable()
        k = usable.index(self.index) if self.index in usable else 0
        self.set_index(usable[(k + direction) % len(usable)])

    def set_alert(self, name, on):
        """Voyant rouge clignotant au-dessus d'une position (ex. SSTV détectée),
        même si elle n'est pas choisie : invitation à y passer."""
        if name in self.positions:
            (self.alerts.add if on else self.alerts.discard)(self.positions.index(name))
            self.update()

    def _flash(self):
        self.flash = not self.flash
        self.update()

    def _tick(self):
        if getattr(self, "_drag", None):
            return                              # la souris tient le bouton
        goal = ANGLES[self.index]
        self.shown += (goal - self.shown) * 0.2  # ralenti en fin de course : pose douce
        if abs(goal - self.shown) < 0.2:
            self.shown = goal
            self.timer.stop()
        self.update()

    def _angle_at(self, pos):
        d = QtCore.QPointF(pos) - self.center
        return max(ANGLES[0] - 6, min(ANGLES[-1] + 6, math.degrees(math.atan2(d.x(), -d.y()))))

    def _lp(self, event):
        return QtCore.QPointF(event.pos()) / self.k

    def mousePressEvent(self, event):
        pos = self._lp(event)
        for i, a in enumerate(ANGLES):          # clic près d'une inscription
            if (pos - self._label_pos(a)).manhattanLength() < 22 and self.positions[i]:
                self.set_index(i)
                return
        # sur le bouton : on peut le tourner en glissant (doux) ; simple clic = cran suivant
        self._drag = {"start": self._lp(event), "moved": False}
        self.timer.stop()

    def mouseMoveEvent(self, event):
        drag = getattr(self, "_drag", None)
        if not drag:
            return
        if (self._lp(event) - drag["start"]).manhattanLength() > 4:
            drag["moved"] = True
        if drag["moved"]:
            self.shown = self._angle_at(self._lp(event))   # le bec suit la souris
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        drag = getattr(self, "_drag", None)
        self._drag = None
        self.setCursor(QtCore.Qt.PointingHandCursor)
        if not drag:
            return
        if not drag["moved"]:
            self._step(1)                       # simple clic : cran suivant (comme avant)
            return
        # lâché : le cran utilisable le plus proche de l'angle atteint
        best = min(self._usable(), key=lambda i: abs(ANGLES[i] - self.shown))
        self.set_index(best)

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y()
        if abs(self._wheel) >= 120:
            self._step(1 if self._wheel > 0 else -1)
            self._wheel = 0
        event.accept()

    def _dir(self, a):
        r = math.radians(a)
        return QtCore.QPointF(math.sin(r), -math.cos(r))

    def _label_pos(self, a):
        return self.center + self._dir(a) * (70 if abs(a) < 10 else 62)   # pas de chevauchement

    def _blue_led(self, p, c, red=False):
        if self.flash:                              # éclat : halo
            g = QtGui.QRadialGradient(c, 11)
            if red:
                g.setColorAt(0, QtGui.QColor(255, 140, 120, 240))
                g.setColorAt(0.4, QtGui.QColor(255, 40, 20, 170))
                g.setColorAt(1, QtGui.QColor(255, 0, 0, 0))
            else:
                g.setColorAt(0, QtGui.QColor(120, 200, 255, 230))
                g.setColorAt(0.4, QtGui.QColor(40, 140, 255, 150))
                g.setColorAt(1, QtGui.QColor(30, 110, 255, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(c, 11, 11)
        g = QtGui.QConicalGradient(c, 135)          # bague chromée
        for stop, col in ((0, "#ffffff"), (0.25, "#777c82"), (0.5, "#e6e8ea"),
                          (0.75, "#585d63"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#16181a"), 0.6))
        p.drawEllipse(c, 4.6, 4.6)
        g = QtGui.QRadialGradient(c - QtCore.QPointF(1, 1), 4)
        if self.flash:
            g.setColorAt(0, QtGui.QColor("#ffffff"))
            g.setColorAt(0.4, QtGui.QColor("#ff9a8a" if red else "#9fd4ff"))
            g.setColorAt(1, QtGui.QColor("#d01000" if red else "#1e6bff"))
        else:
            g.setColorAt(0, QtGui.QColor("#502a24" if red else "#2a3550"))
            g.setColorAt(1, QtGui.QColor("#0c0505" if red else "#05070c"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 0.5))
        p.drawEllipse(c, 3, 3)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(self.k, self.k)
        w, h = 150, 172                         # dessin prévu à cette taille
        c = self.center
        # platine sombre en tôle peinte, bord biseauté, 2 vis
        plate = QtCore.QRectF(2, 2, w - 4, h - 4)
        g = QtGui.QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QtGui.QColor("#fbf3d9"))
        g.setColorAt(0.6, QtGui.QColor("#efe2bb"))
        g.setColorAt(1, QtGui.QColor("#d6c592"))
        p.setPen(QtGui.QPen(QtGui.QColor("#3a2c12"), 2))
        p.setBrush(g)
        p.drawRoundedRect(plate, 10, 10)
        p.setPen(QtGui.QPen(QtGui.QColor(120, 90, 40, 120), 1.2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(plate.adjusted(2, 2, -2, -2), 8, 8)
        for sx in (14, w - 14):
            sc = QtCore.QPointF(sx, h - 14)
            sg = QtGui.QRadialGradient(sc - QtCore.QPointF(1, 1), 5)
            sg.setColorAt(0, QtGui.QColor("#e8e8e8"))
            sg.setColorAt(1, QtGui.QColor("#555"))
            p.setPen(QtGui.QPen(QtGui.QColor("#222"), 0.8))
            p.setBrush(sg)
            p.drawEllipse(sc, 3.6, 3.6)
            p.drawLine(sc + QtCore.QPointF(-2.4, 1), sc + QtCore.QPointF(2.4, -1))
        # titre gravé
        p.setFont(QtGui.QFont("URW Gothic", 8, QtGui.QFont.Black))
        p.setPen(QtGui.QColor("#1e1609"))
        p.drawText(QtCore.QRectF(0, h - 27, w, 16), QtCore.Qt.AlignCenter, "FONCTION")
        # voyant ambre : allumé quand une fonction est enclenchée
        lit = self.index != 0
        lc = QtCore.QPointF(w - 22, 20)
        if lit:
            hg = QtGui.QRadialGradient(lc, 16)
            hg.setColorAt(0, QtGui.QColor(255, 160, 30, 200))
            hg.setColorAt(1, QtGui.QColor(255, 120, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(hg)
            p.drawEllipse(lc, 16, 16)
        rg = QtGui.QConicalGradient(lc, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#777c82"), (0.5, "#e6e8ea"),
                          (0.75, "#585d63"), (1, "#ffffff")):
            rg.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(rg)
        p.setPen(QtGui.QPen(QtGui.QColor("#16181a"), 0.8))
        p.drawEllipse(lc, 7, 7)
        lg = QtGui.QRadialGradient(lc - QtCore.QPointF(1.5, 1.5), 6)
        lg.setColorAt(0, QtGui.QColor("#fff6d0" if lit else "#7a5a32"))
        lg.setColorAt(1, QtGui.QColor("#e07000" if lit else "#201508"))
        p.setBrush(lg)
        p.drawEllipse(lc, 4.6, 4.6)
        # arc gravé et crans
        arc_r = 44
        p.setPen(QtGui.QPen(QtGui.QColor("#1e1609"), 1.4))
        rect = QtCore.QRectF(c.x() - arc_r, c.y() - arc_r, 2 * arc_r, 2 * arc_r)
        p.drawArc(rect, int((90 - ANGLES[-1]) * 16), int((ANGLES[-1] - ANGLES[0]) * 16))
        for i, a in enumerate(ANGLES):
            u = self._dir(a)
            sel = i == self.index
            p.setPen(QtGui.QPen(QtGui.QColor("#c62828" if sel else "#1e1609"), 2.6 if sel else 1.6))
            p.drawLine(c + u * (arc_r - 2), c + u * (arc_r + 6))
            name = self.positions[i]
            lp = self._label_pos(a)
            if name:
                p.setFont(QtGui.QFont("URW Gothic", 9, QtGui.QFont.Black))
                p.setPen(QtGui.QColor("#c62828" if sel else "#1e1609"))
                p.drawText(QtCore.QRectF(lp.x() - 30, lp.y() - 9, 60, 18),
                           QtCore.Qt.AlignCenter, name)
                if sel:                             # voyant bleu à ras, au-dessus
                    self._blue_led(p, lp + QtCore.QPointF(0, -12))
                elif i in self.alerts:              # voyant rouge : « venez ici »
                    self._blue_led(p, lp + QtCore.QPointF(0, -12), red=True)
            else:                                   # position réservée
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QColor(30, 22, 9, 150))
                p.drawEllipse(lp, 2.4, 2.4)
        # ombre du bouton
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 120))
        p.drawEllipse(c + QtCore.QPointF(2, 4), 30, 30)
        # jupe ronde bakélite
        g = QtGui.QRadialGradient(c - QtCore.QPointF(10, 12), 46)
        g.setColorAt(0, QtGui.QColor("#4c4744"))
        g.setColorAt(0.5, QtGui.QColor("#191614"))
        g.setColorAt(1, QtGui.QColor("#030303"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawEllipse(c, 29, 29)
        # bec (pointeur) bakélite, tourné vers la position
        p.save()
        p.translate(c)
        p.rotate(self.shown)
        beak = QtGui.QPainterPath()
        beak.moveTo(0, -40)
        beak.cubicTo(7, -32, 13, -10, 13, 14)
        beak.cubicTo(13, 24, -13, 24, -13, 14)
        beak.cubicTo(-13, -10, -7, -32, 0, -40)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 110))
        p.drawPath(beak.translated(2, 3))
        g = QtGui.QLinearGradient(-13, 0, 13, 0)
        g.setColorAt(0, QtGui.QColor("#4a4542"))
        g.setColorAt(0.35, QtGui.QColor("#24201e"))
        g.setColorAt(1, QtGui.QColor("#050505"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawPath(beak)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 70), 1.2))     # reflet
        p.drawLine(QtCore.QPointF(-6, -14), QtCore.QPointF(-2, -32))
        p.setPen(QtGui.QPen(QtGui.QColor("#f4efe0"), 2.2, cap=QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(0, -36), QtCore.QPointF(0, -18))     # repère blanc
        p.restore()
        p.end()
