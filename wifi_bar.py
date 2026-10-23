"""Barre Wi-Fi : dégradé vert (excellent) → jaune → orange → rouge, avec une LED
rouge placée selon la force du signal reçu à l'instant t. La LED clignote tout
à droite si le signal est totalement perdu. Même principe que l'extension GNOME
« Voyant Wi-Fi »."""

from PyQt5 import QtCore, QtGui, QtWidgets


def wifi_signal():
    """Force du signal Wi-Fi reçu (0 à 100 %), ou -1 si perdu."""
    try:
        with open("/proc/net/wireless") as f:
            lines = f.read().splitlines()[2:]
    except OSError:
        return -1
    best = -1
    for line in lines:
        iface, _, rest = line.partition(":")
        fields = rest.split()
        if len(fields) < 2:
            continue
        try:
            with open(f"/sys/class/net/{iface.strip()}/operstate") as f:
                if f.read().strip() != "up":
                    continue
        except OSError:
            continue
        quality = float(fields[1].rstrip("."))      # qualité sur 70
        if quality > 0:
            best = max(best, round(min(70.0, quality) / 70 * 100))
    return best


class WifiBar(QtWidgets.QWidget):
    BAR_H, LED = 10, 14

    def __init__(self):
        super().__init__()
        self.setFixedSize(130, 22)
        self.signal = wifi_signal()
        self.blink = False
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(500)                    # rythme de lecture et de clignotement

    def refresh(self):
        self.signal = wifi_signal()
        self.blink = not self.blink
        self.setToolTip(f"Wi-Fi : {self.signal} %" if self.signal >= 0
                        else "Wi-Fi : signal perdu")
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        led = self.LED
        bar = QtCore.QRectF(led / 2, (h - self.BAR_H) / 2, w - led, self.BAR_H)
        grad = QtGui.QLinearGradient(bar.left(), 0, bar.right(), 0)
        grad.setColorAt(0, QtGui.QColor("#2ecc40"))
        grad.setColorAt(0.33, QtGui.QColor("#ffe600"))
        grad.setColorAt(0.66, QtGui.QColor("#ff9800"))
        grad.setColorAt(1, QtGui.QColor("#e53935"))
        p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1))
        p.setBrush(grad)
        p.drawRoundedRect(bar, self.BAR_H / 2, self.BAR_H / 2)
        # LED : 100 % à gauche (vert), 0 % à droite (rouge) ; clignote si perdu
        lost = self.signal < 0
        if lost and not self.blink:
            p.end()
            return
        pct = 0 if lost else max(0, min(100, self.signal))
        cx = bar.left() + (100 - pct) / 100 * bar.width()
        cy = h / 2
        halo = QtGui.QRadialGradient(cx, cy, led)
        halo.setColorAt(0, QtGui.QColor(255, 26, 26, 160))
        halo.setColorAt(1, QtGui.QColor(255, 26, 26, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QtCore.QPointF(cx, cy), led, led / 1.4)
        body = QtGui.QRadialGradient(cx - 2, cy - 2, led / 2)
        body.setColorAt(0, QtGui.QColor("#ffb3b3"))
        body.setColorAt(0.5, QtGui.QColor("#ff1a1a"))
        body.setColorAt(1, QtGui.QColor("#a00000"))
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1))
        p.setBrush(body)
        p.drawEllipse(QtCore.QPointF(cx, cy), led / 2 - 1, led / 2 - 1)
        p.end()
