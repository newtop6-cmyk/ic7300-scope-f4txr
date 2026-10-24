"""Afficheur de fréquence à tambours mécaniques (façon Collins) : un rouleau
noir par chiffre, chiffres blancs, qui ROULE vers le nouveau chiffre ; on voit
les chiffres voisins dépasser en haut et en bas, assombris par la courbure ;
fenêtre en verre, cadre en laiton vieilli, points en laiton entre les groupes."""

import math

from PyQt5 import QtCore, QtGui, QtWidgets


class DrumDisplay(QtWidgets.QWidget):
    tuned = QtCore.pyqtSignal(int)

    def __init__(self, width=370, height=74):
        super().__init__()
        self.setFixedSize(width, height)
        self.setToolTip("Molette : changer la fréquence")
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self._text = "--.---.---"
        self._angle = 0
        self.pos = []                   # position affichée de chaque rouleau (0–10)
        self.goal = []
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.font = QtGui.QFont("DejaVu Serif", 26, QtGui.QFont.Bold)
        self._layout(self._text)
        # rétro-éclairage : 0 = éteint, ~0,35 en réception, jusqu'à 1 en émission
        self.light = 0.0                # réception : rétro-éclairage éteint
        self.light_goal = 0.0
        self.tx = 0.0                   # teinte émission (0 = ambre, 1 = orange-rouge)
        self.tx_goal = 0.0
        self.light_timer = QtCore.QTimer(self)
        self.light_timer.timeout.connect(self._light_tick)

    def set_tx(self, on, watts=None):
        """Fin d'émission : retour à l'éclairage de repos (couleur inchangée)."""
        if not on:
            self.set_voice(None)

    def set_voice(self, level):
        """Émission : l'intensité suit la voix (level 0 à 1) ; None = repos.
        La couleur reste l'ambre de réception."""
        self.tx_goal = 0.0
        # silence → presque éteint, voix forte → éclat maximal (contraste fort)
        self.light_goal = 0.0 if level is None else 0.05 + 1.25 * min(1.0, level)
        if not self.light_timer.isActive():
            self.light_timer.start(30)

    def _light_tick(self):
        up = self.light_goal > self.light
        self.light += (self.light_goal - self.light) * (0.7 if up else 0.3)   # très vif
        self.tx += (self.tx_goal - self.tx) * (0.4 if self.tx_goal > self.tx else 0.1)
        if abs(self.light_goal - self.light) < 0.005 and abs(self.tx_goal - self.tx) < 0.005:
            self.light, self.tx = self.light_goal, self.tx_goal
            self.light_timer.stop()
        self.update()

    def _lamp(self, alpha=255):
        """Couleur de l'ampoule : ambre en réception, orange-rouge en émission."""
        t = self.tx
        return QtGui.QColor(255, int(185 - 95 * t), int(80 - 60 * t), alpha)

    # --- valeur ----------------------------------------------------------
    def _layout(self, text):
        self.chars = list(text)
        digits = [c for c in text if c != "."]
        self.goal = [float(c) if c.isdigit() else -1.0 for c in digits]
        if len(self.pos) != len(self.goal):
            self.pos = list(self.goal)

    def setText(self, text):
        if text == self._text:
            return
        old = len([c for c in self._text if c != "."])
        self._text = text
        self._layout(text)
        if old != len(self.goal):
            self.pos = list(self.goal)
        self.timer.start(16)
        self.update()

    def text(self):
        return self._text

    def wheelEvent(self, event):
        self._angle += event.angleDelta().y()
        steps = int(self._angle / 120)
        if steps:
            self._angle -= steps * 120
            self.tuned.emit(steps)
        event.accept()

    def _tick(self):
        moving = False
        for i, g in enumerate(self.goal):
            if g < 0:
                self.pos[i] = g
                continue
            p = self.pos[i] if self.pos[i] >= 0 else g
            d = (g - p + 5) % 10 - 5        # chemin le plus court sur le rouleau
            if abs(d) < 0.01:
                self.pos[i] = g
                continue
            self.pos[i] = (p + d * 0.25) % 10
            moving = True
        if not moving:
            self.timer.stop()
        self.update()

    # --- dessin ----------------------------------------------------------
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        frame = self._paint_frame(p)
        self._paint_window(p, frame.adjusted(18, 8, -18, -8), self.chars, self.pos)
        p.end()

    def _paint_frame(self, p):
        w, h = self.width(), self.height()
        # ombre et cadre en laiton vieilli
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 110))
        p.drawRoundedRect(QtCore.QRectF(3, 4, w - 3, h - 4), 9, 9)
        frame = QtCore.QRectF(0, 0, w - 4, h - 5)
        g = QtGui.QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QtGui.QColor("#f1d98e"))
        g.setColorAt(0.35, QtGui.QColor("#b48a3c"))
        g.setColorAt(0.7, QtGui.QColor("#7a5a22"))
        g.setColorAt(1, QtGui.QColor("#4a3410"))
        p.setPen(QtGui.QPen(QtGui.QColor("#2a1c06"), 1.2))
        p.setBrush(g)
        p.drawRoundedRect(frame, 9, 9)
        for sx in (frame.left() + 9, frame.right() - 9):          # vis
            for sy in (frame.top() + 9, frame.bottom() - 9):
                sg = QtGui.QRadialGradient(sx - 1, sy - 1, 4)
                sg.setColorAt(0, QtGui.QColor("#fff2c0"))
                sg.setColorAt(1, QtGui.QColor("#6a4c14"))
                p.setPen(QtGui.QPen(QtGui.QColor("#2a1c06"), 0.7))
                p.setBrush(sg)
                p.drawEllipse(QtCore.QPointF(sx, sy), 2.8, 2.8)
                p.drawLine(QtCore.QPointF(sx - 2, sy), QtCore.QPointF(sx + 2, sy))
        return frame

    def _paint_window(self, p, win, chars, positions, sep_w=9):
        """Une fenêtre de tambours : chars = texte (chiffres et séparateurs)."""
        # lumière qui déborde de la fenêtre sur le laiton
        p.setBrush(QtCore.Qt.NoBrush)
        for k in range(1, 10):                      # lueur dégradée, sans trait dur
            a = min(255, int(110 * self.light * self.light * (1 - k / 10)))
            p.setPen(QtGui.QPen(self._lamp(a), 1.6))
            p.drawRoundedRect(win.adjusted(-k * 1.3, -k * 1.0, k * 1.3, k * 1.0), 5 + k, 5 + k)
        p.setPen(QtGui.QPen(QtGui.QColor("#1a1206"), 1.5))
        p.setBrush(QtGui.QColor("#050505"))
        p.drawRoundedRect(win, 4, 4)
        inner = win.adjusted(4, 3, -4, -3)
        n_digits = len([c for c in chars if c not in ".:"])
        n_dots = len(chars) - n_digits
        dot_w = sep_w
        dw = (inner.width() - n_dots * dot_w - (n_digits - 1) * 2) / max(n_digits, 1)
        x = inner.left()
        k = 0
        fm = QtGui.QFontMetricsF(self.font)
        for ch in chars:
            if ch == ":":                                       # deux points en laiton
                for cy in (inner.center().y() - 4, inner.center().y() + 4):
                    c = QtCore.QPointF(x + dot_w / 2, cy)
                    p.setPen(QtCore.Qt.NoPen)
                    p.setBrush(QtGui.QColor("#d8b866"))
                    p.drawEllipse(c, 1.6, 1.6)
                x += dot_w
                continue
            if ch == ".":                                       # point en laiton
                c = QtCore.QPointF(x + dot_w / 2, inner.bottom() - 7)
                dg = QtGui.QRadialGradient(c - QtCore.QPointF(0.8, 0.8), 3)
                dg.setColorAt(0, QtGui.QColor("#fff0b0"))
                dg.setColorAt(1, QtGui.QColor("#8a6420"))
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(dg)
                p.drawEllipse(c, 2.4, 2.4)
                x += dot_w
                continue
            drum = QtCore.QRectF(x, inner.top(), dw, inner.height())
            self._drum(p, drum, positions[k], fm)
            x += dw + 2
            k += 1
        # verre : reflet en haut, ombre interne
        p.setClipping(False)
        g = QtGui.QLinearGradient(0, win.top(), 0, win.bottom())
        g.setColorAt(0, QtGui.QColor(255, 255, 255, 70))
        g.setColorAt(0.35, QtGui.QColor(255, 255, 255, 10))
        g.setColorAt(0.36, QtGui.QColor(255, 255, 255, 0))
        g.setColorAt(1, QtGui.QColor(0, 0, 0, 40))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(win.adjusted(1, 1, -1, -1), 4, 4)
        # fil d'index rouge, fin, au milieu (grandes fenêtres seulement)
        if win.height() < 40:
            return
        p.setPen(QtGui.QPen(QtGui.QColor(200, 30, 20, 150), 1))
        p.drawLine(QtCore.QPointF(win.left() + 2, win.center().y()),
                   QtCore.QPointF(win.left() + 9, win.center().y()))
        p.drawLine(QtCore.QPointF(win.right() - 9, win.center().y()),
                   QtCore.QPointF(win.right() - 2, win.center().y()))

    def _drum(self, p, r, pos, fm):
        """Un rouleau : chiffre courant au centre, voisins au-dessus et dessous."""
        p.save()
        p.setClipRect(r)
        # cylindre noir : plus clair au milieu
        g = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QtGui.QColor("#000000"))
        g.setColorAt(0.5, QtGui.QColor("#2a2826"))
        g.setColorAt(1, QtGui.QColor("#000000"))
        p.fillRect(r, g)
        # rétro-éclairage : lumière chaude au centre du rouleau
        lg = QtGui.QRadialGradient(r.center(), r.height() * 0.7)
        lg.setColorAt(0, self._lamp(min(255, int(200 * self.light))))
        lg.setColorAt(1, self._lamp(0))
        p.fillRect(r, lg)
        step = r.height() * 0.62                     # écart entre deux chiffres
        cy = r.center().y()
        p.setFont(self.font)
        if pos < 0:                                  # pas de valeur : tiret
            p.setPen(QtGui.QColor("#d8d2c0"))
            p.drawText(r, QtCore.Qt.AlignCenter, "–")
        else:
            base = math.floor(pos)
            frac = pos - base
            for off in (-2, -1, 0, 1, 2):
                digit = int((base + off) % 10)
                y = cy + (off - frac) * step         # le rouleau monte quand pos croît
                dist = abs(y - cy) / (r.height() / 2)
                if dist > 1.3:
                    continue
                # courbure : les chiffres loin du centre sont écrasés et sombres
                squash = max(0.25, math.cos(min(dist, 1.2) * 1.15))
                bright = int(240 * max(0.0, 1 - dist * 0.85))
                p.save()
                p.translate(r.center().x(), y)
                p.scale(1.0, squash)
                box = QtCore.QRectF(-r.width() / 2, -fm.height() / 2, r.width(), fm.height())
                if dist < 0.5 and self.light > 0.05:     # lueur autour du chiffre
                    glow = self._lamp(min(255, int(150 * self.light * (1 - dist * 2))))
                    p.setPen(glow)
                    for dx, dy in ((-1.5, 0), (1.5, 0), (0, -1.5), (0, 1.5)):
                        p.drawText(box.translated(dx, dy), QtCore.Qt.AlignCenter, str(digit))
                lamp = self._lamp()
                mix = min(0.9, 0.65 * self.light)              # chiffre teinté par la lampe
                dim = 1.0                                       # chiffres toujours bien lisibles
                col = QtGui.QColor(
                    min(255, int(dim * (bright * (1 - mix) + lamp.red() * mix * bright / 240))),
                    min(255, int(dim * ((bright - 6) * (1 - mix) + lamp.green() * mix * bright / 240))),
                    min(255, int(dim * ((bright - 20) * (1 - mix) + lamp.blue() * mix * bright / 240))))
                p.setPen(col)
                p.drawText(box, QtCore.Qt.AlignCenter, str(digit))
                p.restore()
        # ombres de courbure en haut et en bas
        g = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QtGui.QColor(0, 0, 0, 230))
        g.setColorAt(0.28, QtGui.QColor(0, 0, 0, 0))
        g.setColorAt(0.72, QtGui.QColor(0, 0, 0, 0))
        g.setColorAt(1, QtGui.QColor(0, 0, 0, 230))
        p.fillRect(r, g)
        # séparations entre rouleaux
        p.setPen(QtGui.QPen(QtGui.QColor(90, 80, 60, 120), 0.8))
        p.drawLine(r.topLeft(), r.bottomLeft())
        p.restore()


