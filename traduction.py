"""Fenêtre TRADUCTION : écoute la réception de la radio, reconnaît la langue de
chaque phrase et l'affiche traduite en français, en direct (hors ligne).

Le son est découpé en phrases (pause de 0,5 s, ou 7 s au plus) ; chacune est
analysée par traduction_worker.py (Whisper + Argos, venv ~/claude/whisper).
Le français n'est pas retraduit ; il est affiché tel quel."""

import html
import json
import os
import queue
import subprocess
import tempfile
import threading
import time

import numpy as np
from PyQt5 import QtCore, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_PY = os.path.expanduser("~/claude/whisper/venv/bin/python")
WORKER = os.path.join(HERE, "traduction_worker.py")
RATE = 16000
MIN_SEG, MAX_SEG, PAUSE = 1.5, 7.0, 0.5

COLORS = {"en": "#38bdf8", "ru": "#f43f5e", "uk": "#facc15", "es": "#fb923c", "it": "#4ade80",
          "de": "#a78bfa", "pt": "#2dd4bf", "pl": "#f472b6", "nl": "#fdba74", "cs": "#60a5fa",
          "el": "#22d3ee", "tr": "#ef4444", "ro": "#eab308", "ja": "#fb7185", "fr": "#818cf8"}


class Translator(QtCore.QObject):
    """Écoute + analyse en arrière-plan ; résultats par signaux Qt."""
    result = QtCore.pyqtSignal(dict)
    status = QtCore.pyqtSignal(str)
    level = QtCore.pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.running = False
        self.paused = False             # émission en cours : on n'écoute pas
        self.proc = self.worker = None
        self.q = queue.Queue(maxsize=3)
        self.path = os.path.join(tempfile.gettempdir(), f"traduction-{os.getpid()}.f32")

    def start(self, source):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._capture, args=(source,), daemon=True).start()
        threading.Thread(target=self._analyse, daemon=True).start()

    def stop(self):
        self.running = False
        for p in (self.proc, self.worker):
            if p is not None and p.poll() is None:
                p.terminate()
        self.proc = self.worker = None

    def _capture(self, source):
        self.proc = subprocess.Popen(
            ["parec", "-d", source, "--format=s16le", f"--rate={RATE}", "--channels=1",
             "--raw", "--latency-msec=100", "--client-name=IC-7300 TRADUCTION"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        block = RATE // 10
        buf, history = [], []
        while self.running:
            raw = self.proc.stdout.read(block * 2)
            if not raw:
                break
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
            history = (history + [rms])[-100:]
            floor = float(np.percentile(history, 20))
            self.level.emit(min(1.0, rms / (max(history) + 1e-9)))
            if self.paused:
                buf = []
                continue
            buf.append(x)
            dur = len(buf) / 10
            n = int(PAUSE * 10)
            calm = len(buf) > n and all(float(np.sqrt(np.mean(b * b))) < floor * 1.6
                                        for b in buf[-n:])
            if (dur >= MIN_SEG and calm) or dur >= MAX_SEG:
                audio = np.concatenate(buf)
                buf = []
                m = float(np.max(np.abs(audio)))
                if m < 1e-4:
                    continue
                try:
                    self.q.put_nowait(audio * (0.9 / m))
                except queue.Full:
                    self.status.emit("En retard : une phrase a été sautée")

    def _analyse(self):
        self.status.emit("Chargement de la reconnaissance et de la traduction (≈ 15 s)…")
        try:
            self.worker = subprocess.Popen([WHISPER_PY, "-I", WORKER], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           text=True, bufsize=1)
            ready = self.worker.stdout.readline()
            if "ready" not in ready:
                self.status.emit("Traduction impossible : moteur non démarré")
                return
        except OSError as e:
            self.status.emit(f"Traduction impossible : {e}")
            return
        self.status.emit("J'écoute la réception…")
        while self.running:
            try:
                audio = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            t0 = time.time()
            self.status.emit("Analyse de la phrase…")
            try:
                audio.astype(np.float32).tofile(self.path)
                self.worker.stdin.write(self.path + "\n")
                out = json.loads(self.worker.stdout.readline() or "{}")
            except (OSError, ValueError):
                out = {}
            if out.get("text"):
                out["delay"] = time.time() - t0
                self.result.emit(out)
            self.status.emit(f"J'écoute la réception… (dernière analyse {time.time() - t0:.1f} s)")


class TranslationWindow(QtWidgets.QWidget):
    """Fenêtre de traduction : langue, texte d'origine, et français en gros."""
    closed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowTitle("TRADUCTION — réception IC-7300")
        self.resize(760, 420)
        self.font_pt = 15
        self.setStyleSheet("QWidget { background: #0b0f1a; color: #e8ecf6; }"
                           "QPushButton { background: #182036; border: 1px solid #26304a;"
                           " border-radius: 6px; padding: 4px 12px; font-weight: bold; }"
                           "QPushButton:hover { background: #26304a; }")
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("🌐 TRADUCTION EN FRANÇAIS")
        title.setStyleSheet("font: bold 13pt 'DejaVu Sans'; color: #ffb627;")
        top.addWidget(title)
        top.addStretch()
        self.level_bar = QtWidgets.QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setFixedSize(120, 10)
        self.level_bar.setStyleSheet("QProgressBar { background: #182036; border: none; }"
                                     "QProgressBar::chunk { background: #4ade80; }")
        top.addWidget(self.level_bar)
        lay.addLayout(top)
        self.text = QtWidgets.QTextBrowser()
        self.text.setStyleSheet("QTextBrowser { background: #121828; border: 1px solid #26304a;"
                                " border-radius: 8px; padding: 8px; }")
        lay.addWidget(self.text, 1)
        bottom = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: #8e98b3;")
        bottom.addWidget(self.status_label, 1)
        self.show_orig = QtWidgets.QCheckBox("texte d'origine")
        self.show_orig.setChecked(True)
        bottom.addWidget(self.show_orig)
        for label, fn in (("A−", lambda: self._zoom(-1)), ("A+", lambda: self._zoom(1)),
                          ("Effacer", self.text.clear), ("Fermer", self.close)):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(fn)
            bottom.addWidget(b)
        lay.addLayout(bottom)

    def _zoom(self, d):
        self.font_pt = max(9, min(30, self.font_pt + d))

    def set_status(self, text):
        self.status_label.setText(text)

    def set_level(self, v):
        self.level_bar.setValue(int(v * 100))

    def add(self, r):
        lang, name = r.get("lang", "?"), r.get("name", r.get("lang", "?"))
        col = COLORS.get(lang, "#cbd5e1")
        stamp = time.strftime("%H:%M:%S")
        orig = html.escape(r.get("text", ""))
        fr = r.get("fr")
        badge = (f"<span style='background:{col}; color:#0b0f1a; font-weight:bold;"
                 f" padding:1px 6px; border-radius:4px;'>&nbsp;{html.escape(name.upper())}&nbsp;</span>")
        head = (f"<div style='margin-top:10px; color:#8e98b3; font-size:9pt;'>{stamp} &nbsp;"
                f"{badge} &nbsp;{int(r.get('prob', 0) * 100)} %</div>")
        if fr is None:                              # déjà en français
            body = f"<div style='font-size:{self.font_pt}pt; color:#e8ecf6;'>{orig}</div>"
        else:
            body = ""
            if self.show_orig.isChecked():
                body += f"<div style='font-size:{max(9, self.font_pt - 5)}pt; color:#8e98b3;'>{orig}</div>"
            body += (f"<div style='font-size:{self.font_pt}pt; color:#ffe9b0; font-weight:bold;'>"
                     f"🇫🇷 {html.escape(fr)}</div>")
        self.text.append(head + body)
        sb = self.text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
