"""Enregistrement vidéo de l'écran + son du trafic (micro, réception, émission).

Réglages de SimpleScreenRecorder (qui, en version 0.3.11, ne se pilote pas
depuis un autre programme) : H.264 crf 28 « faster », 15 images/s, son Vorbis
96 kb/s, fichier ~/MUSARDE-AAAA-MM-JJ_HH.MM.SS.mkv.

Le son est enregistré à part par parec (ffmpeg, occupé par l'image, en perdait
la fin) depuis la sortie « ic7300_enregistrement » du Scope ; l'image par ffmpeg
avec l'heure réelle de chaque image. À l'arrêt, les deux sont assemblés et calés
l'un sur l'autre (heure réelle), en arrière-plan : le Scope ne se fige pas.
"""

import os
import subprocess
import threading
import time

from PyQt5 import QtCore, QtWidgets

AUDIO_SOURCE = "ic7300_enregistrement.monitor"
OUT_DIR = os.path.expanduser("~")
OUT_DIR_BF = os.path.expanduser("~/REC BF")          # REC BF : son seul
TMP_DIR = os.path.expanduser("~/.cache/ic7300-scope/rec")
RATE, CHANNELS = 48000, 2


class ScreenRecorder(QtCore.QObject):
    changed = QtCore.pyqtSignal(bool, str)      # (enregistre ?, message)

    def __init__(self, audio_only=False):
        super().__init__()
        self.audio_only = audio_only            # REC BF : le son seul, sans l'écran
        self.video = self.audio = None
        self.path = None
        self.started = 0.0
        self.finishing = False

    @property
    def recording(self):
        proc = self.audio if self.audio_only else self.video
        return proc is not None and proc.poll() is None

    def elapsed(self):
        return time.time() - self.started if self.recording else 0.0

    def toggle(self):
        if self.finishing:
            self.changed.emit(False, "Vidéo en cours d'assemblage, un instant…")
        elif self.recording:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.recording or self.finishing:
            return
        os.makedirs(TMP_DIR, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H.%M.%S")
        name = f"REC-BF-{stamp}.ogg" if self.audio_only else f"MUSARDE-{stamp}.mkv"
        out = OUT_DIR_BF if self.audio_only else OUT_DIR
        os.makedirs(out, exist_ok=True)
        self.path = os.path.join(out, name)
        self.tmp_video = os.path.join(TMP_DIR, f"video-{stamp}.mkv")
        self.tmp_audio = os.path.join(TMP_DIR, f"son-{stamp}.raw")
        geo = QtWidgets.QApplication.primaryScreen().geometry()
        w, h = geo.width() // 2 * 2, geo.height() // 2 * 2      # H.264 : dimensions paires
        try:
            self.audio = subprocess.Popen(
                ["parec", "-d", AUDIO_SOURCE, "--raw", "--format=s16le", f"--rate={RATE}",
                 f"--channels={CHANNELS}", "--latency-msec=20",
                 "--client-name=IC-7300 enregistrement video"],
                stdout=open(self.tmp_audio, "wb"), stderr=subprocess.DEVNULL)
            if not self.audio_only:
                self.video = subprocess.Popen(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                     "-thread_queue_size", "1024", "-f", "x11grab", "-framerate", "15",
                     "-video_size", f"{w}x{h}", "-draw_mouse", "1",
                     "-i", f"{os.environ.get('DISPLAY', ':0')}+{geo.x()},{geo.y()}",
                     "-copyts",                     # heure réelle de chaque image (calage du son)
                     "-c:v", "libx264", "-preset", "faster", "-crf", "28", "-pix_fmt", "yuv420p",
                     self.tmp_video],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except OSError as e:
            self._kill()
            self.changed.emit(False, f"Enregistrement impossible : {e}")
            return
        self.started = time.time()
        QtCore.QTimer.singleShot(1500, self._check_started)
        self.changed.emit(True, f"Enregistrement : {os.path.basename(self.path)}")

    def _check_started(self):
        if self.audio_only:
            if self.audio is not None and self.audio.poll() is not None:  # parec arrêté
                self._kill()
                self.changed.emit(False, "Enregistrement du son arrêté (sortie "
                                         "« ic7300_enregistrement » absente ?)")
            return
        if self.video is not None and self.video.poll() is not None:     # ffmpeg arrêté
            err = (self.video.stderr.read() or b"").decode(errors="replace").strip()
            self._kill()
            self.changed.emit(False, "Enregistrement arrêté : " + (err.splitlines() or ["?"])[-1])

    def _kill(self):
        for p in (self.video, self.audio):
            if p is not None and p.poll() is None:
                p.terminate()
        self.video = self.audio = None

    def stop(self, wait=False):
        """Arrêt : l'image se referme, puis le son ; assemblage en arrière-plan
        (wait=True : on attend la fin, pour la fermeture du Scope)."""
        if not self.recording:
            return
        video, audio = self.video, self.audio
        self.video = self.audio = None
        self.finishing = True
        self.changed.emit(False, "Arrêt : enregistrement du fichier…" if self.audio_only
                          else "Arrêt : assemblage de la vidéo et du son…")
        job = threading.Thread(target=self._finish, args=(video, audio), daemon=not wait)
        job.start()
        if wait:
            job.join(timeout=120)

    def _finish(self, video, audio):
        if self.audio_only:
            return self._finish_audio(audio)
        try:
            try:
                video.stdin.write(b"q")             # ffmpeg referme l'image proprement
                video.stdin.flush()
                video.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                video.terminate()
                video.wait(timeout=5)
            t_end = time.time()
            audio.terminate()
            audio.wait(timeout=5)
            # début réel du son : fin moins sa durée (parec suit en temps réel)
            n = os.path.getsize(self.tmp_audio) // (2 * CHANNELS)
            a_start = t_end - n / RATE
            first = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                 "packet=pts_time", "-read_intervals", "%+#1", "-of", "csv=p=0",
                 self.tmp_video], capture_output=True, text=True).stdout.split()
            v_start = float(first[0]) if first else a_start
            offset = v_start - a_start              # > 0 : le son a commencé avant l'image
            audio_in = ["-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS)]
            if offset >= 0:
                audio_in = ["-ss", f"{offset:.3f}"] + audio_in
            else:
                audio_in = ["-itsoffset", f"{-offset:.3f}"] + audio_in
            done = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", self.tmp_video,
                 *audio_in, "-i", self.tmp_audio, "-map", "0:v", "-map", "1:a",
                 "-c:v", "copy", "-c:a", "libvorbis", "-b:a", "96k", "-shortest", self.path],
                capture_output=True, text=True)
            if done.returncode == 0 and os.path.exists(self.path):
                for tmp in (self.tmp_video, self.tmp_audio):
                    os.remove(tmp)
                size = os.path.getsize(self.path) / 1e6
                self.changed.emit(False, f"Vidéo enregistrée : {os.path.basename(self.path)} "
                                         f"({size:.0f} Mo, son calé à {offset * 1000:+.0f} ms)")
            else:
                self.changed.emit(False, "Assemblage raté : image et son gardés dans "
                                         f"{TMP_DIR} ({done.stderr.strip()[-120:]})")
        except Exception as e:                      # on prévient toujours
            self.changed.emit(False, f"Enregistrement : erreur à l'arrêt ({e})")
        finally:
            self.finishing = False

    def _finish_audio(self, audio):
        """REC BF : son brut → fichier Ogg Vorbis (le son entier, jusqu'à l'arrêt)."""
        try:
            audio.terminate()
            audio.wait(timeout=5)
            done = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS), "-i", self.tmp_audio,
                 "-c:a", "libvorbis", "-b:a", "128k", self.path],
                capture_output=True, text=True)
            if done.returncode == 0 and os.path.exists(self.path):
                os.remove(self.tmp_audio)
                n = os.path.getsize(self.path) / 1e6
                self.changed.emit(False, f"Son enregistré : {os.path.basename(self.path)} "
                                         f"({n:.1f} Mo)")
            else:
                self.changed.emit(False, f"Enregistrement du son raté : brut gardé dans "
                                         f"{TMP_DIR} ({done.stderr.strip()[-120:]})")
        except Exception as e:
            self.changed.emit(False, f"Enregistrement du son : erreur à l'arrêt ({e})")
        finally:
            self.finishing = False
