"""SSTV : réception (décodage du son en image) et émission (image en son).

Une image SSTV commence par un en-tête VIS (1900 Hz, coupure à 1200 Hz,
1900 Hz, puis 8 bits de 30 ms) qui donne le mode. Chaque ligne est ensuite
une suite de segments : top de synchro à 1200 Hz, paliers, et balayages où la
fréquence code la luminosité (1500 Hz noir, 2300 Hz blanc).

Le décodeur suit la fréquence instantanée, cherche l'en-tête, puis lit les
lignes en se recalant à chaque top de synchro (ce qui corrige la pente due
aux petits écarts d'horloge entre l'émetteur et la carte son).
"""
import threading

import numpy as np

from psk31_decoder import lowpass

SYNC_HZ, BLACK_HZ, WHITE_HZ, LEADER_HZ = 1200.0, 1500.0, 2300.0, 1900.0
CENTER_HZ = 1700.0              # milieu de la bande utile (1100 à 2300 Hz)
WORK_RATE = 12000               # fréquence de travail du décodeur (Hz)
MS = WORK_RATE // 1000          # échantillons par milliseconde
SMOOTH = 4                      # moyenne de la mesure de fréquence (0,33 ms) : moins de bruit
FREQ_MIN, FREQ_MAX = 1000.0, 2600.0     # au-delà : parasite, ramené dans la bande


class Mode:
    def __init__(self, name, vis, width, height, segments, family,
                 rows_per_period=1, first_sync=0.0):
        self.name = name
        self.vis = vis
        self.width = width
        self.height = height
        self.segments = segments    # [(type, durée en ms)]
        self.family = family        # rgb, robot36, robot72, pd
        self.rows_per_period = rows_per_period
        self.first_sync = first_sync  # top de synchro avant la 1re ligne (Scottie)
        self.period = sum(d for _, d in segments)
        self.periods = height // rows_per_period
        offset = 0.0
        self.sync_offset = None
        self.sync_length = 0.0
        for kind, duration in segments:
            if kind == "sync":
                self.sync_offset, self.sync_length = offset, duration
                break
            offset += duration

    @property
    def duration(self):
        """Durée de l'image, en-tête VIS compris (s)."""
        return 0.91 + (self.first_sync + self.period * self.periods) / 1000


def _martin(name, vis, scan):
    return Mode(name, vis, 320, 256,
                [("sync", 4.862), ("porch", 0.572), ("G", scan), ("sep", 0.572),
                 ("B", scan), ("sep", 0.572), ("R", scan), ("sep", 0.572)], "rgb")


def _scottie(name, vis, scan):
    return Mode(name, vis, 320, 256,
                [("sep", 1.5), ("G", scan), ("sep", 1.5), ("B", scan),
                 ("sync", 9.0), ("porch", 1.5), ("R", scan)], "rgb", first_sync=9.0)


def _pd(name, vis, width, height, scan):
    return Mode(name, vis, width, height,
                [("sync", 20.0), ("porch", 2.08), ("Y0", scan), ("V", scan),
                 ("U", scan), ("Y1", scan)], "pd", rows_per_period=2)


def _wraase(name, vis, scan):
    """Wraase SC2 : synchro, palier, puis R, G, B pleine ligne (sans séparateur)."""
    return Mode(name, vis, 320, 256,
                [("sync", 5.5225), ("porch", 0.5), ("R", scan), ("G", scan),
                 ("B", scan)], "rgb")


