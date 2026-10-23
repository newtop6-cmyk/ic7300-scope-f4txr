"""Sifflement d'hétérodyne façon récepteur d'autrefois : aigu quand on est loin
de la fréquence du correspondant, il descend en s'approchant et s'éteint au
« battement nul » (calé). Joué sur les haut-parleurs du PC (pacat)."""

import subprocess
import threading

import numpy as np

RATE = 48000
BLOCK = 960                     # 20 ms
HZ_PER_HZ = 9.0                 # écart de 200 Hz → sifflement à 1800 Hz
MIN_PITCH = 60.0                # en dessous : battement nul, silence
LEVEL = 0.10                    # discret, sous le son de la radio
# Mode précis (écart mesuré) : la note est exactement au prorata de l'écart,
# plancher audible, et silence seulement au battement nul (±DEAD_HZ)
BASE_PITCH = 150.0              # note pour un écart minuscule
PRECISE_HZ_PER_HZ = 8.0         # +8 Hz de note par Hz d'écart
MAX_PITCH = 3500.0
DEAD_HZ = 4.0                   # calé à ±4 Hz : silence


class Whistle:
    def __init__(self):
        self.offset = 0.0               # écart (Hz) que montre l'aiguille
        self.on = False                 # sifflement voulu en ce moment
        self.precise = False            # True : offset = écart mesuré exact
        self._pitch = 0.0
        self._amp = 0.0
        self._phase = 0.0
        self._t = 0.0
        self._proc = None
        self._thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        try:
            self._proc = subprocess.Popen(
                ["pacat", "--playback", "--raw", "--format=s16le",
                 f"--rate={RATE}", "--channels=1", "--latency-msec=60",
                 "--client-name=IC-7300 sifflement"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._proc:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            self._proc.terminate()
            self._proc = None

    def _run(self):
        n = np.arange(1, BLOCK + 1)
        while self._running:
            if self.precise:
                err = abs(self.offset)
                pitch = min(MAX_PITCH, BASE_PITCH + err * PRECISE_HZ_PER_HZ)
                amp = LEVEL if self.on and err > DEAD_HZ else 0.0
                if amp and err < 2 * DEAD_HZ:        # s'éteint en douceur au calage
                    amp *= (err - DEAD_HZ) / DEAD_HZ
            else:
                pitch = abs(self.offset) * HZ_PER_HZ
                amp = LEVEL if self.on and pitch > MIN_PITCH else 0.0
                if amp and pitch < 250:              # s'éteint en douceur vers 0
                    amp *= (pitch - MIN_PITCH) / (250 - MIN_PITCH)
            # glissements progressifs (pas de clic)
            pitches = self._pitch + (pitch - self._pitch) * n / BLOCK
            amps = self._amp + (amp - self._amp) * n / BLOCK
            self._pitch, self._amp = pitch, amp
            # léger vibrato : la « respiration » des vieux oscillateurs
            t = self._t + n / RATE
            self._t = t[-1] % 1000
            pitches = pitches * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))
            phase = self._phase + 2 * np.pi * np.cumsum(pitches) / RATE
            self._phase = phase[-1] % (2 * np.pi)
            wave = np.sin(phase) + 0.25 * np.sin(2 * phase)   # un peu d'harmonique
            data = (wave * amps / 1.25 * 32767).astype("<i2").tobytes()
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except (OSError, AttributeError, ValueError):
                self._running = False
