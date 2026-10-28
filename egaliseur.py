"""Égaliseur de la voix d'émission (micro du PC → radio).

Chemin du son :  micro → parec → filtres (ce fichier) → pacat → sortie
virtuelle « ic7300_micro_eq » ; la liaison d'émission du Scope prend le son
sur cette sortie (ic7300_micro_eq.monitor) au lieu du micro brut.

Les réglages sont dans egaliseur-voix.ini (à côté de ce fichier). On peut
les changer dans la fenêtre ÉGALISEUR ou en modifiant le fichier à la main :
ils sont relus tout seuls dès que le fichier change (moins d'une seconde).
Essai seul : python3 egaliseur.py   (ouvre la fenêtre, traite le micro par défaut)
"""

import configparser
import json
import os
import subprocess
import threading
import time

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from scipy import signal

RATE = 48000
BLOCK = 960                     # 20 ms
SINK = "ic7300_micro_eq"
MONITOR = SINK + ".monitor"
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "egaliseur-voix.ini")
MY_PRESETS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "egaliseur-mes-reglages.json")
MINE = "★ "                     # repère des réglages enregistrés par l'utilisateur
BANDS = (100, 200, 400, 700, 1000, 1500, 2000, 2500, 3000)
ENV = {**os.environ, "LC_ALL": "C"}
CEILING = 10 ** (-1 / 20)       # limiteur : crêtes tenues à -1 dBFS
LIM_RELEASE_MS = 60
REC_SECONDS = 15                # durée de l'enregistrement de test

COMP_TEXT = """
[compresseur]
# Compresseur : remonte les passages faibles de la voix et retient les
# pointes → modulation plus dense, plus « dynamique », plus présente.
# oui = en service ; non = coupé
actif = {on}
# seuil en dB (-40 à 0) : au-dessus, la voix est compressée. Plus bas = plus de compression.
seuil_db = {thr:g}
# taux (1 à 10) : 1 = rien, 3-4 = naturel et punchy, 6-10 = très serré
taux = {ratio:g}
# rattrapage en dB (0 à 20) : remonte le tout après compression
rattrapage_db = {makeup:g}
# attaque (ms) : vitesse de réaction aux pointes (2 à 30)
attaque_ms = {attack:g}
# relâchement (ms) : retour après une pointe (50 à 500). Court = plus agressif.
relachement_ms = {release:g}
# porte anti-souffle (dB, -70 à -30) : sous ce niveau le rattrapage s'efface,
# pour ne pas remonter le bruit de fond entre les phrases. Plus haut = plus de silence.
porte_db = {gate:g}
"""
PORTE_TEXT = """
[porte]
# Porte anti-souffle : quand on ne parle pas, le souffle de fond est baissé
# en douceur ; dès qu'on parle, la voix passe entière (rien ne change au timbre).
# oui = en service ; non = coupée
actif = {on}
# seuil en dB (-75 à -30) : sous ce niveau, c'est du souffle. Plus haut = coupe plus.
seuil_db = {thr}
# baisse du souffle en dB (6 à 40)
attenuation_db = {floor}
"""
DEBR_TEXT = """
[debruitage]
# Débruiteur doux : apprend le souffle pendant les silences et le retire en
# continu, même sous la voix (latence ~21 ms). oui = en service ; non = coupé
actif = {on}
# baisse maximale du souffle en dB (3 à 24) : plus haut = plus propre, mais
# trop haut peut donner un léger « gazouillis »
force_db = {force}
# niveau sous lequel on considère que c'est du silence (souffle), en dB
seuil_silence_db = {quiet}
"""
GATE_HOLD_MS = 250              # porte : reste ouverte 250 ms après la voix (fins de mots)
GATE_RELEASE_MS = 120           # … puis se referme en douceur

COMP_DEFAULT = dict(comp_on=True, thr=-28.0, ratio=4.0, makeup=10.0, attack=5.0, release=150.0,
                    gate=-50.0)

DEFAULT_TEXT = """\
# ============================================================
#  ÉGALISEUR DE LA VOIX D'ÉMISSION — IC-7300 Scope (F4TXR)
# ============================================================
# Ce fichier est relu tout seul dès qu'il est enregistré :
# change une valeur, enregistre (Ctrl+S), écoute le résultat.
# La fenêtre ÉGALISEUR du Scope écrit aussi dans ce fichier.
# Une ligne qui commence par # est un commentaire (ignorée).

[general]
# oui = égaliseur en service ; non = voix brute (aucun filtre)
actif = oui
# gain général après les filtres, en dB (-12 à +12)
gain_general_db = -4
# passe-haut : coupe les graves sous cette fréquence (Hz). 0 = pas de coupure.
# En BLU, 100 à 300 Hz : moins de grondement, plus de punch.
passe_haut_hz = 300
# passe-bas : coupe les aigus au-dessus (Hz). 0 = pas de coupure.
# La BLU de l'IC-7300 passe environ jusqu'à 2900 Hz.
passe_bas_hz = 2900
# largeur des bandes (Q) : 0.7 = large et doux, 2 = étroit et précis
largeur_q = 1.2

[bandes]
# niveau de chaque bande en dB, de -12 (moins) à +12 (plus)
#  100-200 Hz : rondeur, grondement
#  400-700 Hz : voix « en boîte » si trop fort
#  1000-2000 Hz : présence, intelligibilité
#  2500-3000 Hz : clarté, sifflantes
100 = -12
200 = -8
400 = -4
700 = -2
1000 = 1
1500 = 4
2000 = 6
2500 = 5
3000 = 2
""" + COMP_TEXT.format(on="oui", thr=-28, ratio=4, makeup=10, attack=5, release=150, gate=-50)

PRESETS = {
    "Plat": dict(hp=0, lp=0, gain=0, bands=[0] * 9),
    "DX (percutant)": dict(hp=250, lp=2800, gain=0,
                           bands=[-12, -6, -3, -2, 0, 3, 5, 4, 2]),
    "Voix grave → percutante": dict(hp=300, lp=2900, gain=-4,
                                    bands=[-12, -8, -4, -2, 1, 4, 6, 5, 2]),
    "Chaud (QSO local)": dict(hp=100, lp=2900, gain=0,
                              bands=[2, 3, 1, -1, 0, 1, 1, 0, -2]),
    "Clair": dict(hp=150, lp=2900, gain=0,
                  bands=[-3, -2, -1, -2, 0, 2, 3, 3, 1]),
    # moins métallique : présence (2–3 kHz) adoucie, un peu de chaleur
    # (400–700 Hz), compression douce et lente (la compression forte durcit)
    "Naturel (anti-métallique)": dict(hp=150, lp=2700, gain=0, q=0.9,
                                      bands=[-4, -1, 1, 1, 0, 0, -2, -4, -6],
                                      comp_on=True, thr=-26.0, ratio=3.0, makeup=7.0,
                                      attack=12.0, release=250.0, gate=-50.0),
}


