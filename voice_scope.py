"""Oscilloscope « vintage » : la forme d'onde de la voix au micro du PC.

Boîtier en tôle émaillée martelée, tube cathodique vert phosphore avec
quadrillage, traînée lumineuse (rémanence), verre bombé, vis, voyant et
boutons en bakélite. La trace est synchronisée sur les fronts montants
(comme le déclenchement d'un vrai scope) et le gain s'adapte doucement.
"""

import collections
import json
import os
import random
import subprocess

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

RATE = 16000
BLOCK = 128                     # 8 ms par bloc lu : la trace suit la voix sans retard
SHOW = 400                      # échantillons affichés (25 ms : 2 à 6 périodes de voix)
PERSIST = 4                     # anciennes traces gardées (rémanence du phosphore)
CW_POINTS = 600                 # réception CW : 3 s de manipulation (5 ms par point)
FLOOR = 0.006                   # en dessous (≈ -44 dBFS) : pas d'amplification du souffle

# vobulation : spectre de la voix balayé par un spot, comme un vobulateur
VOBU_FMIN, VOBU_FMAX = 100, 4000   # Hz, échelle logarithmique
VOBU_POINTS = 180
VOBU_FFT = 1024                    # 64 ms de son analysés (fenêtre de Hann)
VOBU_RANGE_DB = 48                 # hauteur de l'écran au-dessus du bruit de fond
VOBU_SWEEP_TICKS = 14              # un balayage complet ≈ 0,22 s
CONFIG = os.path.expanduser("~/.config/ic7300-scope/oscillo.json")


