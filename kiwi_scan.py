"""Scan des QSO français par un récepteur KiwiSDR public (votre radio ne bouge pas).

Le KiwiSDR (Beaulieu, Isère ou Ain) donne la cascade du segment phonie de la
bande ; les signaux BLU y sont repérés, chacun est écouté 7 s sur le Kiwi et
sa langue reconnue par Whisper « base » sur le PC (langue_worker.py, son propre
processus). Résultats envoyés au fur et à mesure (signaux Qt) :
  status(texte), segment(bas Hz, haut Hz), testing(Hz), result(dict).
Limites de courtoisie : 1 h par session, 170 min par jour (fichier d'usage).
Essai seul : python3 kiwi_scan.py 40m
"""

import asyncio
import json
import os
import subprocess
import tempfile
import threading
import time

import numpy as np
from PyQt5 import QtCore

HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_PY = os.path.expanduser("~/claude/whisper/venv/bin/python")
WORKER = os.path.join(HERE, "langue_worker.py")
USAGE_FILE = os.path.join(os.path.expanduser("~/.config/ic7300-scope"), "kiwi-usage.json")

KIWIS = [   # du plus proche au plus lointain ; on passe au suivant s'il est plein ou muet
    {"nom": "Beaulieu-sur-Mer (06)", "ws": "ws://22669.proxy.kiwisdr.com:8073"},
    {"nom": "Isère", "ws": "ws://linkz.ddns.net:8073"},
    {"nom": "Maconnex, Ain (F4VUK)", "ws": "ws://samoro.hopto.org:32073"},
]
# segments phonie (Hz) et bande latérale
PHONE = {"160m": (1_843_000, 1_990_000, "lsb"), "80m": (3_600_000, 3_800_000, "lsb"),
         "60m": (5_351_000, 5_366_000, "usb"), "40m": (7_060_000, 7_195_000, "lsb"),
         "20m": (14_110_000, 14_350_000, "usb"), "17m": (18_111_000, 18_168_000, "usb"),
         "15m": (21_151_000, 21_450_000, "usb"), "12m": (24_931_000, 24_990_000, "usb"),
         "10m": (28_320_000, 29_000_000, "usb")}
LISTEN_S = 7.0          # écoute de chaque signal
RETEST_OTHER = 300      # s avant de retester une fréquence (autre langue / pas de parole)
RETEST_FR = 90          # s avant de revérifier un QSO français
FR_PROB = 0.55
MAX_SESSION = 3600
MAX_DAY = 170 * 60


def ssb_signals(spec, centre, span, lo, hi, side):
    """Signaux BLU (1,2 à 4 kHz de large) du segment → [(réglage Hz, marge dB)], du plus fort."""
    n = len(spec)
    hz = span / n
    i0 = max(0, int((lo - (centre - span / 2)) / hz))
    i1 = min(n, int((hi - (centre - span / 2)) / hz))
    if i1 - i0 < 20:
        return []
    seg = spec[i0:i1]
    noise = float(np.median(seg))
    above = seg > noise + 6
    gap = max(1, int(400 / hz))
    out, k, m = [], 0, len(seg)
    while k < m:
        if not above[k]:
            k += 1
            continue
        d = f = j = k
        while j < m and (above[j] or j - f <= gap):
            if above[j]:
                f = j
            j += 1
        width = (f - d + 1) * hz
        if 1200 <= width <= 4000:
            f_lo = centre - span / 2 + (i0 + d) * hz
            f_hi = centre - span / 2 + (i0 + f + 1) * hz
            tune = f_hi + 150 if side == "lsb" else f_lo - 150
            out.append((int(round(tune / 100) * 100), float(seg[d:f + 1].max() - noise)))
        k = j
    return sorted(out, key=lambda x: -x[1])


class Busy(Exception):
    pass


