"""Enregistrement vidéo de l'écran + son du trafic (micro, réception, émission).

Mêmes réglages que SimpleScreenRecorder (qui, en version 0.3.11, ne se pilote
pas depuis un autre programme) : H.264 crf 28 « faster », 15 images/s, son
Vorbis 96 kb/s pris sur la sortie « ic7300_enregistrement » du Scope, fichier
~/MUSARDE-AAAA-MM-JJ_HH.MM.SS.mkv. Arrêt propre : « q » envoyé à ffmpeg.
"""

import os
import subprocess
import time

from PyQt5 import QtCore, QtWidgets

AUDIO_SOURCE = "ic7300_enregistrement.monitor"
OUT_DIR = os.path.expanduser("~")


class ScreenRecorder(QtCore.QObject):
    changed = QtCore.pyqtSignal(bool, str)      # (enregistre ?, message)

    def __init__(self):
        super().__init__()
        self.proc = None
        self.path = None
        self.started = 0.0

    @property
    def recording(self):
        return self.proc is not None and self.proc.poll() is None

    def elapsed(self):
        return time.time() - self.started if self.recording else 0.0

    def toggle(self):
        self.stop() if self.recording else self.start()

    def start(self):
        if self.recording:
            return
        geo = QtWidgets.QApplication.primaryScreen().geometry()
        w, h = geo.width() // 2 * 2, geo.height() // 2 * 2      # H.264 : dimensions paires
        self.path = os.path.join(OUT_DIR, time.strftime("MUSARDE-%Y-%m-%d_%H.%M.%S.mkv"))
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-thread_queue_size", "1024", "-f", "x11grab", "-framerate", "15",
               "-video_size", f"{w}x{h}", "-draw_mouse", "1",
               "-i", f"{os.environ.get('DISPLAY', ':0')}+{geo.x()},{geo.y()}",
               "-thread_queue_size", "1024", "-f", "pulse", "-i", AUDIO_SOURCE,
               "-c:v", "libx264", "-preset", "faster", "-crf", "28", "-pix_fmt", "yuv420p",
               "-c:a", "libvorbis", "-b:a", "96k", self.path]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except OSError as e:
            self.proc = None
            self.changed.emit(False, f"Enregistrement impossible : {e}")
            return
        self.started = time.time()
        QtCore.QTimer.singleShot(1500, self._check_started)
        self.changed.emit(True, f"Enregistrement : {os.path.basename(self.path)}")

    def _check_started(self):
        if self.proc is not None and self.proc.poll() is not None:     # ffmpeg s'est arrêté
            err = (self.proc.stderr.read() or b"").decode(errors="replace").strip()
            self.proc = None
            self.changed.emit(False, "Enregistrement arrêté : " + (err.splitlines() or ["?"])[-1])

    def stop(self):
        if not self.recording:
            return
        try:
            self.proc.stdin.write(b"q")             # ffmpeg referme le fichier proprement
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.terminate()
        self.proc = None
        size = os.path.getsize(self.path) / 1e6 if os.path.exists(self.path) else 0
        self.changed.emit(False, f"Vidéo enregistrée : {os.path.basename(self.path)} "
                                 f"({size:.0f} Mo)")
