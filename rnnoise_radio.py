"""Filtre RNNoise (local, sans compte ni Internet) sur le son de la radio :
son de la radio → filtre RNNoise → haut-parleurs. La fenêtre garde une part
du son direct (non filtré), dosée selon la force du signal."""

import os
import subprocess

PLUGIN = os.path.expanduser("~/claude/rnnoise/librnnoise_ladspa.so")
FILTER = "ic7300_rnnoise"
# seuil de détection de voix (%), maintien (ms), maintien rétroactif (ms), 2 inutilisés
CONTROLS = "0,200,0,0,0"
ENV = {**os.environ, "LC_ALL": "C"}


def _pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, env=ENV)


def _modules():
    """Modules chargés pour ce filtre."""
    out = _pactl("list", "short", "modules").stdout
    return [line.split("\t")[0] for line in out.splitlines() if FILTER in line]


def active():
    return bool(_modules())


def on(source):
    """Branche le filtre ; renvoie un message d'erreur, ou None si tout va bien."""
    off()
    speakers = _pactl("get-default-sink").stdout.strip()
    r = _pactl("load-module", "module-ladspa-sink", f"sink_name={FILTER}",
               f"sink_master={speakers}", "rate=48000", "channels=1",
               f"plugin={PLUGIN}", "label=noise_suppressor_mono", f"control={CONTROLS}",
               "sink_properties=device.description=IC-7300_RNNoise")
    if r.returncode:
        return "filtre RNNoise introuvable (~/claude/rnnoise)"
    r = _pactl("load-module", "module-loopback", f"source={source}", f"sink={FILTER}",
               "latency_msec=60", "source_dont_move=true",
               f"sink_input_properties=media.name={FILTER}_entree")
    if r.returncode:
        off()
        return "son de la radio introuvable"
    return None


def off():
    # la boucle d'abord, puis le filtre
    for m in sorted(_modules(), key=int, reverse=True):
        _pactl("unload-module", m)


def set_volume(percent):
    """Volume du son épuré (peut dépasser 100 % : gain logiciel)."""
    _pactl("set-sink-volume", FILTER, f"{int(percent)}%")
