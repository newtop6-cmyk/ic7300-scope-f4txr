"""Barre Trafic : débit réseau du PC, au format de la barre Wi-Fi (130×22).
Moitié haute = sortie (envoi, orange), moitié basse = entrée (réception, cyan).
Échelle logarithmique de 100 o/s à 10 Mo/s pour voir le moindre filet de données.
Lecture de /proc/net/dev toutes les 100 ms sur l'interface de la route par défaut
(Wi-Fi, modem USB…), qui est recherchée à chaque fois, car elle peut changer."""

import math
import time

from PyQt5 import QtCore, QtGui, QtWidgets

LOW, HIGH = 100.0, 10_000_000.0          # o/s : bas et haut de l'échelle


def default_iface():
    """Interface de la route par défaut (plus petite métrique), ou None."""
    best = None
    try:
        with open("/proc/net/route") as f:
            for line in f.read().splitlines()[1:]:
                fields = line.split()
                if len(fields) > 6 and fields[1] == "00000000":
                    metric = int(fields[6])
                    if best is None or metric < best[1]:
                        best = (fields[0], metric)
    except (OSError, ValueError):
        return None
    return best[0] if best else None


def iface_bytes(iface):
    """(octets reçus, octets envoyés) de l'interface, ou None."""
    try:
        with open("/proc/net/dev") as f:
            for line in f.read().splitlines()[2:]:
                name, _, rest = line.partition(":")
                if name.strip() == iface:
                    v = rest.split()
                    return int(v[0]), int(v[8])
    except (OSError, ValueError, IndexError):
        pass
    return None


def level(rate):
    """Débit (o/s) → position 0..1 sur l'échelle logarithmique."""
    if rate <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log10(max(rate, LOW) / LOW) /
                        math.log10(HIGH / LOW))) if rate >= LOW else rate / LOW * 0.04


def human(rate):
    for unit, div in (("Mo/s", 1e6), ("Ko/s", 1e3)):
        if rate >= div:
            return f"{rate / div:.1f} {unit}"
    return f"{rate:.0f} o/s"


class TrafficBar(QtWidgets.QWidget):
    BAR_H, LED = 10, 8
    TICK_MS = 100

    def __init__(self):
        super().__init__()
        self.setFixedSize(130, 22)
        self.iface = None
        self.last = None                  # (temps, reçus, envoyés)
        self.rx = self.tx = 0.0           # débits lissés (o/s)
        self.rx_peak = self.tx_peak = 0.0  # positions des crêtes (0..1)
        self.rx_on = self.tx_on = False   # paquet vu pendant ce tick
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(self.TICK_MS)

    def refresh(self):
        iface = default_iface()
        now = time.monotonic()
        counts = iface_bytes(iface) if iface else None
        if iface != self.iface or counts is None or self.last is None:
            self.iface = iface
            self.last = (now, *counts) if counts else None
            self.rx_on = self.tx_on = False
            self.rx *= 0.5
            self.tx *= 0.5
        else:
            dt = max(1e-3, now - self.last[0])
            drx, dtx = counts[0] - self.last[1], counts[1] - self.last[2]
            self.last = (now, *counts)
            self.rx_on, self.tx_on = drx > 0, dtx > 0
            # montée immédiate, descente douce : chaque paquet se voit
            for name, d in (("rx", drx), ("tx", dtx)):
                rate = max(0, d) / dt
                old = getattr(self, name)
                setattr(self, name, rate if rate > old else old * 0.7 + rate * 0.3)
        # crêtes : retombent lentement
        self.rx_peak = max(level(self.rx), self.rx_peak - 0.01)
        self.tx_peak = max(level(self.tx), self.tx_peak - 0.01)
        self.setToolTip(f"Trafic ({self.iface or 'aucune liaison'})\n"
                        f"Sortie ↑ {human(self.tx)}\nEntrée ↓ {human(self.rx)}"
                        if self.iface else "Trafic : aucune liaison réseau")
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        led = self.LED
        bar = QtCore.QRectF(led + 4, (h - self.BAR_H) / 2, w - led - 6, self.BAR_H)
        r = self.BAR_H / 2
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(bar, r, r)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#1a1a1a"))
        p.drawPath(clip)
        p.save()
        p.setClipPath(clip)
        half = bar.height() / 2
        lanes = ((self.tx, self.tx_peak, bar.top(), "#ff9800", "#ffd180"),
                 (self.rx, self.rx_peak, bar.top() + half, "#00bcd4", "#a7f3ff"))
        for rate, peak, top, color, light in lanes:
            lv = level(rate)
            if lv > 0:
                grad = QtGui.QLinearGradient(bar.left(), 0, bar.right(), 0)
                grad.setColorAt(0, QtGui.QColor(color).darker(160))
                grad.setColorAt(1, QtGui.QColor(light))
                p.setBrush(grad)
                p.drawRect(QtCore.QRectF(bar.left(), top, bar.width() * lv, half))
            if peak > 0.01:
                x = bar.left() + bar.width() * peak
                p.setBrush(QtGui.QColor("#ffffff"))
                p.drawRect(QtCore.QRectF(x - 1, top, 2, half))
        p.restore()
        p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(clip)
        # petite séparation entre les deux voies
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 150), 1))
        p.drawLine(QtCore.QPointF(bar.left() + 2, bar.center().y()),
                   QtCore.QPointF(bar.right() - 2, bar.center().y()))
        # LED d'activité : orange = envoi, cyan = réception, blanc = les deux
        if self.tx_on and self.rx_on:
            c = QtGui.QColor("#ffffff")
        elif self.tx_on:
            c = QtGui.QColor("#ff9800")
        elif self.rx_on:
            c = QtGui.QColor("#00bcd4")
        else:
            c = QtGui.QColor("#333333")
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.setBrush(c)
        p.drawEllipse(QtCore.QPointF(led / 2 + 1, h / 2), led / 2, led / 2)
        p.end()
