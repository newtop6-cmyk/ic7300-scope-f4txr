"""Écran WATERFALL FRANCE : waterfall plein écran + stations françaises en direct.

Le waterfall vient du scope de la radio (feed_scope). Curseur interactif :
une ligne suit la souris avec la fréquence et la station la plus proche ;
clic sur un signal (ou une station de la liste) = la radio s'y cale
précisément (bord de la BLU, pointe de la CW). Rien d'autre ne bouge le VFO.

SCAN QSO FR : un récepteur KiwiSDR sur Internet (kiwi_scan.py) parcourt le
segment phonie de la bande et fait reconnaître la langue de chaque QSO ;
bande de scan sous le waterfall (vert = français, gris = autre langue).

Stations françaises (F, TM, TK, TO…, DOM-TOM) repérées en temps réel :
  - RBN en direct (telnet.reversebeacon.net:7000 CW/RTTY, :7001 FT8/FT4),
  - DX Summit (toutes les 30 s),
  - indicatifs lus dans le texte décodé par le Scope (feed_text).
Elles s'affichent sur le waterfall à leur fréquence et dans la liste de droite. Boule RETOUR en bas : ferme l'écran.
Essai seul : python3 wf_france.py
"""

import calendar
import json
import math
import os
import re
import socket
import threading
import time
import urllib.request

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from ball_button import BallButton
from kiwi_scan import KiwiScan, PHONE as SCAN_PHONE
import callsigns
from voice_call import VoiceCall

VOICE_MODES = ("LSB", "USB", "AM", "FM")

MY_CALL = "F4TXR"
HISTORY = 400                   # lignes du waterfall
KEEP_S = 15 * 60                # une station reste affichée 15 min après son dernier spot
NEW_S = 20                      # « nouvelle » : clignote pendant 20 s
SNAP_KHZ = 0.6                  # clic à moins de 0,6 kHz d'une station : on se cale sur elle
BLEU, BLANC, ROUGE = "#3d7dff", "#f2f2f2", "#ff4040"
VERT = "#3ddc84"                # QSO français trouvé par le scan
# reconnaissance du mode au calage : fréquences de base FT8 / FT4 (Hz, le signal
# est dans les 3 kHz au-dessus), portions RTTY et CW de chaque bande
DIGI_DIALS = (1_840_000, 3_573_000, 5_357_000, 7_074_000, 10_136_000, 14_074_000,
              18_100_000, 21_074_000, 24_915_000, 28_074_000, 50_313_000,       # FT8
              3_575_000, 7_047_500, 10_140_000, 14_080_000, 18_104_000,
              21_140_000, 24_919_000, 28_180_000, 50_318_000)                   # FT4
RTTY_PARTS = ((3_580_000, 3_600_000), (7_040_000, 7_050_000), (10_140_000, 10_150_000),
              (14_080_000, 14_099_000), (18_095_000, 18_109_000),
              (21_080_000, 21_120_000), (24_915_000, 24_929_000), (28_050_000, 28_150_000))
CW_PARTS = ((1_810_000, 1_838_000), (3_500_000, 3_570_000), (7_000_000, 7_040_000),
            (10_100_000, 10_130_000), (14_000_000, 14_070_000), (18_068_000, 18_095_000),
            (21_000_000, 21_070_000), (24_890_000, 24_915_000), (28_000_000, 28_070_000),
            (50_000_000, 50_100_000))


def phone_side(hz):
    """Bande latérale d'usage : LSB sous 10 MHz (sauf 60 m), USB au-dessus."""
    return "USB" if hz >= 10_000_000 or 5_250_000 <= hz <= 5_450_000 else "LSB"


def digi_dial(hz):
    """Fréquence de base FT8/FT4 si `hz` tombe dans sa fenêtre de 3 kHz."""
    return next((d for d in DIGI_DIALS if d - 200 <= hz <= d + 3200), None)


def mode_by_frequency(hz):
    """Mode probable d'une station d'après sa place dans la bande → (Hz, mode)."""
    dial = digi_dial(hz)
    if dial:
        return dial, "USB-D"
    if any(lo <= hz <= hi for lo, hi in RTTY_PARTS):
        return hz, "RTTY"
    if any(lo <= hz <= hi for lo, hi in CW_PARTS):
        return hz, "CW"
    return hz, phone_side(hz)


TX_ON, TX_OFF = "#ff3030", "#5a1414"    # indicatif de l'émetteur : rouge clignotant
RX_COLOR = "#ffd54a"                    # indicatif de la station qui reçoit : jaune
QSO_PAIR = re.compile(r"\b([A-Z0-9]{1,3}[0-9][A-Z]{1,4})\s+(?:DE|DU|DEL)\s+"
                      r"([A-Z0-9]{1,3}[0-9][A-Z]{1,4})\b")
SCAN_COLOR = "#ff4fd8"          # curseur du scan
DAY_DIR = os.path.expanduser("~/.config/ic7300-scope")
SHOT_DIR = os.path.expanduser("~/Images/Waterfall FR")     # captures d'écran     # scan-AAAAMMJJ.jsonl : le jour

BANDS = [("160m", 1_810_000, 2_000_000), ("80m", 3_500_000, 3_800_000),
         ("60m", 5_351_500, 5_366_500), ("40m", 7_000_000, 7_200_000),
         ("30m", 10_100_000, 10_150_000), ("20m", 14_000_000, 14_350_000),
         ("17m", 18_068_000, 18_168_000), ("15m", 21_000_000, 21_450_000),
         ("12m", 24_890_000, 24_990_000), ("10m", 28_000_000, 29_700_000),
         ("6m", 50_000_000, 52_000_000), ("4m", 70_000_000, 70_500_000)]

FR_CALL = re.compile(r"^(?:F[A-Z]?\d|T[HKMOPQVWX]\d)[A-Z0-9]*[A-Z]$")
FR_COUNTRIES = {
    "France", "Corsica", "Guadeloupe", "Martinique", "French Guiana", "Reunion Island",
    "Mayotte", "St. Pierre & Miquelon", "New Caledonia", "French Polynesia",
    "Wallis & Futuna Islands", "Kerguelen Islands", "Crozet Island",
    "Amsterdam & St. Paul Is.", "Austral Islands", "Marquesas Islands", "Saint Martin",
    "Saint Barthelemy", "Clipperton Island", "Glorioso Islands", "Juan de Nova, Europa",
    "Tromelin Island", "Chesterfield Islands"}
TEXT_CALL = re.compile(r"\b([A-Z0-9]{1,3}[0-9][A-Z]{1,4}(?:/[A-Z0-9]{1,4})?)\b")
RBN_LINE = re.compile(r"DX de (\S+?):\s+(\d+\.\d+)\s+(\S+)\s+(\S+)\s+(-?\d+) dB"
                      r"(?:\s+(\d+) (?:WPM|BPS))?\s+(.*?)\s*(\d{4})Z")
SPANS = [(0, "BANDE"), (5000, "±5"), (10_000, "±10"), (25_000, "±25"), (50_000, "±50"),
         (100_000, "±100"), (250_000, "±250")]


def is_french(call, country=None):
    if country in FR_COUNTRIES:
        return True
    return any(len(part) >= 3 and FR_CALL.match(part) for part in call.upper().split("/"))


def band_of(hz):
    for name, low, high in BANDS:
        if low <= hz <= high:
            return name, low, high
    return None


def fmt_khz(khz):
    return f"{khz:,.1f}".replace(",", " ").replace(".", ",")


