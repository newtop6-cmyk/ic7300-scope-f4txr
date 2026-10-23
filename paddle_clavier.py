"""Paddle au clavier : Ctrl gauche = points, Ctrl droit = traits (iambique).

On entend la tonalité tout de suite sur le PC (pacat). Chaque lettre
reconnue est envoyée à la radio, qui l'émet elle-même en CW (commande CI-V
0x17) : le réseau jusqu'au Pi est trop lent pour manipuler point par point.
"""

import math
import subprocess
import threading

import numpy as np
from PyQt5 import QtCore

RATE = 48000
BLOCK = 240                     # 5 ms : précision du manipulateur
TONE_HZ = 650
LEVEL = 0.25
RAMP = int(RATE * 0.005)        # 5 ms de montée/descente (pas de clics)

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
    ".-.-.-": ".", "--..--": ",", "..--..": "?", "-..-.": "/", "-...-": "=",
    ".-.-.": "+", "-....-": "-",
}


class KeyboardPaddle(QtCore.QObject):
    char = QtCore.pyqtSignal(str)          # lettre (ou espace) à émettre
    unknown = QtCore.pyqtSignal(str)       # suite de points/traits inconnue

    def __init__(self, wpm=20):
        super().__init__()
        self.wpm = wpm
        self.dit_down = False
        self.dah_down = False
        self._latch_dit = False
        self._latch_dah = False
        self._proc = None
        self._thread = None
        self._running = False

    # --- appelé par la fenêtre ------------------------------------------
    def press(self, dah, down):
        if dah:
            self.dah_down = down
        else:
            self.dit_down = down
        if down:                        # mémoire du levier opposé (iambique)
            self._latch_dah = self._latch_dah or dah
            self._latch_dit = self._latch_dit or not dah

    def start(self):
        if self._running:
            return
        try:
            self._proc = subprocess.Popen(
                ["pacat", "--playback", "--raw", "--format=s16le",
                 f"--rate={RATE}", "--channels=1", "--latency-msec=25",
                 "--client-name=IC-7300 paddle"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.dit_down = self.dah_down = False
        if self._proc:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            self._proc.terminate()
            self._proc = None

    # --- manipulateur + tonalité ----------------------------------------
    def _run(self):
        self._latch_dit = self._latch_dah = False
        element = None                  # "." ou "-" en cours
        remaining = 0                   # échantillons restants de l'état courant
        keyed = False                   # tonalité en cours
        last = None                     # dernier élément émis
        letter = ""                     # points/traits de la lettre en cours
        silence = 0                     # échantillons sans élément
        word_sent = True
        phase = 0.0
        amp = 0.0
        step = 2 * np.pi * TONE_HZ / RATE
        while self._running:
            dit = int(RATE * 1.2 / self.wpm)
            out = np.zeros(BLOCK, np.float32)
            for i in range(BLOCK):
                if remaining <= 0:
                    if keyed:           # fin d'un élément : un blanc d'un point
                        keyed = False
                        remaining = dit
                        continue
                    # choix de l'élément suivant
                    nxt = None
                    if self.dit_down and self.dah_down:
                        nxt = "-" if last == "." else "."
                    elif last == "." and self._latch_dah:
                        nxt = "-"
                    elif last == "-" and self._latch_dit:
                        nxt = "."
                    elif self.dit_down or self._latch_dit:
                        nxt = "."
                    elif self.dah_down or self._latch_dah:
                        nxt = "-"
                    self._latch_dit = self._latch_dah = False
                    if nxt:
                        element = last = nxt
                        letter += nxt
                        keyed = True
                        remaining = dit if nxt == "." else 3 * dit
                        silence = 0
                        word_sent = False
                    else:
                        last = None
                        silence += 1
                        if letter and silence >= 2 * dit:      # fin de lettre
                            c = MORSE.get(letter)
                            if c:
                                self.char.emit(c)
                            else:
                                self.unknown.emit(letter)
                            letter = ""
                        elif not letter and not word_sent and silence >= 5 * dit:
                            self.char.emit(" ")                 # fin de mot
                            word_sent = True
                else:
                    remaining -= 1
                target = LEVEL if keyed else 0.0
                if amp < target:
                    amp = min(target, amp + LEVEL / RAMP)
                elif amp > target:
                    amp = max(target, amp - LEVEL / RAMP)
                out[i] = amp * math.sin(phase)
                phase += step
            phase %= 2 * np.pi
            try:
                self._proc.stdin.write((out * 32767).astype("<i2").tobytes())
                self._proc.stdin.flush()
            except (OSError, AttributeError, ValueError):
                break


class PaddleKeys(QtCore.QObject):
    """Filtre clavier de l'application : Ctrl gauche/droit → paddle."""

    def __init__(self, paddle):
        super().__init__()
        self.paddle = paddle

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            try:
                with open("/tmp/paddle-debug.log", "a") as f:
                    f.write(f"touche {int(kind)} key={event.key():x} scan={event.nativeScanCode()} obj={type(obj).__name__}\n")
            except OSError:
                pass
        if kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease) \
                and event.key() == QtCore.Qt.Key_Control:
            try:
                with open("/tmp/paddle-debug.log", "a") as f:
                    f.write(f"{kind} scan={event.nativeScanCode()} vk={event.nativeVirtualKey():x} rep={event.isAutoRepeat()} obj={type(obj).__name__}\n")
            except OSError:
                pass
            if not event.isAutoRepeat():
                dah = event.nativeScanCode() == 105 or event.nativeVirtualKey() == 0xFFE4
                self.paddle.press(dah, kind == QtCore.QEvent.KeyPress)
            return True
        return False