MODES = [
    _wraase("Wraase SC2-180", 55, 235.0),
    _wraase("Wraase SC2-120", 63, 156.5),
    _martin("Martin M1", 44, 146.432),
    _martin("Martin M2", 40, 73.216),
    _scottie("Scottie S1", 60, 138.24),
    _scottie("Scottie S2", 56, 88.064),
    _scottie("Scottie DX", 76, 345.6),
    Mode("Robot 36", 8, 320, 240,
         [("sync", 9.0), ("porch", 3.0), ("Y", 88.0), ("csep", 4.5),
          ("cporch", 1.5), ("C", 44.0)], "robot36"),
    Mode("Robot 72", 12, 320, 240,
         [("sync", 9.0), ("porch", 3.0), ("Y", 138.0), ("vsep", 4.5),
          ("cporch", 1.5), ("V", 69.0), ("usep", 4.5), ("cporch", 1.5),
          ("U", 69.0)], "robot72"),
    _pd("PD 50", 93, 320, 256, 91.52),
    _pd("PD 90", 99, 320, 256, 170.24),
    _pd("PD 120", 95, 640, 496, 121.6),
    _pd("PD 160", 98, 512, 400, 195.584),
    _pd("PD 180", 96, 640, 496, 183.04),
    _pd("PD 240", 97, 640, 496, 244.48),
    _pd("PD 290", 94, 800, 616, 228.8),
]
BY_VIS = {m.vis: m for m in MODES}
BY_NAME = {m.name: m for m in MODES}

# fréquence fixe de chaque segment qui n'est pas un balayage
FIXED_HZ = {"sync": SYNC_HZ, "porch": BLACK_HZ, "sep": BLACK_HZ,
            "cporch": LEADER_HZ, "vsep": BLACK_HZ, "usep": WHITE_HZ}


def _chroma_width(mode, kind):
    """Les modes Robot transmettent la couleur à demi-résolution."""
    if mode.family in ("robot36", "robot72") and kind in ("C", "U", "V"):
        return mode.width // 2
    return mode.width


# --- couleurs : YUV pleine échelle (comme slowrx et MMSSTV)

def rgb_to_yuv(rgb):
    rgb = rgb.astype(np.float32)
    y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    u = 128 + 0.564 * (rgb[..., 2] - y)
    v = 128 + 0.713 * (rgb[..., 0] - y)
    return y, u, v


def yuv_to_rgb(y, u, v):
    r = y + 1.402 * (v - 128)
    g = y - 0.344 * (u - 128) - 0.714 * (v - 128)
    b = y + 1.772 * (u - 128)
    return np.clip(np.stack([r, g, b], axis=-1), 0, 255).astype(np.uint8)


def value_to_hz(v):
    return BLACK_HZ + np.asarray(v, np.float32) / 255 * (WHITE_HZ - BLACK_HZ)


def hz_to_value(f):
    return np.clip((f - BLACK_HZ) / (WHITE_HZ - BLACK_HZ) * 255, 0, 255)


# --- émission

def encode(mode, rgb, rate=48000, amplitude=0.7):
    """Image RVB (hauteur × largeur × 3, à la taille du mode) → son SSTV."""
    rgb = np.asarray(rgb, np.uint8)
    assert rgb.shape[:2] == (mode.height, mode.width), "image à la taille du mode"
    y, u, v = rgb_to_yuv(rgb)
    parts = []                      # (fréquences, durée en ms)

    def tone(hz, ms):
        parts.append((np.array([hz], np.float32), ms))

    def scan(values, ms):
        parts.append((value_to_hz(values), ms))

    def half(row):                  # demi-résolution horizontale
        return row.reshape(-1, 2).mean(axis=1)

    # en-tête VIS : bits de poids faible d'abord, parité paire
    tone(LEADER_HZ, 300)
    tone(SYNC_HZ, 10)
    tone(LEADER_HZ, 300)
    tone(SYNC_HZ, 30)
    bits = [(mode.vis >> i) & 1 for i in range(7)]
    bits.append(sum(bits) % 2)
    for bit in bits:
        tone(1100 if bit else 1300, 30)
    tone(SYNC_HZ, 30)
    if mode.first_sync:
        tone(SYNC_HZ, mode.first_sync)

    for period in range(mode.periods):
        row = period * mode.rows_per_period
        for kind, ms in mode.segments:
            if kind in FIXED_HZ:
                tone(FIXED_HZ[kind], ms)
            elif kind == "csep":        # Robot 36 : 1500 Hz avant R-Y, 2300 avant B-Y
                tone(BLACK_HZ if row % 2 == 0 else WHITE_HZ, ms)
            elif kind in "RGB":
                scan(rgb[row, :, "RGB".index(kind)], ms)
            elif kind == "Y":
                scan(y[row], ms)
            elif kind == "C":           # Robot 36 : couleur d'une paire de lignes
                pair = slice(row - row % 2, row - row % 2 + 2)
                scan(half((v if row % 2 == 0 else u)[pair].mean(axis=0)), ms)
            elif kind in ("U", "V") and mode.family == "robot72":
                scan(half((u if kind == "U" else v)[row]), ms)
            elif kind in ("U", "V"):    # PD : couleur commune aux deux lignes
                scan((u if kind == "U" else v)[row:row + 2].mean(axis=0), ms)
            elif kind == "Y0":
                scan(y[row], ms)
            elif kind == "Y1":
                scan(y[row + 1], ms)

    # fréquence échantillon par échantillon, avec un temps qui ne dérive pas
    total = sum(ms for _, ms in parts)
    freq = np.empty(int(round(total / 1000 * rate)), np.float32)
    t = 0.0
    for values, ms in parts:
        a, b = int(round(t / 1000 * rate)), int(round((t + ms) / 1000 * rate))
        if len(values) == 1:
            freq[a:b] = values[0]
        else:
            index = ((np.arange(a, b) - t / 1000 * rate) / (ms / 1000 * rate)
                     * len(values)).astype(int)
            freq[a:b] = values[np.clip(index, 0, len(values) - 1)]
        t += ms
    # en double précision : en simple, le cumul perd la phase au bout de
    # quelques dizaines de secondes et les fréquences dérivent
    phase = np.mod(2 * np.pi * np.cumsum(freq, dtype=np.float64) / rate, 2 * np.pi)
    return (amplitude * np.sin(phase)).astype(np.float32)


