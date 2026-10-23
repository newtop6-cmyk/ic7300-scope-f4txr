"""Reconnaissance du mode (LSB, USB, AM, FM) et de la fréquence exacte d'une
station, d'après le spectre du scope de la radio autour de la fréquence écoutée.

- AM  : porteuse nette avec des bandes latérales des deux côtés → la porteuse ;
- FM  : bloc large (≥ 7 kHz), sans côté dominant → son centre ;
- BLU : bloc de voix de 1,5 à 4 kHz, sans porteuse → LSB ou USB selon l'usage
        de la bande, porteuse estimée au bord de la voix, arrondie au kHz.
Une porteuse seule (CW, sifflement) ou un signal trop faible : None."""

import numpy as np

STRONG = 6.0            # le bloc doit dépasser le fond d'au moins 6 unités
ABOVE = 3.5             # un point « occupé » dépasse le fond de 3,5 unités
GAP_HZ = 400            # trous tolérés dans un même bloc
SEARCH_HZ = 6000        # le bloc doit toucher la zone ± 6 kHz autour du curseur
CARRIER_DB = 7.0        # porteuse AM : pointe nettement au-dessus du bloc


def usual_sideband(hz):
    """LSB sous 10 MHz (sauf 60 m), USB au-dessus."""
    if 5_330_000 <= hz <= 5_410_000:
        return "USB"
    return "LSB" if hz < 10_000_000 else "USB"


FM_MIN_HZ = 28_000_000  # en dessous (décamétrique), pas de FM : bloc large = BLU collées


def ssb_in_crowd(points, freqs, freq, floor):
    """Station BLU sous le curseur dans un bloc encombré : porteuse au kHz
    rond qui a la voix du bon côté et le moins de signal de l'autre côté."""
    side = usual_sideband(freq)
    sign = -1 if side == "LSB" else 1           # côté de la voix
    best, best_score = None, None
    base = round(freq / 1000) * 1000
    for k in range(-3, 4):
        c = base + k * 1000
        a, b = sorted((c + sign * 300, c + sign * 2700))
        voice = points[(freqs >= a) & (freqs <= b)]
        a2, b2 = sorted((c - sign * 150, c - sign * 700))
        other = points[(freqs >= a2) & (freqs <= b2)]
        if voice.size < 3 or other.size < 1:
            continue
        if voice.mean() < floor + STRONG / 2:
            continue
        # voix forte, côté opposé calme, et proximité du curseur
        score = (voice.mean() - floor) - 0.3 * (other.mean() - floor) \
            - 4.0 * abs(c - freq) / 1000
        if best_score is None or score > best_score:
            best, best_score = c, score
    if best is None or best_score < 2:
        return None
    return side, int(best)


