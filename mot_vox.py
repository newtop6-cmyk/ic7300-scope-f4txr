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


# ce que Whisper écrit pour le numéro qui suit « vox » (VOX 1, VOX 2…)
NUM_WORDS = {"1": 1, "un": 1, "une": 1, "hein": 1, "one": 1, "1er": 1,
             "2": 2, "deux": 2, "de": 2, "two": 2,
             "3": 3, "trois": 3, "three": 3, "4": 4, "quatre": 4, "four": 4,
             "5": 5, "cinq": 5, "6": 6, "six": 6, "7": 7, "sept": 7, "set": 7,
             "8": 8, "huit": 8, "9": 9, "neuf": 9}


def vox_number(text):
    """« VOX 1 » → 1, « vox deux » → 2 ; None si ce n'est pas « VOX + numéro » seul."""
    words = re.findall(r"[a-z0-9àâéèêëîïôöùûüç]+", text.lower())
    if len(words) == 1:
        m = re.fullmatch(r"([a-z]+)(\d)", words[0])
        if m and (m.group(1) in VOX_WORDS or m.group(1) == "voix"):
            return int(m.group(2))
        return None
    if len(words) == 2 and (words[0] in VOX_WORDS or words[0] == "voix"):
        return NUM_WORDS.get(words[1])
    return None


# « TOP » : VOX armé jusqu'à « STOP » (comme un vrai VOX) ; « STOP » : arrêt
TOP_WORDS = {"top", "tope", "toppe", "topp", "tops", "taupe", "thop", "tob", "tôpe"}
STOP_WORDS = {"stop", "stoppe", "stope", "stopp", "stops", "stap", "stup", "stopé"}


def single_word(text, words):
    """Vrai si la parole est un seul mot de la liste (« Top ! », « stop. »)."""
    found = re.findall(r"[a-zàâéèêëîïôöùûüç]+", text.lower())
    return len(found) == 1 and found[0] in words


def is_top(text):
    return single_word(text, TOP_WORDS)


def is_stop(text):
    return single_word(text, STOP_WORDS)


def is_vox(text):
    words = re.findall(r"[a-zàâéèêëîïôöùûüç]+", text.lower())
    return len(words) == 1 and words[0] in VOX_WORDS


class MotVox(QtCore.QObject):
    heard = QtCore.pyqtSignal(str)
    word = QtCore.pyqtSignal()
    segment = QtCore.pyqtSignal(bytes)      # chaque parole courte, son brut 16 kHz

    def __init__(self):
        super().__init__()
        self.source = None
        self.threshold = -40.0              # dBFS, suit le bouton de sensibilité du VOX
        self.paused = False
        self.transcribe = True
        self.last_db = -90.0              # False : paroles envoyées sans Whisper
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
            if self.transcribe:
                self._start_worker()            # sinon chargé au premier besoin
            pre = deque(maxlen=PRE_BLOCKS)
            speech, quiet = [], 0
            noise = -90.0                       # bruit de fond du micro (suivi lent)
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
                self.last_db = max(db, self.last_db - 1.5)   # niveau affiché (retombe doucement)
                # bruit de fond : descend tout de suite, remonte de 1,7 dB/s.
                # Le seuil reste 12 dB au-dessus : avec du bruit (radio sur les
                # haut-parleurs, ventilation) la parole a encore une fin et le
                # mot « VOX » est entendu au lieu d'une « phrase trop longue »
                noise = db if db < noise else noise + 0.05
                level = max(self.threshold, noise + 12)
                self.effective = level
                loud = db > level
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
                        db = 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)
                        noise = db if db < noise else noise + 0.05
                        if db < max(self.threshold, noise + 12):
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
                        self.segment.emit(clip)
                        if not self.transcribe:
                            continue
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
