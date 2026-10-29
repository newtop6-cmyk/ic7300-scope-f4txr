"""Barregraphes de liaison, deux mesures :
- LIAISON : PC ↔ téléphone GSM qui lui donne Internet (modem USB ou partage
  Wi-Fi). Le téléphone est la passerelle de la route par défaut.
- 4G : PC → Pi qui porte la radio, à travers le réseau 4G et Tailscale.
Un ping par seconde ; sur les 10 derniers, temps de réponse médian, gigue et
pertes donnent une note de 0 à 1.
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


def quality(samples, bad_ms=100):
    """samples : temps en ms, None = perdu. Note de 0 à 1 ; bad_ms = note 0."""
    if not samples:
        return 0.0
    ok = [s for s in samples if s is not None]
    loss = 1 - len(ok) / len(samples)
    if not ok:
        return 0.0
    rtt = statistics.median(ok)
    jitter = statistics.pstdev(ok) if len(ok) > 1 else 0.0
    # téléphone (bad_ms 100) : ≤ 5 ms → 1, 50 ms → 0,5 ;
    # Pi en 4G (bad_ms 1000) : ≤ 50 ms → 1, 400 ms → 0,6
    q = (bad_ms - rtt) / (bad_ms * 0.95)
    q -= jitter / bad_ms                # gigue : liaison qui hoquette
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
    """Ping en tâche de fond ; signal updated(note, ms médian, % pertes).
    target=None : la passerelle (le téléphone) ; sinon l'adresse donnée.
    target="" : rien à mesurer (radio branchée sur ce PC)."""
    updated = QtCore.pyqtSignal(float, float, float)

    def __init__(self, parent=None, target=None, name="PC ↔ téléphone", bad_ms=100):
        super().__init__(parent)
        self.target, self.name, self.bad_ms = target, name, bad_ms
        self.enabled = target != ""
        self.host = default_gateway() if target is None else target
        self.samples = deque(maxlen=WINDOW)
        self.note, self.rtt, self.loss = 0.0, -1.0, 0.0
        self.lost = False
        if self.enabled:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            start = time.monotonic()
            ms = None
            gw = default_gateway() if self.target is None else self.target
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
            self.note = quality(list(self.samples), self.bad_ms)
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
        if not pr.enabled:
            tip = f"Liaison {pr.name} : radio branchée sur ce PC, rien à mesurer"
        elif pr.lost:
            tip = (f"Liaison {pr.name} : COUPÉE" if pr.host else
                   f"Liaison {pr.name} : aucune connexion")
        elif pr.rtt < 0:
            tip = f"Liaison {pr.name} : mesure en cours…"
        else:
            tip = (f"Liaison {pr.name} ({pr.host}) : {round(pr.note * 100)} %\n"
                   f"temps de réponse {pr.rtt:.0f} ms, pertes {pr.loss:.0f} %\n"
                   "(10 dernières secondes)")
        st = getattr(pr, "status", None)
        if st and not pr.lost and pr.rtt >= 0:     # Starlink : détails de la parabole
            tip = (f"Starlink : {round(pr.note * 100)} %\n"
                   f"latence {st['latency_ms']:.0f} ms, pertes {100 * st['drop']:.1f} %\n"
                   f"ciel obstrué {100 * st['obstructed']:.0f} %\n"
                   f"débit ↓ {st['down_bps'] / 1e3:.0f} kbit/s, ↑ {st['up_bps'] / 1e3:.0f} kbit/s")
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
            if not pr.enabled:
                c = QtGui.QColor("#3a3f44")
            elif not on:
                c = c.darker(520)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 2, 2)
            if on and pr.enabled:       # reflet de la LED
                p.setBrush(QtGui.QColor(255, 255, 255, 60))
                p.drawRoundedRect(QtCore.QRectF(r.left() + 1, r.top() + 1,
                                                r.width() - 2, r.height() * 0.35), 1, 1)
        if self.text:
            if not pr.enabled:
                label = "LOCAL"
            elif pr.lost:
                label = "COUPÉ"
            elif pr.rtt < 0:
                label = "…"
            else:
                label = f"{pr.rtt:.1f} ms" if pr.rtt < 10 else f"{pr.rtt:.0f} ms"
            p.setFont(QtGui.QFont("DejaVu Sans", 9 if w >= 50 else (7 if w >= 40 else 6), QtGui.QFont.Bold))
            box = QtCore.QRectF(0, h - text_h, w, text_h)
            p.setPen(QtGui.QColor(255, 255, 255, 170))      # gravé : reflet dessous
            p.drawText(box.translated(0, 1), QtCore.Qt.AlignCenter, label)
            p.setPen(QtGui.QColor("#c62828" if pr.lost else "#1c1f22"))
            p.drawText(box, QtCore.Qt.AlignCenter, label)
        p.end()


# --- Starlink : état de la parabole (latence, pertes, obstruction) ----------
DISH = "192.168.100.1"
DISH_URL = f"http://{DISH}:9201/SpaceX.API.Device.Device/Handle"
STATUS_REQ = b"\x00\x00\x00\x00\x03" + bytes([0xE2, 0x3E, 0x00])   # get_status (grpc-web)


def _varint(b, i):
    v = s = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return v, i


def _fields(b):
    """Protobuf brut → {champ: valeur} (float, entier ou octets du sous-message)."""
    out, i = {}, 0
    import struct
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            out[f], i = _varint(b, i)
        elif wt == 5:
            out[f] = struct.unpack("<f", b[i:i + 4])[0]
            i += 4
        elif wt == 1:
            out[f] = struct.unpack("<d", b[i:i + 8])[0]
            i += 8
        elif wt == 2:
            n, i = _varint(b, i)
            out[f] = b[i:i + n]
            i += n
        else:
            break
    return out


def dish_status(iface=None):
    """État de la parabole : dict(latency_ms, drop, obstructed, down_bps, up_bps)
    ou None si elle ne répond pas."""
    cmd = ["curl", "-s", "-m", "3", "-X", "POST",
           "-H", "Content-Type: application/grpc-web+proto", "-H", "X-Grpc-Web: 1",
           "--data-binary", "@-", DISH_URL]
    if iface:
        cmd[1:1] = ["--interface", iface]
    try:
        data = subprocess.run(cmd, input=STATUS_REQ, capture_output=True, timeout=5).stdout
        if len(data) < 6 or data[0] != 0:
            return None
        n = int.from_bytes(data[1:5], "big")
        st = _fields(_fields(data[5:5 + n]).get(2004, b""))
        if 1009 not in st:
            return None
        obst = _fields(st.get(1004, b""))
        return {"latency_ms": float(st.get(1009, -1)),
                "drop": float(st.get(1003, 0.0)),           # absent = aucune perte
                "obstructed": float(obst.get(1, 0.0)),
                "down_bps": float(st.get(1007, 0.0)),
                "up_bps": float(st.get(1008, 0.0))}
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
        return None


def _default_ifaces():
    """Interfaces des routes par défaut (le Wi-Fi de la box Starlink en fait partie)."""
    names = []
    try:
        with open("/proc/net/route") as f:
            for line in f.read().splitlines()[1:]:
                k = line.split()
                if len(k) > 1 and k[1] == "00000000" and k[0] not in names:
                    names.append(k[0])
    except OSError:
        pass
    return names


def starlink_quality(st):
    """Note 0 à 1 : latence (≤ 30 ms = plein, 150 ms = 0), pertes très pénalisées."""
    q = (150 - st["latency_ms"]) / 120
    q *= (1 - min(1.0, st["drop"])) ** 3
    return max(0.0, min(1.0, q))


class StarlinkProbe(QtCore.QObject):
    """Même interface que LinkProbe (note, rtt, loss, lost, updated) pour LinkBar ;
    la parabole est jointe par l'interface qui y mène (souvent le Wi-Fi de la box,
    même quand Internet passe par le téléphone)."""
    updated = QtCore.pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name, self.host, self.enabled = "Starlink", DISH, True
        self.note, self.rtt, self.loss = 0.0, -1.0, 0.0
        self.lost, self.status, self.iface, self.misses = False, None, None, 0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            start = time.monotonic()
            st = dish_status(self.iface)
            if st is None:                          # autre interface ?
                for iface in [None] + _default_ifaces():
                    if iface != self.iface:
                        st = dish_status(iface)
                        if st is not None:
                            self.iface = iface
                            break
            if st is None:
                self.misses += 1
                self.lost = self.misses >= 2
                if self.lost:
                    self.note, self.rtt = 0.0, -1.0
            else:
                self.misses, self.lost, self.status = 0, False, st
                self.note = starlink_quality(st)
                self.rtt = st["latency_ms"]
                self.loss = 100 * st["drop"]
            self.updated.emit(self.note, self.rtt, self.loss)
            time.sleep(max(0.0, 2.0 - (time.monotonic() - start)))