# --- réglages ---------------------------------------------------------------
def load_settings():
    if not os.path.exists(CONFIG):
        with open(CONFIG, "w") as f:
            f.write(DEFAULT_TEXT)
    cp = configparser.ConfigParser()
    try:
        cp.read(CONFIG)
    except configparser.Error:
        cp = configparser.ConfigParser()
        cp.read_string(DEFAULT_TEXT)

    def num(section, key, default):
        try:
            return float(cp.get(section, key).replace(",", "."))
        except (configparser.Error, ValueError):
            return default
    on = cp.get("general", "actif", fallback="oui").strip().lower() in (
        "oui", "yes", "1", "on", "vrai", "true")
    return dict(
        on=on,
        gain=max(-12.0, min(12.0, num("general", "gain_general_db", 0))),
        hp=max(0.0, num("general", "passe_haut_hz", 0)),
        lp=max(0.0, num("general", "passe_bas_hz", 0)),
        q=max(0.3, min(5.0, num("general", "largeur_q", 1.2))),
        bands=[max(-12.0, min(12.0, num("bandes", str(b), 0))) for b in BANDS],
        comp_on=cp.get("compresseur", "actif", fallback="oui").strip().lower() in (
            "oui", "yes", "1", "on", "vrai", "true"),
        thr=max(-40.0, min(0.0, num("compresseur", "seuil_db", COMP_DEFAULT["thr"]))),
        ratio=max(1.0, min(10.0, num("compresseur", "taux", COMP_DEFAULT["ratio"]))),
        makeup=max(0.0, min(20.0, num("compresseur", "rattrapage_db",
                                      COMP_DEFAULT["makeup"]))),
        attack=max(1.0, min(50.0, num("compresseur", "attaque_ms", COMP_DEFAULT["attack"]))),
        release=max(20.0, min(1000.0, num("compresseur", "relachement_ms",
                                          COMP_DEFAULT["release"]))),
        gate=max(-70.0, min(-30.0, num("compresseur", "porte_db", COMP_DEFAULT["gate"]))),
        gate_on=cp.get("porte", "actif", fallback="oui").strip().lower() in (
            "oui", "yes", "1", "on", "vrai", "true"),
        gate_thr=max(-75.0, min(-30.0, num("porte", "seuil_db", -50.0))),
        gate_floor=max(6.0, min(40.0, num("porte", "attenuation_db", 24.0))),
        dn_on=cp.get("debruitage", "actif", fallback="non").strip().lower() in (
            "oui", "yes", "1", "on", "vrai", "true"),
        dn_force=max(3.0, min(24.0, num("debruitage", "force_db", 12.0))),
        dn_quiet=max(-75.0, min(-35.0, num("debruitage", "seuil_silence_db", -55.0))))


def save_settings(s):
    """Réécrit le fichier en gardant ses commentaires : seules les valeurs changent."""
    if not os.path.exists(CONFIG):
        load_settings()
    values = {"actif": "oui" if s["on"] else "non",
              "gain_general_db": f"{s['gain']:g}", "passe_haut_hz": f"{s['hp']:g}",
              "passe_bas_hz": f"{s['lp']:g}", "largeur_q": f"{s['q']:g}"}
    values.update({str(b): f"{v:g}" for b, v in zip(BANDS, s["bands"])})
    comp = {"actif": "oui" if s["comp_on"] else "non", "seuil_db": f"{s['thr']:g}",
            "taux": f"{s['ratio']:g}", "rattrapage_db": f"{s['makeup']:g}",
            "attaque_ms": f"{s['attack']:g}", "relachement_ms": f"{s['release']:g}",
            "porte_db": f"{s.get('gate', -50):g}"}
    porte = {"actif": "oui" if s.get("gate_on", True) else "non",
             "seuil_db": f"{s.get('gate_thr', -50):g}",
             "attenuation_db": f"{s.get('gate_floor', 24):g}"}
    debr = {"actif": "oui" if s.get("dn_on") else "non",
            "force_db": f"{s.get('dn_force', 12):g}",
            "seuil_silence_db": f"{s.get('dn_quiet', -55):g}"}
    out = []
    section = ""
    found_comp = False
    found_porte = False
    found_debr = False
    with open(CONFIG) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1]
                found_comp = found_comp or section == "compresseur"
                found_porte = found_porte or section == "porte"
                found_debr = found_debr or section == "debruitage"
            key = line.split("=", 1)[0].strip()
            table = {"compresseur": comp, "porte": porte, "debruitage": debr}.get(section, values)
            if "=" in line and not line.lstrip().startswith("#") and key in table:
                out.append(f"{key} = {table.pop(key)}\n")
            else:
                out.append(line)
    if not found_comp:              # ancien fichier : on ajoute la section
        out.append(COMP_TEXT.format(on="oui" if s["comp_on"] else "non", thr=s["thr"],
                                    ratio=s["ratio"], makeup=s["makeup"],
                                    attack=s["attack"], release=s["release"],
                                    gate=s.get("gate", -50)))
    if not found_porte:             # porte anti-souffle : section ajoutée
        out.append(PORTE_TEXT.format(on=porte["actif"], thr=porte["seuil_db"],
                                     floor=porte["attenuation_db"]))
    if not found_debr:              # débruiteur : section ajoutée
        out.append(DEBR_TEXT.format(on=debr["actif"], force=debr["force_db"],
                                    quiet=debr["seuil_silence_db"]))
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(out)
    os.replace(tmp, CONFIG)


def load_my_presets():
    try:
        with open(MY_PRESETS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_my_presets(presets):
    tmp = MY_PRESETS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MY_PRESETS)