class MicReader(QtCore.QThread):
    samples = QtCore.pyqtSignal(object)         # bloc numpy float32

    def __init__(self, source):
        super().__init__()
        self.source = source
        self._running = True
        self._proc = None

    def run(self):
        try:
            self._proc = subprocess.Popen(
                ["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                 f"--device={self.source}", "--latency-msec=10",
                 "--client-name=IC-7300 oscilloscope"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return
        nbytes = BLOCK * 2
        while self._running:
            data = self._proc.stdout.read(nbytes)
            if len(data) < nbytes:
                break
            self.samples.emit(np.frombuffer(data, "<i2").astype(np.float32) / 32768)

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self.wait(1000)


class VoiceScope(QtWidgets.QWidget):
    W, H = 380, 205

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.setToolTip("Oscilloscope : la forme d'onde de ta voix au micro")
        self.reader = None
        self.buf = np.zeros(4096, np.float32)
        self.env = FLOOR
        self.gain = 1.0 / FLOOR
        self.traces = []                    # anciennes traces (rémanence)
        self.level = 0.0                    # pour le voyant
        self._case = None                   # fond peint une fois (tôle martelée)
        # réception CW : enveloppe de la note (une valeur toutes les 5 ms, 3 s)
        self.cw_mode = False
        self.cw_env = collections.deque([0.0] * CW_POINTS, maxlen=CW_POINTS)
        # vobulation
        self.vobu = self._load_mode()       # vobulation choisie (clic sur l'écran)
        self.tx = False                     # émission : micro ; réception : son reçu
        self.rx_reader = None               # son de la radio (vobulation en réception)
        self.rx_buf = np.zeros(4096, np.float32)
        self._win = np.hanning(VOBU_FFT).astype(np.float32)
        freqs = np.fft.rfftfreq(VOBU_FFT, 1 / RATE)
        edges = np.geomspace(VOBU_FMIN, VOBU_FMAX, VOBU_POINTS + 1)
        self._bins = [(int(np.searchsorted(freqs, a)), max(int(np.searchsorted(freqs, b)),
                       int(np.searchsorted(freqs, a)) + 1)) for a, b in zip(edges[:-1], edges[1:])]
        self.spec = np.full(VOBU_POINTS, -120.0)      # dB affichés (descente lente)
        self.noise_db = -75.0                         # bruit de fond suivi
        self.curve = np.zeros(VOBU_POINTS)            # balayage en cours (0 à 1)
        self.old_curve = np.zeros(VOBU_POINTS)        # balayage précédent
        self.sweep = 0                                # position du spot (points)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(40)             # 25 images/s : fluide sans saturer l'interface
        self._update_tooltip()

    # --- vobulation / forme d'onde (clic sur l'écran) -------------------------
    def set_tx(self, on):
        """La radio émet : vobulation (si choisie) ; en réception : forme d'onde."""
        if on != self.tx:
            self.tx = on
            self.traces = []
            self.sweep = 0
            self.curve[:] = 0
            self.old_curve[:] = 0
            self.update()

    def _vobu_on(self):
        return self.vobu and not self.cw_mode       # en permanence (émission ET réception)

    @staticmethod
    def _load_mode():
        try:
            with open(CONFIG) as f:
                return bool(json.load(f).get("vobulation", True))
        except (OSError, ValueError, AttributeError):
            return True

    def _update_tooltip(self):
        if self.cw_mode:
            return
        self.setToolTip(
            "Oscilloscope en VOBULATEUR : spectre 100 Hz à 4 kHz balayé par le spot ; "
            "en réception = son reçu (voix du correspondant), en émission = ta voix au "
            "micro. Clic : forme d'onde de ta voix." if self.vobu else
            "Oscilloscope : la forme d'onde de ta voix au micro. "
            "Clic : mode vobulateur.")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and not self.cw_mode:
            self.vobu = not self.vobu
            self.traces = []
            try:
                os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
                with open(CONFIG, "w") as f:
                    json.dump({"vobulation": self.vobu}, f)
            except OSError:
                pass
            self._update_tooltip()
            self.update()
        super().mousePressEvent(event)

    # --- réception CW : manipulation ON / OFF --------------------------------
    def set_cw(self, on):
        if on != self.cw_mode:
            self.cw_mode = on
            if on:
                self.setToolTip("Oscilloscope : manipulation CW reçue (ON en haut, OFF en bas)")
            else:
                self._update_tooltip()
            self.update()

    def has_cw(self):
        """De la CW est-elle vraiment reçue ? Une note nette au-dessus du bruit,
        manipulée (alternance de signes et de silences) sur les 3 dernières s."""
        env = np.array(self.cw_env)
        thr = self._cw_threshold(env)
        if not np.isfinite(thr):
            return False
        on = env > thr
        duty = float(on.mean())
        edges = np.flatnonzero(on[1:] != on[:-1])
        if not (0.05 < duty < 0.9 and 6 <= len(edges) <= 160):
            return False
        # signes nettement plus forts que les silences…
        if float(np.median(env[on])) < 3.0 * float(np.median(env[~on])) + 1e-9:
            return False
        # … et assez longs (≥ 20 ms) : le bruit, lui, saute d'un point à l'autre
        runs = np.diff(np.concatenate(([0], edges + 1, [len(on)])))
        on_runs = runs[(np.arange(len(runs)) % 2 == 0) == bool(on[0])]
        return len(on_runs) > 0 and float(np.median(on_runs)) >= 4

    def feed_cw(self, values):
        self.cw_env.extend(float(v) for v in values)

    # --- son -------------------------------------------------------------
    def set_source(self, source):
        if self.reader and self.reader.source == source:
            return
        if self.reader:                     # seulement le micro (le son reçu continue)
            self.reader.stop()
            self.reader = None
        if source and source != "file":
            self.reader = MicReader(source)
            self.reader.samples.connect(self._on_samples)
            self.reader.start()

    def set_rx_source(self, source):
        """Son de la radio : vobulation en réception."""
        if self.rx_reader:
            self.rx_reader.stop()
            self.rx_reader = None
        if source:
            self.rx_reader = MicReader(source)
            self.rx_reader.samples.connect(self._on_rx_samples)
            self.rx_reader.start()

    def _on_rx_samples(self, x):
        n = len(x)
        self.rx_buf = np.roll(self.rx_buf, -n)
        self.rx_buf[-n:] = x

    def stop(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
        if self.rx_reader:
            self.rx_reader.stop()
            self.rx_reader = None

    def voice_level(self):
        """Niveau de la voix 0 à 1, très sensible (≈ -55 dBFS → 0, -15 dBFS → 1),
        sur les 50 dernières ms."""
        x = self.buf[-800:]
        db = 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)
        return float(np.clip((db + 55) / 40, 0.0, 1.0)) ** 0.7

    def _on_samples(self, x):
        n = len(x)
        self.buf = np.roll(self.buf, -n)
        self.buf[-n:] = x

    # --- trace -----------------------------------------------------------
    def _tick(self):
        if not self.isVisible():
            return
        if self.cw_mode:
            env = np.array(self.cw_env)
            self.level = self.level * 0.7 + 0.3 * float(env[-20:].max() > self._cw_threshold(env))
            self.update()
            return
        if self._vobu_on():
            self._tick_vobu()
            return
        recent = self.buf[-1024:]
        peak = float(np.max(np.abs(recent)))
        self.env = max(peak, self.env * 0.96, FLOOR)
        target = 0.8 / self.env
        # baisse tout de suite (pas d'écrêtage), remonte en douceur
        self.gain = target if target < self.gain else self.gain + (target - self.gain) * 0.15
        self.level = self.level * 0.8 + 0.2 * min(peak / 0.3, 1.0)
        # déclenchement : dernier front montant qui laisse SHOW points derrière lui
        seg = self.buf[-(SHOW + 1200):]
        thr = 0.15 * self.env
        start = None
        cross = np.flatnonzero((seg[:-1] < thr) & (seg[1:] >= thr))
        cross = cross[cross <= len(seg) - SHOW - 1]
        if len(cross):
            start = int(cross[-1])
        if start is None:
            start = len(seg) - SHOW                              # balayage libre
        y = np.clip(seg[start:start + SHOW] * self.gain, -1.15, 1.15)
        self.traces = (self.traces + [y.copy()])[-PERSIST:]
        self.update()

    def _tick_vobu(self):
        """Spectre du son le plus récent ; le spot avance et redessine la courbe
        avec ce spectre : la trace est toujours celle de la voix de l'instant."""
        src = self.buf if self.tx else self.rx_buf      # émission : micro ; sinon radio
        x = src[-VOBU_FFT:] * self._win
        mag = np.abs(np.fft.rfft(x)) / (self._win.sum() / 2)
        db_bins = 20 * np.log10(np.array([mag[a:b].max() for a, b in self._bins]) + 1e-9)
        # montée immédiate, descente douce (comme le phosphore)
        self.spec = np.maximum(db_bins, self.spec - 2.5)
        # bruit de fond : suit vite vers le bas, lentement vers le haut
        floor = float(np.percentile(db_bins, 25))
        rate = 0.25 if floor < self.noise_db else 0.01
        self.noise_db += (floor - self.noise_db) * rate
        low = self.noise_db - 2
        y = np.clip((self.spec - low) / VOBU_RANGE_DB, 0.0, 1.05)
        step = max(1, VOBU_POINTS // VOBU_SWEEP_TICKS)
        end = min(self.sweep + step, VOBU_POINTS)
        self.curve[:end] = y[:end]          # derrière le spot : la voix de maintenant
        self.sweep = end
        if self.sweep >= VOBU_POINTS:       # fin de balayage : on repart à gauche
            self.old_curve = self.curve.copy()
            self.sweep = 0
        peak = float(np.max(np.abs(self.buf[-800:])))
        self.level = self.level * 0.6 + 0.4 * min(peak / 0.3, 1.0)
        # bouton GAIN : sensibilité (bruit de fond bas = gain fort)
        self.gain = float(10 ** np.clip((-self.noise_db - 30) / 60 * np.log10(0.8 / FLOOR), 0,
                                        np.log10(0.8 / FLOOR)))
        self.update()

    def _paint_vobu(self, p, screen):
        """Trace en miroir autour de la ligne centrale : plate sans modulation,
        pics vers le haut ET vers le bas avec la voix."""
        n = VOBU_POINTS
        xs = screen.left() + 4 + np.arange(n) * (screen.width() - 8) / (n - 1)
        bottom = screen.bottom() - 14                   # place des repères en bas
        mid = (screen.top() + 14 + bottom) / 2          # ligne centrale (repos)
        half = (bottom - screen.top() - 14) / 2
        shown = np.concatenate((self.curve[:self.sweep], self.old_curve[self.sweep:]))
        up = [QtCore.QPointF(float(x), float(mid - v * half)) for x, v in zip(xs, shown)]
        down = [QtCore.QPointF(float(x), float(mid + v * half)) for x, v in zip(xs, shown)]
        # ligne centrale de repos
        p.setPen(QtGui.QPen(QtGui.QColor(120, 255, 170, 70), 1))
        p.drawLine(QtCore.QPointF(screen.left() + 4, mid), QtCore.QPointF(screen.right() - 4, mid))
        # intérieur du spectre rempli : vert phosphore plein, plus lumineux au
        # centre ; la partie déjà balayée (après le spot) un peu plus pâle
        def fill(a, b, strength):
            if b - a < 2:
                return
            area = QtGui.QPolygonF(up[a:b] + down[a:b][::-1])
            g = QtGui.QLinearGradient(0, mid - half, 0, mid + half)
            g.setColorAt(0.0, QtGui.QColor(40, 230, 40, int(215 * strength)))     # vert fluo
            g.setColorAt(0.3, QtGui.QColor(57, 255, 20, int(245 * strength)))
            g.setColorAt(0.5, QtGui.QColor(190, 255, 170, int(255 * strength)))   # cœur éclatant
            g.setColorAt(0.7, QtGui.QColor(57, 255, 20, int(245 * strength)))
            g.setColorAt(1.0, QtGui.QColor(40, 230, 40, int(215 * strength)))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(g)
            p.drawPolygon(area)
        fill(0, max(self.sweep, 1) + 1, 1.0)            # balayage en cours : plein
        fill(max(self.sweep - 1, 0), n, 0.85)          # ancien balayage : à peine moins vif
        # partie ancienne (après le spot) plus pâle
        if self.sweep < n - 1:
            p.setPen(QtGui.QPen(QtGui.QColor(90, 255, 160, 70), 1.6))
            p.drawPolyline(QtGui.QPolygonF(up[self.sweep:]))
            p.drawPolyline(QtGui.QPolygonF(down[self.sweep:]))
        k = max(self.sweep, 1)
        for width, color, alpha in ((7, (60, 255, 140), 34), (3.5, (90, 255, 160), 95),
                                    (1.4, (215, 255, 225), 240)):
            p.setPen(QtGui.QPen(QtGui.QColor(*color, alpha), width,
                                cap=QtCore.Qt.RoundCap, join=QtCore.Qt.RoundJoin))
            p.drawPolyline(QtGui.QPolygonF(up[:k]))
            p.drawPolyline(QtGui.QPolygonF(down[:k]))
        # spot du balayage : sur les deux branches
        if self.sweep:
            for spot in (up[self.sweep - 1], down[self.sweep - 1]):
                halo = QtGui.QRadialGradient(spot, 9)
                halo.setColorAt(0, QtGui.QColor(230, 255, 235, 240))
                halo.setColorAt(1, QtGui.QColor(90, 255, 160, 0))
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(halo)
                p.drawEllipse(spot, 9, 9)
            x = up[self.sweep - 1].x()
            p.setPen(QtGui.QPen(QtGui.QColor(120, 255, 170, 55), 1))
            p.drawLine(QtCore.QPointF(x, screen.top() + 4), QtCore.QPointF(x, bottom))
        # repères de fréquence
        p.setFont(QtGui.QFont("DejaVu Sans Mono", 6, QtGui.QFont.Bold))
        p.setPen(QtGui.QColor(150, 255, 190, 170))
        span = np.log(VOBU_FMAX / VOBU_FMIN)
        for f, label in ((200, "200"), (500, "500"), (1000, "1k"), (2000, "2k"), (3000, "3k")):
            x = screen.left() + 4 + np.log(f / VOBU_FMIN) / span * (screen.width() - 8)
            p.drawLine(QtCore.QPointF(x, bottom), QtCore.QPointF(x, bottom + 3))
            p.drawText(QtCore.QRectF(x - 14, bottom + 2, 28, 10), QtCore.Qt.AlignCenter, label)
        p.drawText(QtCore.QRectF(screen.left() + 8, screen.top() + 5, 190, 10),
                   QtCore.Qt.AlignLeft, "VOBULATION · " + ("ÉMISSION" if self.tx else "RÉCEPTION"))
        p.drawText(QtCore.QRectF(screen.right() - 80, screen.top() + 5, 72, 10),
                   QtCore.Qt.AlignRight, f"{self.noise_db:.0f} dB")

    @staticmethod
    def _cw_threshold(env):
        floor = float(np.percentile(env, 20))
        peak = float(np.percentile(env, 98))
        return floor + 0.45 * (peak - floor) if peak > floor * 2.5 + 1e-6 else float("inf")

    def _paint_cw(self, p, screen, cy):
        """Créneaux ON/OFF qui défilent, enveloppe brute en fond."""
        env = np.array(self.cw_env)
        thr = self._cw_threshold(env)
        peak = max(float(np.percentile(env, 99)), 1e-6)
        xs = screen.left() + np.arange(len(env)) * screen.width() / (len(env) - 1)
        amp = screen.height() / 2 * 0.8
        raw = QtGui.QPolygonF([QtCore.QPointF(float(x), float(cy + amp - 2 * amp * min(v / peak, 1.0)))
                               for x, v in zip(xs, env)])
        p.setPen(QtGui.QPen(QtGui.QColor(60, 255, 140, 45), 1.2))
        p.drawPolyline(raw)
        on = env > thr
        pts = []
        for i, (x, state) in enumerate(zip(xs, on)):
            y = cy - amp * 0.75 if state else cy + amp * 0.75
            if i and state != on[i - 1]:
                pts.append(QtCore.QPointF(float(x), pts[-1].y()))   # front vertical
            pts.append(QtCore.QPointF(float(x), float(y)))
        poly = QtGui.QPolygonF(pts)
        for width, color, alpha in ((7, (60, 255, 140), 30), (3.5, (90, 255, 160), 90),
                                    (1.4, (215, 255, 225), 235)):
            p.setPen(QtGui.QPen(QtGui.QColor(*color, alpha), width,
                                cap=QtCore.Qt.RoundCap, join=QtCore.Qt.MiterJoin))
            p.drawPolyline(poly)
        p.setPen(QtGui.QColor(150, 255, 190, 170))
        p.setFont(QtGui.QFont("DejaVu Sans Mono", 7, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(screen.left() + 6, screen.top() + 4, 60, 12),
                   QtCore.Qt.AlignLeft, "CW  ON")
        p.drawText(QtCore.QRectF(screen.left() + 6, screen.bottom() - 16, 60, 12),
                   QtCore.Qt.AlignLeft, "OFF")

    # --- dessin ----------------------------------------------------------
    def _paint_case(self):
        """Boîtier : tôle émaillée gris-vert martelée, peinte une seule fois."""
        pm = QtGui.QPixmap(self.size())
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(1, 1, self.W - 2, self.H - 2)
        g = QtGui.QLinearGradient(0, 0, 0, self.H)
        g.setColorAt(0, QtGui.QColor("#6d7d71"))
        g.setColorAt(0.5, QtGui.QColor("#56655a"))
        g.setColorAt(1, QtGui.QColor("#3c473f"))
        p.setPen(QtGui.QPen(QtGui.QColor("#1d231f"), 2))
        p.setBrush(g)
        p.drawRoundedRect(r, 14, 14)
        # martelé : petites taches claires et sombres
        rnd = random.Random(7300)
        p.setPen(QtCore.Qt.NoPen)
        for _ in range(900):
            x, y = rnd.uniform(6, self.W - 6), rnd.uniform(6, self.H - 6)
            c = QtGui.QColor(255, 255, 255, rnd.randint(6, 18)) if rnd.random() < 0.5 \
                else QtGui.QColor(0, 0, 0, rnd.randint(8, 22))
            p.setBrush(c)
            s = rnd.uniform(1.5, 4.5)
            p.drawEllipse(QtCore.QPointF(x, y), s, s)
        # liseré clair en haut (relief)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 50), 1.2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 12, 12)

        # cadre noir du tube
        bezel = QtCore.QRectF(12, 12, 250, self.H - 24)
        g = QtGui.QLinearGradient(bezel.topLeft(), bezel.bottomRight())
        g.setColorAt(0, QtGui.QColor("#3a3a3a"))
        g.setColorAt(1, QtGui.QColor("#0b0b0b"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.5))
        p.setBrush(g)
        p.drawRoundedRect(bezel, 16, 16)
        for cx, cy in ((bezel.left() + 10, bezel.top() + 10), (bezel.right() - 10, bezel.top() + 10),
                       (bezel.left() + 10, bezel.bottom() - 10), (bezel.right() - 10, bezel.bottom() - 10)):
            self._screw(p, cx, cy, 4.2)

        # panneau de droite : plaque gravée, voyant, boutons
        plate = QtCore.QRectF(274, 14, self.W - 286, 34)
        g = QtGui.QLinearGradient(plate.topLeft(), plate.bottomLeft())
        g.setColorAt(0, QtGui.QColor("#e9dfc4"))
        g.setColorAt(1, QtGui.QColor("#c9bb94"))
        p.setPen(QtGui.QPen(QtGui.QColor("#6b5d3c"), 1))
        p.setBrush(g)
        p.drawRoundedRect(plate, 3, 3)
        self._screw(p, plate.left() + 5, plate.center().y(), 2.2)
        self._screw(p, plate.right() - 5, plate.center().y(), 2.2)
        f = QtGui.QFont("DejaVu Serif", 6, QtGui.QFont.Bold)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.6)
        p.setFont(f)
        p.setPen(QtGui.QColor("#3b2f17"))
        p.drawText(plate.adjusted(0, 3, 0, -15), QtCore.Qt.AlignCenter, "OSCILLOSCOPE")
        f.setPointSizeF(5.5)
        p.setFont(f)
        p.drawText(plate.adjusted(0, 17, 0, -2), QtCore.Qt.AlignCenter, "MODULATION")

        f = QtGui.QFont("DejaVu Sans", 6, QtGui.QFont.Bold)
        f.setPointSizeF(5.5)
        p.setFont(f)
        p.setPen(QtGui.QColor("#e7e0cc"))
        p.drawText(QtCore.QRectF(274, 56, 50, 10), QtCore.Qt.AlignCenter, "PILOT")
        p.drawText(QtCore.QRectF(274, 108, 46, 10), QtCore.Qt.AlignCenter, "GAIN")
        p.drawText(QtCore.QRectF(324, 108, 46, 10), QtCore.Qt.AlignCenter, "TIME/DIV")
        p.drawText(QtCore.QRectF(274, 166, self.W - 286, 10), QtCore.Qt.AlignCenter,
                   "TYPE 7300-S")
        # bouton TIME/DIV fixe (décor) ; GAIN est dessiné à chaque fois
        self._knob(p, 347, 140, 0.35)
        p.end()
        self._case = pm

    @staticmethod
    def _screw(p, x, y, r):
        g = QtGui.QRadialGradient(x - r / 3, y - r / 3, r * 1.4)
        g.setColorAt(0, QtGui.QColor("#f2f2f2"))
        g.setColorAt(1, QtGui.QColor("#6e6e6e"))
        p.setPen(QtGui.QPen(QtGui.QColor("#2a2a2a"), 0.8))
        p.setBrush(g)
        p.drawEllipse(QtCore.QPointF(x, y), r, r)
        p.setPen(QtGui.QPen(QtGui.QColor("#333"), 1))
        p.drawLine(QtCore.QPointF(x - r * 0.7, y + r * 0.3), QtCore.QPointF(x + r * 0.7, y - r * 0.3))

    @staticmethod
    def _knob(p, x, y, turn):
        """Bouton bakélite noir à jupe striée, repère blanc ; turn de 0 à 1."""
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.drawEllipse(QtCore.QPointF(x + 2, y + 3), 19, 19)            # ombre
        g = QtGui.QRadialGradient(x - 6, y - 7, 26)
        g.setColorAt(0, QtGui.QColor("#4a4a4a"))
        g.setColorAt(1, QtGui.QColor("#080808"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawEllipse(QtCore.QPointF(x, y), 18, 18)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 35), 1))
        for i in range(24):                                             # stries
            a = i * 15 * np.pi / 180
            p.drawLine(QtCore.QPointF(x + 15 * np.cos(a), y + 15 * np.sin(a)),
                       QtCore.QPointF(x + 18 * np.cos(a), y + 18 * np.sin(a)))
        g = QtGui.QRadialGradient(x - 4, y - 5, 16)
        g.setColorAt(0, QtGui.QColor("#555"))
        g.setColorAt(1, QtGui.QColor("#111"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 0.8))
        p.drawEllipse(QtCore.QPointF(x, y), 12, 12)
        a = (-225 + 270 * turn) * np.pi / 180                           # repère
        p.setPen(QtGui.QPen(QtGui.QColor("#f4f1e6"), 2.2, cap=QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(x + 4 * np.cos(a), y + 4 * np.sin(a)),
                   QtCore.QPointF(x + 11 * np.cos(a), y + 11 * np.sin(a)))

    def _make_layers(self):
        """Décor fixe en deux images : dessous (écran + quadrillage), dessus (reflet)."""
        if self._case is None:
            self._paint_case()
        self._under = QtGui.QPixmap(self._case)
        p = QtGui.QPainter(self._under)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        # écran : verre légèrement bombé, phosphore vert
        screen = QtCore.QRectF(26, 24, 222, self.H - 48)
        path = QtGui.QPainterPath()
        path.addRoundedRect(screen, 14, 14)
        g = QtGui.QRadialGradient(screen.center(), screen.width() * 0.62)
        g.setColorAt(0, QtGui.QColor("#0d3320"))
        g.setColorAt(0.7, QtGui.QColor("#06180f"))
        g.setColorAt(1, QtGui.QColor("#020805"))
        p.fillPath(path, g)

        # quadrillage 8 × 6 divisions, sous-graduations sur les axes
        cols, rows = 8, 6
        dx, dy = screen.width() / cols, screen.height() / rows
        grid = QtGui.QColor(90, 190, 130, 55)
        p.setPen(QtGui.QPen(grid, 0.8))
        for i in range(1, cols):
            p.drawLine(QtCore.QPointF(screen.left() + i * dx, screen.top()),
                       QtCore.QPointF(screen.left() + i * dx, screen.bottom()))
        for j in range(1, rows):
            p.drawLine(QtCore.QPointF(screen.left(), screen.top() + j * dy),
                       QtCore.QPointF(screen.right(), screen.top() + j * dy))
        cx, cy = screen.center().x(), screen.center().y()
        p.setPen(QtGui.QPen(QtGui.QColor(110, 210, 150, 85), 0.8))
        for k in range(cols * 5 + 1):
            x = screen.left() + k * dx / 5
            p.drawLine(QtCore.QPointF(x, cy - 2.5), QtCore.QPointF(x, cy + 2.5))
        for k in range(rows * 5 + 1):
            y = screen.top() + k * dy / 5
            p.drawLine(QtCore.QPointF(cx - 2.5, y), QtCore.QPointF(cx + 2.5, y))

        p.end()
        self._over = QtGui.QPixmap(self.size())
        self._over.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(self._over)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        screen = QtCore.QRectF(26, 24, 222, self.H - 48)
        path = QtGui.QPainterPath()
        path.addRoundedRect(screen, 14, 14)
        p.setClipPath(path)
        # reflet du verre et vignettage
        g = QtGui.QLinearGradient(screen.topLeft(), screen.center())
        g.setColorAt(0, QtGui.QColor(255, 255, 255, 38))
        g.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        refl = QtGui.QPainterPath()
        refl.addEllipse(QtCore.QRectF(screen.left() - 40, screen.top() - 60,
                                      screen.width() * 0.9, screen.height() * 0.75))
        p.fillPath(refl, g)
        p.setClipping(False)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(path)

        p.end()

    def paintEvent(self, _):
        if self._case is None:
            self._paint_case()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # décor fixe (boîtier, écran, quadrillage) peint une seule fois
        if getattr(self, "_under", None) is None or self._under.size() != self.size():
            self._make_layers()
        p.drawPixmap(0, 0, self._under)
        screen = QtCore.QRectF(26, 24, 222, self.H - 48)
        path = QtGui.QPainterPath()
        path.addRoundedRect(screen, 14, 14)
        cy = screen.center().y()
        p.save()
        p.setClipPath(path)

        if self.cw_mode:                        # réception CW : manipulation
            self._paint_cw(p, screen, cy)
            self.traces = []
        elif self._vobu_on():                   # spectre balayé (émission ou réception)
            self._paint_vobu(p, screen)
            self.traces = []
        # traces : les plus anciennes pâlissent (rémanence)
        xs = screen.left() + np.arange(SHOW) * screen.width() / (SHOW - 1)
        amp = screen.height() / 2 * 0.92
        n = len(self.traces)
        for idx, y in enumerate(self.traces):
            age = n - 1 - idx                     # 0 = trace actuelle
            ys = cy - np.asarray(y) * amp
            # 1 point sur 2 (≈ 1 par pixel de l'écran) : même dessin, 2 × moins cher
            poly = QtGui.QPolygonF([QtCore.QPointF(a, b)
                                    for a, b in zip(xs[::2].tolist(), ys[::2].tolist())])
            fade = 0.45 ** age
            # trace actuelle : halo + cœur ; anciennes : un trait pâle
            # (traits épais à coins ronds = très coûteux, l'interface ramait)
            passes = (((2.0, (90, 255, 160), 110),) if age else
                      ((4.0, (70, 255, 150), 70), (1.4, (215, 255, 225), 230)))
            for width, color, alpha in passes:
                p.setPen(QtGui.QPen(QtGui.QColor(*color, int(alpha * fade)), width,
                                    cap=QtCore.Qt.FlatCap, join=QtCore.Qt.BevelJoin))
                p.drawPolyline(poly)

        p.restore()
        p.drawPixmap(0, 0, self._over)          # reflet du verre + bord (fixe)

        # voyant ambre : brille avec la voix
        lx, ly = 299, 82
        glow = 0.25 + 0.75 * self.level
        g = QtGui.QRadialGradient(lx, ly, 15)
        g.setColorAt(0, QtGui.QColor(255, 170, 40, int(170 * glow)))
        g.setColorAt(1, QtGui.QColor(255, 120, 0, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QtCore.QPointF(lx, ly), 15, 15)
        g = QtGui.QRadialGradient(lx - 2, ly - 2, 8)
        g.setColorAt(0, QtGui.QColor(255, 235, 170).darker(int(250 - 150 * glow)))
        g.setColorAt(1, QtGui.QColor(200, 90, 0).darker(int(260 - 120 * glow)))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#9a8a5a"), 2))             # bague chromée
        p.drawEllipse(QtCore.QPointF(lx, ly), 7, 7)

        # bouton GAIN : suit le gain automatique
        turn = float(np.clip(np.log10(self.gain) / np.log10(0.8 / FLOOR), 0, 1))
        self._knob(p, 297, 140, turn)
        p.end()


if __name__ == "__main__":                  # essai seul : python3 voice_scope.py
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = VoiceScope()
    src = subprocess.run(["pactl", "get-default-source"], capture_output=True,
                         text=True).stdout.strip()
    w.set_source(src)
    w.show()
    app.aboutToQuit.connect(w.stop)
    sys.exit(app.exec_())
