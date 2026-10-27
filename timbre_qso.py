"""Timbre « QSO » pour les messages VOX n : la voix brute du micro est égalisée
pour avoir le même timbre que la référence (~/.config/ic7300-scope/
timbre-reference.wav : le message préféré de l'utilisateur), fond nettoyé,
compression très légère (2:1), crête mise à -1 dB.

Usage : apply(entrée_wav, sortie_wav) → durée (s) ; lève une exception si échec."""

import os
import subprocess
import wave

import numpy as np
from scipy import signal

REFERENCE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                         "ic7300-scope", "timbre-reference.wav")
FINISH = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.15,"
          "areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.25,"
          "areverse,"
          # fond sonore nettoyé, sans pompage : réduction de bruit + porte douce
          "afftdn=nr=14:nf=-55:tn=1,"
          "agate=threshold=0.015:ratio=3:attack=5:release=150:range=0.15,"
          # compression très légère (2:1) : la voix garde son relief
          "acompressor=threshold=-22dB:ratio=2:attack=10:release=200:makeup=2dB,"
          "alimiter=limit=0.89:level=false,afade=t=in:d=0.03")


def _read(path):
    with wave.open(path) as w:
        rate, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), "<i2").astype(np.float64) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    return x, rate


def _speech(x, rate):
    """Seulement les passages de parole (les silences fausseraient le timbre)."""
    n = int(0.03 * rate)
    m = len(x) // n
    if m == 0:
        return x
    blocks = x[:m * n].reshape(m, n)
    db = 10 * np.log10((blocks ** 2).mean(1) + 1e-12)
    keep = blocks[db > db.max() - 25]
    return keep.ravel() if len(keep) else x


def apply(src, dst):
    raw, rate = _read(src)
    if not os.path.exists(REFERENCE):
        y = raw                                     # pas de référence : voix telle quelle
    else:
        ref, rref = _read(REFERENCE)
        if rref != rate:
            ref = signal.resample_poly(ref, rate, rref)
        f, pa = signal.welch(_speech(raw, rate), rate, nperseg=4096)
        _, pb = signal.welch(_speech(ref, rate), rate, nperseg=4096)
        g = 10 * np.log10(pb + 1e-15) - 10 * np.log10(pa + 1e-15)
        sm = np.array([np.mean(g[(f >= fc / 2 ** (1 / 6)) & (f <= fc * 2 ** (1 / 6))])
                       for fc in np.maximum(f, 25)])
        sm -= np.median(sm[(f > 800) & (f < 2500)])
        sm = np.clip(sm, -30, 15)                   # graves : jusqu’à -30 dB
        sm[f < 150] = -30
        sm[f > 3400] = np.minimum(sm[f > 3400], -20)
        taps = signal.firwin2(2047, f / (rate / 2), 10 ** (sm / 20))
        y = signal.fftconvolve(raw, taps, mode="same")
    peak = np.max(np.abs(y)) or 1.0
    y = y / peak * 0.5
    tmp = dst + ".tmp.wav"
    with wave.open(tmp, "wb") as o:
        o.setnchannels(1)
        o.setsampwidth(2)
        o.setframerate(rate)
        o.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-af", FINISH,
                           "-ar", "48000", "-ac", "1", dst], capture_output=True, text=True)
    os.remove(tmp)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-150:])
    # volume final : crête à -1 dB (gain simple, sans écraser)
    with wave.open(dst) as w:
        rate_o, frames = w.getframerate(), w.readframes(w.getnframes())
    z = np.frombuffer(frames, "<i2").astype(np.float64) / 32768
    peak = np.max(np.abs(z)) if len(z) else 0
    if peak > 0:
        z = z * (10 ** (-1 / 20) / peak)
    with wave.open(dst, "wb") as o:
        o.setnchannels(1)
        o.setsampwidth(2)
        o.setframerate(rate_o)
        o.writeframes((np.clip(z, -1, 1) * 32767).astype("<i2").tobytes())
    return len(z) / rate_o
