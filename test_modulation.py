#!/usr/bin/env python3
"""Test de modulation sans émettre : écoute le micro N secondes (parler
normalement) et compare au niveau de la dernière émission réelle (po.log)."""
import subprocess, sys, numpy as np
SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 10
mic = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True).stdout.strip()
p = subprocess.Popen(["parec", f"--device={mic}", "--raw", "--format=s16le", "--rate=16000",
                      "--channels=1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
raw = p.stdout.read(16000 * 2 * SEC); p.terminate()
x = np.frombuffer(raw, np.int16).astype(float) / 32768
blocks = x[: len(x) // 320 * 320].reshape(-1, 320)          # 20 ms, comme le VOX
db = 20 * np.log10(np.sqrt((blocks ** 2).mean(1)) + 1e-9)
voice = db[db > -40]
ref = []
for line in open("/home/marco/claude/ic7300-scope/po.log"):
    parts = line.split()
    if len(parts) == 3 and parts[2] != "None" and float(parts[2]) > -40:
        ref.append(float(parts[2]))
ref = ref[-400:]
print(f"micro : {mic}")
if len(voice) < 20:
    print("pas assez de parole entendue : parlez plus près du micro et recommencez")
else:
    print(f"maintenant  : médiane {np.median(voice):.1f} dB, crêtes {np.percentile(voice, 98):.1f} dB "
          f"({len(voice) * 20 / 1000:.1f} s de parole)")
if ref:
    print(f"émission de cette nuit : médiane {np.median(ref):.1f} dB, crêtes {np.percentile(ref, 98):.1f} dB")
