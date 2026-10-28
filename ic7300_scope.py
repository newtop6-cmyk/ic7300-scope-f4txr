#!/usr/bin/env python3
"""IC-7300 Scope : S-mètre en bargraph, spectre audio et waterfall.

Le son est lu sur la carte « USB Audio CODEC » de la radio via parec,
le S-mètre, la fréquence et le mode sont lus en CI-V sur le port USB.
"""
import argparse
import datetime
import json
import math
import os
import tempfile
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import types
import wave

import numpy as np
import serial
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from cw_decoder import CwDecoder
from psk31_decoder import Psk31Decoder
from rtty_decoder import RttyDecoder
from ft8_decoder import Ft8Decoder
import ft8_bridge
from ft8_map import Ft8Map
from demo_finger import DemoFinger, SIZES as DEMO_SIZES
from ball_button import BallButton
from rtty_screen import RttyScreen
from wf_france import WaterfallFrance
from screen_rec import ScreenRecorder
from sstv_window import SstvWindow
import sstv as sstv_modes
from sstv_watch import SstvWatch
from ssb_tuner import SsbTuner, D_MAX, D_WIDE
import console
from emission_button import EmissionButton
WSJTX_QSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wsjtx-sombre.qss")
from wifi_bar import WifiBar
from traffic_bar import TrafficBar
from mode_detect import analyse as analyse_mode, analyse_station
from ssb_meter import PlainLed, SsbLed, SsbMeter, SsbMeterSmall
from magic_eye import MagicEye
from pot_knob import PotKnob, ScaleKnob
from vox_pc import VoxMonitor
from mot_vox import MotVox, vox_number
from voix_vox import LEARN_COUNT, VoiceCommands, features
from dictee import Dictee, paste_into, split_send
from traduction import TranslationWindow, Translator
import timbre_qso
from voice_scope import VoiceScope
from power_knob import MODE as KNOB_MODE, NamePlate, PowerKnob, VintageKnob, ScaleBakelite
from band_keys import BandKey
from title_plate import TitlePlate
from rust_style import AmberLed, MilitaryLever, RustPlate
from function_selector import FunctionSelector
from vintage_toggle import ToggleSwitch
from loupe import AltWheel, Loupe
from push_plate import PushPlate
from paddle_clavier import MORSE
from drum_display import DrumClock, DrumDisplay
from nixie_display import NixieDisplay
from function_screen import FunctionScreen, PendingView, SstvLiveView
from tx_galva import RedButton, TxGalva
from vintage_switch import BlueLed, LeverSwitch, SilverPlate
from band_selector import BandSelector
from emergency_button import EmergencyButton
from vintage_meter import SwrMicroGalva, SwrTitle, VintageSMeter, VintagePowerMeter
from whistle import Whistle
from qso_hunter import QsoHunter, find_signals
from panel_frame import PanelFrame
from silver_frame import SilverFrame
from cw_station import CwStation
from egaliseur import EqEngine, EqWindow
import rm_noise
import rnnoise_radio
from cw_hunter import CwHunter
from paddle_clavier import KeyboardPaddle, PaddleKeys

DEFAULT_SOURCE = "alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"   # PC de F4TXR (PulseAudio)
RADIO_SINK = "alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"
DEFAULT_PORT = ("/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_"
                "Controller_IC-7300_03011996-if00-port0")   # IC-7300 de F4TXR

# Flux de l'écoute permanente (~/.config/pipewire/pipewire.conf.d/50-ic7300-loopback.conf)
LOOPBACK_STREAM = "ic7300_loopback_out"
# pactl en français écrit « 0,00 » dans son JSON : forcer les nombres à point
PACTL_ENV = {**os.environ, "LC_ALL": "C"}
# Radio sur un autre PC (--remote) : serveur CAT (cat_server.py) et son
# PipeWire en réseau (pipewire-pulse.conf.d/50-reseau.conf) sur ce PC-là
CAT_TCP_PORT = 7300
PULSE_TCP_PORT = 4713
REMOTE_RX = "ic7300_distant_rx"
REMOTE_TX = "ic7300_distant_tx"
REMOTE_RX_PIPE = "ic7300_distant_rx_pipe"   # contient REMOTE_RX : déchargé avec lui
# sortie « enregistrement » : réception + émission (micro, FT8…) mélangées,
# à choisir dans SimpleScreenRecorder (entrée « Monitor of IC-7300_enregistrement »).
# Jamais déchargée : l'enregistreur garde sa source même si le Scope redémarre.
RECORD_SINK = "ic7300_enregistrement"
REMOTE_FORMAT = ["format=s16le", "rate=16000", "channels=1"]


def music_dir():
    try:
        out = subprocess.run(["xdg-user-dir", "MUSIC"], capture_output=True,
                             text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or os.path.expanduser("~/Music")


RECORD_DIR = os.path.join(music_dir(), "IC-7300")

# réglages de la radio avant que l'appli les change (scope, mode data pendant
# l'émission) ; le fichier n'existe que tant qu'il reste quelque chose à
# remettre, y compris si l'appli a planté
STATE_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME")
                          or os.path.expanduser("~/.config"),
                          "ic7300-scope", "etat-origine.json")
# dernière fréquence et dernier mode utilisés sur chaque bande
BANDS_FILE = os.path.join(os.path.dirname(STATE_FILE), "bandes.json")
MESSAGE_FILE = os.path.join(os.path.dirname(STATE_FILE), "message-cw.txt")
DEFAULT_MESSAGE = "CQ CQ CQ DE F4TXR F4TXR K"
# VOX1, VOX2… : messages vocaux enregistrés au micro. Le poussoir met le message
# en attente ; il part seulement quand on dit « VOX 1 » (« VOX 2 »…) au micro.
VOX_MSG_NUMBERS = (1, 2, 3, 4)  # un poussoir par message (VOX5 : ajouter 5)
VOX_MSG_MAX_S = 120             # enregistrement arrêté tout seul au-delà


def vox_msg_file(n):
    return os.path.join(os.path.dirname(STATE_FILE), f"vox{n}.wav")
# bandes émission de l'IC-7300 : nom, limites (Hz), fréquence et mode de départ
BANDS = [("160m", 1_810_000, 2_000_000, 1_850_000, "LSB"),
         ("80m", 3_500_000, 3_800_000, 3_700_000, "LSB"),
         ("60m", 5_351_500, 5_366_500, 5_360_000, "USB"),
         ("40m", 7_000_000, 7_200_000, 7_100_000, "LSB"),
         ("30m", 10_100_000, 10_150_000, 10_120_000, "CW"),
         ("20m", 14_000_000, 14_350_000, 14_200_000, "USB"),
         ("17m", 18_068_000, 18_168_000, 18_130_000, "USB"),
         ("15m", 21_000_000, 21_450_000, 21_250_000, "USB"),
         ("12m", 24_890_000, 24_990_000, 24_950_000, "USB"),
         ("10m", 28_000_000, 29_700_000, 28_500_000, "USB"),
         ("6m", 50_000_000, 52_000_000, 50_150_000, "USB"),
         ("4m", 70_000_000, 70_500_000, 70_200_000, "USB")]


def band_of(hz):
    for name, low, high, _, _ in BANDS:
        if low <= hz <= high:
            return name
    return None


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def update_state(**values):
    state = load_state()
    state.update(values)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def remove_state(*keys):
    state = load_state()
    for key in keys:
        state.pop(key, None)
    if state:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    else:
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass


ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg")

RATE = 48000
FFT_SIZE = 4096
HOP = 1600                      # 30 spectres par seconde
BIN_HZ = RATE / FFT_SIZE
HISTORY = 300                   # lignes du waterfall (10 s)
RX_FINE_MAX = 30                # barre « RX fin » : pleine échelle au-dessus du bruit

RIG_ADDR = 0x94                 # adresse CI-V par défaut de l'IC-7300
CTRL_ADDR = 0xE0
MODES = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY",
         0x05: "FM", 0x07: "CW-R", 0x08: "RTTY-R"}
DATA_MODES = ("LSB", "USB", "AM", "FM")   # existent aussi en mode data (USB-D…)
MODE_NAMES = ["LSB", "LSB-D", "USB", "USB-D", "AM", "AM-D", "FM", "FM-D",
              "CW", "CW-R", "RTTY", "RTTY-R"]
TX_TIMEOUT = 180                # s : l'émission est coupée au-delà
# repères de l'IC-7300 pour les mesures en émission
PO_POINTS = [(0, 0), (143, 50), (213, 100), (255, 120)]           # % de puissance
SWR_POINTS = [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (255, 6.0)]
COMP_POINTS = [(0, 0.0), (130, 15.0), (241, 30.0), (255, 32.0)]     # dB
ID_POINTS = [(0, 0.0), (97, 10.0), (146, 15.0), (241, 25.0)]      # A
ALC_ZONE = 120                  # au-delà, l'ALC sort de sa zone sur la radio
MIN_FREQ = 30_000               # couverture de réception de l'IC-7300
MAX_FREQ = 74_800_000
# fréquences d'appel SSTV par bande (surveillées sur le scope de la radio)
SSTV_CALLING = {"80m": (3_730_000, "LSB"), "40m": (7_165_000, "LSB"),
                "20m": (14_230_000, "USB"), "17m": (18_160_000, "USB"),
                "15m": (21_340_000, "USB"), "12m": (24_975_000, "USB"),
                "10m": (28_680_000, "USB"), "6m": (50_510_000, "USB")}
SPANS = [2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000]
# zone écoutée autour de la fréquence affichée, en kHz (approximative)
PASSBANDS = {"LSB": (-3.0, -0.1), "USB": (0.1, 3.0), "CW": (-0.25, 0.25),
             "CW-R": (-0.25, 0.25), "RTTY": (-0.25, 0.25),
             "RTTY-R": (-0.25, 0.25), "AM": (-3.0, 3.0), "FM": (-7.5, 7.5)}


# fréquences FT8 (kHz) : en mode data, FT8 près d'elles, PSK31 ailleurs
FT8_KHZ = (1840, 3573, 5357, 7074, 10136, 14074, 18100, 21074, 24915,
           28074, 50313)


def auto_decoder_for(mode, hz):
    """Décodeur à ouvrir tout seul pour ce mode (et cette fréquence)."""
    base = mode.removesuffix("-R")
    if base == "CW":
        return "cw"
    if base == "RTTY":
        return "rtty"
    if mode.endswith("-D"):
        if hz and any(abs(hz - k * 1000) <= 3000 for k in FT8_KHZ):
            return "ft8"
        return "psk31"
    return None


# bouton poussoir gris en relief (bords arrondis) ; enfoncé = creusé
PUSH_3D = (
    "QPushButton { color: #151515; font-weight: bold; border-radius: 7px;"
    " border-style: solid; border-width: 2px 2px 4px 2px;"
    " border-top-color: #ffffff; border-left-color: #e6e6e6;"
    " border-bottom-color: #1e1e1e; border-right-color: #3c3c3c;"
    " padding: 2px 4px;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff,"
    " stop:0.15 #e4e4e4, stop:0.55 #bdbdbd, stop:1 #7e7e7e); }"
    "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    " stop:0 #ffffff, stop:0.15 #ececec, stop:0.55 #c9c9c9, stop:1 #8a8a8a); }"
    "QPushButton:pressed, QPushButton:checked {"
    " border-width: 4px 2px 2px 2px;"
    " border-top-color: #1e1e1e; border-left-color: #2e2e2e;"
    " border-bottom-color: #f0f0f0; border-right-color: #d6d6d6;"
    " padding: 3px 3px 1px 5px;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6e6e6e,"
    " stop:0.4 #a2a2a2, stop:1 #d2d2d2); }"
    # tout bouton en position active (ON) : vert vif, toujours creusé
    "QPushButton:checked { color: white;"
    " border-top-color: #0b3d0b; border-left-color: #145214;"
    " border-bottom-color: #b9ffb9; border-right-color: #8ee88e;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0d6b16,"
    " stop:0.4 #1fae2c, stop:0.8 #3ddc4a, stop:1 #8dff8d); }")
PUSH_3D_MODE = PUSH_3D          # bande / mode choisis : vert aussi

# poussoirs VOX1… : jaunes en relief (reflet en haut, ombre en bas) ; enfoncé = creusé
PUSH_YELLOW_3D = (
    "QPushButton { color: #2a1c00; font-weight: bold; font-size: 9pt; border-radius: 9px;"
    " border-style: solid; border-width: 2px 3px 6px 3px;"
    " border-top-color: #fff6b0; border-left-color: #f5d94a;"
    " border-bottom-color: #6b4e00; border-right-color: #9a7400;"
    " padding: 1px 2px;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fffbe0,"
    " stop:0.12 #ffe95c, stop:0.5 #ffd21a, stop:0.85 #e0a800, stop:1 #b88600); }"
    "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    " stop:0 #ffffff, stop:0.12 #fff07a, stop:0.5 #ffdc3a, stop:0.85 #ebb612,"
    " stop:1 #c49400); }"
    "QPushButton:pressed, QPushButton:checked {"
    " border-width: 6px 3px 2px 3px;"
    " border-top-color: #5a4100; border-left-color: #7a5a00;"
    " border-bottom-color: #fff2a0; border-right-color: #f0d040;"
    " padding: 3px 2px 0px 2px;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #a87c00,"
    " stop:0.4 #e0b000, stop:1 #ffe04a); }")


SWR_GALVA_PX = 44              # hauteur du micro-galva ROS (au-dessus du POWER)
KNOB_POWER_PX = 120            # bouton de puissance (154 avant le micro-galva ROS)
FUNC_SCALE = 0.77              # sélecteur FONCTION (1.0 avant le micro-galva ROS)
BAND_SEL_PX = 200              # commutateur de bandes rotatif (à droite du VFO)
BAND_SEL_GAP = 14
EMERGENCY_PX = 78              # bouton d'arrêt d'urgence (champignon)
EMERGENCY_GAP = 2
SNAP_DELAY_MS = 1500            # bouton immobile depuis 1,5 s : arrondi au kHz
FINE_MAX = 300                  # Hz : l'affinage par la voix reste à ± 300 Hz du kHz rond
PULL_MAX = 1500                 # Hz : rattrapage après appui sur CALAGE AUTO BLU
# Verrou de fréquence : un calage automatique ne peut corriger la fréquence
# choisie que peu après le choix, et jamais loin ; ensuite elle ne bouge plus.
CALAGE_WINDOW_S = 60            # s après le choix de la fréquence
CALAGE_MAX_HZ = 3000            # Hz d'écart maximal avec la fréquence choisie
CALAGE_FINE_HZ = 350            # au-delà de la fenêtre : affinage permis à ± 350 Hz du choix
ECHO_TIMEOUT_S = 3.0            # s : attente de la confirmation de la radio
PULL_SECONDS = 45               # durée du rattrapage


# bouton MARCHE / ARRÊT de la radio, même relief que les autres
POWER_ON = PUSH_3D + (
    "QPushButton { color: white;"
    " border-top-color: #b9ffb9; border-left-color: #8ee88e;"
    " border-bottom-color: #0b3d0b; border-right-color: #145214;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8dff8d,"
    " stop:0.2 #3ddc4a, stop:0.6 #1fae2c, stop:1 #0d6b16); }"
    "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    " stop:0 #a6ffa6, stop:0.2 #4ee85a, stop:0.6 #26bf34, stop:1 #10781a); }")
POWER_OFF = PUSH_3D + (
    "QPushButton { color: white;"
    " border-top-color: #ffb3b3; border-left-color: #e88e8e;"
    " border-bottom-color: #3d0b0b; border-right-color: #521414;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ff8d8d,"
    " stop:0.2 #e53935, stop:0.6 #b71c1c, stop:1 #6b0d0d); }"
    "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    " stop:0 #ffa6a6, stop:0.2 #ef4b47, stop:0.6 #c62828, stop:1 #7a1010); }")


# CHERCHER QSO FR actif, phase sombre du clignotement
HUNT_DARK = ("QPushButton:checked { color: #b9ffb9; background: qlineargradient("
             "x1:0, y1:0, x2:0, y2:1, stop:0 #062e09, stop:0.5 #0b4a10, stop:1 #155e1a); }")
# bouton RESTER ICI, phase sombre du clignotement
STAY_DARK = PUSH_3D + (
    "QPushButton { color: #ffb0b0;"
    " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7a2a2a,"
    " stop:0.5 #4a0e0e, stop:1 #2a0606); }")


def usual_sideband(hz):
    """Usage radioamateur : LSB sous 10 MHz, USB au-dessus et sur 60 m."""
    if hz is None:
        return None
    if 5_250_000 <= hz <= 5_450_000 or hz >= 10_000_000:
        return "USB"
    return "LSB"


def base_mode(name):
    """Le mode sans le mode data : USB-D → USB."""
    return name.removesuffix("-D")


def mode_name(code, data):
    name = MODES.get(code, f"mode {code:02X}")
    return name + "-D" if data and name in DATA_MODES else name
STEPS = [("10 Hz", 10), ("100 Hz", 100), ("1 kHz", 1000), ("5 kHz", 5000),
         ("10 kHz", 10_000), ("100 kHz", 100_000)]

# Échelle du S-mètre Icom : 0 = S0, 120 = S9, 241 = S9+60 dB
S9 = 120
S9_PLUS_60 = 241


def bcd_le(data):
    """BCD poids faible en premier (fréquence CI-V)."""
    value = 0
    for i, b in enumerate(data):
        value += ((b >> 4) * 10 + (b & 0x0F)) * 100 ** i
    return value


def to_bcd_le(value, size=5):
    return bytes((value // 10 ** (2 * i + 1) % 10) << 4
                 | value // 10 ** (2 * i) % 10 for i in range(size))


def bcd_be(data):
    """BCD poids fort en premier (niveaux CI-V)."""
    value = 0
    for b in data:
        value = value * 100 + (b >> 4) * 10 + (b & 0x0F)
    return value


def s_meter_raw(db_over_s9):
    return S9 + (S9_PLUS_60 - S9) * db_over_s9 / 60


def s_meter_text(raw):
    if raw <= S9:
        return f"S{round(raw * 9 / S9)}"
    return f"S9+{round((raw - S9) * 60 / (S9_PLUS_60 - S9))}"


def format_frequency(hz):
    return f"{hz // 1_000_000}.{(hz // 1000) % 1000:03d}.{hz % 1000:03d}"


def find_loopback_stream():
    """Flux d'écoute radio → PC : (index, volume en %, muet) ou None."""
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"],
                             capture_output=True, text=True, timeout=2,
                             env=PACTL_ENV).stdout
        streams = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    for stream in streams:
        if stream["properties"].get("node.name") == LOOPBACK_STREAM:
            channel = next(iter(stream["volume"].values()))
            volume = int(channel["value_percent"].rstrip("%"))
            return stream["index"], volume, stream["mute"]
    return None


def remote_audio(host):
    """Crée ici l'entrée et la sortie son de la radio branchée sur `host`,
    plus l'écoute sur la sortie par défaut. Renvoie les modules à décharger."""
    unload_remote_audio(None)       # restes d'une session plantée
    # relais son orphelins d'une session précédente (ils joueraient la radio
    # directement dans le casque, sans tenir compte du MUET)
    for pattern in ("ic7300-scope/rx_relay.py", "client-name=IC-7300 emission",
                    "stream-name=IC-7300 reception"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    server = f"server=tcp:{host}:{PULSE_TCP_PORT}"
    commands = [
        # son allégé pour la 4G : mono 16 kHz (≈ 32 Ko/s au lieu de ≈ 190)
        # réception : sortie locale alimentée par rx_relay.py (SSH, retard borné),
        # vue comme une entrée « ic7300_distant_rx » ; l'ancien tunnel PipeWire
        # se figeait et accumulait des secondes de retard
        ["module-null-sink", f"sink_name={REMOTE_RX_PIPE}", *REMOTE_FORMAT,
         "sink_properties=device.description=IC-7300_reception"],
        ["module-remap-source", f"master={REMOTE_RX_PIPE}.monitor",
         f"source_name={REMOTE_RX}", "channels=1",
         "source_properties=device.description=IC-7300_radio"],
        # émission : sortie locale « muette », son envoyé au Pi par SSH (plus bas) ;
        # le tunnel PipeWire de ce PC hachait le son (trous de 100 ms)
        ["module-null-sink", f"sink_name={REMOTE_TX}", *REMOTE_FORMAT,
         "sink_properties=device.description=IC-7300_emission"],
        ["module-loopback", f"source={REMOTE_RX}", "latency_msec=60",
         "source_dont_move=true", f"sink_input_properties=node.name={LOOPBACK_STREAM}"],
    ]
    modules = []
    for command in commands:
        try:
            out = subprocess.run(["pactl", "load-module", *command],
                                 capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            out = None
        if out is None or out.returncode != 0:
            unload_remote_audio(modules)
            error = out.stderr.strip() if out else "pas de réponse"
            raise RuntimeError(f"{command[0]} : {error or 'échec'}")
        modules.append(out.stdout.strip())
    modules += record_mix()
    # son d'émission vers le Pi : flux continu par SSH (silence hors émission),
    # lu par pw-play sur la carte son de la radio
    global _TX_KEEPALIVE
    _TX_KEEPALIVE = subprocess.Popen(
        ["bash", "-c",
         f"parec --device={REMOTE_TX}.monitor --raw --format=s16le --rate=16000 "
         f"--channels=1 --latency-msec=20 --client-name='IC-7300 emission' | "
         f"ssh -o BatchMode=yes -o ConnectTimeout=5 -o ServerAliveInterval=5 "
         f"marco@{host} 'exec pw-play --raw --target {RADIO_SINK} --rate 16000 "
         f"--channels 1 --format s16 --latency 100ms -'"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    global _RX_RELAY
    _RX_RELAY = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "rx_relay.py"), host, DEFAULT_SOURCE, REMOTE_RX_PIPE],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    return modules


_TX_KEEPALIVE = None
_RX_RELAY = None


def record_mix():
    """Relie réception et émission à la sortie d'enregistrement (créée si absente).
    Le micro n'y arrive qu'en émission : sa liaison vers la radio est muette sinon."""
    sinks = subprocess.run(["pactl", "list", "short", "sinks"],
                           capture_output=True, text=True).stdout
    if not any(line.split("\t")[1:2] == [RECORD_SINK] for line in sinks.splitlines()):
        subprocess.run(["pactl", "load-module", "module-null-sink",
                        f"sink_name={RECORD_SINK}", "rate=48000", "channels=2",
                        "sink_properties=device.description=IC-7300_enregistrement"],
                       capture_output=True)
    modules = []
    for name, source in (("ic7300_enreg_rx", f"{REMOTE_RX_PIPE}.monitor"),
                         ("ic7300_enreg_tx", f"{REMOTE_TX}.monitor")):
        out = subprocess.run(
            ["pactl", "load-module", "module-loopback", f"source={source}",
             f"sink={RECORD_SINK}", "latency_msec=60",
             "source_dont_move=true", "sink_dont_move=true",
             f"sink_input_properties='node.name={name} media.role=ic7300rec'"],
            capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            modules.append(out.stdout.strip())
    return modules


def remote_audio_present():
    """Vrai si l'entrée ET la sortie son de la radio distante existent encore ici."""
    try:
        sources = subprocess.run(["pactl", "list", "short", "sources"],
                                 capture_output=True, text=True, timeout=5).stdout
        sinks = subprocess.run(["pactl", "list", "short", "sinks"],
                               capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True                 # pactl muet : ne rien casser
    rx = any(line.split("\t")[1:2] == [REMOTE_RX] for line in sources.splitlines())
    tx = any(line.split("\t")[1:2] == [REMOTE_TX] for line in sinks.splitlines())
    sending = _TX_KEEPALIVE is not None and _TX_KEEPALIVE.poll() is None
    receiving = _RX_RELAY is not None and _RX_RELAY.poll() is None
    return rx and tx and sending and receiving


RX_MAX_DELAY_MS = 600       # au-delà, la liaison de réception est recréée


def remote_rx_delay_ms():
    """Retard annoncé par la liaison de réception (ms), ou None."""
    try:
        out = subprocess.run(["pactl", "list", "sources"], capture_output=True,
                             text=True, timeout=3, env=PACTL_ENV).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    block = out.split(f"Name: {REMOTE_RX}")
    if len(block) < 2:
        return None
    for line in block[1].splitlines()[:40]:
        line = line.strip()
        if line.startswith("Latency:"):
            try:
                return int(line.split()[1]) / 1000
            except (IndexError, ValueError):
                return None
    return None


def reload_remote_rx(host):
    """Recrée seulement la réception (tunnel + écoute) : vide le retard accumulé."""
    out = subprocess.run(["pactl", "list", "modules", "short"],
                         capture_output=True, text=True).stdout
    for line in reversed(out.splitlines()):
        if REMOTE_RX in line:
            subprocess.run(["pactl", "unload-module", line.split()[0]], capture_output=True)
    server = f"server=tcp:{host}:{PULSE_TCP_PORT}"
    for command in (
            ["module-tunnel-source", server, f"source={DEFAULT_SOURCE}",
             f"source_name={REMOTE_RX}", *REMOTE_FORMAT],
            ["module-loopback", f"source={REMOTE_RX}", "latency_msec=60",
             "source_dont_move=true", f"sink_input_properties=node.name={LOOPBACK_STREAM}"]):
        subprocess.run(["pactl", "load-module", *command], capture_output=True, timeout=10)


def watch_remote_audio(host, reader, stop):
    """Recrée le son de la radio distante quand il a disparu (coupure réseau,
    4G...) : PulseAudio supprime alors le tunnel et bascule parec sur le micro.
    Surveille aussi le retard de la réception : le tunnel se fige parfois
    (après une émission) et accumule plusieurs secondes de retard."""
    tick = 0
    late = 0
    while not stop.wait(1):
        tick += 1
        delay = remote_rx_delay_ms()
        delay = None                    # relais SSH : retard borné par rx_relay.py
        late = late + 1 if delay is not None and delay > RX_MAX_DELAY_MS else 0
        if late >= 2:
            late = 0
            reload_remote_rx(host)
            proc = reader.proc
            if proc:
                proc.terminate()        # parec repart sur la nouvelle entrée
            continue
        if tick % 5:
            continue
        if remote_audio_present():
            continue
        try:
            remote_audio(host)
        except RuntimeError as e:
            reader.failed.emit(f"Son du Pi coupé, nouvel essai… ({e})")
            continue
        reader.failed.emit("Son du Pi rétabli")
        proc = reader.proc
        if proc:
            proc.terminate()        # parec repart sur la bonne entrée


def unload_remote_audio(modules):
    """Décharge les modules donnés, ou tous ceux de --remote (None)."""
    global _TX_KEEPALIVE, _RX_RELAY
    for proc in (_TX_KEEPALIVE, _RX_RELAY):
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGTERM)     # avec ses ssh/pacat/parec
            except OSError:
                pass
    _TX_KEEPALIVE = _RX_RELAY = None
    if modules is None:
        out = subprocess.run(["pactl", "list", "modules", "short"],
                             capture_output=True, text=True).stdout
        modules = [line.split()[0] for line in out.splitlines()
                   if REMOTE_RX in line or REMOTE_TX in line]
    for module in reversed(modules):
        subprocess.run(["pactl", "unload-module", module], capture_output=True)


def mic_gain_now():
    """Gain actuel du micro par défaut du PC, en % (100 si inconnu)."""
    out = subprocess.run(["pactl", "get-source-volume", "@DEFAULT_SOURCE@"],
                         capture_output=True, text=True, env=PACTL_ENV).stdout
    m = re.search(r"(\d+)%", out)
    return int(m.group(1)) if m else 100


def list_microphones(exclude):
    """Entrées son du PC (nom, description), sans les retours et sans la radio."""
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", "sources"],
                             capture_output=True, text=True, timeout=2,
                             env=PACTL_ENV).stdout
        sources = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    # « description » vaut « (null) » quand elle contient des accents
    def label(src):
        desc = src["properties"].get("device.description")
        if desc and desc != "(null)":
            return desc
        if src["name"].startswith("alsa_input.pci"):
            return "micro du PC"
        return src["properties"].get("alsa.card_name") or src["name"]
    return [(src["name"], label(src))
            for src in sources
            if not src["name"].endswith(".monitor") and src["name"] != exclude]


def sink_volume(sink):
    try:
        out = subprocess.run(["pactl", "get-sink-volume", sink],
                             capture_output=True, text=True, timeout=2).stdout
        return int(out.split("%")[0].split()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def piecewise(raw, points):
    """Conversion d'un niveau CI-V (0 à 255) par interpolation entre repères."""
    xs, ys = zip(*points)
    return float(np.interp(raw, xs, ys))


def parse_frequency(text):
    """« 14.074 » ou « 14,074 » → MHz, « 7074 » → kHz, « 7074000 » → Hz."""
    text = text.strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    if "." in text or value < 100:
        return round(value * 1_000_000)
    if value < 100_000:
        return round(value * 1000)
    return round(value)


class AudioReader(QtCore.QThread):
    """Lit le son de la radio et calcule un spectre en dBFS."""
    spectrum = QtCore.pyqtSignal(object, float)
    failed = QtCore.pyqtSignal(str)
    decoded = QtCore.pyqtSignal(str)
    decoder_state = QtCore.pyqtSignal(str, float, bool, bool)  # infos, note, signal, actif
    ssb_state = QtCore.pyqtSignal(object, str, bool)   # écart estimé, état, calé
    ssb_correct = QtCore.pyqtSignal(str, float)        # "shift"/"flip", Hz
    sstv_seen = QtCore.pyqtSignal(object)              # (mode, Hz des tops) ou None
    cw_env = QtCore.pyqtSignal(object)                 # réception CW : enveloppe (5 ms)

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.proc = None
        self._running = True
        self.decoders = {"cw": CwDecoder(RATE), "psk31": Psk31Decoder(RATE),
                         "rtty": RttyDecoder(RATE), "ft8": Ft8Decoder(RATE)}
        self.decoder = None             # décodeur choisi, ou None
        self.sstv = None                # décodeur SSTV quand sa fenêtre est ouverte
        self.sstv_watch = SstvWatch(RATE)  # surveillance SSTV permanente (légère)
        self.cw_env_pitch = None        # note CW suivie pour l'oscilloscope (Hz) ou None
        self.ssb_tuner = SsbTuner(RATE)
        self.ssb = None                 # = ssb_tuner quand le calage BLU est actif
        self._record_lock = threading.Lock()
        self._record = None
        self.recorded_frames = 0
        self.capture = None             # liste : copie du son (recherche de QSO)

    def run(self):
        # le flux peut tomber (son du Pi coupé par le réseau) : on relance parec
        while self._running:
            if self._read_once() is False:
                return
            if self._running:
                time.sleep(2)

    def _read_once(self):
        cmd = ["parec", "--raw", f"--device={self.source}", "--format=s16le",
               f"--rate={RATE}", "--channels=1", "--latency-msec=20",
               "--client-name=IC-7300 Scope"]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
        except FileNotFoundError:
            self.failed.emit("parec introuvable (paquet pulseaudio-utils)")
            return False
        window = np.hanning(FFT_SIZE).astype(np.float32)
        norm = window.sum() / 2
        buf = np.zeros(FFT_SIZE, np.float32)
        nbytes = HOP * 2
        while self._running:
            data = self.proc.stdout.read(nbytes)
            if len(data) < nbytes:
                if self._running:
                    err = self.proc.stderr.read().decode(errors="replace").strip()
                    self.failed.emit(f"Flux audio interrompu {err}".strip())
                break
            with self._record_lock:
                if self._record:
                    self._record.writeframes(data)
                    self.recorded_frames += HOP
            x = np.frombuffer(data, "<i2").astype(np.float32) / 32768
            buf = np.roll(buf, -HOP)
            buf[-HOP:] = x
            mag = np.abs(np.fft.rfft(buf * window)) / norm
            db = 20 * np.log10(mag + 1e-10)
            rms = 20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-10)
            self.spectrum.emit(db.astype(np.float32), float(rms))
            capture = self.capture
            if capture is not None:
                capture.append(x.copy())
            sstv = self.sstv
            if sstv:
                sstv.feed(x)
            if self.sstv_watch.feed(x):
                self.sstv_seen.emit(self.sstv_watch.result)
            pitch = self.cw_env_pitch
            if pitch:                   # enveloppe de la note CW, une valeur / 5 ms
                n = len(x) // 240
                seg = x[:n * 240].reshape(n, 240)
                osc = np.exp(-2j * np.pi * pitch * np.arange(240) / RATE)
                self.cw_env.emit(np.abs(seg @ osc) / 240)
            ssb = self.ssb
            if ssb:
                frames = ssb.frames
                action = ssb.feed(x)
                if action is not None:
                    self.ssb_correct.emit(action[0], float(action[1]))
                elif ssb.frames != frames or ssb.hold > 0:
                    estimate = None if ssb.estimate is None else float(ssb.estimate)
                    self.ssb_state.emit(estimate, ssb.status, bool(ssb.locked))
            decoder = self.decoder
            if decoder:
                decoder.track_pitch(db, BIN_HZ)
                text = decoder.feed(x)
                if text:
                    self.decoded.emit(text)
                # types Python purs : un numpy.bool fait planter emit() et
                # arrête ce fil, donc tous les décodeurs
                self.decoder_state.emit(decoder.status(), float(decoder.pitch or 0.0),
                                        bool(decoder.has_signal), bool(decoder.key_down))

    def start_recording(self, path):
        """Enregistre le son de la radio tel quel : WAV mono 16 bits."""
        record = wave.open(path, "wb")
        record.setnchannels(1)
        record.setsampwidth(2)
        record.setframerate(RATE)
        with self._record_lock:
            self._record = record
            self.recorded_frames = 0

    def stop_recording(self):
        with self._record_lock:
            record, self._record = self._record, None
        if record:
            record.close()

    def stop(self):
        self.stop_recording()
        self.decoders["ft8"].close()
        self._running = False
        if self.proc:
            self.proc.terminate()
        self.wait(2000)


class CivReader(QtCore.QThread):
    """Interroge la radio en CI-V : S-mètre, fréquence et mode."""
    meter = QtCore.pyqtSignal(int)
    frequency = QtCore.pyqtSignal(int)
    mode = QtCore.pyqtSignal(str)
    other_frequency = QtCore.pyqtSignal(int)     # VFO non sélectionné
    other_mode = QtCore.pyqtSignal(str)
    af_gain = QtCore.pyqtSignal(int)            # volume de la radio, 0 à 255
    tuner = QtCore.pyqtSignal(int)              # boîte d'accord : 0 arrêt, 1 marche, 2 accord
    power = QtCore.pyqtSignal(int)              # puissance réglée, 0 à 255
    transmitting = QtCore.pyqtSignal(bool)      # la radio émet
    tx_meters = QtCore.pyqtSignal(int, int, int)  # puissance, ROS, ALC (0 à 255)
    po_meter = QtCore.pyqtSignal(int)              # puissance seule (0 à 255)
    usb_mod = QtCore.pyqtSignal(int)            # menu USB MOD Level, 0 à 255
    comp = QtCore.pyqtSignal(int)               # compression, 0 à 255
    drain = QtCore.pyqtSignal(int)              # courant de l'ampli (Id), 0 à 255
    scope = QtCore.pyqtSignal(object, int, int) # balayage, bords bas/haut (Hz)
    span = QtCore.pyqtSignal(int)               # demi-largeur du scope (Hz)
    cw_pitch = QtCore.pyqtSignal(int)           # note CW réglée dans la radio (Hz)
    vox = QtCore.pyqtSignal(bool)               # VOX de la radio en marche
    vox_gain = QtCore.pyqtSignal(int)           # gain VOX, 0 à 255
    comp_on = QtCore.pyqtSignal(bool)           # compresseur de modulation en marche
    comp_level = QtCore.pyqtSignal(int)         # niveau du compresseur, 0 à 255
    status = QtCore.pyqtSignal(str)
    alive = QtCore.pyqtSignal(bool)             # la radio répond (allumée)

    def __init__(self, port, baud):
        super().__init__()
        self.port = port
        self.baud = baud
        self._running = True
        self._pending_freq = None
        self._pending_mode = None
        self._pending_vox_gain = None
        self._pending_comp_level = None
        self._vox_used = False          # VOX allumé par Scope : coupé à la fermeture
        self._pending_af = None
        self._commands = queue.Queue()
        self._tuner = None
        self._filter = 0x01                 # FIL1 tant que la radio n'a rien dit
        self._pending_span = None
        self._pending_power = None
        self._pending_onoff = None      # True allumer, False éteindre
        self._last_reply = 0.0          # heure de la dernière trame de la radio
        self._alive = None
        self._pending_usb_mod = None
        self._pending_ptt = None
        self._ptt = False               # émission demandée par l'appli
        self._tx = False                # la radio dit qu'elle émet
        self._data_state = None         # (data, filtre) lu sur la radio
        self._mode_code = None          # dernier mode lu (code CI-V)
        self._data_off_mod = None       # menu DATA OFF MOD lu sur la radio
        self._tx_data = False           # émission en mode data (numérique)
        self._tx_meters = [0, 0, 0]
        self._wave = None
        self._wave_edges = None
        # réglages du scope de la radio, remis à la fermeture
        self._scope_mode = None
        self._scope_speed = None

    def run(self):
        while self._running:
            try:
                # chemin du port, ou socket://hôte:port (cat_server.py)
                with serial.serial_for_url(self.port, self.baud, timeout=0.05,
                                           exclusive=True) as ser:
                    self.status.emit("CAT connecté")
                    self._buf = bytearray()
                    self._recover(ser)
                    self._scope_setup(ser)
                    self._poll(ser)
                    self._release(ser)
                    if self._vox_used:          # sécurité : pas de VOX laissé en marche
                        self._command(ser, 0x16, 0x46, 0x00)
                    self._scope_restore(ser)
            except (serial.SerialException, OSError) as e:
                self.status.emit(f"CAT indisponible : {e}")
                for _ in range(20):
                    if not self._running:
                        return
                    time.sleep(0.1)

    def _send(self, ser, *payload):
        ser.write(bytes([0xFE, 0xFE, RIG_ADDR, CTRL_ADDR, *payload, 0xFD]))

    def set_frequency(self, hz):
        """Appelable depuis l'interface : seule la dernière valeur est envoyée."""
        self._pending_freq = hz

    def set_mode(self, name):
        self._pending_mode = name

    def set_vox(self, on):
        if on:
            self._vox_used = True
        self._commands.put((0x16, 0x46, 0x01 if on else 0x00))

    def set_vox_gain(self, level):
        self._pending_vox_gain = level

    def set_comp(self, on):
        """Compresseur de modulation (SSB) de la radio : marche / arrêt."""
        self._commands.put((0x16, 0x44, 0x01 if on else 0x00))

    def set_comp_level(self, level):
        self._pending_comp_level = level

    def set_af_gain(self, level):
        self._pending_af = level

    def set_span(self, hz):
        self._pending_span = hz

    def vfo_operation(self, code):
        """0x00 VFO A, 0x01 VFO B, 0xA0 A=B, 0xB0 échange A/B."""
        self._commands.put((0x07, code))

    def tune(self):
        """Lance l'accord de la boîte d'accord interne (la radio émet)."""
        self._commands.put((0x1C, 0x01, 0x02))
        self._tune_watch_until = time.monotonic() + 3.5   # suivi serré dès l'appui

    def set_atu(self, on):
        self._commands.put((0x1C, 0x01, 0x01 if on else 0x00))

    def set_power(self, level):
        self._pending_power = level

    def stop_cw(self):
        """Arrête tout de suite le texte CW en cours d'émission par la radio."""
        self._commands.put((0x17, 0xFF))

    def send_cw(self, text):
        """La radio émet ce texte en CW (30 caractères au plus par commande)."""
        data = text.upper().encode("ascii", "ignore")[:30]
        if data:
            self._commands.put((0x17, *data))

    def set_break_in(self, on):
        """BK-IN de la radio : semi break-in (True) ou coupé (False)."""
        self._commands.put((0x16, 0x47, 0x01 if on else 0x00))

    def set_key_speed(self, wpm):
        """Vitesse du manipulateur de la radio (6 à 48 mots/min)."""
        v = round((min(max(wpm, 6), 48) - 6) * 255 / 42)
        self._commands.put((0x14, 0x0C, v // 100, (v // 10 % 10) << 4 | v % 10))

    def set_radio_power(self, on):
        """Allume (True) ou éteint (False) la radio."""
        self._pending_onoff = on

    def _power_switch(self, ser, on):
        if on:
            # réveil : une suite de FE (environ 150 à 115200 bauds), puis la commande
            ser.write(bytes([0xFE] * 150 + [0xFE, 0xFE, RIG_ADDR, CTRL_ADDR,
                                            0x18, 0x01, 0xFD]))
            self.status.emit("Allumage envoyé, patiente quelques secondes…")
        else:
            self._release(ser)
            self._scope_restore(ser)
            self._send(ser, 0x18, 0x00)
            self._last_reply = 0.0
            self.status.emit("Extinction envoyée")

    def _check_alive(self, ser):
        # à distance (réseau, 4G) les réponses peuvent tarder : plus de marge,
        # sinon le bouton passe à OFF alors que la radio est allumée
        limit = 12 if str(self.port).startswith("socket://") else 4
        alive = time.monotonic() - self._last_reply < limit
        if alive != self._alive:
            if alive and self._alive is False:
                self._scope_setup(ser)      # la radio vient de s'allumer
                self._last_wave = time.monotonic()
            self._alive = alive
            self.alive.emit(alive)
        # radio allumée mais plus de données du scope (après une émission…) :
        # on relance l'envoi du scope
        now = time.monotonic()
        if alive and now - getattr(self, "_last_wave", now) > 4 \
                and now - getattr(self, "_last_scope_setup", 0) > 6:
            self._last_scope_setup = now
            self._txlog("scope muet depuis 4 s : relance")
            self._scope_setup(ser)

    def set_usb_mod(self, level):
        """Gain de l'entrée USB à l'émission (menu USB MOD Level), 0 à 255."""
        self._pending_usb_mod = level

    def set_ptt(self, on, data=False):
        """Émission (True) ou réception (False).

        data=True passe la radio en mode data (SSTV…) ; sinon le mode reste
        tel quel (phonie) et l'entrée USB est prise hors mode data."""
        if on:
            self._tx_data = data
        self._pending_ptt = on

    def _key(self, ser):
        if self._tx_data:
            self._key_data(ser)
        else:
            self._key_voice(ser)
        self._buf = bytearray()             # vieilles réponses « réception » jetées
        self._command(ser, 0x1C, 0x00, 0x01)
        self._ptt = True
        self._keyed_at = time.monotonic()

    def _key_voice(self, ser):
        # hors mode data, la radio prend le son sur l'entrée du menu
        # DATA OFF MOD (MIC,ACC ici) : on la met sur USB le temps de l'émission
        self._data_off_mod = None
        self._transact(ser, (0x1A, 0x05, 0x00, 0x66), (0x1A,))
        saved = self._data_off_mod
        if saved == 0x03 and load_state().get("tx_menu") is None:
            # déjà sur USB sans trace d'une émission en cours : resté bloqué
            # (appli coupée en pleine émission) → on reviendra à MIC,ACC
            saved = 0x02
        if saved is not None:
            update_state(tx_menu=saved)
            if saved != 0x03:
                self._command(ser, 0x1A, 0x05, 0x00, 0x66, 0x03)

    def _key_data(self, ser):
        # en mode data, le son vient de l'USB (réglage DATA MOD = USB) :
        # on y passe le temps de l'émission et on note l'état d'avant
        self._data_state = None
        self._transact(ser, (0x1A, 0x06), (0x1A,))
        saved = self._data_state or (0x00, 0x00)
        update_state(tx_data=list(saved))
        if saved[0] == 0x00:
            self._command(ser, 0x1A, 0x06, 0x01, self._filter)

    def _release(self, ser):
        """Repasse en réception et remet les réglages d'avant l'émission."""
        if self._ptt:
            self._command(ser, 0x1C, 0x00, 0x00)
            self._ptt = False
        state = load_state()
        saved = state.get("tx_data")
        if saved:
            if saved[0] == 0x00:
                self._command(ser, 0x1A, 0x06, *saved)
            remove_state("tx_data")
        if state.get("tx_menu") is not None:
            self._command(ser, 0x1A, 0x05, 0x00, 0x66, state["tx_menu"])
            remove_state("tx_menu")

    def _recover(self, ser):
        """Si l'appli a planté en émission, on coupe et on remet le mode data."""
        state = load_state()
        if state.get("tx_data") or state.get("tx_menu") is not None:
            self._command(ser, 0x1C, 0x00, 0x00)
            self._release(ser)
            self.status.emit("Émission coupée : l'appli s'était arrêtée en émission")

    def _poll(self, ser):
        # La radio ignore une commande reçue pendant qu'elle répond à la
        # précédente : on attend chaque réponse avant d'envoyer la suivante.
        n = 0
        while self._running:
            changed = False
            onoff, self._pending_onoff = self._pending_onoff, None
            if onoff is not None:
                self._power_switch(ser, onoff)
                n = 1                       # pas de longue série de questions tout de suite
            ptt, self._pending_ptt = self._pending_ptt, None
            if ptt is True and not self._ptt:
                self._key(ser)
                n = 1                       # pas de relecture des réglages : mesures tout de suite
            elif ptt is False:
                self._release(ser)
                n = 1                       # S-mètre tout de suite au retour en réception
            hz, self._pending_freq = self._pending_freq, None
            if hz is not None:
                self._command(ser, 0x05, *to_bcd_le(hz))
                changed = True
            mode, self._pending_mode = self._pending_mode, None
            if mode is not None:
                base = base_mode(mode)
                code = next(c for c, m in MODES.items() if m == base)
                # sans le filtre, la radio repasse sur son filtre par défaut
                self._command(ser, 0x06, code, self._filter)
                if base in DATA_MODES:
                    data = 0x01 if mode.endswith("-D") else 0x00
                    self._command(ser, 0x1A, 0x06, data,
                                  self._filter if data else 0x00)
                self._transact(ser, (0x1A, 0x06), (0x1A,))
                changed = True
            while not self._commands.empty():
                self._command(ser, *self._commands.get())
                changed = True
            level, self._pending_af = self._pending_af, None
            if level is not None:
                self._command(ser, 0x14, 0x01, level // 100,
                              (level // 10 % 10) << 4 | level % 10)
            power, self._pending_power = self._pending_power, None
            if power is not None:
                self._command(ser, 0x14, 0x0A, power // 100,
                              (power // 10 % 10) << 4 | power % 10)
            level, self._pending_usb_mod = self._pending_usb_mod, None
            if level is not None:
                self._command(ser, 0x1A, 0x05, 0x00, 0x65, level // 100,
                              (level // 10 % 10) << 4 | level % 10)
            level, self._pending_comp_level = self._pending_comp_level, None
            if level is not None:
                self._command(ser, 0x14, 0x0E, level // 100,
                              (level // 10 % 10) << 4 | level % 10)
            level, self._pending_vox_gain = self._pending_vox_gain, None
            if level is not None:
                self._command(ser, 0x14, 0x16, level // 100,
                              (level // 10 % 10) << 4 | level % 10)
            span, self._pending_span = self._pending_span, None
            if span is not None:
                self._command(ser, 0x27, 0x15, 0x00, *to_bcd_le(span))
                self._transact(ser, (0x27, 0x15, 0x00), (0x27,))
            if changed:
                n = 0
            if self._ptt or self._tx:       # en émission : puissance, ROS, ALC
                # Po et ALC à chaque tour, le reste à tour de rôle : barres plus vives
                others = [(0x1C, 0x00), (0x15, 0x12), (0x15, 0x14), (0x15, 0x16)]
                queries = [(0x15, 0x11)]            # Po à chaque tour
                # ALC et COMP en alternance (galva), le reste de temps en temps
                queries.append((0x15, 0x13) if n % 2 == 0 else (0x15, 0x14))
                if n % 4 == 1:
                    queries.append((0x15, 0x12))    # ROS souvent : barre sous le S-mètre
                if n % 8 == 3:
                    queries.append(others[n // 8 % 4])
                if n % 30 == 0:
                    queries += [(0x03,), (0x04,), (0x1A, 0x06)]
            elif n % 10 == 0:
                queries = [(0x03,), (0x04,), (0x1A, 0x06), (0x25, 0x01), (0x26, 0x01),
                           (0x14, 0x01), (0x14, 0x0A), (0x1C, 0x00),
                           (0x1C, 0x01), (0x1A, 0x05, 0x00, 0x65), (0x15, 0x02),
                           (0x14, 0x09), (0x16, 0x46), (0x14, 0x16),
                           (0x16, 0x44), (0x14, 0x0E)]
            elif self._tuner == 0x02 or time.monotonic() < getattr(
                    self, "_tune_watch_until", 0):  # accord en cours : on suit de près
                queries = [(0x1C, 0x00), (0x1C, 0x01), (0x15, 0x11), (0x15, 0x12)]
            elif self._mode_code in (0x03, 0x07):   # CW : suivre la manipulation
                queries = [(0x15, 0x02), (0x15, 0x11)]
            else:
                queries = [(0x15, 0x02)]
                if n % 3 == 0:              # la radio émet-elle d'elle-même ? (TUNE, PTT, VOX)
                    queries.append((0x1C, 0x00))
            n += 1
            for query in queries:
                if not self._running:
                    break               # fermeture : on remet la radio sans attendre
                if self._pending_ptt is not None:
                    break               # passage émission/réception : tout de suite
                self._transact(ser, query, (query[0],))
            self._check_alive(ser)
            time.sleep(0.005 if (self._ptt or self._tx) else 0.05)

    def _scope_setup(self, ser):
        """Scope de la radio centré sur la fréquence, données envoyées en CI-V."""
        if self._scope_mode is None:
            saved = load_state().get("scope")
            if saved:                   # la dernière session n'a pas pu les remettre
                self._scope_mode, self._scope_speed = saved
            else:
                self._transact(ser, (0x27, 0x14, 0x00), (0x27,))
                self._transact(ser, (0x27, 0x1A, 0x00), (0x27,))
                if self._scope_mode is not None and self._scope_speed is not None:
                    update_state(scope=[self._scope_mode, self._scope_speed])
        self._command(ser, 0x27, 0x14, 0x00, 0x00)      # mode centré
        self._command(ser, 0x27, 0x1A, 0x00, 0x00)      # balayage rapide
        self._command(ser, 0x27, 0x10, 0x01)            # spectre de la radio allumé
        self._command(ser, 0x27, 0x11, 0x01)            # données vers le CI-V
        self._transact(ser, (0x27, 0x15, 0x00), (0x27,))

    def _scope_restore(self, ser):
        self._command(ser, 0x27, 0x11, 0x00)
        if self._scope_mode is not None:
            self._command(ser, 0x27, 0x14, 0x00, self._scope_mode)
        if self._scope_speed is not None:
            self._command(ser, 0x27, 0x1A, 0x00, self._scope_speed)
        remove_state("scope")

    def _command(self, ser, *payload):
        reply = self._transact(ser, payload, (0xFB, 0xFA))
        if reply != 0xFB:
            self.status.emit("La radio a refusé la commande")

    def _txlog(self, text):
        """Journal de diagnostic des mesures d'émission (tx-debug.log)."""
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "tx-debug.log"), "a") as f:
                f.write(f"{datetime.datetime.now():%H:%M:%S.%f} {text}\n")
        except OSError:
            pass

    def _transact(self, ser, payload, expected):
        """Envoie une trame et attend une réponse parmi `expected`."""
        return self._transact_raw(ser, payload, expected)

    def _transact_raw(self, ser, payload, expected):
        self._send(ser, *payload)
        # par le réseau (--remote, 4G) la réponse met jusqu'à ~0,5 s à revenir
        wait = 1.0 if str(self.port).startswith("socket://") else 0.15
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            self._buf += ser.read(64)
            while 0xFD in self._buf:
                end = self._buf.index(0xFD)
                cmd = self._handle(bytes(self._buf[:end]))
                del self._buf[:end + 1]
                if cmd in expected:
                    return cmd
        return None

    def _emit_mode(self):
        if self._mode_code is not None:
            data = self._data_state is not None and self._data_state[0]
            self.mode.emit(mode_name(self._mode_code, data))

    def _handle(self, frame):
        """Traite une trame CI-V et renvoie sa commande."""
        start = frame.find(b"\xfe\xfe")
        if start < 0:
            return None
        frame = frame[start:].lstrip(b"\xfe")
        if len(frame) < 3 or frame[1] != RIG_ADDR:
            return None                     # écho de nos propres commandes
        self._last_reply = time.monotonic()
        cmd, data = frame[2], frame[3:]
        if cmd == 0x27 and len(data) >= 4 and data[0] == 0x00:
            self._wave_part(bcd_be(data[2:3]), bcd_be(data[3:4]), data[4:])
            return None                     # données du scope, pas une réponse
        if cmd in (0x00, 0x03) and len(data) == 5:
            self.frequency.emit(bcd_le(data))
        elif cmd in (0x01, 0x04) and data:
            self._mode_code = data[0]
            if len(data) >= 2:
                self._filter = data[1]
            self._emit_mode()
        elif cmd == 0x25 and len(data) == 6 and data[0] == 0x01:
            self.other_frequency.emit(bcd_le(data[1:]))
        elif cmd == 0x26 and len(data) >= 2 and data[0] == 0x01:
            self.other_mode.emit(mode_name(data[1], len(data) >= 3 and data[2]))
        elif cmd == 0x1C and len(data) == 2 and data[0] == 0x01:
            self._tuner = data[1]
            self.tuner.emit(data[1])
        elif cmd == 0x1C and len(data) == 2 and data[0] == 0x00:
            if not (data[1] == 0x00 and self._ptt
                    and time.monotonic() - getattr(self, "_keyed_at", 0) < 3):
                self._tx = data[1] == 0x01
                self.transmitting.emit(self._tx)
        elif cmd == 0x1A and len(data) == 3 and data[0] == 0x06:
            self._data_state = (data[1], data[2])
            self._emit_mode()
        elif cmd == 0x1A and len(data) == 5 and data[:3] == b"\x05\x00\x65":
            self.usb_mod.emit(bcd_be(data[3:]))
        elif cmd == 0x1A and len(data) == 4 and data[:3] == b"\x05\x00\x66":
            self._data_off_mod = data[3]
        elif cmd == 0x14 and len(data) == 3 and data[0] == 0x0A:
            self.power.emit(bcd_be(data[1:]))
        elif cmd == 0x15 and len(data) == 3 and data[0] in (0x11, 0x12, 0x13):
            self._tx_meters[data[0] - 0x11] = bcd_be(data[1:])
            if data[0] == 0x11:
                self.po_meter.emit(bcd_be(data[1:]))
            if data[0] == 0x13:
                self.tx_meters.emit(*self._tx_meters)
        elif cmd == 0x15 and len(data) == 3 and data[0] == 0x14:
            self.comp.emit(bcd_be(data[1:]))
        elif cmd == 0x15 and len(data) == 3 and data[0] == 0x16:
            self.drain.emit(bcd_be(data[1:]))
        elif cmd == 0x16 and len(data) == 2 and data[0] == 0x44:
            self.comp_on.emit(bool(data[1]))
        elif cmd == 0x14 and len(data) == 3 and data[0] == 0x0E:
            self.comp_level.emit(bcd_be(data[1:]))
        elif cmd == 0x16 and len(data) == 2 and data[0] == 0x46:
            self.vox.emit(bool(data[1]))
        elif cmd == 0x14 and len(data) == 3 and data[0] == 0x16:
            self.vox_gain.emit(bcd_be(data[1:]))
        elif cmd == 0x14 and len(data) == 3 and data[0] == 0x09:
            # 0–255 → 300–900 Hz par pas de 5 Hz
            self.cw_pitch.emit(int(round((300 + bcd_be(data[1:]) * 600 / 255) / 5) * 5))
        elif cmd == 0x14 and len(data) == 3 and data[0] == 0x01:
            self.af_gain.emit(bcd_be(data[1:]))
        elif cmd == 0x15 and len(data) == 3 and data[0] == 0x02:
            self.meter.emit(bcd_be(data[1:]))
        elif cmd == 0x27 and len(data) == 3 and data[0] == 0x14:
            if self._scope_mode is None:
                self._scope_mode = data[2]
        elif cmd == 0x27 and len(data) == 3 and data[0] == 0x1A:
            if self._scope_speed is None:
                self._scope_speed = data[2]
        elif cmd == 0x27 and len(data) == 7 and data[0] == 0x15:
            self.span.emit(bcd_le(data[2:]))
        return cmd

    def _wave_part(self, seq, total, payload):
        """Un balayage arrive en `total` trames ; la première donne les bords."""
        self._last_wave = time.monotonic()
        if seq == 1:
            self._wave = []
            self._wave_edges = None
            if len(payload) >= 11:
                a, b = bcd_le(payload[1:6]), bcd_le(payload[6:11])
                # mode centré : fréquence centrale et demi-largeur
                self._wave_edges = (a - b, a + b) if payload[0] == 0 else (a, b)
        elif self._wave is not None and seq == len(self._wave) + 2:
            self._wave.append(payload)
            if seq == total and self._wave_edges:
                points = np.frombuffer(b"".join(self._wave), np.uint8)
                self.scope.emit(points.astype(np.float32), *self._wave_edges)
                self._wave = None
        else:
            self._wave = None               # trame perdue : on attend le suivant

    def stop(self):
        # laisser le temps de couper l'émission et de remettre le scope
        self._running = False
        self.wait(6000)


# RNNoise : part de son d'origine (non filtré) mêlée au son filtré, selon le
# S-mètre — signal faible : davantage d'origine, pour ne pas perdre la station
RNN_MIX_WEAK = 0.35                 # à S3 et en dessous
RNN_MIX_STRONG = 0.12               # à S9 et au-dessus
RNN_RAW_WEAK, RNN_RAW_STRONG = 40, 120      # valeurs brutes Icom (S3, S9)
RNN_CLEAN_VOLUME = 220             # volume de départ du son épuré (%)

RECH_MAN_TEXT = "RECH MAN"
MANUAL_HOLD_S = 20                  # arrêt sur chaque station en RECH MAN
# trois pièces accolées : coins arrondis seulement aux extrémités
GLUE_LEFT = ("QPushButton { border-top-right-radius: 0; border-bottom-right-radius: 0;"
             " border-right-width: 1px; }")
GLUE_MID = "QPushButton { border-radius: 0; border-left-width: 1px; border-right-width: 1px; }"
GLUE_RIGHT = ("QPushButton { border-top-left-radius: 0; border-bottom-left-radius: 0;"
              " border-left-width: 1px; }")


class SignButton(QtWidgets.QPushButton):
    """Bouton « − ◀ » ou « ▶ + » de RECH MAN : signe en gras coloré au bout de
    la flèche."""

    def __init__(self, sign, color, left):
        super().__init__()
        self.sign, self.color, self.left = sign, QtGui.QColor(color), left
        self.setMinimumWidth(56)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        font = QtGui.QFont(self.font())
        font.setBold(True)
        big = QtGui.QFont(font)
        big.setPointSizeF(font.pointSizeF() * 1.5)
        shift = 1 if self.isDown() else 0               # bouton enfoncé
        r = self.rect().adjusted(9, -2 + shift, -9, shift)
        arrow, sign_align, arrow_align = (
            ("◀", QtCore.Qt.AlignLeft, QtCore.Qt.AlignRight) if self.left else
            ("▶", QtCore.Qt.AlignRight, QtCore.Qt.AlignLeft))
        p.setFont(font)
        p.setPen(QtGui.QColor("#151515"))
        p.drawText(r, arrow_align | QtCore.Qt.AlignVCenter, arrow)
        p.setFont(big)
        p.setPen(self.color)
        p.drawText(r, sign_align | QtCore.Qt.AlignVCenter, self.sign)
        p.end()


class FrequencyDisplay(QtWidgets.QWidget):
    """Afficheur de fréquence rétro-éclairé, en creux dans une lunette en relief.
    Réglable à la molette."""
    tuned = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._text = "--.---.---"
        self.setFixedSize(370, 74)
        self.setToolTip("Molette : changer la fréquence")
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self._angle = 0
        self.font = QtGui.QFont("DejaVu Sans Mono", 34, QtGui.QFont.Bold)

    def setText(self, text):
        if text != self._text:
            self._text = text
            self.update()

    def text(self):
        return self._text

    def wheelEvent(self, event):
        self._angle += event.angleDelta().y()
        steps = int(self._angle / 120)
        if steps:
            self._angle -= steps * 120
            self.tuned.emit(steps)
        event.accept()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QtCore.Qt.NoPen)
        # ombre portée
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.drawRoundedRect(QtCore.QRectF(3, 4, w - 3, h - 4), 10, 10)
        # lunette métallique en relief
        rim = QtGui.QLinearGradient(0, 0, 0, h)
        rim.setColorAt(0, QtGui.QColor("#f2f2f2"))
        rim.setColorAt(0.45, QtGui.QColor("#9a9a9a"))
        rim.setColorAt(1, QtGui.QColor("#2c2c2c"))
        p.setBrush(rim)
        outer = QtCore.QRectF(0, 0, w - 4, h - 5)
        p.drawRoundedRect(outer, 10, 10)
        body = outer.adjusted(3, 3, -3, -3)
        metal = QtGui.QLinearGradient(0, body.top(), 0, body.bottom())
        metal.setColorAt(0, QtGui.QColor("#cfcfcf"))
        metal.setColorAt(0.5, QtGui.QColor("#7d7d7d"))
        metal.setColorAt(1, QtGui.QColor("#565656"))
        p.setBrush(metal)
        p.drawRoundedRect(body, 8, 8)
        # vitre creusée : bord sombre en haut, clair en bas
        well = body.adjusted(6, 6, -6, -6)
        groove = QtGui.QLinearGradient(0, well.top(), 0, well.bottom())
        groove.setColorAt(0, QtGui.QColor("#000000"))
        groove.setColorAt(1, QtGui.QColor("#d8d8d8"))
        p.setBrush(groove)
        p.drawRoundedRect(well, 6, 6)
        glass = well.adjusted(2, 2, -2, -2)
        # fond rétro-éclairé : bleu nuit, plus lumineux au centre
        back = QtGui.QRadialGradient(glass.center(), glass.width() * 0.6)
        back.setColorAt(0, QtGui.QColor("#0d3346"))
        back.setColorAt(0.7, QtGui.QColor("#07202d"))
        back.setColorAt(1, QtGui.QColor("#020a0f"))
        p.setBrush(back)
        p.drawRoundedRect(glass, 5, 5)
        # ombre intérieure (profondeur)
        shade = QtGui.QLinearGradient(0, glass.top(), 0, glass.top() + 14)
        shade.setColorAt(0, QtGui.QColor(0, 0, 0, 200))
        shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawRoundedRect(glass, 5, 5)
        # chiffres à 7 segments : segments éteints en filigrane, allumés avec halo
        lit, ghost = self._segment_paths(glass)
        p.setBrush(QtGui.QColor(79, 195, 247, 34))
        p.drawPath(ghost)
        p.setBrush(QtCore.Qt.NoBrush)
        for width, alpha in ((9, 25), (6, 40), (3, 70)):        # halo lumineux
            p.setPen(QtGui.QPen(QtGui.QColor(79, 195, 247, alpha), width,
                                QtCore.Qt.SolidLine, QtCore.Qt.RoundCap,
                                QtCore.Qt.RoundJoin))
            p.drawPath(lit)
        p.setPen(QtCore.Qt.NoPen)
        r = lit.boundingRect()
        digits = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        digits.setColorAt(0, QtGui.QColor("#d9f6ff"))
        digits.setColorAt(0.5, QtGui.QColor("#6fd6ff"))
        digits.setColorAt(1, QtGui.QColor("#29a8e0"))
        p.setBrush(digits)
        p.drawPath(lit)
        # étiquette (horloges : LOCAL / TU)
        tag = getattr(self, "tag", "")
        if tag:
            f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Bold)
            p.setFont(f)
            p.setPen(QtGui.QColor(111, 214, 255, 200))
            p.drawText(QtCore.QRectF(glass.left() + 4, glass.top(), self.tag_width,
                                     glass.height()), QtCore.Qt.AlignCenter, tag)
            p.setPen(QtCore.Qt.NoPen)
        # reflet de la vitre
        shine = QtGui.QLinearGradient(0, glass.top(), 0, glass.top() + glass.height() * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 55))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawRoundedRect(QtCore.QRectF(glass.left() + 3, glass.top() + 2,
                                        glass.width() - 6, glass.height() * 0.42), 4, 4)
        p.end()


    # segments allumés pour chaque caractère (a haut, b haut droit, c bas droit,
    # d bas, e bas gauche, f haut gauche, g milieu)
    SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
                "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg",
                "9": "abcdfg", "-": "g", " ": ""}

    def _segment_paths(self, glass):
        """Chemins des segments allumés et éteints, centrés dans la vitre."""
        h = getattr(self, "digit_h", None) or (glass.height() - 12)  # hauteur d'un chiffre
        dw = h * 0.52                           # largeur d'un chiffre
        t = h * 0.13                            # épaisseur d'un segment
        gap = h * 0.20                          # espace entre chiffres
        dotw = h * 0.26                         # place d'un point
        slant = 0.10                            # chiffres penchés
        text = self._text
        n = sum(c not in ".,:" for c in text)
        places = getattr(self, "places", 8)
        text = " " * max(0, places - n) + text  # toujours le même nombre de places
        widths = [dotw if c in ".,:" else dw + gap for c in text]
        offset = getattr(self, "tag_width", 0)  # place de l'étiquette à gauche
        x = glass.center().x() + offset / 2 - (sum(widths) - gap) / 2
        top = glass.center().y() - h / 2
        lit, ghost = QtGui.QPainterPath(), QtGui.QPainterPath()

        def hseg(x0, y0):           # segment horizontal (losange allongé)
            m = t / 2
            return [(x0 + m * 0.4, y0), (x0 + m * 1.4, y0 - m), (x0 + dw - m * 1.4, y0 - m),
                    (x0 + dw - m * 0.4, y0), (x0 + dw - m * 1.4, y0 + m),
                    (x0 + m * 1.4, y0 + m)]

        def vseg(x0, y0, y1):       # segment vertical
            m = t / 2
            return [(x0, y0 + m * 0.4), (x0 + m, y0 + m * 1.4), (x0 + m, y1 - m * 1.4),
                    (x0, y1 - m * 0.4), (x0 - m, y1 - m * 1.4), (x0 - m, y0 + m * 1.4)]

        def add(path, pts):
            # penche le chiffre : décalage vers la droite en montant
            poly = QtGui.QPolygonF([QtCore.QPointF(px + (top + h - py) * slant, py)
                                    for px, py in pts])
            path.addPolygon(poly)
            path.closeSubpath()

        for c, cw in zip(text, widths):
            if c in ".,:":
                d = t * 1.1
                rows = (top + h * 0.28, top + h * 0.72 - d) if c == ":" else (top + h - d,)
                for y in rows:
                    dot = QtGui.QPainterPath()
                    dot.addEllipse(QtCore.QRectF(x - gap / 2 + (dotw - d) / 2, y, d, d))
                    lit.addPath(dot)
            else:
                m = t / 2
                y_top, y_mid, y_bot = top + m, top + h / 2, top + h - m
                shapes = {"a": hseg(x, y_top), "g": hseg(x, y_mid), "d": hseg(x, y_bot),
                          "f": vseg(x + m, y_top, y_mid), "b": vseg(x + dw - m, y_top, y_mid),
                          "e": vseg(x + m, y_mid, y_bot), "c": vseg(x + dw - m, y_mid, y_bot)}
                on = self.SEGMENTS.get(c, "")
                for name, pts in shapes.items():
                    add(lit if name in on else ghost, pts)
            x += cw
        return lit, ghost


class PercentDisplay(FrequencyDisplay):
    """Petit afficheur rétro-éclairé « 100 % » (même boîtier que la fréquence)."""

    def __init__(self):
        super().__init__()
        self.places = 3
        self.digit_h = 13
        self.tag_width = -18                # chiffres décalés à gauche, « % » à droite
        self.setFixedSize(96, 46)
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.setText("100")

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        glass = QtCore.QRectF(0, 0, w - 4, h - 5).adjusted(11, 11, -11, -11)
        p.setFont(QtGui.QFont("DejaVu Sans", 9, QtGui.QFont.Bold))
        p.setPen(QtGui.QColor(111, 214, 255, 230))
        p.drawText(glass.adjusted(0, 0, -3, 0), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                   "%")
        p.end()

    def wheelEvent(self, event):
        event.ignore()


class ClockPair(FrequencyDisplay):
    """Deux horloges HH:MM:SS (locale en haut, TU en bas) dans le même boîtier
    rétro-éclairé que la fréquence."""

    def __init__(self):
        super().__init__()
        self.places = 6
        self.digit_h = 15
        self.tag_width = 40
        self.setFixedSize(172, 74)
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.setToolTip("En haut : heure locale du PC · en bas : heure TU "
                        "(temps universel, UTC), celle des carnets de trafic")
        self.lines = ("--:--:--", "--:--:--")
        self._tick()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)

    def _tick(self):
        lines = (datetime.datetime.now().strftime("%H:%M:%S"),
                 datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S"))
        if lines != self.lines:
            self.lines = lines
            self.update()

    def _segment_paths(self, glass):
        lit, ghost = QtGui.QPainterPath(), QtGui.QPainterPath()
        half = glass.height() / 2
        for i, text in enumerate(self.lines):
            row = QtCore.QRectF(glass.left(), glass.top() + i * half, glass.width(), half)
            self._text = text
            a, b = FrequencyDisplay._segment_paths(self, row)
            lit.addPath(a)
            ghost.addPath(b)
        return lit, ghost

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        glass = QtCore.QRectF(0, 0, w - 4, h - 5).adjusted(11, 11, -11, -11)
        half = glass.height() / 2
        p.setFont(QtGui.QFont("DejaVu Sans", 7, QtGui.QFont.Bold))
        p.setPen(QtGui.QColor(111, 214, 255, 210))
        for i, tag in enumerate(("LOCAL", "TU")):
            p.drawText(QtCore.QRectF(glass.left() + 3, glass.top() + i * half,
                                     self.tag_width, half), QtCore.Qt.AlignVCenter, tag)
        p.end()

    def wheelEvent(self, event):
        event.ignore()                  # pas de réglage sur une horloge


class CwEntry(QtWidgets.QLineEdit):
    """Champ de saisie CW : Échap arrête l'émission en cours."""
    escape = QtCore.pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.escape.emit()
            return
        super().keyPressEvent(event)


class TuningKnob(QtWidgets.QWidget):
    """Bouton de VFO : on le tourne à la souris (glisser) ou à la molette."""
    tuned = QtCore.pyqtSignal(int)
    DETENTS = 40                    # crans par tour

    def __init__(self):
        super().__init__()
        self.setFixedSize(285, 285)            # très gros bouton vintage (×1,5)
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self.setToolTip("Glisser en tournant ou molette : changer la fréquence")
        self.angle = 0.0
        self._accum = 0.0
        self._last = None
        self._wheel = 0

    def _angle_at(self, pos):
        c = self.rect().center()
        return math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))

    def _rotate(self, degrees):
        self.angle = (self.angle + degrees) % 360
        self._accum += degrees
        per_detent = 360 / self.DETENTS
        steps = int(self._accum / per_detent)
        if steps:
            self._accum -= steps * per_detent
            self.tuned.emit(steps)
        self.update()

    # Un clic simple ne change rien. Double-clic : le VFO s'accroche à la
    # souris (anneau lumineux) et tourne en suivant ses déplacements, sans
    # tenir le bouton ; nouveau double-clic, clic droit ou Échap : décroché.
    def mousePressEvent(self, event):
        if not KNOB_MODE["precision"]:          # mode direct : clic + glisser
            if event.button() == QtCore.Qt.LeftButton:
                self._direct = True
                self._last = self._angle_at(event.pos())
            event.accept()
            return
        if self._last is not None and not self.rect().contains(event.pos()):
            self._release()                     # accroché : un clic EN DEHORS décroche
            self._unhooked_at = time.monotonic()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if not KNOB_MODE["precision"]:
            event.accept()
            return
        if time.monotonic() - getattr(self, "_unhooked_at", 0) < 0.6:
            event.accept()                      # 2e clic du double-clic qui a décroché
            return
        if self._last is not None:
            self._release()
        else:
            self._last = self._angle_at(event.pos())
            self.setMouseTracking(True)
            self.grabMouse(QtGui.QCursor(QtCore.Qt.ClosedHandCursor))
            self.grabKeyboard()
            self.update()
        event.accept()

    def _release(self):
        if self._last is None:
            return
        self._last = None
        self.setMouseTracking(False)
        self.releaseMouse()
        self.releaseKeyboard()
        self.update()

    def keyPressEvent(self, event):
        if self._last is not None and event.key() == QtCore.Qt.Key_Escape:
            self._release()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        self._release()
        super().hideEvent(event)

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        c = self.rect().center()
        if not getattr(self, "_direct", False) and max(
                abs(event.pos().x() - c.x()), abs(event.pos().y() - c.y())) > 1.5 * self.width():
            self._release()                     # souris partie loin du VFO : décroché
            return
        a = self._angle_at(event.pos())
        delta = (a - self._last + 180) % 360 - 180
        self._last = a
        self._rotate(delta)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_direct", False):     # mode direct : on lâche, c'est fini
            self._direct = False
            self._last = None
            self.update()
        event.accept()

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            self._rotate(steps * 360 / self.DETENTS)
        event.accept()

    def paintEvent(self, event):
        """Gros bouton façon Collins : jupe noire graduée 0…100 qui tourne,
        index fixe en haut, bouton en aluminium brossé à bord moleté,
        creux pour le doigt, ombre portée."""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = QtCore.QPointF(self.rect().center())
        R = min(self.width(), self.height()) / 2 - 2
        skirt_r = R - 12
        # ombre portée de la jupe
        p.setPen(QtCore.Qt.NoPen)
        for k, alpha in enumerate((70, 45, 25)):
            p.setBrush(QtGui.QColor(0, 0, 0, alpha))
            p.drawEllipse(c + QtCore.QPointF(3 + k, 5 + k), skirt_r + 1 + k, skirt_r + 1 + k)
        # index fixe : triangle crème en haut, sur la façade
        tip = c + QtCore.QPointF(0, -skirt_r + 1)
        tri = QtGui.QPolygonF([tip, tip + QtCore.QPointF(-7, -10), tip + QtCore.QPointF(7, -10)])
        p.setBrush(QtGui.QColor("#f2ead2"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawPolygon(tri)
        # jupe noire brillante (bord biseauté)
        g = QtGui.QRadialGradient(c - QtCore.QPointF(skirt_r * 0.3, skirt_r * 0.35), skirt_r * 1.5)
        g.setColorAt(0, QtGui.QColor("#3a3a3a"))
        g.setColorAt(0.6, QtGui.QColor("#121212"))
        g.setColorAt(1, QtGui.QColor("#020202"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.5))
        p.setBrush(g)
        p.drawEllipse(c, skirt_r, skirt_r)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 45), 1.2))
        p.drawArc(QtCore.QRectF(c.x() - skirt_r + 2, c.y() - skirt_r + 2,
                                2 * skirt_r - 4, 2 * skirt_r - 4), 40 * 16, 120 * 16)
        # graduations blanches 0…100 sur la jupe (tournent avec le bouton)
        cream = QtGui.QColor("#f1ecdc")
        p.setFont(QtGui.QFont("DejaVu Sans", 7, QtGui.QFont.Bold))
        for i in range(100):
            a = math.radians(i * 3.6 - 90 + self.angle)
            u = QtCore.QPointF(math.cos(a), math.sin(a))
            big, mid = i % 10 == 0, i % 5 == 0
            p.setPen(QtGui.QPen(cream, 1.6 if big else 1.0 if mid else 0.7))
            p.drawLine(c + u * (skirt_r - 3), c + u * (skirt_r - (11 if big else 8 if mid else 5)))
            if big:
                pt = c + u * (skirt_r - 19)
                p.setPen(cream)
                p.drawText(QtCore.QRectF(pt.x() - 10, pt.y() - 6, 20, 12),
                           QtCore.Qt.AlignCenter, str(i))
        body = skirt_r - 30
        # ombre du bouton sur la jupe
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 120))
        p.drawEllipse(c + QtCore.QPointF(2, 4), body + 2, body + 2)
        # bord moleté en aluminium (stries qui tournent)
        g = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#fdfdfd"), (0.12, "#8c9095"), (0.3, "#e9ebed"),
                          (0.5, "#62676c"), (0.7, "#dadde0"), (0.86, "#7f8489"), (1, "#fdfdfd")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#2a2c2e"), 1.2))
        p.setBrush(g)
        p.drawEllipse(c, body, body)
        for i in range(90):
            a = math.radians(i * 4 + self.angle)
            u = QtCore.QPointF(math.cos(a), math.sin(a))
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 1))
            p.drawLine(c + u * (body - 9), c + u * (body - 0.5))
        # face en aluminium brossé : reflets en cône (lumière fixe) + tournage
        face = body - 10
        g = QtGui.QConicalGradient(c, 45)
        for stop, col in ((0, "#f6f7f8"), (0.12, "#c4c8cc"), (0.25, "#9da2a7"),
                          (0.38, "#d8dbde"), (0.5, "#f2f3f4"), (0.62, "#bfc3c7"),
                          (0.75, "#979ca1"), (0.88, "#d4d7da"), (1, "#f6f7f8")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#55595d"), 1))
        p.setBrush(g)
        p.drawEllipse(c, face, face)
        p.setBrush(QtCore.Qt.NoBrush)
        for k in range(3, int(face), 2):
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 16 if k % 4 == 1 else 9), 0.8))
            p.drawEllipse(c, k, k)
        # léger bombé : halo clair en haut à gauche
        g = QtGui.QRadialGradient(c - QtCore.QPointF(face * 0.4, face * 0.45), face * 1.1)
        g.setColorAt(0, QtGui.QColor(255, 255, 255, 70))
        g.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, face, face)
        # creux pour le doigt (concave : sombre en haut à gauche, clair en bas)
        a = math.radians(self.angle - 90)
        u = QtCore.QPointF(math.cos(a), math.sin(a))
        dimple = c + u * face * 0.6
        dr = face * 0.2
        dg = QtGui.QLinearGradient(dimple - QtCore.QPointF(dr, dr), dimple + QtCore.QPointF(dr, dr))
        dg.setColorAt(0, QtGui.QColor("#6a6e72"))
        dg.setColorAt(0.5, QtGui.QColor("#b8bcc0"))
        dg.setColorAt(1, QtGui.QColor("#f4f5f6"))
        p.setPen(QtGui.QPen(QtGui.QColor("#4a4e52"), 1))
        p.setBrush(dg)
        p.drawEllipse(dimple, dr, dr)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 120), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(QtCore.QRectF(dimple.x() - dr, dimple.y() - dr, 2 * dr, 2 * dr),
                  200 * 16, 140 * 16)
        self._paint_badge(p, c, face * 0.36)
        if self._last is not None and not getattr(self, "_direct", False):   # accroché
            for k, a in ((0, 230), (3, 120), (6, 50)):
                p.setPen(QtGui.QPen(QtGui.QColor(255, 190, 60, a), 3))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(c, skirt_r + 2 - k, skirt_r + 2 - k)
        p.end()

    @staticmethod
    def _gold_text(p, rect, text, font, spacing=0.0):
        """Lettres dorées en relief : ombre sombre, puis dégradé or."""
        font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, spacing)
        path = QtGui.QPainterPath()
        fm = QtGui.QFontMetricsF(font)
        x = rect.center().x() - fm.horizontalAdvance(text) / 2
        y = rect.center().y() + (fm.ascent() - fm.descent()) / 2
        path.addText(x, y, font, text)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 200))
        p.drawPath(path.translated(0.8, 1.0))
        g = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
        g.setColorAt(0, QtGui.QColor("#fff2b8"))
        g.setColorAt(0.45, QtGui.QColor("#e0b54a"))
        g.setColorAt(0.55, QtGui.QColor("#a8781c"))
        g.setColorAt(1, QtGui.QColor("#f0d277"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor(90, 60, 10, 160), 0.4))
        p.drawPath(path)

    def _paint_badge(self, p, c, r):
        """Médaillon fixe F4TXR : bague chromée, émail noir, filet et lettres or."""
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 110))                   # ombre
        p.drawEllipse(c + QtCore.QPointF(1.5, 2.5), r + 1, r + 1)
        g = QtGui.QConicalGradient(c, 135)                       # bague chromée
        for stop, col in ((0, "#ffffff"), (0.25, "#70757b"), (0.5, "#e9ebed"),
                          (0.75, "#575c62"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1c1e20"), 1))
        p.drawEllipse(c, r, r)
        er = r - 4                                               # émail noir
        g = QtGui.QRadialGradient(c - QtCore.QPointF(er * 0.3, er * 0.35), er * 1.4)
        g.setColorAt(0, QtGui.QColor("#2c2a30"))
        g.setColorAt(0.6, QtGui.QColor("#0e0d10"))
        g.setColorAt(1, QtGui.QColor("#030303"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 0.8))
        p.drawEllipse(c, er, er)
        p.setBrush(QtCore.Qt.NoBrush)                            # filet doré
        p.setPen(QtGui.QPen(QtGui.QColor("#c9a043"), 1.1))
        p.drawEllipse(c, er - 3, er - 3)
        p.setPen(QtGui.QPen(QtGui.QColor(201, 160, 67, 110), 0.6))
        p.drawEllipse(c, er - 5, er - 5)
        # petites étoiles dorées de part et d'autre
        for side in (-1, 1):
            sc = c + QtCore.QPointF(side * er * 0.62, -er * 0.02)
            star = QtGui.QPolygonF([sc + QtCore.QPointF(
                math.cos(math.radians(90 + k * 36)) * (2.6 if k % 2 == 0 else 1.1),
                -math.sin(math.radians(90 + k * 36)) * (2.6 if k % 2 == 0 else 1.1))
                for k in range(10)])
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#e0b54a"))
            p.drawPolygon(star)
        # textes
        f = QtGui.QFont("URW Gothic", 5, QtGui.QFont.Bold)
        self._gold_text(p, QtCore.QRectF(c.x() - er, c.y() - er * 0.72, 2 * er, er * 0.42),
                        "RADIO", f, 1.6)
        f = QtGui.QFont("URW Gothic", 11, QtGui.QFont.Black)
        self._gold_text(p, QtCore.QRectF(c.x() - er, c.y() - er * 0.3, 2 * er, er * 0.6),
                        "F4TXR", f, 0.6)
        f = QtGui.QFont("URW Gothic", 6, QtGui.QFont.Bold)
        self._gold_text(p, QtCore.QRectF(c.x() - er, c.y() + er * 0.32, 2 * er, er * 0.42),
                        "73", f, 1.0)
        # verre bombé : reflet
        hl = QtCore.QRectF(c.x() - er * 0.75, c.y() - er * 0.85, er * 1.2, er * 0.7)
        g = QtGui.QLinearGradient(hl.topLeft(), hl.bottomLeft())
        g.setColorAt(0, QtGui.QColor(255, 255, 255, 70))
        g.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(hl)


class BarGraph(QtWidgets.QWidget):
    """Bargraph à segments avec mémoire de crête."""

    def __init__(self, minimum, maximum, ticks, red_from, segments=48, hold=1.0,
                 curve=1.0, fall=None):
        super().__init__()
        self.hold = hold
        self.curve = curve              # < 1 : échelle dilatée (petites valeurs plus visibles)
        self.fall = fall                # vitesse de descente (unités/s) ; None = immédiate
        self.last_set = 0.0
        self.minimum = minimum
        self.maximum = maximum
        self.ticks = ticks
        self.red_from = red_from
        self.segments = segments
        self.value = minimum
        self.peak = minimum
        self.peak_time = 0.0
        self.setMinimumHeight(32)       # plus bas : place gagnée pour le waterfall
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Fixed)

    def setValue(self, value):
        value = min(max(value, self.minimum), self.maximum)
        now = time.monotonic()
        if self.fall and value < self.value:    # monte d'un coup, redescend doucement
            value = max(value, self.value - self.fall * (now - self.last_set))
        self.last_set = now
        self.value = value
        if value >= self.peak:
            self.peak = value
            self.peak_time = now
        elif now - self.peak_time > self.hold:
            step = (self.maximum - self.minimum) * 0.015
            self.peak = max(value, self.peak - step)
        self.update()

    def _fraction(self, value):
        f = (value - self.minimum) / (self.maximum - self.minimum)
        return max(0.0, f) ** self.curve

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        w, h = self.width(), self.height()
        margin = 6
        bar_h = h - 18
        inner_w = w - 2 * margin
        p.fillRect(self.rect(), QtGui.QColor("#0b0f13"))
        seg_w = inner_w / self.segments
        lit_fraction = self._fraction(self.value)
        green, red = QtGui.QColor("#3ddc84"), QtGui.QColor("#ff5252")
        for i in range(self.segments):
            centre = (i + 0.5) / self.segments
            seg_value = self.minimum + centre ** (1 / self.curve) * (self.maximum - self.minimum)
            color = red if seg_value >= self.red_from else green
            if centre > lit_fraction:
                color = color.darker(500)
            p.fillRect(QtCore.QRectF(margin + i * seg_w + 1, 4, seg_w - 2,
                                     bar_h - 4), color)
        if self.peak > self.minimum:
            x = margin + self._fraction(self.peak) * inner_w
            p.fillRect(QtCore.QRectF(x - 1.5, 2, 3, bar_h), QtGui.QColor("#ffd54a"))
        font = p.font()
        font.setPointSizeF(8)
        p.setFont(font)
        p.setPen(QtGui.QColor("#b0bec5"))
        for value, label in self.ticks:
            x = margin + self._fraction(value) * inner_w
            x = min(max(x, 24), w - 24)
            p.drawText(QtCore.QRectF(x - 24, bar_h + 1, 48, 16),
                       QtCore.Qt.AlignCenter, label)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.setWindowTitle("IC-7300 Scope")
        # sans la barre blanche du bureau : bandeau vintage « MADE IN F4TXR »
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.FramelessWindowHint)
        self.title_plate = TitlePlate(self)
        self.setMenuWidget(self.title_plate)
        self.audio = AudioReader(args.source)   # démarré une fois l'écran prêt
        self.audio_rate = RATE
        self.sstv_window = None
        self.resize(1100, 760)
        self.fmax = args.fmax
        self.avg = None
        self.waterfall = None
        self.wf_low = -100.0
        self.freq_hz = None
        self.auto_decoder = "?"         # dernier choix automatique du décodeur
        self.ssb_target = None          # fréquence posée par le calage BLU
        self.ssb_anchor = None          # kHz rond sur lequel on s'est calé
        self.snap_timer = QtCore.QTimer(self)
        self.snap_timer.setSingleShot(True)
        self.snap_timer.setInterval(SNAP_DELAY_MS)
        self.snap_timer.timeout.connect(self._snap_to_khz)
        # calage auto : reconnaissance du mode (LSB/USB/AM/FM) et fréquence exacte
        # d'après le scope, juste avant l'arrondi au kHz
        self.detect_timer = QtCore.QTimer(self)
        self.detect_timer.setSingleShot(True)
        self.detect_timer.setInterval(max(300, SNAP_DELAY_MS - 300))
        self.detect_timer.timeout.connect(self._detect_mode)
        self.last_band = None
        self.ssb_recentred = False
        self.other_hz = None
        self.other_mode = ""

        central = QtWidgets.QWidget()
        # FIXE / MOBILE : page 0 = tout l'écran actuel, page 1 = écran MOBILE
        self.pages = QtWidgets.QStackedWidget()
        self.pages.addWidget(central)
        self.pages.addWidget(self._mobile_page())
        self.setCentralWidget(self.pages)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(5, 4, 5, 4)       # marges serrées : tout tient dans l'écran
        layout.setSpacing(3)

        # Fréquence, mode et état
        top = QtWidgets.QHBoxLayout()
        self.freq_label = DrumDisplay()         # compteur à tambours mécaniques
        self.freq_label.tuned.connect(self.on_tuned)
        self.step_combo = QtWidgets.QComboBox()
        for label, hz in STEPS:
            self.step_combo.addItem(label, hz)
        self.step_combo.setCurrentIndex(2)
        self.step_combo.setToolTip("Pas de la molette sur la fréquence")
        self.freq_entry = QtWidgets.QLineEdit()
        self.freq_entry.setPlaceholderText("7074 ou 14.074")
        self.freq_entry.setToolTip("kHz, MHz (avec un point) ou Hz, puis Entrée")
        self.freq_entry.setMaximumWidth(130)
        self.freq_entry.returnPressed.connect(self.on_freq_entered)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(MODE_NAMES)
        self.mode_combo.setStyleSheet("font: bold 16pt; color: #ffd54a;")
        self.mode_combo.activated[str].connect(self.on_mode_selected)
        self.cursor_label = QtWidgets.QLabel("")
        self.cursor_label.setStyleSheet("font: 12pt monospace;")
        top.addWidget(self.freq_label)
        top.addWidget(QtWidgets.QLabel("MHz"))
        top.addSpacing(8)
        self.clocks = DrumClock()               # horloges à tambours, assorties
        self.backlight_on_air = False
        self.backlight_timer = QtCore.QTimer(self)    # émission : lumière = voix
        self.backlight_timer.timeout.connect(self._backlight_voice)
        self.freq_label.lamp.connect(self._pump_meters)   # cadrans : même pompage
        top.addWidget(self.clocks)
        top.addSpacing(10)
        top.addWidget(self.step_combo)
        top.addSpacing(20)
        top.addWidget(self.mode_combo)
        top.addSpacing(20)
        top.addWidget(QtWidgets.QLabel("Aller à"))
        top.addWidget(self.freq_entry)
        top.addSpacing(20)
        # Wi-Fi et, juste dessous, le trafic réseau (sortie / entrée)
        net_grid = QtWidgets.QGridLayout()
        net_grid.setSpacing(2)
        net_grid.addWidget(QtWidgets.QLabel("Wi-Fi"), 0, 0)
        self.wifi_bar = WifiBar()
        net_grid.addWidget(self.wifi_bar, 0, 1)
        net_grid.addWidget(QtWidgets.QLabel("Trafic"), 1, 0)
        self.traffic_bar = TrafficBar()
        net_grid.addWidget(self.traffic_bar, 1, 1)
        top.addLayout(net_grid)
        top.addStretch()
        top.addWidget(self.cursor_label)
        left = QtWidgets.QVBoxLayout()
        left.addLayout(top)

        # S-mètre à aiguille, et à côté les mesures d'émission
        self.s_meter = VintageSMeter()
        meters = QtWidgets.QHBoxLayout()
        # Barre « RX fin » (grande, en tête des barres) : signal mesuré sur le
        # spectre dans la bande passante, au-dessus du bruit
        # même échelle que l'aiguille : S1…S9 puis +20/+40/+60 (valeurs brutes Icom)
        rx_ticks = [(i * S9 / 9, f"S{i}") for i in (3, 6, 9)] + \
                   [(S9 + db * (S9_PLUS_60 - S9) / 60, f"+{db}") for db in (20, 40)]
        self.rx_fine = BarGraph(0, S9_PLUS_60, rx_ticks, red_from=S9,
                                segments=60, hold=2.0)          # 60 cases : lisible sous le S-mètre
        self.rx_fine.setToolTip("Réception fine, calée sur l'aiguille du S-mètre "
                                "(1 case ≈ 1 dB). Sous S1, le spectre montre aussi "
                                "les signaux trop faibles pour l'aiguille. "
                                "Repère jaune = crête des 2 dernières secondes.")
        self.rx_fine_value = QtWidgets.QLabel("")
        self.rx_fine_value.setStyleSheet("font: bold 12pt monospace; color: #3ddc84;")
        self.rx_fine_level = 0.0
        self.rx_scope_part = 0.0        # spectre : crête bande passante − bruit
        self.rx_meter_part = 0.0        # S-mètre : écart au fond de bruit, en dB
        self.rx_meter_floor = None
        self.rx_timer = QtCore.QTimer(self)
        self.rx_timer.timeout.connect(self._rx_fine_tick)
        self.rx_timer.start(33)         # même cadence que l'aiguille
        # sous l'aiguille : préampli BF (gain du son reçu), gradué de 0 à 10
        s_col = QtWidgets.QVBoxLayout()
        s_col.setSpacing(2)
        s_col.addWidget(self.s_meter)
        self.preamp_knob = ScaleBakelite(          # bakélite, comme NIVEAU / ALC
            5.0, 88, "",
            lambda v: f"{round((v / 5 if v <= 5 else 1 + (v - 5) * 0.4) * 100)} %")
        self.preamp_knob.setToolTip("Préampli BF : gain du son reçu sur le PC. "
                                    "5 = normal, 0 = silence, 10 = ×3 (+10 dB). "
                                    "Molette 0,1 · Maj+molette 1 · double-clic = 5")
        self.preamp_knob.valueChanged.connect(self.on_preamp)
        self.preamp_label = QtWidgets.QLabel("PRÉAMPLI BF\nposition 5,0")
        self.preamp_label.setStyleSheet("font: bold 10pt; color: #e0e0e0;")
        self.preamp_display = PercentDisplay()
        self.preamp_display.setToolTip("Gain du préampli BF : 100 % = son normal")
        # préampli placé sous le waterfall, au-dessus des bandes (voir plus bas)
        self.preamp_box = QtWidgets.QWidget()
        # à gauche des rangées bandes + modes : chaque bouton au-dessus de son
        # afficheur, libellé à côté (aucune hauteur en plus pour le waterfall)
        pre_row = QtWidgets.QHBoxLayout(self.preamp_box)
        pre_row.setContentsMargins(4, 0, 4, 0)
        pre_row.setSpacing(4)

        def knob_column(knob, display):
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(knob, 0, QtCore.Qt.AlignHCenter)
            display.hide()                  # la valeur est gravée sous le bouton
            return col
        self.preamp_label.setStyleSheet("font: bold 9pt; color: #e0e0e0;")
        self.preamp_display.hide()              # bouton placé dans la rangée du haut
        self.preamp_label.hide()                # nom gravé sur le bouton
        pre_row.addSpacing(6)
        # volume d'écoute sur le PC en bouton rond (suit le curseur « Volume PC »),
        # la radio n'est pas touchée ; 0 à 10 = 0 à 150 %
        self.af_knob = ScaleBakelite(
            0.0, 88, "",
            lambda v: f"{self.pc_volume.value() if hasattr(self, 'pc_volume') else round(v * 15)} %")
        self.af_knob.setToolTip("Volume d'écoute sur le PC seulement (pas la radio). "
                                "Molette 1,5 % · Maj+molette 15 % · double-clic = 75 %")
        self.af_knob.valueChanged.connect(self.on_af_knob)
        self.af_display = PercentDisplay()
        self.af_display.setText("0")
        self.af_display.setToolTip("Volume d'écoute sur le PC")
        af_label = QtWidgets.QLabel("VOLUME BF\nPC")
        af_label.setStyleSheet("font: bold 10pt; color: #e0e0e0;")
        af_label.setStyleSheet("font: bold 9pt; color: #e0e0e0;")
        self.af_display.hide()                  # bouton placé dans la rangée du haut
        # libellé + commutateur casque / HP PC (ajouté plus bas) l'un sous l'autre
        self.af_label_box = QtWidgets.QVBoxLayout()
        self.af_label_box.setSpacing(4)
        self.af_label_box.addStretch()
        af_label.hide()                         # nom gravé sur le bouton
        pre_row.addLayout(self.af_label_box)
        # sous le S-mètre, juste au-dessus du waterfall : NIVEAU micro et ALC
        self.level_knob = VintageKnob(
            88, 100, "%", None, "",
            "Niveau du son envoyé à la radio : glisser, ou molette (1 %, Maj = 10 %)")
        self.alc_knob = VintageKnob(
            88, 100, "%", None, "",
            "Gain de l'entrée USB de la radio (USB MOD LEVEL) : glisser, ou molette")
        self.alc_knob.setEnabled(False)         # activé quand la radio répond
        self.clean_knob = VintageKnob(
            88, 400, "%", None, "",
            "Volume du son épuré quand RNNOISE est actif (au-delà de 100 % : amplifié)")
        self.clean_knob.setEnabled(False)       # actif avec RNNOISE
        self.view_toggle = ToggleSwitch(
            "RF", "AUDIO", tooltip="Affichage du spectre et du waterfall : RF = scope "
            "de la radio (clic pour s'y caler), AUDIO = le son reçu")
        self.af_radio_knob = VintageKnob(
            88, 100, "%", None, "",
            "Volume du haut-parleur de la radio (AF) — le son vers le PC n'en dépend pas")
        self.af_radio_knob.setEnabled(False)    # activé quand la radio répond
        self.mute_toggle = ToggleSwitch(
            "SON", "MUET", tooltip="Levier en bas : son de la radio coupé sur le PC")
        self.precision_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="PRÉCISION : levier en bas (ON) = double-clic pour "
            "accrocher un bouton à la souris, double-clic pour le décrocher ; "
            "en haut (OFF) = clic et glisser directement")
        self.precision_toggle.setDown(True, emit=False)   # ON au démarrage
        self.precision_toggle.pos_f = 1.0
        self.precision_toggle.toggled.connect(self._precision_toggled)
        self.message_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="MESSAGE : levier en bas = la radio émet en CW le "
            "message préparé (puis revient sur OFF) ; en haut = arrêt. "
            "Clic droit : écrire le message.")
        self.message_toggle.toggled.connect(self._message_toggled)
        self.message_toggle.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.message_toggle.customContextMenuRequested.connect(self._edit_message)
        self.message_timer = QtCore.QTimer(self)
        self.message_timer.setSingleShot(True)
        self.message_timer.timeout.connect(self._message_next)
        self.message_chunks = []
        # écran CW plein écran (bouton de mode CW) : EMISSION en haut, RECEPTION en bas
        self.cw_station = None
        self.cw_hidden = []             # fenêtres réduites pour laisser l'écran CW devant
        # FT8 : WSJT-X en plein écran, piloté à travers le Scope (ft8_bridge.py)
        self.ft8_source = args.source
        self.ft8_proc = None
        self.ft8_tx = False             # émission en cours demandée par WSJT-X
        self.ft8_server = ft8_bridge.RigctlServer(types.SimpleNamespace(
            get_freq=self.ft8_get_freq, set_freq=self.ft8_set_freq,
            get_mode=self.ft8_get_mode, set_mode=self.ft8_set_mode,
            get_ptt=self.ft8_get_ptt, set_ptt=self.ft8_set_ptt), self)
        self.ft8_server.status.connect(lambda t: self.statusBar().showMessage(t, 5000))
        self.ft8_timer = QtCore.QTimer(self)
        self.ft8_timer.timeout.connect(self._ft8_watch)
        self.ft8_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="FT8 : levier en bas = WSJT-X s'ouvre en plein écran "
            "et peut recevoir et émettre en FT8 (fréquence, mode et émission passent "
            "par le Scope), avec la mappemonde des stations entendues derrière ; "
            "en haut = WSJT-X fermé. Clic droit : opacité de WSJT-X.")
        self.ft8_toggle.toggled.connect(self._ft8_toggled)
        self.ft8_toggle.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ft8_toggle.customContextMenuRequested.connect(self._ft8_menu)
        self.ft8_map = Ft8Map()             # mappemonde derrière WSJT-X
        # bouton boule bleue en bas à droite de l'écran FT8 : ferme FT8
        self.ft8_close = BallButton("FERMER\nFT8")
        self.ft8_close.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                                      | QtCore.Qt.WindowStaysOnTopHint
                                      | QtCore.Qt.X11BypassWindowManagerHint)
        self.ft8_close.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.ft8_close.setToolTip("Ferme WSJT-X et la carte, la radio repasse en réception, "
                                  "les fenêtres reviennent")
        self.ft8_hidden = []                # fenêtres rangées pendant FT8
        self.ft8_close.clicked.connect(lambda: self.ft8_toggle.setDown(False))
        self.ft8_opacity = self._ft8_load_opacity()
        # DÉCODEUR RTTY : carte plein écran + texte décodé (rtty_screen.py)
        self.rtty_screen = RttyScreen()
        self.rtty_hidden = []
        self.rtty_prev_decoder = 0
        self.rtty_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="DÉCODEUR RTTY : levier en bas = la radio passe en RTTY "
            "(fréquence RTTY de la bande), écran plein avec la mappemonde, le texte décodé "
            "et un point rouge sur la station pendant qu'elle émet ; en haut = retour.")
        self.rtty_toggle.toggled.connect(self._rtty_toggled)
        self.rtty_close = BallButton("FERMER\nRTTY")
        self.rtty_close.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                                       | QtCore.Qt.WindowStaysOnTopHint
                                       | QtCore.Qt.X11BypassWindowManagerHint)
        self.rtty_close.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.rtty_close.setToolTip("Ferme l'écran RTTY, les fenêtres reviennent")
        self.rtty_close.clicked.connect(lambda: self.rtty_toggle.setDown(False))
        self.rtty_timer = QtCore.QTimer(self)
        self.rtty_timer.timeout.connect(self._rtty_tick)
        # WATERFALL FR : waterfall plein écran + stations françaises (wf_france.py).
        # Levier ON = veille : l'écran s'ouvre tout seul à chaque nouvelle station
        # française ; RETOUR le réduit. Le VFO ne bouge que sur un clic dans l'écran.
        self.fr_screen = WaterfallFrance()
        self.fr_screen.set_audio_source(args.source)    # indicatif dit à la voix
        # REC : vidéo de l'écran + son du trafic (micro, réception, émission)
        self.screen_rec = ScreenRecorder()
        self.screen_rec.changed.connect(lambda on, msg: self.statusBar().showMessage(msg, 8000))
        self.fr_screen.set_recorder(self.screen_rec)
        self.fr_screen.back.connect(self._fr_reduce)
        self.fr_screen.span.connect(self._fr_span)
        self.fr_screen.tune.connect(self._fr_tune)
        self.fr_screen.fine.connect(self._fr_fine)
        self.fr_screen.fine_done.connect(self._fr_voice_calage)
        self.fr_screen.found.connect(self._fr_found)
        self.fr_hidden = []
        self.fr_saved_span = None
        self.fr_full = False                    # WATERFALL FR : bande entière (mode fixe)
        self.fr_full_band = None
        self.fr_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="WATERFALL FR : levier en bas = waterfall plein écran avec "
            "les stations françaises de la bande (RBN, DX Summit, texte décodé, scan QSO FR "
            "par récepteur Internet) ; RETOUR le réduit (la recherche continue, les nouvelles "
            "stations sont signalées en bas du Scope). Dans l'écran : le curseur se colle sur "
            "les signaux, clic = la radio s'y cale. En haut = arrêt. "
            "Clic droit : rouvrir l'écran.")
        self.fr_toggle.toggled.connect(self._fr_toggled)
        self.fr_toggle.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.fr_toggle.customContextMenuRequested.connect(self._fr_open_now)
        self.fr_timer = QtCore.QTimer(self)
        self.fr_timer.timeout.connect(self._fr_tick)
        # FIXE / MOBILE : levier en haut = écran complet, en bas = écran MOBILE
        self.mobile_toggle = ToggleSwitch(
            "FIXE", "MOBILE", tooltip="Levier en haut = FIXE (écran complet habituel), "
            "en bas = MOBILE (écran différent, en cours de création)")
        self.mobile_toggle.toggled.connect(self._mobile_toggled)
        self.mobile_timer = QtCore.QTimer(self)         # écran MOBILE : boutons recopiés
        self.mobile_timer.timeout.connect(self._mobile_sync)
        # DÉMO : la souris devient un gros doigt (demo_finger.py)
        self.demo_finger = DemoFinger()
        self.demo_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="DÉMO : levier en bas = la souris devient un gros doigt "
            "(visible en partage d'écran et en vidéo), le bout du doigt = l'endroit visé, "
            "onde rouge à chaque clic ; en haut = souris normale. "
            "Clic droit : taille du doigt.")
        self.demo_toggle.toggled.connect(self._demo_toggled)
        self.demo_toggle.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.demo_toggle.customContextMenuRequested.connect(self._demo_menu)
        # VOX1, VOX2… : poussoirs ; appui = message en attente de « VOX n » dit au micro
        self.vox_msg_buttons = {}
        for n in VOX_MSG_NUMBERS:
            button = QtWidgets.QPushButton(f"VOX{n}")
            button.setCheckable(True)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.setToolTip(
                f"VOX{n} : appui = ton message vocal n° {n} se met en attente (bouton "
                f"orange clignotant), sans émettre. Il part seulement quand tu dis "
                f"« VOX {n} » au micro : émission du message puis retour immédiat en "
                f"réception. Nouvel appui = annuler. "
                f"Clic droit : enregistrer le message au micro, ou l'écouter.")
            button.clicked.connect(lambda on, n=n: self._vox_msg_arm(n, on))
            button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, n=n: self._vox_msg_menu(n, pos))
            self.vox_msg_buttons[n] = button
        self.vox_msg_armed = set()          # messages en attente de « VOX n »
        # ESSAI : tout comme en vrai, sans émettre ; gardé d'une session à l'autre,
        # actif par défaut (on l'enlève exprès pour émettre pour de vrai)
        self.vox_msg_dry = self._vox_dry_load()
        self.vox_msg_dry_auto = set()       # voix pas apprise : essai à blanc d'office
        self.vox_match_detail = ""          # dernier résultat de reconnaissance
        self.vox_rx_muted = False           # réception coupée pour entendre « VOX n »
        self.vox_seg_time = 0.0
        self.vox_dry_player = None
        self.vox_dry_timer = QtCore.QTimer(self)
        self.vox_dry_timer.timeout.connect(self._vox_dry_check)
        self.vox_msg_sending = None         # n° du message en cours d'émission
        self.vox_msg_rec = None             # (n, parec) pendant l'enregistrement
        self.vox_msg_rec_timer = QtCore.QTimer(self)
        self.vox_msg_rec_timer.setSingleShot(True)
        self.vox_msg_rec_timer.timeout.connect(self._vox_msg_rec_stop)
        self.vox_msg_blink = False
        self.vox_msg_blink_timer = QtCore.QTimer(self)
        self.vox_msg_blink_timer.timeout.connect(self._vox_msg_show)
        self.vox_msg_blink_timer.start(60)     # rythmes calculés sur l'heure
        # DICTÉE : ce qui est dit au micro s'écrit dans le terminal (Claude)
        self.dictee = Dictee()
        self.dictee_state = ""
        self.dictee.state.connect(self._dictee_state)
        self.dictee.done.connect(self._dictee_done)
        self.dictee_button = QtWidgets.QPushButton("DICTÉE")
        self.dictee_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.dictee_button.setStyleSheet(PUSH_YELLOW_3D)
        self.dictee_button.setToolTip(
            "DICTÉE : appuie, parle, puis tais-toi 1,5 s : ta phrase s'écrit dans le "
            "terminal (Claude). Finis par « envoie » pour la valider en plus (Entrée). "
            "Nouvel appui pendant l'écoute = fin tout de suite. Mots mal compris : "
            "dictee-corrections.txt ; vocabulaire : dictee-vocabulaire.txt.")
        self.dictee_button.clicked.connect(self._dictee_click)
        # TRADUCTION : la réception traduite en français, en direct, dans une fenêtre
        self.translator = Translator()
        self.translation_window = None
        self.translate_button = QtWidgets.QPushButton("TRADUC-\nTION")
        self.translate_button.setCheckable(True)
        self.translate_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.translate_button.setStyleSheet(PUSH_YELLOW_3D + "QPushButton { font-size: 7pt; }")
        self.translate_button.setToolTip(
            "TRADUCTION : appui = une fenêtre s'ouvre et traduit en français, en direct, "
            "ce que dit la station reçue (langue reconnue, texte d'origine, français en "
            "gros). Hors ligne ; 5 à 10 s de décalage. Nouvel appui = fermer.")
        self.translate_button.toggled.connect(self._translate_toggled)
        # REC BF : son seul (réception + émission + micro) ; VDO+BF : écran + son
        self.rec_bf = ScreenRecorder(audio_only=True)
        self.rec_bf.changed.connect(lambda on, msg: self.statusBar().showMessage(msg, 8000))
        self.rec_bf_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="REC BF : levier en bas = enregistre le son du trafic "
            "(réception, émission et ton micro), sans l'image, dans le dossier ~/REC BF (REC-BF-date.ogg) ; "
            "en haut = arrêt.")
        self.rec_bf_toggle.toggled.connect(
            lambda down: self._rec_switch(self.rec_bf, self.rec_bf_toggle, down))
        self.rec_bf.changed.connect(
            lambda *_: self.rec_bf_toggle.setDown(self.rec_bf.recording, emit=False))
        self.vdo_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="VDO+BF : levier en bas = vidéo complète de l'écran avec "
            "le son du trafic, dans ~/MUSARDE-date.mkv ; en haut = arrêt (même "
            "enregistreur que les boutons REC vidéo).")
        self.vdo_toggle.toggled.connect(
            lambda down: self._rec_switch(self.screen_rec, self.vdo_toggle, down))
        self.screen_rec.changed.connect(
            lambda *_: self.vdo_toggle.setDown(self.screen_rec.recording, emit=False))
        # LOUPE : lentille ronde qui suit le pointeur (loupe.py)
        self.loupe = Loupe()
        self.loupe_wheel = AltWheel(self.loupe)
        QtWidgets.QApplication.instance().installEventFilter(self.loupe_wheel)
        self.loupe.zoom_changed.connect(
            lambda z: self.statusBar().showMessage(f"Loupe : grossissement × {z}", 2000))
        self.loupe_toggle = ToggleSwitch(
            "OFF", "ON", tooltip="LOUPE : levier en bas = lentille qui suit le pointeur, "
            "réticule rouge sur le pixel visé ; en haut = arrêt. Grossissement : "
            "Alt + molette, ou clic droit sur l'interrupteur (× 2 à × 10).")
        self.loupe_toggle.toggled.connect(self._loupe_toggled)
        self.loupe_toggle.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.loupe_toggle.customContextMenuRequested.connect(self._loupe_menu)
        self.output_toggle = ToggleSwitch(
            "HP PC", "CASQUE", tooltip="Sortie du son du PC : levier en haut = "
            "haut-parleurs du PC, en bas = casque")
        self.volume_knob = VintageKnob(
            88, 150, "%", None, "",
            "Volume du son de la radio sur le PC (0 à 150 %) : glisser, ou molette")
        # GAIN MICRO : volume d'entrée du micro du PC (remplace la liste « Micro » du bas)
        self.mic_knob = ScaleBakelite(
            mic_gain_now() / 15, 88, "", lambda v: f"{round(v * 15)} %",
            "Gain du micro du PC (0 à 150 %) : glisser, ou molette "
            "(Maj+molette = pas de 15 %)")
        self.mic_knob.valueChanged.connect(self.on_mic_knob)
        # NIVEAU COMP : niveau du compresseur de la radio (0 à 10), en bouton rond
        self.comp_round = ScaleBakelite(
            0.0, 88, "", lambda v: f"{v:.1f}".replace(".", ","),
            "Niveau du compresseur de l'IC-7300 (0 à 10 comme sur la radio). "
            "Molette 0,1 · Maj+molette 1 · glisser")
        self.comp_round.valueChanged.connect(
            lambda v: self.on_comp_knob(round(v * 25.5)))
        # rangée PRÉ-BF, VOL PC, NIV, ALC : au-dessus du waterfall (voir plus bas),
        # alignée à gauche ; la place à droite est gardée pour d'autres boutons
        self.knob_bar = QtWidgets.QHBoxLayout()
        self.knob_bar.setSpacing(8)
        self.knob_bar.setContentsMargins(6, 0, 6, 0)
        # chaque bouton avec, juste au-dessus, sa plaque d'aluminium gravée
        # famille RÉGLAGES AUDIO : dans un cadre d'argent, à gauche
        self.audio_bar = QtWidgets.QHBoxLayout()
        self.audio_bar.setSpacing(6)
        audio = ((self.preamp_knob, "PRÉAMPLI BF"), (self.af_knob, "VOLUME PC"),
                 (self.volume_knob, "VOLUME"), (self.af_radio_knob, "AF RADIO"),
                 (self.clean_knob, "FILTRE RX"),
                 (self.mic_knob, "GAIN MICRO"), (self.level_knob, "NIVEAU TX"),
                 (self.alc_knob, "ALC"), (self.comp_round, "NIVEAU COMP"),
                 (self.mute_toggle, "MUET"), (self.output_toggle, "ÉCOUTE"))
        others = ((self.view_toggle, "AFFICHAGE"),
                  (self.precision_toggle, "PRÉCISION"),
                  (self.loupe_toggle, "LOUPE"),
                  (self.message_toggle, "MESSAGE"),
                  (self.ft8_toggle, "FT8"),
                  (self.rtty_toggle, "DÉCODEUR RTTY"),
                  (self.fr_toggle, "WATERFALL FR"),
                  (self.demo_toggle, "DÉMO"))
        # 2e ligne d'interrupteurs, sous la première : les nouveaux s'ajoutent ici
        others2 = ((self.rec_bf_toggle, "REC BF"),
                   (self.vdo_toggle, "VDO+BF"),
                   *((self.vox_msg_buttons[n], f"VOX{n}") for n in VOX_MSG_NUMBERS),
                   (self.dictee_button, "DICTÉE"),
                   (self.translate_button, "TRADUCTION"),
                   (self.mobile_toggle, "FIXE / MOBILE"))
        # volumes : réglage relatif, doux et précis (glisser haut/bas, Ctrl = très fin)
        for knob in (self.volume_knob, self.af_knob, self.af_radio_knob, self.preamp_knob):
            knob.fine = True
        # 80 px par bouton (au lieu de 88) : la rangée tient dans la largeur de l'écran
        col_px = 80
        SWITCH_PX = 60
        self.switch_row1 = QtWidgets.QHBoxLayout()
        self.switch_row1.setSpacing(4)          # serré : la fenêtre tient dans l'écran
        self.switch_row2 = QtWidgets.QHBoxLayout()
        self.switch_row2.setSpacing(4)          # serré : la fenêtre tient dans l'écran
        for bar, items in ((self.audio_bar, audio), (self.switch_row1, others),
                           (self.switch_row2, others2)):
            for knob, name in items:
                if knob.width() > col_px:
                    knob.setFixedSize(col_px, round(knob.height() * col_px / knob.width()))
                if bar is not self.audio_bar:   # 2 lignes d'interrupteurs : leviers plus petits
                    knob.setFixedSize(SWITCH_PX, SWITCH_PX)
                col = QtWidgets.QVBoxLayout()
                col.setSpacing(1)
                col.addWidget(NamePlate(name, col_px), 0, QtCore.Qt.AlignHCenter)
                col.addWidget(knob, 0, QtCore.Qt.AlignHCenter)
                bar.addLayout(col)
            if bar is self.audio_bar:
                self.audio_frame = SilverFrame(self.audio_bar, "RÉGLAGES AUDIO")
                self.knob_bar.addWidget(self.audio_frame)
                self.knob_bar.addSpacing(6)
        self.switch_row1.addStretch()
        self.switch_row2.addStretch()
        switch_rows = QtWidgets.QVBoxLayout()
        switch_rows.setSpacing(2)
        switch_rows.addLayout(self.switch_row1)
        switch_rows.addLayout(self.switch_row2)
        self.knob_bar.addLayout(switch_rows, stretch=1)
        s_col.addStretch()
        meters.addLayout(s_col)
        self.s_col = s_col                      # le texte décodé s'y place (sous le S-mètre)
        meters.addSpacing(12)
        # Bargraphs d'émission
        tx_bars = QtWidgets.QGridLayout()
        swr_ticks = [(raw, f"{swr:g}") for raw, swr in SWR_POINTS[:-1]] + [(255, "∞")]
        self.swr_meter = BarGraph(0, 255, swr_ticks, red_from=80, segments=60)
        comp_ticks = [(v, f"{v}") for v in (0, 10, 20, 30)]
        self.comp_meter = BarGraph(0, 30, comp_ticks, red_from=20, segments=24)
        alc_ticks = [(v, f"{v}") for v in (0, 10, 25, 50, 100, 150)]
        self.alc_meter = BarGraph(0, 150, alc_ticks, red_from=100, segments=24,
                                  curve=0.5, fall=200)
        self.alc_meter.setToolTip("ALC en % de sa zone : rester sous 100")
        po_ticks = [(v, f"{v}") for v in (0, 5, 25, 50, 100)]
        self.po_meter = BarGraph(0, 110, po_ticks, red_from=90, segments=24, hold=4.0,
                                 curve=0.5, fall=80)
        self.po_meter.setToolTip("Puissance de sortie en watts (repère jaune = crête des 4 dernières secondes)")
        self.po_value = QtWidgets.QLabel("")
        self.po_peak_w = 0.0
        self.po_peak_t = 0.0
        id_ticks = [(v, f"{v}") for v in (0, 5, 10, 15, 20, 25)]
        self.id_meter = BarGraph(0, 25, id_ticks, red_from=22, segments=24)
        self.id_meter.setToolTip("Courant consommé par l'ampli (Id)")
        self.swr_value = QtWidgets.QLabel("")
        self.comp_value = QtWidgets.QLabel("")
        self.alc_value = QtWidgets.QLabel("")
        self.id_value = QtWidgets.QLabel("")
        # RX fin en haut ; dessous, pour le moment, le galva d'émission remplace
        # les barres Po / ROS / COMP / ALC / Id (gardées en mémoire, non affichées)
        for name, meter, value in (("Po W", self.po_meter, self.po_value),
                                   ("ROS", self.swr_meter, self.swr_value),
                                   ("COMP dB", self.comp_meter, self.comp_value),
                                   ("ALC %", self.alc_meter, self.alc_value),
                                   ("Id", self.id_meter, self.id_value)):
            value.setMinimumWidth(60)
            value.setStyleSheet("font: bold 12pt monospace;")
        # barre RX fin juste sous le S-mètre, à sa largeur
        rx_box = QtWidgets.QWidget()
        rx_box.setFixedWidth(self.s_meter.width())
        rx_row = QtWidgets.QHBoxLayout(rx_box)
        rx_row.setContentsMargins(0, 0, 0, 0)
        rx_row.setSpacing(4)
        self.rx_fine_value.setMinimumWidth(48)
        self.rx_fine_value.setStyleSheet("font: bold 10pt monospace;")
        rx_row.addWidget(self.rx_fine, stretch=1)
        rx_row.addWidget(self.rx_fine_value)
        s_col.insertWidget(1, rx_box)
        # même barre pour le ROS, juste dessous (bouge en émission)
        swr_box = QtWidgets.QWidget()
        swr_box.setFixedWidth(self.s_meter.width())
        swr_row = QtWidgets.QHBoxLayout(swr_box)
        swr_row.setContentsMargins(0, 0, 0, 0)
        swr_row.setSpacing(4)
        self.swr_value.setMinimumWidth(48)
        self.swr_value.setStyleSheet("font: bold 10pt monospace;")
        swr_row.addWidget(self.swr_meter, stretch=1)
        swr_row.addWidget(self.swr_value)
        # petite LED rouge d'alarme : clignote très vite si le ROS dépasse 2
        self.swr_led = QtWidgets.QLabel()
        self.swr_led.setFixedSize(12, 12)
        self.swr_led.setToolTip("Alarme ROS : clignote en rouge si le ROS dépasse 2")
        swr_row.addWidget(self.swr_led)
        swr_box.setFixedWidth(self.s_meter.width() + 16)
        # (barre ROS sous le S-mètre retirée : micro-galva ROS au-dessus du POWER).
        # Gardée en mémoire, invisible : sinon Qt la détruit (et swr_meter avec)
        self.swr_box = swr_box
        swr_box.hide()
        self.swr_galva = SwrMicroGalva(height=SWR_GALVA_PX)
        self.swr_alarm = False
        self.swr_blink = False
        self.swr_timer = QtCore.QTimer(self)
        self.swr_timer.timeout.connect(self._swr_led_tick)
        self.swr_timer.start(50)            # 10 clignotements par seconde
        self._swr_led_paint(False)
        # deux galvas ronds côte à côte + gros bouton rouge d'émission
        self.tx_galva = TxGalva()
        self.red_button = RedButton("", size=67)            # sans inscription
        self.red_button.setToolTip("Émission : appui = la radio émet, nouvel appui = "
                                   "réception (comme le bouton ÉMETTRE)")
        # à droite du S-mètre : les deux galvas côte à côte, le bouton dessous
        tx_panel = QtWidgets.QVBoxLayout()
        tx_panel.setSpacing(4)
        self.tx_galva_row = QtWidgets.QHBoxLayout()    # Po W | COMP | CALE (ajouté plus bas)
        self.tx_galva_row.setSpacing(6)
        self.tx_galva_row.addWidget(self.tx_galva)
        tx_panel.addLayout(self.tx_galva_row)
        # oscilloscope vintage : forme d'onde de la voix au micro
        self.voice_scope = VoiceScope()
        tx_panel.addSpacing(46)                 # descendu : juste au-dessus des potentiomètres
        tx_panel.addWidget(self.voice_scope, 0, QtCore.Qt.AlignHCenter)
        tx_panel.addStretch()
        meters.insertSpacing(1, 10)             # [S-mètre, espace, galvas, …]
        meters.insertLayout(2, tx_panel)
        # VFO au centre, en bas de l'en-tête (juste au-dessus du waterfall)
        meters.addStretch(1)                    # VFO entre les galvas et POWER
        self.vfo_slot = QtWidgets.QVBoxLayout()
        meters.addLayout(self.vfo_slot)
        # à droite du VFO (décalé à gauche) : commutateur de bandes rotatif vintage,
        # dans la grille du VFO (même axe horizontal que le centre du VFO)
        self.band_selector = BandSelector(BAND_SEL_PX)
        self.band_selector.changed.connect(self._band_selector_changed)
        meters.addStretch(1)
        # à droite : galva POWER, jumeau du S-mètre
        self.power_meter = VintagePowerMeter()
        power_col = QtWidgets.QVBoxLayout()
        power_col.setSpacing(1)
        self.swr_galva.setFixedWidth(self.power_meter.width())   # même largeur que POWER
        self.swr_title = SwrTitle(self.power_meter.width())       # « R . O . S » au-dessus
        power_col.addWidget(self.swr_title)
        power_col.addWidget(self.swr_galva)
        power_col.addWidget(self.power_meter)
        # sous le galva POWER : bouton argent de réglage de la puissance (W)
        self.power_knob = PowerKnob(KNOB_POWER_PX)   # plus petit : place pour le micro-galva ROS
        self.power_knob.setEnabled(False)       # activé quand la radio répond
        power_col.addSpacing(0)
        # à droite du bouton de puissance : sélecteur rotatif FONCTION (OFF, ZOOM, …)
        self.function_selector = FunctionSelector(("OFF", "ZOOM", "SSTV", "", ""),
                                                  scale=FUNC_SCALE)
        self.function_selector.changed.connect(self.on_function)
        self.function_screen = FunctionScreen()   # fonction enclenchée = plein écran
        self.function_screen.back.connect(lambda: self.function_selector.set_index(0))
        self.sstv_view = None
        self.zoom_saved_span = None
        knob_and_sel = QtWidgets.QHBoxLayout()
        knob_and_sel.setSpacing(0)
        knob_and_sel.addStretch()
        power_knob_col = QtWidgets.QVBoxLayout()
        power_knob_col.setSpacing(1)
        power_knob_col.addWidget(NamePlate("POWER", 110), 0, QtCore.Qt.AlignHCenter)
        power_knob_col.addWidget(self.power_knob, 0, QtCore.Qt.AlignHCenter)
        knob_and_sel.addLayout(power_knob_col)
        knob_and_sel.addWidget(self.function_selector, 0, QtCore.Qt.AlignVCenter)
        knob_and_sel.addStretch()
        power_col.addLayout(knob_and_sel)
        power_col.addStretch()
        meters.addLayout(power_col)
        left.addLayout(meters)
        left.addStretch()

        # VFO
        self.active_vfo = None              # la radio ne dit pas lequel est actif
        vfo = QtWidgets.QGridLayout()
        self.vfo_label = QtWidgets.QLabel("VFO ?")
        self.vfo_label.setAlignment(QtCore.Qt.AlignCenter)
        self.vfo_label.setStyleSheet("font: bold 14pt; color: #4fc3f7;")
        self.knob = TuningKnob()
        self.knob.tuned.connect(self.on_knob_tuned)     # pas choisi par l'interrupteur
        # interrupteur à levier : pas du bouton VFO 50 kHz (gauche) / 100 kHz (droite)
        self.vfo_step_switch = LeverSwitch("50 kHz", "100 kHz")
        self.vfo_step_switch.setToolTip("Pas du bouton VFO : 50 kHz ou 100 kHz")
        self.led_100k = BlueLed()       # au-dessus : 100 kHz (fixe)
        self.led_50k = BlueLed()        # dessous : 50 kHz (clignote)
        self.led_100k.setToolTip("Pas de 100 kHz choisi")
        self.led_50k.setToolTip("Pas de 50 kHz choisi")
        self.vfo_step_switch.toggled.connect(self._vfo_step_leds)
        # plaque argentée à droite du VFO : 4 interrupteurs de pas fin, un seul actif
        self.fine_plate = RustPlate()           # tôle rouillée militaire
        plate_grid = QtWidgets.QGridLayout(self.fine_plate)
        plate_grid.setContentsMargins(14, 12, 10, 12)
        plate_grid.setVerticalSpacing(3)           # inscription juste au-dessus du levier
        plate_grid.setHorizontalSpacing(4)
        self.fine_switches = []             # (pas en Hz, interrupteur, LED)
        for row, (hz, text) in enumerate(((1, "1 Hz"), (10, "10 Hz"),
                                          (100, "100 Hz"), (1000, "1 kHz"))):
            name = QtWidgets.QLabel(text)           # inscription en relief, au-dessus
            name.setAlignment(QtCore.Qt.AlignCenter)
            name.setStyleSheet("font: 900 10pt 'DejaVu Sans Condensed'; color: #1a1206; "
                               "letter-spacing: 1px; background: transparent;")
            relief = QtWidgets.QGraphicsDropShadowEffect(name)
            relief.setOffset(1, 1)                  # pochoir noir, liseré clair
            relief.setBlurRadius(0)
            relief.setColor(QtGui.QColor(255, 240, 215, 200))
            name.setGraphicsEffect(relief)
            sw = MilitaryLever("", "", width=84, height=34)   # levier acier gauche ↔ droite
            sw.setToolTip(f"Pas du bouton VFO : {text} (levier à droite = enclenché)")
            led = AmberLed(size=20, period_ms=70)       # voyant ambre, flash très rapide
            plate_grid.addWidget(name, 2 * row, 0, QtCore.Qt.AlignHCenter)   # pile au-dessus du levier
            plate_grid.addWidget(sw, 2 * row + 1, 0)
            plate_grid.addWidget(led, 2 * row + 1, 1)
            sw.toggled.connect(lambda on, h=hz: self._fine_step_toggled(h, on))
            self.fine_switches.append((hz, sw, led))
        self._vfo_step_leds(False)
        self.other_label = QtWidgets.QLabel("")
        self.other_label.setAlignment(QtCore.Qt.AlignCenter)
        self.other_label.setStyleSheet("font: 11pt monospace; color: #90a4ae;")
        self.other_label.setToolTip("L'autre VFO")
        self.vfo_label.hide()               # inscription « VFO ? » retirée (gardée en mémoire)
        vfo.addWidget(self.knob, 1, 0, 1, 4, QtCore.Qt.AlignCenter)
        vfo.addWidget(self.fine_plate, 1, 4, QtCore.Qt.AlignVCenter)   # à droite du VFO
        vfo.setColumnMinimumWidth(5, BAND_SEL_GAP)
        vfo.addWidget(self.band_selector, 1, 6, QtCore.Qt.AlignVCenter)  # centré sur le VFO
        step_row = QtWidgets.QHBoxLayout()
        step_row.setSpacing(4)
        step_row.addStretch()
        step_row.addWidget(self.led_50k)            # côté gauche = 50 kHz
        step_row.addWidget(self.vfo_step_switch)
        step_row.addWidget(self.led_100k)           # côté droit = 100 kHz
        step_row.addStretch()
        # interrupteur 50/100 kHz retiré à la demande (objets gardés, non affichés)
        for widget in (self.vfo_step_switch, self.led_50k, self.led_100k):
            widget.hide()
        buttons = [("A", "Passer sur le VFO A", 0x00),
                   ("B", "Passer sur le VFO B", 0x01),
                   ("A/B", "Basculer entre VFO A et B", 0xB0),
                   ("A=B", "Copier le VFO actif dans l'autre", 0xA0)]
        self.vfo_buttons = []           # placés dans la rangée d'outils, en bas
        for col, (text, tip, code) in enumerate(buttons):
            button = QtWidgets.QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _, c=code: self.on_vfo_operation(c))
            self.vfo_buttons.append(button)
        vfo.addWidget(self.other_label, 3, 0, 1, 4)
        self.tune_button = QtWidgets.QPushButton("TUNE")
        self.tune_button.setToolTip("Accorde l'antenne avec la boîte d'accord "
                                    "interne. La radio émet une porteuse.")
        self.tune_button.clicked.connect(self.on_tune)
        self.atu_button = QtWidgets.QPushButton("ATU")
        self.atu_button.setCheckable(True)
        self.atu_button.setToolTip("Boîte d'accord interne en service")
        self.atu_button.clicked.connect(self.on_atu)
        self.onoff_button = QtWidgets.QPushButton("ON / OFF")
        self.onoff_button.setToolTip("Allume ou éteint l'IC-7300")
        self.onoff_button.setStyleSheet(PUSH_3D)
        self.onoff_button.clicked.connect(self.on_onoff)   # placé près du calage
        self.radio_on = None

        # Bandes : la radio retrouve la dernière fréquence utilisée sur la bande
        try:
            with open(BANDS_FILE) as f:
                self.band_memory = json.load(f)
        except (OSError, ValueError):
            self.band_memory = {}
        bands = QtWidgets.QGridLayout()
        bands.setSpacing(0)                     # baguette de laiton continue
        self.band_buttons = {}
        for i, (name, low, high, _, _) in enumerate(BANDS):
            button = BandKey(name)      # touche ivoire + voyant ambre dessous
            button.setToolTip(f"{low / 1e6:g} – {high / 1e6:g} MHz")
            button.clicked.connect(lambda _, n=name: self.on_band(n))
            bands.addWidget(button, 0, i)
            self.band_buttons[name] = button

        # Boutons de mode, même style que les bandes
        mode_line = QtWidgets.QGridLayout()     # touches vintage, au-dessus du waterfall
        mode_line.setSpacing(0)                 # baguette de laiton continue
        modes = QtWidgets.QGridLayout()         # calage BLU, en haut à droite
        modes.setSpacing(4)
        self.mode_buttons = {}
        for i, name in enumerate(MODE_NAMES):
            button = BandKey(name)      # même touche ivoire + voyant que les bandes
            button.clicked.connect(lambda _, n=name: self.on_mode_button(n))
            mode_line.addWidget(button, 0, i)
            self.mode_buttons[name] = button
        # Calage automatique BLU et son vu-mètre
        rows = 0
        self.ssb_meter = SsbMeterSmall()     # placé à côté du galva COMP
        self.ssb_auto = QtWidgets.QPushButton("CALAGE AUTO BLU")
        self.ssb_auto.setCheckable(True)
        self.ssb_auto.setChecked(True)
        self.ssb_auto.setStyleSheet(PUSH_3D)
        self.ssb_auto.setToolTip("En LSB/USB, recale la radio sur la voix du "
                                 "correspondant (quelques secondes de voix)")
        self.ssb_auto.toggled.connect(lambda _: self._update_ssb())
        self.ssb_auto.toggled.connect(
            lambda on: on and hasattr(self, "detect_timer") and self.detect_timer.start(0))
        # appui sur CALAGE AUTO BLU : rattrapage du correspondant le plus proche
        self.ssb_pull_until = 0.0
        self.ssb_auto.toggled.connect(self._start_pull)
        # bouton poussoir : choix automatique de LSB/USB (voyant vert) ou
        # choix libre des modes à la main (voyant rouge)
        self.sideband_button = QtWidgets.QPushButton("AUTO LSB/USB")
        self.sideband_button.setCheckable(True)
        self.sideband_button.setToolTip(
            "Enfoncé (vert) : le programme choisit LSB ou USB tout seul (usage "
            "de la bande, puis écoute de la voix) · relevé (rouge) : choix libre")
        self.sideband_button.setStyleSheet(PUSH_3D)
        self.sideband_led = PlainLed("#c62828")
        self.sideband_button.toggled.connect(self.on_sideband_auto)
        push = QtWidgets.QVBoxLayout()
        push.addStretch()
        push.addWidget(self.sideband_led, 0, QtCore.Qt.AlignCenter)
        push.addStretch()
        meter_row = QtWidgets.QHBoxLayout()
        meter_row.addLayout(push)
        self.ssb_led = SsbLed(self.ssb_meter)   # voyant du calage, à l'ancienne place du galva
        self.tx_galva_row.addWidget(self.ssb_meter)
        self.tx_galva_row.addStretch()               # les galvas restent serrés à gauche
        modes.addLayout(meter_row, rows, 0, 1, 2)
        ssb_row = QtWidgets.QHBoxLayout()
        ssb_row.addStretch()
        # sifflement d'hétérodyne pendant la recherche, comme jadis
        self.whistle = Whistle()
        self.radio_cw_pitch = 600.0     # relu dans la radio (CI-V 0x14 0x09)
        self.cw_note = None             # note mesurée de la station CW
        self.ssb_estimate = None        # écart BLU mesuré par le calage
        # bouton poussoir marche/arrêt du sifflement (la recherche continue)
        self.whistle_check = QtWidgets.QPushButton()
        self.whistle_check.setCheckable(True)
        self.whistle_check.setChecked(False)    # muet au départ : seulement sur appui
        self.whistle_check.setStyleSheet(PUSH_3D)
        self.whistle_check.setToolTip("Son aigu de recherche : marche / arrêt. "
                                      "Ne change rien à la recherche elle-même.")
        self.whistle_check.toggled.connect(self.on_whistle_toggled)
        self._whistle_text(False)
        self.whistle_timer = QtCore.QTimer(self)
        self.whistle_timer.timeout.connect(self._update_whistle)
        self.whistle_timer.start(30)
        # recherche automatique d'un QSO en français, signal fort
        self.hunt_button = QtWidgets.QPushButton("CHERCHER QSO FR")
        self.hunt_button.setCheckable(True)
        # fond jaune au repos ; vert (comme tout bouton actif) pendant la recherche
        self.hunt_style = (
            PUSH_3D + "QPushButton:!checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
              " stop:0 #fff6c0, stop:0.2 #ffe066, stop:0.6 #f5c400, stop:1 #a88400); }"
              "QPushButton:!checked:hover { background: qlineargradient(x1:0, y1:0,"
              " x2:0, y2:1, stop:0 #fff9d6, stop:0.2 #ffe680, stop:0.6 #ffd21a,"
              " stop:1 #b89200); }")
        self.hunt_button.setStyleSheet(self.hunt_style)
        # pendant la recherche : clignote vert vif / vert sombre
        self.hunt_blink = False
        self.hunt_timer = QtCore.QTimer(self)
        self.hunt_timer.timeout.connect(self._blink_hunt)
        self.hunt_button.toggled.connect(self._hunt_blinking)
        self.hunt_button.setToolTip(
            "Parcourt la portion phonie de la bande, écoute les signaux forts "
            "et s'arrête sur le premier QSO en français. Nouvel appui : QSO "
            "français suivant. Recliquer pendant la recherche pour l'arrêter.")
        self.hunt_button.toggled.connect(self.on_hunt_toggled)
        # QSO français trouvé : bouton rouge clignotant pour y rester
        self.stay_button = QtWidgets.QPushButton("RESTER ICI")
        self.stay_button.setToolTip("Arrête la recherche et reste sur ce QSO en français")
        self.stay_button.clicked.connect(
            lambda: self.scanner.keep() if self.scanner.active else self.hunter.keep())
        self.stay_button.setVisible(False)
        self.stay_blink = False
        self.stay_timer = QtCore.QTimer(self)
        self.stay_timer.timeout.connect(self._blink_stay)

        self.hunter = QsoHunter(self)
        self.hunter.status.connect(self.on_hunt_status)
        self.hunter.heard.connect(self.on_station_heard)
        self.hunter.finished.connect(self.on_hunt_finished)
        self.hunter.found.connect(lambda hz, text: QtWidgets.QApplication.beep())
        self.hunter.holding.connect(self.on_hunt_holding)
        ssb_row.addStretch()
        modes.addLayout(ssb_row, rows + 1, 0, 1, 2)
        # œil magique vert, en phase avec l'aiguille du calage
        self.magic_eye = MagicEye(self.ssb_meter)
        # en haut à droite : seulement le voyant vert rond (œil magique) ;
        # les petites LED (AUTO LSB/USB, calage) sont gardées mais non affichées
        self.ssb_led.hide()
        self.sideband_led.hide()
        # en haut à droite : le gros bouton vert RX / rouge TX (œil magique masqué)
        self.magic_eye.hide()
        modes.addWidget(self.red_button, rows, 0, 1, 2, QtCore.Qt.AlignHCenter)
        # sous le gros bouton vert, à droite de FONCTION : poussoir TUNE vintage
        self.tune_plate = PushPlate(
            "TUNE", tooltip="Accorde l'antenne avec la boîte d'accord interne. "
            "La radio émet une porteuse (voyant ambre pendant l'accord).")
        self.tune_plate.clicked.connect(self.on_tune)
        tune_col = QtWidgets.QVBoxLayout()          # descendu : dans l'axe de FONCTION
        tune_col.setContentsMargins(0, 0, 0, 0)
        # arrêt d'urgence : champignon rouge juste sous le gros bouton vert
        self.emergency_button = EmergencyButton(EMERGENCY_PX)
        self.emergency_button.pressed.connect(self.on_emergency)
        tune_col.addSpacing(EMERGENCY_GAP)
        tune_col.addWidget(self.emergency_button, 0, QtCore.Qt.AlignHCenter)
        tune_col.addSpacing(EMERGENCY_GAP)
        tune_col.addWidget(self.tune_plate, 0, QtCore.Qt.AlignHCenter)
        self.tune_col = tune_col                    # le bouton EMISSION s'y ajoute plus bas
        modes.addLayout(tune_col, rows + 2, 0, 1, 2, QtCore.Qt.AlignHCenter)
        modes.setRowStretch(rows + 4, 1)

        header = QtWidgets.QHBoxLayout()
        header.addLayout(left, stretch=1)
        header.addSpacing(10)
        self.vfo_slot.addStretch()
        self.vfo_slot.addLayout(vfo)            # (voir plus haut : au centre)
        header.addSpacing(6)
        header.addLayout(modes)
        layout.addLayout(header)

        # Spectre et waterfall
        graphics = pg.GraphicsLayoutWidget()
        self.spec_plot = graphics.addPlot(row=0, col=0)
        self.spec_plot.setYRange(-130, 0, padding=0)
        self.spec_plot.setMouseEnabled(x=False, y=False)
        self.spec_plot.showGrid(x=True, y=True, alpha=0.25)
        self.spec_plot.setLabel("left", "dBFS")
        self.spec_plot.hideButtons()
        self.spec_curve = self.spec_plot.plot(
            pen=pg.mkPen("#4fc3f7", width=1), fillLevel=-140,
            brush=(79, 195, 247, 60))
        self.wf_plot = graphics.addPlot(row=1, col=0)
        self.wf_plot.setXLink(self.spec_plot)
        self.wf_plot.setMouseEnabled(x=False, y=False)
        self.wf_plot.hideAxis("left")
        self.wf_plot.invertY(True)
        self.wf_plot.hideButtons()
        self.wf_image = pg.ImageItem()
        self.wf_image.setLookupTable(
            pg.colormap.get("inferno").getLookupTable(nPts=256))
        self.wf_plot.addItem(self.wf_image)
        graphics.ci.layout.setRowStretchFactor(0, 1)
        graphics.ci.layout.setRowStretchFactor(1, 4)     # waterfall bien haut
        self.cursor_lines = []
        self.tuned_lines = []
        self.passbands = []
        for plot in (self.spec_plot, self.wf_plot):
            line = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffffff80"))
            line.setVisible(False)
            plot.addItem(line, ignoreBounds=True)
            self.cursor_lines.append(line)
            band = pg.LinearRegionItem(movable=False, brush=(255, 213, 74, 40),
                                       pen=pg.mkPen(None))
            plot.addItem(band, ignoreBounds=True)
            self.passbands.append(band)
            tuned = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffd54a", width=1))
            plot.addItem(tuned, ignoreBounds=True)
            self.tuned_lines.append(tuned)
        self.pitch_lines = []
        for plot in (self.spec_plot, self.wf_plot):
            line = pg.InfiniteLine(angle=90, pen=pg.mkPen("#3ddc84", width=1,
                                                          style=QtCore.Qt.DashLine))
            line.setVisible(False)
            plot.addItem(line, ignoreBounds=True)
            self.pitch_lines.append(line)
        graphics.scene().sigMouseMoved.connect(self.on_mouse_moved)
        graphics.scene().sigMouseClicked.connect(self.on_mouse_clicked)
        # molette : change la fréquence ; glisser en vue RF : déplace la bande
        self.drag = None                # (x de départ, kHz par pixel, fréquence)
        self.dragged = False
        graphics.viewport().installEventFilter(self)
        graphics.setMinimumHeight(50)        # spectre + waterfall toujours visibles (gros VFO)
        # touches de bande vintage : sous le waterfall ; au-dessus, la rangée de boutons
        band_top = QtWidgets.QHBoxLayout()          # HP PC à gauche des bandes
        band_top.setSpacing(4)
        band_top.addWidget(self.preamp_box)
        keys = QtWidgets.QVBoxLayout()              # bandes et modes : un seul cadre
        keys.setSpacing(0)
        # rangée des touches de bandes retirée : le commutateur rotatif la remplace
        # (touches gardées en mémoire, cachées : le reste du code s'en sert)
        for button in self.band_buttons.values():
            button.hide()
        self.bands_hidden_widget = QtWidgets.QWidget()
        self.bands_hidden_widget.setLayout(bands)
        self.bands_hidden_widget.hide()
        keys.addLayout(mode_line)
        band_top.addWidget(PanelFrame(keys), stretch=1)
        layout.addLayout(self.knob_bar)
        layout.addWidget(graphics, stretch=1)
        self.graphics = graphics                # prêté à l'écran plein cadre (ZOOM)
        self.main_layout = layout
        self.graphics_index = layout.indexOf(graphics)
        layout.addLayout(band_top)
        # tout ce qui est sous le waterfall : un seul bloc, masquable d'un coup
        self.below = QtWidgets.QWidget()
        below = QtWidgets.QVBoxLayout(self.below)
        below.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.below)
        # préampli BF entre le waterfall et les bandes
        # boutons de bandes et de modes, en ligne sous le waterfall
        band_mode = QtWidgets.QVBoxLayout()
        band_mode.setSpacing(0)
        # (HP PC, bandes et modes sont maintenant au-dessus du waterfall)
        # tous les autres boutons, même format, dans une 3e rangée encadrée
        tools = QtWidgets.QGridLayout()
        tools.setSpacing(4)
        for button in self.vfo_buttons + [self.tune_button]:
            button.setStyleSheet(PUSH_3D)
        self.atu_button.setStyleSheet(PUSH_3D_MODE)
        for col, button in enumerate(self.vfo_buttons + [
                self.atu_button, self.sideband_button, self.ssb_auto,
                self.hunt_button, self.whistle_check, self.onoff_button,
                self.stay_button]):
            button.setMinimumWidth(58)
            tools.addWidget(button, 0, col)
        below.addWidget(PanelFrame(tools))
        # 4e rangée encadrée : filtres (RM Noise, et d'autres plus tard)
        extras = QtWidgets.QGridLayout()
        extras.setSpacing(4)
        self.rmnoise_button = QtWidgets.QPushButton("RM NOISE")
        self.rmnoise_button.setCheckable(True)
        self.rmnoise_button.setMinimumWidth(58)
        self.rmnoise_button.setStyleSheet(
            PUSH_3D + "QPushButton:!checked { color: #2a1200; background: qlineargradient("
            "x1:0, y1:0, x2:0, y2:1, stop:0 #ffd9a8, stop:0.2 #ffad4d, stop:0.6 #f57c00,"
            " stop:1 #a34f00); }")
        self.rmnoise_button.setToolTip("Filtre RM Noise à 100 % sur le son de la radio "
                                       "(le son direct est coupé). Recliquer pour arrêter.")
        self.rmnoise_button.toggled.connect(self.on_rmnoise)
        extras.addWidget(self.rmnoise_button, 0, 0)
        # RNNoise : filtre local, sans compte (en attendant RM Noise)
        self.rnnoise_button = QtWidgets.QPushButton("RNNOISE")
        self.rnnoise_button.setCheckable(True)
        self.rnnoise_button.setMinimumWidth(58)
        self.rnnoise_button.setStyleSheet(PUSH_3D)
        self.rnnoise_button.setToolTip("Filtre anti-bruit RNNoise (sur ce PC, sans compte) "
                                       "sur le son de la radio. Recliquer pour l'arrêter.")
        self.rnnoise_button.toggled.connect(self.on_rnnoise)
        self.rnn_mix = RNN_MIX_WEAK
        self.s_raw_avg = 0.0
        self.rnn_timer = QtCore.QTimer(self)
        self.rnn_timer.timeout.connect(self._update_rnn_mix)
        extras.addWidget(self.rnnoise_button, 0, 1)
        self.cw_button = QtWidgets.QPushButton("DÉCODAGE CW")
        self.cw_button.setCheckable(True)
        self.cw_button.setMinimumWidth(58)
        self.cw_button.setStyleSheet(PUSH_3D)
        self.cw_button.setToolTip("Balaye la portion CW de la bande et décode chaque "
                                  "signal 20 s, dans une grande fenêtre. Recliquer pour arrêter.")
        self.cw_button.toggled.connect(self.on_cw_toggled)
        extras.addWidget(self.cw_button, 0, 2)
        # SCAN : arrêt 10 s sur chaque station BLU, clignote tant qu'il tourne
        self.scan_button = QtWidgets.QPushButton("SCAN")
        self.scan_button.setCheckable(True)
        self.scan_button.setMinimumWidth(58)
        self.scan_button.setStyleSheet(PUSH_3D)
        self.scan_button.setToolTip("Balaye la bande et s'arrête 10 s sur chaque station "
                                    "LSB/USB détectée. Recliquer pour arrêter.")
        self.scan_button.toggled.connect(self.on_scan_toggled)
        extras.addWidget(self.scan_button, 0, 3)
        # CONSOLE : terminal gardé visible par-dessus Scope (F12 aussi)
        self.console_button = QtWidgets.QPushButton("CONSOLE")
        self.console_button.setCheckable(True)
        self.console_button.setMinimumWidth(58)
        self.console_button.setStyleSheet(PUSH_3D)
        self.console_button.setToolTip("Garde le terminal visible par-dessus Scope "
                                       "(en ouvre un s'il n'y en a pas). Recliquer ou F12 "
                                       "pour le renvoyer derrière.")
        self.console_button.toggled.connect(self.on_console_toggled)
        extras.addWidget(self.console_button, 0, 4)
        # RECH MAN : après un scan, revenir pas à pas sur les stations entendues
        # (flèche gauche = -1, -2… ; flèche droite = +1, +2…), 20 s sur chacune
        self.manual_prev = SignButton("−", "#000000", left=True)
        self.manual_prev.setStyleSheet(PUSH_3D + GLUE_LEFT)
        self.manual_prev.setToolTip("Station entendue précédente (-1, -2…), arrêt 20 s")
        self.manual_prev.clicked.connect(lambda: self.on_manual_step(-1))
        self.manual_next = SignButton("+", "#e00000", left=False)
        self.manual_next.setStyleSheet(PUSH_3D + GLUE_RIGHT)
        self.manual_next.setToolTip("Station entendue suivante (+1, +2…), arrêt 20 s")
        self.manual_next.clicked.connect(lambda: self.on_manual_step(1))
        # au milieu : plaque d'affichage (clignote et décompte pendant l'arrêt)
        self.manual_button = QtWidgets.QPushButton(RECH_MAN_TEXT)
        self.manual_button.setCheckable(True)
        self.manual_button.setMinimumWidth(110)
        self.manual_button.setStyleSheet(PUSH_3D + GLUE_MID)
        self.manual_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.manual_button.clicked.connect(self.on_manual_stay)
        self.manual_button.setToolTip("Après un SCAN : − = station précédente, "
                                      "+ = station suivante, 20 s sur chacune. "
                                      "Appui ici : on reste sur la fréquence écoutée "
                                      "(arrêt du scan et de la recherche).")
        manual_box = QtWidgets.QWidget()
        manual_row = QtWidgets.QHBoxLayout(manual_box)
        manual_row.setContentsMargins(0, 0, 0, 0)
        manual_row.setSpacing(0)
        manual_row.addWidget(self.manual_prev)
        manual_row.addWidget(self.manual_button)
        manual_row.addWidget(self.manual_next)
        extras.addWidget(manual_box, 0, 5)
        # PADDLE CLAVIER : Ctrl gauche = points, Ctrl droit = traits
        self.paddle = KeyboardPaddle()
        self.paddle_keys = PaddleKeys(self.paddle)
        self.paddle.char.connect(self.on_paddle_char)
        self.paddle.unknown.connect(lambda code: self.statusBar().showMessage(
            f"Paddle : « {code} » n'est pas une lettre, rien d'émis"))
        self.paddle_sent = ""
        self.paddle_button = QtWidgets.QPushButton("PADDLE CLAVIER")
        self.paddle_button.setCheckable(True)
        self.paddle_button.setMinimumWidth(58)
        self.paddle_button.setStyleSheet(PUSH_3D)
        self.paddle_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.paddle_button.setToolTip("Manipuler au clavier : Ctrl gauche = points, "
                                      "Ctrl droit = traits. Chaque lettre est émise par "
                                      "la radio (en CW). Recliquer pour arrêter.")
        self.paddle_button.toggled.connect(self.on_paddle_toggled)
        self.paddle_wpm = QtWidgets.QSpinBox()
        self.paddle_wpm.setRange(10, 35)
        self.paddle_wpm.setValue(20)
        self.paddle_wpm.setSuffix(" mots/min")
        self.paddle_wpm.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.paddle_wpm.valueChanged.connect(self.on_paddle_wpm)
        paddle_box = QtWidgets.QWidget()
        paddle_row = QtWidgets.QHBoxLayout(paddle_box)
        paddle_row.setContentsMargins(0, 0, 0, 0)
        paddle_row.setSpacing(4)
        paddle_row.addWidget(self.paddle_button)
        paddle_row.addWidget(self.paddle_wpm)
        extras.addWidget(paddle_box, 0, 6)
        # VOX : bouton marche/arrêt + potentiomètre de gain (réglage fin)
        self.vox_button = QtWidgets.QPushButton("VOX OFF")
        self.vox_button.setCheckable(True)
        self.vox_button.setMinimumWidth(58)
        self.vox_button.setStyleSheet(PUSH_3D)
        self.vox_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.vox_button.setToolTip("VOX sur le micro du PC : la radio passe en émission "
                                   "quand tu parles, et revient en réception 0,8 s après. "
                                   "Vert = en attente · rouge = émission.")
        self.vox_button.toggled.connect(self.on_vox_toggled)
        self.vox_knob = PotKnob(0, 255)
        self.vox_knob.setToolTip("Sensibilité du VOX : plus haut = déclenche plus "
                                 "facilement. Molette = réglage fin (1 cran), "
                                 "Maj + molette = 10 crans, ou glisser haut/bas")
        self.vox_knob.setValue(128)
        self.vox_monitor = None
        self.vox_tx = False             # émission lancée par le VOX
        self.vox_last_voice = 0.0
        self.vox_knob.valueChanged.connect(self.on_vox_knob)
        self.vox_label = QtWidgets.QLabel(f"{128 * 100 / 255:.0f} %")
        self.vox_label.setMinimumWidth(44)
        self.vox_label.setStyleSheet("font: bold 11pt monospace;")
        vox_box = QtWidgets.QWidget()
        vox_row = QtWidgets.QHBoxLayout(vox_box)
        vox_row.setContentsMargins(0, 0, 0, 0)
        vox_row.setSpacing(4)
        vox_row.addWidget(self.vox_button)
        self.vox_button.hide()          # remplacé par le bouton EMISSION (sous TUNE)
        self.emission_button = EmissionButton()
        self.emission_button.setToolTip(self.vox_button.toolTip() + "\nMise en marche "
                                        "manuelle ; coupure 2 s après la fin de modulation.")
        self.emission_button.is_tx = lambda: self.vox_tx
        self.emission_button.toggled.connect(self.vox_button.setChecked)
        self.vox_button.toggled.connect(self._emission_sync)
        self.tune_col.addWidget(self.emission_button, 0, QtCore.Qt.AlignHCenter)
        vox_row.addWidget(self.vox_knob)
        vox_row.addWidget(self.vox_label)
        # VOX VOCAL : dire « VOX » au micro arme le VOX ; coupure 1 s après la parole
        self.vox_vocal_button = QtWidgets.QPushButton("VOX\nVOCAL")
        self.vox_vocal_button.setCheckable(True)
        self.vox_vocal_button.setStyleSheet(PUSH_3D + "QPushButton { font-size: 8pt; }")
        self.vox_vocal_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.vox_vocal_button.setToolTip(
            "Commande à la voix : dis « VOX » seul au micro → le VOX se met en marche ; "
            "parle, la radio émet ; 1 s après la fin de ta parole → retour en réception, "
            "VOX coupé, et le Scope attend un nouveau « VOX ».")
        self.vox_vocal_button.toggled.connect(self.on_vox_vocal_toggled)
        self.mot_vox = MotVox()
        self.mot_vox.word.connect(self.on_mot_vox)
        self.mot_vox.heard.connect(self.on_mot_vox_heard)
        self.mot_vox.segment.connect(self.on_mot_vox_segment)
        self.voice_cmds = VoiceCommands()   # ta voix pour « VOX 1 », « VOX 2 »…
        self.vox_learn = None               # apprentissage en cours : (n, exemples, fenêtre)
        self.vox_by_voice = False       # VOX armé par le mot « VOX »
        self.mot_vox_timer = QtCore.QTimer(self)
        self.mot_vox_timer.timeout.connect(self._mot_vox_tick)
        vox_row.addWidget(self.vox_vocal_button)
        extras.addWidget(vox_box, 0, 7)
        # ÉGALISEUR : timbre de la voix d'émission (egaliseur.py, egaliseur-voix.ini)
        self.eq_engine = EqEngine()
        self.eq_window = None
        self.eq_button = QtWidgets.QPushButton("ÉGALISEUR")
        self.eq_button.setMinimumWidth(58)
        self.eq_button.setStyleSheet(PUSH_3D)
        self.eq_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.eq_button.setToolTip("Égaliseur de la voix du micro avant la radio. Réglages "
                                  "aussi dans egaliseur-voix.ini (relu tout seul).")
        self.eq_button.clicked.connect(self.on_eq_button)
        eq_col = QtWidgets.QVBoxLayout()           # dans le cadre RÉGLAGES AUDIO
        eq_col.setSpacing(1)
        eq_col.addWidget(NamePlate("ÉGALISEUR", 88), 0, QtCore.Qt.AlignHCenter)
        self.eq_button.setText("RÉGLER")
        self.eq_button.setMinimumHeight(44)
        eq_col.addWidget(self.eq_button, 0, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter)
        eq_col.addStretch()
        self.audio_bar.addLayout(eq_col)
        # compresseur de modulation de la radio (BLU) : marche/arrêt + niveau 0–10
        self.comp_button = QtWidgets.QPushButton("COMP OFF")
        self.comp_button.setCheckable(True)
        self.comp_button.setMinimumWidth(58)
        self.comp_button.setStyleSheet(PUSH_3D)
        self.comp_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.comp_button.setToolTip("Compresseur de modulation de l'IC-7300 (BLU) : "
                                    "marche / arrêt. Surveiller la barre COMP dB : "
                                    "10 à 15 dB en pointe, c'est bien.")
        self.comp_button.toggled.connect(self.on_comp_toggled)
        self.comp_knob = PotKnob(0, 255)
        self.comp_knob.setToolTip("Niveau du compresseur (0 à 10 comme sur la radio). "
                                  "Molette = fin, Maj + molette = 10 crans, ou glisser")
        self.comp_knob.valueChanged.connect(self.on_comp_knob)
        self.comp_label = QtWidgets.QLabel("–")
        self.comp_label.setMinimumWidth(30)
        self.comp_label.setStyleSheet("font: bold 11pt monospace;")
        comp_box = QtWidgets.QWidget()
        comp_row = QtWidgets.QHBoxLayout(comp_box)
        comp_row.setContentsMargins(0, 0, 0, 0)
        comp_row.setSpacing(4)
        # le bouton COMP va dans la rangée d'outils, avec les autres boutons
        tools.addWidget(self.comp_button, 0, 12)
        comp_title = QtWidgets.QLabel("Niveau COMP")
        comp_row.addWidget(comp_title)
        comp_row.addWidget(self.comp_knob)
        comp_row.addWidget(self.comp_label)
        # placé dans la ligne des réglages d'émission (voir tx_row)
        self.heard_stations = []            # (fréquence, LSB/USB), dans l'ordre d'écoute
        self.heard_index = -1               # station où l'on est dans cette liste
        self.heard_origin = -1              # station où le scan s'est arrêté (repère 0)
        self.manual_left = 0
        self.manual_blink = False
        self.manual_timer = QtCore.QTimer(self)
        self.manual_timer.timeout.connect(self._manual_tick)
        self.seek_active = False
        self.seek_dir = 1
        self.manual_seek_hz = None
        self.scanner = QsoHunter(self, scan_only=True)
        self.scanner.status.connect(lambda text: self.statusBar().showMessage(text))
        self.scanner.heard.connect(self.on_station_heard)
        # QSO français repéré pendant le scan : bip + bouton rouge RESTER ICI
        self.scanner.found.connect(self.on_scan_found)
        self.scanner.holding.connect(self.on_hunt_holding)
        self.scanner.finished.connect(self.on_scan_finished)
        self.scan_blink = False
        self.scan_timer = QtCore.QTimer(self)
        self.scan_timer.timeout.connect(self._blink_scan)
        self.extras_layout = extras
        for col in range(6, 12):            # place gardée pour d'autres boutons
            extras.setColumnStretch(col, 1)
        below.addWidget(PanelFrame(extras))

        # Réglages
        controls = QtWidgets.QHBoxLayout()
        self.view_combo = QtWidgets.QComboBox()
        self.view_combo.addItem("RF (scope radio)", "rf")
        self.view_combo.addItem("Audio", "audio")
        self.view_combo.setToolTip("RF : centré sur la fréquence écoutée, "
                                   "clic pour s'y caler. Audio : le son reçu.")
        self.span_combo = QtWidgets.QComboBox()
        for hz in SPANS:
            label = f"±{hz / 1000:g} kHz".replace(".", ",")
            self.span_combo.addItem(label, hz)
        self.span_combo.setToolTip("Largeur du scope de la radio")
        self.span_combo.activated.connect(self.on_span_selected)
        self.fmax_spin = QtWidgets.QSpinBox()
        self.fmax_spin.setRange(500, RATE // 2)
        self.fmax_spin.setSingleStep(500)
        self.fmax_spin.setSuffix(" Hz")
        self.fmax_spin.setValue(self.fmax)
        self.fmax_spin.valueChanged.connect(self.set_fmax)
        self.auto_check = QtWidgets.QCheckBox("Niveaux auto")
        self.auto_check.setChecked(True)
        self.floor_spin = QtWidgets.QDoubleSpinBox()
        self.floor_spin.setRange(-160, 160)
        self.floor_spin.setValue(self.wf_low)
        self.floor_spin.valueChanged.connect(self.on_floor_changed)
        self.range_spin = QtWidgets.QDoubleSpinBox()
        self.range_spin.setRange(10, 160)
        # menu RF / Audio remplacé par l'interrupteur AFFICHAGE (rangée du haut)
        self.view_combo.hide()
        self.view_toggle.toggled.connect(
            lambda down: self.view_combo.setCurrentIndex(1 if down else 0))
        self.view_combo.currentIndexChanged.connect(
            lambda i: self.view_toggle.setDown(i == 1, emit=False))
        controls.addWidget(QtWidgets.QLabel("Largeur"))
        controls.addWidget(self.span_combo)
        controls.addWidget(self.fmax_spin)
        controls.addSpacing(20)
        controls.addWidget(self.auto_check)
        controls.addWidget(QtWidgets.QLabel("Plancher"))
        controls.addWidget(self.floor_spin)
        controls.addWidget(QtWidgets.QLabel("Plage"))
        controls.addWidget(self.range_spin)
        controls.addStretch()

        # Volumes : le son de la radio sur le PC, et le volume de la radio
        self.pc_volume = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.pc_volume.setRange(0, 150)
        self.pc_volume.setFixedWidth(130)
        self.pc_volume.setToolTip("Volume du son de la radio sur le PC")
        self.pc_volume_label = QtWidgets.QLabel()
        self.pc_volume_label.setMinimumWidth(50)
        self.mute_check = QtWidgets.QCheckBox("Muet")
        self.af_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.af_slider.setRange(0, 255)
        self.af_slider.setFixedWidth(130)
        self.af_slider.setToolTip("Volume du haut-parleur de la radio (AF). "
                                  "Ne change pas le son envoyé au PC.")
        self.af_label = QtWidgets.QLabel()
        self.af_label.setMinimumWidth(50)
        # curseur Volume PC remplacé par le bouton VOLUME (à côté d'ALC) ;
        # le curseur reste caché : il fait le lien avec le son
        self.pc_volume.hide()
        self.pc_volume_label.hide()
        self.volume_knob.valueChanged.connect(self.pc_volume.setValue)
        # case Muet remplacée par l'interrupteur MUET (à côté d'AFFICHAGE)
        self.mute_check.hide()
        self.mute_toggle.toggled.connect(self.mute_check.setChecked)
        self.mute_check.toggled.connect(lambda on: self.mute_toggle.setDown(on, emit=False))
        # commutateur de sortie : casque (USB) ou haut-parleurs du PC
        self.output_button = QtWidgets.QPushButton()
        self.output_button.setStyleSheet(PUSH_3D)
        self.output_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.output_button.setToolTip("Bascule tout le son du PC entre le casque "
                                      "et les haut-parleurs du PC")
        self.output_button.clicked.connect(self.on_output_switch)
        # LED rouge allumée quand le son part dans le casque
        self.headset_led = QtWidgets.QLabel()
        self.headset_led.setFixedSize(14, 14)
        self.headset_led.setToolTip("Rouge = son dans le casque")
        out_row = QtWidgets.QHBoxLayout()
        out_row.setSpacing(6)
        out_row.addWidget(self.headset_led)
        out_row.addWidget(self.output_button)
        # bouton CASQUE remplacé par l'interrupteur ÉCOUTE (à côté de MUET)
        self.headset_led.hide()
        self.output_button.hide()
        self.preamp_box.hide()                  # plus rien à gauche des touches
        self.output_toggle.toggled.connect(self._output_toggled)
        self.af_label_box.addLayout(out_row)               # sous « VOLUME BF PC »
        self._output_text()
        self.output_timer = QtCore.QTimer(self)            # casque branché/débranché
        self.output_timer.timeout.connect(self._output_text)
        self.output_timer.start(2000)
        # volume du son épuré par RNNoise (au-delà de 100 % : amplifié)
        self.clean_volume = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.clean_volume.setRange(50, 400)
        self.clean_volume.setValue(RNN_CLEAN_VOLUME)
        self.clean_volume.setFixedWidth(110)
        self.clean_volume.setEnabled(False)
        self.clean_volume.setToolTip("Volume du son épuré quand RNNOISE est actif "
                                     "(au-delà de 100 % : amplifié)")
        self.clean_volume_label = QtWidgets.QLabel(f"{RNN_CLEAN_VOLUME} %")
        self.clean_volume_label.setMinimumWidth(50)
        self.clean_volume.valueChanged.connect(self.on_clean_volume)
        # curseur Épuré remplacé par le bouton ÉPURÉ (rangée au-dessus du waterfall)
        self.clean_volume.hide()
        self.clean_volume_label.hide()
        self.clean_knob.setValue(self.clean_volume.value())
        self.clean_knob.valueChanged.connect(
            lambda v: self.clean_volume.setValue(max(50, v)))   # 50 % au minimum
        # curseur AF radio remplacé par le bouton AF RADIO (à droite d'ÉPURÉ)
        self.af_slider.hide()
        self.af_label.hide()
        self.af_radio_knob.valueChanged.connect(
            lambda pct: self.af_slider.setValue(round(pct * 255 / 100)))

        self.loopback = None
        self.pc_volume.valueChanged.connect(self.on_pc_volume)
        self.mute_check.toggled.connect(self.on_mute)
        # le son (surtout en --remote) peut apparaître après la fenêtre :
        # chercher chaque seconde jusqu'à le trouver
        self.loopback_timer = QtCore.QTimer(self)
        self.loopback_timer.timeout.connect(self.attach_loopback)
        if not self.attach_loopback():
            self.loopback_timer.start(1000)
        self.af_slider.setEnabled(False)    # activé quand la radio répond
        self.af_slider.valueChanged.connect(self.on_af_slider)
        below.addLayout(controls)

        # Décodeurs CW et PSK31
        decoder_row = QtWidgets.QHBoxLayout()
        self.decoder_combo = QtWidgets.QComboBox()
        self.decoder_combo.addItem("Aucun", None)
        self.decoder_combo.addItem("CW", "cw")
        self.decoder_combo.addItem("PSK31", "psk31")
        self.decoder_combo.addItem("RTTY 45", "rtty")
        self.decoder_combo.addItem("FT8", "ft8")
        self.decoder_auto = QtWidgets.QCheckBox("Calage auto")
        self.decoder_auto.setChecked(True)
        self.rtty_invert = QtWidgets.QCheckBox("Inverser")
        self.rtty_invert.setToolTip("Mark sur la tonalité haute. À essayer si "
                                    "le texte reste incohérent.")
        self.rtty_invert.toggled.connect(self.on_rtty_invert)
        self.decoder_led = QtWidgets.QLabel("●")
        self.decoder_info = QtWidgets.QLabel("")
        self.decoder_info.setStyleSheet("font: 11pt monospace;")
        decoder_clear = QtWidgets.QPushButton("Effacer")
        self.decoder_clear = decoder_clear
        self.decoder_row = decoder_row
        decoder_row.addWidget(QtWidgets.QLabel("Décodeur"))
        decoder_row.addWidget(self.decoder_combo)
        decoder_row.addWidget(self.decoder_auto)
        decoder_row.addWidget(self.rtty_invert)
        decoder_row.addWidget(self.decoder_led)
        decoder_row.addWidget(self.decoder_info)
        self.decoder_led.setMinimumWidth(16)
        decoder_row.addStretch()
        decoder_row.addWidget(decoder_clear)
        sstv_button = QtWidgets.QPushButton("SSTV…")
        sstv_button.setToolTip("Réception et émission d'images SSTV, "
                               "dans une fenêtre à part")
        sstv_button.clicked.connect(self.open_sstv)
        decoder_row.addWidget(sstv_button)
        decoder_row.addSpacing(20)
        self.record_button = QtWidgets.QPushButton("● Enregistrer")
        self.record_button.setCheckable(True)
        self.record_button.setToolTip(f"Enregistre le son de la radio dans {RECORD_DIR}")
        self.record_button.toggled.connect(self.on_record)
        self.record_label = QtWidgets.QLabel("")
        self.record_label.setStyleSheet("font: 11pt monospace;")
        record_folder = QtWidgets.QPushButton("Dossier")
        record_folder.setToolTip("Ouvrir le dossier des enregistrements")
        record_folder.clicked.connect(self.open_record_folder)
        decoder_row.addWidget(self.record_button)
        decoder_row.addWidget(self.record_label)
        decoder_row.addWidget(record_folder)
        # REC vidéo : écran + son du trafic (le même enregistreur que dans WATERFALL FR)
        decoder_row.addSpacing(10)
        self.rec_video_button = QtWidgets.QPushButton("⏺ REC vidéo")
        self.rec_video_button.setToolTip(
            "Vidéo de l'écran avec le son du trafic (micro + réception + émission) dans "
            "~/MUSARDE-date.mkv ; nouveau clic = arrêt")
        self.rec_video_button.clicked.connect(self.screen_rec.toggle)
        decoder_row.addWidget(self.rec_video_button)
        self.screen_rec.changed.connect(lambda *_: self._rec_video_show())
        self.rec_video_timer = QtCore.QTimer(self)
        self.rec_video_timer.timeout.connect(self._rec_video_show)
        self.rec_video_timer.start(1000)
        self.record_timer = QtCore.QTimer(self)
        self.record_timer.setInterval(500)
        self.record_timer.timeout.connect(self.update_record_label)
        self.record_path = None
        self.decoder_text = QtWidgets.QPlainTextEdit()
        self.decoder_text.setReadOnly(True)
        self.decoder_text.setMaximumBlockCount(500)
        self.decoder_text.setFixedSize(300, 104)
        self.decoder_text.setStyleSheet("font: bold 12pt monospace; color: #3ddc84; "
                                        "background: #05080a; border: 2px solid #3e3024; "
                                        "border-radius: 6px;")
        self.decoder_text.setVisible(False)
        below.addLayout(decoder_row)
        # texte décodé : dans la place libre sous le S-mètre (la fenêtre ne grandit pas)
        self.s_col.insertWidget(self.s_col.count() - 1, self.decoder_text)

        # Émission : micro du PC ou fichier, envoyés à la radio par l'USB
        self.radio_sink = args.sink
        tx_row = QtWidgets.QHBoxLayout()
        self.power_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.power_slider.setRange(0, 100)
        self.power_slider.setFixedWidth(120)
        self.power_slider.setToolTip("Puissance d'émission de la radio")
        self.power_slider.setEnabled(False)     # activé quand la radio répond
        self.power_label = QtWidgets.QLabel("")
        self.power_label.setMinimumWidth(55)
        self.tx_source = QtWidgets.QComboBox()
        for name, description in list_microphones(args.source):
            self.tx_source.addItem(f"Micro : {description}", name)
        self.tx_source.addItem("Fichier audio", "file")
        # micro par défaut du système en premier choix (le casque quand il est branché)
        default_mic = subprocess.run(["pactl", "get-default-source"], capture_output=True,
                                     text=True, env=PACTL_ENV).stdout.strip()
        if self.tx_source.findData(default_mic) >= 0:
            self.tx_source.setCurrentIndex(self.tx_source.findData(default_mic))
        self.voice_scope.set_source(self.tx_source.currentData())
        self.tx_source.currentIndexChanged.connect(
            lambda _: self.voice_scope.set_source(self.tx_source.currentData()))
        self.tx_source.setToolTip("Ce qui part à l'émission")
        self.tx_file = None
        self.tx_file_button = QtWidgets.QPushButton("Choisir…")
        self.tx_file_button.clicked.connect(self.choose_tx_file)
        self.tx_level = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.tx_level.setRange(0, 100)
        self.tx_level.setFixedWidth(100)
        self.tx_level.setToolTip("Niveau du son envoyé à la radio. Le régler "
                                 "pour que l'ALC bouge sans dépasser.")
        volume = sink_volume(self.radio_sink)
        self.tx_level.setValue(volume if volume is not None else 50)
        self.tx_level_label = QtWidgets.QLabel(f"{self.tx_level.value()} %")
        self.tx_level_label.setMinimumWidth(40)
        self.tx_level.valueChanged.connect(self.on_tx_level)
        # gain USB de la radio : c'est lui qui fait monter l'ALC
        self.alc_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.alc_slider.setRange(0, 100)
        self.alc_slider.setFixedWidth(100)
        self.alc_slider.setToolTip("Gain de l'entrée USB de la radio (menu USB MOD "
                                   "Level). En émission, le monter jusqu'à ce que "
                                   "l'ALC bouge, sans rester au maximum.")
        self.alc_slider.setEnabled(False)       # activé quand la radio répond
        self.alc_slider_label = QtWidgets.QLabel("")
        self.alc_slider_label.setMinimumWidth(40)
        self.tx_meter_label = QtWidgets.QLabel("")
        self.tx_meter_label.setStyleSheet("font: 11pt monospace;")
        self.ptt_button = QtWidgets.QPushButton("ÉMETTRE")
        self.ptt_button.setCheckable(True)
        self.ptt_button.setMinimumWidth(120)
        self.ptt_button.setToolTip(f"La radio émet. Coupure automatique après "
                                   f"{TX_TIMEOUT // 60} min (ou la durée du "
                                   f"fichier s'il est plus long).")
        self.ptt_button.toggled.connect(self.on_ptt)
        self.red_button.toggled.connect(self.ptt_button.setChecked)
        # curseur Puissance retiré de l'écran : remplacé par le bouton argent
        # sous le galva POWER (le curseur reste caché, il fait le lien avec la radio)
        self.power_slider.hide()
        self.power_label.hide()
        tx_row.addSpacing(10)
        tx_row.addWidget(self.tx_source)
        self.tx_source.hide()           # remplacé par le bouton GAIN MICRO (micro par défaut)
        tx_row.addWidget(self.tx_file_button)
        # curseurs Niveau et Réglage ALC remplacés par les boutons NIVEAU et ALC
        # sous le S-mètre (les curseurs restent cachés : lien avec le son et la radio)
        self.tx_level.hide()
        self.tx_level_label.hide()
        self.alc_slider.hide()
        self.alc_slider_label.hide()
        self.level_knob.setValue(self.tx_level.value())
        self.level_knob.valueChanged.connect(self.tx_level.setValue)
        self.alc_knob.valueChanged.connect(self.alc_slider.setValue)
        tx_row.addWidget(self.tx_meter_label)
        tx_row.addSpacing(16)
        tx_row.addWidget(comp_box)
        # champ de saisie CW : texte tapé → émis par la radio (Entrée), Échap = stop
        tx_row.addSpacing(16)
        self.cw_entry = CwEntry()
        self.cw_entry.setPlaceholderText("Texte CW à émettre… (Entrée = émettre, Échap = stop)")
        self.cw_entry.setMinimumWidth(420)
        self.cw_entry.setStyleSheet(
            "QLineEdit { font: bold 12pt monospace; color: #3ddc84; background: #05080a; "
            "border: 2px solid #3e3024; border-radius: 6px; padding: 3px 8px; }")
        self.cw_entry.returnPressed.connect(self._cw_entry_send)
        self.cw_entry.escape.connect(self._cw_entry_stop)
        tx_row.addWidget(self.cw_entry, stretch=1)
        tx_row.addStretch()
        tx_row.addWidget(self.ptt_button)
        self.ptt_button.hide()          # caché : l'émission passe par EMISSION / bouton rouge
        self.cw_entry.hide()            # champ CW vert retiré (l'écran CW a le sien)
        # ligne vidée : Niveau COMP et mesure d'émission remontent sur la ligne Décodeur
        at = self.decoder_row.indexOf(self.decoder_clear)
        comp_box.hide()                 # remplacé par le bouton rond NIVEAU COMP
        self.decoder_row.insertWidget(at, self.tx_meter_label)
        self.decoder_row.insertSpacing(at + 2, 16)
        below.addLayout(tx_row)

        # Fenêtre de décodage CW : prend toute la place sous le waterfall
        cw_box = QtWidgets.QVBoxLayout()
        self.cw_text = QtWidgets.QPlainTextEdit()
        self.cw_text.setReadOnly(True)
        self.cw_text.setMaximumBlockCount(2000)
        self.cw_text.setMinimumHeight(32)       # une ligne au minimum : la fenêtre tient à l'écran
        self.cw_text.setStyleSheet("font: bold 20pt monospace; color: #3ddc84;"
                                   " background: #05080a; border: none;")
        self.cw_info = QtWidgets.QLabel("")
        self.cw_info.setStyleSheet("font: bold 13pt monospace; color: #ffd54a;")
        self.cw_bottom = QtWidgets.QHBoxLayout()
        self.cw_bottom.addWidget(self.cw_info, stretch=1)
        cw_box.addWidget(self.cw_text, stretch=1)
        cw_box.addLayout(self.cw_bottom)
        self.cw_frame = PanelFrame(cw_box)
        self.cw_frame.setVisible(False)
        layout.addWidget(self.cw_frame, stretch=1)
        self.cw_view_active = False
        self.cw_blink = False
        self.cw_blink_timer = QtCore.QTimer(self)
        self.cw_blink_timer.timeout.connect(self._blink_cw)
        self.cw_hunter = CwHunter(self)
        self.cw_hunter.status.connect(self.on_cw_status)
        self.cw_hunter.countdown.connect(self.on_cw_countdown)
        self.cw_hunter.finished.connect(self.on_cw_finished)
        self.tx_source.currentIndexChanged.connect(self.on_tx_source)
        self.on_tx_source()
        self.power_slider.valueChanged.connect(self.on_power_slider)
        self.power_knob.valueChanged.connect(self.power_slider.setValue)
        self.alc_slider.valueChanged.connect(self.on_alc_slider)
        self.tx_active = False
        self.tx_digital = False         # émission numérique (SSTV) : mode data
        self.tx_started = 0.0
        self.tx_limit = TX_TIMEOUT          # s ; plus pour un fichier plus long
        self.tx_loopback = None             # module PipeWire micro → radio
        self.tx_loopback_source = None
        self.tx_loopback_input = None
        self._tx_mic_unload()               # restes d'une session plantée
        self._rec_mic_unload()
        source = self.tx_source.currentData()
        if source and source != "file":
            self.eq_engine.start(source)    # voix égalisée prête avant la liaison
            self._tx_mic_mute(source, True)  # liaison prête dès le départ, micro coupé
        # micro → enregistrement : revérifié toutes les 5 s hors émission (le système
        # son peut le remettre muet au démarrage)
        self.rec_mic_timer = QtCore.QTimer(self)
        self.rec_mic_timer.timeout.connect(self._rec_links_check)
        self.rec_mic_timer.start(5000)
        # MUET tenu : le flux d'écoute peut être recréé (relais, réseau) et repartir
        # avec le son ; on remet toutes les 1,5 s l'état voulu
        self.mute_guard_timer = QtCore.QTimer(self)
        self.mute_guard_timer.timeout.connect(self._mute_guard)
        self.mute_guard_timer.start(1500)
        QtCore.QTimer.singleShot(2500, self._rec_links_check)
        self.tx_player = None               # paplay du fichier
        self.tx_timer = QtCore.QTimer(self)
        self.tx_timer.setInterval(250)
        self.tx_timer.timeout.connect(self.check_tx)
        self.decoder_combo.currentIndexChanged.connect(self.on_decoder_changed)
        self.decoder_auto.toggled.connect(self.on_decoder_auto)
        decoder_clear.clicked.connect(self.decoder_text.clear)
        self._set_decoder_led(False, False)

        self.view = None
        self.scope_edges = None
        self.view_combo.currentIndexChanged.connect(self.on_view_changed)
        self.on_view_changed()

        self.audio.spectrum.connect(self.on_spectrum)
        self.audio.failed.connect(self.statusBar().showMessage)
        self.audio.decoded.connect(self.on_decoded)
        self.audio.decoder_state.connect(self.on_decoder_state)
        self.audio.ssb_state.connect(self.on_ssb_state)
        self.audio.ssb_correct.connect(self.on_ssb_correct)
        self.audio.sstv_seen.connect(self.on_sstv_seen)
        self.audio.cw_env.connect(self.voice_scope.feed_cw)
        self.cw_scope_timer = QtCore.QTimer(self)        # oscillo : CW reçue ou voix
        self.cw_scope_timer.timeout.connect(self._cw_scope_update)
        self.cw_scope_timer.start(300)
        self.sstv_history = []          # dernières analyses de la surveillance SSTV
        self.sstv_last = None           # (mode, Hz des tops) de la dernière détection
        self.sstv_band_hits = []        # fréquence d'appel de la bande : signal présent ?
        self.sstv_band_target = None    # (fréquence, mode) à rejoindre
        self.sstv_band_timer = QtCore.QTimer(self)
        self.sstv_band_timer.timeout.connect(self._sstv_band_check)
        self.sstv_band_timer.start(2000)
        self.on_decoder_changed()
        self.audio.start()

        self.civ = None
        if args.no_cat:
            self.statusBar().showMessage("CAT désactivé")
        else:
            self.civ = CivReader(args.port, args.baud)
            self.civ.meter.connect(self.on_meter)
            self.civ.cw_pitch.connect(self.on_cw_pitch)
            self.civ.vox.connect(self.on_radio_vox)
            self.civ.vox_gain.connect(self.on_radio_vox_gain)
            self.civ.comp_on.connect(self.on_radio_comp)
            self.civ.comp_level.connect(self.on_radio_comp_level)
            self.civ.frequency.connect(self.on_frequency)
            self.civ.mode.connect(self.on_mode)
            self.civ.other_frequency.connect(self.on_other_frequency)
            self.civ.other_mode.connect(self.on_other_mode)
            self.civ.af_gain.connect(self.on_af_gain)
            self.civ.tuner.connect(self.on_tuner)
            self.civ.power.connect(self.on_power)
            self.civ.transmitting.connect(self.on_transmitting)
            self.civ.tx_meters.connect(self.on_tx_meters)
            self.civ.po_meter.connect(self.on_po)
            self.civ.usb_mod.connect(self.on_usb_mod)
            self.civ.comp.connect(self.on_comp)
            self.civ.drain.connect(self.on_drain)
            self.civ.scope.connect(self.on_scope)
            self.civ.span.connect(self.on_span)
            self.civ.status.connect(self.statusBar().showMessage)
            self.civ.alive.connect(self.on_alive)
            self.civ.start()

    def visible_bins(self):
        return int(self.fmax / BIN_HZ) + 1

    def on_view_changed(self):
        self.view = self.view_combo.currentData()
        rf = self.view == "rf"
        self.span_combo.setVisible(rf)
        self.fmax_spin.setVisible(not rf)
        for item in self.tuned_lines + self.passbands:
            item.setVisible(rf)
        self._show_pitch_lines()
        self.avg = None
        if rf:
            # niveaux du scope de la radio : 0 à 160
            self.spec_plot.setYRange(0, 160, padding=0)
            self.spec_plot.setLabel("left", "Niveau")
            self.spec_curve.setFillLevel(0)
            self.wf_plot.setLabel("bottom", "Fréquence (kHz)")
            self.floor_spin.setSuffix("")
            self.range_spin.setSuffix("")
            self.wf_low = 20.0
            self.range_spin.setValue(90)
            self.scope_edges = None
            self._reset_waterfall(1, 0, 1)
            self._update_markers()
        else:
            self.spec_plot.setYRange(-130, 0, padding=0)
            self.spec_plot.setLabel("left", "dBFS")
            self.spec_curve.setFillLevel(-140)
            self.wf_plot.setLabel("bottom", "Fréquence audio", units="Hz")
            self.floor_spin.setSuffix(" dB")
            self.range_spin.setSuffix(" dB")
            self.wf_low = -100.0
            self.range_spin.setValue(60)
            self.set_fmax(self.fmax)
        self.floor_spin.setValue(self.wf_low)

    def _reset_waterfall(self, width, x0, x1):
        self.waterfall = np.full((HISTORY, width), -160, np.float32)
        self.wf_image.setImage(self.waterfall, autoLevels=False,
                               levels=(-160, -100))
        self.wf_image.setRect(QtCore.QRectF(x0, 0, x1 - x0, HISTORY))
        self.spec_plot.setXRange(x0, x1, padding=0)
        self.wf_plot.setYRange(0, HISTORY, padding=0)

    def set_fmax(self, fmax):
        self.fmax = fmax
        if self.view == "audio":
            self._reset_waterfall(self.visible_bins(), 0,
                                  self.visible_bins() * BIN_HZ)
            self.spec_plot.setXRange(0, fmax, padding=0)

    def _add_waterfall_row(self, row, visible):
        if self.auto_check.isChecked():
            # plancher juste sous le bruit, plage juste au-dessus des signaux
            # forts : le bruit reste sombre et les signaux ressortent bien
            target = float(np.percentile(visible, 20)) - 8
            self.wf_low += 0.05 * (target - self.wf_low)
            top = float(np.percentile(visible, 99.5)) + 2
            span = min(max(top - self.wf_low, 25.0), 90.0)
            span = self.range_spin.value() + 0.05 * (span - self.range_spin.value())
            for spin, value in ((self.floor_spin, self.wf_low), (self.range_spin, span)):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        self.waterfall = np.roll(self.waterfall, 1, axis=0)
        self.waterfall[0] = row
        self.wf_image.setImage(self.waterfall, autoLevels=False,
                               levels=(self.wf_low,
                                       self.wf_low + self.range_spin.value()))
        self._mobile_waterfall()

    def on_scope(self, points, low, high):
        if self.fr_toggle.down:
            self.fr_screen.feed_scope(points, low, high)
        self.hunter.feed_scope(points, low, high)
        self.cw_hunter.feed_scope(points, low, high)
        self.scanner.feed_scope(points, low, high)
        self._update_rx_fine(points, low, high)
        if self.view != "rf":
            return
        n = len(points)
        if self.scope_edges != (low, high) or self.waterfall.shape[1] != n:
            old = self.scope_edges
            if old and old[1] - old[0] == high - low and self.waterfall.shape[1] == n:
                # la fréquence a bougé : on décale l'historique d'autant
                shift = round((old[0] - low) / ((high - low) / n))
                self.waterfall = np.roll(self.waterfall, shift, axis=1)
                if shift > 0:
                    self.waterfall[:, :shift] = -160
                elif shift < 0:
                    self.waterfall[:, shift:] = -160
                self.wf_image.setRect(QtCore.QRectF(low / 1000, 0,
                                                    (high - low) / 1000, HISTORY))
                self.spec_plot.setXRange(low / 1000, high / 1000, padding=0)
            else:
                self._reset_waterfall(n, low / 1000, high / 1000)
            self.scope_edges = (low, high)
            self.avg = None
        self.avg = points if self.avg is None else 0.5 * self.avg + 0.5 * points
        step = (high - low) / n
        self.spec_curve.setData((low + (np.arange(n) + 0.5) * step) / 1000, self.avg)
        self._add_waterfall_row(points, self.avg)

    def _update_rx_fine(self, points, low, high):
        """Barre RX fin : crête du spectre dans la bande passante moins le bruit."""
        if getattr(self, "tx_active", False) or not self.freq_hz:
            return
        points = np.asarray(points, float)
        n = len(points)
        if n < 20 or high <= low:
            return
        f = self.freq_hz
        mode = self.mode_combo.currentText()
        band = {"USB": (f + 200, f + 2800), "LSB": (f - 2800, f - 200),
                "AM": (f - 4000, f + 4000), "FM": (f - 6000, f + 6000)}
        lo, hi = band.get(mode.replace("-D", ""), (f - 250, f + 250))
        step = (high - low) / n
        i0 = max(0, int((lo - low) / step))
        i1 = min(n, int(np.ceil((hi - low) / step)) + 1)
        if i1 - i0 < 1:
            return
        inside = np.sort(points[i0:i1])[-3:]        # les 3 points les plus forts
        floor = np.percentile(points, 20)
        self.rx_scope_part = max(0.0, float(inside.mean() - floor))

    def _rx_meter_feed(self, raw):
        """Part S-mètre : écart au fond de bruit suivi lentement (0,45 dB/unité)."""
        if getattr(self, "tx_active", False):
            return
        if self.rx_meter_floor is None or raw < self.rx_meter_floor:
            self.rx_meter_floor = float(raw)
        else:
            self.rx_meter_floor += (raw - self.rx_meter_floor) * 0.003
        self.rx_meter_part = max(0.0, (raw - self.rx_meter_floor) * 0.45)

    def _rx_fine_tick(self):
        """Barre RX fin animée comme l'aiguille : monte vite, redescend doucement."""
        # position exacte de l'aiguille ; sous S1, le spectre prend le relais
        if getattr(self, "tx_active", False):
            # en émission : pas de réception, barre à zéro
            self.rx_fine.value = self.rx_fine.peak = self.rx_fine.minimum
            self.rx_fine.update()
            self.rx_fine_value.setText("TX")
            return
        needle = self.s_meter.value
        s1 = S9 / 9
        level = max(needle, min(self.rx_scope_part * s1 / 10, s1))
        self.rx_fine_level = level
        self.rx_fine.setValue(level)
        if level <= S9:
            text = f"S{level * 9 / S9:.1f}".replace(".", ",")
        else:
            text = f"S9+{(level - S9) * 60 / (S9_PLUS_60 - S9):.0f}"
        self.rx_fine_value.setText(text)

    def on_span(self, hz):
        index = self.span_combo.findData(hz)
        if index >= 0:
            self.span_combo.setCurrentIndex(index)

    # -- surveillance SSTV --------------------------------------------------

    def on_sstv_seen(self, result):
        """Toutes les secondes : (mode, Hz des tops) si une image SSTV passe."""
        self.sstv_history = (self.sstv_history + [result])[-20:]
        recent = [r for r in self.sstv_history[-6:] if r]
        if len(recent) >= 2:                    # 2 détections sur 6 s : c'est une image
            self.sstv_last = recent[-1]
            self._sstv_alert()
            self._sstv_auto_decode(recent[-1][0],
                                   float(np.median([r[1] for r in recent])))
        elif not any(self.sstv_history[-20:]):  # 20 s sans rien : fin d'alerte
            self.sstv_last = None
            self._sstv_alert()
            win = self.sstv_window
            if win is not None and not win.isVisible() and self.audio.sstv is not None:
                win.refresh()                   # dernière image enregistrée
                self.audio.sstv = None          # fin du décodage automatique
                win.timer.stop()

    def _sstv_alert(self):
        on = self.sstv_last is not None or self.sstv_band_target is not None
        self.function_selector.set_alert("SSTV", on)

    def _sstv_auto_decode(self, mode_name, sync_hz):
        """Décodage automatique, même fenêtre SSTV fermée ; une image prise en
        cours de route démarre au rythme des tops (sans en-tête VIS)."""
        if self.sstv_window is None:
            self.sstv_window = SstvWindow(self)
        win = self.sstv_window
        if self.audio.sstv is None:
            self.audio.sstv = win.decoder
            win.timer.start()                   # enregistre les images finies
            self.statusBar().showMessage(
                f"SSTV détectée ({mode_name}) : décodage automatique", 5000)
        mode = sstv_modes.BY_NAME.get(mode_name)
        if win.decoder.mode is None:
            # correspondant mal calé : on décale tout le signal (couleurs justes)
            win.decoder.tune_offset = 1200 - sync_hz if abs(sync_hz - 1200) > 15 else 0.0
            if mode:
                win.decoder.start_without_vis(mode)

    def _sstv_band_check(self):
        """Fréquence d'appel SSTV de la bande (hors de l'écoute actuelle) : un
        signal y tient-il plusieurs secondes dans la bande 1100–2300 Hz ?"""
        target = None
        band = self.freq_hz and band_of(self.freq_hz)
        call = SSTV_CALLING.get(band) if band else None
        if call and self.avg is not None and self.scope_edges and not self.tx_active \
                and abs(call[0] - self.freq_hz) > 2500:
            low, high = self.scope_edges
            f, mode = call
            a, b = (f + 1100, f + 2300) if mode == "USB" else (f - 2300, f - 1100)
            if low <= a and b <= high:
                n = len(self.avg)
                i0 = int((a - low) / (high - low) * n)
                i1 = max(i0 + 1, int((b - low) / (high - low) * n))
                level = float(np.median(self.avg[i0:i1]))
                floor = float(np.percentile(self.avg, 20))
                self.sstv_band_hits = (self.sstv_band_hits + [level - floor > 8])[-5:]
                if sum(self.sstv_band_hits) >= 4:
                    target = call
        else:
            self.sstv_band_hits = []
        if target != self.sstv_band_target:
            self.sstv_band_target = target
            self._sstv_alert()

    def _sstv_tune(self):
        """En passant sur SSTV : rejoindre le correspondant. Image entendue :
        correction d'après la fréquence des tops (1200 Hz attendus) ; sinon
        signal vu sur la fréquence d'appel de la bande : on y va."""
        sign = self._ssb_sign()
        if self.sstv_last and sign and self.freq_hz:
            offset = self.sstv_last[1] - 1200
            if abs(offset) > 15:
                hz = int(round(self.freq_hz + sign * offset))
                self.ssb_target = hz
                self.tune_to(hz)
                if self.sstv_window is not None:
                    self.sstv_window.decoder.tune_offset = 0.0   # la radio est recalée
                self.sstv_history = []          # nouvelle mesure des tops après recalage
                self.statusBar().showMessage(
                    f"SSTV : calé sur le correspondant ({offset:+.0f} Hz)", 5000)
        elif self.sstv_band_target:
            hz, mode = self.sstv_band_target
            if mode != self.mode_combo.currentText():
                self._set_sideband(mode)
            self.ssb_target = hz
            self.tune_to(hz)
            self.statusBar().showMessage(
                f"SSTV : fréquence d'appel {format_frequency(hz)} MHz {mode}", 5000)

    def on_function(self, name):
        """Sélecteur FONCTION. ZOOM : waterfall resserré à ±5 kHz ; SSTV : fenêtre
        SSTV ouverte (décodage en direct) ; OFF : tout revient comme avant."""
        if name == "SSTV":
            self._sstv_tune()
            self._sstv_attach()
        elif self.sstv_window and self.sstv_window.isVisible():
            self.sstv_window.close()
        elif self.sstv_last is None:
            self._sstv_detach()
        if name == "ZOOM":
            if self.zoom_saved_span is None:
                self.zoom_saved_span = self.span_combo.currentData()
            hz = 5000
        else:
            hz, self.zoom_saved_span = self.zoom_saved_span, None
        index = self.span_combo.findData(hz) if hz else -1
        if index >= 0:
            self.span_combo.setCurrentIndex(index)
            self.on_span_selected()
        self.statusBar().showMessage(
            {"ZOOM": "Fonction ZOOM : waterfall ±5 kHz",
             "SSTV": "Fonction SSTV : décodage des images en direct"}.get(name, "Fonction OFF"),
            3000)
        self._function_fullscreen(name)

    def _function_fullscreen(self, name):
        """Fonction enclenchée : son contenu en plein écran ; OFF : retour."""
        screen = self.function_screen
        if name == "OFF":
            self._give_back(screen.take_content())
            screen.hide()
            self.activateWindow()
            return
        if name == "ZOOM":
            self.main_layout.removeWidget(self.graphics)
            widget = self.graphics
        elif name == "SSTV":
            if self.sstv_view is None:
                self.sstv_view = SstvLiveView(
                    lambda: self.sstv_window.decoder if self.sstv_window else None)
            widget = self.sstv_view
        else:
            widget = PendingView(name)          # fonction encore à créer
        self._give_back(screen.show_content(name, widget))

    def _give_back(self, widget):
        """Rend le waterfall à la fenêtre principale, à sa place."""
        if widget is self.graphics:
            self.main_layout.insertWidget(self.graphics_index, widget, stretch=1)
            widget.show()

    def _sstv_attach(self):
        """Décodeur SSTV branché sur le son (sans ouvrir la fenêtre SSTV)."""
        if self.sstv_window is None:
            self.sstv_window = SstvWindow(self)
        if self.audio.sstv is None:
            self.audio.sstv = self.sstv_window.decoder
            self.sstv_window.timer.start()      # enregistre les images finies

    def _sstv_detach(self):
        win = self.sstv_window
        if win is not None and not win.isVisible() and self.audio.sstv is not None:
            win.refresh()
            self.audio.sstv = None
            win.timer.stop()

    def on_span_selected(self):
        if self.civ:
            self.civ.set_span(self.span_combo.currentData())

    def _update_markers(self):
        if self.freq_hz is None:
            return
        f = self.freq_hz / 1000
        low, high = PASSBANDS.get(base_mode(self.mode_combo.currentText()),
                                  (-1.5, 1.5))
        for line in self.tuned_lines:
            line.setPos(f)
        for band in self.passbands:
            band.setRegion((f + low, f + high))

    def on_floor_changed(self, value):
        if not self.auto_check.isChecked():
            self.wf_low = value

    def on_spectrum(self, db, rms):
        if self.view != "audio":
            return
        self.avg = db if self.avg is None else 0.6 * self.avg + 0.4 * db
        k = self.visible_bins()
        visible = self.avg[:k]
        self.spec_curve.setData(np.arange(k) * BIN_HZ, visible)
        self._add_waterfall_row(db[:k], visible)

    def _spy(self, text, stack=False):
        """Journal des changements de fréquence (freq.log) : qui, quand, refus."""
        try:
            who = ""
            if stack:
                import inspect
                who = " par " + " < ".join(f.function for f in inspect.stack()[2:6])
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freq.log")
            if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
                os.replace(path, path + ".1")       # journal gardé à taille raisonnable
            with open(path, "a") as log:
                log.write(f"{datetime.datetime.now():%H:%M:%S.%f} {text} "
                          f"{self.mode_combo.currentText()}{who}\n")
        except Exception:
            pass

    def on_frequency(self, hz):
        """Fréquence annoncée par la radio. Tant que la radio n'a pas confirmé
        la dernière fréquence demandée, ce qu'elle annonce d'autre est un
        ancien état en retard : on l'ignore (l'affichage ne recule jamais)."""
        now = time.monotonic()
        pending = getattr(self, "_pending", None)
        if pending:
            if hz == pending[0]:
                self._pending = None            # confirmé par la radio
            elif now - pending[1] < ECHO_TIMEOUT_S:
                return                          # écho en retard : ignoré
            else:
                self._pending = None            # la radio n'a pas pris la commande
                self._spy(f"RADIO n'a pas pris {pending[0]}, reste sur {hz}")
        if hz != self.freq_hz:
            # la radio a changé d'elle-même (son bouton) : c'est le nouveau choix
            self._spy(f"RADIO {self.freq_hz} -> {hz}")
            self._chosen = (hz, now)
        self._apply_frequency(hz)

    def _apply_frequency(self, hz):
        if hz != self.freq_hz:
            self.audio.ssb_tuner.request_reset()    # le son d'avant ne vaut plus
            self._set_khz_candidates(hz)
            if self.cw_hunter.active and not self.cw_hunter.is_own(hz) \
                    and hz != self.ssb_target:      # bouton tourné : balayage CW arrêté
                self.cw_hunter.stop()
                self.cw_info.setText("Balayage arrêté (réglage à la main) : décodage sur place")
            if self.scanner.active and not self.scanner.is_own(hz) \
                    and hz != self.ssb_target:      # bouton tourné : scan arrêté
                self.scanner.stop()
                self.statusBar().showMessage("Scan arrêté (réglage à la main)", 4000)
            if self.hunter.active and not self.hunter.is_own(hz) \
                    and hz != self.ssb_target:      # bouton tourné : on arrête
                self.hunter.stop()
                self.statusBar().showMessage("Recherche arrêtée (réglage à la main)", 4000)
            if hz != self.ssb_target:               # changé à la main
                self.ssb_recentred = False
                self.ssb_anchor = None
                self.ssb_pull_until = 0.0           # le rattrapage s'arrête
                self.ssb_meter.pull_led = "off"
                if self._detect_allowed():
                    self.detect_timer.start()       # mode reconnu quand on lâche
                if self.audio.ssb:
                    self.ssb_meter.set_state("search", status="attente de voix")
                    self.snap_timer.start()         # arrondi quand on lâche le bouton
        self.freq_hz = hz
        self.freq_label.setText(format_frequency(hz))
        self.m_freq.setText(format_frequency(hz))
        self._update_markers()
        band = band_of(hz)
        for name, button in self.band_buttons.items():
            button.setChecked(name == band)
        self.band_selector.set_band(band)
        self.m_bands.set_band(band)                 # écran MOBILE
        if band != self.last_band:          # nouvelle bande : bande latérale d'usage
            self.last_band = band
            if hasattr(self, "sideband_button"):
                self._usual_sideband()
        self._auto_decoder()

    def _remember_band(self):
        """Note la fréquence et le mode actuels pour la bande en cours."""
        band = self.freq_hz and band_of(self.freq_hz)
        if band:
            self.band_memory[band] = [self.freq_hz, self.mode_combo.currentText()]
            try:
                os.makedirs(os.path.dirname(BANDS_FILE), exist_ok=True)
                with open(BANDS_FILE, "w") as f:
                    json.dump(self.band_memory, f)
            except OSError:
                pass

    def _band_selector_changed(self, name):
        """Commutateur de bandes tourné : même effet qu'une touche de bande."""
        if name in self.band_buttons:
            self.on_band(name)
        if not self.civ or self.tx_active:      # refusé : le bouton revient
            self.band_selector.set_band(band_of(self.freq_hz or 0))
            self.m_bands.set_band(band_of(self.freq_hz or 0))

    def on_band(self, name):
        if not self.civ or self.tx_active:
            self.band_buttons[name].setChecked(name == band_of(self.freq_hz or 0))
            return
        self._remember_band()
        default = next(b for b in BANDS if b[0] == name)
        hz, mode = self.band_memory.get(name, (default[3], default[4]))
        if mode in ("AM", "AM-D", "FM", "FM-D") and hz < 28_000_000:
            mode = usual_sideband(hz)       # pas d'AM/FM rappelée en décamétrique
        if mode in MODE_NAMES and mode != self.mode_combo.currentText():
            self.mode_combo.setCurrentText(mode)
            self._sync_mode_buttons()
            self.civ.set_mode(mode)
        self.tune_to(hz)

    def on_paddle_toggled(self, on):
        app = QtWidgets.QApplication.instance()
        if on:
            if self.mode_combo.currentText() not in ("CW", "CW-R") or not self.civ:
                self.paddle_button.setChecked(False)
                self.statusBar().showMessage("Paddle clavier : passe d'abord la radio en CW")
                return
            self.paddle.wpm = self.paddle_wpm.value()
            self.civ.set_key_speed(self.paddle.wpm)
            self.paddle_sent = ""
            self.paddle.start()
            app.installEventFilter(self.paddle_keys)
            self.statusBar().showMessage(
                "Paddle clavier : Ctrl gauche = points, Ctrl droit = traits. "
                "Chaque lettre part à la radio, qui l'émet.")
        else:
            app.removeEventFilter(self.paddle_keys)
            self.paddle.stop()
            self.statusBar().showMessage("Paddle clavier arrêté")

    def on_paddle_wpm(self, wpm):
        self.paddle.wpm = wpm
        if self.paddle_button.isChecked() and self.civ:
            self.civ.set_key_speed(wpm)

    def on_paddle_char(self, c):
        if not self.paddle_button.isChecked() or not self.civ:
            return
        if self.mode_combo.currentText() not in ("CW", "CW-R"):
            self.statusBar().showMessage("Paddle : la radio n'est plus en CW, rien d'émis")
            return
        self.civ.send_cw(c)
        self.paddle_sent = (self.paddle_sent + c)[-60:]
        self.statusBar().showMessage(f"Émis : {self.paddle_sent}")

    def on_mode(self, name):
        self.mode_combo.setCurrentText(name)
        self._sync_mode_buttons()
        self._update_markers()

    def _ssb_sign(self):
        """+1 en USB, -1 en LSB, None ailleurs (pas de calage BLU)."""
        return {"USB": 1, "LSB": -1}.get(self.mode_combo.currentText())

    def _update_ssb(self):
        """Calage BLU actif seulement en LSB/USB, case cochée, hors émission."""
        sign = self._ssb_sign()
        if not hasattr(self, "ssb_auto"):
            return                      # fenêtre pas encore construite
        active = bool(sign and self.ssb_auto.isChecked()
                      and not getattr(self, "tx_active", False))
        if active and self.audio.ssb is None:
            self.audio.ssb_tuner.request_reset()
            self.ssb_meter.set_state("search", status="attente de voix")
            self.ssb_anchor = None
            self.snap_timer.start()
        elif not active:
            self.ssb_meter.set_state("off")
        self.audio.ssb_tuner.mirror = self.sideband_button.isChecked()
        self.audio.ssb = self.audio.ssb_tuner if active else None
        self.ssb_auto.setEnabled(bool(sign))
        self._set_khz_candidates(self.freq_hz)  # LSB/USB : le signe des écarts change

    def on_ssb_state(self, estimate, status, locked):
        self.ssb_estimate = 0.0 if locked else estimate
        if self.audio.ssb is None:
            return
        if status != getattr(self, "_last_ssb_status", None):
            self._last_ssb_status = status      # journal : pourquoi pas de correction
            est = "-" if estimate is None else f"{estimate:+.0f}"
            self._log_calage(f"etat « {status} » aiguille {est}")
        if locked:
            self.ssb_meter.set_state("locked", 0, status)
            if self.ssb_meter.pull_led == "search":
                self.ssb_meter.pull_led = "locked"   # calage parfait par le rattrapage
        elif estimate is None:
            if not self.ssb_recentred:      # après une correction : reste sur 0
                self.ssb_meter.set_state("search", status=status)
        else:
            self.ssb_meter.set_state("measure", estimate, status)

    def on_sideband_auto(self, on):
        self.sideband_led.set_color("#2ecc40" if on else "#c62828")
        if on:
            self._usual_sideband()
        self._update_ssb()

    def _usual_sideband(self):
        """En LSB/USB, prend la bande latérale d'usage pour la fréquence."""
        if not self.sideband_button.isChecked() or not self.civ or self.tx_active:
            return
        current = self.mode_combo.currentText()
        wanted = usual_sideband(self.freq_hz)
        if current in ("LSB", "USB") and wanted and wanted != current:
            self._set_sideband(wanted)

    def _set_sideband(self, name):
        self.mode_combo.setCurrentText(name)
        self.civ.set_mode(name)
        self._sync_mode_buttons()
        self._update_markers()
        self.statusBar().showMessage(f"Bande latérale automatique : {name}", 4000)

    def band_of_freq(self):
        return band_of(self.freq_hz) if self.freq_hz else None

    def set_mode_by_hunter(self, name):
        if self.civ:
            self._set_sideband(name)

    def on_hunt_toggled(self, on):
        if on and self.scanner.resume():            # scan verrouillé : on le libère
            self.hunt_button.blockSignals(True)
            self.hunt_button.setChecked(False)
            self.hunt_button.blockSignals(False)
            self._hunt_blinking(False)
            return
        if on and not self.hunter.active:
            if not self.civ or self.tx_active:
                self.hunt_button.setChecked(False)
                return
            if self.scanner.active:                 # une seule recherche à la fois
                self.scan_button.setChecked(False)
            self.statusBar().showMessage("Recherche : démarrage de Whisper…")
            self.hunter.start()
        elif not on and self.hunter.active:
            self.hunter.stop()
            self.statusBar().showMessage("Recherche arrêtée", 4000)

    def on_hunt_status(self, text):
        self.statusBar().showMessage(text)
        if "balayage" in text or "calage de la voix" in text \
                or ("arrêt" in text and "arrêt 10 s" not in text):
            return                      # pas chaque kHz ni chaque seconde au journal
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "recherche.log"), "a") as log:
                log.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
        except OSError:
            pass

    # --- scan ---------------------------------------------------------
    def on_scan_toggled(self, on):
        if on:
            if not self.civ or self.tx_active:
                self.scan_button.setChecked(False)
                return
            if self.hunter.active:                  # une seule recherche à la fois
                self.hunt_button.setChecked(False)
            self.scan_timer.start(500)
            self.scanner.start()
        else:
            self.scanner.stop()
            self._scan_stopped()

    def _scan_stopped(self):
        self.scan_timer.stop()
        self.scan_button.setStyleSheet(PUSH_3D)

    def _blink_scan(self):
        self.scan_blink = not self.scan_blink
        self.scan_button.setStyleSheet(PUSH_3D + (HUNT_DARK if self.scan_blink else ""))

    def on_console_toggled(self, on):
        """Terminal visible par-dessus Scope, ou renvoyé derrière."""
        if not on:
            console.hide_console()
            self.activateWindow()
            return
        # la 1re fois, la console est rangée en bas à droite du waterfall ;
        # ensuite on respecte la place où on l'a mise
        geo = QtWidgets.QApplication.primaryScreen().geometry()
        screen = None       # taille et place de la console réglées à la main
        if console.show_console(screen):
            self._console_placed = True
        else:
            # terminal tout juste ouvert : on le met au-dessus quand il apparaît
            QtCore.QTimer.singleShot(1500, lambda: self.console_button.isChecked()
                                     and console.show_console(screen))
            self._console_placed = True

    # --- RECH MAN : retour sur les stations entendues ---------------------
    def on_station_heard(self, hz, side):
        stations = [st for st in self.heard_stations if abs(st[0] - hz) > 1500]
        stations.append((hz, side))
        self.heard_stations = stations[-50:]
        self.heard_index = self.heard_origin = len(self.heard_stations) - 1

    def on_manual_step(self, direction):
        if not self.civ or self.tx_active:
            return
        scanning = self.scanner.active or self.hunter.active
        if self.scanner.active:                     # arrêt volontaire du scan
            self.scan_button.setChecked(False)
        if self.hunter.active:
            self.hunt_button.setChecked(False)
        # sur une station mémorisée par le scan : on parcourt la liste ;
        # sinon (pas de scan, bouton tourné) : station la plus proche du curseur
        on_list = (0 <= self.heard_index < len(self.heard_stations) and self.freq_hz
                   and (scanning or abs(self.freq_hz - self.heard_stations[
                       self.heard_index][0]) <= 1500))
        new = self.heard_index + direction
        if not on_list or not 0 <= new < len(self.heard_stations):
            self._start_seek(direction)
            return
        self.seek_active = False
        self.manual_seek_hz = None
        self.heard_index = new
        hz, side = self.heard_stations[new]
        if self.mode_combo.currentText() != side:
            self._set_sideband(side)
        self.tune_to(hz)
        self.manual_left = MANUAL_HOLD_S
        self.manual_button.setChecked(True)
        self.manual_timer.start(500)
        self._manual_show()
        self._start_station_lock(hz)

    def on_manual_stay(self):
        """Appui sur la plaque RECH MAN : on fixe l'écoute ici, tout balayage arrêté."""
        busy = (self.manual_timer.isActive() or self.seek_active
                or self.scanner.active or self.hunter.active)
        if self.scanner.active:
            self.scan_button.setChecked(False)
        if self.hunter.active:
            self.hunt_button.setChecked(False)
        self.seek_active = False
        self.manual_timer.stop()
        self.manual_button.setChecked(False)
        self.manual_button.setStyleSheet(PUSH_3D + GLUE_MID)
        self.manual_button.setText(RECH_MAN_TEXT)
        if busy and self.freq_hz:
            self.statusBar().showMessage(f"Écoute fixée sur {self.freq_hz / 1e6:.4f} MHz "
                                         "(balayage arrêté)", 6000)

    # recherche de la station la plus proche, vers le haut (+) ou le bas (−)
    def _start_seek(self, direction):
        if self.view != "rf":
            self.statusBar().showMessage("RECH MAN : passer en vue « RF (scope radio) » "
                                         "pour chercher une station", 5000)
            return
        self.manual_timer.stop()
        self.seek_active = True
        self.seek_dir = direction
        self.seek_jumps = 0
        self.seek_target = self.freq_hz
        self.manual_seek_hz = None
        band = band_of(self.freq_hz or 0)
        edges = next(((lo, hi) for name, lo, hi, _, _ in BANDS if name == band), None)
        self.seek_edges = edges or (MIN_FREQ, MAX_FREQ)
        self.manual_button.setChecked(True)
        self.manual_button.setText("cherche " + ("+" if direction > 0 else "−"))
        self.statusBar().showMessage("RECH MAN : recherche de la station la plus proche "
                                     + ("au-dessus…" if direction > 0 else "en dessous…"))
        self._seek_look()

    def _seek_look(self):
        if not self.seek_active:
            return
        cur = self.freq_hz
        if cur and self.seek_target and abs(cur - self.seek_target) > 2000:
            self._seek_end("RECH MAN : recherche arrêtée (réglage à la main)")
            return
        if not self.scope_edges or self.avg is None or not cur:
            QtCore.QTimer.singleShot(500, self._seek_look)
            return
        low, high = self.scope_edges
        side = self.mode_combo.currentText()
        ssb = side in ("LSB", "USB")
        margin = 1500 if ssb else 150               # pas la station où l'on est déjà
        lo_edge, hi_edge = self.seek_edges
        ahead = [hz for hz in find_signals(self.avg, low, high, side)
                 if (hz - cur) * self.seek_dir > margin
                 and low + 1000 <= hz <= high - 1000 and lo_edge <= hz <= hi_edge]
        if ahead:
            hz = min(ahead, key=lambda f: abs(f - cur))
            self.seek_active = False
            self.manual_seek_hz = hz
            self.tune_to(hz)
            self.manual_left = MANUAL_HOLD_S
            self.manual_timer.start(500)
            self._manual_show()
            self._start_station_lock(hz)
            return
        # rien en vue : on avance d'un bon morceau de scope (avec recouvrement)
        jump = int((high - low) * 0.4) // 1000 * 1000 or 1000
        nxt = cur + jump * self.seek_dir
        self.seek_jumps += 1
        if not lo_edge <= nxt <= hi_edge or self.seek_jumps > 60:
            self._seek_end("RECH MAN : aucune station trouvée jusqu'au bord de la bande")
            return
        self.seek_target = nxt
        self.tune_to(nxt)
        QtCore.QTimer.singleShot(2500, self._seek_look)     # scope rafraîchi

    # --- RECH MAN : se caler sur la station trouvée (mode + fréquence exacte) ---
    def _start_station_lock(self, hz):
        self.lock_id = getattr(self, "lock_id", 0) + 1
        self.lock_hz = hz
        lock = self.lock_id
        # le scope doit d'abord se rafraîchir sur la nouvelle fréquence (réseau)
        QtCore.QTimer.singleShot(2500, lambda: self._station_lock(lock, 1))

    def _lock_valid(self, lock):
        return (lock == getattr(self, "lock_id", 0) and self.freq_hz and not self.tx_active
                and abs(self.freq_hz - self.lock_hz) <= 3000)   # pas retouché à la main

    def _station_lock(self, lock, attempt):
        if not self._lock_valid(lock):
            return
        if self.view != "rf" or self.avg is None or not self.scope_edges:
            if attempt < 3:
                QtCore.QTimer.singleShot(1500, lambda: self._station_lock(lock, attempt + 1))
            return
        result = analyse_station(self.avg, *self.scope_edges, self.freq_hz)
        if not result:
            if attempt < 3:                 # signal pas encore assez moyenné
                QtCore.QTimer.singleShot(1500, lambda: self._station_lock(lock, attempt + 1))
            else:
                self.statusBar().showMessage("RECH MAN : mode de la station non reconnu",
                                             5000)
            return
        mode, hz = result
        if not self._calage_ok(hz):
            return
        current = self.mode_combo.currentText()
        if mode == "CW" and current == "CW-R":
            mode = "CW-R"
        if mode != current:
            self._set_sideband(mode)
        if mode in ("LSB", "USB"):
            # la voix finit le calage au Hz près (calage auto BLU)
            if not self.ssb_auto.isChecked():
                self.ssb_auto.setChecked(True)
        if mode in ("AM", "FM"):
            self.snap_timer.stop()
        self.lock_hz = hz
        if abs(hz - self.freq_hz) >= 10:
            self.ssb_target = hz
            self.tune_to(hz, calage=True)
        self._log_calage(f"rech man {mode} {hz}")
        self.statusBar().showMessage(
            f"RECH MAN : station en {mode} sur {format_frequency(hz)} MHz", 6000)
        if mode in ("CW", "CW-R"):
            # affinage à l'oreille du décodeur : note mesurée → pitch de la radio
            if not self.decoder_auto.isChecked():
                self.decoder_auto.setChecked(True)
            QtCore.QTimer.singleShot(3000, lambda: self._cw_fine_lock(lock, 1))

    def _cw_fine_lock(self, lock, attempt):
        if not self._lock_valid(lock):
            return
        if self.cw_note is None:
            if attempt < 4:
                QtCore.QTimer.singleShot(2000, lambda: self._cw_fine_lock(lock, attempt + 1))
            return
        offset = self.cw_note - self.radio_cw_pitch
        if abs(offset) > 250:
            # note trop loin du pitch : le décodeur entend autre chose, on n'y touche pas
            self._log_calage(f"rech man cw ignore {offset:+.0f}")
            return
        if abs(offset) <= 8:
            self.statusBar().showMessage(
                f"RECH MAN : CW calée au Hz sur {format_frequency(self.freq_hz)} MHz "
                f"(note {self.cw_note:.0f} Hz)", 6000)
            return
        sign = -1 if self.mode_combo.currentText() == "CW-R" else 1
        hz = int(round(self.freq_hz + sign * offset))
        if not self._calage_ok(hz):
            return
        self.lock_hz = hz
        self._log_calage(f"rech man cw affine {offset:+.0f}")
        self.tune_to(hz, calage=True)
        if attempt < 4:                     # on vérifie après le réglage
            QtCore.QTimer.singleShot(2500, lambda: self._cw_fine_lock(lock, attempt + 1))

    def _seek_end(self, text):
        self.seek_active = False
        self.manual_button.setChecked(False)
        self.manual_button.setStyleSheet(PUSH_3D + GLUE_MID)
        self.manual_button.setText(RECH_MAN_TEXT)
        self.statusBar().showMessage(text, 6000)

    def _manual_show(self):
        if self.manual_seek_hz:
            sign = "+" if self.seek_dir > 0 else "−"
            self.manual_button.setText(f"{sign} · {self.manual_left} s")
            self.statusBar().showMessage(
                f"RECH MAN : station la plus proche sur {self.manual_seek_hz / 1e6:.4f} "
                f"MHz, arrêt {self.manual_left} s")
            return
        rel = self.heard_index - self.heard_origin
        hz = self.heard_stations[self.heard_index][0]
        self.manual_button.setText(f"{rel:+d} · {self.manual_left} s" if rel
                                   else f"0 · {self.manual_left} s")
        self.statusBar().showMessage(
            f"RECH MAN : station {rel:+d} sur {hz / 1e6:.4f} MHz "
            f"({self.heard_index + 1}/{len(self.heard_stations)}), "
            f"arrêt {self.manual_left} s")

    def _manual_tick(self):
        self.manual_blink = not self.manual_blink
        self.manual_button.setStyleSheet(PUSH_3D + GLUE_MID
                                         + (HUNT_DARK if self.manual_blink else ""))
        if self.manual_blink:
            return                                  # une seconde = deux clignotements
        self.manual_left -= 1
        if self.manual_left > 0:
            self._manual_show()
            return
        self.manual_timer.stop()
        self.manual_button.setStyleSheet(PUSH_3D + GLUE_MID)
        self.manual_button.setChecked(False)
        self.manual_button.setText(RECH_MAN_TEXT)
        self.statusBar().showMessage("RECH MAN : 20 s écoulées, on reste sur cette "
                                     "station (− / + pour changer)", 6000)

    def on_scan_finished(self, found):
        self.scan_button.blockSignals(True)
        self.scan_button.setChecked(False)
        self.scan_button.blockSignals(False)
        self._scan_stopped()
        if found:
            self.statusBar().showMessage("Scan arrêté : on reste sur le QSO français")

    def on_scan_found(self, hz, text):
        QtWidgets.QApplication.beep()
        self.statusBar().showMessage(
            f"QSO français sur {hz / 1e6:.3f} MHz : écoute verrouillée — "
            "appuyer sur CHERCHER QSO FR pour reprendre le scan")

    # --- décodage CW -------------------------------------------------
    def on_cw_toggled(self, on):
        if on:
            if not self.civ or self.tx_active:
                self.cw_button.setChecked(False)
                return
            if self.hunter.active:                  # une seule recherche à la fois
                self.hunter.stop()
            if self.scanner.active:
                self.scan_button.setChecked(False)
            self._cw_view(True)
            self.cw_text.clear()
            self.decoder_combo.setCurrentIndex(self.decoder_combo.findData("cw"))
            # décodage SUR PLACE : la fréquence choisie ne bouge pas (plus de
            # balayage automatique de la bande, qui déplaçait le VFO)
            self.cw_info.setText(f"Décodage CW sur {format_frequency(self.freq_hz or 0)} MHz "
                                 "(sur place, la fréquence ne bouge pas)")
        else:
            self.cw_hunter.stop()
            self._cw_view(False)

    def _cw_view(self, on):
        """Bascule : grande fenêtre de décodage ↔ boutons et réglages habituels."""
        self.cw_view_active = on
        self.below.setVisible(not on)
        self.cw_frame.setVisible(on)
        if on:      # le bouton suit dans la fenêtre de décodage pour l'arrêter
            self.cw_bottom.addWidget(self.cw_button)
            self.cw_button.setMinimumWidth(260)
            self.cw_button.setMinimumHeight(40)
        else:
            self.cw_blink_timer.stop()
            self.cw_button.setText("DÉCODAGE CW")
            self.cw_button.setStyleSheet(PUSH_3D)
            self.cw_button.setMinimumWidth(58)
            self.cw_button.setMinimumHeight(0)
            self.extras_layout.addWidget(self.cw_button, 0, 2)
            self.cw_info.setText("")

    def on_cw_status(self, text):
        self.cw_info.setText(text)
        self.statusBar().showMessage(text)

    def on_cw_countdown(self, left):
        """Arrêt de 20 s sur un signal : le bouton clignote, décompte au centre."""
        if left > 0:
            self.cw_button.setText(f"DÉCODAGE CW   {left} s")
            if not self.cw_blink_timer.isActive():
                self.cw_blink_timer.start(500)
        else:
            self.cw_blink_timer.stop()
            self.cw_button.setText("DÉCODAGE CW")
            self.cw_button.setStyleSheet(PUSH_3D)

    def _blink_cw(self):
        self.cw_blink = not self.cw_blink
        self.cw_button.setStyleSheet(PUSH_3D + (HUNT_DARK if self.cw_blink else ""))

    def on_cw_finished(self):
        self.cw_blink_timer.stop()
        if self.cw_button.isChecked():  # arrêt du balayage (bouton tourné) : on reste
            self.cw_button.setText("DÉCODAGE CW")     # en décodage sur place
            self.cw_button.setStyleSheet(PUSH_3D)

    def on_rnnoise(self, on):
        """RNNoise : son de la radio filtré vers les haut-parleurs, son direct coupé."""
        if on:
            if self.rmnoise_button.isChecked():     # un seul filtre à la fois
                self.rmnoise_button.setChecked(False)
            error = rnnoise_radio.on(self.audio.source)
            if error:
                self.statusBar().showMessage(f"RNNoise : {error}", 6000)
                self.rnnoise_button.blockSignals(True)
                self.rnnoise_button.setChecked(False)
                self.rnnoise_button.blockSignals(False)
                return
            # le son direct n'est pas coupé : il reste une part d'origine, dosée
            # automatiquement selon la force du signal
            self.mute_check.setChecked(False)
            self.rnn_mix = RNN_MIX_WEAK
            self._apply_direct_volume()
            self.rnn_timer.start(1000)
            self.clean_volume.setEnabled(True)
            self.clean_knob.setEnabled(True)
            rnnoise_radio.set_volume(round(self.clean_volume.value()
                                           * self._preamp_factor()))
            self.statusBar().showMessage("RNNoise en marche : son filtré + une part "
                                         "d'origine dosée selon le signal", 5000)
        else:
            rnnoise_radio.off()
            self.rnn_timer.stop()
            self.clean_volume.setEnabled(False)
            self.clean_knob.setEnabled(False)
            self.rnnoise_button.setText("RNNOISE")
            self._apply_direct_volume()
            self.mute_check.setChecked(False)
            self.statusBar().showMessage("RNNoise arrêté : son direct de la radio", 4000)

    def on_clean_volume(self, value):
        self.clean_volume_label.setText(f"{value} %")
        self.clean_knob.setValue(value)
        if self.rnnoise_button.isChecked():
            rnnoise_radio.set_volume(round(value * self._preamp_factor()))

    def _update_rnn_mix(self):
        """Dosage de la part d'origine selon le S-mètre (lissé)."""
        raw = self.s_raw_avg
        t = min(1.0, max(0.0, (raw - RNN_RAW_WEAK) / (RNN_RAW_STRONG - RNN_RAW_WEAK)))
        target = RNN_MIX_WEAK + t * (RNN_MIX_STRONG - RNN_MIX_WEAK)
        mix = 0.7 * self.rnn_mix + 0.3 * target
        if abs(mix - self.rnn_mix) >= 0.01:
            self.rnn_mix = mix
            self._apply_direct_volume()
        self.rnnoise_button.setText(f"RNNOISE {round(self.rnn_mix * 100)} %")
        self.rnnoise_button.setToolTip(
            f"RNNoise : son filtré + {round(self.rnn_mix * 100)} % de son d'origine "
            "(plus de son d'origine quand le signal est faible). Recliquer pour arrêter.")

    def _apply_direct_volume(self):
        """Regroupe les changements rapides (bouton qu'on glisse) : le son suit
        en douceur, sans file d'attente de commandes pactl."""
        if not hasattr(self, "_volume_timer"):
            self._volume_timer = QtCore.QTimer(self)
            self._volume_timer.setSingleShot(True)
            self._volume_timer.timeout.connect(self._apply_direct_volume_now)
        if not self._volume_timer.isActive():
            self._volume_timer.start(30)

    def _apply_direct_volume_now(self):
        """Volume du son direct : Volume PC, réduit à la part d'origine sous RNNoise."""
        volume = self.pc_volume.value() * self._preamp_factor()
        if self.rnnoise_button.isChecked():
            volume = volume * self.rnn_mix
        self._pactl_stream("set-sink-input-volume", f"{round(volume)}%")

    def _preamp_factor(self):
        """Préampli BF : 0 → silence, 5 → ×1, 10 → ×3."""
        v = self.preamp_knob.value if hasattr(self, "preamp_knob") else 5.0
        return v / 5 if v <= 5 else 1 + (v - 5) * 0.4

    def on_preamp(self, value):
        f = self._preamp_factor()
        self.preamp_label.setText(f"PRÉAMPLI BF\nposition {value:.1f}".replace(".", ","))
        self.preamp_display.setText(f"{round(f * 100)}")
        self._apply_direct_volume()
        if self.rnnoise_button.isChecked():
            rnnoise_radio.set_volume(round(self.clean_volume.value() * f))

    def on_rmnoise(self, on):
        """RM Noise : lancé, branché sur le son de la radio, curseur à 100 %."""
        if on and self.rnnoise_button.isChecked():  # un seul filtre à la fois
            self.rnnoise_button.setChecked(False)
        if on:
            self.mute_check.setChecked(True)        # plus de son direct
            self.statusBar().showMessage("RM Noise : démarrage…")
            threading.Thread(target=self._rmnoise_start, daemon=True).start()
        else:
            rm_noise.stop()
            self.mute_check.setChecked(False)
            self.statusBar().showMessage("RM Noise arrêté : son direct de la radio", 4000)

    def _rmnoise_start(self):
        if not rm_noise.running():
            rm_noise.launch()
        speakers = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                  text=True).stdout.strip()
        routed = (False, False)
        for _ in range(60):                     # RM Noise met ~20 s à s'ouvrir
            routed = rm_noise.route(self.audio.source, speakers)
            if all(routed):
                break
            time.sleep(0.5)
        time.sleep(1.0)
        rm_noise.slider_full()
        text = ("RM Noise en marche à 100 % sur le son de la radio" if all(routed) else
                "RM Noise ouvert, mais son entrée/sortie son n'est pas encore branchée")
        QtCore.QMetaObject.invokeMethod(self.statusBar(), "showMessage",
                                        QtCore.Qt.QueuedConnection,
                                        QtCore.Q_ARG(str, text))

    def _hunt_blinking(self, on):
        if on:
            self.hunt_timer.start(500)
        else:
            self.hunt_timer.stop()
            self.hunt_button.setStyleSheet(self.hunt_style)

    def _blink_hunt(self):
        self.hunt_blink = not self.hunt_blink
        self.hunt_button.setStyleSheet(self.hunt_style + (HUNT_DARK if self.hunt_blink else ""))

    def on_hunt_holding(self, left):
        """Décompte des 20 s sur un QSO français ; 0 : bouton caché."""
        if left <= 0:
            self.stay_timer.stop()
            self.stay_button.setVisible(False)
            return
        self.stay_button.setText("QSO FR VERROUILLÉ" if left < 0 else f"RESTER ICI {left} s")
        if not self.stay_button.isVisible():
            self.stay_button.setVisible(True)
            self.stay_blink = True
            self._blink_stay()
            self.stay_timer.start(450)

    def _blink_stay(self):
        """Clignote : rouge vif / rouge sombre."""
        self.stay_blink = not self.stay_blink
        self.stay_button.setStyleSheet(POWER_OFF if self.stay_blink else STAY_DARK)

    def on_hunt_finished(self, found):
        self.hunt_button.blockSignals(True)
        self.hunt_button.setChecked(False)
        self.hunt_button.blockSignals(False)
        self._hunt_blinking(False)
        if found:
            self.statusBar().showMessage(
                "QSO français trouvé : on reste dessus — rappuyer sur CHERCHER QSO FR "
                "pour le suivant")

    def _whistle_text(self, on):
        self.whistle_check.setText("SIFFLEMENT " + ("ON" if on else "OFF"))

    def on_whistle_toggled(self, on):
        self._whistle_text(on)
        if on:
            self.whistle.start()
        else:
            self.whistle.on = False
            self.whistle.stop()

    def _update_whistle(self):
        """Le sifflement suit l'aiguille du cadran de calage."""
        meter = self.ssb_meter
        wanted = self.whistle_check.isChecked() and not self.tx_active
        if self.mode_combo.currentText() in ("CW", "CW-R"):
            # CW : écart exact entre la note de la station et le pitch de la radio
            self.whistle.precise = True
            self.whistle.on = wanted and self.cw_note is not None
            if self.cw_note is not None:
                self.whistle.offset = self.cw_note - self.radio_cw_pitch
            return
        self.whistle.on = (wanted and self.audio.ssb is not None
                           and meter.state in ("search", "measure"))
        if meter.state == "measure" and self.ssb_estimate is not None:
            self.whistle.precise = True             # écart mesuré, pas l'aiguille
            self.whistle.offset = self.ssb_estimate
        else:
            self.whistle.precise = False            # recherche : suit l'aiguille
            self.whistle.offset = meter.needle_hz()

    def _log_calage(self, text):
        try:                            # journal pour vérifier les corrections
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "calage.log"), "a") as log:
                log.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
                          f"{self.mode_combo.currentText()} {self.freq_hz} {text}\n")
        except OSError:
            pass

    def _detect_allowed(self):
        return (not self._sstv_busy() and hasattr(self, "detect_timer") and self.ssb_auto.isChecked()
                and not self.tx_active and self.view == "rf"
                and self.mode_combo.currentText() in ("LSB", "USB", "AM", "FM")
                and not (self.scanner.active or self.hunter.active
                         or self.cw_hunter.active))

    def _detect_mode(self):
        """Mode et fréquence exacte de la station sous le curseur (scope)."""
        if not self._detect_allowed() or self.avg is None or not self.scope_edges \
                or not self.freq_hz:
            return
        result = analyse_mode(self.avg, *self.scope_edges, self.freq_hz)
        if not result:
            if self._pulling():
                self._log_calage("detection : aucune station trouvée à ± 6 kHz")
            return
        mode, hz = result
        if not self._calage_ok(hz):
            self._spy(f"REFUS mode {mode} {hz} (fréquence verrouillée)")
            return
        current = self.mode_combo.currentText()
        if mode != current:
            self._set_sideband(mode)
        if mode in ("AM", "FM"):
            self.snap_timer.stop()                  # pas d'arrondi BLU ici
        if abs(hz - self.freq_hz) >= 10:
            self.ssb_target = hz
            self.tune_to(hz, calage=True)
        self._log_calage(f"mode {mode} {hz}")
        self.statusBar().showMessage(
            f"Calage auto : {mode} sur {format_frequency(hz)} MHz"
            + ("" if mode == current else f" (au lieu de {current})"), 5000)

    def _start_pull(self, on):
        """Fenêtre de rattrapage : la voix peut recaler jusqu'à ± PULL_MAX Hz
        (au lieu de ± FINE_MAX autour du kHz rond), pendant PULL_SECONDS."""
        self.ssb_pull_until = time.monotonic() + PULL_SECONDS if on else 0.0
        if on and self.freq_hz:             # demandé par l'opérateur : calage permis
            self._chosen = (self.freq_hz, time.monotonic())
        self.ssb_meter.pull_led = "search" if on else "off"
        # recherche élargie (± D_WIDE) pendant le rattrapage seulement
        self.audio.ssb_tuner.d_limit = D_WIDE if on else D_MAX
        self._set_khz_candidates(self.freq_hz)
        if on:
            QtCore.QTimer.singleShot(PULL_SECONDS * 1000, self._pull_narrow)
        if on:
            # pas de calage parfait à la fin du rattrapage : LED éteinte
            QtCore.QTimer.singleShot((PULL_SECONDS + 5) * 1000, self._pull_timeout)
            self.statusBar().showMessage(
                f"Calage auto BLU : rattrapage du correspondant ({PULL_SECONDS} s)", 5000)

    def _pull_narrow(self):
        if not self._pulling():
            self.audio.ssb_tuner.d_limit = D_MAX
            self.audio.ssb_tuner.candidates = None
            self.audio.ssb_tuner.fast = False   # fin du rattrapage : réglages habituels

    def _set_khz_candidates(self, hz):
        """Rattrapage : kHz ronds à ± D_WIDE de hz, en écarts d pour le calage voix."""
        sign = self._ssb_sign()
        tuner = self.audio.ssb_tuner
        if not hz or not sign:
            tuner.candidates = None
            tuner.round_ds = []
            return
        base = round(hz / 1000) * 1000
        ds = [(k - hz) * sign for k in range(base - 2000, base + 3000, 1000)
              if abs(k - hz) <= D_WIDE]
        tuner.round_ds = ds             # le kHz rond l'emporte en cas de doute
        tuner.candidates = ds if self._pulling() else None

    def _pull_timeout(self):
        if self.ssb_meter.pull_led == "search" and not self._pulling():
            self.ssb_meter.pull_led = "off"

    def _pulling(self):
        return time.monotonic() < self.ssb_pull_until

    def _snap_to_khz(self):
        """Les stations BLU sont presque toujours sur un kHz rond : on s'y cale."""
        if self.audio.ssb is None or self.tx_active or self.freq_hz is None:
            return
        target = round(self.freq_hz / 1000) * 1000
        if self.ssb_target is not None and self.freq_hz == self.ssb_target \
                and abs(self.freq_hz - target) <= FINE_MAX:
            self.ssb_anchor = target        # fréquence posée par le calage voix :
            return                          # l'arrondi ne la défait pas
        self.ssb_anchor = target
        if target == self.freq_hz:
            self.ssb_recentred = True
            self.ssb_meter.set_state("locked", 0, "calé sur le kHz rond")
            return
        if not self._calage_ok(target):
            return                      # fréquence verrouillée : on n'y touche plus
        self._log_calage(f"arrondi {target - self.freq_hz:+d}")
        self.statusBar().showMessage(
            f"Calage BLU : kHz rond {format_frequency(target)}", 4000)
        self.ssb_target = target
        self.ssb_recentred = True
        self.tune_to(target, calage=True)
        self.ssb_meter.set_state("locked", 0, "calé sur le kHz rond")

    def _sstv_busy(self):
        """Décodage SSTV en cours : le calage BLU sur la voix ne doit pas jouer."""
        return self.audio.sstv is not None

    def on_ssb_correct(self, kind, shift):
        if self._sstv_busy():
            return
        sign = self._ssb_sign()
        if not sign or self.audio.ssb is None or self.tx_active or self.freq_hz is None:
            return
        if kind == "flip":
            if not self.sideband_button.isChecked():
                return
            # le correspondant est sur l'autre bande latérale : on y passe,
            # la porteuse est à « shift » Hz ; le calage fin suit
            carrier = self.freq_hz + sign * round(shift)
            if not self._calage_ok(carrier):
                return
            self._set_sideband("LSB" if sign > 0 else "USB")
            self._log_calage(f"bascule, porteuse {shift:+.0f}")
            self.ssb_target = carrier
            self.ssb_recentred = False
            self.ssb_anchor = None
            self.ssb_meter.set_state("search", status="autre bande latérale, recalage…")
            self.tune_to(carrier, calage=True)
            self.snap_timer.start()
            return
        target = self.freq_hz + sign * round(shift)
        if not self._calage_ok(target):
            self._log_calage(f"verrou {shift:+.0f}")
            return
        if self._pulling():
            # rattrapage : on suit la voix du correspondant, même hors du kHz rond
            if abs(shift) > PULL_MAX:
                self._log_calage(f"rattrapage refusé {shift:+.0f}")
                return
            self.ssb_anchor = target            # nouvelle référence : la vraie fréquence
            if target % 1000 == 0 and self.audio.ssb_tuner.candidates:
                # kHz rond trouvé : fin du rattrapage, affinage normal autour
                self.ssb_pull_until = 0.0
                self.audio.ssb_tuner.d_limit = D_MAX
                self.audio.ssb_tuner.candidates = None
                self._log_calage(f"rattrapage : kHz rond {target}")
                self.statusBar().showMessage(
                    f"Calage auto BLU : station trouvée sur {format_frequency(target)} MHz", 6000)
        elif self.ssb_anchor is None or abs(target - self.ssb_anchor) > FINE_MAX:
            # trop loin du kHz rond : sans doute une erreur, on ne bouge pas
            self._log_calage(f"refus {shift:+.0f}")
            return
        self._log_calage(f"affinage {shift:+.0f}")
        self.ssb_meter.set_state("measure", shift, f"correction {shift:+.0f} Hz")
        self.statusBar().showMessage(f"Calage BLU : correction de {shift:+.0f} Hz", 4000)
        self.ssb_target = target
        self.ssb_recentred = True
        self.tune_to(self.ssb_target, calage=True)
        self.ssb_meter.set_state("locked", 0, "recalé, vérification…")

    def _auto_decoder(self):
        """Ouvre le décodeur du mode quand le mode (ou la zone FT8) change ;
        entre deux changements, un choix fait à la main est respecté."""
        self._update_ssb()
        name = auto_decoder_for(self.mode_combo.currentText(), self.freq_hz)
        if name == self.auto_decoder:
            return
        self.auto_decoder = name
        index = 0 if name is None else self.decoder_combo.findData(name)
        if index >= 0 and index != self.decoder_combo.currentIndex():
            self.decoder_combo.setCurrentIndex(index)

    def _sync_mode_buttons(self):
        current = self.mode_combo.currentText()
        if (self.cw_station is not None and self.cw_station.isVisible()
                and current not in ("CW", "CW-R")):
            self._cw_station_close()
        self._auto_decoder()
        for name, button in self.mode_buttons.items():
            button.setChecked(name == current)

    def on_mode_button(self, name):
        if not self.civ or self.tx_active:
            self._sync_mode_buttons()
            return
        current = self.mode_combo.currentText()
        if (name == "CW" and current == "CW"
                and (self.cw_station is None or not self.cw_station.isVisible())):
            self._cw_station_open()             # écran fermé par RETOUR : on le rouvre
            return
        if name == current:
            # second appui sur le mode en cours : retour au mode d'avant
            back = getattr(self, "previous_mode", None)
            if not back or back == current:
                back = usual_sideband(self.freq_hz or 7_000_000)
            name = back
        self.previous_mode = current
        self.mode_combo.setCurrentText(name)
        self.on_mode_selected(name)
        if name == "CW":
            self._cw_station_open()

    def tune_to(self, hz, calage=False):
        """Seule porte d'entrée pour changer la fréquence depuis le Scope.
        calage=True : correction automatique (arrondi, calage BLU/CW, mode
        reconnu). Elle n'est permise que dans les CALAGE_WINDOW_S secondes
        qui suivent le choix de la fréquence et à moins de CALAGE_MAX_HZ de
        celle-ci ; sinon elle est refusée et la fréquence ne bouge pas."""
        if not self.civ:
            return False
        hz = int(hz)
        if not MIN_FREQ <= hz <= MAX_FREQ:
            self.statusBar().showMessage(
                f"Hors de la plage de la radio ({MIN_FREQ // 1000}–"
                f"{MAX_FREQ // 1_000_000} MHz)")
            return False
        now = time.monotonic()
        chosen = getattr(self, "_chosen", None)
        if calage:
            if not self._calage_ok(hz):
                self._spy(f"REFUS calage {self.freq_hz} -> {hz} (fréquence verrouillée)",
                          stack=True)
                return False
        else:
            self._chosen = (hz, now)            # nouvelle fréquence choisie
        self._pending = (hz, now)               # en attente de confirmation radio
        self._spy(f"SCOPE {self.freq_hz} -> {hz}{' calage' if calage else ''}", stack=True)
        self._apply_frequency(hz)
        self.civ.set_frequency(hz)
        return True

    # --- FIXE / MOBILE ------------------------------------------------------
    @staticmethod
    def _big(widget, zoom):
        """Le même cadran, agrandi zoom fois (dessin et souris compris)."""
        scene = QtWidgets.QGraphicsScene()
        scene.setBackgroundBrush(QtGui.QColor("#15181c"))      # fond de l'écran MOBILE
        widget.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        proxy = scene.addWidget(widget)
        proxy.setScale(zoom)
        view = QtWidgets.QGraphicsView(scene)
        view.setStyleSheet("background: transparent; border: none;")
        view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        view.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        w, h = round(widget.width() * zoom), round(widget.height() * zoom)
        scene.setSceneRect(0, 0, w, h)
        view.setFixedSize(w + 2, h + 2)
        return view

    def _mobile_page(self):
        """Écran MOBILE : l'essentiel en grand (fréquence, bandes, arrêt d'urgence,
        waterfall, S-mètre, VFO, EMISSION, QSO en français, fonctions VOX)."""
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: #15181c;")
        box = QtWidgets.QVBoxLayout(page)
        box.setContentsMargins(16, 8, 16, 4)
        box.setSpacing(6)
        # 1re ligne : fréquence, commutateur de bandes, arrêt d'urgence
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(30)
        top.addStretch()
        self.m_smeter = VintageSMeter()             # S-mètre en haut à gauche
        top.addWidget(self._big(self.m_smeter, 1.3), 0, QtCore.Qt.AlignVCenter)
        self.m_freq = NixieDisplay(800, 170)        # tubes Nixie ; molette = fréquence
        self.m_freq.tuned.connect(self.on_tuned)
        top.addWidget(self.m_freq, 0, QtCore.Qt.AlignVCenter)
        self.m_bands = BandSelector(BAND_SEL_PX)
        self.m_bands.changed.connect(self._band_selector_changed)
        top.addWidget(self._big(self.m_bands, 1.15), 0, QtCore.Qt.AlignVCenter)
        self.m_emergency = EmergencyButton(EMERGENCY_PX)
        self.m_emergency.pressed.connect(self.on_emergency)
        top.addWidget(self._big(self.m_emergency, 2.0), 0, QtCore.Qt.AlignVCenter)
        top.addStretch()
        box.addLayout(top)
        # 2e ligne : waterfall avec l'échelle des fréquences (kHz)
        self.m_wf_plot = pg.PlotWidget()
        self.m_wf_plot.setBackground("#101418")
        self.m_wf_plot.setMouseEnabled(x=False, y=False)
        self.m_wf_plot.hideAxis("left")
        self.m_wf_plot.invertY(True)
        self.m_wf_plot.hideButtons()
        self.m_wf_plot.setMenuEnabled(False)
        axis = self.m_wf_plot.getAxis("bottom")
        axis.setTickFont(QtGui.QFont("DejaVu Sans", 11, QtGui.QFont.Bold))
        axis.setTextPen(pg.mkPen("#f0d890"))
        self.m_wf_image = pg.ImageItem()
        self.m_wf_image.setLookupTable(pg.colormap.get("inferno").getLookupTable(nPts=256))
        self.m_wf_plot.addItem(self.m_wf_image)
        self.m_wf_tuned = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffd54a", width=2))
        self.m_wf_plot.addItem(self.m_wf_tuned, ignoreBounds=True)
        self.m_wf_plot.setMinimumHeight(180)
        self.m_wf_plot.scene().sigMouseClicked.connect(self._mobile_wf_clicked)
        self.m_wf_plot.setCursor(QtCore.Qt.PointingHandCursor)
        self.m_wf_plot.setToolTip("Clic sur une station : la radio s'y cale ; "
                                  "molette : changer la fréquence")
        self.m_wf_plot.viewport().installEventFilter(self)     # molette
        box.addWidget(self.m_wf_plot, 1)
        # 3e ligne : S-mètre, VFO, EMISSION, QSO en français et VOX
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(30)
        row.addStretch()
        self.m_knob = TuningKnob()                  # bouton VFO
        self.m_knob.tuned.connect(self.on_knob_tuned)
        row.addWidget(self._big(self.m_knob, 1.0), 0, QtCore.Qt.AlignVCenter)
        self.m_emission = EmissionButton()
        self.m_emission.is_tx = lambda: getattr(self, "vox_tx", False)
        self.m_emission.toggled.connect(lambda on: self.vox_button.setChecked(on))
        row.addWidget(self._big(self.m_emission, 2.3), 0, QtCore.Qt.AlignVCenter)
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        self.m_hunt = QtWidgets.QPushButton("QSO EN FRANÇAIS")
        self.m_hunt.setCheckable(True)
        self.m_hunt.setFocusPolicy(QtCore.Qt.NoFocus)
        self.m_hunt.setFixedSize(210, 40)
        self.m_hunt.setToolTip("Comme CHERCHER QSO FR : cherche un QSO en français "
                               "et s'arrête dessus ; nouvel appui = suivant / arrêt")
        self.m_hunt.clicked.connect(lambda: self.hunt_button.click())
        right.addWidget(self._big(self.m_hunt, 1.6), 0, QtCore.Qt.AlignHCenter)
        vox = QtWidgets.QHBoxLayout()
        vox.setSpacing(8)
        self.m_vox = {}
        for n in VOX_MSG_NUMBERS:                   # VOX1… : même effet que les poussoirs
            button = QtWidgets.QPushButton(f"VOX{n}")
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.setFixedSize(60, 60)
            button.setToolTip(f"VOX{n} : message vocal n° {n} en attente de « VOX {n} »")
            button.clicked.connect(lambda _=False, n=n: self.vox_msg_buttons[n].click())
            self.m_vox[n] = button
            vox.addWidget(self._big(button, 1.6))
        self.m_vox_vocal = QtWidgets.QPushButton("VOX\nVOCAL")
        self.m_vox_vocal.setCheckable(True)
        self.m_vox_vocal.setFocusPolicy(QtCore.Qt.NoFocus)
        self.m_vox_vocal.setFixedSize(60, 60)
        self.m_vox_vocal.setStyleSheet(PUSH_3D + "QPushButton { font-size: 8pt; }")
        self.m_vox_vocal.setToolTip("VOX VOCAL : dire « VOX » au micro arme le VOX")
        self.m_vox_vocal.clicked.connect(lambda: self.vox_vocal_button.click())
        vox.addWidget(self._big(self.m_vox_vocal, 1.6))
        right.addLayout(vox)
        row.addLayout(right)
        row.addStretch()
        box.addLayout(row)
        # retour à l'écran FIXE
        self.mobile_back = ToggleSwitch("FIXE", "MOBILE",
                                        tooltip="Levier en haut = retour à l'écran FIXE")
        self.mobile_back.setFixedSize(60, 60)
        self.mobile_back.setDown(True, emit=False)
        self.mobile_back.toggled.connect(self._mobile_toggled)
        plate = QtWidgets.QVBoxLayout()
        plate.setSpacing(1)
        plate.addWidget(NamePlate("FIXE / MOBILE", 110), 0, QtCore.Qt.AlignHCenter)
        plate.addWidget(self.mobile_back, 0, QtCore.Qt.AlignHCenter)
        box.addLayout(plate)
        return page

    def _mobile_sync(self):
        """Écran MOBILE : boutons recopiés sur ceux de l'écran FIXE (état, couleur)."""
        for mine, theirs in ((self.m_hunt, self.hunt_button),
                             (self.m_vox_vocal, self.vox_vocal_button)):
            if mine.isChecked() != theirs.isChecked():
                mine.setChecked(theirs.isChecked())
        style = self.hunt_button.styleSheet() + "QPushButton { font-weight: bold; }"
        if self.m_hunt.styleSheet() != style:
            self.m_hunt.setStyleSheet(style)
        for n, button in self.m_vox.items():
            theirs = self.vox_msg_buttons[n]
            if button.text() != theirs.text():
                button.setText(theirs.text())
            if button.styleSheet() != theirs.styleSheet():
                button.setStyleSheet(theirs.styleSheet())
        if self.m_emergency.flashing != self.emergency_button.flashing:
            self.m_emergency.set_flashing(self.emergency_button.flashing)

    def _mobile_wf_clicked(self, event):
        """Clic sur le waterfall MOBILE : la radio va sur cette fréquence."""
        if event.button() != QtCore.Qt.LeftButton or self.view != "rf":
            return
        vb = self.m_wf_plot.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(event.scenePos()):
            return
        x = vb.mapSceneToView(event.scenePos()).x()         # kHz
        step = self.step_combo.currentData()
        self.tune_to(round(x * 1000 / step) * step)

    def _mobile_waterfall(self):
        """Le waterfall de l'écran MOBILE recopie le grand (quand il est affiché)."""
        if self.pages.currentIndex() != 1 or self.waterfall is None:
            return
        x0, x1 = self.spec_plot.viewRange()[0]
        self.m_wf_image.setImage(self.waterfall, autoLevels=False,
                                 levels=(self.wf_low, self.wf_low + self.range_spin.value()))
        self.m_wf_image.setRect(QtCore.QRectF(x0, 0, x1 - x0, HISTORY))
        self.m_wf_plot.setXRange(x0, x1, padding=0)
        self.m_wf_plot.setYRange(0, HISTORY, padding=0)
        if self.view == "rf" and self.freq_hz:
            self.m_wf_tuned.setValue(self.freq_hz / 1000)
            self.m_wf_tuned.setVisible(True)
        else:
            self.m_wf_tuned.setVisible(False)

    def _mobile_toggled(self, mobile):
        self.mobile_toggle.setDown(mobile, emit=False)
        self.mobile_back.setDown(mobile, emit=False)
        self.pages.setCurrentIndex(1 if mobile else 0)
        if mobile:
            self.mobile_timer.start(150)
            self._mobile_sync()
            self._mobile_waterfall()
        else:
            self.mobile_timer.stop()

    def _loupe_toggled(self, on):
        """Interrupteur LOUPE : levier en bas = lentille autour du pointeur."""
        if on:
            self.loupe.start()
            self.statusBar().showMessage(
                f"Loupe × {self.loupe.zoom} : Alt + molette pour régler", 4000)
        else:
            self.loupe.stop()

    # --- FT8 : WSJT-X piloté par le Scope ----------------------------------
    HAMLIB_MODES = {"USB-D": "PKTUSB", "LSB-D": "PKTLSB", "FM-D": "PKTFM", "AM-D": "PKTAM"}

    def _ft8_toggled(self, on):
        if on:
            if self.rtty_toggle.down:           # un seul écran plein à la fois
                self.rtty_toggle.setDown(False)
            if self.fr_toggle.down:
                self.fr_toggle.setDown(False)
            if self.vox_button.isChecked():         # le micro ne doit pas émettre
                self.vox_button.setChecked(False)
            if not self.ft8_server.start():
                self.ft8_toggle.setDown(False)
                return
            ft8_bridge.ensure_wsjtx_config(self.ft8_source, self.radio_sink)
            self._ft8_force_freq()
            if self.ft8_proc is None or self.ft8_proc.poll() is not None:
                self.ft8_proc = subprocess.Popen(
                    ["wsjtx", "-stylesheet", WSJTX_QSS], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
            screen = (self.windowHandle().screen() if self.windowHandle()
                      else QtWidgets.QApplication.primaryScreen())
            self.ft8_map.setGeometry(screen.geometry())
            self.ft8_map.start()
            self.ft8_map.showFullScreen()
            geo = screen.geometry()
            self.ft8_close.move(geo.right() - self.ft8_close.width() - 6,
                                geo.bottom() - self.ft8_close.height() - 22)
            self.ft8_close.show()
            self.ft8_close.raise_()
            self.ft8_window = None
            self.ft8_ids = set()
            self.ft8_tries = 0
            self.ft8_timer.start(500)
            self.statusBar().showMessage("FT8 : ouverture de WSJT-X…", 5000)
        else:
            self.ft8_timer.stop()
            if self.ft8_tx:
                self.ft8_set_ptt(False)
            proc = self.ft8_proc
            if proc and proc.poll() is None:
                # fermeture normale (WSJT-X garde ses réglages), forcée après 5 s
                if self.ft8_window:
                    subprocess.run(["wmctrl", "-i", "-c", self.ft8_window])
                else:
                    proc.terminate()
                QtCore.QTimer.singleShot(5000, lambda: proc.poll() is None and proc.terminate())
            self.ft8_proc = None
            self.ft8_map.stop()
            self.ft8_close.hide()
            self._ft8_restore_windows()
            self.ft8_server.stop()
            before = getattr(self, "ft8_before", None)
            self.ft8_before = None
            if before and self.civ and not self.tx_active:
                hz, mode = before
                if mode.endswith("-D"):             # jamais laissé en mode données
                    mode = mode[:-2]
                self.ft8_set_mode(mode)
                self._manual_tuning()
                self.tune_to(hz)
                self.statusBar().showMessage(
                    f"FT8 arrêté : retour sur {hz / 1e6:.3f} MHz {mode}", 5000)
            else:
                self.statusBar().showMessage("FT8 arrêté", 3000)

    def _ft8_force_freq(self):
        """Radio calée sur la fréquence FT8 normalisée de la bande, en USB-D."""
        if not self.civ or self.tx_active:
            return
        self._manual_tuning()           # SCAN, recherches… s'arrêtent
        # fréquence et mode d'avant, rendus à l'arrêt du FT8
        self.ft8_before = (self.freq_hz, self.mode_combo.currentText())
        hz = ft8_bridge.ft8_freq_for(self.freq_hz)
        self.ft8_set_mode("PKTUSB")
        if hz != self.freq_hz:
            self.tune_to(hz)
        self.statusBar().showMessage(f"FT8 : radio calée sur {hz / 1e6:.3f} MHz USB-D", 6000)

    def _ft8_watch(self):
        """Met WSJT-X en plein écran dès que sa fenêtre paraît ; si on ferme
        WSJT-X, l'interrupteur repasse sur OFF."""
        if self.ft8_proc is None or self.ft8_proc.poll() is not None:
            self.ft8_toggle.setDown(False)
            return
        if self.ft8_window:
            self._ft8_keep_map_below()
            return
        if self.ft8_tries > 60:
            return
        self.ft8_tries += 1
        out = subprocess.run(["wmctrl", "-l", "-p"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            cols = line.split(None, 4)
            if len(cols) == 5 and cols[2] == str(self.ft8_proc.pid):
                self.ft8_ids.add(int(cols[0], 16))
                if "K1JT" in cols[4]:           # fenêtre principale (titre avec version)
                    self.ft8_window = cols[0]
                    subprocess.run(["wmctrl", "-i", "-r", cols[0], "-b", "add,fullscreen"])
                    self._ft8_apply_opacity()
                    QtCore.QTimer.singleShot(300, self._ft8_hide_windows)
                    subprocess.run(["wmctrl", "-i", "-a", cols[0]])
                elif "Wide Graph" in cols[4]:   # cascade masquée : la carte reste dégagée
                    subprocess.run(["wmctrl", "-i", "-c", cols[0]])

    FT8_CONFIG = os.path.expanduser("~/.config/ic7300-scope/ft8.json")

    def _ft8_load_opacity(self):
        try:
            with open(self.FT8_CONFIG) as f:
                return max(40, min(100, int(json.load(f)["opacite"])))
        except (OSError, ValueError, KeyError, TypeError):
            return 75

    def _ft8_apply_opacity(self):
        """WSJT-X un peu transparent : la mappemonde se voit derrière."""
        if self.ft8_window:
            value = int(self.ft8_opacity / 100 * 0xFFFFFFFF)
            subprocess.run(["xprop", "-id", self.ft8_window, "-f", "_NET_WM_WINDOW_OPACITY",
                            "32c", "-set", "_NET_WM_WINDOW_OPACITY", str(value)],
                           capture_output=True)

    def _ft8_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addSection("Opacité de WSJT-X sur la carte")
        for value in (100, 90, 85, 80, 75, 70, 60, 50):
            action = menu.addAction(f"{value} %")
            action.setCheckable(True)
            action.setChecked(value == self.ft8_opacity)
            action.triggered.connect(lambda _, v=value: self._ft8_set_opacity(v))
        menu.exec_(self.ft8_toggle.mapToGlobal(pos))

    def _ft8_set_opacity(self, value):
        self.ft8_opacity = value
        try:
            os.makedirs(os.path.dirname(self.FT8_CONFIG), exist_ok=True)
            with open(self.FT8_CONFIG, "w") as f:
                json.dump({"opacite": value}, f)
        except OSError:
            pass
        self._ft8_apply_opacity()

    def _ft8_hide_windows(self):
        """Range toutes les autres fenêtres (Scope compris) : derrière WSJT-X il
        ne reste que la mappemonde. Elles reviennent à la fermeture de FT8."""
        keep = {int(self.ft8_map.winId())}
        if self.console_button.isChecked():         # CONSOLE allumé : le terminal reste
            keep |= set(console.terminal_windows())
        self.ft8_hidden = self._hide_windows(
            keep, str(self.ft8_proc.pid) if self.ft8_proc else "")
        if self.console_button.isChecked():         # … et passe devant WSJT-X
            QtCore.QTimer.singleShot(400, lambda: console.show_console(None))

    def _rtty_hide(self):
        keep = {int(self.rtty_screen.winId())}
        if self.console_button.isChecked():         # CONSOLE allumé : le terminal reste
            keep |= set(console.terminal_windows())
        self.rtty_hidden = self._hide_windows(keep)
        if self.console_button.isChecked():
            QtCore.QTimer.singleShot(200, lambda: console.show_console(None))

    def _hide_windows(self, keep, pid=""):
        """Réduit toutes les fenêtres sauf `keep` et celles du processus `pid` ;
        renvoie la liste (du bas vers le haut) pour les rendre ensuite."""
        out = subprocess.run(["wmctrl", "-l", "-p"], capture_output=True, text=True).stdout
        candidates = set()
        for line in out.splitlines():
            cols = line.split(None, 4)
            if len(cols) < 4 or cols[1] == "-1" or cols[2] == pid:
                continue                    # bureau, panneaux, fenêtres de WSJT-X
            w = int(cols[0], 16)
            if w not in keep:
                candidates.add(w)
        stack = subprocess.run(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"],
                               capture_output=True, text=True).stdout
        order = [int(x, 16) for x in re.findall(r"0x[0-9a-f]+", stack)]
        hidden = [w for w in order if w in candidates]   # du bas vers le haut
        for w in hidden:
            self.demo_finger.x11.iconify(w)
        return hidden

    def _restore_windows(self, hidden):
        """Fenêtres rangées : de retour, dans leur ordre d'avant."""
        for w in hidden:
            subprocess.run(["wmctrl", "-i", "-a", hex(w)], capture_output=True)

    def _ft8_restore_windows(self):
        self._restore_windows(self.ft8_hidden)
        self.ft8_hidden = []

    # --- DÉCODEUR RTTY plein écran ------------------------------------------
    RTTY_FREQS = (3_590_000, 7_043_000, 10_142_000, 14_085_000, 18_105_000,
                  21_085_000, 24_925_000, 28_085_000)
    RTTY_BANDS = ((3_580_000, 3_600_000), (7_040_000, 7_050_000), (10_140_000, 10_150_000),
                  (14_080_000, 14_099_000), (18_095_000, 18_109_000),
                  (21_080_000, 21_120_000), (24_915_000, 24_929_000),
                  (28_050_000, 28_150_000))

    def _rtty_tick(self):
        """Écran RTTY : fréquence et émission de ma radio, en temps réel."""
        self.rtty_screen.set_frequency(self.freq_hz)
        self.rtty_screen.set_tx(self.tx_active or getattr(self.civ, "_tx", False))

    def _rtty_toggled(self, on):
        if on:
            if self.ft8_toggle.down:            # un seul écran plein à la fois
                self.ft8_toggle.setDown(False)
            if self.fr_toggle.down:
                self.fr_toggle.setDown(False)
            # fréquence et mode d'avant : rendus à la fermeture de l'écran RTTY
            self.rtty_prev = (self.freq_hz, self.mode_combo.currentText())
            if self.civ and not self.tx_active:
                self._manual_tuning()
                hz = self.freq_hz or 14_085_000
                if not any(lo <= hz <= hi for lo, hi in self.RTTY_BANDS):
                    hz = min(self.RTTY_FREQS, key=lambda f: abs(f / hz - 1))
                    self.tune_to(hz)
                self.ft8_set_mode("RTTY")
            self.rtty_prev_decoder = self.decoder_combo.currentIndex()
            self.decoder_combo.setCurrentIndex(self.decoder_combo.findData("rtty"))
            self.decoder_auto.setChecked(True)
            screen = (self.windowHandle().screen() if self.windowHandle()
                      else QtWidgets.QApplication.primaryScreen())
            geo = screen.geometry()
            self.rtty_screen.reset()
            self.rtty_screen.set_frequency(self.freq_hz)
            self.rtty_screen.setGeometry(geo)
            self.rtty_screen.start()
            self.rtty_screen.showFullScreen()
            self.rtty_close.move(geo.right() - self.rtty_close.width() - 6,
                                 geo.bottom() - self.rtty_close.height() - 22)
            self.rtty_close.show()
            self.rtty_close.raise_()
            self.rtty_timer.start(250)
            QtCore.QTimer.singleShot(400, lambda: self.rtty_toggle.down and self._rtty_hide())
        else:
            self.rtty_timer.stop()
            self.rtty_close.hide()
            self.rtty_screen.stop()
            self._restore_windows(self.rtty_hidden)
            self.rtty_hidden = []
            self.decoder_combo.setCurrentIndex(self.rtty_prev_decoder)
            prev = getattr(self, "rtty_prev", None)
            self.rtty_prev = None
            if prev and self.civ and not self.tx_active:      # retour au trafic d'avant
                hz, mode = prev
                if mode and mode != self.mode_combo.currentText():
                    self.ft8_set_mode(mode)
                if hz and hz != self.freq_hz:
                    self.tune_to(hz)

    # --- WATERFALL FR plein écran (lecture seule : VFO jamais changé) ----------
    # --- VOX1, VOX2… : messages vocaux déclenchés par la parole ------------
    def _vox_msg_show(self):
        """Poussoirs : orange clignotant = en attente de « VOX n », rouge = émission."""
        now = time.monotonic()
        self.vox_msg_blink = int(now / 0.4) % 2 == 0      # attente : clignote lentement
        fast = int(now / 0.12) % 2 == 0                    # message en cours : très vite
        for n, button in self.vox_msg_buttons.items():
            # « :checked » aussi : sinon le fond du bouton enfoncé masquerait la couleur
            over = "QPushButton, QPushButton:checked, QPushButton:hover { %s }"
            if self.vox_msg_sending == n:
                style = over % ("background: %s; color: white;"
                                % ("#ff2a2a" if fast else "#5a0000"))
                text = "ÉMET"
            elif n in self.vox_msg_armed:
                style = over % ("background: %s; color: #151515; font-size: 8pt;"
                                % ("#ff8a00" if self.vox_msg_blink else "#8a5200"))
                text = (f"ESSAI\nVOX {n}" if (self.vox_msg_dry or n in self.vox_msg_dry_auto)
                        else f"DIS\nVOX {n}")
            elif self.vox_msg_rec and self.vox_msg_rec[0] == n:
                style = over % "background: #8a0000; color: white;"
                text = "🎙 REC"
            elif self.vox_learn is not None and self.vox_learn[0] == n:
                style = over % "background: #1e6fd0; color: white; font-size: 8pt;"
                text = "🗣\nAPPREND"
            else:
                style, text = "", (f"VOX{n}\nESSAI" if self.vox_msg_dry else f"VOX{n}")
                if self.vox_msg_dry:
                    style = over % "font-size: 8pt;"
            if button.text() != text:
                button.setText(text)
            full = PUSH_YELLOW_3D + style
            if button.styleSheet() != full:
                button.setStyleSheet(full)
            if button.isChecked() != (n in self.vox_msg_armed):
                button.setChecked(n in self.vox_msg_armed)

    def _vox_msg_arm(self, n, on):
        """Appui sur VOX n : message en attente (aucune émission), ou annulé.
        Pas encore de message : l'appui lance l'enregistrement, un 2e appui l'arrête."""
        if self.vox_msg_rec is not None and self.vox_msg_rec[0] == n:
            self._vox_log(f"VOX{n} : 2e appui → fin de l'enregistrement du message")
            self._vox_msg_rec_stop()
            return
        if on and not os.path.exists(vox_msg_file(n)) and self.vox_msg_rec is None \
                and not self.tx_active:
            self._vox_log(f"VOX{n} : pas de message → enregistrement (2e appui = fin)")
            self._vox_msg_rec_start(n)
            self.statusBar().showMessage(f"VOX{n} : enregistrement du message — parle, puis "
                                         f"appuie de nouveau sur VOX{n} (ou Terminer)")
            return
        if self.vox_msg_sending == n and self.vox_dry_player is not None:
            self.vox_dry_player.terminate()     # ESSAI : arrêt du message
            return
        if not on:
            self.vox_msg_armed.discard(n)
            self.vox_msg_dry_auto.discard(n)
            self._vox_log(f"VOX{n} : attente annulée (nouvel appui)")
            self.statusBar().showMessage(f"VOX{n} : attente annulée", 4000)
        else:
            problem = None
            if not os.path.exists(vox_msg_file(n)):
                problem = f"VOX{n} : pas encore de message (clic droit sur VOX{n} → Enregistrer)"
            elif self.vox_msg_rec is not None:
                problem = "Termine d'abord l'enregistrement du message"
            elif not self._vox_mic():
                problem = f"VOX{n} : pas de micro pour entendre « VOX {n} »"
            if not problem and not self.voice_cmds.learned(n):
                # voix pas encore apprise : l'appui lance l'apprentissage (jamais d'émission)
                self._vox_msg_show()
                self._vox_log(f"VOX{n} appuyé : voix pas apprise → apprentissage")
                self._vox_learn_start(n)
                return
            if problem:
                self._vox_log(problem)
                self.statusBar().showMessage(problem, 6000)
            else:
                self.vox_msg_armed.add(n)
                self._vox_log(f"VOX{n} appuyé : en attente"
                              + (" (ESSAI)" if self.vox_msg_dry or n in self.vox_msg_dry_auto
                                 else ""))
                if n in self.vox_msg_dry_auto:
                    self.statusBar().showMessage(
                        f"VOX{n} : ESSAI À BLANC (ta voix n'est pas encore apprise, rien ne "
                        f"sera émis) — dis « VOX {n} » au micro", 8000)
                    self._mot_vox_need()
                    self._vox_msg_show()
                    return
                self.statusBar().showMessage(
                    f"VOX{n} en attente : dis « VOX {n} » au micro pour l'émettre "
                    "(seule ta voix est acceptée)", 8000)
        self._mot_vox_need()
        self._vox_msg_show()

    def _vox_msg_menu(self, n, pos):
        menu = QtWidgets.QMenu(self)
        recording = self.vox_msg_rec is not None
        if not recording:
            record = menu.addAction(f"🎙 Enregistrer le message VOX{n} (micro)")
        else:
            record = menu.addAction("⏹ Terminer l'enregistrement")
        listen = menu.addAction(f"🔊 Écouter le message VOX{n} (sur le PC)")
        listen.setEnabled(os.path.exists(vox_msg_file(n)) and not recording)
        menu.addSeparator()
        dry = menu.addAction("🧪 Mode ESSAI : sans émettre (message joué dans le casque)")
        dry.setCheckable(True)
        dry.setChecked(self.vox_msg_dry)
        learn = menu.addAction(f"🗣 Apprendre ma voix pour « VOX {n} »"
                               + (" (déjà appris : refaire)" if self.voice_cmds.learned(n)
                                  else ""))
        learn.setEnabled(not recording and self.vox_learn is None and not self.tx_active)
        chosen = menu.exec_(self.vox_msg_buttons[n].mapToGlobal(pos))
        if chosen is learn:
            self._vox_learn_start(n)
            return
        if chosen is dry:
            self.vox_msg_dry = dry.isChecked()
            self._vox_dry_save()
            self._vox_msg_show()
            self.statusBar().showMessage(
                "Mode ESSAI : rien n'est émis, le message est joué dans le casque ; "
                "niveau du micro et seuil affichés pendant l'attente" if self.vox_msg_dry
                else "Mode ESSAI arrêté : VOX n émet de nouveau pour de vrai", 8000)
            return
        if chosen is record:
            if recording:
                self._vox_msg_rec_stop()
            else:
                self._vox_msg_rec_start(n)
        elif chosen is listen:
            subprocess.Popen(["paplay", vox_msg_file(n)])
            self.statusBar().showMessage(f"VOX{n} : écoute du message sur le PC", 4000)

    def _vox_learn_start(self, n):
        """Apprentissage : « VOX n » dit LEARN_COUNT fois, ta voix seulement."""
        if not self._vox_mic():
            self.statusBar().showMessage("Pas de micro", 5000)
            return
        self.vox_msg_armed.discard(n)
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(f"Apprendre « VOX {n} »")
        box.addButton("Annuler", QtWidgets.QMessageBox.RejectRole)
        box.setModal(False)
        box.buttonClicked.connect(lambda *_: self._vox_learn_end(cancel=True))
        self.vox_learn = (n, [], box)
        self._vox_learn_text()
        box.show()
        self._mot_vox_need()
        self._vox_msg_show()

    def _vox_learn_text(self, note=""):
        n, clips, box = self.vox_learn
        box.setText(f"🗣 Dis « VOX {n} » au micro, normalement, comme en trafic.\n"
                    f"Attends une seconde entre chaque fois.\n\n"
                    f"Exemple {len(clips) + 1} sur {LEARN_COUNT}"
                    + ("  " + "✔" * len(clips)) + (f"\n\n{note}" if note else ""))

    def _vox_learn_end(self, cancel=False):
        if self.vox_learn is None:
            return
        n, clips, box = self.vox_learn
        self.vox_learn = None
        box.close()
        self._mot_vox_need()
        self._vox_msg_show()
        if cancel:
            self.statusBar().showMessage(f"Apprentissage de « VOX {n} » annulé "
                                         "(l'ancien est gardé s'il existe)", 6000)
            return
        kept = self.voice_cmds.save(n, clips)
        limit = self.voice_cmds.limit.get(n, 0)
        self._vox_log(f"apprentissage VOX {n} terminé : {kept} exemples, tolérance {limit:.1f}")
        QtWidgets.QMessageBox.information(
            self, f"« VOX {n} » appris",
            f"Ta voix pour « VOX {n} » est apprise ({kept} exemples, tolérance "
            f"{limit:.1f}).\n\nAppuie sur VOX{n}, puis dis « VOX {n} » : le message "
            "part seulement si c'est toi qui le dis.")

    def on_mot_vox_segment(self, clip):
        """Parole courte entendue au micro : exemple d'apprentissage, ou commande."""
        if self.vox_learn is not None:
            n, clips, box = self.vox_learn
            if features(clip) is None:
                self._vox_learn_text("(trop court, recommence)")
                return
            clips.append(clip)
            self._vox_log(f"apprentissage VOX {n} : exemple {len(clips)}/{LEARN_COUNT} "
                          f"({len(clip) / 32000:.1f} s)")
            if len(clips) >= LEARN_COUNT:
                self._vox_learn_end()
            else:
                self._vox_learn_text()
            return
        if not self.vox_msg_armed or self.tx_active:
            return
        self.vox_seg_time = time.monotonic()
        if not (self.vox_msg_armed - self.vox_msg_dry_auto):
            return                              # essai à blanc : décidé par le texte
        n, dist, detail = self.voice_cmds.match(clip, self.vox_msg_armed - self.vox_msg_dry_auto)
        self.vox_match_detail = detail
        self._vox_log(f"voix : {detail}" + (" → reconnue" if n is not None else ""))
        if n is not None:
            self.voice_cmds.add_example(n, clip)        # suit ta voix du moment
            self.statusBar().showMessage(f"Ta voix reconnue : {detail}", 6000)
            self._vox_msg_send(n)
        else:
            self.statusBar().showMessage(f"Pas reconnu : {detail}", 5000)

    def _vox_msg_rec_start(self, n):
        if self.tx_active:
            self.statusBar().showMessage("Pas d'enregistrement pendant l'émission", 5000)
            return
        self.vox_msg_armed.discard(n)
        source = self._vox_mic() or "@DEFAULT_SOURCE@"
        path = vox_msg_file(n)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            proc = subprocess.Popen(
                # micro brut : pas de porte anti-souffle ni de retard ; le timbre
                # QSO est appliqué à la fin (timbre_qso.py)
                ["parec", "-d", source, "--file-format=wav",
                 "--rate=48000", "--channels=1", f"--client-name=IC-7300 VOX{n}",
                 path + ".brut.wav"], stderr=subprocess.DEVNULL)
        except OSError as e:
            self.statusBar().showMessage(f"VOX{n} : enregistrement impossible ({e})", 6000)
            return
        self.vox_msg_rec = (n, proc)
        self._mot_vox_need()                # pas d'écoute de « VOX n » pendant ce temps
        self.vox_msg_rec_timer.start(VOX_MSG_MAX_S * 1000)
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(f"VOX{n}")
        box.setText(f"🎙 Enregistrement du message VOX{n}…\n\nParle dans le micro, "
                    "puis clique sur « Terminer ».")
        box.addButton("Terminer", QtWidgets.QMessageBox.AcceptRole)
        box.setModal(False)
        box.buttonClicked.connect(lambda *_: self._vox_msg_rec_stop())
        self.vox_msg_box = box
        box.show()
        self._vox_msg_show()

    def _vox_msg_rec_stop(self):
        """Fin de l'enregistrement : silences du début et de la fin enlevés
        (retour en réception dès le dernier mot)."""
        if self.vox_msg_rec is None:
            return
        n, proc = self.vox_msg_rec
        self.vox_msg_rec = None
        self.vox_msg_rec_timer.stop()
        proc.terminate()
        proc.wait(timeout=5)
        box = getattr(self, "vox_msg_box", None)
        if box is not None:
            box.close()
            self.vox_msg_box = None
        path = vox_msg_file(n)
        tmp = path + ".net.wav"
        self.statusBar().showMessage(f"VOX{n} : mise au timbre QSO…")
        QtWidgets.QApplication.processEvents()
        try:
            length = timbre_qso.apply(path + ".brut.wav", tmp)
        except Exception:
            length = 0.0
        self._mot_vox_need()
        self._vox_msg_show()
        if length < 0.3:
            self.statusBar().showMessage(f"VOX{n} : rien d'enregistré (micro muet ?) — "
                                         "message précédent gardé s'il existe", 8000)
            return
        os.replace(tmp, path)
        os.remove(path + ".brut.wav")
        self.statusBar().showMessage(f"VOX{n} : message enregistré ({length:.1f} s). "
                                     f"Appuie sur VOX{n}, puis dis « VOX {n} » "
                                     "pour l'émettre", 8000)

    @staticmethod
    def _wav_seconds(path):
        try:
            with wave.open(path) as w:
                return w.getnframes() / w.getframerate()
        except (OSError, wave.Error, EOFError):
            return 0.0

    def _vox_msg_send(self, n):
        """« VOX n » entendu : émission du message, puis réception dès la fin."""
        self.vox_msg_armed.discard(n)       # une seule émission par appui
        if self.vox_msg_dry or n in self.vox_msg_dry_auto:
            self.vox_msg_dry_auto.discard(n)
            return self._vox_dry_send(n)
        problem = None
        if not self.civ:
            problem = "émission impossible sans CAT"
        elif self.tx_active:
            problem = "déjà en émission"
        elif base_mode(self.mode_combo.currentText()) not in ("LSB", "USB", "AM", "FM"):
            problem = "seulement en phonie (LSB, USB, AM, FM)"
        elif not os.path.exists(vox_msg_file(n)):
            problem = "message introuvable"
        if problem:
            self.statusBar().showMessage(f"« VOX {n} » entendu, mais {problem} : "
                                         "rien d'émis", 8000)
            self._mot_vox_need()
            self._vox_msg_show()
            return
        length = self._wav_seconds(vox_msg_file(n))
        self.vox_msg_sending = n
        self.civ.set_ptt(True)
        self.tx_limit = max(TX_TIMEOUT, length + 15)
        self.tx_active = True
        self.tx_galva.set_tx(True)
        self._pactl_stream("set-sink-input-mute", "1")     # casque muet pendant l'émission
        self._update_ssb()
        self.tx_started = time.monotonic()
        self.tx_timer.start()
        self._set_ptt_button(True)
        self.statusBar().showMessage(f"« VOX {n} » entendu : émission du message "
                                     f"({length:.1f} s)")
        self._vox_msg_show()
        QtCore.QTimer.singleShot(300, lambda: self._vox_msg_play(n))  # radio en émission d'abord

    VOX_DRY_FILE = os.path.join(os.path.dirname(STATE_FILE), "vox-essai.json")

    def _vox_dry_load(self):
        try:
            return bool(json.load(open(self.VOX_DRY_FILE)).get("essai", True))
        except (OSError, ValueError):
            return True

    def _vox_dry_save(self):
        try:
            with open(self.VOX_DRY_FILE, "w") as f:
                json.dump({"essai": self.vox_msg_dry}, f)
        except OSError:
            pass

    VOX_LOG = os.path.expanduser("~/.cache/ic7300-scope/vox-essais.log")

    def _vox_log(self, text):
        """Journal des VOX n (essais et émissions) : pour relire après coup."""
        try:
            os.makedirs(os.path.dirname(self.VOX_LOG), exist_ok=True)
            with open(self.VOX_LOG, "a") as f:
                f.write(time.strftime("%H:%M:%S ") + text + "\n")
        except OSError:
            pass

    def _vox_dry_send(self, n):
        """ESSAI : même déroulé, sans PTT ; message joué sur la sortie du PC."""
        if not os.path.exists(vox_msg_file(n)):
            self.statusBar().showMessage(f"ESSAI VOX{n} : message introuvable", 6000)
            return
        self.vox_msg_sending = n
        now = time.monotonic()
        self.vox_dry_heard = self.vox_seg_time if now - self.vox_seg_time < 10 else now
        self.vox_dry_len = self._wav_seconds(vox_msg_file(n))
        self._mot_vox_need()
        self._vox_msg_show()
        self.statusBar().showMessage(f"ESSAI VOX{n} : « VOX {n} » reconnu "
                                     f"({getattr(self, 'vox_match_detail', '')}) — émission "
                                     f"SIMULÉE, message dans le casque ({self.vox_dry_len:.1f} s)")
        self.vox_dry_start = None
        QtCore.QTimer.singleShot(300, lambda: self._vox_dry_play(n))  # comme la vraie bascule

    def _vox_dry_play(self, n):
        if self.vox_msg_sending != n:
            return
        self.vox_dry_start = time.monotonic()
        self.vox_dry_player = subprocess.Popen(["paplay", vox_msg_file(n)])
        self._vox_log(f"ESSAI VOX{n} : message lancé sur la sortie du PC")
        self.vox_dry_timer.start(50)

    def _vox_dry_check(self):
        p = self.vox_dry_player
        if p is None or p.poll() is None:
            return
        self.vox_dry_timer.stop()
        self.vox_dry_player = None
        n = self.vox_msg_sending
        self.vox_msg_sending = None
        end = time.monotonic()
        start_delay = (self.vox_dry_start or end) - self.vox_dry_heard
        self._mot_vox_need()
        self._vox_msg_show()
        self._vox_log(f"ESSAI VOX{n} terminé : départ {start_delay + 0.3:.1f} s après « VOX {n} », "
                      f"message {end - (self.vox_dry_start or end):.1f} s, retour réception "
                      f"(simulé), code paplay {p.returncode}")
        self.statusBar().showMessage(
            f"ESSAI VOX{n} terminé : départ {start_delay + 0.3:.1f} s après la fin de "
            f"« VOX {n} » (dont 0,3 s de silence pour la détecter), message "
            f"{end - (self.vox_dry_start or end):.1f} s, retour en réception (simulé) "
            "dès la fin. Rien n'a été émis.", 20000)

    def _vox_msg_play(self, n):
        if self.tx_active and self.vox_msg_sending == n:
            self.tx_player = subprocess.Popen(
                ["paplay", f"--device={self.radio_sink}", vox_msg_file(n)])
            # retour BF : le même message sur la sortie du PC, en même temps
            self.vox_monitor_player = subprocess.Popen(
                ["paplay", "--client-name=IC-7300 retour BF", vox_msg_file(n)])
            self._vox_log(f"VOX{n} : émission réelle du message, retour BF sur le PC")

    # --- TRADUCTION de la réception en français -------------------------------
    def _translate_toggled(self, on):
        if on:
            if self.translation_window is None:
                win = TranslationWindow(self)
                win.closed.connect(lambda: self.translate_button.setChecked(False))
                self.translator.result.connect(win.add)
                self.translator.status.connect(win.set_status)
                self.translator.level.connect(win.set_level)
                self.translation_window = win
            self.translation_window.show()
            self.translation_window.raise_()
            self.translator.start(self.audio.source)
            if getattr(self, "translate_pause_timer", None) is None:
                self.translate_pause_timer = QtCore.QTimer(self)
                self.translate_pause_timer.timeout.connect(self._translate_pause)
            self.translate_pause_timer.start(300)
            self.translate_button.setStyleSheet(
                PUSH_YELLOW_3D + "QPushButton, QPushButton:checked { background: #4ade80;"
                " color: #0b0f1a; font-size: 7pt; }")
            self.statusBar().showMessage("TRADUCTION : écoute de la réception (premier "
                                         "résultat après ≈ 15 s de chargement)", 6000)
        else:
            self.translator.stop()
            if getattr(self, "translate_pause_timer", None):
                self.translate_pause_timer.stop()
            if self.translation_window is not None and self.translation_window.isVisible():
                self.translation_window.blockSignals(True)
                self.translation_window.hide()
                self.translation_window.blockSignals(False)
            self.translate_button.setStyleSheet(PUSH_YELLOW_3D + "QPushButton { font-size: 7pt; }")

    def _translate_pause(self):
        """Pas de traduction de sa propre émission."""
        self.translator.paused = self.tx_active

    # --- DICTÉE vers le terminal --------------------------------------------
    def _dictee_click(self):
        if self.dictee.active:
            self.dictee.stop()                  # fin de la parole tout de suite
            return
        mic = self._vox_mic()
        if not mic:
            self.statusBar().showMessage("DICTÉE : pas de micro", 5000)
            return
        self.dictee.start(mic)
        self._dictee_state("prépare")

    def _dictee_state(self, state):
        self.dictee_state = state
        look = {"prépare": ("…", "#8a6d00", "white"),
                "écoute": ("PARLE", "#ff8a00", "#151515"),
                "parle": ("J'ÉCOUTE", "#c62828", "white"),
                "texte": ("ÉCRIT…", "#1e6fd0", "white")}.get(state)
        if look:
            text, bg, fg = look
            self.dictee_button.setText(text)
            self.dictee_button.setStyleSheet(
                PUSH_YELLOW_3D + "QPushButton, QPushButton:hover { background: %s;"
                " color: %s; font-size: 8pt; }" % (bg, fg))
        else:
            self.dictee_button.setText("DICTÉE")
            self.dictee_button.setStyleSheet(PUSH_YELLOW_3D)
        if state == "écoute":
            self.statusBar().showMessage("DICTÉE : parle, puis tais-toi 1,5 s "
                                         "(finis par « envoie » pour valider)", 8000)

    def _dictee_done(self, text, err):
        self._dictee_state("")
        if err or not text:
            self.statusBar().showMessage(f"DICTÉE : {err or 'rien compris'}", 6000)
            return
        text, send = split_send(text)
        if not text:
            return
        QtWidgets.QApplication.clipboard().setText(text)
        wid = console.claude_terminal()
        if wid is None or not paste_into(wid, send):
            self.statusBar().showMessage(f"DICTÉE (copiée, à coller) : « {text} »", 10000)
            return
        self.statusBar().showMessage(f"DICTÉE {'envoyée' if send else 'écrite'} : "
                                     f"« {text} »", 10000)

    def _rec_switch(self, rec, switch, down):
        """Interrupteurs REC BF et VDO+BF : levier en bas = départ, en haut = arrêt."""
        if down and not rec.recording:
            rec.start()
        elif not down and rec.recording:
            rec.stop()
        if rec.finishing and down:
            self.statusBar().showMessage("Enregistrement précédent en cours de finition, "
                                         "un instant…", 5000)
        switch.setDown(rec.recording, emit=False)

    def _rec_video_show(self):
        """Bouton REC vidéo de l'écran principal : rouge + durée pendant l'enregistrement."""
        rec = self.screen_rec
        if rec.recording:
            s = int(rec.elapsed())
            self.rec_video_button.setText(f"■ REC {s // 60:02d}:{s % 60:02d}")
            self.rec_video_button.setStyleSheet("background: #c62828; color: white; font-weight: bold;")
        elif rec.finishing:
            self.rec_video_button.setText("⏳ assemblage…")
            self.rec_video_button.setStyleSheet("background: #8a6d00; color: white;")
        else:
            self.rec_video_button.setText("⏺ REC vidéo")
            self.rec_video_button.setStyleSheet("")

    def _fr_tick(self):
        self.fr_screen.set_frequency(self.freq_hz, self.mode_combo.currentText())
        if base_mode(self.mode_combo.currentText()) in ("LSB", "USB") and self.ssb_auto.isChecked():
            tuner = self.audio.ssb_tuner
            self.fr_screen.set_calage(("⚡ " if tuner.fast else "") + tuner.status, tuner.locked)
        else:
            self.fr_screen.set_calage("", False)
        if self.fr_full and self.freq_hz and band_of(self.freq_hz) != self.fr_full_band:
            self._fr_full_band()                # autre bande : l'affichage suit

    # plages du mode fixe du scope de l'IC-7300 (code BCD de la plage)
    FIXED_RANGES = ((30_000, 1_600_000, 0x01), (1_600_000, 2_000_000, 0x02),
                    (2_000_000, 6_000_000, 0x03), (6_000_000, 8_000_000, 0x04),
                    (8_000_000, 11_000_000, 0x05), (11_000_000, 15_000_000, 0x06),
                    (15_000_000, 20_000_000, 0x07), (20_000_000, 22_000_000, 0x08),
                    (22_000_000, 26_000_000, 0x09), (26_000_000, 30_000_000, 0x10),
                    (30_000_000, 45_000_000, 0x11), (45_000_000, 60_000_000, 0x12),
                    (60_000_000, 74_800_000, 0x13))

    def _fr_full_band(self):
        """Scope de la radio en mode FIXE, bords = la bande entière (1 MHz au plus),
        jeu de bords n° 3 de la radio."""
        if not self.civ or not self.freq_hz:
            return
        name = band_of(self.freq_hz)
        self.fr_full_band = name
        edges = next(((lo, hi) for n, lo, hi, _, _ in BANDS if n == name), None)
        if edges is None:                       # hors bande : on reste en mode centré
            self.civ._commands.put((0x27, 0x14, 0x00, 0x00))
            return
        lo, hi = edges
        if hi - lo > 1_000_000:                 # 10 m, 6 m : la fenêtre de 1 MHz suit le VFO
            lo = max(lo, min(self.freq_hz - 500_000, hi - 1_000_000))
            hi = lo + 1_000_000
        code = next((c for a, b, c in self.FIXED_RANGES if a <= lo < b), None)
        if code is None:
            return
        self.civ._commands.put((0x27, 0x1E, code, 0x03, *to_bcd_le(lo), *to_bcd_le(hi)))
        self.civ._commands.put((0x27, 0x16, 0x00, 0x03))      # bords n° 3
        self.civ._commands.put((0x27, 0x14, 0x00, 0x01))      # mode fixe

    def _fr_span(self, hz):
        """Boutons de l'écran : BANDE (0) = bande entière, sinon largeur centrée."""
        self.fr_full = hz == 0
        if self.fr_full:
            self._fr_full_band()
        else:
            if self.civ:
                self.civ._commands.put((0x27, 0x14, 0x00, 0x00))     # mode centré
            index = self.span_combo.findData(hz)
            if index >= 0:
                self.span_combo.setCurrentIndex(index)
                self.on_span_selected()
        self.fr_screen.set_span(hz)

    def _fr_toggled(self, on):
        if on:
            self.fr_saved_span = self.span_combo.currentData()
            self._fr_span(0)                    # toute la bande dès l'ouverture
            self._fr_tick()
            self.fr_screen.start()
            self.fr_timer.start(250)
            self._fr_show()                     # visible tout de suite ; RETOUR = veille
        else:
            self.fr_timer.stop()
            self.fr_screen.stop()
            self.fr_full = False
            if self.civ:
                self.civ._commands.put((0x27, 0x14, 0x00, 0x00))     # scope centré, comme avant
            if self.fr_saved_span is not None \
                    and self.fr_saved_span != self.span_combo.currentData():
                self._fr_span(self.fr_saved_span)       # largeur d'avant rendue
            self.fr_saved_span = None
            self._restore_windows(self.fr_hidden)
            self.fr_hidden = []

    def _fr_open_now(self, *_):
        """Clic droit sur l'interrupteur : écran ouvert tout de suite (veille lancée)."""
        if not self.fr_toggle.down:
            self.fr_toggle.setDown(True)
        self._fr_show()

    def _fr_show(self):
        """Écran WATERFALL FR au premier plan, plein écran. Ouvert seulement à la
        demande (levier, clic droit) : plus aucune condition ne le bloque."""
        if self.ft8_toggle.down:                # un seul écran plein : FT8 / RTTY fermés
            self.ft8_toggle.setDown(False)
        if self.rtty_toggle.down:
            self.rtty_toggle.setDown(False)
        screen = (self.windowHandle().screen() if self.windowHandle()
                  else QtWidgets.QApplication.primaryScreen())
        self.fr_screen.setGeometry(screen.geometry())
        self.fr_screen.showFullScreen()
        self.fr_screen.raise_()
        self.fr_screen.activateWindow()
        self.statusBar().showMessage("WATERFALL FR ouvert (RETOUR ou Échap pour revenir)", 4000)

        def hide_others():
            if self.fr_toggle.down and self.fr_screen.isVisible():
                keep = {int(self.fr_screen.winId())}
                if self.console_button.isChecked():
                    keep |= set(console.terminal_windows())
                self.fr_hidden = self._hide_windows(keep)
        QtCore.QTimer.singleShot(400, hide_others)

    def _fr_reduce(self):
        """RETOUR : écran réduit, la recherche continue (clic droit sur
        l'interrupteur pour le rouvrir)."""
        self.fr_screen.hide()
        self._restore_windows(self.fr_hidden)
        self.fr_hidden = []
        self.statusBar().showMessage(
            "WATERFALL FR réduit : clic droit sur l'interrupteur pour le rouvrir", 6000)

    def _fr_found(self, s):
        """Nouvelle station française : seulement signalée (l'écran ne s'ouvre
        plus tout seul, à la demande de l'utilisateur le 27/10)."""
        if not self.fr_toggle.down:
            return
        self.statusBar().showMessage(
            f"Station française trouvée : {s['call']} sur {s['hz'] / 1000:.1f} kHz "
            "(clic droit sur WATERFALL FR pour voir)", 10000)

    def _fr_tune(self, hz, mode):
        """Clic dans l'écran WATERFALL FR : calage immédiat et précis."""
        if not self.civ:
            return
        self._manual_tuning()
        if mode and mode in MODE_NAMES and mode != self.mode_combo.currentText():
            self.mode_combo.setCurrentText(mode)
            self._sync_mode_buttons()
            self.civ.set_mode(mode)
            self._update_markers()
        self._fr_set(hz)
        self._fr_voice_calage()

    def _fr_set(self, hz):
        """Fréquence choisie dans WATERFALL FR : elle devient la référence du calage
        voix (pas de retour forcé au kHz rond : la station peut être à 14 131,48)."""
        self.ssb_target = hz                    # notre propre réglage, pas « à la main »
        self.ssb_anchor = hz
        self.tune_to(hz)

    def _fr_fine(self, hz):
        """Glisser / molette dans WATERFALL FR : la radio suit, au hertz près."""
        if not self.civ:
            return
        if not getattr(self, "_fr_fine_on", False):
            self._fr_fine_on = True
            self._manual_tuning()               # une fois par réglage : recherches arrêtées
        self._fr_set(hz)

    def _fr_voice_calage(self):
        """Fin du réglage : en BLU, le CALAGE AUTO BLU écoute la voix et ajuste
        la fréquence au plus juste (voix naturelle), jusqu'à ± PULL_MAX autour
        de la fréquence choisie."""
        self._fr_fine_on = False
        if base_mode(self.mode_combo.currentText()) in ("LSB", "USB") \
                and self.ssb_auto.isChecked():
            def pull():
                self._start_pull(True)
                self.ssb_anchor = self.freq_hz  # référence : la fréquence choisie
                tuner = self.audio.ssb_tuner
                tuner.fast = True               # signal faible accepté, décision rapide
                tuner.candidates = None         # pas de kHz rond imposé (station à x,48…)
                tuner.request_reset()
            QtCore.QTimer.singleShot(300, pull)

    def _ft8_keep_map_below(self):
        """Quand WSJT-X est au premier plan, la carte doit être juste dessous
        (sinon c'est le Scope qu'on verrait à travers WSJT-X)."""
        def root(prop):
            out = subprocess.run(["xprop", "-root", prop], capture_output=True,
                                 text=True).stdout
            return [int(x, 16) for x in re.findall(r"0x[0-9a-f]+", out)]
        active = root("_NET_ACTIVE_WINDOW")
        if not active or active[0] not in self.ft8_ids:
            return
        stack = root("_NET_CLIENT_LIST_STACKING")
        map_id, main = int(self.ft8_map.winId()), int(self.ft8_window, 16)
        if map_id not in stack or main not in stack:
            return
        i_map, i_main = stack.index(map_id), stack.index(main)
        if i_map < i_main and all(w in self.ft8_ids for w in stack[i_map + 1:i_main]):
            return
        subprocess.run(["wmctrl", "-i", "-a", hex(map_id)])
        for w in [w for w in stack if w in self.ft8_ids and w != main] + [main]:
            subprocess.run(["wmctrl", "-i", "-a", hex(w)])

    # appelées par ft8_bridge (WSJT-X → radio)
    def ft8_get_freq(self):
        return self.freq_hz

    def ft8_set_freq(self, hz):
        if not self.tx_active and hz != self.freq_hz:
            self.tune_to(hz)

    def ft8_get_mode(self):
        mode = self.mode_combo.currentText()
        return self.HAMLIB_MODES.get(mode, mode)

    def ft8_set_mode(self, name):
        mode = {v: k for k, v in self.HAMLIB_MODES.items()}.get(name, name)
        if self.civ and mode in MODE_NAMES and mode != self.mode_combo.currentText():
            self.mode_combo.setCurrentText(mode)
            self._sync_mode_buttons()
            self.civ.set_mode(mode)

    def ft8_get_ptt(self):
        return self.tx_active

    def ft8_set_ptt(self, on):
        """Émission FT8 : mode data, son pris sur l'USB (WSJT-X), micro coupé."""
        if on and not self.tx_active and self.civ:
            self.civ.set_ptt(True, data=True)
            self.ft8_tx = True
            self.tx_limit = TX_TIMEOUT
            self.tx_active = True
            self.tx_galva.set_tx(True)
            self._pactl_stream("set-sink-input-mute", "1")     # écoute muette en émission
            self._update_ssb()
            self.tx_started = time.monotonic()
            self.tx_timer.start()
            self._set_ptt_button(True)
        elif not on and self.tx_active:
            self.ft8_tx = False
            self.stop_tx()

    def _demo_toggled(self, on):
        """Interrupteur DÉMO : levier en bas = la souris devient un gros doigt."""
        if on:
            self.demo_finger.start()
            self.statusBar().showMessage(
                f"Démo : doigt {self.demo_finger.size_name.lower()} (clic droit sur DÉMO "
                "pour la taille)", 4000)
        else:
            self.demo_finger.stop()

    def _demo_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        for name in DEMO_SIZES:
            action = menu.addAction(f"Doigt {name.lower()}")
            action.setCheckable(True)
            action.setChecked(name == self.demo_finger.size_name)
            action.triggered.connect(lambda _, n=name: self.demo_finger.set_size(n))
        menu.exec_(self.demo_toggle.mapToGlobal(pos))

    def _loupe_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        for z in range(2, 11):
            action = menu.addAction(f"Grossissement × {z}")
            action.setCheckable(True)
            action.setChecked(z == self.loupe.zoom)
            action.triggered.connect(lambda _, z=z: self.loupe.set_zoom(z))
        menu.exec_(self.loupe_toggle.mapToGlobal(pos))

    def _calage_ok(self, hz):
        """Un calage automatique peut-il encore aller sur hz ? (voir tune_to)"""
        chosen = getattr(self, "_chosen", None)
        if chosen is None:
            return False
        if abs(hz - chosen[0]) <= CALAGE_FINE_HZ:
            return True             # affinage par la voix : toujours permis, sans dériver
        return (time.monotonic() - chosen[1] <= CALAGE_WINDOW_S
                and abs(hz - chosen[0]) <= CALAGE_MAX_HZ)

    def _manual_tuning(self):
        """L'opérateur règle la fréquence lui-même : toute recherche automatique
        (DÉCODAGE CW, SCAN, CHERCHER QSO FR) s'arrête et la fréquence reste là."""
        if self.cw_hunter.active:
            self.cw_hunter.stop()
            self.cw_info.setText("Balayage arrêté (réglage à la main) : décodage sur place")
        if self.scanner.active:
            self.scan_button.setChecked(False)
        if self.hunter.active:
            self.hunt_button.setChecked(False)
        self.statusBar().showMessage("Réglage à la main : recherches automatiques arrêtées", 3000)

    def on_tuned(self, steps):
        self._manual_tuning()
        if self.freq_hz is None:
            return
        step = self.step_combo.currentData()
        base = self.freq_hz // step * step
        if steps < 0 and base != self.freq_hz:
            steps += 1                      # on s'aligne d'abord sur le pas
        self.tune_to(base + steps * step)

    def _fine_step(self):
        """Pas fin enclenché sur la plaque (Hz), ou None."""
        return next((hz for hz, sw, _ in self.fine_switches if sw.isChecked()), None)

    def _fine_step_toggled(self, hz, on):
        if on:                              # un seul pas fin à la fois
            for other, sw, _ in self.fine_switches:
                if other != hz and sw.isChecked():
                    sw.blockSignals(True)
                    sw.setChecked(False)
                    sw.blockSignals(False)
        for other, sw, led in self.fine_switches:
            led.set_mode("blink" if sw.isChecked() else "off")
        self._vfo_step_leds(self.vfo_step_switch.isChecked())

    def _vfo_step_leds(self, on_100k):
        fine = hasattr(self, "fine_switches") and self._fine_step() is not None
        # pas fin enclenché : les LED 50/100 kHz s'éteignent (pas inutilisé)
        self.led_100k.set_mode("off" if fine else "on" if on_100k else "off")
        self.led_50k.set_mode("off" if fine or on_100k else "blink")

    def on_knob_tuned(self, steps):
        """Bouton VFO : pas de 50 kHz ou 100 kHz selon l'interrupteur à levier."""
        self._manual_tuning()
        if self.freq_hz is None:
            return
        step = self._fine_step() or self.step_combo.currentData()   # sinon : pas du menu
        base = self.freq_hz // step * step
        if steps < 0 and base != self.freq_hz:
            steps += 1                      # on s'aligne d'abord sur le pas
        self.tune_to(base + steps * step)

    def on_freq_entered(self):
        self._manual_tuning()
        hz = parse_frequency(self.freq_entry.text())
        if hz is None:
            self.statusBar().showMessage("Fréquence non comprise")
            return
        self.freq_entry.clear()
        self.tune_to(hz)

    def on_mode_selected(self, name):
        self._sync_mode_buttons()
        self._update_markers()
        if self.civ:
            self.civ.set_mode(name)

    def on_other_frequency(self, hz):
        self.other_hz = hz
        self._show_other()

    def on_other_mode(self, name):
        self.other_mode = name
        self._show_other()

    def _show_other(self):
        name = {"A": "B", "B": "A"}.get(self.active_vfo, "autre")
        text = "--.---.---"
        if self.other_hz is not None:
            text = format_frequency(self.other_hz)
        self.other_label.setText(f"{name} : {text} {self.other_mode}".rstrip())

    def on_vfo_operation(self, code):
        if not self.civ:
            return
        if code == 0x00:
            self.active_vfo = "A"
        elif code == 0x01:
            self.active_vfo = "B"
        elif code == 0xB0 and self.active_vfo:
            self.active_vfo = "B" if self.active_vfo == "A" else "A"
        self.vfo_label.setText(f"VFO {self.active_vfo or '?'}")
        self._show_other()
        self.civ.vfo_operation(code)

    def on_power(self, raw):
        self.power_slider.setEnabled(True)
        self.power_knob.setEnabled(True)
        # bouton POWER tourné il y a moins de 2 s : la radio renvoie encore
        # l'ancienne valeur (surtout pendant le SCAN) ; on ne l'écoute pas
        if time.monotonic() - getattr(self, "_power_user_at", 0) < 2:
            return
        if not self.power_slider.isSliderDown():
            self.power_slider.blockSignals(True)
            self.power_slider.setValue(round(raw * 100 / 255))
            self.power_slider.blockSignals(False)
        self.power_label.setText(f"≈ {self.power_slider.value()} W")
        if not self.power_knob._dragging:
            self.power_knob.setValue(self.power_slider.value())

    def on_power_slider(self, percent):
        self._power_user_at = time.monotonic()
        self.power_label.setText(f"≈ {percent} W")
        self.power_knob.setValue(percent)
        if self.civ:
            self.civ.set_power(round(percent * 255 / 100))

    def on_usb_mod(self, raw):
        self.alc_slider.setEnabled(True)
        self.alc_knob.setEnabled(True)
        if not self.alc_slider.isSliderDown():
            self.alc_slider.blockSignals(True)
            self.alc_slider.setValue(round(raw * 100 / 255))
            self.alc_slider.blockSignals(False)
        self.alc_slider_label.setText(f"{self.alc_slider.value()} %")
        if not self.alc_knob._dragging:
            self.alc_knob.setValue(self.alc_slider.value())

    def on_alc_slider(self, percent):
        self.alc_slider_label.setText(f"{percent} %")
        self.alc_knob.setValue(percent)
        if self.civ:
            self.civ.set_usb_mod(round(percent * 255 / 100))

    def on_tx_source(self):
        is_file = self.tx_source.currentData() == "file"
        self.tx_file_button.setVisible(is_file)
        if is_file and self.tx_file:
            self.tx_file_button.setText(os.path.basename(self.tx_file))
        if not is_file and hasattr(self, "eq_engine"):
            self.eq_engine.start(self.tx_source.currentData())
        # liaison micro → radio préparée pour le nouveau micro (coupée hors émission)
        if (hasattr(self, "tx_loopback_input") and not is_file
                and not getattr(self, "tx_active", False)):
            self._tx_mic_mute(self.tx_source.currentData(), True)
        # VOX en marche : il écoute le micro qu'on vient de choisir
        vox_monitor = getattr(self, "vox_monitor", None)
        if vox_monitor and not is_file and vox_monitor.source != self.tx_source.currentData():
            vox_monitor.stop()
            self.vox_monitor = VoxMonitor(self.tx_source.currentData())
            self.vox_monitor.level.connect(self.on_vox_level)
            self.vox_monitor.start()

    def choose_tx_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Fichier à émettre", RECORD_DIR,
            "Audio (*.wav *.flac *.ogg);;Tous les fichiers (*)")
        if path:
            self.tx_file = path
            self.tx_file_button.setText(os.path.basename(path))

    def on_tx_level(self, value):
        self.tx_level_label.setText(f"{value} %")
        self.level_knob.setValue(value)
        subprocess.run(["pactl", "set-sink-volume", self.radio_sink, f"{value}%"],
                       capture_output=True)

    def on_ptt(self, on):
        if on:
            self.start_tx()
        else:
            self.stop_tx()

    def start_tx(self):
        source = self.tx_source.currentData()
        problem = None
        if not self.civ:
            problem = "Émission impossible sans CAT"
        elif source == "file" and not self.tx_file:
            problem = "Choisis d'abord un fichier à émettre"
        if problem:
            self.statusBar().showMessage(problem)
            self._set_ptt_button(False)
            return
        self.civ.set_ptt(True, data=self.tx_digital)
        if source == "file":
            # un temps pour que la radio passe en émission avant le son
            QtCore.QTimer.singleShot(400, self._play_tx_file)
        else:
            self._tx_mic_mute(source, False)
            if not self.vox_monitor:
                self.tx_mic_monitor = VoxMonitor(source)
                self.tx_mic_monitor.level.connect(self.on_vox_level)
                self.tx_mic_monitor.start()
        self.tx_limit = TX_TIMEOUT
        if source == "file":
            try:
                with wave.open(self.tx_file) as w:
                    length = w.getnframes() / w.getframerate()
                self.tx_limit = max(TX_TIMEOUT, length + 15)
            except (OSError, wave.Error, EOFError):
                pass
        self.tx_active = True
        self.tx_galva.set_tx(True)
        self._pactl_stream("set-sink-input-mute", "1")     # casque muet pendant l'émission
        self._update_ssb()              # pas de calage BLU en émission
        self.tx_started = time.monotonic()
        self.tx_timer.start()
        self._set_ptt_button(True)

    def open_sstv(self):
        if self.sstv_window is None:
            self.sstv_window = SstvWindow(self)
        self.sstv_window.show()
        self.sstv_window.raise_()
        self.sstv_window.activateWindow()

    def transmit_file(self, path):
        """Émet un fichier (utilisé par la fenêtre SSTV)."""
        if self.tx_active:
            return
        self.tx_file = path
        self.tx_digital = True
        self.tx_source.setCurrentIndex(self.tx_source.findData("file"))
        self.on_tx_source()
        self.ptt_button.setChecked(True)

    def _play_tx_file(self):
        if self.tx_active:
            self.tx_player = subprocess.Popen(
                ["paplay", f"--device={self.radio_sink}", self.tx_file])

    TX_MIC_NODE = "ic7300_tx_micro"

    def _tx_mic_unload(self):
        """Supprime la liaison micro → radio (et les restes d'une session plantée)."""
        out = subprocess.run(["pactl", "list", "modules", "short"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if self.TX_MIC_NODE in line:
                subprocess.run(["pactl", "unload-module", line.split()[0]],
                               capture_output=True)
        self.tx_loopback = None
        self.tx_loopback_source = None
        self.tx_loopback_input = None

    def _tx_mic_mute(self, source, mute):
        """Liaison micro → radio ouverte en permanence : on coupe ou rétablit
        seulement le son. La créer/supprimer à chaque émission réorganisait le son
        du PC et figeait la réception plusieurs secondes."""
        if source is not None and self.tx_loopback:
            # la liaison d'émission vers le Pi a pu tomber et être recréée :
            # notre module a alors disparu avec elle
            modules = subprocess.run(["pactl", "list", "modules", "short"],
                                     capture_output=True, text=True).stdout
            if not any(line.split("\t")[0] == self.tx_loopback
                       for line in modules.splitlines()):
                self.tx_loopback = None
        if source is not None and (not self.tx_loopback
                                   or self.tx_loopback_source != source):
            self._tx_mic_unload()
            out = subprocess.run(
                ["pactl", "load-module", "module-loopback",
                 f"source={self.eq_engine.monitor_for(source)}",
                 f"sink={self.radio_sink}", "latency_msec=40",
                 "source_dont_move=true", "sink_dont_move=true",
                 # rôle à part : sinon le système son mémorise la coupure du micro
                 # pour toutes les liaisons et la réception démarrait muette
                 f"sink_input_properties='node.name={self.TX_MIC_NODE} "
                 "media.role=ic7300tx'"],
                capture_output=True, text=True)
            self.tx_loopback = out.stdout.strip() or None
            self.tx_loopback_source = source
            self.tx_loopback_input = None
        if not self.tx_loopback:
            return
        if self.tx_loopback_input is None:
            for _ in range(60):             # le flux apparaît un instant après le module
                try:
                    streams = json.loads(subprocess.run(
                        ["pactl", "-f", "json", "list", "sink-inputs"],
                        capture_output=True, text=True, env=PACTL_ENV).stdout)
                except ValueError:
                    streams = []
                for stream in streams:
                    if stream["properties"].get("node.name") == self.TX_MIC_NODE:
                        self.tx_loopback_input = str(stream["index"])
                if self.tx_loopback_input:
                    break
                time.sleep(0.05)
        if self.tx_loopback_input:
            subprocess.run(["pactl", "set-sink-input-mute", self.tx_loopback_input,
                            "1" if mute else "0"], capture_output=True)
        # enregistrement : le micro en permanence ; coupé quand il part déjà vers la
        # radio (il est alors enregistré par le chemin d'émission : pas de doublon)
        self._rec_mic(self.tx_loopback_source, record=mute)

    REC_MIC_NODE = "ic7300_enreg_micro"

    def _rec_mic_unload(self):
        out = subprocess.run(["pactl", "list", "modules", "short"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if self.REC_MIC_NODE in line:
                subprocess.run(["pactl", "unload-module", line.split()[0]],
                               capture_output=True)
        self.rec_mic_module = self.rec_mic_monitor = self.rec_mic_input = None

    def _rec_links_check(self):
        """Sortie d'enregistrement : réception et émission toujours actives, micro
        actif hors émission. Le système son peut les remettre muettes (mémoire par
        rôle) : on rétablit."""
        if not self.tx_active:
            self._rec_mic(self.tx_loopback_source, record=True)
        try:
            streams = json.loads(subprocess.run(
                ["pactl", "-f", "json", "list", "sink-inputs"],
                capture_output=True, text=True, env=PACTL_ENV, timeout=2).stdout)
        except (ValueError, OSError, subprocess.SubprocessError):
            return
        for stream in streams:
            if stream["properties"].get("node.name") in ("ic7300_enreg_rx", "ic7300_enreg_tx") \
                    and stream["mute"]:
                subprocess.run(["pactl", "set-sink-input-mute", str(stream["index"]), "0"],
                               capture_output=True)

    def _rec_mic(self, source, record):
        """Liaison micro → sortie d'enregistrement (SimpleScreenRecorder)."""
        if not source:
            return
        monitor = self.eq_engine.monitor_for(source)
        if getattr(self, "rec_mic_monitor", None) != monitor or not getattr(
                self, "rec_mic_module", None):
            self._rec_mic_unload()
            out = subprocess.run(
                ["pactl", "load-module", "module-loopback", f"source={monitor}",
                 f"sink={RECORD_SINK}", "latency_msec=60",
                 "source_dont_move=true", "sink_dont_move=true",
                 f"sink_input_properties='node.name={self.REC_MIC_NODE} "
                 "media.role=ic7300rec'"],
                capture_output=True, text=True)
            self.rec_mic_module = out.stdout.strip() or None
            self.rec_mic_monitor = monitor
        if not self.rec_mic_module:
            return
        if self.rec_mic_input is None:
            for _ in range(40):
                try:
                    streams = json.loads(subprocess.run(
                        ["pactl", "-f", "json", "list", "sink-inputs"],
                        capture_output=True, text=True, env=PACTL_ENV).stdout)
                except ValueError:
                    streams = []
                for stream in streams:
                    if stream["properties"].get("node.name") == self.REC_MIC_NODE:
                        self.rec_mic_input = str(stream["index"])
                if self.rec_mic_input:
                    break
                time.sleep(0.05)
        if self.rec_mic_input:
            done = subprocess.run(["pactl", "set-sink-input-mute", self.rec_mic_input,
                                   "0" if record else "1"], capture_output=True)
            if done.returncode != 0:            # flux recréé : on le recherchera
                self.rec_mic_input = None

    def stop_tx(self, reason=None):
        self._backlight_tx(False)           # rétro-éclairage : retour au calme
        mon = getattr(self, "vox_monitor_player", None)
        if mon is not None and mon.poll() is None:
            mon.terminate()                     # retour BF coupé avec l'émission
        self.vox_monitor_player = None
        if getattr(self, "vox_msg_sending", None):
            self.vox_msg_sending = None
            self._mot_vox_need()
            self._vox_msg_show()
        if self.tx_player:
            self.tx_player.terminate()
            self.tx_player = None
        if self.tx_loopback:
            self._tx_mic_mute(None, True)       # liaison gardée ouverte, micro coupé
        if self.civ:
            self.civ.set_ptt(False)
        self.tx_active = False
        self.tx_galva.set_tx(False)
        self.power_meter.reset()
        self.swr_galva.reset()
        self.swr_alarm = False
        self.tx_stopped_at = time.monotonic()
        # retour de l'écoute au casque (sauf si « Muet » est coché)
        self._pactl_stream("set-sink-input-mute", "1" if self.mute_check.isChecked() else "0")
        if getattr(self, "tx_mic_monitor", None):
            self.tx_mic_monitor.stop()
            self.tx_mic_monitor = None
        self.mic_db = None
        if self.vox_tx:
            self.vox_tx = False
            QtCore.QTimer.singleShot(0, lambda: self._vox_disarm(
                "VOX coupé : émission terminée. Rappuie sur VOX pour le réarmer"))
        self._update_ssb()
        self.tx_digital = False
        self.tx_timer.stop()
        self._set_ptt_button(False)
        self.tx_meter_label.setText("")
        for meter, value in ((self.swr_meter, self.swr_value),
                             (self.comp_meter, self.comp_value),
                             (self.alc_meter, self.alc_value),
                             (self.id_meter, self.id_value)):
            meter.value = meter.minimum         # remise à zéro directe (sans descente lente)
            meter.update()
            value.setText("")
        self.po_meter.value = self.po_meter.minimum
        self.po_meter.update()
        if reason:
            self.statusBar().showMessage(reason)

    def _set_ptt_button(self, on):
        self.red_button.blockSignals(True)          # le bouton rouge suit l'émission
        self.red_button.setChecked(on)
        self.red_button.blockSignals(False)
        self.ptt_button.blockSignals(True)
        self.ptt_button.setChecked(on)
        self.ptt_button.blockSignals(False)
        self.ptt_button.setText("■ ARRÊTER" if on else "ÉMETTRE")
        self.ptt_button.setStyleSheet(
            "background: #c62828; color: white; font-weight: bold;" if on else "")

    def check_tx(self):
        elapsed = time.monotonic() - self.tx_started
        if elapsed > self.tx_limit:
            self.stop_tx(f"Émission coupée au bout de {elapsed / 60:.0f} min")
        elif self.tx_player and self.tx_player.poll() is not None:
            n = self.vox_msg_sending
            self.stop_tx(f"VOX{n} : message émis, retour en réception" if n
                         else "Fichier émis en entier")

    def _cw_scope_update(self):
        """Réception CW (et seulement elle) : l'oscilloscope montre la
        manipulation reçue ; sinon, la voix du micro."""
        cw = (self.mode_combo.currentText() in ("CW", "CW-R") and not self.tx_active
              and not getattr(self.civ, "_tx", False))
        self.audio.cw_env_pitch = (getattr(self, "cw_note", None) or self.radio_cw_pitch) if cw else None
        # créneaux seulement si de la CW est vraiment reçue (gardés 3 s après)
        if cw and self.voice_scope.has_cw():
            self.cw_seen_t = time.monotonic()
        received = cw and time.monotonic() - getattr(self, "cw_seen_t", 0) < 3.0
        self.voice_scope.set_cw(received)

    def _backlight_tx(self, on, watts=None):
        """Émission en cours ou non : en émission, le rétro-éclairage des
        tambours suit la voix (minuterie _backlight_voice)."""
        self.backlight_on_air = on
        if on:
            if not self.backlight_timer.isActive():
                self.backlight_timer.start(30)
        else:
            self.backlight_timer.stop()
            self.freq_label.set_voice(None)
            self.m_freq.set_voice(None)
            self._pump_meters(None)
            self.clocks.set_voice(None)

    def _pump_meters(self, light):
        """S-mètre et 3 petits galvas : lumière du centre qui suit la lampe des
        tambours en émission ; éclairage normal en réception."""
        value = light if self.backlight_on_air else None
        for meter in (self.s_meter, self.tx_galva.po_g, self.tx_galva.comp_g, self.ssb_meter):
            if getattr(meter, "pump", None) != value:
                meter.pump = value
                meter.update()

    def _backlight_voice(self):
        level = self.voice_scope.voice_level()
        self.freq_label.set_voice(level)
        self.m_freq.set_voice(level)
        self.clocks.set_voice(level)

    def on_transmitting(self, tx):
        if self.cw_station is not None:
            self.cw_station.set_tx(tx)      # cadre EMISSION plus vif pendant l'émission
        self.voice_scope.set_tx(tx)        # vobulation seulement en émission
        if not tx and not self.tx_active:
            self.power_meter.setValue(0)        # plus d'émission : aiguille à 0
            self._backlight_tx(False)
        elif tx:
            self._backlight_tx(True)
        delay = 6 if str(self.civ.port).startswith("socket://") else 2
        if self.tx_active and not tx and time.monotonic() - self.tx_started > delay:
            self.stop_tx("La radio n'émet pas (hors bande amateur ?)")

    SWR_ALARM = 2.0

    def _swr_led_paint(self, on):
        if hasattr(self, "swr_galva"):
            self.swr_galva.set_led(on)          # LED du micro-galva ROS
        if hasattr(self, "swr_title"):
            self.swr_title.set_alert(on)        # « R . O . S » clignote avec la LED
        top, edge = ("#ffb0a0", "#ff1a0a") if on else ("#4a1a14", "#1e0604")
        self.swr_led.setStyleSheet(
            "border-radius: 6px; border: 1px solid #111;"
            f"background: qradialgradient(cx:0.35, cy:0.35, radius:0.8, fx:0.35, fy:0.35, "
            f"stop:0 {top}, stop:1 {edge});")

    def _swr_led_tick(self):
        if self.swr_alarm and self.tx_active:
            self.swr_blink = not self.swr_blink
            self._swr_led_paint(self.swr_blink)
        elif self.swr_blink:
            self.swr_blink = False
            self._swr_led_paint(False)

    def on_tx_meters(self, po, swr, alc):
        if self._vox_silent():
            return                              # barres seulement sur la voix
        self.swr_meter.setValue(swr)
        self.swr_galva.setValue(swr)
        self.swr_galva.set_ratio(piecewise(swr, SWR_POINTS))
        self.swr_value.setText(f"{piecewise(swr, SWR_POINTS):.1f}")
        self.tx_galva.set_swr(piecewise(swr, SWR_POINTS))
        self.swr_alarm = piecewise(swr, SWR_POINTS) > self.SWR_ALARM      # strictement au-dessus de 2
        percent = alc * 100 / ALC_ZONE
        self.tx_galva.set_alc(percent)
        self.alc_meter.setValue(percent)
        self.alc_value.setText(f"{percent:.0f}")
        self.tx_meter_label.setText(f"Po {piecewise(po, PO_POINTS):3.0f} %")

    def _vox_silent(self):
        """Vrai pour une mesure d'émission arrivée en retard, juste après le
        retour en réception : elle rallumerait les barres remises à zéro."""
        if not self.tx_active and time.monotonic() - getattr(self, "tx_stopped_at", 0) < 1.5:
            return True
        return False                    # barres continues tant que la radio émet
        if not (self.vox_tx and time.monotonic() - self.vox_last_voice > 0.12):
            return False
        for meter in (self.po_meter, self.alc_meter, self.swr_meter,
                      self.comp_meter, self.id_meter):
            meter.value = meter.minimum
            meter.update()
        return True

    def on_po(self, raw):
        if self.tx_active:              # journal provisoire : rythme des mesures Po
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "po.log"), "a") as log:
                    log.write(f"{time.monotonic():.3f} {raw} {getattr(self, 'mic_db', None)}\n")
            except OSError:
                pass
        if self._vox_silent():
            return                              # barres seulement sur la voix
        watts = piecewise(raw, PO_POINTS)       # % de 100 W = watts
        if self.tx_active or watts > 0.5:       # rétro-éclairage : seulement en émission réelle
            self._backlight_tx(True, watts)
        self.po_meter.setValue(watts)
        self.tx_galva.set_po(watts)
        self.power_meter.setValue(watts)
        now = time.monotonic()
        # puissance du moment, comme l'écran de la radio (plus de pointe tenue 4 s)
        self.po_peak_w, self.po_peak_t = max(watts, self.po_peak_w * 0.85), now
        self.po_value.setText(f"{self.po_peak_w:.0f} W" if self.po_peak_w >= 1 else "")

    def on_drain(self, raw):
        if self._vox_silent():
            return
        amps = piecewise(raw, ID_POINTS)
        self.id_meter.setValue(amps)
        self.id_value.setText(f"{amps:.1f} A")

    def on_comp(self, raw):
        if self._vox_silent():
            return
        db = piecewise(raw, COMP_POINTS)
        self.comp_meter.setValue(db)
        self.tx_galva.set_comp(db)
        self.comp_value.setText(f"{db:.0f}")

    def on_emergency(self):
        """ARRÊT D'URGENCE : coupe tout ce qui peut émettre, tout de suite."""
        acknowledge = self.emergency_button.flashing   # appui pendant les flashs : fin
        if acknowledge:
            self.emergency_button.set_flashing(False)
        try:
            self.message_timer.stop()               # message / saisie CW
            self.message_chunks = []
            self.message_toggle.setDown(False, emit=False)
            if self.vox_button.isChecked():         # VOX désarmé
                self.vox_button.setChecked(False)
            self.vox_msg_armed.clear()              # VOX1… : plus rien en attente
            self.vox_msg_dry_auto.clear()
            if self.vox_dry_player is not None:
                self.vox_dry_player.terminate()
        except Exception:
            pass
        if self.civ:
            self.civ.stop_cw()
            self.civ.set_ptt(False)
            self.civ._commands.put((0x1C, 0x00, 0x00))      # TX OFF direct (accord compris)
        self.stop_tx("⛔ ARRÊT D'URGENCE : émission coupée")
        if self.civ:                                # redit plus tard : rien ne repart
            for ms in (300, 1000):
                QtCore.QTimer.singleShot(ms, lambda: self.civ and self.civ.set_ptt(False))
        self.tune_plate.set_lit(False)
        self.red_button.set_alert(False)
        self._mot_vox_need()
        self._vox_msg_show()
        self._vox_log("ARRÊT D'URGENCE")
        self.emergency_at = time.monotonic()
        if not acknowledge:
            QtCore.QTimer.singleShot(5000, self._emergency_flash)

    def _emergency_flash(self):
        """5 s après l'arrêt d'urgence : flashs par séries de 3 (nouvel appui = fin)."""
        if time.monotonic() - getattr(self, "emergency_at", 0) >= 4.9:
            self.emergency_button.set_flashing(True)

    def on_tune(self):
        if self.civ:
            self.civ.tune()
            # flash dès l'appui ; la radio peut répondre « pas d'accord » juste
            # avant de commencer : on attend qu'elle annonce l'accord (3 s au
            # plus), puis le flash s'arrête dès qu'elle en annonce la fin
            self.tune_seen = False
            self.tune_wait_until = time.monotonic() + 3
            QtCore.QTimer.singleShot(3100, lambda: self.on_tuner(getattr(self, "tuner_state", 0x01)))
            self.tune_plate.set_lit(True)
            self.red_button.set_alert(True)

    def on_onoff(self):
        if not self.civ:
            return
        if self.radio_on:
            # vert : on arrête tout, la radio puis IC-7300 Scope
            self.civ.set_radio_power(False)
            self.on_alive(False)
            self.statusBar().showMessage("Arrêt de la radio et du scope…")
            QtCore.QTimer.singleShot(2500, self.close)   # le temps d'envoyer l'ordre
        else:
            # un appui sur OFF : on allume ; ON vert dès que la radio répond
            self.civ.set_radio_power(True)
            self.onoff_button.setText("ON / OFF …")

    def on_alive(self, on):
        self.radio_on = on
        self.onoff_button.setText("ON / OFF")
        if on:
            self.onoff_button.setStyleSheet(POWER_ON)
            self.onoff_button.setToolTip("En marche : cliquer pour arrêter la radio "
                                         "et fermer IC-7300 Scope")
        else:
            self.onoff_button.setStyleSheet(POWER_OFF)
            self.onoff_button.setToolTip("Radio arrêtée : cliquer pour l'allumer")

    def on_atu(self, on):
        if self.civ:
            self.civ.set_atu(on)

    def on_tuner(self, state):
        self.tuner_state = state
        self.atu_button.setChecked(state in (0x01, 0x02))
        if state == 0x02:
            self.tune_seen = True               # la boîte travaille
            tuning = True
        elif not getattr(self, "tune_seen", True) and \
                time.monotonic() < getattr(self, "tune_wait_until", 0):
            tuning = True                       # pas encore commencé : on attend
        else:
            tuning = False                      # fin de l'accord : arrêt immédiat
            self.tune_seen = True
        self.tune_button.setText("TUNE…" if tuning else "TUNE")
        self.tune_plate.set_lit(tuning)
        self.red_button.set_alert(tuning)       # voyant vert : flash rouge rapide
        if not tuning and not self.tx_active:
            self.power_meter.setValue(0)
            self._backlight_tx(False)
        self.tune_button.setStyleSheet(POWER_OFF if tuning else PUSH_3D)

    def _pactl_stream(self, *args):
        """Commande pactl sur le flux d'écoute ; le retrouve s'il a changé."""
        for attempt in range(2):
            if attempt or not self.loopback:
                self.loopback = find_loopback_stream()
            if not self.loopback:
                break
            cmd = ["pactl", args[0], str(self.loopback[0]), *args[1:]]
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return
        self.statusBar().showMessage("Écoute radio → PC introuvable dans PipeWire")

    def attach_loopback(self):
        """Relie « Volume PC » et « Muet » au flux d'écoute s'il existe."""
        self.loopback = find_loopback_stream()
        found = self.loopback is not None
        tips = ("Volume du son de la radio sur le PC", "")
        for widget, tip in zip((self.pc_volume, self.mute_check), tips):
            widget.setEnabled(found)
            widget.setToolTip(tip if found else "Écoute radio → PC introuvable dans PipeWire")
        if found:
            self.loopback_timer.stop()
            _, volume, muted = self.loopback
            if muted and not getattr(self, "_loopback_seen", False):
                # sourdine laissée par une session précédente (RM Noise…) : au
                # démarrage aucun filtre ne tourne, le son direct doit revenir
                subprocess.run(["pactl", "set-sink-input-mute", str(self.loopback[0]), "0"],
                               capture_output=True)
                muted = False
            self._loopback_seen = True
            for widget, value in ((self.pc_volume, volume), (self.mute_check, muted)):
                widget.blockSignals(True)
                widget.setValue(value) if widget is self.pc_volume else widget.setChecked(value)
                widget.blockSignals(False)
        self.pc_volume_label.setText(f"{self.pc_volume.value()} %")
        self.mute_toggle.setDown(self.mute_check.isChecked(), emit=False)
        self.mute_toggle.setEnabled(found)
        self.volume_knob.setValue(self.pc_volume.value())
        self.volume_knob.setEnabled(found)
        if hasattr(self, "af_knob"):
            self._af_knob_follow(self.pc_volume.value())
        return found

    def on_pc_volume(self, value):
        self.pc_volume_label.setText(f"{value} %")
        self.volume_knob.setValue(value)
        self._af_knob_follow(value)
        self._apply_direct_volume()

    @staticmethod
    def _sinks():
        """Sorties réelles du PC : (casque USB ou None, haut-parleurs PC ou None)."""
        out = subprocess.run(["pactl", "list", "short", "sinks"],
                             capture_output=True, text=True).stdout
        names = [line.split("\t")[1] for line in out.splitlines() if "\t" in line]
        headset = next((n for n in names if n.startswith("alsa_output.usb")
                        and "Burr-Brown" not in n), None)
        speakers = next((n for n in names if n.startswith("alsa_output.pci")), None)
        return headset, speakers

    def _output_text(self):
        current = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                 text=True).stdout.strip()
        on_pc = current.startswith("alsa_output.pci")
        self.output_button.setText("HP PC" if on_pc else "CASQUE")
        self.output_toggle.setDown(not on_pc, emit=False)
        color = ("#3a1010", "#5a2020") if on_pc else ("#ff2a2a", "#ff9a9a")
        self.headset_led.setStyleSheet(
            "border-radius: 7px; border: 1px solid #222;"
            f"background: qradialgradient(cx:0.35, cy:0.35, radius:0.8, "
            f"fx:0.35, fy:0.35, stop:0 {color[1]}, stop:1 {color[0]});")

    def _precision_toggled(self, on):
        """PRÉCISION ON : double-clic pour accrocher les boutons ; OFF : direct."""
        KNOB_MODE["precision"] = on
        for knob in (self.preamp_knob, self.af_knob, self.level_knob, self.alc_knob,
                     self.volume_knob, self.clean_knob, self.af_radio_knob,
                     self.power_knob):
            knob._release()
        self.knob._release()
        self.statusBar().showMessage(
            "PRÉCISION ON : double-clic pour accrocher un bouton, double-clic pour le lâcher"
            if on else "PRÉCISION OFF : cliquer et glisser pour tourner les boutons", 5000)

    # --- message CW préparé -----------------------------------------------
    def _message_text(self):
        try:
            with open(MESSAGE_FILE) as f:
                return f.read().strip() or DEFAULT_MESSAGE
        except OSError:
            return DEFAULT_MESSAGE

    def _edit_message(self, *_):
        """Clic droit sur MESSAGE : écrire le message (gardé pour les fois suivantes)."""
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Message CW", "Message émis en CW (lettres, chiffres, / ? . , =) :",
            QtWidgets.QLineEdit.Normal, self._message_text())
        if ok and text.strip():
            os.makedirs(os.path.dirname(MESSAGE_FILE), exist_ok=True)
            with open(MESSAGE_FILE, "w") as f:
                f.write(text.strip().upper() + "\n")
            self.statusBar().showMessage(f"Message enregistré : {text.strip().upper()}", 5000)

    def _morse_seconds(self, text):
        """Durée d'émission du texte (unités morse à la vitesse choisie)."""
        codes = {v: k for k, v in MORSE.items()}
        units = 0
        for ch in text:
            if ch == " ":
                units += 4                          # 7 entre mots (3 déjà comptés)
                continue
            code = codes.get(ch, "")
            units += sum(1 if c == "." else 3 for c in code) + len(code) - 1 + 3
        return units * 1.2 / self.paddle_wpm.value()

    def _cw_split(self, text):
        """Texte → paquets de 30 caractères au plus (limite de la commande CI-V)."""
        chunks, cur = [], ""
        for w in " ".join(text.upper().split()).split(" "):
            if len(cur) + len(w) + 1 > 30 and cur:
                chunks.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            chunks.append(cur)
        return chunks

    def _cw_entry_send(self):
        text = self.cw_entry.text().strip()
        if not text:
            return
        if not self.civ or self.mode_combo.currentText() not in ("CW", "CW-R"):
            self.statusBar().showMessage("Saisie CW : seulement en mode CW (rien d'émis)", 5000)
            return
        self.cw_entry.clear()
        busy = bool(self.message_chunks) or self.message_timer.isActive()
        self.message_chunks += self._cw_split(text)     # à la suite de ce qui part déjà
        self.statusBar().showMessage(f"CW émis : {text.upper()}")
        if not busy:
            self.civ.set_key_speed(self.paddle_wpm.value())
            self._message_next()

    def _cw_entry_stop(self):
        if self.message_chunks or self.message_timer.isActive():
            self.message_toggle.setDown(False)          # même arrêt que MESSAGE sur OFF
        self.message_timer.stop()
        self.message_chunks = []
        if self.civ:
            self.civ.stop_cw()
        if self.cw_station is not None:
            self.cw_station.stop_play()
        self.statusBar().showMessage("Émission CW arrêtée", 4000)

    def _message_toggled(self, on):
        if not on:
            if self.message_chunks or self.message_timer.isActive():
                self.message_timer.stop()
                self.message_chunks = []
                if self.civ:
                    self.civ.stop_cw()
                self.statusBar().showMessage("Message CW arrêté", 4000)
            return
        if not self.civ or self.mode_combo.currentText() not in ("CW", "CW-R"):
            self.statusBar().showMessage("MESSAGE : seulement en CW (rien d'émis)", 5000)
            self.message_toggle.setDown(False, emit=False)
            return
        text = " ".join(self._message_text().upper().split())
        self.message_chunks = self._cw_split(text)
        self.civ.set_key_speed(self.paddle_wpm.value())
        self.statusBar().showMessage(f"Message CW : {text}")
        self._message_next()

    def _message_next(self):
        if not self.message_chunks:             # message fini : levier sur OFF
            self.message_toggle.setDown(False, emit=False)
            self.statusBar().showMessage("Message CW émis", 4000)
            return
        chunk = self.message_chunks.pop(0)
        self.civ.send_cw(chunk + (" " if self.message_chunks else ""))
        if self.cw_station is not None and self.cw_station.isVisible():
            self.cw_station.play(chunk + " ", self.paddle_wpm.value())
        self.message_timer.start(int(self._morse_seconds(chunk + " ") * 1000) + 300)

    def _output_toggled(self, casque):
        """Interrupteur ÉCOUTE : ne bascule que si la sortie n'y est pas déjà."""
        current = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                 text=True).stdout.strip()
        if casque == current.startswith("alsa_output.pci"):
            self.on_output_switch()
        else:
            self._output_text()

    def on_output_switch(self):
        current = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                 text=True).stdout.strip()
        headset, speakers = self._sinks()
        target = headset if current.startswith("alsa_output.pci") else speakers
        if not target:
            self.statusBar().showMessage("Pas d'autre sortie son (casque débranché ?)", 5000)
            return
        subprocess.run(["pactl", "set-default-sink", target], capture_output=True)
        # les sons déjà en cours suivent (écoute radio, sifflement, Spotify…)
        out = subprocess.run(["pactl", "list", "short", "sink-inputs"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            fields = line.split("\t")
            if len(fields) > 1 and fields[1] != "" and self._sink_name(fields[1]) == current:
                subprocess.run(["pactl", "move-sink-input", fields[0], target],
                               capture_output=True)
        self._output_text()

    @staticmethod
    def _sink_name(index):
        out = subprocess.run(["pactl", "list", "short", "sinks"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            fields = line.split("\t")
            if fields[0] == index:
                return fields[1]
        return None

    def _mute_guard(self):
        """Le son de la réception suit toujours l'interrupteur MUET (et reste coupé
        en émission ou pendant l'attente d'un VOX n)."""
        want = (self.mute_check.isChecked() or self.tx_active
                or getattr(self, "vox_rx_muted", False))
        stream = find_loopback_stream()
        if stream is None:
            return
        if self.loopback is None or self.loopback[0] != stream[0]:
            self.loopback = stream                  # flux recréé : on le reprend
        if bool(stream[2]) != want:
            subprocess.run(["pactl", "set-sink-input-mute", str(stream[0]),
                            "1" if want else "0"], capture_output=True)
            if want:
                self.statusBar().showMessage("MUET rétabli (le son de la réception "
                                             "était revenu tout seul)", 4000)

    def on_mute(self, muted):
        self._pactl_stream("set-sink-input-mute", "1" if muted else "0")

    def on_af_gain(self, level):
        self.af_slider.setEnabled(True)
        if not getattr(self, "_af_radio_cut", False):
            # écoute sur le PC : haut-parleur de la radio coupé au lancement
            # (le son USB vers le PC ne dépend pas de ce volume)
            self._af_radio_cut = True
            if level > 0:
                # ordre envoyé directement : le curseur part déjà de 0 et
                # setValue(0) seul n'aurait rien envoyé à la radio
                self.af_slider.blockSignals(True)
                self.af_slider.setValue(0)
                self.af_slider.blockSignals(False)
                self.on_af_slider(0)
                return
        if not self.af_slider.isSliderDown():
            self.af_slider.blockSignals(True)
            self.af_slider.setValue(level)
            self.af_slider.blockSignals(False)
        self.af_label.setText(f"{round(self.af_slider.value() * 100 / 255)} %")
        self.af_radio_knob.setEnabled(True)
        if not self.af_radio_knob._dragging:
            self.af_radio_knob.setValue(round(self.af_slider.value() * 100 / 255))

    def _af_knob_follow(self, percent):
        """Le bouton rond suit le Volume PC (0–150 %) sans renvoyer d'ordre."""
        self.af_knob.blockSignals(True)
        self.af_knob.setValue(percent / 15)
        self.af_knob.blockSignals(False)
        self.af_display.setText(f"{percent}")
        self.af_display.update()

    def on_eq_button(self):
        if self.eq_window is None:
            self.eq_window = EqWindow(self.eq_engine, self)
            self.eq_window.opened.connect(self._eq_opened)
            self.eq_window.closed.connect(self._eq_closed)
        self.eq_window.show()
        self.eq_window.raise_()
        self.eq_window.activateWindow()

    def _eq_opened(self):
        """Réglage de l'égaliseur : le trafic de la radio est coupé sur le PC."""
        if getattr(self, "eq_mute_before", None) is None:
            self.eq_mute_before = self.mute_check.isChecked()
        self.mute_check.setChecked(True)
        self.statusBar().showMessage("Égaliseur : réception coupée pendant les réglages", 4000)

    def _eq_closed(self):
        """Égaliseur fermé : la réception revient tout de suite (comme avant)."""
        before = getattr(self, "eq_mute_before", None)
        self.eq_mute_before = None
        if before is not None:
            self.mute_check.setChecked(before)

    def on_mic_knob(self, value):
        source = getattr(self, "tx_source", None)
        source = source.currentData() if source is not None else None
        if not source or source == "file":
            source = "@DEFAULT_SOURCE@"
        subprocess.Popen(["pactl", "set-source-volume", source, f"{round(value * 15)}%"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=PACTL_ENV)

    def on_af_knob(self, value):
        self.pc_volume.setValue(round(value * 15))          # même chemin que le curseur

    def on_af_slider(self, level):
        self.af_label.setText(f"{round(level * 100 / 255)} %")
        self.af_radio_knob.setValue(round(level * 100 / 255))
        if self.civ:
            self.civ.set_af_gain(level)

    def on_meter(self, raw):
        self.hunter.feed_meter(raw)
        self.scanner.feed_meter(raw)
        self.s_meter.setValue(raw)
        self.m_smeter.setValue(raw)
        self._rx_meter_feed(raw)
        self.s_raw_avg = 0.8 * self.s_raw_avg + 0.2 * raw     # pour le dosage RNNoise

    def _x_at(self, pos):
        """Abscisse sous la souris (kHz en RF, Hz en audio), ou None."""
        for plot in (self.spec_plot, self.wf_plot):
            if plot.sceneBoundingRect().contains(pos):
                x = plot.vb.mapSceneToView(pos).x()
                if self.view == "audio" and 0 <= x <= self.fmax:
                    return x
                if (self.view == "rf" and self.scope_edges
                        and self.scope_edges[0] <= x * 1000 <= self.scope_edges[1]):
                    return x
        return None

    def on_mouse_moved(self, pos):
        x = self._x_at(pos)
        for line in self.cursor_lines:
            line.setVisible(x is not None)
            if x is not None:
                line.setPos(x)
        if x is None:
            self.cursor_label.setText("")
        elif self.view == "rf":
            self.cursor_label.setText(format_frequency(round(x * 1000)))
        else:
            self.cursor_label.setText(f"{x:6.0f} Hz")

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QtCore.QEvent.Wheel and hasattr(self, "m_wf_plot") \
                and obj is self.m_wf_plot.viewport():
            # waterfall MOBILE : molette = fréquence, au pas choisi
            notches = event.angleDelta().y() / 120
            if notches and self.freq_hz is not None:
                self.on_tuned(round(notches) or (1 if notches > 0 else -1))
            return True
        if kind == QtCore.QEvent.Wheel:
            pos = self.spec_plot.scene().views()[0].mapToScene(event.pos())
            if self._x_at(pos) is not None and self.freq_hz is not None:
                notches = event.angleDelta().y() / 120
                if notches:
                    self.on_tuned(round(notches) or (1 if notches > 0 else -1))
                return True
        elif (kind == QtCore.QEvent.MouseButtonPress
              and event.button() == QtCore.Qt.LeftButton):
            self.dragged = False
            pos = self.spec_plot.scene().views()[0].mapToScene(event.pos())
            if self.view == "rf" and self._x_at(pos) is not None and self.freq_hz:
                low, high = self.spec_plot.vb.viewRange()[0]
                width = self.spec_plot.vb.width()
                if width > 0:
                    self.drag = (event.pos().x(), (high - low) / width, self.freq_hz)
        elif kind == QtCore.QEvent.MouseMove and self.drag:
            x0, khz_per_px, start_hz = self.drag
            dx = event.pos().x() - x0
            if abs(dx) > 3:
                self.dragged = True
            if self.dragged:
                # on tire la bande : vers la gauche, la fréquence monte
                hz = start_hz - dx * khz_per_px * 1000
                step = min(self.step_combo.currentData(), 100)
                self.tune_to(int(round(hz / step) * step))
                self.setCursor(QtCore.Qt.SizeHorCursor)
            return False
        elif kind == QtCore.QEvent.MouseButtonRelease and self.drag:
            self.drag = None
            self.unsetCursor()
        return super().eventFilter(obj, event)

    def on_mouse_clicked(self, event):
        if self.dragged:
            self.dragged = False
            return                      # fin d'un glisser, pas un clic
        x = self._x_at(event.scenePos())
        if x is None:
            return
        decoder = self.decoder_combo.currentData()
        if self.view == "audio":
            if decoder:
                self._set_decoder_pitch(x)
            return
        # vue RF : en PSK31, un clic dans la bande écoutée choisit le signal
        audio = self._audio_offset(x * 1000)
        if decoder in ("psk31", "rtty") and audio is not None:
            self._set_decoder_pitch(audio)
            return
        step = self.step_combo.currentData()
        self.tune_to(round(x * 1000 / step) * step)

    def _audio_offset(self, rf_hz):
        """Fréquence audio d'un signal RF, s'il tombe dans la bande en BLU."""
        if self.freq_hz is None:
            return None
        mode = base_mode(self.mode_combo.currentText())
        audio = {"USB": rf_hz - self.freq_hz, "LSB": self.freq_hz - rf_hz}.get(mode)
        if audio is not None and 100 <= audio <= 3000:
            return audio
        return None

    def _set_decoder_pitch(self, hz):
        decoder = self.audio.decoder
        if decoder is None or decoder.pitch is None:
            return
        if isinstance(decoder, CwDecoder):
            self.decoder_auto.setChecked(False)     # la note ne bouge plus
        decoder.set_pitch(hz)
        self._move_pitch_lines(hz)

    def on_decoder_changed(self):
        name = self.decoder_combo.currentData()
        decoder = self.audio.decoders.get(name)
        if decoder:
            decoder.auto_pitch = self.decoder_auto.isChecked()
        self.audio.decoder = decoder
        self.decoder_text.setVisible(decoder is not None)
        self.decoder_auto.setToolTip({
            "cw": "Cherche la note CW la plus forte entre 300 et 1200 Hz. "
                  "Clic sur le spectre audio pour la choisir.",
            "psk31": "Se recale sur le signal à ± 25 Hz du clic, puis le suit. "
                     "Clic sur le spectre audio, ou en RF dans la bande écoutée.",
            "rtty": "Se recale sur la paire de tonalités à ± 60 Hz du clic. "
                    "Cliquer entre les deux traces.",
        }.get(name, ""))
        self.rtty_invert.setVisible(name == "rtty")
        self.decoder_auto.setVisible(name in ("cw", "psk31", "rtty"))
        # FT8 : plusieurs lignes par créneau, il faut de la place
        self.decoder_text.setFixedHeight(104)   # sous le S-mètre, même pour FT8
        if name == "ft8" and self.decoder_text.document().isEmpty():
            self.decoder_text.setPlainText(
                "UTC      dB   DT Freq  Message  (14.074, 7.074… en USB)\n")
        self.decoder_led.setToolTip({
            "cw": "Allumé quand le signal est manipulé",
            "ft8": "Allumé pendant le décodage d'un créneau",
        }.get(name, "Allumé quand le signal est décodable"))
        if decoder is None:
            self.decoder_info.setText("")
            self._set_decoder_led(False, False)
        else:
            self._move_pitch_lines(decoder.pitch)
        self._show_pitch_lines()

    def on_rtty_invert(self, inverted):
        self.audio.decoders["rtty"].inverted = inverted

    def on_decoder_auto(self, auto):
        if self.audio.decoder:
            self.audio.decoder.auto_pitch = auto

    def _show_pitch_lines(self):
        decoder = self.audio.decoder
        visible = decoder is not None and decoder.pitch is not None
        for line in self.pitch_lines:
            line.setVisible(visible)

    def _move_pitch_lines(self, audio_hz):
        """Repère du décodeur : en Hz audio, ou en kHz RF dans la vue RF."""
        if audio_hz is None:            # FT8 : toute la bande, pas de repère
            self._show_pitch_lines()
            return
        x = audio_hz
        if self.view == "rf":
            mode = base_mode(self.mode_combo.currentText())
            sign = {"USB": 1, "LSB": -1}.get(mode)
            if self.freq_hz is None or sign is None:
                for line in self.pitch_lines:
                    line.setVisible(False)
                return
            x = (self.freq_hz + sign * audio_hz) / 1000
        decoder = self.audio.decoder
        for line in self.pitch_lines:
            line.setVisible(decoder is not None and decoder.pitch is not None)
            line.setPos(x)

    def _set_decoder_led(self, signal, active):
        color = "#3ddc84" if active else ("#2e5d41" if signal else "#37474f")
        self.decoder_led.setStyleSheet(f"font: 16pt; color: {color};")

    # --- écran CW plein écran -----------------------------------------
    def _cw_station_open(self):
        if self.cw_station is None:
            self.cw_station = CwStation(self.paddle_wpm.value())
            self.cw_station.send.connect(self._cw_station_send)
            self.cw_station.stop_tx.connect(self._cw_entry_stop)
            self.cw_station.leave.connect(lambda: self.on_mode_button("CW"))
            self.cw_station.wpm_changed.connect(self.paddle_wpm.setValue)
            self.cw_station.back.connect(self._cw_station_restore)
        self.civ.set_break_in(True)         # BK-IN d'office : le texte tapé part à l'antenne
        self.cw_station.rx_text.clear()
        self.cw_station.set_info(f"{format_frequency(self.freq_hz or 0)} MHz — BK-IN allumé")
        self.cw_station.open(self.windowHandle().screen() if self.windowHandle() else None)
        self.statusBar().showMessage("Écran CW : BK-IN allumé", 4000)
        # comme l'écran RTTY : les autres fenêtres (dont le Scope) sont réduites
        QtCore.QTimer.singleShot(400, self._cw_station_front)

    def _cw_station_front(self):
        if self.cw_station is None or not self.cw_station.isVisible():
            return
        if not self.cw_hidden:
            self.cw_hidden = self._hide_windows({int(self.cw_station.winId())})
        self.cw_station.raise_()
        self.cw_station.activateWindow()
        self.cw_station.entry.setFocus()

    def _cw_station_restore(self):
        """Écran CW fermé : les fenêtres réduites reviennent."""
        self._restore_windows(self.cw_hidden)
        self.cw_hidden = []

    def _cw_station_close(self):
        self._cw_entry_stop()
        if self.civ:
            self.civ.set_break_in(False)    # BK-IN coupé en quittant la CW
        self.cw_station.hide()
        self._cw_station_restore()
        self.statusBar().showMessage("Écran CW fermé : BK-IN coupé", 4000)

    def _cw_station_send(self, text):
        if not self.civ or self.mode_combo.currentText() not in ("CW", "CW-R"):
            self.cw_station.set_info("La radio n'est pas en CW : rien d'émis")
            return
        self.cw_station.sent(text)
        busy = bool(self.message_chunks) or self.message_timer.isActive()
        self.message_chunks += self._cw_split(text)     # à la suite de ce qui part déjà
        if not busy:
            self.civ.set_key_speed(self.paddle_wpm.value())
            self._message_next()

    def on_decoded(self, text):
        if self.cw_station is not None and self.cw_station.isVisible():
            self.cw_station.feed_rx(text)
        if self.rtty_toggle.down:
            self.rtty_screen.feed_text(text)
        if self.fr_toggle.down:
            self.fr_screen.feed_text(text)
        if self.cw_view_active:
            self.cw_text.moveCursor(QtGui.QTextCursor.End)
            self.cw_text.insertPlainText(text)
            self.cw_text.ensureCursorVisible()
        self.decoder_text.moveCursor(QtGui.QTextCursor.End)
        self.decoder_text.insertPlainText(text)
        self.decoder_text.ensureCursorVisible()

    # --- VOX sur le micro du PC : la parole fait passer la radio en émission ---
    VOX_VOICE_MODES = ("LSB", "USB", "AM", "FM")
    VOX_HANG_S = 2.0           # fin de modulation + 2 s → retour réception ET VOX coupé
    VOX_VOCAL_HANG_S = 1.0     # VOX armé par le mot « VOX » : coupure 1 s après la parole

    def _vox_threshold(self):
        """Seuil en dBFS : sensibilité 0 % → -10 dB, 100 % → -60 dB."""
        return -10.0 - self.vox_knob.value / 255 * 50.0

    def _vox_mic(self):
        source = self.tx_source.currentData()
        if source and source != "file":
            return source
        out = subprocess.run(["pactl", "get-default-source"], capture_output=True,
                             text=True, env=PACTL_ENV).stdout.strip()
        return out or None

    def on_vox_toggled(self, on):
        if on:
            mode = self.mode_combo.currentText()
            if mode.endswith("-D") and mode[:-2] in self.VOX_VOICE_MODES:
                self.ft8_set_mode(mode[:-2])        # USB-D → USB : le VOX est pour la phonie
                self.statusBar().showMessage(f"VOX : passage de {mode} en {mode[:-2]}", 5000)
            mic = self._vox_mic()
            if not self.civ or not mic:
                self.statusBar().showMessage("VOX : pas de CAT ou pas de micro", 5000)
                self.vox_button.setChecked(False)
                return
            self.vox_monitor = VoxMonitor(mic)
            self.vox_monitor.level.connect(self.on_vox_level)
            self.vox_monitor.start()
            self.vox_button.setText("VOX ON")
            self.statusBar().showMessage(
                "VOX en marche : la radio ÉMET quand tu parles dans le micro du PC", 8000)
        else:
            self.vox_by_voice = False
            if self.vox_monitor:
                self.vox_monitor.stop()
                self.vox_monitor = None
            if self.vox_tx:
                self.vox_tx = False
                self.stop_tx("VOX arrêté : retour en réception")
            self.vox_button.setText("VOX OFF")
            self.vox_button.setStyleSheet(PUSH_3D)
            self.vox_label.setText(f"{self.vox_knob.value * 100 / 255:.0f} %")

    def on_vox_level(self, db):
        self.mic_db = db
        if not self.vox_button.isChecked():
            return
        now = time.monotonic()
        threshold = self._vox_threshold()
        self.vox_label.setText(f"{db:.0f} dB")
        if db > threshold:
            self.vox_last_voice = now
            if not self.tx_active:
                mode = self.mode_combo.currentText()
                if mode not in self.VOX_VOICE_MODES:
                    self.statusBar().showMessage(f"VOX : pas d'émission en {mode} "
                                                 "(phonie seulement)", 3000)
                    return
                if self.tx_source.currentData() == "file":
                    self.tx_source.setCurrentIndex(0)       # le micro, pas un fichier
                    self.on_tx_source()
                self.vox_tx = True
                self.start_tx()
                if self.tx_active:
                    self.vox_button.setText("VOX ÉMET")
                    self.vox_button.setStyleSheet(POWER_OFF)
                else:
                    self.vox_tx = False
        elif self.vox_tx and self.vox_by_voice and \
                now - self.vox_last_voice > self.VOX_VOCAL_HANG_S:
            self.vox_tx = False
            self.stop_tx()
            self._vox_disarm("VOX coupé : 1 s sans parole. Dis « VOX » pour le réarmer")
        elif self.vox_tx and now - self.vox_last_voice > self.VOX_HANG_S:
            self.vox_tx = False
            self.stop_tx()
            self._vox_disarm("VOX coupé : 2 s sans modulation. Rappuie sur VOX pour le réarmer")

    def on_vox_vocal_toggled(self, on):
        if on:
            mic = self._vox_mic()
            if not mic:
                self.statusBar().showMessage("VOX VOCAL : pas de micro", 5000)
                self.vox_vocal_button.setChecked(False)
                return
            self._mot_vox_need()
            self.statusBar().showMessage(
                "VOX VOCAL en marche : dis « VOX » au micro pour armer le VOX "
                "(chargement de la reconnaissance, quelques secondes)", 8000)
        else:
            self._mot_vox_need()
            self.statusBar().showMessage("VOX VOCAL arrêté", 4000)

    def _vox_rx_quiet(self):
        """Réception coupée pendant l'apprentissage, l'attente de « VOX n » et le
        message : le haut-parleur ne doit pas brouiller le micro. Rétablie après."""
        want = (self.vox_learn is not None or bool(self.vox_msg_armed)
                or self.vox_msg_sending is not None or self.vox_msg_rec is not None)
        if want == self.vox_rx_muted:
            return
        self.vox_rx_muted = want
        if want:
            self._pactl_stream("set-sink-input-mute", "1")
            self._vox_log("réception coupée (micro au calme)")
        elif not self.tx_active:
            self._pactl_stream("set-sink-input-mute",
                               "1" if self.mute_check.isChecked() else "0")
            self._vox_log("réception rétablie")

    def _mot_vox_need(self):
        """Écoute des mots au micro : en marche si VOX VOCAL est allumé ou si un
        message VOX n attend d'être dit (et pas pendant l'enregistrement d'un message)."""
        self._vox_rx_quiet()
        need = (self.vox_vocal_button.isChecked() or bool(self.vox_msg_armed)
                or self.vox_learn is not None) and self.vox_msg_rec is None
        # Whisper seulement pour VOX VOCAL ; VOX n : ta voix comparée aux exemples
        self.mot_vox.transcribe = (self.vox_vocal_button.isChecked()
                                   or bool(self.vox_msg_armed & self.vox_msg_dry_auto)) \
            and self.vox_learn is None
        if need and not self.mot_vox.running:
            mic = self._vox_mic()
            if mic:
                self.mot_vox.start(mic)         # d'abord démarrer : sinon « micro perdu »
                self._mot_vox_tick()
                self.mot_vox_timer.start(100)
        elif not need and self.mot_vox.running:
            self.mot_vox_timer.stop()
            self.mot_vox.stop()

    def _mot_vox_tick(self):
        # pas d'écoute du mot pendant le VOX ou l'émission ; même seuil que le VOX
        self.mot_vox.paused = self.vox_button.isChecked() or self.tx_active \
            or self.dictee.active             # pas de « VOX n » pendant une dictée
        self.mot_vox.threshold = self._vox_threshold()
        if self.vox_msg_armed and (self.vox_msg_dry or self.vox_msg_armed & self.vox_msg_dry_auto) \
                and not self.vox_msg_sending:
            db, thr = self.mot_vox.last_db, self.mot_vox.threshold
            bar = "█" * max(0, min(30, int((db + 70) / 2)))
            self.statusBar().showMessage(
                f"ESSAI — micro {db:4.0f} dB {'▲ AU-DESSUS' if db > thr else '  sous'} "
                f"du seuil {thr:.0f} dB  {bar}   dis « VOX "
                + " / VOX ".join(map(str, sorted(self.vox_msg_armed))) + " »"
                + (f"   | dernier essai : {self.vox_match_detail}"
                   if time.monotonic() - getattr(self, "vox_seg_time", 0) < 8 else ""))
        if not self.mot_vox.running:                        # micro perdu
            if self.vox_vocal_button.isChecked():
                self.vox_vocal_button.setChecked(False)
            if self.vox_msg_armed:
                self.vox_msg_armed.clear()
                self._vox_msg_show()
                self.statusBar().showMessage("VOX n : micro perdu, attente annulée", 8000)

    def on_mot_vox(self):
        if not self.vox_vocal_button.isChecked() or self.vox_button.isChecked() \
                or self.tx_active:
            return
        self.vox_button.setChecked(True)
        if self.vox_button.isChecked():
            self.vox_by_voice = True
            self.statusBar().showMessage("« VOX » entendu : VOX en marche, parle ; "
                                         "coupure 1 s après la fin de ta parole", 8000)

    def on_mot_vox_heard(self, text):
        n = vox_number(text)
        if n is not None and n in (self.vox_msg_armed & self.vox_msg_dry_auto) \
                and not self.tx_active and self.vox_msg_sending is None:
            self.vox_match_detail = f"texte entendu « {text} »"
            self._vox_log(f"entendu « {text} » → VOX {n} reconnu")
            self._vox_msg_send(n)               # essai à blanc : reconnu par le texte
            return
        if self.vox_msg_armed:
            self.vox_match_detail = f"texte entendu « {text} »"
            self._vox_log(f"entendu « {text} » (refusé, attendu VOX "
                          f"{'/'.join(map(str, sorted(self.vox_msg_armed)))})")
        if n is not None or self.vox_msg_armed:
            return      # VOX n : décidé par la voix (on_mot_vox_segment), pas par le texte
        if self.vox_vocal_button.isChecked() and not self.vox_button.isChecked():
            self.statusBar().showMessage(f"VOX VOCAL a entendu : « {text} »", 3000)

    def _vox_disarm(self, message):
        """Le VOX ne reste jamais armé après une émission : remise en marche manuelle."""
        if self.vox_button.isChecked():
            self.vox_button.setChecked(False)
        self.statusBar().showMessage(message, 8000)

    def _emission_sync(self, on):
        """Le bouton EMISSION suit l'état du VOX (coupures automatiques comprises)."""
        if self.emission_button.isChecked() != on:
            self.emission_button.blockSignals(True)
            self.emission_button.setChecked(on)
            self.emission_button.blockSignals(False)
            self.emission_button.update()
        if self.m_emission.isChecked() != on:          # écran MOBILE
            self.m_emission.blockSignals(True)
            self.m_emission.setChecked(on)
            self.m_emission.blockSignals(False)
            self.m_emission.update()

    def on_vox_knob(self, level):
        self.vox_label.setText(f"{level * 100 / 255:.0f} %")

    def on_radio_vox(self, on):
        # le VOX interne de la radio n'est jamais utilisé : s'il est allumé, on l'éteint
        if on and self.civ:
            self.civ.set_vox(False)
            self.statusBar().showMessage("VOX de la radio éteint : seul le bouton VOX "
                                         "du Scope (mise en marche manuelle) est permis", 8000)

    def on_radio_vox_gain(self, level):
        pass

    # --- compresseur de modulation de la radio ---
    def on_comp_toggled(self, on):
        self.comp_button.setText("COMP ON" if on else "COMP OFF")
        if self.civ:
            self.civ.set_comp(on)

    def on_comp_knob(self, level):
        self.comp_label.setText(f"{level * 10 / 255:.1f}".replace(".", ","))
        self.comp_knob_touched = time.monotonic()
        if self.civ:
            self.civ.set_comp_level(level)

    def on_radio_comp(self, on):
        self.comp_button.blockSignals(True)
        self.comp_button.setChecked(on)
        self.comp_button.blockSignals(False)
        self.comp_button.setText("COMP ON" if on else "COMP OFF")

    def on_radio_comp_level(self, level):
        if time.monotonic() - getattr(self, "comp_knob_touched", 0) < 3:
            return                      # on vient de le tourner : la radio n'a pas fini
        self.comp_knob.setValue(level)
        self.comp_label.setText(f"{level * 10 / 255:.1f}".replace(".", ","))
        self.comp_round.blockSignals(True)      # valeur lue dans la radio : pas de renvoi
        self.comp_round.setValue(level * 10 / 255)
        self.comp_round.blockSignals(False)

    def on_cw_pitch(self, hz):
        self.radio_cw_pitch = float(hz)

    def on_decoder_state(self, info, pitch, signal, active):
        if self.rtty_toggle.down:
            self.rtty_screen.set_signal(signal)
        if self.audio.decoder is None:
            return
        self.cw_note = pitch if (signal and self.decoder_combo.currentData() == "cw"
                                 and self.decoder_auto.isChecked()) else None
        self._set_decoder_led(signal, active)
        self.decoder_info.setText(info)
        self._move_pitch_lines(pitch)
        self._cale_cw(pitch, signal)

    def _cale_cw(self, pitch, signal):
        """En CW, le galva CALE montre l'écart entre la note du correspondant
        et la note CW de la radio : au zéro (plein éclat) quand c'est calé."""
        if self.mode_combo.currentText() not in ("CW", "CW-R"):
            return
        if not signal or not pitch:
            # entre deux signes morse : on garde la dernière mesure 2 s
            if time.monotonic() - getattr(self, "cw_cale_t", 0) > 2.0:
                self.ssb_meter.set_state("search", status="CW : pas de note à mesurer")
            return
        self.cw_cale_t = time.monotonic()
        offset = pitch - self.radio_cw_pitch
        if abs(offset) < 10:
            self.ssb_meter.set_state("locked", 0, f"CW calée (écart {offset:+.0f} Hz)")
        else:
            self.ssb_meter.set_state("measure", offset, f"CW : écart {offset:+.0f} Hz")

    def on_record(self, recording):
        if recording:
            os.makedirs(RECORD_DIR, exist_ok=True)
            name = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%S")
            if self.freq_hz is not None:
                name += f"_{format_frequency(self.freq_hz)}_{self.mode_combo.currentText()}"
            self.record_path = os.path.join(RECORD_DIR, name + ".wav")
            try:
                self.audio.start_recording(self.record_path)
            except OSError as e:
                self.statusBar().showMessage(f"Enregistrement impossible : {e}")
                self.record_button.setChecked(False)
                return
            self.record_button.setText("■ Arrêter")
            self.record_button.setStyleSheet("background: #c62828; color: white;")
            self.record_timer.start()
            self.update_record_label()
        else:
            self.audio.stop_recording()
            self.record_timer.stop()
            self.record_button.setText("● Enregistrer")
            self.record_button.setStyleSheet("")
            self.record_label.setText("")
            if self.record_path:
                self.statusBar().showMessage(f"Enregistré : {self.record_path}")

    def update_record_label(self):
        seconds = self.audio.recorded_frames // RATE
        size = self.audio.recorded_frames * 2 / 1e6
        self.record_label.setText(f"{seconds // 60:02d}:{seconds % 60:02d} · {size:.1f} Mo")

    def open_record_folder(self):
        os.makedirs(RECORD_DIR, exist_ok=True)
        subprocess.Popen(["xdg-open", RECORD_DIR])

    def closeEvent(self, event):
        self._remember_band()
        self.mot_vox.stop()
        if self.cw_station is not None and self.cw_station.isVisible():
            self._cw_station_close()
        if self.ft8_toggle.down:
            self.ft8_toggle.setDown(False)
        if self.rtty_toggle.down:
            self.rtty_toggle.setDown(False)
        if self.fr_toggle.down:
            self.fr_toggle.setDown(False)
        self.screen_rec.stop(wait=True)     # vidéo en cours : refermée et assemblée
        self.rec_bf.stop(wait=True)         # son REC BF en cours : fichier fermé
        self.dictee.shutdown()
        self.translator.stop()
        self.loupe.stop()
        self.loupe.close()
        self.demo_finger.stop()             # la flèche de la souris revient
        self.demo_finger.close()
        self.voice_scope.stop()
        self.eq_engine.stop()
        self.function_screen.close()
        self._tx_mic_unload()
        self._rec_mic_unload()
        if self.tx_active:              # fermé en émission : l'écoute ne doit pas rester muette
            self._pactl_stream("set-sink-input-mute",
                               "1" if self.mute_check.isChecked() else "0")
        if self.vox_monitor:
            self.vox_monitor.stop()
            self.vox_monitor = None
        if self.rnnoise_button.isChecked() or self.preamp_knob.value != 5.0:
            # le système son mémorise le volume du flux : on remet le vrai
            # Volume PC (et non la part réduite d'origine) avant de partir
            self._pactl_stream("set-sink-input-volume", f"{self.pc_volume.value()}%")
        self.whistle.stop()
        self.paddle.stop()
        rnnoise_radio.off()
        self.hunter.shutdown()
        self.scanner.stop()
        self.cw_hunter.stop()
        if self.tx_active:
            self.stop_tx()
        if self.sstv_window:
            self.sstv_window.close()
        self.audio.stop()
        if self.civ:
            self.civ.stop()
        super().closeEvent(event)


def dark_palette():
    palette = QtGui.QPalette()
    base, text = QtGui.QColor("#101418"), QtGui.QColor("#e0e0e0")
    palette.setColor(QtGui.QPalette.Window, base)
    palette.setColor(QtGui.QPalette.WindowText, text)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#1a2027"))
    palette.setColor(QtGui.QPalette.Text, text)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#1f262e"))
    palette.setColor(QtGui.QPalette.ButtonText, text)
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#4fc3f7"))
    return palette


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="source PulseAudio/PipeWire du son de la radio")
    parser.add_argument("--port", default=DEFAULT_PORT, help="port série CI-V")
    parser.add_argument("--sink", default=RADIO_SINK,
                        help="sortie PulseAudio/PipeWire vers la radio (émission)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--fmax", type=int, default=3500,
                        help="fréquence audio maximale affichée (Hz)")
    parser.add_argument("--no-cat", action="store_true",
                        help="ne pas ouvrir le port CI-V (s'il est pris par "
                             "un autre logiciel)")
    parser.add_argument("--allumer", action="store_true",
                        help="allume la radio si elle est éteinte au démarrage")
    parser.add_argument("--chercher", action="store_true",
                        help="lance tout de suite la recherche d'un QSO en français")
    parser.add_argument("--remote", metavar="HÔTE",
                        help="radio branchée sur un autre PC du réseau, qui fait "
                             "tourner cat_server.py et partage son son")
    args = parser.parse_args()
    remote_modules = []
    if args.remote:
        try:
            remote_modules = remote_audio(args.remote)
        except RuntimeError as e:
            sys.exit(f"Son du PC distant {args.remote} inaccessible : {e}")
        args.source, args.sink = REMOTE_RX, REMOTE_TX
        args.port = f"socket://{args.remote}:{CAT_TCP_PORT}"

    pg.setConfigOptions(imageAxisOrder="row-major", antialias=True,
                        background="#101418")
    app = QtWidgets.QApplication(sys.argv)
    # un seul IC-7300 Scope à la fois : deux se disputeraient la radio (CAT)
    # et le second démonterait le son du premier (relais orphelins)
    lock = QtCore.QLockFile(os.path.join(tempfile.gettempdir(), "ic7300-scope.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QtWidgets.QMessageBox.information(None, "IC-7300 Scope",
                                          "IC-7300 Scope est déjà ouvert.")
        sys.exit(0)
    app.setApplicationName("IC-7300 Scope")
    app.setDesktopFileName("ic7300-scope")      # lien avec le menu des applications
    app.setWindowIcon(QtGui.QIcon(ICON))
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    window = MainWindow(args)
    # au démarrage : fenêtre agrandie, la barre Ubuntu (lanceurs) et la barre du
    # haut restent accessibles (F11 : plein écran total / fenêtre agrandie)
    window.setGeometry(app.primaryScreen().availableGeometry())
    window.showMaximized()

    def fix_position():
        """Le gestionnaire de fenêtres place parfois Scope décalé hors de l'écran
        malgré « agrandie » : on le remet en place."""
        avail = app.primaryScreen().availableGeometry()
        if window.isFullScreen() or avail.contains(window.frameGeometry().topLeft()) \
                and window.frameGeometry().left() <= avail.left() + 20 \
                and window.frameGeometry().top() <= avail.top() + 20:
            return
        window.showNormal()
        window.setGeometry(avail)
        window.showMaximized()
    QtCore.QTimer.singleShot(1200, fix_position)
    QtCore.QTimer.singleShot(4000, fix_position)

    def toggle_full_screen():
        if window.isFullScreen():
            window.showMaximized()
        else:
            window.showFullScreen()
    QtWidgets.QShortcut(QtGui.QKeySequence("F11"), window, toggle_full_screen)
    QtWidgets.QShortcut(QtGui.QKeySequence("F12"), window,
                        window.console_button.toggle)
    # console visible dès le démarrage, par-dessus le plein écran
    QtCore.QTimer.singleShot(1500, lambda: window.console_button.setChecked(True))
    if args.allumer:
        def power_on():
            # la radio n'a pas répondu depuis le lancement : on l'allume
            if window.civ and not window.radio_on:
                window.civ.set_radio_power(True)
                window.onoff_button.setText("ON / OFF …")
        QtCore.QTimer.singleShot(6000, power_on)
    if args.chercher:
        def start_hunt():
            # attendre que la radio ait donné sa fréquence
            if window.freq_hz and window.civ:
                window.hunt_button.setChecked(True)
            else:
                QtCore.QTimer.singleShot(1000, start_hunt)
        QtCore.QTimer.singleShot(3000, start_hunt)
    stop_watch = threading.Event()
    if args.remote:
        threading.Thread(target=watch_remote_audio, daemon=True,
                         args=(args.remote, window.audio, stop_watch)).start()
    # kill, Ctrl+C ou fin de session : fermer la fenêtre pour remettre la
    # radio comme on l'a trouvée ; le minuteur laisse Python voir le signal
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: window.close())
    wake = QtCore.QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(200)
    code = app.exec_()
    stop_watch.set()
    if args.remote:
        unload_remote_audio(None)   # les modules ont pu être recréés entre-temps
    sys.exit(code)


if __name__ == "__main__":
    main()
