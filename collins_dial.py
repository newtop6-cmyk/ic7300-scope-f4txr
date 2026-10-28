"""Cadran de fréquence rétroéclairé façon Collins (75S-3 / KWM-2) pour
l'écran MOBILE : façade gris Collins, fenêtre éclairée ambre-crème, échelle
des kHz qui défile derrière un fil rouge, fenêtre des MHz à gauche et lecture
exacte gravée en dessous. Même usage que DrumDisplay : setText("7.100.000"),
molette = tuned."""

from PyQt5 import QtCore, QtGui, QtWidgets

PANEL = ("#5d6a63", "#46514b", "#2f3833")        # gris-vert Collins
LIGHT = ("#fff3c9", "#ffd98a", "#d99a3a")        # lampe : centre → bords
INK = QtGui.QColor("#1b120a")                    # encre des chiffres


class CollinsDial(QtWidgets.QWidget):
    tuned = QtCore.pyqtSignal(int)

    def __init__(self, width=800, height=170):
        super().__init__()
        self.setFixedSize(width, height)
        self.setToolTip("Molette : changer la fréquence")
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self._text = "--.---.---"
        self.hz = None                  # fréquence demandée
        self.shown = None               # fréquence affichée (l'échelle glisse)
        self._angle = 0
        self.lamp = 1.0
        self.voice = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # --- même interface que DrumDisplay ------------------------------------
    def setText(self, text):
        self._text = text
        digits = text.replace(".", "")
        self.hz = int(digits) if digits.isdigit() else None
        if self.hz is not None and (self.shown is None or abs(self.hz - self.shown) > 2_000_000):
            self.shown = float(self.hz)            # changement de bande : saut direct
        self.update()

    def text(self):
        return self._text

    def set_voice(self, level):
        self.voice = level

    def set_tx(self, on, watts=None):
        pass

    def wheelEvent(self, event):
        self._angle += event.angleDelta().y()
        steps = int(self._angle / 120)
        if steps:
            self._angle -= steps * 120
            self.tuned.emit(steps)
        event.accept()

    def _tick(self):
        changed = False
        if self.hz is not None and self.shown is not None and self.shown != self.hz:
            self.shown += (self.hz - self.shown) * 0.2
            if abs(self.hz - self.shown) < 5:
                self.shown = float(self.hz)
            changed = True
        goal = 1.0 if self.voice is None else min(1.0, 0.85 + 0.2 * self.voice)
        if abs(goal - self.lamp) > 0.003:
            self.lamp += (goal - self.lamp) * 0.3
            changed = True
        if changed:
            self.update()

    # --- dessin ---------------------------------------------------------------
    def _panel(self, p, w, h):
        g = QtGui.QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QtGui.QColor(PANEL[0]))
        g.setColorAt(0.5, QtGui.QColor(PANEL[1]))
        g.setColorAt(1, QtGui.QColor(PANEL[2]))
        p.setPen(QtGui.QPen(QtGui.QColor("#151a17"), 1.5))
        p.setBrush(g)
        p.drawRoundedRect(QtCore.QRectF(1, 1, w - 2, h - 2), 10, 10)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 50), 1))
        p.drawRoundedRect(QtCore.QRectF(3, 3, w - 6, h - 6), 8, 8)
        # texture légère (peinture granitée)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 18), 1))
        for y in range(6, h - 6, 3):
            p.drawLine(QtCore.QPointF(6, y), QtCore.QPointF(w - 6, y))

    def _window(self, p, r, radius=6):
        """Fenêtre éclairée de l'intérieur : crème au centre, ambre aux bords."""
        bezel = r.adjusted(-5, -5, 5, 5)
        g = QtGui.QLinearGradient(0, bezel.top(), 0, bezel.bottom())
        g.setColorAt(0, QtGui.QColor("#1a1f1c"))
        g.setColorAt(1, QtGui.QColor("#77857d"))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(bezel, radius + 3, radius + 3)
        light = QtGui.QRadialGradient(r.center(), max(r.width(), r.height()) * 0.62)
        for stop, col in ((0, LIGHT[0]), (0.55, LIGHT[1]), (1, LIGHT[2])):
            c = QtGui.QColor(col)
            c = QtGui.QColor(int(c.red() * self.lamp), int(c.green() * self.lamp),
                             int(c.blue() * self.lamp))
            light.setColorAt(stop, c)
        p.setBrush(light)
        p.drawRoundedRect(r, radius, radius)

    def _glass(self, p, r, radius=6):
        """Vitre : reflet en haut, ombre intérieure."""
        shine = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 70))
        shine.setColorAt(0.35, QtGui.QColor(255, 255, 255, 10))
        shine.setColorAt(0.36, QtGui.QColor(255, 255, 255, 0))
        shine.setColorAt(1, QtGui.QColor(0, 0, 0, 45))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 120), 1.5))
        p.setBrush(shine)
        p.drawRoundedRect(r, radius, radius)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        self._panel(p, w, h)
        # fenêtre MHz à gauche, grande fenêtre kHz à droite
        mhz_r = QtCore.QRectF(22, 22, 118, h - 70)
        khz_r = QtCore.QRectF(162, 22, w - 184, h - 70)
        for r in (mhz_r, khz_r):
            self._window(p, r)
        shown = self.shown if self.shown is not None else None
        # MHz
        p.setPen(INK)
        f = QtGui.QFont("DejaVu Serif", 10, QtGui.QFont.Bold)
        f.setPixelSize(int(mhz_r.height() * 0.62))
        p.setFont(f)
        mhz = "--" if shown is None else str(int(round(shown)) // 1_000_000)
        p.drawText(mhz_r.adjusted(0, -8, 0, -8), QtCore.Qt.AlignCenter, mhz)
        f2 = QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Bold)
        f2.setPixelSize(12)
        f2.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2)
        p.setFont(f2)
        p.drawText(mhz_r.adjusted(0, 0, 0, -6), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom, "MC")
        # échelle des kHz qui défile : 1 kHz = px_per_khz pixels
        p.save()
        p.setClipRect(khz_r)
        cx = khz_r.center().x()
        px_per_khz = 26.0
        if shown is not None:
            khz_now = (shown % 1_000_000) / 1000.0
            first = int(khz_now - khz_r.width() / 2 / px_per_khz) - 1
            last = int(khz_now + khz_r.width() / 2 / px_per_khz) + 2
            fnum = QtGui.QFont("DejaVu Serif", 10, QtGui.QFont.Bold)
            fnum.setPixelSize(int(khz_r.height() * 0.36))
            p.setFont(fnum)
            base_y = khz_r.bottom() - 6
            for k in range(first, last + 1):
                for sub in range(5):                 # traits tous les 200 Hz
                    pos = k + sub / 5
                    x = cx + (pos - khz_now) * px_per_khz
                    if sub == 0:
                        long = 26 if k % 10 == 0 else 18 if k % 5 == 0 else 12
                        p.setPen(QtGui.QPen(INK, 2.2 if k % 10 == 0 else 1.4))
                    else:
                        long = 6
                        p.setPen(QtGui.QPen(INK, 0.8))
                    p.drawLine(QtCore.QPointF(x, base_y), QtCore.QPointF(x, base_y - long))
                if k % 5 == 0:
                    x = cx + (k - khz_now) * px_per_khz
                    label = f"{k % 1000:03d}" if k % 10 == 0 else f"{k % 1000:03d}"[-1]
                    p.setPen(INK)
                    rect = QtCore.QRectF(x - 40, khz_r.top() + 4, 80, khz_r.height() * 0.45)
                    if k % 10 == 0:
                        p.setFont(fnum)
                    else:
                        small = QtGui.QFont(fnum)
                        small.setPixelSize(int(fnum.pixelSize() * 0.6))
                        p.setFont(small)
                    p.drawText(rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom, label)
        # assombrissement aux deux bouts (le tambour s'enroule)
        for left in (True, False):
            g = QtGui.QLinearGradient(khz_r.left() if left else khz_r.right(), 0,
                                      khz_r.left() + 70 if left else khz_r.right() - 70, 0)
            g.setColorAt(0, QtGui.QColor(60, 30, 0, 150))
            g.setColorAt(1, QtGui.QColor(60, 30, 0, 0))
            p.fillRect(khz_r, g)
        p.restore()
        # fil rouge de lecture
        p.setPen(QtGui.QPen(QtGui.QColor(190, 20, 10), 2.4))
        p.drawLine(QtCore.QPointF(cx, khz_r.top() - 3), QtCore.QPointF(cx, khz_r.bottom() + 3))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 120, 100, 90), 6))
        p.drawLine(QtCore.QPointF(cx, khz_r.top()), QtCore.QPointF(cx, khz_r.bottom()))
        for r in (mhz_r, khz_r):
            self._glass(p, r)
        # lecture exacte gravée sous les fenêtres + plaque « COLLINS » style
        fe = QtGui.QFont("DejaVu Sans Mono", 10, QtGui.QFont.Bold)
        fe.setPixelSize(26)
        p.setFont(fe)
        read = QtCore.QRectF(khz_r.left(), khz_r.bottom() + 8, khz_r.width(), 34)
        text = self._text + " MHz" if self.hz is not None else "--.---.--- MHz"
        p.setPen(QtGui.QColor(0, 0, 0, 160))
        p.drawText(read.translated(0, 1.2), QtCore.Qt.AlignCenter, text)
        p.setPen(QtGui.QColor("#e8e2cc"))
        p.drawText(read, QtCore.Qt.AlignCenter, text)
        fl = QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Bold)
        fl.setPixelSize(13)
        fl.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 3)
        p.setFont(fl)
        plate = QtCore.QRectF(mhz_r.left(), mhz_r.bottom() + 8, mhz_r.width(), 34)
        p.setPen(QtGui.QColor("#e8e2cc"))
        p.drawText(plate, QtCore.Qt.AlignCenter, "F4TXR")
        p.end()


if __name__ == "__main__":                       # essai seul
    import sys
    app = QtWidgets.QApplication(sys.argv)
    d = CollinsDial()
    d.setText(sys.argv[1] if len(sys.argv) > 1 else "7.100.000")
    d.show()
    sys.exit(app.exec_())
