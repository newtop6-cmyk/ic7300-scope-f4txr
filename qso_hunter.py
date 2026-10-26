"""Recherche automatique d'un QSO en français avec un signal fort.

Parcourt la portion phonie de la bande, 50 kHz à la fois, avec le scope de la
radio ; repère les signaux BLU forts ; sur chacun : se cale, vérifie le
S-mètre, écoute quelques secondes et fait reconnaître la langue par Whisper
(langue_worker.py, hors ligne). S'arrête sur le premier QSO en français."""

import collections
import json
import os
import subprocess
import tempfile
import threading

import numpy as np
from PyQt5 import QtCore

HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_PY = os.path.expanduser("~/claude/whisper/venv/bin/python")
WORKER = os.path.join(HERE, "langue_worker.py")

# portions phonie (Hz) et bande latérale d'usage
PHONE = {"160m": (1_843_000, 1_997_000, "LSB"),
         "80m": (3_603_000, 3_797_000, "LSB"),
         "60m": (5_352_000, 5_366_000, "USB"),
         "40m": (7_053_000, 7_197_000, "LSB"),
         "20m": (14_103_000, 14_347_000, "USB"),
         "17m": (18_112_000, 18_165_000, "USB"),
         "15m": (21_152_000, 21_447_000, "USB"),
         "12m": (24_932_000, 24_987_000, "USB"),
         "10m": (28_303_000, 28_997_000, "USB"),
         "6m": (50_103_000, 50_497_000, "USB")}
SWEEP_STEP = 1000               # balayage : 1 kHz par pas…
SWEEP_MS = 150                  # … toutes les 0,15 s (on voit la fréquence défiler)
SCAN_SWEEP_MS = 400             # SCAN : plus lent, arrêt dès qu'une station passe
BIN_HZ = 250                    # finesse de la carte de la bande
SETTLE_MS = 2500                # après un changement de fréquence (calage, réseau)
LISTEN_S = 10                   # arrêt de 10 s sur chaque signal BLU (son pour Whisper)
LISTEN_MAX_S = 25               # … prolongé jusqu'à 25 s si la voix n'est pas encore calée
STRONG = 6.0                    # signal : au moins 6 unités au-dessus du fond du scope
SSB_FILL = 0.45                 # forme BLU : ≥ 45 % des 2,4 kHz au-dessus du fond
FR_PROB = 0.55                  # Whisper doit être assez sûr que c'est du français
HOLD_S = 20                     # QSO français : on reste 20 s dessus avant de reprendre


class LangueWorker(QtCore.QObject):
    """Whisper dans un processus à part (son propre Python)."""
    result = QtCore.pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.proc = None

    def start(self):
        if self.proc and self.proc.poll() is None:
            return True
        try:
            self.proc = subprocess.Popen([WHISPER_PY, WORKER], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         text=True, bufsize=1)
        except OSError:
            return False
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _read(self):
        for line in self.proc.stdout:
            try:
                self.result.emit(json.loads(line))
            except ValueError:
                pass

    def ask(self, path):
        try:
            self.proc.stdin.write(path + "\n")
            self.proc.stdin.flush()
        except (OSError, AttributeError):
            self.result.emit({"lang": None, "prob": 0.0, "text": "", "error": "Whisper arrêté"})

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None