# --- filtres ----------------------------------------------------------------
def peaking(f0, gain_db, q, rate=RATE):
    """Filtre en cloche (RBJ) : +/- gain_db autour de f0."""
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / rate
    alpha = np.sin(w) / (2 * q)
    b = [1 + alpha * a, -2 * np.cos(w), 1 - alpha * a]
    den = [1 + alpha / a, -2 * np.cos(w), 1 - alpha / a]
    return np.concatenate([np.array(b) / den[0], np.array(den) / den[0]])


def build_sos(s, rate=RATE):
    sections = []
    if s["hp"] > 0:
        sections.append(signal.butter(2, s["hp"], "highpass", fs=rate, output="sos"))
    if s["lp"] > 0 and s["lp"] < rate / 2 - 100:
        sections.append(signal.butter(4, s["lp"], "lowpass", fs=rate, output="sos"))
    for f0, g in zip(BANDS, s["bands"]):
        if abs(g) >= 0.05:
            sections.append(peaking(f0, g, s["q"], rate)[None, :])
    if not sections:
        return None
    return np.vstack(sections)


def response_db(s, freqs):
    """Courbe de réponse (dB) pour l'affichage."""
    sos = build_sos(s)
    if sos is None:
        return np.full(len(freqs), s["gain"])
    _, h = signal.sosfreqz(sos, worN=freqs, fs=RATE)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-6)) + s["gain"]


# --- moteur audio -----------------------------------------------------------
class Denoiser:
    """Débruiteur doux (soustraction spectrale) : apprend l'empreinte du souffle
    pendant les silences et la retire en continu, voix comprise, de force_db au
    plus. Trames de 1024 points, recouvrement 50 % (latence ~21 ms à 48 kHz)."""
    N, HOP = 1024, 512

    def __init__(self):
        self.win = np.sqrt(np.hanning(self.N + 1)[:-1]).astype(np.float32)
        self.inbuf = np.zeros(0, np.float32)
        self.prev = np.zeros(self.N, np.float32)       # entrée de la trame précédente
        self.ola = np.zeros(self.HOP, np.float32)
        self.outq = np.zeros(self.HOP, np.float32)     # latence initiale (silence)
        self.noise = None
        self.gain = None
        self.frames = 0

    def process(self, x, force_db=12.0, quiet_db=-55.0):
        self.inbuf = np.concatenate([self.inbuf, x.astype(np.float32)])
        floor = 10 ** (-force_db / 20)
        out = []
        while len(self.inbuf) >= self.HOP:
            hop, self.inbuf = self.inbuf[:self.HOP], self.inbuf[self.HOP:]
            frame = np.concatenate([self.prev[self.HOP:], hop])
            self.prev = frame
            spec = np.fft.rfft(frame * self.win)
            p = (spec.real ** 2 + spec.imag ** 2)
            level = 10 * np.log10(p.mean() * 2 / self.N + 1e-12)
            if self.noise is None:
                self.noise = p.copy()
            elif level < quiet_db or self.frames < 20:     # silence : on apprend le souffle
                self.noise = 0.9 * self.noise + 0.1 * p
            else:                                          # voix : on garde l'empreinte,
                self.noise = np.minimum(self.noise, p)     # sauf si le souffle baisse
            self.frames += 1
            g = np.clip(1 - 1.5 * self.noise / (p + 1e-12), floor, 1.0)
            self.gain = g if self.gain is None else 0.6 * self.gain + 0.4 * g   # pas de « gazouillis »
            y = np.fft.irfft(spec * self.gain, self.N).astype(np.float32) * self.win
            out.append(self.ola + y[:self.HOP])
            self.ola = y[self.HOP:]
        if out:
            self.outq = np.concatenate([self.outq] + out)
        res, self.outq = self.outq[:len(x)], self.outq[len(x):]
        if len(res) < len(x):
            res = np.concatenate([np.zeros(len(x) - len(res), np.float32), res])
        return res