class FrenchSpots(QtCore.QObject):
    """Sources de spots en tâche de fond : `spot` = stations françaises,
    `any_spot` = toutes les stations (pour reconnaître celle qu'on écoute)."""
    spot = QtCore.pyqtSignal(dict)
    any_spot = QtCore.pyqtSignal(dict)
    status = QtCore.pyqtSignal(str, bool)     # (source, liaison bonne)

    def __init__(self):
        super().__init__()
        self.running = False
        self.socks = []

    def start(self):
        if self.running:
            return
        self.running = True
        for port, name in ((7000, "RBN CW"), (7001, "RBN FT8")):
            threading.Thread(target=self._rbn, args=(port, name), daemon=True).start()
        threading.Thread(target=self._dxsummit, daemon=True).start()

    def stop(self):
        self.running = False
        for s in list(self.socks):
            try:
                s.close()
            except OSError:
                pass
        self.socks = []

    def _rbn(self, port, name):
        while self.running:
            sock = None
            try:
                sock = socket.create_connection(("telnet.reversebeacon.net", port), timeout=20)
                self.socks.append(sock)
                sock.settimeout(90)
                sock.sendall((MY_CALL + "\r\n").encode())
                self.status.emit(name, True)
                buf = b""
                while self.running:
                    data = sock.recv(8192)
                    if not data:
                        break
                    buf += data
                    *lines, buf = buf.split(b"\n")
                    for raw in lines:
                        m = RBN_LINE.search(raw.decode("latin-1"))
                        if not m:
                            continue
                        s = {"call": m.group(3).upper(), "hz": int(float(m.group(2)) * 1000),
                             "mode": m.group(4), "snr": int(m.group(5)), "src": "RBN",
                             "t": time.time(), "info": m.group(7).strip(),
                             "by": m.group(1).split("-")[0]}
                        self.any_spot.emit(s)
                        if is_french(s["call"]):
                            self.spot.emit(s)
            except OSError:
                pass
            finally:
                if sock is not None:
                    if sock in self.socks:
                        self.socks.remove(sock)
                    try:
                        sock.close()
                    except OSError:
                        pass
            if self.running:
                self.status.emit(name, False)
                for _ in range(20):             # nouvel essai dans 10 s
                    if not self.running:
                        return
                    time.sleep(0.5)

    def _dxsummit(self):
        seen = set()
        while self.running:
            try:
                req = urllib.request.Request(
                    "http://www.dxsummit.fi/api/v1/spots?limit=500",
                    headers={"User-Agent": f"Mozilla/5.0 (X11; Linux x86_64) {MY_CALL}-scope",
                             "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    spots = json.load(r)
                self.status.emit("DX Summit", True)
                for s in reversed(spots):           # du plus ancien au plus récent
                    if s.get("id") in seen:
                        continue
                    seen.add(s.get("id"))
                    try:
                        t = calendar.timegm(time.strptime(s["time"][:19], "%Y-%m-%dT%H:%M:%S"))
                    except (KeyError, ValueError):
                        t = time.time()
                    if time.time() - t > KEEP_S:
                        continue
                    spot = {"call": s["dx_call"].upper(), "hz": int(float(s["frequency"]) * 1000),
                            "mode": "", "snr": None, "src": "DXS", "t": t,
                            "info": s.get("info") or "", "by": s.get("de_call", "")}
                    self.any_spot.emit(spot)
                    if is_french(s.get("dx_call", ""), s.get("dx_country")):
                        self.spot.emit(spot)
                if len(seen) > 5000:
                    seen = set(list(seen)[-2000:])
            except (OSError, ValueError, KeyError):
                self.status.emit("DX Summit", False)
            for _ in range(60):                     # toutes les 30 s
                if not self.running:
                    return
                time.sleep(0.5)


class WaterfallFrance(QtWidgets.QWidget):
    span = QtCore.pyqtSignal(int)           # largeur du scope demandée (Hz)
    back = QtCore.pyqtSignal()              # RETOUR
    tune = QtCore.pyqtSignal(int, str)      # clic : se caler là (Hz, mode conseillé ou "")
    found = QtCore.pyqtSignal(dict)         # nouvelle station française sur la bande
    fine = QtCore.pyqtSignal(int)           # réglage fin (glisser, molette) : Hz
    fine_done = QtCore.pyqtSignal()         # fin du réglage fin : calage sur la voix

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Waterfall — stations françaises")
        self.setObjectName("wfFrance")
        self.setStyleSheet("color: #e8e8e8; QToolTip { background: #10161e; }")
        self.pings = []                     # ondes de sonar (heure, français ?)
        self.stations = {}                  # indicatif → spot fusionné
        self.freq_hz = None
        self.mode = ""
        self.edges = None                   # (bas, haut) du scope en Hz
        self.wf = np.full((HISTORY, 2), -160, np.float32)
        self.avg = None
        self.low = -150.0
        self.range = 50.0
        self.mouse_khz = None
        self.selected = None                # indicatif choisi d'un clic (surligné)
        self.marks = []                     # objets graphiques des stations
        self.mark_labels = []               # étiquettes du waterfall (clignotement)
        self.list_labels = []               # lignes de la liste (clignotement)
        self.blink_on = True
        self.src_state = {}
        self.text_tail = ""
        self.known = set()                  # stations déjà signalées (ouverture automatique)
        self.scan_results = []              # résultats du scan (segment en cours)
        self.day = self._load_day()         # tous les résultats du jour (fichier)
        self.scan_seg = None
        self.spots = FrenchSpots()
        self.spots.spot.connect(self.add_spot)
        self.spots.any_spot.connect(self._any_spot)
        self.spots.status.connect(self._source_status)
        # station écoutée (tous pays, tous modes) : spots, texte décodé, voix
        self.band_spots = {}                # indicatif → spot (bande du VFO, tous pays)
        self.heard = None                   # {call, src, rx, t, hz}
        self.voice = VoiceCall()
        self.voice.heard.connect(self._voice_heard)
        self.audio_source = None
        self.scan = KiwiScan()
        self._build()
        self.scan.status.connect(self.scan_label.setText)
        self.scan.testing.connect(self._scan_testing)
        self.scan.result.connect(self._scan_result)
        self.scan.segment.connect(self._scan_segment)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._refresh)
        # fond radar animé (balai, traînée, cercles), comme le fond FT8
        self.radar_timer = QtCore.QTimer(self)
        self.radar_timer.timeout.connect(self.update)
        # émetteurs en rouge clignotant (2 fois par seconde)
        self.blink_timer = QtCore.QTimer(self)
        self.blink_timer.timeout.connect(self._blink)
        # réglage fin (glisser / molette) : envoi limité, puis calage sur la voix
        self._fine_drag = None
        self._fine_target = self._fine_sent = None
        self._fine_timer = QtCore.QTimer(self)
        self._fine_timer.timeout.connect(self._fine_send)
        self._fine_end = QtCore.QTimer(self)
        self._fine_end.setSingleShot(True)
        self._fine_end.timeout.connect(lambda: self.fine_done.emit())

    # --- construction --------------------------------------------------------
    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 6)
        root.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        flag = QtWidgets.QLabel()
        flag.setFixedSize(54, 36)
        flag.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                           f"stop:0 {BLEU}, stop:0.333 {BLEU}, stop:0.334 {BLANC}, "
                           f"stop:0.666 {BLANC}, stop:0.667 {ROUGE}, stop:1 {ROUGE}); "
                           "border: 1px solid #888;")
        top.addWidget(flag)
        title = QtWidgets.QLabel("WATERFALL · STATIONS FRANÇAISES")
        title.setStyleSheet("font: bold 20pt sans-serif; color: #ffffff; padding-left: 8px;")
        top.addWidget(title)
        top.addStretch()
        self.freq_label = QtWidgets.QLabel("—")
        self.freq_label.setStyleSheet("font: bold 26pt monospace; color: #ffd54a;")
        top.addWidget(self.freq_label)
        top.addSpacing(12)
        # état du calage sur la voix (BLU) : vert quand c'est calé
        self.calage_label = QtWidgets.QLabel("")
        self.calage_label.setFixedWidth(330)
        self.calage_label.setStyleSheet("font: bold 12pt sans-serif; color: #ffb74d;")
        top.addWidget(self.calage_label)
        top.addSpacing(12)
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setStyleSheet("font: bold 15pt sans-serif; color: #9fd0ff;")
        top.addWidget(self.count_label)
        root.addLayout(top)

        middle = QtWidgets.QHBoxLayout()
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground(None)           # transparent : le radar se voit derrière
        self.graphics.setStyleSheet("background: transparent; border: none;")
        self.graphics.viewport().setAutoFillBackground(False)
        self.spec = self.graphics.addPlot(row=0, col=0)
        self.spec.setYRange(-130, 0, padding=0)
        self.spec.setMouseEnabled(x=False, y=False)
        self.spec.hideButtons()
        self.spec.hideAxis("left")
        self.spec.showGrid(x=True, y=False, alpha=0.2)
        self.spec_curve = self.spec.plot(pen=pg.mkPen("#4fc3f7", width=1), fillLevel=-1000,
                                         brush=(79, 195, 247, 50))
        self.wfp = self.graphics.addPlot(row=1, col=0)
        self.wfp.setXLink(self.spec)
        self.wfp.setMouseEnabled(x=False, y=False)
        self.wfp.hideButtons()
        self.wfp.hideAxis("left")
        self.wfp.invertY(True)
        self.wfp.getAxis("bottom").setTextPen("#cfcfcf")
        self.wfp.setLabel("bottom", "kHz")
        self.img = pg.ImageItem()
        self.img.setLookupTable(pg.colormap.get("inferno").getLookupTable(nPts=256))
        self.wfp.addItem(self.img)
        # bande de scan : tout le segment phonie, vu par le récepteur Internet
        self.seg = self.graphics.addPlot(row=2, col=0)
        self.seg.setMouseEnabled(x=False, y=False)
        self.seg.hideButtons()
        self.seg.hideAxis("left")
        self.seg.setYRange(0, 1, padding=0)
        self.seg.getAxis("bottom").setTextPen("#cfcfcf")
        self.seg.setTitle("<span style='color:#ff9ff0'>SCAN QSO FR — segment phonie "
                          "(récepteur Internet)</span>", size="10pt")
        self.seg_points = pg.ScatterPlotItem(size=16, pxMode=True)
        self.seg.addItem(self.seg_points)
        self.seg_labels = []
        self.seg_cursor = pg.InfiniteLine(angle=90, pen=pg.mkPen(SCAN_COLOR, width=3))
        self.seg_cursor.setVisible(False)
        self.seg.addItem(self.seg_cursor, ignoreBounds=True)
        self.seg_tuned = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffd54a", width=2))
        self.seg.addItem(self.seg_tuned, ignoreBounds=True)
        self.graphics.ci.layout.setRowStretchFactor(0, 1)
        self.graphics.ci.layout.setRowStretchFactor(1, 5)
        self.graphics.ci.layout.setRowMaximumHeight(2, 95)
        # 2e échelle : stations scannées depuis minuit (fichier du jour), interactive
        self.dayp = self.graphics.addPlot(row=3, col=0)
        self.dayp.setXLink(self.seg)
        self.dayp.setMouseEnabled(x=False, y=False)
        self.dayp.hideButtons()
        self.dayp.hideAxis("left")
        self.dayp.setYRange(0, 1, padding=0)
        self.dayp.getAxis("bottom").setTextPen("#cfcfcf")
        self.dayp.setTitle("<span style='color:#9fe8b8'>STATIONS SCANNÉES AUJOURD'HUI "
                           "— survol : détail · clic : se caler</span>", size="10pt")
        self.day_points = pg.ScatterPlotItem(pxMode=True, hoverable=True)
        self.dayp.addItem(self.day_points)
        self.day_labels = []
        self.day_tuned = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffd54a", width=2))
        self.dayp.addItem(self.day_tuned, ignoreBounds=True)
        self.graphics.ci.layout.setRowMaximumHeight(3, 95)
        # fréquence de la radio (jaune) et curseur de la souris (blanc)
        self.tuned = [pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffd54a", width=2))
                      for _ in range(2)]
        self.cursor = [pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffffffc0", width=1,
                                                              style=QtCore.Qt.DashLine))
                       for _ in range(2)]
        for plot, a, b in ((self.spec, *self.tuned[:1], self.cursor[0]),
                           (self.wfp, self.tuned[1], self.cursor[1])):
            plot.addItem(a, ignoreBounds=True)
            plot.addItem(b, ignoreBounds=True)
            b.setVisible(False)
        # bande du signal sous le curseur aimanté (vert pâle)
        self._snap_band = None
        self.snap_bands = []
        for plot in (self.spec, self.wfp):
            band = pg.LinearRegionItem(movable=False, brush=(61, 220, 132, 55),
                                       pen=pg.mkPen(VERT))
            band.setZValue(30)
            band.setVisible(False)
            plot.addItem(band, ignoreBounds=True)
            self.snap_bands.append(band)
        self.scan_lines = [pg.InfiniteLine(angle=90, pen=pg.mkPen(
            SCAN_COLOR, width=2, style=QtCore.Qt.DashLine)) for _ in range(2)]
        for plot, line in zip((self.spec, self.wfp), self.scan_lines):
            line.setVisible(False)
            plot.addItem(line, ignoreBounds=True)
        self.cursor_text = pg.TextItem("", color="#ffffff", anchor=(0, 0),
                                       fill=pg.mkBrush(0, 0, 0, 190))
        self.cursor_text.setZValue(50)
        self.cursor_text.setVisible(False)
        self.wfp.addItem(self.cursor_text, ignoreBounds=True)
        self.graphics.scene().sigMouseMoved.connect(self._mouse_moved)
        self.graphics.scene().sigMouseClicked.connect(self._mouse_clicked)
        self.graphics.viewport().installEventFilter(self)
        self.graphics.setCursor(QtCore.Qt.CrossCursor)
        middle.addWidget(self.graphics, stretch=1)

        side = QtWidgets.QVBoxLayout()
        # STATION ÉCOUTÉE : indicatif (rouge clignotant) et pays de la station calée
        self.heard_label = QtWidgets.QLabel()
        self.heard_label.setFixedWidth(560)
        self.heard_label.setMinimumHeight(92)
        self.heard_label.setStyleSheet(
            "QLabel { background: rgba(40, 6, 6, 170); border: 2px solid #803030; "
            "border-radius: 10px; padding: 6px 10px; }")
        self.heard_label.setToolTip("Indicatif de la station sur laquelle la radio est calée : "
                                    "spots RBN / DX Summit (tous pays), texte décodé (CW, RTTY, "
                                    "PSK) ou indicatif épelé à la voix (Whisper)")
        side.addWidget(self.heard_label)
        head = QtWidgets.QLabel("Stations françaises sur la bande")
        head.setStyleSheet("font: bold 13pt sans-serif; color: #ffffff;")
        side.addWidget(head)
        self.listw = QtWidgets.QListWidget()
        self.listw.setFixedWidth(560)
        self.listw.setFocusPolicy(QtCore.Qt.NoFocus)
        self.listw.setStyleSheet(
            "QListWidget { font: bold 13pt monospace; background: rgba(6, 12, 28, 165); "
            "border: 1px solid #2a3340; } QListWidget::item { padding: 3px; } "
            "QListWidget::item:hover { background: #1c2a3c; }")
        self.listw.setToolTip("Clic sur une station : la radio se cale dessus")
        self.listw.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.listw.itemClicked.connect(self._list_clicked)
        side.addWidget(self.listw, stretch=1)
        self.src_label = QtWidgets.QLabel("")
        self.src_label.setStyleSheet("font: 10pt sans-serif; color: #a0a0a0;")
        self.src_label.setWordWrap(True)
        side.addWidget(self.src_label)
        legend = QtWidgets.QLabel(
            f"<span style='color:{BLEU}'>■</span> RBN (skimmers)  "
            f"<span style='color:{BLANC}'>■</span> DX Summit  "
            f"<span style='color:{ROUGE}'>■</span> décodé ici  "
            f"<span style='color:{VERT}'>■</span> QSO FR (scan)<br>"
            f"<b><span style='color:{TX_ON}'>ÉMETTEUR</span></b> (clignote) ← "
            f"<b><span style='color:{RX_COLOR}'>station qui reçoit</span></b>")
        legend.setStyleSheet("font: 10pt sans-serif;")
        side.addWidget(legend)
        middle.addLayout(side)
        root.addLayout(middle, stretch=1)

        bottom = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        scan_row = QtWidgets.QHBoxLayout()
        self.scan_button = QtWidgets.QPushButton("SCAN QSO FR")
        self.scan_button.setCheckable(True)
        self.scan_button.setChecked(True)
        self.scan_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.scan_button.setToolTip("Marche/arrêt du scan par le récepteur Internet "
                                    "(votre radio ne bouge pas ; 3 h par jour au plus)")
        self.scan_button.setStyleSheet(
            "QPushButton { font: bold 12pt sans-serif; color: #ddd; background: #222a33; "
            "border: 2px solid #556; border-radius: 8px; padding: 6px 14px; } "
            f"QPushButton:checked {{ background: {SCAN_COLOR}; color: #000; }}")
        self.scan_button.toggled.connect(self._scan_toggled)
        scan_row.addWidget(self.scan_button)
        self.scan_label = QtWidgets.QLabel("")
        self.scan_label.setStyleSheet("font: 11pt sans-serif; color: #ff9ff0;")
        scan_row.addWidget(self.scan_label)
        scan_row.addStretch()
        left.addLayout(scan_row)
        self.tune_label = QtWidgets.QLabel(
            "Clic sur un signal : la radio s'y cale (BLU : bord du signal, CW : pointe)")
        self.tune_label.setStyleSheet("font: 11pt sans-serif; color: #a0a0a0;")
        for label in (self.tune_label, self.scan_label):      # un long texte n'élargit pas l'écran
            label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        left.addWidget(self.tune_label)
        bottom.addLayout(left)
        bottom.addStretch()
        self.back_button = BallButton("RETOUR", diameter=84)
        self.back_button.setToolTip("Réduit cet écran (il se rouvre tout seul à la "
                                    "prochaine station française trouvée)")
        self.back_button.clicked.connect(self.back.emit)
        bottom.addWidget(self.back_button)
        bottom.addSpacing(6)
        self.shot_button = BallButton("CAPTURE", diameter=84)
        self.shot_button.setToolTip(f"Capture de cet écran (image PNG) dans {SHOT_DIR}")
        self.shot_button.clicked.connect(self.capture)
        bottom.addWidget(self.shot_button)
        bottom.addStretch()
        self.span_buttons = QtWidgets.QButtonGroup(self)
        lab = QtWidgets.QLabel("Affichage")
        lab.setStyleSheet("font: 11pt sans-serif; color: #a0a0a0;")
        bottom.addWidget(lab)
        for hz, text in SPANS:
            b = QtWidgets.QPushButton(text)
            b.setCheckable(True)
            b.setFocusPolicy(QtCore.Qt.NoFocus)
            b.setStyleSheet("QPushButton { font: bold 12pt sans-serif; color: #ddd; "
                            "background: #222a33; border: 1px solid #556; border-radius: 6px; "
                            "padding: 6px 10px; } QPushButton:checked { background: #ffd54a; "
                            "color: #000; }")
            b.clicked.connect(lambda _, h=hz: self.span.emit(h))
            self.span_buttons.addButton(b, hz)
            bottom.addWidget(b)
        root.addLayout(bottom)

    # --- marche / arrêt ------------------------------------------------------
    def start(self):
        self.spots.start()
        self.timer.start(1000)
        self._scan_toggled(self.scan_button.isChecked())
        self._refresh()

    def stop(self):
        self.timer.stop()
        self.spots.stop()
        self.scan.stop()
        self.voice.stop()
        self.hide()

    # --- scan par le récepteur Internet --------------------------------------
    def _scan_band(self):
        band = band_of(self.freq_hz) if self.freq_hz else None
        return band[0] if band else None

    def _scan_toggled(self, on):
        if not self.timer.isActive():
            return                              # écran arrêté : le scan partira avec start()
        if on:
            band = self._scan_band()
            if band in SCAN_PHONE:
                self.scan.start(band)
            else:
                self.scan_label.setText(f"Scan : pas de segment phonie sur "
                                        f"{band or 'cette fréquence'}")
        else:
            self.scan.stop()

    def _scan_segment(self, lo, hi):
        if self.scan_seg != (lo, hi):
            self.scan_seg = (lo, hi)
            self.scan_results = [r for r in self.scan_results if lo <= r["hz"] <= hi]
            self.seg.setXRange(lo / 1000, hi / 1000, padding=0.01)
            self._draw_scan()
            self._draw_day()

    def _scan_testing(self, hz):
        for line in self.scan_lines:
            line.setVisible(bool(hz))
            if hz:
                line.setPos(hz / 1000)
        self.seg_cursor.setVisible(bool(hz))
        if hz:
            self.seg_cursor.setPos(hz / 1000)
            self.scan_label.setText(f"Scan : écoute de {fmt_khz(hz / 1000)} kHz…")

    # --- stations scannées du jour (fichier, survit aux redémarrages) --------
    @staticmethod
    def _day_file():
        return os.path.join(DAY_DIR, time.strftime("scan-%Y%m%d.jsonl"))

    def _load_day(self):
        out = []
        try:
            with open(self._day_file()) as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        except OSError:
            pass
        self.day_name = self._day_file()
        return out

    def _save_day(self, r):
        if self._day_file() != getattr(self, "day_name", None):
            self.day = []                       # minuit passé : nouvelle journée
            self.day_name = self._day_file()
        keep = {k: r.get(k) for k in ("hz", "band", "mode", "lang", "prob", "fr", "t")}
        keep["text"] = (r.get("text") or "")[:120]
        self.day.append(keep)
        try:
            os.makedirs(DAY_DIR, exist_ok=True)
            with open(self.day_name, "a") as f:
                f.write(json.dumps(keep, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _day_groups(self):
        """Résultats du jour du segment affiché, regroupés au kHz près."""
        if self.scan_seg is None:
            return []
        lo, hi = self.scan_seg
        groups = {}
        for r in self.day:
            if not lo <= r["hz"] <= hi:
                continue
            g = groups.setdefault(round(r["hz"] / 1000), {"tests": [], "hz": r["hz"]})
            g["tests"].append(r)
        out = []
        for g in groups.values():
            tests = sorted(g["tests"], key=lambda r: r["t"])
            fr = [r for r in tests if r["fr"]]
            last = (fr or tests)[-1]
            out.append({"hz": last["hz"], "mode": last.get("mode") or "", "n": len(tests),
                        "n_fr": len(fr), "first": tests[0]["t"], "last": tests[-1]["t"],
                        "langs": sorted({(r.get("lang") or "?") for r in tests}),
                        "text": next((r.get("text") for r in reversed(fr) if r.get("text")), "")})
        return sorted(out, key=lambda g: g["hz"])

    def _draw_day(self):
        groups = self._day_groups()
        pts = []
        for g in groups:
            fr = g["n_fr"] > 0
            size = min(26, (12 if fr else 8) + 3 * (g["n"] - 1))
            pts.append({"pos": (g["hz"] / 1000, 0.3), "size": size,
                        "brush": pg.mkBrush(VERT if fr else "#8a8f98"),
                        "pen": pg.mkPen("#000"), "symbol": "o" if fr else "s", "data": g})
        self.day_points.setData(pts)
        for item in self.day_labels:
            self.dayp.removeItem(item)
        self.day_labels = []
        for g in groups:
            if g["n_fr"]:
                label = pg.TextItem(time.strftime("%H:%M", time.localtime(g["last"])),
                                    color=VERT, anchor=(0.5, 1.2))
                label.setPos(g["hz"] / 1000, 0.3)
                self.dayp.addItem(label, ignoreBounds=True)
                self.day_labels.append(label)

    def _day_at(self, pos):
        khz = self.dayp.vb.mapSceneToView(pos).x()
        near = [g for g in self._day_groups() if abs(g["hz"] / 1000 - khz) < 1.5]
        return (min(near, key=lambda g: abs(g["hz"] / 1000 - khz)) if near else None), khz

    def _scan_result(self, r):
        self._save_day(r)
        self.pings.append((time.time(), bool(r["fr"])))     # onde de sonar sur le fond
        self.scan_results = [x for x in self.scan_results if abs(x["hz"] - r["hz"]) > 1500]
        self.scan_results.append(r)
        lang = (r["lang"] or "?").upper()
        self.scan_label.setText(
            f"Scan : {fmt_khz(r['hz'] / 1000)} kHz → "
            + (f"QSO FRANÇAIS ({round(r['prob'] * 100)} %)" if r["fr"]
               else f"{lang} ({round(r['prob'] * 100)} %)"))
        if r["fr"]:
            # « F5ABC de F4XYZ » entendu : F4XYZ émet, F5ABC reçoit
            spoken = (r.get("text") or "").upper()
            pair = QSO_PAIR.search(spoken)
            calls = TEXT_CALL.findall(spoken)
            tx = pair.group(2) if pair else (calls[-1] if calls else None)
            rx = pair.group(1) if pair else None
            self.add_spot({"call": f"QSO FR {round(r['hz'] / 1000)}", "hz": r["hz"],
                           "mode": r["mode"], "snr": None, "src": "SCAN", "t": r["t"],
                           "info": (r.get("text") or "")[:80], "by": "KiwiSDR",
                           "tx": tx or "QSO FR", "rx": rx or "?"})
        self._draw_scan()

    def _draw_scan(self):
        self._draw_day()
        now = time.time()
        spots = []
        for r in self.scan_results:
            fresh = now - r["t"] < 600
            color = VERT if r["fr"] else "#8a8f98"
            spots.append({"pos": (r["hz"] / 1000, 0.3), "brush": pg.mkBrush(color),
                          "pen": pg.mkPen("#000"), "symbol": "o" if r["fr"] else "s",
                          "size": 18 if r["fr"] else 11, "data": r["hz"]})
            if not fresh:
                spots[-1]["brush"] = pg.mkBrush(color + "60")
        self.seg_points.setData(spots)
        for item in self.seg_labels:
            self.seg.removeItem(item)
        self.seg_labels = []
        for r in self.scan_results:
            text = "FR" if r["fr"] else (r["lang"] or "?").upper()
            label = pg.TextItem(text, color=VERT if r["fr"] else "#a0a4aa", anchor=(0.5, 1.1))
            label.setPos(r["hz"] / 1000, 0.3)
            self.seg.addItem(label, ignoreBounds=True)
            self.seg_labels.append(label)
    # --- entrées venant du Scope ---------------------------------------------
    def set_frequency(self, hz, mode=""):
        if hz and hz != self.freq_hz:
            old_band = self._scan_band()
            self.freq_hz = hz
            for line in self.tuned:
                line.setPos(hz / 1000)
            self.seg_tuned.setPos(hz / 1000)
            self.day_tuned.setPos(hz / 1000)
            band = self._scan_band()
            if band in SCAN_PHONE and band != old_band:     # échelles prêtes avant le scan
                self._scan_segment(*SCAN_PHONE[band][:2])
            if band != old_band and self.timer.isActive() and self.scan_button.isChecked():
                if band in SCAN_PHONE:
                    self.scan.start(band)
                    self.scan.set_band(band)
                else:
                    self.scan.stop()
        self.mode = mode
        if hz:
            self.freq_label.setText(f"{fmt_khz(hz / 1000)} kHz  {mode}")

    def set_calage(self, text, locked):
        """État du calage sur la voix, affiché en haut (vert = voix calée)."""
        text = f"Voix : {text}" if text else ""
        if text != self.calage_label.text():
            self.calage_label.setText(text)
            self.calage_label.setStyleSheet(
                "font: bold 12pt sans-serif; color: %s;" % ("#3ddc84" if locked else "#ffb74d"))

    def set_span(self, hz):
        b = self.span_buttons.button(hz)
        if b:
            b.setChecked(True)

    def feed_scope(self, points, low, high):
        points = np.asarray(points, np.float32)
        n = len(points)
        if n < 2 or high <= low:
            return
        if self.edges != (low, high) or self.wf.shape[1] != n:
            old = self.edges
            if old and old[1] - old[0] == high - low and self.wf.shape[1] == n:
                shift = round((old[0] - low) / ((high - low) / n))
                self.wf = np.roll(self.wf, shift, axis=1)
                if shift > 0:
                    self.wf[:, :shift] = -160
                elif shift < 0:
                    self.wf[:, shift:] = -160
            else:
                self.wf = np.full((HISTORY, n), -160, np.float32)
                self.avg = None
            self.edges = (low, high)
            self.img.setImage(self.wf, autoLevels=False, levels=(self.low, self.low + self.range))
            self.img.setRect(QtCore.QRectF(low / 1000, 0, (high - low) / 1000, HISTORY))
            self.spec.setXRange(low / 1000, high / 1000, padding=0)
            self.wfp.setYRange(0, HISTORY, padding=0)
            self._place_marks()
        self.avg = points if self.avg is None or len(self.avg) != n \
            else 0.5 * self.avg + 0.5 * points
        step = (high - low) / n
        self.spec_curve.setData((low + (np.arange(n) + 0.5) * step) / 1000, self.avg)
        # niveaux automatiques : bruit sombre, signaux bien visibles
        target = float(np.percentile(points, 20)) - 6
        self.low += 0.05 * (target - self.low)
        top = float(np.percentile(points, 99.5)) + 2
        self.range += 0.05 * (min(max(top - self.low, 25.0), 90.0) - self.range)
        self.spec.setYRange(self.low - 3, self.low + self.range + 8, padding=0)
        self.wf = np.roll(self.wf, 1, axis=0)
        self.wf[0] = points
        self.img.setImage(self.wf, autoLevels=False, levels=(self.low, self.low + self.range))

    def feed_text(self, text):
        """Texte décodé (CW, RTTY, PSK) : les indicatifs français entendus ici."""
        self.text_tail = (self.text_tail + text.upper())[-200:]
        # station écoutée, tous pays : l'indicatif après « DE » d'abord (l'émetteur)
        for call in callsigns.calls_in_text(self.text_tail):
            if call != MY_CALL:
                self._heard_set(call, "décodé ici", MY_CALL)
                break
        for call in set(TEXT_CALL.findall(self.text_tail)):
            if call != MY_CALL and is_french(call) and self.freq_hz:
                self.add_spot({"call": call, "hz": self.freq_hz, "mode": self.mode,
                               "snr": None, "src": "ICI", "t": time.time(),
                               "info": "décodé par le Scope", "by": MY_CALL})
        self.text_tail = self.text_tail[-20:]

    # --- stations ------------------------------------------------------------
    def add_spot(self, s):
        old = self.stations.get(s["call"])
        if old and abs(old["hz"] - s["hz"]) < 3000 and old["t"] > s["t"]:
            return                              # spot plus ancien que celui qu'on a
        s = dict(s)
        s["first"] = old["first"] if old and abs(old["hz"] - s["hz"]) < 3000 else time.time()
        s["n"] = (old["n"] + 1) if old else 1
        if old and not s["mode"]:
            s["mode"] = old["mode"]
        self.stations[s["call"]] = s
        # nouvelle station française sur la bande écoutée : on le signale (ouverture auto)
        band = band_of(self.freq_hz) if self.freq_hz else None
        if s["call"] not in self.known and band and band[1] <= s["hz"] <= band[2] \
                and time.time() - s["t"] < KEEP_S:
            self.known.add(s["call"])
            self.found.emit(s)

    def _source_status(self, name, ok):
        self.src_state[name] = ok

    # --- station écoutée : indicatif et pays, tous modes, tous pays -------------
    def set_audio_source(self, source):
        """Son reçu de la radio (pour l'indicatif dit à la voix)."""
        self.audio_source = source

    def _any_spot(self, s):
        band = band_of(self.freq_hz) if self.freq_hz else None
        if band and band[1] <= s["hz"] <= band[2]:
            self.band_spots[s["call"]] = s
            if len(self.band_spots) > 3000:     # on oublie les plus anciens
                for call, _ in sorted(self.band_spots.items(), key=lambda kv: kv[1]["t"])[:1000]:
                    del self.band_spots[call]

    def _voice_heard(self, calls, text):
        mine = [c for c in calls if c != MY_CALL]
        if mine:
            self._heard_set(mine[-1], "voix (Whisper)", "?", text)

    def _heard_set(self, call, src, rx, text=""):
        """Indicatif trouvé pour la fréquence écoutée (le plus direct l'emporte)."""
        self.heard = {"call": call, "src": src, "rx": rx, "t": time.time(),
                      "hz": self.freq_hz, "country": callsigns.country(call) or "?",
                      "text": text}
        self.heard_label.setText(self._heard_html(self.blink_on))

    def _heard_update(self):
        """Toutes les secondes : nouvelle fréquence → on oublie ; sinon un spot
        (tous pays) tout près de la fréquence donne l'indicatif tout de suite."""
        now = time.time()
        f = self.freq_hz
        if self.heard and (not f or abs(self.heard["hz"] - f) > 1500):
            self.heard = None
        for call in [c for c, s in self.band_spots.items() if now - s["t"] > KEEP_S]:
            del self.band_spots[call]
        if f and (self.heard is None or self.heard["src"].startswith("spot")):
            tol = 300 if self.mode.startswith(("CW", "RTTY")) else 1200
            near = [s for s in self.band_spots.values()
                    if abs(s["hz"] - f) <= tol and now - s["t"] < 600]
            if near:
                s = max(near, key=lambda s: s["t"])
                if not self.heard or self.heard["call"] != s["call"]:
                    self._heard_set(s["call"], "spot " + ("RBN" if s["src"] == "RBN"
                                                          else "DX Summit"), s["by"])
                    self.heard["hz"] = f
        # écoute de la voix : seulement écran visible, en BLU / AM / FM
        want = self.isVisible() and self.audio_source and self.mode.split("-")[0] in VOICE_MODES \
            and not self.mode.endswith("-D")
        if want and not self.voice.running:
            self.voice.start(self.audio_source)
        elif not want and self.voice.running:
            self.voice.stop()
        self.heard_label.setText(self._heard_html(self.blink_on))

    def _heard_html(self, on):
        h = self.heard
        title = "<span style='color:#ffb0b0; font-size:10pt'>STATION ÉCOUTÉE</span>"
        if not h:
            listen = " · écoute de la voix…" if self.voice.running else ""
            return (f"{title}<br><span style='color:#a0a0a0; font-size:13pt'>"
                    f"indicatif pas encore entendu{listen}</span>")
        age = int(time.time() - h["t"])
        rx = (f" · reçue par <span style='color:{RX_COLOR}'>{h['rx']}</span>"
              if h["rx"] not in ("?", "", None) else "")
        return (f"{title}<br>"
                f"<span style='color:{self._tx_color(on)}; font-size:26pt; font-weight:bold'>"
                f"{h['call']}</span>&nbsp;&nbsp;"
                f"<span style='color:#ffffff; font-size:16pt; font-weight:bold'>{h['country']}</span><br>"
                f"<span style='color:#cfcfcf; font-size:10pt'>{h['src']}{rx} · il y a {age} s</span>")

    def _band_stations(self):
        now = time.time()
        for call in [c for c, s in self.stations.items() if now - s["t"] > KEEP_S]:
            del self.stations[call]
        band = band_of(self.freq_hz) if self.freq_hz else None
        if band is None:
            return band, []
        _, lo, hi = band
        return band, sorted((s for s in self.stations.values() if lo <= s["hz"] <= hi),
                            key=lambda s: s["hz"])

    def _color(self, s):
        return {"RBN": BLEU, "DXS": BLANC, "ICI": ROUGE, "SCAN": VERT}.get(s["src"], BLANC)

    def _refresh(self):
        band, stations = self._band_stations()
        now = time.time()
        if band:
            self.count_label.setText(f"{len(stations)} station(s) F sur {band[0]}")
        else:
            self.count_label.setText("hors bande radioamateur")
        self.listw.clear()
        self.list_labels = []
        for s in stations:
            tx, rx = self._who(s)
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, s["call"])
            item.setToolTip(f"Émetteur {tx} (rouge) — reçu par {rx} (jaune) — {s['src']}, "
                            f"{s['n']} spot(s) {s['info']}")
            label = QtWidgets.QLabel(self._row_html(s, self.blink_on))
            label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            label.setStyleSheet("font: bold 12pt monospace; background: transparent; "
                                "padding: 2px 4px;")
            item.setSizeHint(QtCore.QSize(10, label.sizeHint().height() + 2))
            self.list_labels.append((label, s))
            if now - s["first"] < NEW_S and int(now) % 2:
                item.setBackground(QtGui.QColor("#4a3a00"))     # nouvelle : clignote
            if self.freq_hz and abs(s["hz"] - self.freq_hz) < 500:
                item.setBackground(QtGui.QColor("#5a4a10"))     # celle qu'on écoute
            if s["call"] == self.selected:
                item.setBackground(QtGui.QColor("#1f4f8f"))     # choisie d'un clic
            self.listw.addItem(item)
            self.listw.setItemWidget(item, label)
            if s["call"] == self.selected:
                self.listw.scrollToItem(item)
        if not stations:
            item = QtWidgets.QListWidgetItem("  en attente de stations françaises…")
            item.setForeground(QtGui.QColor("#777"))
            item.setFlags(QtCore.Qt.NoItemFlags)
            self.listw.addItem(item)
        parts = [f"{name} {'✓' if self.src_state.get(name) else '…'}"
                 for name in ("RBN CW", "RBN FT8", "DX Summit")]
        self.src_label.setText("Sources : " + "   ".join(parts))
        self._place_marks(stations)
        self._heard_update()

    def _place_marks(self, stations=None):
        """Indicatifs posés sur le waterfall, à leur fréquence (partie visible)."""
        for plot, item in self.marks:
            plot.removeItem(item)
        self.marks = []
        self.mark_labels = []
        if self.edges is None:
            return
        if stations is None:
            stations = self._band_stations()[1]
        lo, hi = self.edges
        visible = [s for s in stations if lo <= s["hz"] <= hi]
        # stations à moins de 400 Hz l'une de l'autre (FT8…) : une seule étiquette
        groups = []
        for s in visible:
            if groups and s["hz"] - groups[-1][-1]["hz"] < 400:
                groups[-1].append(s)
            else:
                groups.append([s])
        now = time.time()
        font = QtGui.QFont("Sans", 12, QtGui.QFont.Bold)
        for i, group in enumerate(groups[:60]):
            best = max(group, key=lambda s: s["t"])
            khz = sum(s["hz"] for s in group) / len(group) / 1000
            color = self._color(best)
            fresh = now - best["t"] < 120
            for plot in (self.spec, self.wfp):
                line = pg.InfiniteLine(khz, angle=90, pen=pg.mkPen(
                    color, width=2 if fresh else 1,
                    style=QtCore.Qt.SolidLine if fresh else QtCore.Qt.DotLine))
                line.setOpacity(0.85 if fresh else 0.45)
                plot.addItem(line, ignoreBounds=True)
                self.marks.append((plot, line))
            group = sorted(group, key=lambda s: -s["t"])
            label = pg.TextItem(html=self._mark_html(group, self.blink_on), anchor=(0.5, 0),
                                fill=pg.mkBrush(0, 0, 0, 185))
            label.setFont(font)
            label.setPos(khz, 4 + (i % 3) * 24)      # en quinconce : pas de chevauchement
            label.setZValue(20)
            self.wfp.addItem(label, ignoreBounds=True)
            self.marks.append((self.wfp, label))
            self.mark_labels.append((label, group))

    # --- émetteur (rouge clignotant) et récepteur (jaune) ---------------------
    def _who(self, s):
        """(émetteur, récepteur) d'une station entendue."""
        tx = s.get("tx") or (s["call"] if not s["call"].startswith("QSO FR") else "?")
        rx = s.get("rx") or s.get("by") or "?"
        return tx, rx

    def _tx_color(self, on):
        return TX_ON if on else TX_OFF

    def _mark_html(self, group, on):
        rows = []
        for s in group[:4]:
            tx, rx = self._who(s)
            rows.append(f"<span style='color:{self._tx_color(on)}'>{tx}</span>"
                        f"<span style='color:#8a8f98'> ← </span>"
                        f"<span style='color:{RX_COLOR}; font-size:10pt'>{rx}</span>")
        if len(group) > 4:
            rows.append(f"<span style='color:#cfcfcf'>+{len(group) - 4}</span>")
        return "<div style='text-align:center; font-weight:bold'>" + "<br>".join(rows) + "</div>"

    def _row_html(self, s, on):
        tx, rx = self._who(s)
        age = int((time.time() - s["t"]) // 60)
        age_txt = "à l'instant" if age < 1 else f"{age} min"
        snr = f" {s['snr']} dB" if s["snr"] is not None else ""
        if "country" not in s:                  # pays de l'émetteur, calculé une fois
            s["country"] = callsigns.country(tx) if tx not in ("?", "QSO FR") else ""
        where = f" <span style='color:#d8d8d8; font-size:9pt'>({s['country']})</span>" \
            if s["country"] else ""
        return (f"<span style='color:#cfcfcf'>{fmt_khz(s['hz'] / 1000)}</span>&nbsp; "
                f"<span style='color:{self._tx_color(on)}'>{tx}</span>{where}"
                f"<span style='color:#8a8f98'> ← </span>"
                f"<span style='color:{RX_COLOR}'>{rx}</span>&nbsp; "
                f"<span style='color:{self._color(s)}; font-size:10pt'>"
                f"{s['mode'] or ''}{snr} · {age_txt}</span>")

    def _blink(self):
        """Clignotement des émetteurs (rouge) : 2 fois par seconde."""
        self.blink_on = not self.blink_on
        if self.heard:
            self.heard_label.setText(self._heard_html(self.blink_on))
        for label, group in self.mark_labels:
            label.setHtml(self._mark_html(group, self.blink_on))
        for label, s in self.list_labels:
            label.setText(self._row_html(s, self.blink_on))

    def _nearest(self, khz):
        best = None
        for s in self._band_stations()[1]:
            d = abs(s["hz"] / 1000 - khz)
            if d <= SNAP_KHZ and (best is None or d < best[0]):
                best = (d, s)
        return best[1] if best else None

    # --- souris --------------------------------------------------------------
    def _khz_at(self, pos):
        for plot in (self.wfp, self.spec):
            if plot.sceneBoundingRect().contains(pos):
                return plot.vb.mapSceneToView(pos).x(), plot is self.wfp
        return None, False

    def _mouse_moved(self, pos):
        if self.dayp.sceneBoundingRect().contains(pos):         # échelle du jour : détail
            g, khz = self._day_at(pos)
            if g:
                langs = ", ".join(x.upper() for x in g["langs"])
                text = (f" {fmt_khz(g['hz'] / 1000)} kHz {g['mode']} "
                        f"\n {'QSO FRANÇAIS' if g['n_fr'] else 'autre langue'} · "
                        f"écouté {g['n']}× ({langs}) "
                        f"\n de {time.strftime('%H:%M', time.localtime(g['first']))} "
                        f"à {time.strftime('%H:%M', time.localtime(g['last']))} ")
                if g["text"]:
                    text += f"\n « {g['text'][:50]} » "
                if text != getattr(self, "_tip_text", None):
                    self._tip_text = text
                    QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text.replace(" \n ", "\n").strip(),
                                                self.graphics)
            else:
                self._tip_text = None
                QtWidgets.QToolTip.hideText()
            return
        if getattr(self, "_tip_text", None):
            self._tip_text = None
            QtWidgets.QToolTip.hideText()
        khz, in_wf = self._khz_at(pos)
        if khz is None or self.edges is None:
            for c in self.cursor:
                c.setVisible(False)
            for band in self.snap_bands:
                band.setVisible(False)
            self.cursor_text.setVisible(False)
            self.mouse_khz = None
            return
        self.mouse_khz = khz
        # curseur aimanté : dans la largeur d'un signal, il se colle sur sa
        # fréquence de calage (bord BLU, pointe CW) et la bande du signal s'éclaire
        hz, mode, what = self._snap(khz)
        snapped = what != "fréquence"              # tout signal reconnu (BLU, CW, FT8, RTTY, AM, FM)
        at = hz / 1000 if snapped else khz
        for c in self.cursor:
            c.setPos(at)
            c.setPen(pg.mkPen(VERT if snapped else "#ffffffc0", width=2 if snapped else 1,
                              style=QtCore.Qt.SolidLine if snapped else QtCore.Qt.DashLine))
            c.setVisible(True)
        for band in self.snap_bands:
            if snapped and self._snap_band:
                band.setRegion((self._snap_band[0] / 1000, self._snap_band[1] / 1000))
            band.setVisible(bool(snapped and self._snap_band))
        s = self._nearest(khz)
        if snapped:
            text = f" ▶ {mode} {fmt_khz(hz / 1000)} kHz \n clic : se caler ({what}) "
        else:
            text = f" {fmt_khz(khz)} kHz "
        if s:
            text += f"\n {s['call']}  {s['mode'] or ''}  ({s['src']}) "
        khz = at
        self.cursor_text.setText(text)
        y = self.wfp.vb.mapSceneToView(pos).y() if in_wf else HISTORY * 0.3
        lo, hi = self.edges
        right_side = khz > (lo + hi) / 2000
        self.cursor_text.setAnchor((1.05, 0) if right_side else (-0.05, 0))
        self.cursor_text.setPos(khz, y)
        self.cursor_text.setVisible(True)

    def _mouse_clicked(self, event):
        """Clic : la radio se cale sur le signal visé (station repérée, bord de la
        BLU ou pointe de la CW). C'est la seule action de cet écran sur le VFO."""
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._fine_drag is not None and self._fine_drag.get("moved"):
            return                              # fin d'un glisser de réglage fin, pas un clic
        pos = event.scenePos()
        if self.dayp.sceneBoundingRect().contains(pos):         # échelle du jour
            g, _ = self._day_at(pos)
            if g:
                self._tune(g["hz"], g["mode"], "QSO FR du jour" if g["n_fr"] else "signal du jour")
            return
        if self.seg.sceneBoundingRect().contains(pos):          # bande de scan
            khz = self.seg.vb.mapSceneToView(pos).x()
            near = [r for r in self.scan_results if abs(r["hz"] / 1000 - khz) < 3]
            if near:
                r = min(near, key=lambda r: abs(r["hz"] / 1000 - khz))
                self._tune(r["hz"], r["mode"], "QSO FR" if r["fr"] else "signal du scan")
            return
        khz, _ = self._khz_at(pos)
        if khz is None:
            return
        s = self._nearest(khz)
        if s:
            self.selected = s["call"]
            self._tune_station(s)
            return
        hz, mode, what = self._snap(khz)
        self._tune(hz, mode, what)

    def _snap(self, khz):
        """Signal sous le clic, d'après le spectre de la radio → (Hz, mode, quoi)."""
        hz = int(round(khz * 100)) * 10
        self._snap_band = None
        if self.avg is None or self.edges is None:
            return hz, "", "fréquence"
        lo, hi = self.edges
        n = len(self.avg)
        step = (hi - lo) / n
        i = int((khz * 1000 - lo) / step)
        if not 0 <= i < n:
            return hz, "", "fréquence"
        spec = np.asarray(self.avg, float)
        noise = float(np.median(spec))
        above = spec > noise + 6
        reach = max(1, int(1500 / step))            # le signal doit toucher le clic à ±1,5 kHz
        near = [k for k in range(max(0, i - reach), min(n, i + reach + 1)) if above[k]]
        if not near:
            return hz, "", "fréquence"
        k = min(near, key=lambda k: abs(k - i))
        gap = max(1, int(400 / step))
        a = b = k
        while a > 0 and any(above[max(0, a - gap):a]):
            a -= 1
        while a < k and not above[a]:
            a += 1
        while b < n - 1 and any(above[b + 1:min(n, b + 1 + gap)]):
            b += 1
        while b > k and not above[b]:
            b -= 1
        f_lo, f_hi = lo + a * step, lo + (b + 1) * step
        width = f_hi - f_lo
        self._snap_band = (f_lo, f_hi)
        centre = (f_lo + f_hi) / 2
        idx = np.arange(a, b + 1)
        w = 10 ** (spec[a:b + 1] / 10)
        peak = lo + (float((idx * w).sum() / w.sum()) + 0.5) * step
        r10 = lambda f: int(round(f / 10) * 10)
        dial = digi_dial(centre)
        if dial and width <= 3500:                  # FT8 / FT4 : base de la fenêtre
            return dial, "USB-D", "FT8/FT4"
        narrow = width <= max(600, 3 * step)
        if narrow and any(x <= centre <= y for x, y in RTTY_PARTS) and width >= 150:
            return r10(centre), "RTTY", "RTTY"
        if narrow:                                  # CW : sur la pointe
            return r10(peak), "CW", "pointe CW"
        if 1000 <= width <= 4500:                   # BLU : la porteuse est au bord
            side = phone_side(centre)
            if len(w) >= 6:                         # la voix est plus forte côté porteuse
                third = len(w) // 3
                tilt = 10 * math.log10(w[:third].mean() / max(w[-third:].mean(), 1e-12))
                if tilt > 3:
                    side = "USB"
                elif tilt < -3:
                    side = "LSB"
            carrier = f_hi + 200 if side == "LSB" else f_lo - 200
            return r10(carrier), side, f"signal BLU {side}"
        if 5000 <= width <= 10000:                  # AM : porteuse au centre
            return r10(peak), "AM", "signal AM"
        if 10000 < width <= 20000:                  # FM (10 m, 6 m)
            return r10(centre), "FM", "signal FM"
        return hz, "", "fréquence"

    def _tune_station(self, s):
        mode = (s.get("mode") or "").upper()
        mode = {"CW": "CW", "LSB": "LSB", "USB": "USB", "FT8": "USB-D", "FT4": "USB-D",
                "RTTY": "RTTY", "PSK31": "USB-D", "AM": "AM", "FM": "FM"}.get(mode, "")
        hz = s["hz"]
        if mode == "USB-D":
            hz = digi_dial(hz) or hz                # FT8/FT4 : fréquence de base
        elif not mode:                              # mode inconnu (DX Summit) : d'après la bande
            hz, mode = mode_by_frequency(hz)
        self._tune(hz, mode, s["call"])

    def _tune(self, hz, mode, what):
        self.tune.emit(int(hz), mode)
        self.tune_label.setText(f"Calé sur {fmt_khz(hz / 1000)} kHz {mode} ({what})")

    def _list_clicked(self, item):
        s = self.stations.get(item.data(QtCore.Qt.UserRole))
        if s:
            self.selected = s["call"]
            self._tune_station(s)
            self._refresh()

    # --- réglage fin à l'oreille : glisser ou molette sur le waterfall ----------
    FINE_HZ_PX = 10                         # glisser : 10 Hz par pixel (Ctrl : 1 Hz)

    def _fine_set(self, hz):
        """Nouvelle fréquence du réglage fin (envoyée au plus toutes les 40 ms)."""
        self._fine_target = int(hz)
        self.tune_label.setText(f"Réglage fin : {fmt_khz(hz / 1000)} kHz — "
                                "glisser ou molette (Ctrl : 1 Hz, Maj : 100 Hz)")
        if not self._fine_timer.isActive():
            self._fine_timer.start(40)
        self._fine_end.start(900)               # fin du réglage : calage sur la voix

    def _fine_send(self):
        if self._fine_target is not None and self._fine_target != self._fine_sent:
            self._fine_sent = self._fine_target
            self.fine.emit(self._fine_target)
        else:
            self._fine_timer.stop()

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.Wheel:
            pos = self.graphics.mapToScene(event.pos())
            if self.freq_hz and self._khz_at(pos)[0] is not None:
                notches = event.angleDelta().y() / 120
                mods = event.modifiers()
                step = 1 if mods & QtCore.Qt.ControlModifier else \
                    100 if mods & QtCore.Qt.ShiftModifier else 10
                base = self._fine_target if self._fine_timer.isActive() or \
                    self._fine_end.isActive() else self.freq_hz
                self._fine_set(round((base + notches * step) / step) * step)
            return True
        if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if self.freq_hz and self._khz_at(self.graphics.mapToScene(event.pos()))[0] is not None:
                self._fine_drag = {"x": event.pos().x(), "hz": self.freq_hz, "moved": False}
            else:
                self._fine_drag = None
        elif t == QtCore.QEvent.MouseMove and self._fine_drag is not None \
                and event.buttons() & QtCore.Qt.LeftButton:
            dx = event.pos().x() - self._fine_drag["x"]
            if abs(dx) > 4 or self._fine_drag["moved"]:
                self._fine_drag["moved"] = True
                per_px = 1 if event.modifiers() & QtCore.Qt.ControlModifier else self.FINE_HZ_PX
                self._fine_set(self._fine_drag["hz"] + dx * per_px)
        elif t == QtCore.QEvent.MouseButtonRelease and self._fine_drag is not None:
            if self._fine_drag["moved"]:
                QtCore.QTimer.singleShot(0, self._fine_drag_done)
                return False
            self._fine_drag = None
        return super().eventFilter(obj, event)

    def _fine_drag_done(self):
        self._fine_drag = None

    # --- capture d'écran -------------------------------------------------------
    def capture(self):
        """Image de tout l'écran WATERFALL FR, puis flash blanc de confirmation."""
        image = self.grab()
        path = os.path.join(SHOT_DIR, time.strftime("waterfall-fr-%Y%m%d-%H%M%S.png"))
        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            ok = image.save(path, "PNG")
        except OSError:
            ok = False
        self.tune_label.setText(f"Capture enregistrée : Images/Waterfall FR/{os.path.basename(path)}"
                                if ok
                                else "Capture impossible (dossier Images ?)")
        if ok:
            flash = QtWidgets.QWidget(self)
            flash.setStyleSheet("background: white;")
            flash.setGeometry(self.rect())
            effect = QtWidgets.QGraphicsOpacityEffect(flash)
            flash.setGraphicsEffect(effect)
            flash.show()
            anim = QtCore.QPropertyAnimation(effect, b"opacity", flash)
            anim.setDuration(450)
            anim.setStartValue(0.85)
            anim.setEndValue(0.0)
            anim.finished.connect(flash.deleteLater)
            anim.start()
        return path if ok else None

    # --- fond radar ------------------------------------------------------------
    SWEEP_S = 5.0                           # un balayage gauche → droite

    def showEvent(self, event):
        self.radar_timer.start(50)
        self.blink_timer.start(500)
        super().showEvent(event)

    def hideEvent(self, event):
        self.radar_timer.stop()
        self.blink_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        home = QtCore.QPointF(w / 2, h - 50)        # centre : sous la boule RETOUR
        reach = math.hypot(w / 2, h)
        now = time.time()
        bg = QtGui.QRadialGradient(home, reach)
        bg.setColorAt(0.0, QtGui.QColor("#1d4fb0"))
        bg.setColorAt(0.35, QtGui.QColor("#0d2d7a"))
        bg.setColorAt(0.7, QtGui.QColor("#061647"))
        bg.setColorAt(1.0, QtGui.QColor("#010614"))
        p.fillRect(self.rect(), bg)
        # balai : cône lumineux qui tourne, traînée qui s'efface derrière lui
        # balayage de la moitié haute, de gauche à droite, puis on recommence
        sweep = 180.0 + (now % self.SWEEP_S) / self.SWEEP_S * 180.0
        cone = QtGui.QConicalGradient(home, -sweep)
        cone.setColorAt(0.0, QtGui.QColor(170, 255, 230, 200))
        cone.setColorAt(0.012, QtGui.QColor(110, 255, 210, 150))
        cone.setColorAt(0.05, QtGui.QColor(80, 245, 200, 100))
        cone.setColorAt(0.13, QtGui.QColor(60, 225, 185, 50))
        cone.setColorAt(0.26, QtGui.QColor(50, 210, 175, 0))
        cone.setColorAt(1.0, QtGui.QColor(60, 220, 180, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(cone)
        p.drawEllipse(home, reach, reach)
        # cercles concentriques gradués, allumés dans le sillage du balai
        step = 85.0
        for i in range(1, int(reach / step) + 1):
            r = i * step
            box = QtCore.QRectF(home.x() - r, home.y() - r, 2 * r, 2 * r)
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(150, 230, 255, 50), 0.9))
            p.drawEllipse(home, r, r)
            for k in range(18):
                alpha = int(220 * (1 - k / 18) ** 1.4)
                p.setPen(QtGui.QPen(QtGui.QColor(170, 255, 225, alpha), 1.2))
                p.drawArc(box, int(-(sweep - 5 * (k + 1)) * 16), int(-5 * 16))
            p.setPen(QtGui.QPen(QtGui.QColor(150, 230, 255, 50), 0.8))
            for deg in range(0, 360, 10):
                c, sn = math.cos(math.radians(deg)), math.sin(math.radians(deg))
                tick = 5 if deg % 30 == 0 else 2.5
                p.drawLine(home + QtCore.QPointF(c * (r - tick), sn * (r - tick)),
                           home + QtCore.QPointF(c * (r + tick), sn * (r + tick)))
        rad = math.radians(sweep)
        tip = home + QtCore.QPointF(math.cos(rad) * reach, math.sin(rad) * reach)
        p.setPen(QtGui.QPen(QtGui.QColor(120, 255, 210, 80), 7))     # halo du faisceau
        p.drawLine(home, tip)
        p.setPen(QtGui.QPen(QtGui.QColor(235, 255, 245, 220), 2.0))
        p.drawLine(home, tip)
        # ondes de sonar : une par QSO écouté (vert = français)
        self.pings = [(t, fr) for t, fr in self.pings if now - t < 4.0]
        for t, fr in self.pings:
            age = now - t
            for k in range(3):
                a = age - k * 0.35
                if a <= 0:
                    continue
                r = a * 420
                alpha = int(230 * max(0.0, 1 - a / 3.2))
                col = QtGui.QColor(61, 220, 132, alpha) if fr else QtGui.QColor(200, 210, 230, alpha // 2)
                p.setPen(QtGui.QPen(col, 3 - k))
                p.drawEllipse(home, r, r)
        p.end()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.back.emit()
        else:
            super().keyPressEvent(event)


if __name__ == "__main__":              # essai : faux scope, vrais spots
    app = QtWidgets.QApplication([])
    pg.setConfigOptions(imageAxisOrder="row-major", antialias=True)
    w = WaterfallFrance()
    w.set_frequency(7_100_000, "LSB")
    w.set_span(100_000)
    w.add_spot({"call": "F5ABC", "hz": 7_085_000, "mode": "", "snr": None, "src": "DXS",
                "t": time.time(), "info": "essai", "by": "F1XXX"})
    w.add_spot({"call": "TM5TST", "hz": 7_120_500, "mode": "CW", "snr": 12, "src": "RBN",
                "t": time.time(), "info": "CQ", "by": "DL1X"})
    w.back.connect(app.quit)

    def fake():
        f = w.freq_hz
        n = 475
        x = np.linspace(f - 100_000, f + 100_000, n)
        pts = -125 + 4 * np.random.randn(n)
        for s in w.stations.values():
            pts += 50 * np.exp(-((x - s["hz"]) / 600) ** 2)
        w.feed_scope(pts, f - 100_000, f + 100_000)
    t = QtCore.QTimer()
    t.timeout.connect(fake)
    t.start(60)
    w.start()
    w.showFullScreen()
    app.exec_()
    w.spots.stop()