def analyse(points, low, high, freq):
    """(mode, fréquence) de la station sous le curseur, ou None."""
    points = np.asarray(points, float)
    n = len(points)
    if n < 50 or not low < freq < high:
        return None
    step = (high - low) / n
    freqs = low + (np.arange(n) + 0.5) * step
    floor = np.percentile(points, 30)
    occupied = points > floor + ABOVE
    # blocs de points occupés (petits trous comblés)
    gap = max(1, int(GAP_HZ / step))
    blocks, start, last = [], None, None
    for i in np.flatnonzero(occupied):
        if start is None:
            start = last = i
        elif i - last <= gap:
            last = i
        else:
            blocks.append((start, last))
            start = last = i
    if start is not None:
        blocks.append((start, last))
    # le bloc le plus proche du curseur, dans ± SEARCH_HZ
    best, best_dist = None, None
    for a, b in blocks:
        lo, hi = freqs[a] - step / 2, freqs[b] + step / 2
        dist = 0 if lo <= freq <= hi else min(abs(freq - lo), abs(freq - hi))
        if dist <= SEARCH_HZ and (best_dist is None or dist < best_dist):
            best, best_dist = (a, b), dist
    if best is None:
        return None
    a, b = best
    seg = points[a:b + 1]
    if seg.mean() < floor + STRONG / 2 or seg.max() < floor + STRONG:
        return None                                 # trop faible
    lo, hi = freqs[a] - step / 2, freqs[b] + step / 2
    width = hi - lo
    if width < 600:
        return None                                 # porteuse seule : CW, sifflement
    touches_edge = a == 0 or b == n - 1
    # porteuse : pointe étroite nettement au-dessus du reste du bloc
    k = int(np.argmax(seg))
    peak = seg[k]
    others = np.delete(seg, range(max(0, k - 2), min(len(seg), k + 3)))
    carrier = others.size and peak >= np.median(others) + CARRIER_DB
    if carrier:
        # position fine de la pointe (interpolation parabolique)
        i = a + k
        if 0 < i < n - 1:
            l, c, r = points[i - 1], points[i], points[i + 1]
            den = l - 2 * c + r
            off = 0.5 * (l - r) / den if den else 0.0
        else:
            off = 0.0
        fc = freqs[i] + off * step
        left = (points[a:max(a, i - 2)] > floor + ABOVE).sum() * step
        right = (points[min(b + 1, i + 3):b + 1] > floor + ABOVE).sum() * step
        khz = round(fc / 1000) * 1000
        # vraie AM : porteuse sur un kHz rond, bandes latérales symétriques
        # (une voix BLU avec un pic dedans n'est pas de l'AM)
        if min(left, right) >= 1500 and min(left, right) >= 0.6 * max(left, right) \
                and width <= 12_000 and abs(fc - khz) < 200:
            return "AM", int(khz)
    if width >= 7000 and not touches_edge and freq >= FM_MIN_HZ:
        centre = (lo + hi) / 2
        return "FM", int(round(centre / 500) * 500)
    if width >= 1500:
        # BLU : on juge par la porteuse la plus proche du curseur (marche aussi
        # quand plusieurs stations sont collées)
        found = ssb_in_crowd(points, freqs, freq, floor)
        if found or width > 4000:
            return found
    if 1500 <= width <= 4000:              # voix BLU, même avec un pic de voix
        side = usual_sideband(freq)
        edge = hi + 300 if side == "LSB" else lo - 300
        return side, int(round(edge / 1000) * 1000)
    return None


CW_SEARCH_HZ = 1500     # porteuse CW cherchée à ± 1,5 kHz du curseur
# portions CW des bandes (Hz) : hors de là, pas de « CW » (évite de prendre
# un bout de voix BLU faible pour une porteuse)
CW_SEGMENTS = [(1_810_000, 1_838_000), (3_500_000, 3_570_000),
               (7_000_000, 7_040_000), (10_100_000, 10_150_000),
               (14_000_000, 14_070_000), (18_068_000, 18_095_000),
               (21_000_000, 21_070_000), (24_890_000, 24_915_000),
               (28_000_000, 28_070_000), (50_000_000, 50_100_000)]


def in_cw_segment(hz):
    return any(lo <= hz <= hi for lo, hi in CW_SEGMENTS)


def analyse_station(points, low, high, freq):
    """Comme analyse(), mais reconnaît aussi une porteuse CW seule :
    ("CW", fréquence de la porteuse arrondie à 10 Hz)."""
    result = analyse(points, low, high, freq)
    if result or not in_cw_segment(freq):
        return result
    points = np.asarray(points, float)
    n = len(points)
    if n < 50 or not low < freq < high:
        return None
    step = (high - low) / n
    freqs = low + (np.arange(n) + 0.5) * step
    floor = np.percentile(points, 30)
    near = np.flatnonzero(np.abs(freqs - freq) <= CW_SEARCH_HZ)
    if near.size == 0:
        return None
    i = int(near[np.argmax(points[near])])
    if points[i] < floor + STRONG:
        return None
    # largeur à mi-hauteur : une porteuse CW reste étroite
    half = floor + (points[i] - floor) / 2
    a = b = i
    while a > 0 and points[a - 1] > half:
        a -= 1
    while b < n - 1 and points[b + 1] > half:
        b += 1
    if (b - a + 1) * step > 600:
        return None
    # porteuse isolée : autour (hors ± 300 Hz) presque rien d'occupé
    ring = np.flatnonzero((np.abs(freqs - freqs[i]) <= 1500)
                          & (np.abs(freqs - freqs[i]) > 300))
    if ring.size and (points[ring] > floor + ABOVE).mean() > 0.25:
        return None
    off = 0.0
    if 0 < i < n - 1:
        l, c, r = points[i - 1], points[i], points[i + 1]
        den = l - 2 * c + r
        off = 0.5 * (l - r) / den if den else 0.0
    return "CW", int(round((freqs[i] + off * step) / 10) * 10)
