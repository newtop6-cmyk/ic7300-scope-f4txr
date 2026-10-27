"""Indicatif dit à la voix sur la fréquence écoutée (BLU, AM, FM).

Le son reçu de la radio est enregistré par tranches de 6 s ; Whisper « base »
(langue_worker.py, sur le PC) le transcrit et callsigns.calls_in_speech y
cherche les indicatifs épelés. Signal Qt : heard(liste d'indicatifs, texte).
"""

import json
import os
import subprocess
import tempfile
import threading

from PyQt5 import QtCore

import callsigns

HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_PY = os.path.expanduser("~/claude/whisper/venv/bin/python")
WORKER = os.path.join(HERE, "langue_worker.py")
CHUNK_S = 6


class VoiceCall(QtCore.QObject):
    heard = QtCore.pyqtSignal(list, str)

    def __init__(self):
        super().__init__()
        self.source = None
        self.running = False
        self.worker = None
        self.rec = None
        self.path = os.path.join(tempfile.gettempdir(), f"voix-indicatif-{os.getpid()}.raw")

    def start(self, source):
        self.source = source
        if self.running or not source:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.rec and self.rec.poll() is None:
            self.rec.terminate()

    def _loop(self):
        try:
            while self.running:
                try:
                    self.rec = subprocess.Popen(
                        ["timeout", str(CHUNK_S), "parec", "-d", self.source, "--raw",
                         "--format=s16le", "--rate=48000", "--channels=1",
                         "--latency-msec=50", "--client-name=IC-7300 indicatif"],
                        stdout=open(self.path, "wb"), stderr=subprocess.DEVNULL)
                    self.rec.wait()
                except OSError:
                    break
                if not self.running:
                    break
                if os.path.getsize(self.path) < 48000 * 2:      # moins d'1 s : rien
                    continue
                text = self._transcribe()
                if text:
                    calls = callsigns.calls_in_speech(text)
                    self.heard.emit(calls, text)
        finally:
            self.running = False
            if self.worker and self.worker.poll() is None:
                self.worker.terminate()
            self.worker = None

    def _transcribe(self):
        try:
            if self.worker is None or self.worker.poll() is not None:
                self.worker = subprocess.Popen([WHISPER_PY, WORKER], stdin=subprocess.PIPE,
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.DEVNULL, text=True, bufsize=1)
                self.worker.stdout.readline()                     # {"ready": true}
            self.worker.stdin.write(self.path + "\n")
            self.worker.stdin.flush()
            line = self.worker.stdout.readline()
            return json.loads(line).get("text", "") if line else ""
        except (OSError, ValueError):
            self.worker = None
            return ""
