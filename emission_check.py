"""PROPRETÉ ÉMISSION : contrôle en direct de la qualité de ce qui est émis.

- son envoyé à la radio (pendant l'émission) ou micro après l'égaliseur (hors
  émission, pour répéter sans émettre) : spectre, crête, écrêtage, graves sous
  200 Hz, aigus au-delà de 3 kHz ;
- mesures de la radio pendant l'émission : ALC, compression, ROS ;
- largeur du signal émis vue sur le scope de la radio.
Verdict : PROPRE / À SURVEILLER / SALE, avec ce qu'il faut corriger."""

import subprocess
import time

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

RATE = 16000
BLOCK = 4096                    # ~0,26 s d'analyse
NFFT = 1024


class TxAnalyzer(QtCore.QThread):
    """Lit une source son (parec) et en tire les mesures de propreté."""
    measured = QtCore.pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.source = None
        self._want = None
        self._running = True
        self.proc = None

    def set_source(self, source):
        self._want = source

    def stop(self):
        self._running = False
        if self.proc:
            self.proc.terminate()
        self.wait(1500)

    def run(self):
        win = np.hanning(NFFT)
        freqs = np.fft.rfftfreq(NFFT, 1 / RATE)
        while self._running:
            if self._want != self.source or self.proc is None:
                if self.proc:
                    self.proc.terminate()
                    self.proc = None
                self.source = self._want
                if not self.source:
                    time.sleep(0.2)
                    continue
                try:
                    self.proc = subprocess.Popen(
                        ["parec", f"--device={self.source}", "--raw", "--format=s16le",
                         f"--rate={RATE}", "--channels=1", "--latency-msec=60",
                         "--client-name=IC-7300 propreté"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                except OSError:
                    time.sleep(1)
                    continue
            data = self.proc.stdout.read(BLOCK * 2)
            if not data or len(data) < BLOCK * 2:
                self.proc = None
                time.sleep(0.3)
                continue
            x = np.frombuffer(data, np.int16).astype(np.float32) / 32768
            peak = float(np.abs(x).max())
            rms = float(np.sqrt((x ** 2).mean()))
            clip = float((np.abs(x) > 0.97).mean() * 100)
            frames = x[: (len(x) // NFFT) * NFFT].reshape(-1, NFFT)
            spec = (np.abs(np.fft.rfft(frames * win, axis=1)) ** 2).mean(axis=0)
            total = float(spec.sum()) + 1e-12
            low = float(spec[freqs < 200].sum() / total * 100)
            high = float(spec[freqs > 3000].sum() / total * 100)
            cum = np.cumsum(spec) / total
            f_lo = float(freqs[np.searchsorted(cum, 0.01)])
            f_hi = float(freqs[min(len(freqs) - 1, np.searchsorted(cum, 0.99))])
            self.measured.emit({
                "peak_db": 20 * np.log10(peak + 1e-9), "rms_db": 20 * np.log10(rms + 1e-9),
                "clip": clip, "low": low, "high": high, "f_lo": f_lo, "f_hi": f_hi,
                "spec_db": (10 * np.log10(spec + 1e-12)).astype(np.float32),
                "freqs": freqs, "voice": rms > 0.01, "source": self.source})
        if self.proc:
            self.proc.terminate()


class _Row(QtWidgets.QWidget):
    """Une ligne de mesure : nom, valeur, voyant, conseil."""

    def __init__(self, name):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        self.lamp = QtWidgets.QLabel()
        self.lamp.setFixedSize(16, 16)
        self.name = QtWidgets.QLabel(name)
        self.name.setFixedWidth(150)
        self.name.setStyleSheet("color:#e8e2cc; font: bold 11pt 'DejaVu Sans';")
        self.value = QtWidgets.QLabel("—")
        self.value.setFixedWidth(110)
        self.value.setStyleSheet("color:#ffd98a; font: bold 12pt 'DejaVu Sans Mono';")
        self.advice = QtWidgets.QLabel("")
        self.advice.setStyleSheet("color:#c9c3ad; font: 10pt 'DejaVu Sans';")
        for w in (self.lamp, self.name, self.value, self.advice):
            lay.addWidget(w)
        lay.addStretch()
        self.set(None, "—", "")

    def set(self, level, value, advice):
        color = {0: "#22d65a", 1: "#ffb020", 2: "#ff2a1a"}.get(level, "#555")
        self.lamp.setStyleSheet(
            f"border-radius:8px; border:1px solid #111; background: qradialgradient("
            f"cx:0.35, cy:0.35, radius:0.8, fx:0.35, fy:0.35, stop:0 #ffffff, stop:0.3 {color}, "
            f"stop:1 #101010);")
        self.value.setText(value)
        self.advice.setText(advice)


class EmissionWindow(QtWidgets.QWidget):
    closed = QtCore.pyqtSignal()

    HOLD_S = 3.0                # une alerte reste affichée 3 s

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowTitle("PROPRETÉ ÉMISSION")
        self.resize(820, 600)
        self.setStyleSheet("background:#20251f;")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.verdict = QtWidgets.QLabel("PARLEZ AU MICRO…")
        self.verdict.setAlignment(QtCore.Qt.AlignCenter)
        self.verdict.setMinimumHeight(56)
        self.verdict.setWordWrap(True)
        lay.addWidget(self.verdict)
        self.mode = QtWidgets.QLabel("")
        self.mode.setAlignment(QtCore.Qt.AlignCenter)
        self.mode.setStyleSheet("color:#a9b0a6; font: 10pt 'DejaVu Sans';")
        lay.addWidget(self.mode)
        # spectre du son envoyé, bande normale 300–2700 Hz en vert
        self.plot = pg.PlotWidget()
        self.plot.setBackground("#0e120e")
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.setMenuEnabled(False)
        self.plot.setXRange(0, 4000, padding=0)
        self.plot.setYRange(-90, 0, padding=0)
        self.plot.setLabel("bottom", "Hz")
        self.plot.setLabel("left", "dB")
        band = pg.LinearRegionItem((300, 2700), movable=False, brush=(40, 200, 90, 40),
                                   pen=pg.mkPen((40, 200, 90, 120)))
        self.plot.addItem(band)
        self.curve = self.plot.plot(pen=pg.mkPen("#ffd98a", width=2), fillLevel=-90,
                                    brush=(255, 217, 138, 50))
        self.plot.setMinimumHeight(200)
        lay.addWidget(self.plot, 1)
        self.rows = {}
        for key, name in (("level", "Niveau micro"), ("clip", "Écrêtage"),
                          ("low", "Graves < 200 Hz"), ("high", "Aigus > 3 kHz"),
                          ("width", "Bande audio"), ("alc", "ALC (radio)"),
                          ("comp", "Compression"), ("swr", "ROS"),
                          ("rf", "Largeur émise")):
            self.rows[key] = _Row(name)
            lay.addWidget(self.rows[key])
        self.alerts = {}            # clé → (niveau, conseil, heure)
        self.tx = False
        self._set_verdict(None)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    # --- mesures ----------------------------------------------------------------
    def _judge(self, key, level, value, advice=""):
        self.rows[key].set(level, value, advice)
        if level is not None:
            old = self.alerts.get(key)
            now = time.monotonic()
            if level >= 1 or not old or now - old[2] > self.HOLD_S:
                self.alerts[key] = (level, advice, now)

    def on_audio(self, m):
        if not m["voice"]:
            self.rows["level"].set(None, f"{m['peak_db']:.0f} dB", "silence")
            self._refresh()
            return
        self.curve.setData(m["freqs"], np.maximum(m["spec_db"] - m["spec_db"].max(), -90))
        pk = m["peak_db"]
        self._judge("level", 2 if pk > -1 else 1 if pk < -24 else 0, f"{pk:.0f} dBFS",
                    "trop fort : baisser GAIN MICRO" if pk > -1 else
                    "faible : monter GAIN MICRO" if pk < -24 else "bon")
        c = m["clip"]
        self._judge("clip", 2 if c > 0.5 else 1 if c > 0.05 else 0, f"{c:.2f} %",
                    "son écrêté : baisser GAIN MICRO" if c > 0.05 else "aucun")
        lo = m["low"]
        self._judge("low", 2 if lo > 30 else 1 if lo > 15 else 0, f"{lo:.0f} %",
                    "trop de graves : réduire les basses (ÉGALISEUR)" if lo > 15 else "bon")
        hi = m["high"]
        self._judge("high", 2 if hi > 8 else 1 if hi > 3 else 0, f"{hi:.1f} %",
                    "aigus hors bande : réduire les aigus" if hi > 3 else "bon")
        f0, f1 = m["f_lo"], m["f_hi"]
        wide = f1 - f0
        self._judge("width", 1 if (f0 < 150 or f1 > 3100) else 0,
                    f"{f0:.0f}–{f1:.0f}", "déborde de 300–2700 Hz" if (f0 < 150 or f1 > 3100)
                    else "dans la bande")
        self.mode.setText(("ÉMISSION : son envoyé à la radio" if self.tx else
                           "RÉPÉTITION (sans émettre) : micro après l'égaliseur")
                          + f"   —   {m['source']}")
        self._refresh()

    def on_alc(self, percent):
        self._judge("alc", 2 if percent > 120 else 1 if percent > 100 else 0, f"{percent:.0f} %",
                    "surmodulation : baisser NIVEAU TX" if percent > 100 else "dans la zone")
        self._refresh()

    def on_comp(self, db):
        self._judge("comp", 2 if db > 20 else 1 if db > 15 else 0, f"{db:.0f} dB",
                    "trop comprimé : baisser NIVEAU COMP" if db > 15 else "bon")
        self._refresh()

    def on_swr(self, ratio):
        self._judge("swr", 2 if ratio > 2.5 else 1 if ratio > 1.8 else 0, f"{ratio:.1f}",
                    "antenne mal accordée : TUNE" if ratio > 1.8 else "bon")
        self._refresh()

    def on_rf(self, points, low, high):
        """Largeur du signal émis sur le scope de la radio (niveau à −20 unités du pic)."""
        pts = np.asarray(points, float)
        if len(pts) < 20:
            return
        floor = np.percentile(pts, 30)
        i = int(np.argmax(pts))
        if pts[i] - floor < 15:
            return                      # pas de signal émis visible
        thr = pts[i] - 20
        lo = hi = i
        while lo > 0 and pts[lo - 1] > max(thr, floor + 6):
            lo -= 1
        while hi < len(pts) - 1 and pts[hi + 1] > max(thr, floor + 6):
            hi += 1
        width = (hi - lo + 1) * (high - low) / len(pts)
        self._judge("rf", 2 if width > 3800 else 1 if width > 3100 else 0,
                    f"{width / 1000:.1f} kHz",
                    "trop large (débordement) : baisser NIVEAU TX / COMP" if width > 3100
                    else "propre (indicatif)")
        self._refresh()

    def set_tx(self, tx):
        self.tx = tx
        if not tx:
            for key in ("alc", "comp", "swr", "rf"):
                self.rows[key].set(None, "—", "en émission seulement")
                self.alerts.pop(key, None)
        self._refresh()

    def _refresh(self):
        now = time.monotonic()
        live = {k: v for k, v in self.alerts.items() if now - v[2] < self.HOLD_S + 2}
        worst = max((v[0] for v in live.values()), default=None)
        self._set_verdict(worst, [v[1] for v in live.values() if v[0] == worst and worst])

    def _set_verdict(self, worst, reasons=()):
        text, color = {None: ("PARLEZ AU MICRO…", "#555b55"), 0: ("ÉMISSION PROPRE", "#1f9d45"),
                       1: ("À SURVEILLER", "#c98a00"), 2: ("ÉMISSION SALE", "#c41d12")}[worst]
        if reasons:
            text += "  —  " + " ; ".join(dict.fromkeys(reasons))
        self.verdict.setText(text)
        self.verdict.setStyleSheet(
            f"color:white; background:{color}; border-radius:10px; "
            "font: bold 16pt 'DejaVu Sans'; padding:6px;")
