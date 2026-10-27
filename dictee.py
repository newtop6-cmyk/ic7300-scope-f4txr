"""DICTÉE : ce qui est dit au micro s'écrit dans le terminal (Claude).

Appui : écoute du micro ; fin toute seule après 1,5 s de silence (ou nouvel
appui). Whisper « small » transcrit, guidé par le vocabulaire radio de
l'utilisateur (dictee-vocabulaire.txt, appris sur ses QSO) ; les corrections
de dictee-corrections.txt sont appliquées, les indicatifs épelés
(« Fox-trot 4 Tango X-Ray Roméo ») deviennent « F4TXR ». Le texte est collé
dans le terminal ; s'il finit par « envoie », il est aussi validé (Entrée).
"""

import ctypes
import json
import os
import re
import subprocess
import tempfile
import threading
import time

import numpy as np
from PyQt5 import QtCore

HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_PY = os.path.expanduser("~/claude/whisper/venv/bin/python")
WORKER = os.path.join(HERE, "dictee_worker.py")
VOCAB_FILE = os.path.join(HERE, "dictee-vocabulaire.txt")
FIX_FILE = os.path.join(HERE, "dictee-corrections.txt")
RATE, BLOCK = 16000, 480                    # 30 ms
END_SILENCE_S = 1.5
WAIT_START_S = 8.0
MAX_S = 60.0
SEND_WORDS = ("envoie", "envoyer", "envoi", "valide", "valider")

PHONETIC = {
    "alpha": "A", "alfa": "A", "bravo": "B", "charlie": "C", "delta": "D", "echo": "E",
    "écho": "E", "fox": "F", "foxtrot": "F", "fox-trot": "F", "golf": "G", "hotel": "H",
    "hôtel": "H", "india": "I", "juliet": "J", "juliette": "J", "kilo": "K", "lima": "L",
    "mike": "M", "november": "N", "oscar": "O", "papa": "P", "québec": "Q", "quebec": "Q",
    "romeo": "R", "roméo": "R", "sierra": "S", "tango": "T", "uniform": "U",
    "victor": "V", "whisky": "W", "whiskey": "W", "x-ray": "X", "xray": "X",
    "yankee": "Y", "zulu": "Z"}
DIGITS = {"zéro": "0", "zero": "0", "un": "1", "deux": "2", "trois": "3", "quatre": "4",
          "cinq": "5", "six": "6", "sept": "7", "huit": "8", "neuf": "9"}


def spell_callsigns(text):
    """« Fox-trot 4 Tango X-Ray Roméo » → « F4TXR » (au moins 3 éléments,
    dont 2 mots de l'alphabet radio)."""
    text = re.sub(r"(?i)\bfox[\s-]*(trot|rot|road|trotte)\b", "Foxtrot", text)
    text = re.sub(r"(?i)\bx[\s-]ray\b", "Xray", text)
    tokens = re.split(r"(\s+)", text)
    out, run = [], []

    def flush():
        letters = [t for t in run if t[1] == "L"]
        if len(run) >= 3 and len(letters) >= 2:
            out.append("".join(t[2] for t in run))
        else:
            out.append(" ".join(t[0] for t in run))
        run.clear()
    for tok in tokens:
        if tok.isspace() or not tok:
            if not run:
                out.append(tok)
            continue
        bare = tok.rstrip(".,;:!?")
        trail = tok[len(bare):]
        core = bare.lstrip(".,;:!?").lower()
        if core in PHONETIC:
            run.append((bare, "L", PHONETIC[core]))
        elif core.isdigit() and len(core) == 1:
            run.append((bare, "D", core))
        elif core in DIGITS and run:
            run.append((bare, "D", DIGITS[core]))
        else:
            if run:
                flush()
                out.append(" ")
            out.append(tok)
            continue
        if trail:
            flush()
            out[-1] += trail
            out.append(" ")
    if run:
        flush()
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


def load_vocab():
    try:
        lines = [ln.strip() for ln in open(VOCAB_FILE, encoding="utf-8")]
    except OSError:
        return ""
    return " ".join(ln for ln in lines if ln and not ln.startswith("#"))[:800]


def apply_fixes(text):
    try:
        lines = open(FIX_FILE, encoding="utf-8").read().splitlines()
    except OSError:
        return text
    for ln in lines:
        if "=>" in ln and not ln.lstrip().startswith("#"):
            bad, good = (s.strip() for s in ln.split("=>", 1))
            if bad:
                text = re.sub(r"(?i)\b" + re.escape(bad) + r"\b", good, text)
    return text


# --- coller dans le terminal (X11, touches simulées par XTest) -------------
def _keys(combo):
    """Appuie puis relâche une combinaison, ex. ("Control_L", "Shift_L", "v")."""
    try:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
    except OSError:
        return False
    x11.XOpenDisplay.restype = ctypes.c_void_p
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return False
    dpy = ctypes.c_void_p(dpy)
    codes = []
    for name in combo:
        sym = x11.XStringToKeysym(name.encode())
        codes.append(x11.XKeysymToKeycode(dpy, ctypes.c_ulong(sym)))
    for c in codes:
        xtst.XTestFakeKeyEvent(dpy, c, 1, 0)
    for c in reversed(codes):
        xtst.XTestFakeKeyEvent(dpy, c, 0, 0)
    x11.XFlush(dpy)
    x11.XCloseDisplay(dpy)
    return True