# --- réception

class SstvDecoder:
    """Décode en continu ; l'image en cours est dans `image` (RVB uint8)."""

    def __init__(self, rate):
        self.rate = rate
        self._decim = rate // WORK_RATE
        self._fir = lowpass(750, rate, 255)
        self._fir_state = np.zeros(len(self._fir) - 1, complex)
        self._phase = 0.0
        self._pending = np.zeros(0, np.float32)
        self._decim_count = 0
        self._prev = None
        self._prod_tail = np.zeros(SMOOTH - 1, complex)
        self._lock = threading.Lock()
        self.finished = []          # (mode, image) terminées, à enregistrer
        self.tune_offset = 0.0      # Hz ajoutés (correspondant mal calé : tops ≠ 1200 Hz)
        self.patient = False        # image sans en-tête : tolère plus de tops manqués
        self.reset()

    def reset(self):
        with self._lock:
            self._freq = np.zeros(0, np.float32)    # fréquence instantanée
            self._base = 0                          # indice absolu de _freq[0]
            self._searched = 0                      # VIS cherché jusqu'ici
            self.mode = None
            self.image = None
            self.line = 0                           # périodes décodées
            self._start = 0.0                       # début de la 1re période
            self._offset = 0.0                      # recalage par les synchros
            self._missed = 0
            self._uv = None

    def status(self):
        if self.mode is None:
            return "En attente d'une image (en-tête VIS)…"
        done = min(self.line * self.mode.rows_per_period, self.mode.height)
        return f"{self.mode.name} · ligne {done}/{self.mode.height}"

    # -- démodulation FM : fréquence instantanée à 12 kHz

    def feed(self, samples):
        n = np.arange(len(samples))
        step = 2 * np.pi * CENTER_HZ / self.rate
        mixed = samples * np.exp(-1j * (self._phase + step * n))
        self._phase = (self._phase + step * len(samples)) % (2 * np.pi)
        padded = np.concatenate([self._fir_state, mixed])
        filtered = np.convolve(padded, self._fir, mode="valid")
        self._fir_state = padded[len(padded) - len(self._fir_state):]
        first = (-self._decim_count) % self._decim
        self._decim_count += len(filtered)
        z = filtered[first::self._decim]
        if not len(z):
            return
        if self._prev is not None:
            z = np.concatenate([[self._prev], z])
        else:
            z = np.concatenate([[z[0]], z])
        self._prev = z[-1]
        # fréquence instantanée moins bruitée : produits z(k)·z*(k-1) moyennés sur
        # SMOOTH échantillons avant l'angle (bien meilleur dans le bruit que l'angle
        # de chaque produit), puis valeurs aberrantes (parasites) ramenées dans la bande
        prod = z[1:] * np.conj(z[:-1])
        prod = np.concatenate([self._prod_tail, prod])
        smooth = np.convolve(prod, np.ones(SMOOTH), mode="valid")
        self._prod_tail = prod[len(prod) - (SMOOTH - 1):]
        freq = (CENTER_HZ + self.tune_offset
                + np.angle(smooth) * WORK_RATE / (2 * np.pi))
        freq = np.clip(freq, FREQ_MIN, FREQ_MAX)
        with self._lock:
            self._freq = np.concatenate([self._freq, freq.astype(np.float32)])
            if self.mode is None:
                self._search_vis()
            if self.mode is not None:
                self._decode_lines()
            self._trim()

    def _trim(self):
        """Hors image, on ne garde que les dernières secondes."""
        if self.mode is None:
            drop = len(self._freq) - 2 * WORK_RATE
            if drop > 0:
                self._freq = self._freq[drop:]
                self._base += drop
                self._searched = max(self._searched, self._base)

    def _at(self, absolute):
        return absolute - self._base

    # -- en-tête VIS

    def _search_vis(self):
        blocks = len(self._freq) // MS
        if blocks < 500:
            return
        # médianes par milliseconde, puis par fenêtres : tient mieux au bruit
        ms = np.median(self._freq[:blocks * MS].reshape(blocks, MS), axis=1)
        med = lambda a, b: float(np.median(ms[a:b]))
        first = max((self._searched - self._base) // MS, 170)
        last = blocks - 310           # il faut 300 ms après le bit de départ
        for b in range(first, last):
            # front 1900 → 1200 Hz : début du bit de départ
            # tolérances un peu larges : le bruit tire les fréquences mesurées vers
            # le milieu de la bande ; parité et structure écartent les fausses alertes
            if abs(med(b, b + 25) - SYNC_HZ) > 90 or abs(med(b - 8, b) - LEADER_HZ) > 150:
                continue
            if abs(med(b, b + 8) - SYNC_HZ) > 130:
                continue                # b à quelques ms du front au plus
            if abs(med(b - 250, b - 15) - LEADER_HZ) > 90:
                continue
            bits = [med(b + 30 * (k + 1) + 5, b + 30 * (k + 2) - 5) for k in range(8)]
            if not all(1000 <= f < 1420 for f in bits):
                continue
            bits = [1 if f < SYNC_HZ else 0 for f in bits]
            if sum(bits[:7]) % 2 != bits[7]:
                continue
            mode = BY_VIS.get(sum(bit << k for k, bit in enumerate(bits[:7])))
            if mode is None:
                continue
            # place exacte du front, à l'échantillon près
            raw = self._freq
            around = range((b - 6) * MS, (b + 6) * MS)
            edge = max(around, key=lambda i: raw[i - 3 * MS:i].mean() - raw[i:i + 3 * MS].mean())
            self._begin(mode, self._base + edge + (300 + mode.first_sync) * MS)
            self._vis_edge = self._base + edge  # pour revérifier le mode au rythme des tops
            return
        self._searched = self._base + max(last, first) * MS

    def start_without_vis(self, mode):
        """Image prise en cours de route (en-tête VIS manqué) : on se cale sur
        le premier top de synchro des dernières secondes et on décode la suite
        avec ce mode (trouvé par la surveillance au rythme des tops)."""
        with self._lock:
            if self.mode is not None:
                return False
            blocks = len(self._freq) // MS
            if blocks < 200:
                return False
            ms = np.median(self._freq[:blocks * MS].reshape(blocks, MS), axis=1)
            low = ms < 1300
            i = 0
            while i < blocks:
                if low[i]:
                    j = i
                    while j < blocks and low[j]:
                        j += 1
                    if 3 <= j - i <= 25:
                        start = (i - mode.sync_offset) * MS
                        if start < 0:
                            start += mode.period * MS
                        self._begin(mode, self._base + start)
                        self.patient = True
                        return True
                    i = j
                else:
                    i += 1
            return False

    def _begin(self, mode, start):
        self.patient = False
        self.mode = mode
        self.image = np.zeros((mode.height, mode.width, 3), np.uint8)
        self.line = 0
        self._start = float(start)
        self._offset = 0.0
        self._missed = 0
        self._uv = None
        self._previous_y = None
        self._sync_hist = []                # (période, décalage) des tops bien reçus
        self._drift = 0.0                   # dérive d'horloge apprise (échantillons/période)
        self._good = 0                      # tops nets reçus
        self._vis_edge = None               # front de l'en-tête VIS (si reçu)
        self._checked = False               # mode revérifié au rythme des tops

    # -- lignes

    def _decode_lines(self):
        mode = self.mode
        period = mode.period * MS
        margin = 8 * MS
        while self.line < mode.periods:
            begin = self._start + self._offset + self.line * period
            if self._at(begin + period + margin) >= len(self._freq):
                return                  # la période n'est pas encore arrivée
            self._resync(begin)
            begin = self._start + self._offset + self.line * period
            self._decode_period(begin)
            self.line += 1
            if self.line == 8 and not self._checked and self._vis_edge is not None:
                self._checked = True
                if self._good < 5 and self._recheck_mode():
                    return                      # autre mode : l'image repart du début
                mode = self.mode
            # en-tête reçu : mode et durée connus, on va jusqu'au bout sauf si le
            # signal a vraiment disparu (60 tops manqués d'affilée)
            if self._missed > (40 if self.patient else 60) and self.line > 20:
                break                   # plus de synchro : fin du signal
        self._finish()

    def _sync_cost(self, expected):
        """Ressemblance à un top de synchro autour de `expected` (± 3 ms) : petit = net."""
        mode_len = None
        best = None
        for shift in range(-3 * MS, 3 * MS + 1, 3):
            a = self._at(expected + shift)
            if a < 0 or a + 40 * MS >= len(self._freq):
                return None
            mode_len = self._cand_len
            seg = self._freq[a:a + mode_len]
            cost = float(np.mean(np.minimum(np.abs(seg - SYNC_HZ), 400)))
            best = cost if best is None else min(best, cost)
        return best

    def _recheck_mode(self):
        """En-tête VIS peut-être mal lu dans le bruit (un bit faux = autre mode) :
        on essaie tous les modes au rythme réel des tops de synchro depuis l'en-tête,
        et on reprend l'image avec le meilleur s'il colle nettement mieux."""
        scores = []
        for mode in MODES:
            start = self._vis_edge + (300 + mode.first_sync) * MS
            self._cand_len = max(int(mode.sync_length * MS), MS)
            costs = []
            for k in range(8):
                c = self._sync_cost(int(round(start + k * mode.period * MS
                                              + mode.sync_offset * MS)))
                if c is None:
                    break
                costs.append(c)
            if len(costs) >= 4:
                scores.append((float(np.mean(costs)), mode, start))
        if not scores:
            return False
        scores.sort(key=lambda s: s[0])
        cost, mode, start = scores[0]
        current = next((c for c, m, _ in scores if m is self.mode), None)
        if mode is self.mode or cost > 200 or (current is not None and cost > 0.75 * current):
            return False
        edge = self._vis_edge
        self._begin(mode, start)
        self._vis_edge, self._checked = edge, True
        return True

    def _resync(self, begin):
        """Cherche le top de synchro autour de sa place prévue (± 6 ms).

        Juste après un top, la fréquence ne descend jamais sous le noir
        (1500 Hz) : on l'exige de 1 à 3 ms après sa fin, ce qui écarte les
        places trop tôt (et, pour la 1re ligne, le bit d'arrêt de l'en-tête,
        lui aussi à 1200 Hz).
        """
        mode = self.mode
        length = int(mode.sync_length * MS)
        expected = int(round(begin + mode.sync_offset * MS))
        best, best_cost = 0, None
        for shift in range(-6 * MS, 6 * MS + 1, 2):
            a = self._at(expected + shift)
            if a < 0:
                continue
            sync = self._freq[a:a + length]
            after = self._freq[a + length + MS:a + length + 3 * MS]
            cost = (np.mean(np.minimum(np.abs(sync - SYNC_HZ), 400))
                    + np.mean(np.clip(BLACK_HZ - 50 - after, 0, 400)))
            if best_cost is None or cost < best_cost:
                best, best_cost = shift, cost
        # dans le bruit, un « top » loin de la place prévue est un faux : refusé
        # (sauf s'il est très net) ; la 1re ligne cherche partout
        plausible = self.line == 0 or abs(best) <= 2 * MS or (best_cost is not None and best_cost < 90)
        if best_cost is not None and best_cost < 230 and plausible:
            # 1re ligne : on prend tout ; ensuite on lisse pour ne pas sauter
            # (top net : 0,5 ; top douteux dans le bruit : 0,2)
            weight = 1.0 if self.line == 0 else (0.5 if best_cost < 150 else 0.2)
            self._offset += weight * best
            self._missed = 0 if best_cost < 150 else self._missed
            self._good += best_cost < 150
            self._sync_hist.append((self.line, self._offset))
            self._sync_hist = self._sync_hist[-60:]
            if len(self._sync_hist) >= 12:      # dérive d'horloge (pente) par moindres carrés
                ls, os_ = np.array(self._sync_hist).T
                self._drift = float(np.polyfit(ls, os_, 1)[0])
        else:
            self._missed += 1
            self._offset += self._drift         # top manqué : on suit la dérive apprise

    def _scan(self, start_ms, ms, count, begin):
        """Moyenne de la fréquence sur `count` pixels d'un balayage."""
        a = begin + start_ms * MS
        edges = np.round(a + np.arange(count + 1) * (ms * MS / count)).astype(int)
        edges = np.clip(edges - self._base, 0, len(self._freq) - 1)
        lo = edges[0]
        part = self._freq[lo:edges[-1] + 2]
        sums = np.concatenate([[0.0], np.cumsum(part, dtype=np.float64)])
        starts = edges[:-1] - lo
        widths = np.maximum(edges[1:] - edges[:-1], 1)
        values = (sums[starts + widths] - sums[starts]) / widths
        # le dernier pixel déborde sur le segment suivant (synchro…) : liseré
        values[-1] = values[-2]
        return hz_to_value(values)

    def _decode_period(self, begin):
        mode = self.mode
        found = {}
        offset = 0.0
        for kind, ms in mode.segments:
            if kind in ("R", "G", "B", "Y", "Y0", "Y1", "U", "V", "C"):
                found[kind] = self._scan(offset, ms, _chroma_width(mode, kind), begin)
            elif kind == "csep":
                a = int(self._at(begin + offset * MS))
                found["csep"] = float(np.median(self._freq[a:a + int(ms * MS)]))
            offset += ms
        row = self.line * mode.rows_per_period
        if mode.family == "rgb":
            self.image[row] = np.stack([found["R"], found["G"], found["B"]],
                                       axis=-1).astype(np.uint8)
        elif mode.family == "pd":
            for k, y in enumerate((found["Y0"], found["Y1"])):
                if row + k < mode.height:
                    self.image[row + k] = yuv_to_rgb(y, found["U"], found["V"])
        else:
            if mode.family == "robot72":
                u, v = found["U"], found["V"]
            else:                       # Robot 36 : V et U une ligne sur deux
                u, v = self._uv or (np.full(mode.width // 2, 128.0),) * 2
                if found["csep"] < (BLACK_HZ + WHITE_HZ) / 2:
                    v = found["C"]
                else:
                    u = found["C"]
                self._uv = (u, v)
            full = lambda c: np.repeat(c, 2)[:mode.width]
            self.image[row] = yuv_to_rgb(found["Y"], full(u), full(v))
            if mode.family == "robot36" and row % 2 == 1 and self._previous_y is not None:
                # la paire est complète : on refait la ligne d'avant avec ses couleurs
                self.image[row - 1] = yuv_to_rgb(self._previous_y, full(u), full(v))
            self._previous_y = found["Y"]

    def _finish(self):
        rows = min(self.line * self.mode.rows_per_period, self.mode.height)
        if rows > 16:
            self.finished.append((self.mode, self.image[:rows].copy()))
        end = int(self._start + self._offset + self.line * self.mode.period * MS)
        self.mode = None
        self._searched = max(end, self._base)
