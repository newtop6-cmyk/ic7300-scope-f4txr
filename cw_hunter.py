"""Décodage CW automatique : balaye la portion CW de la bande, repère les
signaux CW (porteuses étroites), se cale dessus puis les décode 20 s chacun."""

import collections

import numpy as np
from PyQt5 import QtCore

# portions CW (Hz)
CW_BANDS = {"160m": (1_810_000, 1_838_000), "80m": (3_500_000, 3_570_000),
            "60m": (5_351_500, 5_354_000), "40m": (7_000_000, 7_040_000),
            "30m": (10_100_000, 10_130_000), "20m": (14_000_000, 14_070_000),
            "17m": (18_068_000, 18_095_000), "15m": (21_000_000, 21_070_000),
            "12m": (24_890_000, 24_915_000), "10m": (28_000_000, 28_070_000),
            "6m": (50_000_000, 50_100_000)}
SWEEP_STEP = 1000               # balayage visible : 1 kHz…
SWEEP_MS = 150                  # … toutes les 0,15 s
BIN_HZ = 100                    # carte de la bande assez fine pour la CW
STRONG = 8.0                    # au moins 8 unités au-dessus du fond du scope
NARROW_BINS = 5                 # une CW tient dans ~500 Hz (sinon : BLU, data…)
CW_PITCH = 600                  # note CW de la radio (Hz)
SETTLE_MS = 1800                # après un saut : son revenu, note mesurable
HOLD_S = 20                     # décodage de chaque signal


class CwHunter(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    countdown = QtCore.pyqtSignal(int)          # secondes restantes (0 = pas d'arrêt)
    finished = QtCore.pyqtSignal()

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._step)
        self.active = False
        self.state = None
        self.target = None
        self.recent = collections.deque(maxlen=40)

    def is_own(self, hz):
        return hz in self.recent

    def start(self):
        band = self.w.band_of_freq()
        if band not in CW_BANDS:
            self.status.emit("Décodage CW : choisir d'abord une bande (160 à 6 m)")
            self.finished.emit()
            return
        self.low, self.high = CW_BANDS[band]
        self.band = band
        self.visited = []
        self.active = True
        if self.w.mode_combo.currentText() != "CW":
            self.w.set_mode_by_hunter("CW")
        self._start_sweep()

    def stop(self):
        if not self.active:
            return
        self.active = False
        self.timer.stop()
        self.countdown.emit(0)
        self.finished.emit()

    # --- données venant de la fenêtre ---------------------------------
    def feed_scope(self, points, low, high):
        if not self.active or self.state != "sweep":
            return
        n = len(points)
        freqs = low + (np.arange(n) + 0.5) * (high - low) / n
        idx = ((freqs - self.map_low) // BIN_HZ).astype(int)
        ok = (idx >= 0) & (idx < len(self.map_sum))
        np.add.at(self.map_sum, idx[ok], np.asarray(points, float)[ok])
        np.add.at(self.map_count, idx[ok], 1)

    # --- déroulement ---------------------------------------------------
    def _tune(self, hz):
        hz = int(round(hz / 10) * 10)
        self.target = hz
        self.recent.append(hz)
        self.w.tune_to(hz)

    def _start_sweep(self):
        self.map_low = self.low - 30_000
        size = (self.high - self.low + 60_000) // BIN_HZ
        self.map_sum = np.zeros(size)
        self.map_count = np.zeros(size)
        self.state = "sweep"
        self.pos = self.low
        self.countdown.emit(0)
        self._step()

    def _candidates(self):
        """Signaux CW : pics étroits nettement au-dessus du fond."""
        seen = self.map_count > 0
        if seen.sum() < 20:
            return []
        avg = np.where(seen, self.map_sum / np.maximum(self.map_count, 1), np.nan)
        floor = np.nanpercentile(avg, 40)
        avg = np.nan_to_num(avg, nan=floor)
        above = avg > floor + STRONG / 2
        found = []
        for i in range(1, len(avg) - 1):
            if avg[i] < floor + STRONG or avg[i] < avg[i - 1] or avg[i] < avg[i + 1]:
                continue
            lo = hi = i
            while lo > 0 and above[lo - 1]:
                lo -= 1
            while hi < len(avg) - 1 and above[hi + 1]:
                hi += 1
            if hi - lo + 1 > NARROW_BINS:
                continue                            # trop large : pas de la CW
            hz = self.map_low + (i + 0.5) * BIN_HZ
            if not (self.low <= hz <= self.high):
                continue
            if any(abs(hz - v) < 400 for v in self.visited):
                continue
            found.append((float(avg[i] - floor), hz))
        # du plus fort au plus faible, sans doublons proches
        out = []
        for _, hz in sorted(found, reverse=True):
            if all(abs(hz - o) > 300 for o in out):
                out.append(hz)
        return out

    def _step(self):
        if not self.active:
            return
        if self.state == "sweep":
            if self.pos <= self.high:
                self.status.emit(f"Décodage CW : balayage {self.pos / 1e6:.3f} MHz "
                                 f"({self.low / 1e6:.3f} → {self.high / 1e6:.3f})")
                self._tune(self.pos)
                self.pos += SWEEP_STEP
                self.timer.start(SWEEP_MS)
                return
            self.queue = self._candidates()
            if not self.queue:
                self.visited = []
                self.status.emit("Décodage CW : aucun signal CW, nouveau balayage…")
                self._start_sweep()
                return
            self.status.emit(f"Décodage CW : {len(self.queue)} signal(aux) CW repéré(s)")
            self._next()
        elif self.state == "settle":
            # calage fin : la note entendue doit être celle de la radio
            dec = self.w.audio.decoders["cw"]
            shift = dec.pitch - CW_PITCH
            if 15 < abs(shift) < 450:
                self._tune(self.target + shift)
            dec.set_pitch(CW_PITCH)
            dec.auto_pitch = True
            self.state = "hold"
            self.left = HOLD_S
            self.countdown.emit(self.left)
            self.status.emit(f"Décodage CW sur {self.target / 1e6:.5f} MHz")
            self.timer.start(1000)
        elif self.state == "hold":
            self.left -= 1
            self.countdown.emit(self.left)
            if self.left > 0:
                self.timer.start(1000)
                return
            self._next()

    def _next(self):
        if not self.queue:
            self._start_sweep()
            return
        hz = self.queue.pop(0)
        self.visited.append(hz)
        self.state = "settle"
        self._tune(hz)
        dec = self.w.audio.decoders["cw"]
        dec._spectrum = None            # nouvelle note à mesurer
        dec.auto_pitch = True
        self.status.emit(f"Décodage CW : calage sur {hz / 1e6:.5f} MHz…")
        self.timer.start(SETTLE_MS)
