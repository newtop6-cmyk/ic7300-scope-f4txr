"""VOX VOCAL : écoute le micro du PC et repère le mot « VOX » dit seul.

Le son est découpé en paroles courtes (entre 0,2 et 1,5 s, suivies d'un
silence) ; chacune est transcrite par Whisper (mot_vox_worker.py, hors ligne).
Signal Qt : heard(texte) pour toute parole transcrite, word() quand c'est « VOX ».
Mettre .paused = True pendant le VOX et l'émission : rien n'est écouté.
"""

import json
import os
import re
import subprocess
import tempfile
import threading
from collections import deque

import numpy as np
from PyQt5 import QtCore

HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_PY = os.path.expanduser("~/claude/whisper/venv/bin/python")
WORKER = os.path.join(HERE, "mot_vox_worker.py")
RATE = 16000
BLOCK = 480                                 # 30 ms
PRE_BLOCKS = 8                              # 240 ms gardés avant le début de la parole
END_SILENCE = 10                            # 300 ms de silence = fin de la parole
MIN_BLOCKS, MAX_BLOCKS = 7, 50              # 0,2 s à 1,5 s
# ce que Whisper écrit quand on dit « vox »
VOX_WORDS = {"vox", "voxe", "box", "boxe", "fox", "vocs", "voks", "vax", "wox"}


def is_vox(text):
    words = re.findall(r"[a-zàâéèêëîïôöùûüç]+", text.lower())
    return len(words) == 1 and words[0] in VOX_WORDS


class MotVox(QtCore.QObject):
    heard = QtCore.pyqtSignal(str)
    word = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.source = None
        self.threshold = -40.0              # dBFS, suit le bouton de sensibilité du VOX
        self.paused = False
        self.running = False
        self.proc = None
        self.worker = None
        self.path = os.path.join(tempfile.gettempdir(), f"mot-vox-{os.getpid()}.raw")

    def start(self, source):
        if self.running or not source:
            return
        self.source = source
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _loop(self):
        try:
            self.proc = subprocess.Popen(
                ["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                 f"--device={self.source}", "--latency-msec=30",
                 "--client-name=IC-7300 VOX VOCAL"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self._start_worker()
            pre = deque(maxlen=PRE_BLOCKS)
            speech, quiet = [], 0
            while self.running:
                data = self.proc.stdout.read(BLOCK * 2)
                if len(data) < BLOCK * 2:
                    break
                if self.paused:
                    pre.clear()
                    speech, quiet = [], 0
                    continue
                x = np.frombuffer(data, "<i2").astype(np.float32) / 32768
                db = 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)
                loud = db > self.threshold
                if not speech:
                    pre.append(data)
                    if loud:
                        speech, quiet = list(pre), 0
                    continue
                speech.append(data)
                quiet = 0 if loud else quiet + 1
                if len(speech) > MAX_BLOCKS + PRE_BLOCKS + END_SILENCE:
                    speech = []                         # phrase trop longue : pas un ordre
                    while self.running and not self.paused:     # attendre le silence
                        data = self.proc.stdout.read(BLOCK * 2)
                        if len(data) < BLOCK * 2:
                            return
                        x = np.frombuffer(data, "<i2").astype(np.float32) / 32768
                        if 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9) \
                                < self.threshold:
                            quiet += 1
                            if quiet >= END_SILENCE:
                                break
                        else:
                            quiet = 0
                    pre.clear()
                    quiet = 0
                    continue
                if quiet >= END_SILENCE:
                    n = len(speech) - PRE_BLOCKS - END_SILENCE
                    clip, speech = b"".join(speech), []
                    pre.clear()
                    if n >= MIN_BLOCKS and not self.paused:
                        text = self._transcribe(clip)
                        if text and self.running and not self.paused:
                            self.heard.emit(text)
                            if is_vox(text):
                                self.word.emit()
        except OSError:
            pass
        finally:
            self.running = False
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            if self.worker and self.worker.poll() is None:
                self.worker.terminate()
            self.worker = None

    def _start_worker(self):
        self.worker = subprocess.Popen([WHISPER_PY, "-I", WORKER], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, bufsize=1)
        self.worker.stdout.readline()                   # {"ready": true}

    def _transcribe(self, clip):
        try:
            if self.worker is None or self.worker.poll() is not None:
                self._start_worker()
            with open(self.path, "wb") as f:
                f.write(clip)
            self.worker.stdin.write(self.path + "\n")
            return json.loads(self.worker.stdout.readline() or "{}").get("text", "")
        except (OSError, ValueError):
            return ""
