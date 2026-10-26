"""Écran DÉCODEUR RTTY : mappemonde plein écran + texte décodé.

Le texte vient du décodeur RTTY du Scope (feed_text). Les indicatifs y sont
repérés (« DE F5ABC », « CQ … F5ABC F5ABC », ou le même indicatif deux fois
en une minute) et vérifiés par cty.dat. La station qui émet apparaît en
petit point rouge sur la carte, à sa place (pays), UNIQUEMENT pendant son
émission : le point s'éteint 3 s après la fin du signal.
Essai seul : python3 rtty_screen.py
"""

import math
import re
import time

from PyQt5 import QtCore, QtGui, QtWidgets

from ft8_map import Ft8Map

CALL_RE = re.compile(r"\b([A-Z0-9]{1,3}[0-9][A-Z]{1,4}(?:/[A-Z0-9]{1,4})?)\b")
OFF_AIR_S = 3.0         # fin de signal → point éteint après ce délai
REPEAT_S = 60           # même indicatif deux fois en une minute = confirmé
TEXT_LINES = 7


class RttyScreen(Ft8Map):
    def __init__(self, home_grid="JN33ps", home_call="F4TXR", background=True):
        super().__init__(home_grid, home_call, background)
        self.setWindowTitle("Décodeur RTTY")
        self.text = ""                  # texte décodé (fin gardée)
        self.signal = False
        self.last_signal = 0.0
        self.freq_hz = None
        self.on_air = None              # (indicatif, pays, lat, lon)
        self.seen = {}                  # indicatif → dernière fois vu (confirmation)
        self.heard = []                 # [(heure, indicatif, pays)] les plus récents d'abord
        self.tx = False                 # ma radio émet
        self.tx_text = ""               # ce que j'émets (texte)
        self.tx_since = 0.0

    # pas d'UDP ici : seulement l'animation
    def start(self):
        self.timer.start(80)

    def stop(self):
        self.timer.stop()
        self.hide()

    def reset(self):
        self.text, self.on_air, self.seen, self.heard = "", None, {}, []
        self.tx_text = ""

    def set_tx(self, on):
        """Ma radio passe en émission (True) ou en réception (False)."""
        if on and not self.tx:
            self.tx_since = time.time()
            stamp = time.strftime("%H:%M:%S")
            self.tx_text += ("\n" if self.tx_text else "") + f"[{stamp}] émission F4TXR "
        self.tx = bool(on)

    def add_tx_text(self, chunk):
        self.tx_text = (self.tx_text + chunk)[-4000:]

    # --- entrées venant du Scope
    def set_frequency(self, hz):
        self.freq_hz = hz

    def set_signal(self, signal):
        self.signal = bool(signal)
        if signal:
            self.last_signal = time.time()

    def feed_text(self, chunk):
        self.last_signal = time.time()          # des caractères arrivent : ça émet
        self.text = (self.text + chunk)[-4000:]
        tail = self.text[-160:].upper().replace("\n", " ")
        found = None
        for m in CALL_RE.finditer(tail):
            call = m.group(1)
            prefix = re.match(r"[A-Z0-9]{1,3}?(?=[0-9][A-Z])", call)
            if not prefix or not re.search(r"[A-Z]", call.split("/")[0][:3]):
                continue
            country = self.locator.country(call)
            if not country:
                continue
            country = country.replace("Fed. Rep. of ", "")
            before = tail[max(0, m.start() - 4):m.start()]
            now = time.time()
            confirmed = ("DE " in before or now - self.seen.get(call, 0) < REPEAT_S
                         or tail.count(call) >= 2)
            self.seen[call] = now
            if confirmed:
                found = (call, country)
        if found:
            self._set_on_air(*found)

    def _set_on_air(self, call, country):
        pos = self.locator.position(call)
        if not pos:
            return
        if not self.on_air or self.on_air[0] != call:
            self.heard = [h for h in self.heard if h[1] != call]
            self.heard.insert(0, (time.strftime("%H:%M"), call, country))
            del self.heard[8:]
        self.on_air = (call, country, pos[0], pos[1])

    def _tick(self):
        if self.on_air and time.time() - self.last_signal > OFF_AIR_S:
            self.on_air = None                  # fin d'émission : le point s'éteint
        self.update()

    # --- dessin
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._background())
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        now = time.time()
        home = self._xy(*self.home)
        # ma station
        p.setPen(QtGui.QPen(QtGui.QColor("#2a1c06"), 1))
        p.setBrush(QtGui.QColor("#ffd27a"))
        p.drawEllipse(home, 5, 5)
        p.setPen(QtGui.QColor("#ffd27a"))
        p.setFont(QtGui.QFont("DejaVu Sans", 9, QtGui.QFont.Bold))
        p.drawText(home + QtCore.QPointF(8, 14), self.home_call)
        # station en émission : petit point rouge vivant
        if self.on_air:
            call, country, lat, lon = self.on_air
            pt = self._xy(lat, lon)
            k = 0.5 + 0.5 * math.sin(now * 2 * math.pi * 1.4)
            glow = QtGui.QRadialGradient(pt, 16)
            glow.setColorAt(0, QtGui.QColor(255, 40, 40, int(90 + 140 * k)))
            glow.setColorAt(1, QtGui.QColor(255, 40, 40, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(pt, 16, 16)
            p.setBrush(QtGui.QColor(255, 50, 50))
            p.drawEllipse(pt, 4, 4)
            p.setFont(QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Bold))
            p.setPen(QtGui.QColor(0, 0, 0, 170))
            p.drawText(pt + QtCore.QPointF(9, -7), f"{call}  {country}")
            p.setPen(QtGui.QColor(255, 225, 225))
            p.drawText(pt + QtCore.QPointF(8, -8), f"{call}  {country}")
        # bandeau du haut
        panel = QtGui.QColor(2, 8, 28, 170)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(panel)
        p.drawRoundedRect(QtCore.QRectF(16, 14, 800, 74), 10, 10)
        p.setFont(QtGui.QFont("DejaVu Sans", 17, QtGui.QFont.Bold))
        p.setPen(QtGui.QColor("#cfe3ff"))
        freq = f"{self.freq_hz / 1e6:.3f} MHz" if self.freq_hz else ""
        p.drawText(QtCore.QRectF(32, 18, 780, 34), QtCore.Qt.AlignVCenter,
                   f"DÉCODEUR RTTY  ·  45 bauds  ·  {freq}")
        live = self.signal or now - self.last_signal < 1.0
        p.setBrush(QtGui.QColor(60, 255, 90) if live else QtGui.QColor(40, 70, 50))
        p.drawEllipse(QtCore.QPointF(40, 68), 7, 7)
        p.setFont(QtGui.QFont("DejaVu Sans", 12, QtGui.QFont.Bold))
        p.setPen(QtGui.QColor("#ffe27a") if self.on_air else QtGui.QColor("#8fa6c8"))
        p.drawText(QtCore.QRectF(56, 54, 650, 28), QtCore.Qt.AlignVCenter,
                   f"En émission : {self.on_air[0]} — {self.on_air[1]}" if self.on_air
                   else ("Signal reçu, indicatif pas encore identifié" if live
                         else "En attente d'une station…"))
        # dernières stations identifiées
        if self.heard:
            box = QtCore.QRectF(w - 380, 14, 364, 34 + 24 * len(self.heard))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(panel)
            p.drawRoundedRect(box, 10, 10)
            p.setPen(QtGui.QColor("#8fa6c8"))
            p.setFont(QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Bold))
            p.drawText(box.adjusted(14, 6, 0, 0), QtCore.Qt.AlignTop, "Dernières stations")
            p.setFont(QtGui.QFont("DejaVu Sans Mono", 10))
            for i, (hhmm, call, country) in enumerate(self.heard):
                p.setPen(QtGui.QColor("#ffe27a") if self.on_air and call == self.on_air[0]
                         else QtGui.QColor("#dbe7ff"))
                p.drawText(QtCore.QPointF(box.left() + 14, box.top() + 48 + 24 * i),
                           f"{hhmm}  {call:<10} {country[:20]}")
        # deux masques transparents en avant-plan : ÉMISSION | RÉCEPTION
        # (la boule FERMER reste libre à droite)
        gap = 14
        width = (w - 180 - gap) / 2
        height = 34 + 30 * TEXT_LINES + 12
        top = h - 22 - height
        live = self.signal or now - self.last_signal < 1.0
        self._panel(p, QtCore.QRectF(16, top, width, height), "ÉMISSION",
                    QtGui.QColor("#ff6b6b"), self.tx_text, self.tx,
                    f"EN ÉMISSION  {int(now - self.tx_since)} s" if self.tx else "repos")
        self._panel(p, QtCore.QRectF(16 + width + gap, top, width, height), "RÉCEPTION",
                    QtGui.QColor("#7dff8a"), self.text, live,
                    "signal reçu" if live else "en écoute")
        p.end()

    def _panel(self, p, box, title, color, text, lit, state):
        """Masque translucide : la carte reste visible derrière."""
        p.setPen(QtGui.QPen(QtGui.QColor(color.red(), color.green(), color.blue(), 110), 1.5))
        p.setBrush(QtGui.QColor(0, 6, 20, 120))
        p.drawRoundedRect(box, 12, 12)
        # titre + voyant
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(color if lit else QtGui.QColor(color.red() // 4, color.green() // 4,
                                                  color.blue() // 4))
        p.drawEllipse(QtCore.QPointF(box.left() + 20, box.top() + 19), 7, 7)
        p.setFont(QtGui.QFont("DejaVu Sans", 13, QtGui.QFont.Bold))
        p.setPen(color)
        p.drawText(QtCore.QRectF(box.left() + 34, box.top() + 4, box.width() - 50, 30),
                   QtCore.Qt.AlignVCenter, title)
        p.setFont(QtGui.QFont("DejaVu Sans", 10))
        p.setPen(QtGui.QColor(200, 215, 240, 200))
        p.drawText(QtCore.QRectF(box.left(), box.top() + 4, box.width() - 16, 30),
                   QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, state)
        p.setPen(QtGui.QPen(QtGui.QColor(color.red(), color.green(), color.blue(), 60), 1))
        p.drawLine(QtCore.QPointF(box.left() + 12, box.top() + 36),
                   QtCore.QPointF(box.right() - 12, box.top() + 36))
        # texte (fin) : chaque ligne repliée à la largeur du masque
        font = QtGui.QFont("DejaVu Sans Mono", 15, QtGui.QFont.Bold)
        p.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        room = int(box.width() - 28)
        lines = []
        for raw in text.replace("\r", "").split("\n")[-TEXT_LINES * 2:]:
            while metrics.horizontalAdvance(raw) > room and len(raw) > 1:
                n = len(raw)
                while n > 1 and metrics.horizontalAdvance(raw[:n]) > room:
                    n -= 1
                lines.append(raw[:n])
                raw = raw[n:]
            lines.append(raw)
        p.setPen(color.lighter(115))
        for i, line in enumerate(lines[-TEXT_LINES:]):
            p.drawText(QtCore.QPointF(box.left() + 14, box.top() + 62 + 30 * i), line)


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    s = RttyScreen(background=False)
    s.resize(1400, 760)
    s.set_frequency(14_085_000)
    s.feed_text("RYRYRY CQ CQ CQ DE DL1ABC DL1ABC DL1ABC K\n")
    s.feed_text("F4TXR DE EA8ZZ EA8ZZ UR 599 599 BK\nCQ TEST JA1XYZ JA1XYZ\n")
    s.set_signal(True)
    s.set_tx(True)
    s.add_tx_text("EA8ZZ DE F4TXR F4TXR 599 599 BK")
    s.start()
    s.show()
    if "--shot" in sys.argv:
        QtCore.QTimer.singleShot(800, lambda: (s.grab().save(sys.argv[-1]), app.quit()))
    app.exec_()