class QsoHunter(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(bool)          # True : on reste sur un QSO français
    found = QtCore.pyqtSignal(int, str)         # QSO français : fréquence, début du texte
    holding = QtCore.pyqtSignal(int)            # secondes restantes sur ce QSO (0 = fini)
    heard = QtCore.pyqtSignal(int, str)         # station écoutée : fréquence, LSB/USB

    def __init__(self, window, scan_only=False):
        super().__init__()
        self.w = window
        # scan_only : scan, arrêt 10 s tout rond sur chaque station BLU (sans
        # attendre le calage), langue reconnue ensuite par Whisper
        self.scan_only = scan_only
        self.language = False           # reconnaissance de langue disponible
        self.label = "Scan" if scan_only else "Recherche"
        self.worker = LangueWorker()
        self.worker.result.connect(self._on_language)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._step)
        self.active = False
        self.state = None
        self.target = None              # fréquence posée par la recherche
        # dernières fréquences posées : la radio les confirme avec du retard
        self.recent = collections.deque(maxlen=30)
        self.s_peak = 0
        self.wavfile = os.path.join(tempfile.gettempdir(), f"qso-fr-{os.getpid()}.raw")

    def _say(self, text):
        self.status.emit(text.replace("Recherche", self.label, 1))

    # --- commandes -------------------------------------------------------
    def start(self):
        w = self.w
        band = w.freq_hz and next((b for b in PHONE if b == w.band_of_freq()), None)
        if not band:
            self._say("Recherche : choisir d'abord une bande phonie (160 à 6 m)")
            self.finished.emit(False)
            return
        # le scan reconnaît aussi la langue (Whisper) ; sans Whisper il continue
        # quand même, sans reconnaissance
        self.language = self.worker.start()
        if not self.scan_only and not self.language:
            self._say("Recherche : Whisper introuvable (~/claude/whisper)")
            self.finished.emit(False)
            return
        self.low, self.high, self.side = PHONE[band]
        saved = getattr(self, "saved", None)
        self.saved = None
        self.band = band
        self.visited = set()
        self.active = True
        if w.mode_combo.currentText() != self.side:
            w.set_mode_by_hunter(self.side)
        if saved and saved["band"] == band and not self.scan_only:
            # nouvel appui après un QSO français : on passe au suivant, sans
            # réécouter les stations déjà faites
            self.visited = saved["visited"]
            self.queue = saved["queue"]
            self._say("Recherche : QSO français suivant…")
            if self.queue:
                self._next_candidate()
            else:
                self._start_sweep()
            return
        self._start_sweep()

    def stop(self, found=False):
        if not self.active:
            return
        self.active = False
        self.timer.stop()
        self.w.audio.capture = None
        self.holding.emit(0)
        self.finished.emit(found)

    def keep(self):
        """L'opérateur reste sur le QSO français trouvé : fin de la recherche."""
        if self.active and self.state == "hold":
            self._say(f"On reste sur le QSO français de {self.target / 1e6:.3f} MHz")
            self.holding.emit(0)
            self.stop(True)

    def resume(self):
        """Scan verrouillé sur un QSO français : on reprend le balayage."""
        if self.active and self.state == "hold":
            self.holding.emit(0)
            self._say("Scan : déverrouillé, reprise du balayage…")
            self._next_candidate()
            return True
        return False

    def shutdown(self):
        self.stop()
        self.worker.stop()

    # --- données venant de la fenêtre -----------------------------------
    def feed_scope(self, points, low, high):
        """Pendant le balayage : carte de la bande (moyenne par case de 250 Hz)."""
        if not self.active or self.state != "sweep":
            return
        n = len(points)
        freqs = low + (np.arange(n) + 0.5) * (high - low) / n
        idx = ((freqs - self.map_low) // BIN_HZ).astype(int)
        ok = (idx >= 0) & (idx < len(self.map_sum))
        np.add.at(self.map_sum, idx[ok], np.asarray(points, float)[ok])
        np.add.at(self.map_count, idx[ok], 1)

    def feed_meter(self, raw):
        if self.active and self.state == "listen":
            self.s_peak = max(self.s_peak, raw)

    # --- déroulement ---------------------------------------------------
    def is_own(self, hz):
        """Fréquence posée par la recherche (et pas par la main de l'opérateur) ?"""
        return hz in self.recent

    def _tune(self, hz):
        self.target = hz
        self.recent.append(hz)
        self.w.tune_to(hz)

    def _start_sweep(self):
        """Balayage visible de toute la portion phonie, kHz après kHz."""
        self.map_low = self.low - 30_000
        size = (self.high - self.low + 60_000) // BIN_HZ
        self.map_sum = np.zeros(size)
        self.map_count = np.zeros(size)
        self.state = "sweep"
        self.pos = self.low
        self._step()

    def _candidates(self):
        """Signaux BLU forts repérés : fréquences de porteuse probables."""
        seen = self.map_count > 0
        if seen.sum() < 20:
            return []
        avg = np.where(seen, self.map_sum / np.maximum(self.map_count, 1), np.nan)
        floor = np.nanpercentile(avg, 30)
        avg = np.nan_to_num(avg, nan=floor)
        width = int(round(2400 / BIN_HZ))                   # largeur d'une voix BLU
        smooth = np.convolve(avg, np.ones(width) / width, mode="same")
        found, taken = [], np.zeros(len(smooth), bool)
        above = avg > floor + STRONG / 2
        for i in np.argsort(smooth)[::-1]:
            if smooth[i] < floor + STRONG:
                break
            if taken[max(0, i - width):i + width].any():
                continue
            # une voix BLU occupe toute sa largeur ; une porteuse (CW, parasite) non
            band = above[max(0, i - width // 2):i + width // 2 + 1]
            if band.mean() < SSB_FILL:
                continue
            taken[max(0, i - width):i + width] = True
            # bords de la voix : la porteuse est ~300 Hz au-dessus du bord haut
            # en LSB, ~300 Hz sous le bord bas en USB
            lo = hi = i
            while lo > 0 and above[lo - 1] and i - lo < 2 * width:
                lo -= 1
            while hi < len(above) - 1 and above[hi + 1] and hi - i < 2 * width:
                hi += 1
            if self.side == "LSB":
                carrier = self.map_low + (hi + 1) * BIN_HZ + 300
            else:
                carrier = self.map_low + lo * BIN_HZ - 300
            # les stations sont presque toujours sur un kHz rond
            carrier = int(round(carrier / 1000) * 1000)
            if self.low - 3000 <= carrier <= self.high + 3000 \
                    and all(abs(carrier - v) > 2000 for v in self.visited):   # déjà écouté
                found.append((float(smooth[i] - floor), carrier))
        return [c for _, c in sorted(found, reverse=True)]

    def _step(self):
        if not self.active:
            return
        if self.state == "sweep":
            if self.scan_only and self.pos > self.low:
                hz = self._signal_here()
                if hz:                          # station sous le curseur : on s'arrête
                    self.resume = self.pos + 2000
                    self.visited.add(hz)
                    self.state = "settle"
                    self._tune(hz)
                    self.timer.start(SETTLE_MS)
                    return
            if self.scan_only and self.pos > self.high:
                self.visited.clear()            # bout de la portion : on recommence
                self._say("Recherche : fin de la portion phonie, nouveau balayage…")
                self._start_sweep()
                return
            if self.pos <= self.high:
                self._say(f"Recherche : balayage {self.pos / 1e6:.3f} MHz "
                                 f"({self.low / 1e6:.3f} → {self.high / 1e6:.3f})")
                self._tune(self.pos)
                self.pos += SWEEP_STEP
                self.timer.start(SCAN_SWEEP_MS if self.scan_only else SWEEP_MS)
                return
            self.queue = self._candidates()
            if not self.queue:
                if self.visited:
                    self.visited.clear()            # les stations changent : on recommence
                self._say("Recherche : aucun signal BLU nouveau, nouveau balayage…")
                self._start_sweep()
                return
            self._say(f"Recherche : {len(self.queue)} signal(aux) BLU à écouter")
            self._next_candidate()
        elif self.state == "settle":
            self.state = "listen"
            self.heard.emit(self.w.freq_hz or self.target, self.side)
            self.s_peak = 0
            self.listen_left = LISTEN_S
            self.listened = 0
            self.w.audio.capture = []
            self._listen_status()
            self.timer.start(1000)
        elif self.state == "hold":
            self.hold_left -= 1
            self.holding.emit(self.hold_left)
            if self.hold_left > 0:
                self.timer.start(1000)
                return
            self._say("Recherche : reprise du balayage…")
            self._next_candidate()
        elif self.state == "listen":
            self.listen_left -= 1
            self.listened += 1
            tuner = self.w.audio.ssb_tuner
            # voix entendue, ou calage qui vient de corriger et revérifie
            voice = tuner.normal.frames >= 3 or tuner.hold > 0
            calibrating = self.w.audio.ssb is not None and voice and not tuner.locked
            if self.scan_only:
                calibrating = False         # scan : 10 s tout rond
            if self.listen_left > 0 or (calibrating and self.listened < LISTEN_MAX_S):
                self._listen_status(calibrating and self.listen_left <= 0)
                self.timer.start(1000)
                return
            chunks = self.w.audio.capture or []
            self.w.audio.capture = None
            if not chunks or not self.language:
                self._next_candidate()
                return
            (np.concatenate(chunks) * 32767).astype("<i2").tofile(self.wavfile)
            self.state = "whisper"
            self._say(f"Recherche : quelle langue sur {self.target / 1e6:.3f} MHz ?")
            self.worker.ask(self.wavfile)

    def _listen_status(self, calibrating=False):
        where = self.w.freq_hz or self.target
        if calibrating:
            self._say(f"Recherche : {where / 1e6:.4f} MHz, calage de la voix…")
        else:
            self._say(f"Recherche : signal BLU sur {where / 1e6:.4f} MHz, "
                             f"arrêt {self.listen_left} s…")

    def _signal_here(self):
        """SCAN : station BLU à ± 1 kHz du curseur, pas encore écoutée."""
        w = self.w
        if w.avg is None or not w.scope_edges:
            return None
        cur = w.freq_hz or self.pos
        near = [hz for hz in find_signals(w.avg, *w.scope_edges, self.side)
                if abs(hz - cur) <= 1000 and self.low - 3000 <= hz <= self.high + 3000
                and all(abs(hz - v) > 2000 for v in self.visited)]
        return min(near, key=lambda hz: abs(hz - cur)) if near else None

    def _next_candidate(self):
        if self.scan_only:                      # SCAN : on reprend le balayage
            self.state = "sweep"
            self.pos = max(self.pos, getattr(self, "resume", self.low))
            self._step()
            return
        if not self.queue:
            self._start_sweep()
            return
        hz = self.queue.pop(0)
        self.visited.add(hz)
        self.state = "settle"
        self._tune(hz)
        self.timer.start(SETTLE_MS)

    def _on_language(self, res):
        if res.get("ready") or not self.active or self.state != "whisper":
            return
        lang, prob = res.get("lang"), res.get("prob", 0.0)
        where = f"{self.target / 1e6:.3f} MHz"
        if lang == "fr" and prob >= FR_PROB:
            text = res.get("text", "")
            self._say(f"QSO en français trouvé sur {where} !  « {text[:80]} »")
            if not self.scan_only:
                # on s'arrête dessus ; un nouvel appui ira au QSO français suivant
                self.saved = {"band": self.band,
                              "visited": set(self.visited) | {self.target},
                              "queue": list(self.queue)}
                self.state = "found"
                self.found.emit(self.target, text)
                self.stop(True)
                return
            # scan : verrouillé sur ce QSO, sans limite de temps ; l'appui
            # sur CHERCHER QSO FR déverrouille et reprend le scan
            self.state = "hold"
            self.found.emit(self.target, text)
            self.holding.emit(-1)
            return
        self._say(f"Recherche : {where} = {lang or '?'} ({prob:.0%}), suivant…")
        self._next_candidate()


def find_signals(points, low, high, side):
    """Stations visibles sur le scope (fréquences en Hz, triées).
    LSB/USB : voix BLU (porteuse estimée, arrondie au kHz) ;
    autre mode (CW…) : signaux étroits (arrondis à 10 Hz)."""
    points = np.asarray(points, float)
    n = len(points)
    if n < 20:
        return []
    step = (high - low) / n
    freqs = low + (np.arange(n) + 0.5) * step
    floor = np.percentile(points, 30)
    found = []
    if side in ("LSB", "USB"):
        width = max(1, int(round(2400 / step)))
        smooth = np.convolve(points, np.ones(width) / width, mode="same")
        above = points > floor + STRONG / 2
        taken = np.zeros(n, bool)
        for i in np.argsort(smooth)[::-1]:
            if smooth[i] < floor + STRONG:
                break
            if taken[max(0, i - width):i + width].any():
                continue
            if above[max(0, i - width // 2):i + width // 2 + 1].mean() < SSB_FILL:
                continue
            taken[max(0, i - width):i + width] = True
            lo = hi = i
            while lo > 0 and above[lo - 1] and i - lo < 2 * width:
                lo -= 1
            while hi < n - 1 and above[hi + 1] and hi - i < 2 * width:
                hi += 1
            carrier = (freqs[hi] + step / 2 + 300 if side == "LSB"
                       else freqs[lo] - step / 2 - 300)
            found.append(int(round(carrier / 1000) * 1000))
    else:
        half = max(1, int(round(300 / step)))          # pics séparés d'au moins 300 Hz
        for i in range(n):
            if points[i] < floor + STRONG:
                continue
            if points[i] < points[max(0, i - half):i + half + 1].max():
                continue
            found.append(int(round(freqs[i] / 10) * 10))
    return sorted(set(found))
