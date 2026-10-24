#!/usr/bin/env python3
"""Auto-test d'IC-7300 Scope en mode distant (aucune émission radio).

    python3 autotest.py            → tableau d'audit dans le terminal
Vérifie : fichiers, processus, réseau, Pi, son reçu, chemin d'émission
(ton de test jusqu'à la carte son du Pi, radio NON passée en émission),
liaisons son du PC, casque, micro, galva, journal du waterfall.
"""

import glob
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PI = "100.76.125.118"
PI_SINK = "alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"
ENV = dict(os.environ, LC_ALL="C")
rows = []


def add(group, item, ok, detail):
    rows.append((group, item, ok, detail))


def run(cmd, timeout=15, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=ENV, **kw).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def ssh(command, timeout=15):
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                f"marco@{PI}", command], timeout=timeout)


def blocks_db(raw, block=160):
    x = np.frombuffer(raw, "<i2").astype(float) / 32768
    n = len(x) // block
    if n == 0:
        return np.array([])
    return 20 * np.log10(np.sqrt((x[:n * block].reshape(n, block) ** 2).mean(1)) + 1e-9)


# 1. fichiers
bad = []
for f in sorted(glob.glob(os.path.join(HERE, "*.py"))):
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError:
        bad.append(os.path.basename(f))
add("Logiciel", "Fichiers Python", not bad,
    "tous corrects" if not bad else "erreur : " + ", ".join(bad))

# 2. processus
for name, pattern in (("Scope", "^python3 .*ic7300_scope.py"),
                      ("Relais réception", "rx_relay.py"),
                      ("Flux émission", "^parec --device=ic7300_distant_tx.monitor")):
    found = bool(run(["pgrep", "-f", pattern]).strip())
    add("Logiciel", name, found, "en marche" if found else "ARRÊTÉ")

# 3. réseau
out = run(["ping", "-c", "30", "-i", "0.2", "-q", PI], timeout=20)
loss = next((l for l in out.splitlines() if "packet loss" in l), "")
rtt = next((l for l in out.splitlines() if "rtt" in l), "")
try:
    lost = float(loss.split("%")[0].split()[-1])
    mn, avg, mx = [float(v) for v in rtt.split("=")[1].split()[0].split("/")[:3]]
    add("Réseau", "Liaison PC → Pi", lost == 0 and mx < 150,
        f"perte {lost:.0f} %, moyenne {avg:.0f} ms, pointe {mx:.0f} ms")
except (ValueError, IndexError):
    add("Réseau", "Liaison PC → Pi", False, "Pi injoignable")
wifi = run(["nmcli", "-t", "-f", "ACTIVE,SSID,CHAN,SIGNAL", "dev", "wifi"])
active = next((l for l in wifi.splitlines() if l.split(":")[0] in ("yes", "oui")), "")
if active:
    _, ssid, chan, sig = active.split(":")[:4]
    add("Réseau", "Wi-Fi du PC", int(chan) > 14,
        f"{ssid}, canal {chan} ({'5 GHz' if int(chan) > 14 else '2,4 GHz'}), signal {sig} %")

# 4. Pi
pi = ssh("systemctl --user is-active ic7300-cat-server; vcgencmd measure_temp; "
         f"wpctl get-volume $(wpctl status | grep -m1 'PCM2901' | grep -o '[0-9]\\+' | head -1); "
         "uptime -p").splitlines()
if pi:
    add("Raspberry Pi", "Serveur radio (CAT)", pi[0].strip() == "active", pi[0].strip())
    temp = pi[1].split("=")[-1] if len(pi) > 1 else "?"
    try:
        t = float(temp.rstrip("'C"))
        add("Raspberry Pi", "Température", t < 70, temp)
    except ValueError:
        add("Raspberry Pi", "Température", False, temp)
    add("Raspberry Pi", "Allumé depuis", True, pi[-1].replace("up ", ""))
else:
    add("Raspberry Pi", "Accès SSH", False, "pas de réponse")

# 5. son reçu
try:
    raw = subprocess.run(["timeout", "10", "parec", "-d", "ic7300_distant_rx", "--raw",
                          "--format=s16le", "--rate=16000", "--channels=1",
                          "--latency-msec=20"], capture_output=True, timeout=15).stdout
except subprocess.SubprocessError:
    raw = b""
e = blocks_db(raw)
if len(e):
    silent = e < -80
    gaps, run_len = [], 0
    for v in silent:
        if v:
            run_len += 1
        elif run_len:
            gaps.append(run_len)
            run_len = 0
    if run_len:
        gaps.append(run_len)
    lost_ms = sum(gaps) * 10
    add("Son", "Réception radio → PC (10 s)", lost_ms < 300,
        f"niveau {np.median(e):.0f} dBFS, {len(gaps)} coupure(s), {lost_ms} ms perdus")
else:
    add("Son", "Réception radio → PC (10 s)", False, "aucun son")

# 6. chemin d'émission (ton de test, radio NON en émission)
tone = (0.3 * np.sin(2 * np.pi * 1000 * np.arange(32000) / 16000) * 32767).astype("<i2")
with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
    f.write(tone.tobytes())
    tone_file = f.name
