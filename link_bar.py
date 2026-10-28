"""Barregraphe LIAISON : qualité de la liaison entre le PC et le téléphone GSM
qui lui donne Internet (modem USB ou partage Wi-Fi). Le téléphone est la
passerelle de la route par défaut : on le pingue une fois par seconde ; sur les
10 derniers pings, temps de réponse médian, gigue et pertes donnent une note
de 0 à 1.
Cases allumées de gauche (rouge) à droite (vert) : plus il y en a, meilleure
est la liaison. Liaison coupée : la première case clignote en rouge."""

import re
import statistics
import subprocess
import threading
import time
from collections import deque

from PyQt5 import QtCore, QtGui, QtWidgets

WINDOW = 10                 # pings pris en compte


def quality(samples):
    """samples : temps en ms, None = perdu. Note de 0 à 1."""
    if not samples:
        return 0.0
    ok = [s for s in samples if s is not None]
    loss = 1 - len(ok) / len(samples)
    if not ok:
        return 0.0
    rtt = statistics.median(ok)
    jitter = statistics.pstdev(ok) if len(ok) > 1 else 0.0
    q = (100 - rtt) / 95                # ≤ 5 ms → 1 ; 50 ms → 0,5 ; 100 ms → 0
    q -= jitter / 100                   # gigue : liaison qui hoquette
    q *= (1 - loss) ** 2                # pertes : très pénalisées
    return max(0.0, min(1.0, q))


def default_gateway():
    """Adresse de la passerelle par défaut (le téléphone), ou None."""
    best = None
    try:
        with open("/proc/net/route") as f:
            for line in f.read().splitlines()[1:]:
                k = line.split()
                if len(k) > 6 and k[1] == "00000000" and int(k[3], 16) & 2:
                    if best is None or int(k[6]) < best[1]:
                        best = (k[2], int(k[6]))
    except (OSError, ValueError):
        return None
    if not best:
        return None
    raw = int(best[0], 16)                  # petit-boutiste
    return ".".join(str(raw >> s & 255) for s in (0, 8, 16, 24))


class LinkProbe(QtCore.QObject):
    """Ping du téléphone (passerelle) en tâche de fond ;
    signal updated(note, ms médian, % pertes)."""
    updated = QtCore.pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = default_gateway()
        self.samples = deque(maxlen=WINDOW)
        self.note, self.rtt, self.loss = 0.0, -1.0, 0.0
        self.lost = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            start = time.monotonic()
            ms = None
            gw = default_gateway()          # la connexion peut changer
            if gw != self.host:
                self.host = gw
                self.samples.clear()
            try:
                if not gw:
                    raise OSError("pas de connexion")
                out = subprocess.run(["ping", "-n", "-c", "1", "-W", "2", self.host],
                                     capture_output=True, text=True, timeout=4).stdout
                m = re.search(r"time=([\d.]+)", out)
                ms = float(m.group(1)) if m else None
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.samples.append(ms)
            ok = [s for s in self.samples if s is not None]
            self.note = quality(list(self.samples))
            self.rtt = statistics.median(ok) if ok else -1.0
            self.loss = 100 * (1 - len(ok) / len(self.samples))
            last3 = list(self.samples)[-3:]
            self.lost = len(last3) == 3 and all(s is None for s in last3)
            self.updated.emit(self.note, self.rtt, self.loss)
            time.sleep(max(0.0, 1.0 - (time.monotonic() - start)))


SEG_COLORS = ("#e53935", "#e53935", "#ff6d00", "#ff9800", "#ffc400",
              "#ffe600", "#c6e600", "#7ed321", "#2ecc40", "#2ecc40")


class LinkBar(QtWidgets.QWidget):
    """Cases LED. vertical=True : grand modèle (écran MOBILE), bas = mauvais."""

    def __init__(self, probe, width=130, height=22, vertical=False, text=False):
        super().__init__()
        self.probe = probe
        self.vertical = vertical
        self.text = text
        self.setFixedSize(width, height)
        self.blink = False
        probe.updated.connect(lambda *_: self.update())
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(400)
        self._tick()

    def _tick(self):
        self.blink = not self.blink
        pr = self.probe
        if pr.lost:
            tip = ("Liaison PC ↔ téléphone : COUPÉE" if pr.host else
                   "Liaison PC ↔ téléphone : aucune connexion")
        elif pr.rtt < 0:
            tip = "Liaison PC ↔ téléphone : mesure en cours…"
        else:
            tip = (f"Liaison PC ↔ téléphone ({pr.host}) : {round(pr.note * 100)} %\n"
                   f"temps de réponse {pr.rtt:.0f} ms, pertes {pr.loss:.0f} %\n"
                   "(10 dernières secondes)")
        self.setToolTip(tip)
        if pr.lost:
            self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pr = self.probe
        n = len(SEG_COLORS)
        lit = 0 if (pr.lost or pr.rtt < 0) else max(1, round(pr.note * n))
        w, h = self.width(), self.height()
        text_h = 22 if self.text else 0
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.setBrush(QtGui.QColor("#15181b"))
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, w - 1, h - 1 - text_h), 4, 4)
        gap, pad = 2, 3
        for i, color in enumerate(SEG_COLORS):
            if self.vertical:
                seg_h = (h - text_h - 2 * pad - gap * (n - 1)) / n
                r = QtCore.QRectF(pad, h - text_h - pad - (i + 1) * seg_h - i * gap,
                                  w - 2 * pad, seg_h)
            else:
                seg_w = (w - 2 * pad - gap * (n - 1)) / n
                r = QtCore.QRectF(pad + i * (seg_w + gap), pad, seg_w, h - 2 * pad)
            c = QtGui.QColor(color)
            on = i < lit or (i == 0 and pr.lost and self.blink)
            if not on:
                c = c.darker(520)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 2, 2)
            if on:                  # reflet de la LED
                p.setBrush(QtGui.QColor(255, 255, 255, 60))
                p.drawRoundedRect(QtCore.QRectF(r.left() + 1, r.top() + 1,
                                                r.width() - 2, r.height() * 0.35), 1, 1)
        if self.text:
            if pr.lost:
                label = "COUPÉ"
            elif pr.rtt < 0:
                label = "…"
            else:
                label = f"{pr.rtt:.1f} ms" if pr.rtt < 10 else f"{pr.rtt:.0f} ms"
            p.setFont(QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Bold))
            box = QtCore.QRectF(0, h - text_h, w, text_h)
            p.setPen(QtGui.QColor(255, 255, 255, 170))      # gravé : reflet dessous
            p.drawText(box.translated(0, 1), QtCore.Qt.AlignCenter, label)
            p.setPen(QtGui.QColor("#c62828" if pr.lost else "#1c1f22"))
            p.drawText(box, QtCore.Qt.AlignCenter, label)
        p.end()
