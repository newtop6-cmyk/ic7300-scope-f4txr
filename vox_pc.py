"""VOX côté PC : écoute le micro du PC (parec) et donne son niveau en dBFS
toutes les 30 ms. La fenêtre décide ensuite d'émettre ou non."""

import subprocess

import numpy as np
from PyQt5 import QtCore

RATE = 16000
BLOCK = 480                     # 30 ms


class VoxMonitor(QtCore.QThread):
    level = QtCore.pyqtSignal(float)            # dBFS du micro

    def __init__(self, source):
        super().__init__()
        self.source = source
        self._running = True
        self._proc = None

    def run(self):
        try:
            self._proc = subprocess.Popen(
                ["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                 f"--device={self.source}", "--latency-msec=30",
                 "--client-name=IC-7300 VOX"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return
        nbytes = BLOCK * 2
        while self._running:
            data = self._proc.stdout.read(nbytes)
            if len(data) < nbytes:
                break
            x = np.frombuffer(data, "<i2").astype(np.float32) / 32768
            rms = float(np.sqrt(np.mean(x * x))) + 1e-9
            self.level.emit(20 * np.log10(rms))

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self.wait(1000)
