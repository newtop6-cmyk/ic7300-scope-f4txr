"""Calage automatique en BLU (LSB/USB) sur la voix du correspondant.

Une voix voisée contient des harmoniques k × F0 (F0 : hauteur de la voix).
Si la radio est décalée de d Hz, elles sortent à k × F0 + d. Pour chaque
tranche de son, on cherche le « peigne » k × F0 + d qui tombe le mieux sur les
pics du spectre. Dans une tranche, d n'est connu qu'à un multiple de F0 près ;
mais F0 bouge sans cesse quand on parle alors que d reste fixe : en cumulant
plusieurs secondes de voix, seul le vrai d ressort.

Bande latérale : si le correspondant est sur l'autre bande (LSB entendue en
USB…), sa voix arrive à l'envers et ses harmoniques ne donnent jamais un d
stable. On fait donc le même travail sur le spectre retourné (miroir autour de
MIRROR Hz) : si c'est lui qui donne un d net, il faut changer de bande latérale.
"""

import numpy as np

FRAME = 4096                    # 85 ms à 48 kHz
PAD = 16384                     # zéros ajoutés : grille de ~3 Hz
HOP_S = 0.1                     # une analyse toutes les 0,1 s
LOW, HIGH = 300, 1600           # harmoniques cherchées dans cette bande (Hz audio)
F0S = np.arange(80, 300, 2)     # hauteurs de voix essayées
D_MAX = 300                     # décalage cherché : ± 300 Hz
D_STEP = 2
SMOOTH_HZ = 121                 # voisinage pour faire ressortir les pics
VOICED = 0.5                    # score mini d'une tranche voisée
HISTORY = 200                   # scores gardés pour connaître celui du bruit (20 s)
NOISE_PCT = 30                  # le bruit : 30e centile des scores récents
CLEAR = 4.5                     # voix nette : score > bruit + 4,5 écarts du bruit
MIN_FRAMES = 15                 # tranches voisées nettes avant de corriger
QUICK_FRAMES = 8                # voix très nette : on corrige dès 8 tranches
QUICK_MARGIN = 0.6              # « très nette » : 2e pic < 60 % du 1er
MIN_SHIFT = 15                  # Hz : en dessous, on ne touche à rien
MARGIN = 0.6                    # 2e pic (hors ± 30 Hz) < 60 % du 1er, sinon doute
HOLD_S = 1.0                    # attente après un changement de fréquence (son en réseau)
FORGET = 0.97                   # oubli progressif (autre correspondant…)
MIRROR = 1400                   # Hz audio : centre du retournement du spectre
FLIP_MARGIN = 0.7               # changer de bande latérale demande un pic plus net


class Track:
    """Cumul d'une analyse (son à l'endroit, ou retourné)."""

    def __init__(self, n):
        self.acc = np.zeros(n)
        self.frames = 0.0
        self.history = []               # scores récents (bruit et voix)

    def add(self, scores):
        """Ajoute une tranche ; True si elle contenait une voix nette."""
        per_f0 = scores.max(axis=1)
        best = int(per_f0.argmax())
        score = float(per_f0[best])
        # le bruit seul donne aussi des « peignes » : on apprend leur score
        self.history = (self.history + [score])[-HISTORY:]
        if len(self.history) < 20:
            return False
        hist = np.array(self.history)
        base = np.percentile(hist, NOISE_PCT)
        low = hist[hist <= np.percentile(hist, 60)]
        spread = max(float(low.std()), 0.02)
        weight = (score - base) / spread - CLEAR
        if score < VOICED or weight <= 0:                  # pas de voix nette
            # oubli doux (moitié en ~15 s) : du bruit isolé ne suffit jamais
            self.frames *= 0.995
            self.acc *= 0.995
            return False
        # courbe en d pour la hauteur trouvée (± un pas)
        curve = scores[max(best - 1, 0):best + 2].max(axis=0)
        z = (curve - curve.mean()) / (curve.std() + 1e-9)
        self.acc = self.acc * FORGET + z * min(weight, 4.0)
        self.frames += 1
        return True

    def peak(self, ds, margin):
        """(d, net, rapport) : meilleur d, s'il ressort nettement des autres,
        et 2e pic / 1er pic (plus c'est petit, plus c'est net)."""
        acc = self.acc - np.median(self.acc)
        i = int(np.argmax(acc))
        far = np.abs(ds - ds[i]) > 30
        ratio = float(acc[far].max() / acc[i]) if acc[i] > 0 else 1.0
        # un pic collé au bord de la plage n'est pas fiable
        clear = ratio <= margin and abs(ds[i]) <= ds[-1] - 40
        d = float(ds[i])
        if 0 < i < len(ds) - 1:                            # affiner entre deux points
            a, b, c = acc[i - 1:i + 2]
            if a - 2 * b + c < 0:
                d += D_STEP * 0.5 * (a - c) / (a - 2 * b + c)
        return d, clear, ratio