class DrumClock(DrumDisplay):
    """Deux horloges à tambours (LOCAL en haut, TU en bas), même cadre en
    laiton et même rétro-éclairage que la fréquence ; les chiffres roulent."""

    def __init__(self):
        super().__init__(172, 74)
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.setToolTip("En haut : heure locale du PC · en bas : heure TU "
                        "(temps universel, UTC), celle des carnets de trafic")
        self.font = QtGui.QFont("DejaVu Serif", 10, QtGui.QFont.Bold)
        self.rows = [[0.0] * 6, [0.0] * 6]
        self.row_goals = [[0.0] * 6, [0.0] * 6]
        self._clock()
        self.rows = [list(g) for g in self.row_goals]
        self.clock_timer = QtCore.QTimer(self)
        self.clock_timer.timeout.connect(self._clock)
        self.clock_timer.start(250)

    def _clock(self):
        import datetime
        now = datetime.datetime.now()
        utc = datetime.datetime.now(datetime.timezone.utc)
        for i, t in enumerate((now, utc)):
            self.row_goals[i] = [float(c) for c in t.strftime("%H%M%S")]
        if not self.timer.isActive():
            self.timer.start(16)

    def _tick(self):
        moving = False
        for row, goals in zip(self.rows, self.row_goals):
            for i, g in enumerate(goals):
                d = (g - row[i] + 5) % 10 - 5
                if abs(d) < 0.01:
                    row[i] = g
                    continue
                row[i] = (row[i] + d * 0.25) % 10
                moving = True
        if not moving:
            self.timer.stop()
        self.update()

    def wheelEvent(self, event):
        event.ignore()                          # pas de réglage sur une horloge

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        frame = self._paint_frame(p)
        inner = frame.adjusted(8, 7, -8, -7)
        half = inner.height() / 2
        f = QtGui.QFont("DejaVu Sans Condensed", 6, QtGui.QFont.Black)
        for i, tag in enumerate(("LOCAL", "TU")):
            row = QtCore.QRectF(inner.left(), inner.top() + i * half, inner.width(), half)
            p.setFont(f)                                # nom gravé sur le laiton
            tag_r = QtCore.QRectF(row.left(), row.top(), 30, row.height())
            p.setPen(QtGui.QColor(255, 240, 200, 150))
            p.drawText(tag_r.translated(0, 0.8), QtCore.Qt.AlignCenter, tag)
            p.setPen(QtGui.QColor("#2a1c06"))
            p.drawText(tag_r, QtCore.Qt.AlignCenter, tag)
            win = row.adjusted(32, 1.5, 0, -1.5)
            self._paint_window(p, win, list("00:00:00"), self.rows[i], sep_w=6)
        p.end()