class Dictee(QtCore.QObject):
    state = QtCore.pyqtSignal(str)          # "écoute", "parle", "texte", "fini"
    done = QtCore.pyqtSignal(str, str)      # (texte, erreur)

    def __init__(self):
        super().__init__()
        self.active = False
        self.stop_flag = False
        self.worker = None
        self.lock = threading.Lock()
        self.path = os.path.join(tempfile.gettempdir(), f"dictee-{os.getpid()}.raw")

    def start(self, source):
        if self.active or not source:
            return
        self.active, self.stop_flag = True, False
        threading.Thread(target=self._run, args=(source,), daemon=True).start()

    def stop(self):
        self.stop_flag = True

    def _run(self, source):
        text, err = "", ""
        try:
            clip = self._listen(source)
            if clip is None:
                err = "rien entendu"
            else:
                self.state.emit("texte")
                with open(self.path, "wb") as f:
                    f.write(clip)
                text = self._transcribe()
                text = spell_callsigns(apply_fixes(text))
                if not text:
                    err = "pas compris"
        except Exception as e:                      # on prévient toujours
            err = str(e)
        finally:
            self.active = False
            self.done.emit(text, err)

    def _listen(self, source):
        proc = subprocess.Popen(
            ["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
             f"--device={source}", "--latency-msec=30", "--client-name=IC-7300 DICTÉE"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            self._warm_worker()                     # Whisper se charge pendant qu'on parle
            blocks, levels = [], []
            for _ in range(10):                     # bruit de fond : 0,3 s
                b = proc.stdout.read(BLOCK * 2)
                levels.append(self._db(b))
            thr = max(float(np.median(levels)) + 12, -50)
            self.state.emit("écoute")
            t0, first, quiet = time.time(), None, 0
            while not self.stop_flag:
                b = proc.stdout.read(BLOCK * 2)
                if len(b) < BLOCK * 2:
                    break
                blocks.append(b)
                if self._db(b) > thr:
                    quiet = 0
                    if first is None:
                        first = len(blocks) - 1
                        self.state.emit("parle")
                else:
                    quiet += 1
                if first is None:
                    if time.time() - t0 > WAIT_START_S:
                        return None
                    blocks = blocks[-10:]           # garde 0,3 s avant la parole
                elif quiet * 0.03 >= END_SILENCE_S or len(blocks) * 0.03 > MAX_S:
                    break
            if first is None:
                return None
            return b"".join(blocks)
        finally:
            proc.terminate()

    @staticmethod
    def _db(b):
        x = np.frombuffer(b, "<i2").astype(np.float32) / 32768
        return 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)

    def _warm_worker(self):
        with self.lock:
            if self.worker is None or self.worker.poll() is not None:
                self.worker = subprocess.Popen(
                    [WHISPER_PY, "-I", WORKER], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
                self.worker_ready = False

    def _transcribe(self):
        with self.lock:
            w = self.worker
            if w is None or w.poll() is not None:
                self._warm_worker_unlocked()
                w = self.worker
            if not getattr(self, "worker_ready", False):
                w.stdout.readline()                 # {"ready": true}
                self.worker_ready = True
            w.stdin.write(json.dumps({"path": self.path, "prompt": load_vocab()}) + "\n")
            line = w.stdout.readline()
            if not line:                            # arrêté (inactivité) : on relance
                self.worker = None
                self._warm_worker_unlocked()
                self.worker.stdout.readline()
                self.worker_ready = True
                self.worker.stdin.write(json.dumps({"path": self.path,
                                                    "prompt": load_vocab()}) + "\n")
                line = self.worker.stdout.readline()
            return json.loads(line or "{}").get("text", "").strip()

    def _warm_worker_unlocked(self):
        self.worker = subprocess.Popen(
            [WHISPER_PY, "-I", WORKER], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.worker_ready = False

    def shutdown(self):
        if self.worker and self.worker.poll() is None:
            self.worker.terminate()


def split_send(text):
    """« … envoie » → (texte sans le mot, True) : à valider avec Entrée."""
    m = re.search(r"[\s,.;:!]*\b(" + "|".join(SEND_WORDS) + r")\b[\s.!]*$", text, re.I)
    if m:
        return text[:m.start()].strip(), True
    return text, False


def paste_into(wid, send):
    """Colle le presse-papiers dans le terminal wid (Ctrl+Maj+V), puis Entrée."""
    from console import activate
    activate(wid)
    time.sleep(0.25)
    ok = _keys(("Control_L", "Shift_L", "v"))
    if ok and send:
        time.sleep(0.15)
        _keys(("Return",))
    return ok
