"""Surveillance SSTV permanente (même fenêtre SSTV fermée), très légère.

Toutes les secondes, on regarde les 8 dernières secondes de son, ramenées à
8 kHz : fréquence instantanée (signal analytique), puis tops de synchro
(passages autour de 1200 Hz de quelques ms). Si les écarts entre tops tombent
régulièrement sur la période d'un mode SSTV connu, c'est une image : on donne
le mode et la fréquence réelle des tops (1200 Hz si la radio est bien calée ;
l'écart dit de combien il faut bouger pour tomber sur le correspondant).
"""

import numpy as np

import sstv

RATE8 = 8000
WINDOW_S = 8.0
MIN_SYNCS = 5                   # tops réguliers nécessaires dans la fenêtre
TOLERANCE = 0.012               # écart de période toléré (horloges un peu fausses)


class SstvWatch:
    def __init__(self, rate):
        self.rate = rate
        self.step = rate // RATE8
        self.buf = np.zeros(0, np.float32)
        self.pending = 0
        self.result = None              # (nom du mode, fréquence des tops en Hz) ou None

    def feed(self, x):
        """Ajoute du son ; renvoie True quand une nouvelle analyse a été faite."""
        n = len(x) // self.step * self.step
        if n:
            y = x[:n].reshape(-1, self.step).mean(axis=1)
            self.buf = np.concatenate((self.buf, y))[-int(WINDOW_S * RATE8):]
        self.pending += len(x)
        if self.pending < self.rate:            # une analyse par seconde
            return False
        self.pending = 0
        self.result = self._analyse() if len(self.buf) >= 4 * RATE8 else None
        return True

    def _analyse(self):
        x = self.buf - self.buf.mean()
        spec = np.fft.rfft(x)
        f = np.fft.rfftfreq(len(x), 1 / RATE8)
        band = (f > 1000) & (f < 2500)
        # assez d'énergie dans la bande SSTV par rapport au reste ?
        inside = float(np.mean(np.abs(spec[band]) ** 2))
        outside = float(np.mean(np.abs(spec[(f > 300) & (f < 3400) & ~band]) ** 2)) + 1e-12
        if inside < 1.5 * outside:
            return None
        spec[~band] = 0                          # signal analytique, bande 1000-2500 Hz
        analytic = np.fft.ifft(np.concatenate((spec, np.zeros(len(x) - len(spec)))) * 2)
        inst = np.diff(np.unwrap(np.angle(analytic))) * RATE8 / (2 * np.pi)
        per_ms = len(inst) // 8
        ms = np.median(inst[:per_ms * 8].reshape(per_ms, 8), axis=1)    # 1 valeur / ms
        low = ms < 1300
        starts, sync_hz = [], []
        i = 0
        while i < len(low):
            if low[i]:
                j = i
                while j < len(low) and low[j]:
                    j += 1
                if 3 <= j - i <= 25:
                    starts.append(i)
                    sync_hz.append(float(np.median(ms[i:j])))
                i = j
            else:
                i += 1
        if len(starts) < MIN_SYNCS:
            return None
        gaps = np.diff(starts).astype(float)
        best = None
        for mode in sstv.MODES:
            p = mode.period
            # chaque écart doit valoir un nombre entier de périodes (tops manqués)
            k = np.round(gaps / p)
            ok = (k >= 1) & (np.abs(gaps - k * p) <= np.maximum(3.0, TOLERANCE * p * k))
            score = int(ok.sum())
            # assez de tops réguliers : au moins 30 % des périodes de la fenêtre
            # (sinon une voix, avec ses syllabes, finit par « tomber juste »
            # sur les modes à période courte), et la majorité des écarts justes
            need = max(MIN_SYNCS - 1, int(0.3 * len(ms) / p))
            frac = score / len(gaps)
            if score >= need and frac >= 0.6 and (best is None or frac > best[0]):
                best = (frac, mode)
        if best is None:
            return None
        return best[1].name, float(np.median(sync_hz))
