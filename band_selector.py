"""Commutateur de bandes vintage : platine crème vissée, 12 bandes gravées en
arc (270°), gros bouton bakélite à bec en relief, voyant bleu sur la bande
choisie. Clic sur une bande = y aller ; molette = bande voisine ; glisser le
bouton = le tourner (posé sur la bande la plus proche au lâcher)."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets

BAND_NAMES = ("160", "80", "60", "40", "30", "20", "17", "15", "12", "10", "6", "4")
SPAN = 135                      # de -135° à +135° depuis la verticale


def _angles(n):
    return [-SPAN + 2 * SPAN * i / (n - 1) for i in range(n)]


class BandSelector(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal(str)        # « 40m »…

    def __init__(self, size=200):
        super().__init__()
        self.setFixedSize(size, size)
        self.k = size / 200                 # dessin prévu en 200 × 200
        self.names = list(BAND_NAMES)
        self.angles = _angles(len(self.names))
        self.index = 3                      # 40 m
        self.shown = self.angles[self.index]
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Commutateur de bandes : clic sur une bande, molette, ou "
                        "tourner le bouton à la souris")
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._drag = None
        self._wheel = 0
        self.blink = True                   # la bande choisie clignote (bien visible)
        self.blink_timer = QtCore.QTimer(self)
        self.blink_timer.timeout.connect(self._blink)
        self.blink_timer.start(260)

    def _blink(self):
        self.blink = not self.blink
        self.update()

    # --- état -------------------------------------------------------------
    def set_band(self, name):
        """Bande de la radio (sans renvoyer d'ordre)."""
        short = (name or "").removesuffix("m")
        if short in self.names:
            i = self.names.index(short)
            if i != self.index:
                self.index = i
                self.timer.start(16)
                if self.underMouse():           # souris sur le commutateur : la suivre
                    self._point_at(i)

    def _choose(self, i):
        i = max(0, min(len(self.names) - 1, i))
        self.index = i
        self.timer.start(16)
        self._point_at(i)
        self.changed.emit(self.names[i] + "m")

    def _point_at(self, i):
        """Pointeur de la souris posé pile sur le nom de la bande i."""
        lp = self._label_pos(self.angles[i]) * self.k
        proxy = self.graphicsProxyWidget()
        if proxy and proxy.scene() and proxy.scene().views():   # cadran agrandi (écran MOBILE)
            view = proxy.scene().views()[0]
            at = view.viewport().mapToGlobal(view.mapFromScene(proxy.mapToScene(lp)))
        else:
            at = self.mapToGlobal(lp.toPoint())
        QtGui.QCursor.setPos(at)

    def _tick(self):
        if self._drag and self._drag["moved"]:
            return
        goal = self.angles[self.index]
        self.shown += (goal - self.shown) * 0.22
        if abs(goal - self.shown) < 0.2:
            self.shown = goal
            self.timer.stop()
        self.update()

    # --- géométrie (coordonnées du dessin 200 × 200) ----------------------
    C = QtCore.QPointF(100, 108)

    @staticmethod
    def _dir(a):
        r = math.radians(a)
        return QtCore.QPointF(math.sin(r), -math.cos(r))

    def _label_pos(self, a):
        return self.C + self._dir(a) * 79

    def _lp(self, event):
        return QtCore.QPointF(event.pos()) / self.k

    def _angle_at(self, pos):
        d = pos - self.C
        a = math.degrees(math.atan2(d.x(), -d.y()))
        return max(-SPAN - 8, min(SPAN + 8, a))

    # --- souris ----------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return
        pos = self._lp(event)
        for i, a in enumerate(self.angles):
            if (pos - self._label_pos(a)).manhattanLength() < 15:
                self._choose(i)
                return
        self._drag = {"start": pos, "moved": False}

    def mouseMoveEvent(self, event):
        if not self._drag:
            return
        pos = self._lp(event)
        if (pos - self._drag["start"]).manhattanLength() > 4:
            self._drag["moved"] = True
        if self._drag["moved"]:
            self.shown = self._angle_at(pos)
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        drag, self._drag = self._drag, None
        self.setCursor(QtCore.Qt.PointingHandCursor)
        if not drag:
            return
        if not drag["moved"]:
            self._choose((self.index + 1) % len(self.names))     # simple clic : suivante
            return
        best = min(range(len(self.angles)), key=lambda i: abs(self.angles[i] - self.shown))
        self._choose(best)

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y()
        if abs(self._wheel) >= 120:
            self._choose(self.index + (1 if self._wheel > 0 else -1))
            self._wheel = 0
        event.accept()

    # --- dessin ------------------------------------------------------------
    @staticmethod
    def _led(p, at, on):
        """Petite LED dans une bague chromée : bleue allumée, sinon éteinte."""
        if on:
            halo = QtGui.QRadialGradient(at, 10)
            halo.setColorAt(0, QtGui.QColor(90, 180, 255, 220))
            halo.setColorAt(1, QtGui.QColor(30, 110, 255, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(at, 10, 10)
        g = QtGui.QConicalGradient(at, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#777c82"), (0.5, "#e6e8ea"),
                          (0.75, "#585d63"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#16181a"), 0.6))
        p.drawEllipse(at, 4.2, 4.2)
        g = QtGui.QRadialGradient(at - QtCore.QPointF(0.8, 0.8), 3)
        if on:
            g.setColorAt(0, QtGui.QColor("#ffffff"))
            g.setColorAt(0.4, QtGui.QColor("#9fd4ff"))
            g.setColorAt(1, QtGui.QColor("#1e6bff"))
        else:
            g.setColorAt(0, QtGui.QColor("#3a4560"))
            g.setColorAt(1, QtGui.QColor("#05070c"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 0.5))
        p.drawEllipse(at, 2.7, 2.7)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(self.k, self.k)
        W = H = 200
        c = self.C
        # ombre portée + platine crème biseautée
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.drawRoundedRect(QtCore.QRectF(4, 6, W - 6, H - 6), 12, 12)
        plate = QtGui.QLinearGradient(0, 0, 0, H)
        plate.setColorAt(0, QtGui.QColor("#fbf3dc"))
        plate.setColorAt(0.5, QtGui.QColor("#efe2bd"))
        plate.setColorAt(1, QtGui.QColor("#cdbb8c"))
        p.setBrush(plate)
        p.setPen(QtGui.QPen(QtGui.QColor("#6d5f3e"), 1.2))
        p.drawRoundedRect(QtCore.QRectF(1, 1, W - 4, H - 4), 11, 11)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 170), 1))
        p.drawRoundedRect(QtCore.QRectF(3, 3, W - 8, H - 8), 9, 9)
        # vis aux 4 coins
        for x, y in ((12, 12), (W - 15, 12), (12, H - 15), (W - 15, H - 15)):
            g = QtGui.QRadialGradient(QtCore.QPointF(x - 1.5, y - 1.5), 6)
            g.setColorAt(0, QtGui.QColor("#f4f4f4"))
            g.setColorAt(1, QtGui.QColor("#6c6c6c"))
            p.setBrush(g)
            p.setPen(QtGui.QPen(QtGui.QColor("#333"), 0.8))
            p.drawEllipse(QtCore.QPointF(x, y), 4.5, 4.5)
            p.setPen(QtGui.QPen(QtGui.QColor("#333"), 1.1))
            p.drawLine(QtCore.QPointF(x - 3, y + 1), QtCore.QPointF(x + 3, y - 1))
        # titre gravé
        f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Black)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        r = QtCore.QRectF(0, H - 24, W, 14)
        p.setPen(QtGui.QColor(255, 255, 255, 180))
        p.drawText(r.translated(0, 0.8), QtCore.Qt.AlignCenter, "BANDES")
        p.setPen(QtGui.QColor("#2b2414"))
        p.drawText(r, QtCore.Qt.AlignCenter, "BANDES")
        # graduations, noms des bandes, voyant bleu sur la bande choisie
        f = QtGui.QFont("DejaVu Sans Condensed", 8, QtGui.QFont.Bold)
        p.setFont(f)
        for i, (name, a) in enumerate(zip(self.names, self.angles)):
            d = self._dir(a)
            p.setPen(QtGui.QPen(QtGui.QColor("#3a3020"), 1.4))
            p.drawLine(c + d * 49, c + d * 55)
            lp = self._label_pos(a)
            chosen = i == self.index
            self._led(p, c + d * 63, chosen and self.blink)   # LED : clignote sur la bande
            if chosen and self.blink:                         # nom de la bande : éclat
                halo = QtGui.QRadialGradient(lp, 15)
                halo.setColorAt(0, QtGui.QColor(80, 170, 255, 200))
                halo.setColorAt(1, QtGui.QColor(30, 110, 255, 0))
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(halo)
                p.drawEllipse(lp, 15, 15)
            if chosen:
                p.setPen(QtGui.QColor("#ffffff") if self.blink else QtGui.QColor("#0b4fd0"))
            else:
                p.setPen(QtGui.QColor("#241c10"))
            p.drawText(QtCore.QRectF(lp.x() - 14, lp.y() - 7, 28, 14), QtCore.Qt.AlignCenter, name)
        # bague chromée autour du bouton
        g = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#ffffff"), (0.25, "#7a7f85"), (0.5, "#e8eaec"),
                          (0.75, "#5a5f65"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1a1a1a"), 1))
        p.drawEllipse(c, 47, 47)
        # ombre du bouton
        sh = QtGui.QRadialGradient(c + QtCore.QPointF(3, 5), 46)
        sh.setColorAt(0.75, QtGui.QColor(0, 0, 0, 140))
        sh.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(sh)
        p.drawEllipse(c + QtCore.QPointF(3, 5), 46, 46)
        # bouton bakélite cannelé
        kb = QtGui.QRadialGradient(c - QtCore.QPointF(12, 14), 52)
        kb.setColorAt(0, QtGui.QColor("#5c5c5c"))
        kb.setColorAt(0.45, QtGui.QColor("#1e1e1e"))
        kb.setColorAt(1, QtGui.QColor("#050505"))
        p.setBrush(kb)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawEllipse(c, 40, 40)
        p.save()
        p.translate(c)
        p.rotate(self.shown)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 28), 1.6))
        for i in range(36):                         # cannelures
            a = math.radians(i * 10)
            p.drawLine(QtCore.QPointF(36 * math.sin(a), -36 * math.cos(a)),
                       QtCore.QPointF(40 * math.sin(a), -40 * math.cos(a)))
        # bec (pointeur) en relief
        beak = QtGui.QPainterPath()
        beak.moveTo(0, -46)
        beak.lineTo(11, -8)
        beak.quadTo(0, 6, -11, -8)
        beak.closeSubpath()
        bg = QtGui.QLinearGradient(-11, 0, 11, 0)
        bg.setColorAt(0, QtGui.QColor("#4a4a4a"))
        bg.setColorAt(0.5, QtGui.QColor("#111"))
        bg.setColorAt(1, QtGui.QColor("#000"))
        p.setBrush(bg)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawPath(beak)
        p.setPen(QtGui.QPen(QtGui.QColor("#f4f4f4"), 2.2))     # trait blanc du repère
        p.drawLine(QtCore.QPointF(0, -42), QtCore.QPointF(0, -20))
        p.restore()
        # capuchon central bombé + reflet
        cap = QtGui.QRadialGradient(c - QtCore.QPointF(6, 7), 24)
        cap.setColorAt(0, QtGui.QColor("#6a6a6a"))
        cap.setColorAt(0.6, QtGui.QColor("#161616"))
        cap.setColorAt(1, QtGui.QColor("#000"))
        p.setBrush(cap)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawEllipse(c, 20, 20)
        hl = QtGui.QRadialGradient(c - QtCore.QPointF(14, 16), 18)
        hl.setColorAt(0, QtGui.QColor(255, 255, 255, 120))
        hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(hl)
        p.drawEllipse(c - QtCore.QPointF(12, 14), 16, 11)
        p.end()