rec = subprocess.Popen(["ssh", "-o", "BatchMode=yes", f"marco@{PI}",
                        f"timeout 5 pw-record --target {PI_SINK} -P stream.capture.sink=true "
                        "--rate 16000 --channels 1 --format s16 -"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
time.sleep(1.5)
run(["timeout", "3", "pacat", "--playback", "--latency-msec=20", "-d", "ic7300_distant_tx",
     "--raw", "--format=s16le", "--rate=16000", "--channels=1", tone_file], timeout=6)
got = rec.communicate(timeout=10)[0]
os.unlink(tone_file)
e = blocks_db(got, 1600)
on = e[e > -40]
add("Son", "Chemin d'émission PC → radio", len(on) >= 15,
    f"ton reçu {len(on) / 10:.1f} s sur 2 s à {on.max():.0f} dBFS" if len(on) else "ton NON reçu")

# 7. liaisons son du PC
try:
    streams = json.loads(run(["pactl", "-f", "json", "list", "sink-inputs"]))
except ValueError:
    streams = []
by_name = {(s["properties"].get("node.name") or s["properties"].get("application.name")): s
           for s in streams}
lo = by_name.get("ic7300_loopback_out")
if lo:
    vol = list(lo["volume"].values())[0]["value_percent"]
    add("Son", "Écoute radio (Volume PC)", not lo["mute"],
        f"{'MUET' if lo['mute'] else 'son actif'}, {vol}")
else:
    add("Son", "Écoute radio (Volume PC)", False, "absente")
mic = by_name.get("ic7300_tx_micro")
add("Son", "Micro → radio hors émission", bool(mic and mic["mute"]),
    "coupé (normal)" if mic and mic["mute"] else "OUVERT ou absent")
sink = run(["pactl", "get-default-sink"]).strip()
src = run(["pactl", "get-default-source"]).strip()
headset = "usb" in sink and "Burr" not in sink
add("Son", "Sortie active", True, "casque" if headset else "haut-parleurs du PC")
vol = run(["pactl", "get-sink-volume", sink]).split("/")
add("Son", "Volume de la sortie", True, vol[1].strip() if len(vol) > 1 else "?")
add("Son", "Micro par défaut", "usb" in src, "casque" if "usb" in src else "micro du PC")
try:
    mraw = subprocess.run(["timeout", "3", "parec", "-d", src, "--raw", "--format=s16le",
                           "--rate=16000", "--channels=1"], capture_output=True,
                          timeout=6).stdout
    me = blocks_db(mraw)[20:]
    add("Son", "Bruit du micro (VOX)", np.median(me) < -50,
        f"médian {np.median(me):.0f} dBFS (seuil VOX à 50 % : −35)")
except subprocess.SubprocessError:
    add("Son", "Bruit du micro (VOX)", False, "lecture impossible")

# 8. galva (rendu hors écran)
g = run([sys.executable, "-c",
         "import sys; sys.path.insert(0, %r)\n" % HERE +
         "import os; os.environ['QT_QPA_PLATFORM']='offscreen'\n"
         "from PyQt5 import QtWidgets\nfrom tx_galva import TxGalva\n"
         "app=QtWidgets.QApplication([])\ng=TxGalva(); g.set_tx(True); g.set_po(8); g.set_comp(10)\n"
         "[g._tick() for _ in range(90)]\nprint('%.2f %.2f' % (g.po.pos, g.comp.pos))"])
try:
    po, comp = [float(v) for v in g.split()[-2:]]
    add("Affichage", "Galva (8 W, 10 dB)", 0.4 < po < 0.6 and comp > 0.3,
        f"aiguille Po {po:.2f}, COMP {comp:.2f}")
except ValueError:
    add("Affichage", "Galva", False, "rendu impossible")

# 9. waterfall : relances dans les 10 dernières minutes
log = os.path.join(HERE, "tx-debug.log")
recent = 0
if os.path.exists(log):
    now = time.time()
    today = time.strftime("%Y-%m-%d ")
    for line in open(log, errors="ignore").read().splitlines()[-200:]:
        if "relance" in line:
            try:
                t = time.mktime(time.strptime(today + line.split(".")[0], "%Y-%m-%d %H:%M:%S"))
                recent += now - t < 600
            except ValueError:
                pass
add("Affichage", "Waterfall (relances / 10 min)", recent <= 3, f"{recent} relance(s)")

# tableau
w1 = max(len(r[0]) for r in rows)
w2 = max(len(r[1]) for r in rows)
print(f"\nAUDIT IC-7300 Scope — {time.strftime('%d/%m/%Y %H:%M')} (aucune émission)\n")
print(f"{'Domaine':<{w1}}  {'Contrôle':<{w2}}  État  Détail")
print("-" * (w1 + w2 + 60))
for group, item, ok, detail in rows:
    print(f"{group:<{w1}}  {item:<{w2}}  {'OK ' if ok else '⚠️ '}   {detail}")
good = sum(r[2] for r in rows)
print(f"\n{good}/{len(rows)} contrôles OK")
