"""Commandes « VOX 1 », « VOX 2 »… apprises sur la voix de l'utilisateur.

Apprentissage : la commande est dite plusieurs fois ; chaque exemple est gardé
(son brut 16 kHz) dans ~/.config/ic7300-scope/voix/. Reconnaissance : la parole
entendue est comparée aux exemples (empreinte MFCC, alignement DTW) ; elle n'est
acceptée que si elle ressemble à tes exemples autant qu'ils se ressemblent
entre eux. Une autre voix, ou une autre commande, en reste loin.
"""

import glob
import json
import os

import numpy as np

RATE = 16000
VOICE_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                         "ic7300-scope", "voix")
LEARN_COUNT = 6                 # exemples demandés par commande
MARGIN = 1.35                   # tolérance au-delà de l'écart entre tes exemples
WIN, HOP, NFFT, NMEL, NCEP = 400, 160, 512, 26, 13


def _mel_bank():
    def mel(f):
        return 2595 * np.log10(1 + f / 700)

    def hz(m):
        return 700 * (10 ** (m / 2595) - 1)
    pts = hz(np.linspace(mel(80), mel(7600), NMEL + 2))
    bins = np.floor((NFFT + 1) * pts / RATE).astype(int)
    bank = np.zeros((NMEL, NFFT // 2 + 1))
    for i in range(NMEL):
        a, b, c = bins[i], bins[i + 1], bins[i + 2]
        bank[i, a:b] = (np.arange(a, b) - a) / max(b - a, 1)
        bank[i, b:c] = (c - np.arange(b, c)) / max(c - b, 1)
    return bank


_BANK = _mel_bank()
_DCT = np.cos(np.pi / NMEL * (np.arange(NMEL) + 0.5)[None, :] * np.arange(NCEP)[:, None])
_WINDOW = np.hamming(WIN)


def features(raw):
    """Son brut s16le 16 kHz → empreinte (trames × coefficients), parole seule."""
    x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    if len(x) < WIN * 4:
        return None
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])
    n = 1 + (len(x) - WIN) // HOP
    frames = np.stack([x[i * HOP:i * HOP + WIN] for i in range(n)]) * _WINDOW
    power = np.abs(np.fft.rfft(frames, NFFT)) ** 2
    energy = 10 * np.log10(power.sum(1) + 1e-10)
    keep = energy > energy.max() - 30           # silences du début et de la fin enlevés
    idx = np.where(keep)[0]
    if len(idx) < 10:
        return None
    sl = slice(idx[0], idx[-1] + 1)
    ceps = np.log(power[sl] @ _BANK.T + 1e-10) @ _DCT.T
    ceps = ceps[:, 1:]                          # sans le volume
    ceps -= ceps.mean(0)                        # micro / pièce : effacés
    delta = np.gradient(ceps, axis=0)
    return np.hstack([ceps, delta]).astype(np.float32)


def dtw(a, b):
    """Distance moyenne le long du meilleur alignement de deux empreintes."""
    cost = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    n, m = cost.shape
    acc = np.full((n + 1, m + 1), np.inf, np.float32)
    acc[0, 0] = 0
    for i in range(1, n + 1):
        row, prev, c = acc[i], acc[i - 1], cost[i - 1]
        diag = np.minimum(prev[:-1], prev[1:])          # (i-1, j-1) et (i-1, j)
        row[1:] = c + diag
        for j in range(1, m + 1):                       # (i, j-1)
            v = c[j - 1] + row[j - 1]
            if v < row[j]:
                row[j] = v
    return float(acc[n, m] / (n + m))


class VoiceCommands:
    """Exemples de ta voix pour chaque commande, et reconnaissance."""

    def __init__(self):
        self.examples = {}          # n → [empreintes]
        self.limit = {}             # n → distance maximale acceptée
        self.load()

    def _files(self, n):
        return sorted(glob.glob(os.path.join(VOICE_DIR, f"vox{n}-*.raw")))

    def load(self):
        self.examples, self.limit = {}, {}
        try:
            limits = json.load(open(os.path.join(VOICE_DIR, "seuils.json")))
        except (OSError, ValueError):
            limits = {}
        for path in glob.glob(os.path.join(VOICE_DIR, "vox*-*.raw")):
            n = int(os.path.basename(path)[3:].split("-")[0])
            f = features(open(path, "rb").read())
            if f is not None:
                self.examples.setdefault(n, []).append(f)
        for n in self.examples:
            self.limit[n] = limits.get(str(n)) or self._compute_limit(n)

    def learned(self, n):
        return len(self.examples.get(n, [])) >= 3

    def _compute_limit(self, n):
        """Écart de chaque exemple à ses voisins les plus proches : la tolérance."""
        ex = self.examples.get(n, [])
        if len(ex) < 2:
            return 0.0
        near = []
        for i, a in enumerate(ex):
            d = sorted(dtw(a, b) for j, b in enumerate(ex) if j != i)
            near.append(np.mean(d[:2]))
        return float(max(near) * MARGIN)

    def save(self, n, clips):
        """Remplace les exemples de la commande n ; renvoie le nombre gardé."""
        os.makedirs(VOICE_DIR, exist_ok=True)
        for path in self._files(n):
            os.remove(path)
        kept = 0
        for i, clip in enumerate(clips):
            if features(clip) is not None:
                with open(os.path.join(VOICE_DIR, f"vox{n}-{i + 1}.raw"), "wb") as f:
                    f.write(clip)
                kept += 1
        self.load()
        self.limit[n] = self._compute_limit(n)
        limits = {str(k): v for k, v in self.limit.items()}
        with open(os.path.join(VOICE_DIR, "seuils.json"), "w") as f:
            json.dump(limits, f)
        return kept

    def match(self, clip, candidates):
        """Commande reconnue parmi candidates (ta voix seulement), ou None.
        Renvoie (n ou None, distance, détail texte)."""
        f = features(clip)
        if f is None:
            return None, 0.0, "trop court"
        scores = {}
        for n, ex in self.examples.items():
            if len(ex) >= 3:
                d = sorted(dtw(f, e) for e in ex)
                scores[n] = float(np.mean(d[:3]))       # les 3 exemples les plus proches
        if not scores:
            return None, 0.0, "voix pas encore apprise"
        best = min(scores, key=scores.get)
        d = scores[best]
        others = [v for k, v in scores.items() if k != best]
        detail = f"VOX {best} à {d:.1f} (limite {self.limit.get(best, 0):.1f})"
        if best not in candidates:
            return None, d, detail + " — pas en attente"
        if d > self.limit.get(best, 0):
            return None, d, detail + " — voix ou mot trop différents"
        if others and d > 0.9 * min(others):
            return None, d, detail + " — trop proche d'une autre commande"
        return best, d, detail