class KiwiScan(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    segment = QtCore.pyqtSignal(int, int)
    testing = QtCore.pyqtSignal(int)
    result = QtCore.pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.band = None
        self.running = False
        self.thread = None
        self.tested = {}            # kHz → (heure, français ?)
        self.worker = None

    # --- marche / arrêt -----------------------------------------------------
    def start(self, band):
        if band not in PHONE:
            self.status.emit(f"Scan : pas de segment phonie connu pour {band or 'cette fréquence'}")
            return False
        self.band = band
        if self.running:
            return True
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def set_band(self, band):
        if band in PHONE:
            self.band = band

    def stop(self):
        self.running = False

    # --- reconnaissance de la langue (Whisper base, processus à part) -------
    def _language(self, pcm, rate):
        if self.worker is None or self.worker.poll() is not None:
            self.worker = subprocess.Popen([WHISPER_PY, WORKER], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           text=True, bufsize=1)
            json.loads(self.worker.stdout.readline() or "{}")       # {"ready": true}
        x = np.asarray(pcm, np.float32)
        n48 = int(len(x) * 48000 / rate)
        y = np.interp(np.linspace(0, len(x) - 1, n48), np.arange(len(x)), x)
        path = os.path.join(tempfile.gettempdir(), f"kiwi-scan-{os.getpid()}.raw")
        y.clip(-32768, 32767).astype("<i2").tofile(path)
        self.worker.stdin.write(path + "\n")
        self.worker.stdin.flush()
        line = self.worker.stdout.readline()
        return json.loads(line) if line else {"lang": None, "prob": 0.0}

    def _stop_worker(self):
        if self.worker and self.worker.poll() is None:
            self.worker.terminate()
        self.worker = None

    # --- usage du jour ------------------------------------------------------
    @staticmethod
    def _usage(add=0.0):
        day = time.strftime("%Y-%m-%d")
        try:
            with open(USAGE_FILE) as f:
                u = json.load(f)
        except (OSError, ValueError):
            u = {}
        if u.get("day") != day:
            u = {"day": day, "s": 0.0}
        if add:
            u["s"] += add
            try:
                os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
                with open(USAGE_FILE, "w") as f:
                    json.dump(u, f)
            except OSError:
                pass
        return u["s"]

    # --- boucle -------------------------------------------------------------
    def _run(self):
        try:
            for kiwi in KIWIS:
                if not self.running:
                    break
                if self._usage() > MAX_DAY:
                    self.status.emit("Scan : limite du jour du récepteur atteinte (≈3 h), reprise demain")
                    break
                self.status.emit(f"Scan : connexion au récepteur {kiwi['nom']}…")
                try:
                    asyncio.run(self._session(kiwi))
                    break
                except Busy as e:
                    self.status.emit(f"Scan : {kiwi['nom']} indisponible ({e}), essai suivant")
                except Exception as e:                 # réseau…
                    self.status.emit(f"Scan : {kiwi['nom']} injoignable ({type(e).__name__})")
            else:
                self.status.emit("Scan : aucun récepteur KiwiSDR disponible")
        finally:
            self.running = False
            self._stop_worker()
            self.testing.emit(0)
            self.status.emit("Scan arrêté")

    async def _session(self, kiwi):
        import aiohttp
        ts = int(time.time())
        started = time.time()
        R = {"rate": None, "wf": [], "cfg": None, "clip": None, "end": False, "ready": False,
             "busy": None}
        async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0 (IC-7300 Scope F4TXR, écoute seule)"}) as s:
            snd = await asyncio.wait_for(s.ws_connect(
                f"{kiwi['ws']}/kiwi/{ts}/SND", max_msg_size=0, heartbeat=30), 15)
            wf = await asyncio.wait_for(s.ws_connect(
                f"{kiwi['ws']}/kiwi/{ts}/W/F", max_msg_size=0, heartbeat=30), 15)
            try:
                for ws in (snd, wf):
                    await ws.send_str("SET auth t=kiwi p=")
                    await ws.send_str("SET ident_user=F4TXR")

                async def read_snd():
                    try:
                        async for m in snd:
                            if m.type != aiohttp.WSMsgType.BINARY:
                                break
                            tag, d = m.data[:3], m.data[3:]
                            if tag == b"MSG":
                                txt = d[1:].decode(errors="replace")
                                if txt.startswith(("too_busy", "badp=1", "down", "redirect")) \
                                        and not txt.startswith("too_busy=0"):
                                    R["busy"] = txt[:40]
                                    break
                                if "audio_rate=" in txt:
                                    R["rate"] = int(txt.split("audio_rate=")[1].split()[0])
                                    await snd.send_str(f"SET AR OK in={R['rate']} out=44100")
                                    await snd.send_str("SET compression=0")
                                    await snd.send_str("SET agc=1 hang=0 thresh=-100 slope=6 "
                                                       "decay=1000 manGain=50")
                                    R["ready"] = True
                            elif tag == b"SND" and R["clip"] is not None:
                                R["clip"].append(np.frombuffer(d[7:], ">i2").astype(np.int16))
                    finally:
                        R["end"] = True

                async def read_wf():
                    try:
                        async for m in wf:
                            if m.type == aiohttp.WSMsgType.TEXT:
                                continue
                            if m.type != aiohttp.WSMsgType.BINARY:
                                break
                            tag, d = m.data[:3], m.data[3:]
                            if tag == b"W/F" and R["cfg"] is not None:
                                R["wf"].append(np.frombuffer(d[13:], np.uint8).astype(np.float32) - 255)
                                del R["wf"][:-80]
                    finally:
                        R["end"] = True

                async def keepalive():
                    while not R["end"]:
                        await asyncio.sleep(5)
                        for ws in (snd, wf):
                            try:
                                await ws.send_str("SET keepalive")
                            except Exception:
                                R["end"] = True

                tasks = [asyncio.create_task(c()) for c in (read_snd, read_wf, keepalive)]
                for _ in range(150):
                    if R["ready"] or R["end"] or R["busy"]:
                        break
                    await asyncio.sleep(0.2)
                if R["busy"] or not R["ready"]:
                    raise Busy(R["busy"] or "pas de réponse")
                self.status.emit(f"Scan : récepteur {kiwi['nom']} connecté")

                async def wait(sec):
                    end = time.time() + sec
                    while time.time() < end and self.running and not R["end"]:
                        await asyncio.sleep(0.1)

                while self.running and not R["end"]:
                    if time.time() - started > MAX_SESSION:
                        self.status.emit("Scan : 1 h de session, pause par courtoisie (relancez si besoin)")
                        self.running = False
                        break
                    if self._usage() + time.time() - started > MAX_DAY:
                        self.status.emit("Scan : limite du jour du récepteur atteinte (≈3 h)")
                        self.running = False
                        break
                    band = self.band
                    lo, hi, side = PHONE[band]
                    self.segment.emit(lo, hi)
                    z = 0
                    while z < 14 and 30e6 / 2 ** (z + 1) >= (hi - lo) * 1.05:
                        z += 1
                    cf = (lo + hi) / 2
                    await wf.send_str(f"SET zoom={z} cf={cf / 1000:.3f}")
                    await wf.send_str("SET maxdb=0 mindb=-100")
                    await wf.send_str("SET wf_speed=4")
                    await wf.send_str("SET wf_comp=0")
                    R["cfg"] = (cf, 30e6 / 2 ** z)
                    R["wf"] = []
                    self.status.emit(f"Scan : analyse du segment phonie {band}…")
                    await wait(3.5)
                    if len(R["wf"]) < 8 or band != self.band:
                        continue
                    mean = 10 * np.log10(np.mean(10 ** (np.array(R["wf"]) / 10), axis=0))
                    now = time.time()
                    cands = []
                    for f, margin in ssb_signals(mean, R["cfg"][0], R["cfg"][1], lo, hi, side):
                        last = self.tested.get(round(f / 1000))
                        if last and now - last[0] < (RETEST_FR if last[1] else RETEST_OTHER):
                            continue
                        cands.append((f, margin))
                    if not cands:
                        self.status.emit(f"Scan {band} : rien de nouveau, nouveau passage dans 15 s")
                        self.testing.emit(0)
                        await wait(15)
                        continue
                    self.status.emit(f"Scan {band} : {len(cands)} signal(aux) à écouter")
                    for f, margin in cands[:6]:
                        if not self.running or R["end"] or band != self.band:
                            break
                        mode = "lsb" if side == "lsb" else "usb"
                        await snd.send_str(f"SET mod={mode} low_cut={-2700 if mode == 'lsb' else 200} "
                                           f"high_cut={-200 if mode == 'lsb' else 2700} "
                                           f"freq={f / 1000:.3f}")
                        self.testing.emit(f)
                        await asyncio.sleep(0.8)
                        R["clip"] = []
                        await wait(LISTEN_S)
                        chunks, R["clip"] = R["clip"], None
                        if not self.running or not chunks:
                            break
                        pcm = np.concatenate(chunks)
                        res = await asyncio.get_running_loop().run_in_executor(
                            None, self._language, pcm, R["rate"])
                        ok = res.get("lang") == "fr" and (res.get("prob") or 0) >= FR_PROB
                        self.tested[round(f / 1000)] = (time.time(), ok)
                        self.result.emit({"hz": f, "band": band, "mode": mode.upper(),
                                          "lang": res.get("lang"), "prob": res.get("prob") or 0.0,
                                          "fr": ok, "margin": round(margin, 1),
                                          "text": res.get("text", ""), "t": time.time()})
                for t in tasks:
                    t.cancel()
            finally:
                self._usage(time.time() - started)
                for ws in (snd, wf):
                    try:
                        await ws.close()
                    except Exception:
                        pass


if __name__ == "__main__":                  # essai : python3 kiwi_scan.py 40m
    import sys
    app = QtCore.QCoreApplication([])
    k = KiwiScan()
    k.status.connect(print)
    k.testing.connect(lambda f: f and print("  écoute", f / 1000, "kHz"))
    k.result.connect(lambda r: print("  →", r["hz"] / 1000, r["lang"], r["prob"],
                                     "FRANÇAIS" if r["fr"] else "", r["text"][:60]))
    k.start(sys.argv[1] if len(sys.argv) > 1 else "40m")
    QtCore.QTimer.singleShot(int(float(sys.argv[2]) * 1000) if len(sys.argv) > 2 else 90000,
                             lambda: (k.stop(), QtCore.QTimer.singleShot(3000, app.quit)))
    app.exec_()