class SsbTuner:
    def __init__(self, rate):
        self.rate = rate
        self.hop = int(rate * HOP_S)
        self.window = np.hanning(FRAME).astype(np.float32)
        self.freqs = np.arange(PAD // 2 + 1) * rate / PAD
        self.top = HIGH + D_MAX + SMOOTH_HZ
        self.grid = np.arange(max(self.top, 2 * MIRROR) + 1)   # 1 Hz
        self.mirror_idx = 2 * MIRROR - np.arange(self.top + 1)  # spectre retourné
        self.mirror = False             # chercher aussi l'autre bande latérale
        self.kernel = np.ones(SMOOTH_HZ) / SMOOTH_HZ
        self.ds = np.arange(-D_MAX, D_MAX + 1, D_STEP)
        # positions (Hz) des harmoniques pour chaque F0 et chaque d
        ks = np.arange(1, HIGH // F0S[0] + 1)
        base = F0S[:, None] * ks[None, :]                  # (F0, k)
        self.valid = ((base >= LOW) & (base <= HIGH)).astype(np.float32)
        self.count = self.valid.sum(axis=1)
        pos = base[:, :, None] + self.ds[None, None, :]    # (F0, k, d)
        self.pos = np.clip(pos, 0, self.top).astype(np.int32)
        # mi-chemin entre deux harmoniques : rien ne doit s'y trouver, sinon
        # c'est la voix à l'octave du dessous (ou un faux peigne)
        mid = np.round(pos + F0S[:, None, None] / 2)
        self.mid = np.clip(mid, 0, self.top).astype(np.int32)
        self.reset()

    def request_reset(self):
        """Depuis un autre fil (fenêtre) : remise à zéro au prochain son."""
        self._reset_pending = True

    def reset(self):
        """À appeler quand la fréquence change : le son d'avant ne vaut plus."""
        self._reset_pending = False
        self.estimate = None            # écart estimé en direct (Hz), pour l'aiguille
        self.locked = False             # calé à moins de MIN_SHIFT
        self.buf = np.zeros(0, np.float32)
        # le bruit de fond de la bande ne change pas avec la fréquence : on garde
        # ce qu'on en a appris, le calage repart ainsi tout de suite
        old = getattr(self, "normal", None), getattr(self, "flipped", None)
        self.normal = Track(len(self.ds))
        self.flipped = Track(len(self.ds))
        for new, prev in zip((self.normal, self.flipped), old):
            if prev is not None:
                new.history = prev.history[-HISTORY:]
        self.hold = int(self.rate * HOLD_S)
        self.status = "attente de voix"

    @property
    def frames(self):
        return self.normal.frames

    def feed(self, x):
        """Ajoute du son. Renvoie None, ("shift", d) ou ("flip", c).
        shift : la radio doit bouger de +d en USB, -d en LSB.
        flip : le correspondant est sur l'autre bande latérale ; sa porteuse
        est à +c Hz (en USB) ou -c Hz (en LSB) de la fréquence actuelle."""
        if self._reset_pending:
            self.reset()
        if self.hold > 0:
            self.hold -= len(x)
            return None
        self.buf = np.concatenate((self.buf, x))
        if len(self.buf) < FRAME + self.hop:
            return None
        frame = self.buf[-FRAME:]
        self.buf = self.buf[-FRAME:]
        return self._analyse(frame)

    def _analyse(self, frame):
        mag = np.abs(np.fft.rfft(frame * self.window, PAD))
        spec = np.interp(self.grid, self.freqs, mag)
        if 10 * np.log10(np.mean(spec[LOW:HIGH] ** 2) + 1e-20) < -120:
            return None                                    # silence numérique
        log = np.log(spec + 1e-12)
        peaks = np.maximum(log - np.convolve(log, self.kernel, mode="same"), 0)
        voiced = self.normal.add(self._comb(peaks[:self.top + 1]))
        # toujours écoutée à l'envers aussi : sert de garde-fou, même si on ne
        # change pas de bande latérale tout seul (self.mirror)
        self.flipped.add(self._comb(peaks[self.mirror_idx]))
        if len(self.normal.history) < 20:
            self.status = "écoute du bruit de fond…"
            return None
        if voiced and self.normal.frames >= 5:
            self.estimate = self.normal.peak(self.ds, 1.0)[0]
        # l'autre bande latérale, si elle seule donne une voix cohérente
        if self.mirror and self.flipped.frames >= MIN_FRAMES:
            dm, clear_m, ratio_m = self.flipped.peak(self.ds, FLIP_MARGIN)
            _, clear_n, ratio_n = self.normal.peak(self.ds, MARGIN)
            if clear_m and (not clear_n or ratio_m < ratio_n):
                self.status = "correspondant sur l'autre bande latérale"
                return ("flip", 2 * MIRROR - dm)
        if not voiced:
            if self.normal.frames < 1:
                self.status = "voix trop faible dans le bruit"
            return None
        frames = self.normal.frames
        if frames < QUICK_FRAMES:
            self.status = f"écoute de la voix… {int(frames)}/{QUICK_FRAMES}"
            return None
        margin = MARGIN if frames >= MIN_FRAMES else QUICK_MARGIN
        d, clear, ratio = self.normal.peak(self.ds, margin)
        if clear and self.flipped.frames >= 3:
            # l'écoute à l'envers doit être nettement moins nette
            clear = ratio < 0.8 * self.flipped.peak(self.ds, 1.0)[2]
        if not clear:
            self.status = "voix peu nette, calage en attente"
            return None
        self.estimate = d
        if abs(d) < MIN_SHIFT:
            self.locked = True
            self.status = f"calé (écart {d:+.0f} Hz)"
            return None
        self.locked = False
        self.status = f"correction {d:+.0f} Hz"
        return ("shift", d)

    def _comb(self, peaks):
        hits = (peaks[self.pos] - peaks[self.mid]) * self.valid[:, :, None]
        return hits.sum(axis=1) / self.count[:, None]      # (F0, d)