class EqEngine:
    """micro → filtres → sortie virtuelle ic7300_micro_eq (toujours en marche)."""

    def __init__(self):
        self.source = None
        self.settings = load_settings()
        self.mtime = self._mtime()
        self.sos = build_sos(self.settings)
        self.zi = None
        self.lock = threading.Lock()
        self.rec = self.play = None
        self.thread = None
        self.running = False
        self.module = None
        self.listen_module = None
        self.level = 0.0                # crête de sortie (0..1) pour le vu-mètre
        self.env_db = -90.0             # enveloppe du compresseur
        self.last_gain = 0.0            # dernier gain appliqué (dB), pour lisser
        self.reduction = 0.0            # compression en cours (dB) pour l'affichage
        self.lim_gain = 1.0             # gain du limiteur (1 = rien)
        self.lim_hits = 0.0             # part du temps où le limiteur agit (0..1)
        self.denoiser = Denoiser()      # débruiteur doux (si en service)
        self.gate_g = 1.0               # porte anti-souffle : gain en cours (0..1)
        self.gate_hold = 0.0            # temps restant porte ouverte (s)

    @staticmethod
    def _mtime():
        try:
            return os.path.getmtime(CONFIG)
        except OSError:
            return 0

    # sortie virtuelle
    def _ensure_sink(self):
        out = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True,
                             text=True, env=ENV).stdout
        if any(line.split("\t")[1] == SINK for line in out.splitlines() if "\t" in line):
            return
        r = subprocess.run(["pactl", "load-module", "module-null-sink", f"sink_name={SINK}",
                            "rate=48000", "channels=1",
                            "sink_properties=device.description=IC-7300_micro_egalise"],
                           capture_output=True, text=True)
        self.module = r.stdout.strip() or None

    def monitor_for(self, source):
        """Source à brancher sur la radio : la voix égalisée si c'est ce micro."""
        return MONITOR if self.running and source == self.source else source

    def start(self, source):
        if not source or source == "file":
            return
        if self.running and source == self.source:
            return
        self.stop(keep_sink=True)
        self._ensure_sink()
        self.source = source
        self.rec = subprocess.Popen(
            ["parec", f"--device={source}", "--raw", "--format=s16le", f"--rate={RATE}",
             "--channels=1", "--latency-msec=20", "--client-name=IC-7300 egaliseur",
             "--stream-name=IC-7300 egaliseur"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.play = subprocess.Popen(
            ["pacat", "--playback", f"--device={SINK}", "--raw", "--format=s16le",
             f"--rate={RATE}", "--channels=1", "--latency-msec=20",
             "--client-name=IC-7300 egaliseur", "--stream-name=IC-7300 egaliseur"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.running = True
        self.zi = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self, keep_sink=False):
        self.running = False
        for p in (self.rec, self.play):
            if p:
                try:
                    p.kill()
                except OSError:
                    pass
        self.rec = self.play = None
        if not keep_sink:
            self.listen(False)
            if self.module:
                subprocess.run(["pactl", "unload-module", self.module], capture_output=True)
                self.module = None

    def apply(self, settings):
        with self.lock:
            self.settings = settings
            self.sos = build_sos(settings)
            self.zi = None

    def _check_file(self):
        m = self._mtime()
        if m != self.mtime:
            self.mtime = m
            self.apply(load_settings())

    def _run(self):
        nbytes = BLOCK * 2
        last_check = 0.0
        rec, play = self.rec, self.play
        while self.running and rec is self.rec:
            data = rec.stdout.read(nbytes)
            if not data:
                break
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
            now = time.monotonic()
            if now - last_check > 0.5:
                last_check = now
                self._check_file()
            with self.lock:
                s, sos = self.settings, self.sos
                if s["on"]:
                    if s.get("dn_on"):
                        x = self.denoiser.process(x, s["dn_force"], s["dn_quiet"])
                    if sos is not None:
                        if self.zi is None or self.zi.shape[0] != sos.shape[0]:
                            self.zi = signal.sosfilt_zi(sos) * 0
                        x, self.zi = signal.sosfilt(sos, x, zi=self.zi)
                    if s["comp_on"]:
                        x = self._compress(x, s)
                    else:
                        self.reduction = 0.0
                    x = x * 10 ** (s["gain"] / 20)
                    if s.get("gate_on", True):
                        x = self._gate(x, s)
                    x = self._limit(x)
            self.level = max(self.level * 0.8, float(np.max(np.abs(x))) if len(x) else 0)
            try:
                play.stdin.write((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
            except (BrokenPipeError, OSError, ValueError):
                break

    def _gate(self, x, s, sub=48):
        """Porte anti-souffle : par tranches de 1 ms, ouverte instantanément sur la
        voix, tenue GATE_HOLD_MS, refermée en douceur jusqu'à −attenuation_db."""
        n = len(x) // sub
        if n == 0:
            return x
        floor = 10 ** (-s.get("gate_floor", 24.0) / 20)
        thr = s.get("gate_thr", -50.0)
        dt = sub / RATE
        rel = np.exp(-dt / (GATE_RELEASE_MS / 1000))
        blocks = x[: n * sub].reshape(n, sub)
        level = 20 * np.log10(np.sqrt((blocks ** 2).mean(axis=1)) + 1e-9)
        gains = np.empty(n + 1, np.float32)
        gains[0] = g = getattr(self, "gate_g", 1.0)
        hold = getattr(self, "gate_hold", 0.0)
        for i, lv in enumerate(level):
            if lv > thr:
                g, hold = 1.0, GATE_HOLD_MS / 1000      # voix : ouverte tout de suite
            elif hold > 0:
                hold -= dt
            else:
                g = floor + (g - floor) * rel           # souffle : baisse douce
            gains[i + 1] = g
        self.gate_g, self.gate_hold = g, hold
        ramp = np.interp(np.arange(n * sub), np.arange(n + 1) * sub, gains)
        out = x.copy()
        out[: n * sub] *= ramp
        if len(x) > n * sub:
            out[n * sub:] *= g
        return out

    def _limit(self, x, sub=24):
        """Limiteur de crêtes : réaction immédiate, retour en 60 ms ; la voix monte
        au plus près du maximum sans écrêter (l'enveloppe BLU est remplie)."""
        n = len(x) // sub
        if n == 0:
            return np.clip(x, -CEILING, CEILING)
        peaks = np.max(np.abs(x[:n * sub].reshape(n, sub)), axis=1)
        rel = np.exp(-sub / (RATE * LIM_RELEASE_MS / 1000))
        g = self.lim_gain
        gains = np.empty(n)
        for i in range(n):
            need = CEILING / peaks[i] if peaks[i] > CEILING else 1.0
            g = need if need < g else min(1.0, rel * g + (1 - rel) * 1.0)
            gains[i] = g
        self.lim_hits = 0.9 * self.lim_hits + 0.1 * float(np.mean(gains < 0.99))
        # gain constant sur chaque tranche (jamais en retard sur une crête)
        y = x[:n * sub].reshape(n, sub) * gains[:, None]
        y = np.concatenate([y.ravel(), x[n * sub:] * g])
        self.lim_gain = g
        return np.clip(y, -CEILING, CEILING)

    def _compress(self, x, s, sub=48):
        """Compresseur : enveloppe par tranches de 1 ms, gain lissé échantillon par
        échantillon. Sous -50 dB (silence, souffle) le rattrapage s'efface, pour ne
        pas remonter le bruit de fond."""
        n = len(x) // sub
        if n == 0:
            return x
        a_att = np.exp(-1.0 / s["attack"])
        a_rel = np.exp(-1.0 / s["release"])
        rms = np.sqrt(np.mean(x[:n * sub].reshape(n, sub) ** 2, axis=1) + 1e-12)
        lvl = 20 * np.log10(rms)
        gains = np.empty(n)
        env = self.env_db
        slope = 1 - 1 / s["ratio"]
        red = 0.0
        for i in range(n):
            a = a_att if lvl[i] > env else a_rel
            env = a * env + (1 - a) * lvl[i]
            over = env - s["thr"]
            g = -over * slope if over > 0 else 0.0
            red = min(red, g)
            gate = min(1.0, max(0.0, (env - s.get("gate", -50) + 10) / 10))
            gains[i] = g + s["makeup"] * gate
        self.env_db = env
        self.reduction = 0.7 * self.reduction + 0.3 * red
        centers = (np.arange(n) + 0.5) * sub
        g_db = np.interp(np.arange(len(x)), np.concatenate([[0], centers]),
                         np.concatenate([[self.last_gain], gains]))
        self.last_gain = gains[-1]
        return x * 10 ** (g_db / 20)

    # enregistrement de comparaison : voix brute et voix égalisée en même temps
    REC_DIR = "/tmp"

    def record(self, seconds=REC_SECONDS):
        """Enregistre `seconds` s du micro brut (avant) et égalisé (après)."""
        files = {}
        procs = []
        for name, dev in (("avant", self.source), ("apres", MONITOR)):
            path = os.path.join(self.REC_DIR, f"ic7300_voix_{name}.wav")
            files[name] = path
            procs.append(subprocess.Popen(
                ["parecord", f"--device={dev}", "--file-format=wav", f"--rate={RATE}",
                 "--channels=1", "--format=s16le", path],
                stderr=subprocess.DEVNULL))
        self.rec_files = files

        def finish():
            time.sleep(seconds)
            for p in procs:
                p.terminate()
        threading.Thread(target=finish, daemon=True).start()
        return files

    @staticmethod
    def _loud(path):
        """Copie d'écoute bien audible et propre : parole vers −14 dB, crêtes
        sous −1 dBFS, sans aucune saturation."""
        import wave
        with wave.open(path) as w:
            rate = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        n = rate // 50
        blocks = x[: len(x) // n * n].reshape(-1, n)
        rms = np.sqrt((blocks ** 2).mean(axis=1)) if len(blocks) else np.array([1e-3])
        voice = rms[rms > 10 ** (-45 / 20)]
        level = float(np.median(voice)) if len(voice) else float(rms.max() or 1e-3)
        # mise à niveau PROPRE (pas de limiteur qui déforme) : parole vers −14 dB
        # sans que les crêtes dépassent −1 dBFS
        peak = float(np.abs(x).max()) or 1e-3
        y = x * min(10 ** (-14 / 20) / level, 10 ** (-1 / 20) / peak)
        out = path[:-4] + "_ecoute.wav"
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((y * 32767).astype(np.int16).tobytes())
        return out

    def playback(self, which):
        path = getattr(self, "rec_files", {}).get(which)
        if path and os.path.exists(path):
            if getattr(self, "player", None):
                self.player.kill()
            self.player = subprocess.Popen(["paplay", self._loud(path)],
                                           stderr=subprocess.DEVNULL)
            return True
        return False

    def playback_received(self):
        """L'enregistrement « après », passé dans un filtre de récepteur BLU
        (300–2700 Hz, flancs raides) : à peu près ce qu'entend le correspondant."""
        src = getattr(self, "rec_files", {}).get("apres")
        if not src or not os.path.exists(src):
            return False
        import wave
        with wave.open(src) as w:
            rate = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
        sos = signal.butter(8, [300, 2700], btype="bandpass", fs=rate, output="sos")
        y = signal.sosfilt(sos, x)
        peak = float(np.abs(y).max()) or 1.0
        y = (y / peak * 0.7 * 32767).astype(np.int16)        # même niveau d'écoute
        out = os.path.join(self.REC_DIR, "ic7300_voix_recu.wav")
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(y.tobytes())
        if getattr(self, "player", None):
            self.player.kill()
        self.player = subprocess.Popen(["paplay", self._loud(out)], stderr=subprocess.DEVNULL)
        return True

    # s'écouter dans le casque
    def listen(self, on):
        if on and not self.listen_module:
            r = subprocess.run(["pactl", "load-module", "module-loopback",
                                f"source={MONITOR}", "latency_msec=30",
                                "source_dont_move=true"], capture_output=True, text=True)
            self.listen_module = r.stdout.strip() or None
        elif not on and self.listen_module:
            subprocess.run(["pactl", "unload-module", self.listen_module], capture_output=True)
            self.listen_module = None


# --- fenêtre ----------------------------------------------------------------
SLIDER_STYLE = """
QSlider::groove:vertical { background: #1a1410; width: 8px; border-radius: 4px;
                           border: 1px solid #5a4630; }
QSlider::handle:vertical { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 #c9c9c9, stop:0.5 #ffffff, stop:1 #8a8a8a);
    height: 18px; margin: 0 -10px; border-radius: 4px; border: 1px solid #333; }
QSlider::add-page:vertical { background: #ff9d3a; border-radius: 4px; }
"""


HSLIDER_STYLE = """
QSlider::groove:horizontal { background: #1a1410; height: 10px; border-radius: 5px;
                             border: 1px solid #5a4630; }
QSlider::handle:horizontal { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #ffffff, stop:0.5 #d0d0d0, stop:1 #8a8a8a);
    width: 26px; margin: -10px 0; border-radius: 6px; border: 1px solid #333; }
QSlider::sub-page:horizontal { background: #ff9d3a; border-radius: 5px; }
"""


class Curve(QtWidgets.QWidget):
    """Courbe de réponse de l'égaliseur, de 50 à 4000 Hz."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(150)
        self.freqs = np.geomspace(50, 4000, 200)
        self.db = np.zeros(200)

    def set_settings(self, s):
        self.db = response_db(s, self.freqs) if s["on"] else np.zeros(200)
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QtGui.QColor("#05080a"))
        lo, hi = np.log(50), np.log(4000)

        def x_of(f):
            return (np.log(f) - lo) / (hi - lo) * (w - 20) + 10

        def y_of(db):
            return h / 2 - db / 18 * (h / 2 - 10)
        p.setPen(QtGui.QPen(QtGui.QColor("#1f3326"), 1))
        for db in (-12, -6, 0, 6, 12):
            p.drawLine(QtCore.QPointF(10, y_of(db)), QtCore.QPointF(w - 10, y_of(db)))
        p.setFont(QtGui.QFont("monospace", 8))
        for f in (100, 200, 500, 1000, 2000, 3000):
            x = x_of(f)
            p.setPen(QtGui.QPen(QtGui.QColor("#1f3326"), 1))
            p.drawLine(QtCore.QPointF(x, 6), QtCore.QPointF(x, h - 14))
            p.setPen(QtGui.QColor("#6a8a72"))
            p.drawText(QtCore.QPointF(x + 2, h - 3), f"{f:g}" if f < 1000 else f"{f // 1000}k")
        p.setPen(QtGui.QColor("#6a8a72"))
        p.drawText(QtCore.QPointF(12, y_of(12) + 4), "+12 dB")
        p.drawText(QtCore.QPointF(12, y_of(-12) + 4), "-12 dB")
        path = QtGui.QPainterPath()
        for i, (f, db) in enumerate(zip(self.freqs, np.clip(self.db, -18, 18))):
            pt = QtCore.QPointF(x_of(f), y_of(db))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QtGui.QPen(QtGui.QColor("#3ddc84"), 3))
        p.drawPath(path)


class EqWindow(QtWidgets.QWidget):
    opened = QtCore.pyqtSignal()        # fenêtre affichée  (le Scope coupe la réception)
    closed = QtCore.pyqtSignal()        # fenêtre cachée    (le Scope la rétablit)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        if parent is not None:          # fenêtre à part, rattachée au Scope, au premier plan
            self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint)
        self.engine = engine
        self.setWindowTitle("Égaliseur de la voix d'émission")
        self.setStyleSheet("EqWindow { background: #14100c; } "
                           "QLabel { color: #e8d9b5; font: bold 10pt sans-serif; } "
                           "QCheckBox { color: #e8d9b5; font: bold 10pt sans-serif; } "
                           "QSpinBox, QDoubleSpinBox, QComboBox { color: #ffd54a; "
                           "background: #05080a; border: 1px solid #5a4630; "
                           "font: bold 10pt sans-serif; padding: 2px 4px; } "
                           "QComboBox QAbstractItemView { color: #ffd54a; background: #05080a; }")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.resize(820, 560)
        self._loading = False
        lay = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        self.on_box = QtWidgets.QCheckBox("ÉGALISEUR EN SERVICE")
        self.on_box.toggled.connect(self._changed)
        top.addWidget(self.on_box)
        top.addStretch()
        top.addWidget(QtWidgets.QLabel("Préréglage :"))
        self.preset = QtWidgets.QComboBox()
        self.preset.setMinimumWidth(220)
        self.preset.activated[str].connect(self._preset)
        top.addWidget(self.preset)
        save_as = QtWidgets.QPushButton("SAUVER SOUS UN NOM")
        save_as.setToolTip("Garde le réglage actuel sous un nom (liste « Préréglage », ★)")
        save_as.clicked.connect(self._save_as)
        top.addWidget(save_as)
        delete = QtWidgets.QPushButton("Supprimer…")
        delete.setToolTip("Effacer un de tes réglages enregistrés")
        delete.clicked.connect(self._delete_mine)
        top.addWidget(delete)
        self._fill_presets()
        self.listen_box = QtWidgets.QCheckBox("M'ÉCOUTER (casque)")
        self.listen_box.setToolTip("Entendre sa voix égalisée dans le casque, sans émettre")
        self.listen_box.toggled.connect(self.engine.listen)
        top.addWidget(self.listen_box)
        lay.addLayout(top)

        self.curve = Curve()
        lay.addWidget(self.curve)

        sliders = QtWidgets.QHBoxLayout()
        self.band_sliders, self.band_labels = [], []
        for f in BANDS:
            col = QtWidgets.QVBoxLayout()
            val = QtWidgets.QLabel("0 dB")
            val.setAlignment(QtCore.Qt.AlignCenter)
            sl = QtWidgets.QSlider(QtCore.Qt.Vertical)
            sl.setRange(-24, 24)                # demi-dB
            sl.setMinimumHeight(170)
            sl.setStyleSheet(SLIDER_STYLE)
            sl.setToolTip("Double-clic sur le nom : remettre à 0 dB")
            sl.valueChanged.connect(self._changed)
            name = QtWidgets.QLabel(f"{f} Hz" if f < 1000 else f"{f / 1000:g} kHz")
            name.setAlignment(QtCore.Qt.AlignCenter)
            col.addWidget(val)
            col.addWidget(sl, 0, QtCore.Qt.AlignHCenter)
            col.addWidget(name)
            sliders.addLayout(col)
            self.band_sliders.append(sl)
            self.band_labels.append(val)
        # gain général
        col = QtWidgets.QVBoxLayout()
        self.gain_label = QtWidgets.QLabel("0 dB")
        self.gain_label.setAlignment(QtCore.Qt.AlignCenter)
        self.gain = QtWidgets.QSlider(QtCore.Qt.Vertical)
        self.gain.setRange(-24, 24)
        self.gain.setMinimumHeight(170)
        self.gain.setStyleSheet(SLIDER_STYLE.replace("#ff9d3a", "#3ddc84"))
        self.gain.valueChanged.connect(self._changed)
        g = QtWidgets.QLabel("GAIN")
        g.setAlignment(QtCore.Qt.AlignCenter)
        col.addWidget(self.gain_label)
        col.addWidget(self.gain, 0, QtCore.Qt.AlignHCenter)
        col.addWidget(g)
        sliders.addSpacing(20)
        sliders.addLayout(col)
        lay.addLayout(sliders)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("Passe-haut"))
        self.hp = QtWidgets.QSpinBox()
        self.hp.setRange(0, 600)
        self.hp.setSingleStep(10)
        self.hp.setSuffix(" Hz")
        self.hp.setSpecialValueText("aucun")
        self.hp.valueChanged.connect(self._changed)
        bottom.addWidget(self.hp)
        bottom.addSpacing(12)
        bottom.addWidget(QtWidgets.QLabel("Passe-bas"))
        self.lp = QtWidgets.QSpinBox()
        self.lp.setRange(0, 4000)
        self.lp.setSingleStep(50)
        self.lp.setSuffix(" Hz")
        self.lp.setSpecialValueText("aucun")
        self.lp.valueChanged.connect(self._changed)
        bottom.addWidget(self.lp)
        bottom.addSpacing(12)
        bottom.addWidget(QtWidgets.QLabel("Largeur Q"))
        self.q = QtWidgets.QDoubleSpinBox()
        self.q.setRange(0.3, 5.0)
        self.q.setSingleStep(0.1)
        self.q.valueChanged.connect(self._changed)
        bottom.addWidget(self.q)
        bottom.addStretch()
        self.meter = QtWidgets.QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedWidth(120)
        self.meter.setToolTip("Niveau de la voix égalisée (rouge = trop fort)")
        bottom.addWidget(QtWidgets.QLabel("Niveau"))
        bottom.addWidget(self.meter)
        flat = QtWidgets.QPushButton("Tout à 0")
        flat.clicked.connect(lambda: self._preset("Plat"))
        bottom.addWidget(flat)
        edit = QtWidgets.QPushButton("Ouvrir le fichier…")
        edit.setToolTip(CONFIG)
        edit.clicked.connect(lambda: subprocess.Popen(["gedit", CONFIG]))
        bottom.addWidget(edit)
        lay.addLayout(bottom)

        # COMPRESSEUR : plus de dynamique dans la modulation
        comp = QtWidgets.QHBoxLayout()
        self.comp_box = QtWidgets.QCheckBox("COMPRESSEUR (dynamique)")
        self.comp_box.setToolTip("Remonte les passages faibles, retient les pointes : "
                                 "voix plus dense et plus présente")
        self.comp_box.toggled.connect(self._changed)
        comp.addWidget(self.comp_box)
        self.comp_sliders = {}
        for key, name, lo, hi, step, unit in (("thr", "Seuil", -40, 0, 1, " dB"),
                                              ("ratio", "Taux", 1, 10, 0.5, ":1"),
                                              ("makeup", "Rattrapage", 0, 20, 1, " dB")):
            comp.addSpacing(10)
            comp.addWidget(QtWidgets.QLabel(name))
            sl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            sl.setRange(int(lo / step), int(hi / step))
            sl.setMinimumWidth(170)
            sl.setMinimumHeight(34)
            sl.setStyleSheet(HSLIDER_STYLE)
            sl.setToolTip(f"{name} : glisser la poignée, ou molette dessus")
            sl.step = step
            sl.valueChanged.connect(self._changed)
            val = QtWidgets.QLabel("")
            val.setMinimumWidth(52)
            comp.addWidget(sl, stretch=1)
            comp.addWidget(val)
            self.comp_sliders[key] = (sl, val, unit)
        comp.addSpacing(10)
        comp.addWidget(QtWidgets.QLabel("Compression"))
        self.gr_meter = QtWidgets.QProgressBar()
        self.gr_meter.setRange(0, 20)
        self.gr_meter.setTextVisible(False)
        self.gr_meter.setFixedWidth(100)
        self.gr_meter.setToolTip("Compression en cours (dB). 6 à 12 dB en parlant : bien.")
        self.gr_meter.setStyleSheet("QProgressBar::chunk { background: #ff9d3a; }")
        comp.addWidget(self.gr_meter)
        lay.addLayout(comp)

        # comparer : s'enregistrer, puis réécouter avant / après égaliseur
        cmp_row = QtWidgets.QHBoxLayout()
        big = ("QPushButton { font: bold 12pt sans-serif; color: #fff; background: %s; "
               "border-radius: 8px; padding: 8px 14px; } QPushButton:disabled { color: #888; }")
        self.rec_button = QtWidgets.QPushButton("● S'ENREGISTRER 15 s")
        self.rec_button.setStyleSheet(big % "#b71c1c")
        self.rec_button.setToolTip("Parle dans le micro pendant 15 s (rien n'est émis)")
        self.rec_button.clicked.connect(self._record)
        self.play_before = QtWidgets.QPushButton("▶ ÉCOUTER AVANT")
        self.play_before.setStyleSheet(big % "#455a64")
        self.play_before.clicked.connect(lambda: self.engine.playback("avant"))
        self.play_after = QtWidgets.QPushButton("▶ ÉCOUTER APRÈS")
        self.play_after.setStyleSheet(big % "#2e7d32")
        self.play_after.setToolTip("Voix passée dans l'égaliseur, telle qu'elle part à la radio")
        self.play_after.clicked.connect(lambda: self.engine.playback("apres"))
        self.play_rx = QtWidgets.QPushButton("▶ COMME REÇU")
        self.play_rx.setStyleSheet(big % "#6a4a14")
        self.play_rx.setToolTip("Ta voix « après », passée dans un filtre de récepteur BLU "
                                "(300–2700 Hz) : à peu près ce qu'entend le correspondant. "
                                "Le compresseur de la radio (NIVEAU COMP) n'y est pas.")
        self.play_rx.clicked.connect(self.engine.playback_received)
        for b in (self.play_before, self.play_after, self.play_rx):
            b.setEnabled(False)
        self.rec_info = QtWidgets.QLabel("")
        cmp_row.addWidget(self.rec_button)
        cmp_row.addWidget(self.play_before)
        cmp_row.addWidget(self.play_after)
        cmp_row.addWidget(self.play_rx)
        cmp_row.addWidget(self.rec_info, stretch=1)
        close = QtWidgets.QPushButton("FERMER")
        close.setFixedSize(78, 78)
        close.setFocusPolicy(QtCore.Qt.NoFocus)
        close.setToolTip("Fermer l'égaliseur (les réglages restent appliqués)")
        close.setStyleSheet(
            "QPushButton { font: bold 10pt sans-serif; color: #fff; border-radius: 39px; "
            "border: 3px solid #c9c9c9; background: qradialgradient(cx:0.4, cy:0.35, "
            "radius:0.7, fx:0.35, fy:0.3, stop:0 #ff6b5e, stop:0.6 #c62828, stop:1 #6d0f0f); }"
            "QPushButton:pressed { background: qradialgradient(cx:0.5, cy:0.5, radius:0.7, "
            "stop:0 #b71c1c, stop:1 #4a0a0a); }")
        close.clicked.connect(self.hide)    # cache l'égaliseur seulement, jamais le Scope
        cmp_row.addWidget(close)
        lay.addLayout(cmp_row)
        self.rec_left = 0
        self.rec_timer = QtCore.QTimer(self)
        self.rec_timer.timeout.connect(self._rec_tick)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.save_timer = QtCore.QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._save)
        self.file_mtime = 0
        self._load()

    def showEvent(self, e):
        self._load()
        self._fill_presets()            # réglages nommés à jour à chaque ouverture
        self.timer.start(100)
        super().showEvent(e)
        if not e.spontaneous():
            self.opened.emit()

    def hideEvent(self, e):
        self.timer.stop()
        self.listen_box.setChecked(False)
        super().hideEvent(e)
        if not e.spontaneous():         # pas une simple réduction de la fenêtre
            self.closed.emit()

    def _load(self):
        s = load_settings()
        self.file_mtime = EqEngine._mtime()
        self._loading = True
        self.on_box.setChecked(s["on"])
        for sl, v in zip(self.band_sliders, s["bands"]):
            sl.setValue(round(v * 2))
        self.gain.setValue(round(s["gain"] * 2))
        self.hp.setValue(int(s["hp"]))
        self.lp.setValue(int(s["lp"]))
        self.q.setValue(s["q"])
        self.comp_box.setChecked(s["comp_on"])
        for key, (sl, _, _) in self.comp_sliders.items():
            sl.setValue(round(s[key] / sl.step))
        self.comp_extra = dict(attack=s["attack"], release=s["release"], gate=s["gate"])
        self._loading = False
        self._refresh(s)

    def _current(self):
        s = dict(on=self.on_box.isChecked(), gain=self.gain.value() / 2,
                 hp=self.hp.value(), lp=self.lp.value(), q=self.q.value(),
                 bands=[sl.value() / 2 for sl in self.band_sliders],
                 comp_on=self.comp_box.isChecked(),
                 **getattr(self, "comp_extra", dict(attack=COMP_DEFAULT["attack"],
                                                    release=COMP_DEFAULT["release"],
                                                    gate=COMP_DEFAULT["gate"])))
        for key, (sl, _, _) in self.comp_sliders.items():
            s[key] = sl.value() * sl.step
        return s

    def _refresh(self, s):
        for lab, v in zip(self.band_labels, s["bands"]):
            lab.setText(f"{v:+g} dB" if v else "0 dB")
        self.gain_label.setText(f"{s['gain']:+g} dB" if s["gain"] else "0 dB")
        for key, (sl, val, unit) in self.comp_sliders.items():
            val.setText(f"{s[key]:g}{unit}")
        self.curve.set_settings(s)

    def _changed(self, *_):
        if self._loading:
            return
        s = self._current()
        self._refresh(s)
        self.engine.apply(s)            # tout de suite dans le son
        self.save_timer.start(300)      # puis dans le fichier

    def _save(self):
        save_settings(self._current())
        self.file_mtime = EqEngine._mtime()
        self.engine.mtime = self.file_mtime

    def _record(self):
        if not self.engine.running:
            self.rec_info.setText("Pas de micro en service")
            return
        self.listen_box.setChecked(False)
        self.engine.record(REC_SECONDS)
        self.rec_left = REC_SECONDS
        self.rec_button.setEnabled(False)
        self._rec_tick()
        self.rec_timer.start(1000)

    def _rec_tick(self):
        if self.rec_left <= 0:
            self.rec_timer.stop()
            self.rec_button.setEnabled(True)
            self.play_before.setEnabled(True)
            self.play_after.setEnabled(True)
            self.play_rx.setEnabled(True)
            self.rec_info.setText("Compare AVANT / APRÈS. Change un réglage, puis "
                                  "réenregistre-toi.")
            return
        self.rec_info.setText(f"Parle maintenant… {self.rec_left} s")
        self.rec_left -= 1

    def _fill_presets(self):
        self.preset.clear()
        self.preset.addItem("—")
        self.preset.addItems(PRESETS)
        mine = load_my_presets()
        if mine:
            self.preset.insertSeparator(self.preset.count())
            self.preset.addItems(MINE + name for name in sorted(mine))

    def _ask(self, title, label, text=""):
        dlg = QtWidgets.QInputDialog(self)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)
        dlg.setTextValue(text)
        dlg.setStyleSheet("QLabel { color: #e8d9b5; } QLineEdit { color: #ffd54a; "
                          "background: #05080a; font: bold 12pt sans-serif; }")
        return dlg.textValue().strip() if dlg.exec_() else ""

    def _save_as(self):
        name = self._ask("Sauver le réglage", "Nom de ce réglage (ex. Mon DX) :")
        if not name:
            return
        mine = load_my_presets()
        if name in mine and QtWidgets.QMessageBox.question(
                self, "Remplacer ?", f"« {name} » existe déjà. Le remplacer ?") \
                != QtWidgets.QMessageBox.Yes:
            return
        s = self._current()
        mine[name] = dict(hp=s["hp"], lp=s["lp"], gain=s["gain"], q=s["q"],
                          bands=s["bands"], comp_on=s["comp_on"], thr=s["thr"],
                          ratio=s["ratio"], makeup=s["makeup"])
        save_my_presets(mine)
        self._fill_presets()
        self.rec_info.setText(f"★ « {name} » enregistré")

    def _delete_mine(self):
        mine = load_my_presets()
        if not mine:
            self.rec_info.setText("Aucun réglage enregistré à supprimer")
            return
        name, ok = QtWidgets.QInputDialog.getItem(
            self, "Supprimer un réglage", "Réglage à supprimer :", sorted(mine), 0, False)
        if ok and name in mine and QtWidgets.QMessageBox.question(
                self, "Supprimer ?", f"Supprimer « {name} » ?") == QtWidgets.QMessageBox.Yes:
            del mine[name]
            save_my_presets(mine)
            self._fill_presets()
            self.rec_info.setText(f"Réglage « {name} » supprimé")

    def _preset(self, name):
        if name.startswith(MINE):
            p = load_my_presets().get(name[len(MINE):])
            if p:
                self._loading = True
                self.q.setValue(p.get("q", 1.2))
                if "comp_on" in p:
                    self.comp_box.setChecked(p["comp_on"])
                    for key, (sl, _, _) in self.comp_sliders.items():
                        sl.setValue(round(p[key] / sl.step))
                self._loading = False
        else:
            p = PRESETS.get(name)
            if p and "comp_on" in p:            # réglage tout prêt avec compresseur
                self._loading = True
                self.q.setValue(p.get("q", 1.2))
                self.comp_box.setChecked(p["comp_on"])
                for key, (sl, _, _) in self.comp_sliders.items():
                    sl.setValue(round(p[key] / sl.step))
                self.comp_extra = dict(attack=p["attack"], release=p["release"],
                                       gate=p["gate"])     # attaque / relâchement doux
                self._loading = False
        if not p:
            return
        self._loading = True
        for sl, v in zip(self.band_sliders, p["bands"]):
            sl.setValue(round(v * 2))
        self.hp.setValue(p["hp"])
        self.lp.setValue(p["lp"])
        self.gain.setValue(round(p["gain"] * 2))
        self.on_box.setChecked(True)
        self._loading = False
        self.preset.setCurrentIndex(0)
        self._changed()

    def _tick(self):
        if EqEngine._mtime() != self.file_mtime:     # fichier modifié à la main
            self._load()
        self.gr_meter.setValue(min(20, int(round(-self.engine.reduction))))
        lvl = min(100, int(self.engine.level * 100))
        self.meter.setValue(lvl)
        color = "#e53935" if lvl > 90 else ("#ffd54a" if lvl > 70 else "#3ddc84")
        self.meter.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")

    def closeEvent(self, e):
        e.ignore()                      # croix de la fenêtre = même chose que FERMER
        self.hide()


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    eng = EqEngine()
    src = subprocess.run(["pactl", "get-default-source"], capture_output=True,
                         text=True).stdout.strip()
    eng.start(src)
    w = EqWindow(eng)
    w.show()
    app.exec_()
    eng.stop()
