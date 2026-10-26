"""Mappemonde FT8 : fond bleu nuit dégradé, stations entendues en temps réel.

WSJT-X envoie chaque décodage en UDP (127.0.0.1:2237). Chaque station qui
émet est placée sur la carte : par son locator s'il est dans le message (ou
déjà vu), sinon par le pays de son indicatif (cty.dat fourni avec WSJT-X).
Point rouge clignotant = entendue depuis moins de 2 min ; point rouge sombre
= entendue dans le quart d'heure ; effacée après 30 min.
La ligne nuit/jour est recalculée chaque minute.
Essai seul : python3 ft8_map.py (fenêtre normale).
"""

import datetime
import json
import math
import subprocess
import os
import re
import struct
import time
import zlib

from PyQt5 import QtCore, QtGui, QtNetwork, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
LAND = os.path.join(HERE, "carte", "ne_50m_land.geojson")
BORDERS = os.path.join(HERE, "carte", "ne_110m_admin_0_countries.geojson")
CTY = "/usr/share/wsjtx/cty.dat"
UDP_PORT = 2237
MAGIC = 0xADBCCBDA

ACTIVE_S = 15           # une période FT8 : la station disparaît dès la suivante
SLOT_S = 15.0           # FT8 : 15 s d'émission, 15 s d'écoute, en alternance


SONAR_WAV = os.path.expanduser("~/.cache/ic7300-scope/sonar.wav")


def sonar_wav():
    """Fabrique (une fois) le « ping » de sonar : bip 1,4 kHz qui s'éteint, suivi
    de deux échos plus faibles et plus sourds."""
    if os.path.exists(SONAR_WAV):
        return SONAR_WAV
    import struct, wave
    os.makedirs(os.path.dirname(SONAR_WAV), exist_ok=True)
    rate, dur = 22050, 1.6
    n = int(rate * dur)
    out = [0.0] * n
    for delay, gain, f in ((0.0, 1.0, 1400.0), (0.32, 0.38, 1385.0), (0.66, 0.15, 1370.0)):
        start = int(delay * rate)
        for i in range(n - start):
            t = i / rate
            env = min(1.0, t / 0.004) * math.exp(-t * (5.5 if delay == 0 else 7.5))
            out[start + i] += gain * env * (math.sin(2 * math.pi * f * t)
                                            + 0.25 * math.sin(2 * math.pi * 2 * f * t))
    peak = max(abs(v) for v in out) or 1.0
    with wave.open(SONAR_WAV, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(v / peak * 26000)) for v in out))
    return SONAR_WAV


def on_air(t_decode, now):
    """La station émet-elle EN CE MOMENT ? Décodée à la fin de sa période
    d'émission (≈ 13–16 s après le début), elle réémet deux périodes plus tard
    (même parité) ; entre les deux elle écoute → pas affichée."""
    slot_tx = int((t_decode - 7.0) // SLOT_S)       # période où elle a émis
    return int(now // SLOT_S) - slot_tx == 2
SWEEP_S = 15.0          # le balai radar fait un tour par période FT8
RECENT_S = 15 * 60      # point sombre
FORGET_S = 30 * 60      # effacée
CORR_S = 10 * 60        # correspondant : flashe encore 10 min après son dernier message

GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")
CALL_RE = re.compile(r"^(?=.*[0-9])(?=.*[A-Z])[A-Z0-9/]{3,12}$")


# --- positions ---------------------------------------------------------------
def grid_to_latlon(grid):
    g = grid.upper()
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) >= 6:
        lon += (ord(g[4]) - 65) * 5 / 60 + 2.5 / 60
        lat += (ord(g[5]) - 65) * 2.5 / 60 + 1.25 / 60
    else:
        lon += 1
        lat += 0.5
    return lat, lon


COUNTRY = {}             # préfixe (ou =indicatif) → nom du pays (rempli par load_cty)


def load_cty(path=CTY):
    """préfixe → (lat, lon) ; '=INDICATIF' pour les indicatifs exacts."""
    table = {}
    try:
        text = open(path, encoding="latin-1").read()
    except OSError:
        return table
    for block in text.split(";"):
        if ":" not in block:
            continue
        head, _, aliases = block.rpartition(":")
        fields = [f.strip() for f in head.split(":")]
        if len(fields) < 7:
            continue
        try:
            lat, lon = float(fields[4]), -float(fields[5])     # cty.dat : ouest positif
        except ValueError:
            continue
        for alias in aliases.replace("\n", "").split(","):
            alias = alias.strip()
            pos = (lat, lon)
            m = re.search(r"<([-\d.]+)/([-\d.]+)>", alias)
            if m:
                pos = (float(m.group(1)), -float(m.group(2)))
            alias = re.sub(r"[\(\[<{~].*$", "", alias).strip()
            if alias:
                table[alias] = pos
                COUNTRY[alias] = fields[0]
    return table


def base_call(call):
    """F/G4ABC → F ; G4ABC/P → G4ABC (partie qui donne le pays)."""
    parts = [p for p in call.split("/")
             if p and p not in ("P", "M", "MM", "AM", "QRP", "A") and not p.isdigit()]
    if not parts:
        return call
    if len(parts) == 1:
        return parts[0]
    return min(parts[:2], key=len)


class Locator:
    def __init__(self):
        self.cty = load_cty()
        self.grids = {}                 # indicatif → locator déjà vu

    def country(self, call):
        """Nom du pays de l'indicatif, ou None s'il n'est pas reconnu."""
        if "=" + call in COUNTRY:
            return COUNTRY["=" + call]
        key = base_call(call)
        for n in range(len(key), 0, -1):
            if key[:n] in COUNTRY:
                return COUNTRY[key[:n]]
        return None

    def position(self, call):
        """(lat, lon, exact) ou None."""
        grid = self.grids.get(call)
        if grid:
            lat, lon = grid_to_latlon(grid)
            return lat, lon, True
        exact = self.cty.get("=" + call)
        if exact:
            return (*exact, False)
        key = base_call(call)
        for n in range(len(key), 0, -1):
            pos = self.cty.get(key[:n])
            if pos:
                # petit décalage fixe par indicatif : pas tous sur le même point
                h = zlib.crc32(call.encode())
                return (pos[0] + ((h & 0xFF) / 255 - 0.5) * 3,
                        pos[1] + (((h >> 8) & 0xFF) / 255 - 0.5) * 4, False)
        return None


def parse_message(text):
    """Message FT8 → (indicatif qui émet, locator ou None, appel CQ ?, destinataire)."""
    tokens = [t.strip("<>") for t in text.upper().split()]
    to = tokens[0] if tokens and tokens[0] != "CQ" else None
    call, grid, cq = _parse_tokens(tokens)
    return call, grid, cq, to


def _parse_tokens(tokens):
    if not tokens:
        return None, None, False
    if tokens[0] == "CQ":
        rest = tokens[1:]
        if len(rest) >= 2 and not CALL_RE.match(rest[0]):
            rest = rest[1:]             # CQ DX, CQ EU, CQ POTA…
        call = rest[0] if rest else None
        grid = rest[1] if len(rest) > 1 else None
        cq = True
    elif len(tokens) >= 2:
        call = tokens[1]
        grid = tokens[2] if len(tokens) > 2 else None
        cq = False
    else:
        return None, None, False
    if not call or not CALL_RE.match(call):
        return None, None, cq
    if grid and (grid == "RR73" or not GRID_RE.match(grid)):
        grid = None
    return call, grid, cq


# --- protocole UDP de WSJT-X ------------------------------------------------
class _Reader:
    def __init__(self, data):
        self.d, self.i = data, 0

    def take(self, fmt):
        v = struct.unpack_from(">" + fmt, self.d, self.i)
        self.i += struct.calcsize(">" + fmt)
        return v[0]

    def text(self):
        n = self.take("I")
        if n == 0xFFFFFFFF:
            return ""
        s = self.d[self.i:self.i + n].decode("utf-8", "replace")
        self.i += n
        return s


def parse_udp(data):
    """→ ('decode', snr, message) / ('status', dx_call, transmitting) / None."""
    try:
        r = _Reader(data)
        if r.take("I") != MAGIC:
            return None
        r.take("I")                     # version du schéma
        kind = r.take("I")
        r.text()                        # nom de l'appli
        if kind == 2:                   # décodage
            r.take("?")
            r.take("I")
            snr = r.take("i")
            r.take("d")
            r.take("I")
            r.text()
            return ("decode", snr, r.text())
        if kind == 1:                   # état
            r.take("Q")
            r.text()
            dx = r.text()
            r.text()
            r.text()
            r.take("?")
            tx = r.take("?")
            return ("status", dx, tx)
    except (struct.error, IndexError):
        return None
    return None


# --- soleil -----------------------------------------------------------------
def subsolar(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    n = now.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1 + (now.hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    minutes = now.hour * 60 + now.minute + now.second / 60
    lon = -(minutes + eqt - 720) / 4
    return math.degrees(decl), lon


# --- fenêtre ----------------------------------------------------------------
class Ft8Map(QtWidgets.QWidget):
    def __init__(self, home_grid="JN33ps", home_call="F4TXR", background=True):
        flags = QtCore.Qt.Window
        if background:
            flags |= (QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowTransparentForInput
                      | QtCore.Qt.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setWindowTitle("Carte FT8")
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.home = grid_to_latlon(home_grid)
        self.home_call = home_call
        self.locator = Locator()
        self.stations = {}              # indicatif → dict
        self.dx_call = ""
        self.transmitting = False
        self.land = self._load_polygons(LAND)
        self.borders = self._load_polygons(BORDERS)
        self.cache = None
        self.cache_minute = None
        self.phase = 0.0
        self.udp = QtNetwork.QUdpSocket(self)
        self.udp.readyRead.connect(self._read_udp)
        self.listening = False
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    # --- marche / arrêt
    def start(self):
        if not self.listening:
            self.listening = self.udp.bind(
                QtNetwork.QHostAddress.LocalHost, UDP_PORT,
                QtNetwork.QUdpSocket.ShareAddress | QtNetwork.QUdpSocket.ReuseAddressHint)
        self.timer.start(40)

    def stop(self):
        self.timer.stop()
        self.udp.close()
        self.listening = False
        self.hide()

    # --- données
    @staticmethod
    def _load_polygons(path):
        try:
            data = json.load(open(path))
        except (OSError, ValueError):
            return []
        rings = []
        for feat in data["features"]:
            geom = feat["geometry"]
            polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
            for poly in polys:
                rings.append(poly[0])
        return rings

    def _read_udp(self):
        while self.udp.hasPendingDatagrams():
            data, _, _ = self.udp.readDatagram(self.udp.pendingDatagramSize())
            msg = parse_udp(data)
            if not msg:
                continue
            if msg[0] == "decode":
                self.add_decode(msg[2], msg[1])
            else:
                self.set_status(msg[1], msg[2])

    def set_status(self, dx_call, transmitting):
        """État de WSJT-X : correspondant choisi (DX Call) et émission."""
        self.dx_call, self.transmitting = dx_call.upper().strip(), transmitting
        if self.dx_call and CALL_RE.match(self.dx_call):
            s = self.stations.get(self.dx_call)
            if s is None:                   # pas encore entendu : placé par son pays
                pos = self.locator.position(self.dx_call)
                if pos:
                    s = self.stations[self.dx_call] = {
                        "lat": pos[0], "lon": pos[1], "exact": pos[2], "t": time.time(),
                        "snr": 0, "cq": False,
                        "seed": (zlib.crc32(self.dx_call.encode()) % 628) / 100}
            if s is not None:
                s["corr"] = time.time()

    def add_decode(self, text, snr=0):
        call, grid, cq, to = parse_message(text)
        if not call:
            return
        old = self.stations.get(call, {})
        if grid:
            self.locator.grids[call] = grid
        pos = self.locator.position(call)
        if not pos:
            return
        self.stations[call] = {"lat": pos[0], "lon": pos[1], "exact": pos[2],
                               "t": time.time(), "snr": snr, "cq": cq,
                               "seed": (zlib.crc32(call.encode()) % 628) / 100,
                               "corr": old.get("corr", 0)}
        if to == self.home_call or call == self.dx_call:     # il m'appelle / mon QSO
            self.stations[call]["corr"] = time.time()

    def _tick(self):
        now = time.time()
        for call in [c for c, s in self.stations.items() if now - s["t"] > FORGET_S]:
            del self.stations[call]
        self.phase = now
        self._sonar(now)
        self.update()

    def _sonar(self, now):
        """Ping de sonar quand le balai rencontre une station en émission ;
        plus la station est loin, plus le ping est faible."""
        sweep = (now % SWEEP_S) / SWEEP_S * 360.0
        prev = getattr(self, "sweep_prev", sweep)
        self.sweep_prev = sweep
        span = (sweep - prev) % 360
        if span <= 0 or span > 90 or not self.isVisible():
            return
        home = self._xy(*self.home)
        far = math.hypot(self.width(), self.height()) / 2
        best = None
        for st in self.stations.values():
            if not on_air(st["t"], now):
                continue
            pt = self._xy(st["lat"], st["lon"])
            ang = math.degrees(math.atan2(pt.y() - home.y(), pt.x() - home.x())) % 360
            if (ang - prev) % 360 <= span:
                d = math.hypot(pt.x() - home.x(), pt.y() - home.y())
                best = d if best is None else min(best, d)
        if best is None or now - getattr(self, "ping_t", 0) < 0.15:
            return
        self.ping_t = now
        volume = int(65536 * max(0.25, 0.85 - 0.55 * min(1.0, best / far)))
        try:
            subprocess.Popen(["paplay", f"--volume={volume}", "--client-name=Sonar FT8",
                              sonar_wav()], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    # --- dessin
    def _xy(self, lat, lon):
        w, h = self.width(), self.height()
        return QtCore.QPointF((lon + 180) / 360 * w, (90 - lat) / 180 * h)

    def _path(self, ring):
        path = QtGui.QPainterPath()
        for i, (lon, lat) in enumerate(ring):
            p = self._xy(lat, lon)
            if i:
                path.lineTo(p)
            else:
                path.moveTo(p)
        path.closeSubpath()
        return path

    def _background(self):
        minute = int(time.time() // 60)
        if self.cache is not None and self.cache.size() == self.size() \
                and self.cache_minute == minute:
            return self.cache
        w, h = self.width(), self.height()
        pix = QtGui.QPixmap(self.size())
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # fond bleu nuit dégradé : plus clair au centre, presque noir aux bords
        # dégradé de la droite (bleu vif) vers la gauche (presque noir)
        grad = QtGui.QLinearGradient(w, 0, 0, 0)
        grad.setColorAt(0.0, QtGui.QColor("#2b6ae0"))
        grad.setColorAt(0.35, QtGui.QColor("#123a9a"))
        grad.setColorAt(0.7, QtGui.QColor("#071a52"))
        grad.setColorAt(1.0, QtGui.QColor("#010614"))
        p.fillRect(0, 0, w, h, grad)
        # quadrillage discret
        p.setPen(QtGui.QPen(QtGui.QColor(120, 170, 255, 45), 1))
        for lon in range(-180, 181, 30):
            p.drawLine(self._xy(90, lon), self._xy(-90, lon))
        for lat in range(-60, 91, 30):
            p.drawLine(self._xy(lat, -180), self._xy(lat, 180))
        # continents
        land = QtGui.QPainterPath()
        land.setFillRule(QtCore.Qt.WindingFill)
        for ring in self.land:
            land.addPath(self._path(ring))
        lg = QtGui.QLinearGradient(0, 0, 0, h)
        lg.setColorAt(0.0, QtGui.QColor(110, 175, 255, 235))
        lg.setColorAt(1.0, QtGui.QColor(60, 120, 230, 220))
        p.setPen(QtGui.QPen(QtGui.QColor(200, 235, 255, 255), 1.6))
        p.setBrush(lg)
        p.drawPath(land)
        # frontières
        p.setPen(QtGui.QPen(QtGui.QColor(20, 50, 120, 150), 0.8))
        p.setBrush(QtCore.Qt.NoBrush)
        for ring in self.borders:
            p.drawPath(self._path(ring))
        # côté nuit
        decl, slon = subsolar()
        tdecl = math.tan(math.radians(decl if abs(decl) > 0.1 else 0.1))
        night = QtGui.QPainterPath()
        for i, lon in enumerate(range(-180, 181, 2)):
            lat = math.degrees(math.atan(-math.cos(math.radians(lon - slon)) / tdecl))
            pt = self._xy(lat, lon)
            night.moveTo(pt) if i == 0 else night.lineTo(pt)
        pole = -90 if decl > 0 else 90
        night.lineTo(self._xy(pole, 180))
        night.lineTo(self._xy(pole, -180))
        night.closeSubpath()
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 12, 95))
        p.drawPath(night)
        # soleil
        sp = self._xy(decl, slon)
        sun = QtGui.QRadialGradient(sp, 26)
        sun.setColorAt(0, QtGui.QColor(255, 230, 140, 160))
        sun.setColorAt(1, QtGui.QColor(255, 230, 140, 0))
        p.setBrush(sun)
        p.drawEllipse(sp, 26, 26)
        p.end()
        self.cache, self.cache_minute = pix, minute
        return pix

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._background())
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        now = time.time()
        home = self._xy(*self.home)
        # liaison avec la station en QSO
        dx = self.stations.get(self.dx_call)
        if dx:
            col = QtGui.QColor(255, 80, 80, 200) if self.transmitting else QtGui.QColor(255, 210, 120, 170)
            p.setPen(QtGui.QPen(col, 1.6, QtCore.Qt.DashLine))
            p.drawLine(home, self._xy(dx["lat"], dx["lon"]))
        # balai radar depuis ma station : un tour par période FT8 (calé sur l'UTC)
        sweep = (now % SWEEP_S) / SWEEP_S * 360.0          # degrés, sens horaire
        reach = math.hypot(self.width(), self.height())
        cone = QtGui.QConicalGradient(home, -sweep)
        cone.setColorAt(0.0, QtGui.QColor(170, 255, 230, 235))
        cone.setColorAt(0.012, QtGui.QColor(110, 255, 210, 185))
        cone.setColorAt(0.05, QtGui.QColor(80, 245, 200, 130))
        cone.setColorAt(0.13, QtGui.QColor(60, 225, 185, 70))
        cone.setColorAt(0.26, QtGui.QColor(50, 210, 175, 0))
        cone.setColorAt(1.0, QtGui.QColor(60, 220, 180, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(cone)
        p.drawEllipse(home, reach, reach)
        # cercles concentriques gradués, espacés régulièrement : fins en permanence,
        # ils s'allument dans le sillage du balai
        step = 85.0
        rings = int(reach / step)
        for i in range(1, rings + 1):
            r = i * step
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(150, 230, 255, 55), 0.9))
            p.drawEllipse(home, r, r)
            box = QtCore.QRectF(home.x() - r, home.y() - r, 2 * r, 2 * r)
            for k in range(18):                     # sillage : 18 tranches de 5°
                alpha = int(235 * (1 - k / 18) ** 1.4)
                p.setPen(QtGui.QPen(QtGui.QColor(170, 255, 225, alpha), 1.2))
                start = -(sweep - 5 * (k + 1))      # Qt : degrés dans le sens inverse
                p.drawArc(box, int(start * 16), int(-5 * 16))
            # graduations : petits traits tous les 10° sur chaque cercle
            p.setPen(QtGui.QPen(QtGui.QColor(150, 230, 255, 55), 0.8))
            for deg in range(0, 360, 10):
                c, sn = math.cos(math.radians(deg)), math.sin(math.radians(deg))
                tick = 5 if deg % 30 == 0 else 2.5
                p.drawLine(home + QtCore.QPointF(c * (r - tick), sn * (r - tick)),
                           home + QtCore.QPointF(c * (r + tick), sn * (r + tick)))
        rad = math.radians(sweep)
        p.setPen(QtGui.QPen(QtGui.QColor(120, 255, 210, 90), 7))          # halo du faisceau
        p.drawLine(home, home + QtCore.QPointF(math.cos(rad) * reach, math.sin(rad) * reach))
        p.setPen(QtGui.QPen(QtGui.QColor(235, 255, 245, 255), 2.2))
        p.drawLine(home, home + QtCore.QPointF(math.cos(rad) * reach, math.sin(rad) * reach))
        font = QtGui.QFont("DejaVu Sans", 8)
        p.setFont(font)
        active = 0
        corrs = []
        for call, s in sorted(self.stations.items(), key=lambda kv: kv[1]["t"]):
            age = now - s["t"]
            pt = self._xy(s["lat"], s["lon"])
            if now - s.get("corr", 0) < CORR_S:
                corrs.append((call, s, pt))     # dessinés par-dessus, en flashs
                continue
            if on_air(s["t"], now):
                active += 1
                ang = math.degrees(math.atan2(pt.y() - home.y(), pt.x() - home.x())) % 360
                since = (sweep - ang) % 360 / 360 * SWEEP_S
                hit = math.exp(-since * 3.0)                # éclair du passage du balai
                echo = math.exp(-since / 5.0)               # rémanence (~15 s)
                # trou sombre autour de la station : elle se détache du bleu
                hole = QtGui.QRadialGradient(pt, 24)
                hole.setColorAt(0, QtGui.QColor(0, 0, 10, 235))
                hole.setColorAt(0.55, QtGui.QColor(0, 0, 10, 150))
                hole.setColorAt(1, QtGui.QColor(0, 0, 10, 0))
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(hole)
                p.drawEllipse(pt, 24, 24)
                # écho radar ambre (tranche sur le bleu) : éclair puis rémanence
                er = 8 + 14 * hit
                glow = QtGui.QRadialGradient(pt, er)
                glow.setColorAt(0, QtGui.QColor(255, 255, 220, int(255 * max(hit, 0.6 * echo))))
                glow.setColorAt(0.35, QtGui.QColor(255, 170, 0, int(230 * echo)))
                glow.setColorAt(1, QtGui.QColor(255, 120, 0, 0))
                p.setBrush(glow)
                p.drawEllipse(pt, er, er)
                # impulsions fines : deux ondes jaune / orange (4 par seconde)
                t = (now * 4.0 + s["seed"] / 6.28) % 1.0
                p.setBrush(QtCore.Qt.NoBrush)
                p.setPen(QtGui.QPen(QtGui.QColor(255, 235, 0, int(255 * (1 - t) ** 0.5)), 2.0))
                p.drawEllipse(pt, 2 + 17 * t, 2 + 17 * t)
                t2 = (t + 0.5) % 1.0
                p.setPen(QtGui.QPen(QtGui.QColor(255, 90, 0, int(240 * (1 - t2) ** 0.5)), 1.6))
                p.drawEllipse(pt, 2 + 17 * t2, 2 + 17 * t2)
                # croissant d'écho tourné vers ma station
                p.setPen(QtGui.QPen(QtGui.QColor(255, 210, 60, int(240 * echo)), 2.2))
                back = math.degrees(math.atan2(-(home.y() - pt.y()), home.x() - pt.x()))
                p.drawArc(QtCore.QRectF(pt.x() - 12, pt.y() - 12, 24, 24),
                          int((back - 35) * 16), int(70 * 16))
                # le point : blanc cerclé de noir
                p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1.2))
                p.setBrush(QtGui.QColor(255, 255, 255))
                p.drawEllipse(pt, 2.6, 2.6)
                # indicatif sur étiquette sombre
                bold = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Bold)
                p.setFont(bold)
                fm = QtGui.QFontMetrics(bold)
                box = QtCore.QRectF(pt.x() + 9, pt.y() - 18, fm.horizontalAdvance(call) + 8, 14)
                p.setPen(QtGui.QPen(QtGui.QColor(255, 200, 0, int(120 + 135 * hit)), 1))
                p.setBrush(QtGui.QColor(0, 0, 12, 205))
                p.drawRoundedRect(box, 4, 4)
                p.setPen(QtGui.QColor(255, 230, 60))
                p.drawText(box, QtCore.Qt.AlignCenter, call)
                p.setFont(font)
            # émission terminée : la station n'est plus dessinée
        # correspondants : flashs blancs/jaunes vifs + onde, nom en gras
        for call, s, pt in corrs:
            t = (now * 2.2 + s["seed"] / 6.28) % 1.0     # 2,2 flashs par seconde
            flash = t < 0.18 or 0.30 < t < 0.40         # double éclair
            ring = (now % 1.2) / 1.2
            p.setPen(QtGui.QPen(QtGui.QColor(255, 220, 90, int(220 * (1 - ring))), 2))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(pt, 6 + 34 * ring, 6 + 34 * ring)
            if flash:
                halo = QtGui.QRadialGradient(pt, 30)
                halo.setColorAt(0, QtGui.QColor(255, 255, 255, 255))
                halo.setColorAt(0.25, QtGui.QColor(255, 230, 120, 220))
                halo.setColorAt(1, QtGui.QColor(255, 60, 30, 0))
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(halo)
                p.drawEllipse(pt, 30, 30)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255) if flash else QtGui.QColor(255, 60, 40))
            p.drawEllipse(pt, 5, 5)
            p.setFont(QtGui.QFont("DejaVu Sans", 11, QtGui.QFont.Bold))
            p.setPen(QtGui.QColor(0, 0, 0, 180))
            p.drawText(pt + QtCore.QPointF(10, -8), call)
            p.setPen(QtGui.QColor("#ffe27a"))
            p.drawText(pt + QtCore.QPointF(9, -9), call)
        # en émission : ma station envoie des ondes
        if self.transmitting:
            for k in range(3):
                r = ((now * 0.9 + k / 3) % 1.0)
                p.setPen(QtGui.QPen(QtGui.QColor(255, 210, 122, int(200 * (1 - r))), 2))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(home, 6 + 40 * r, 6 + 40 * r)
        # ma station
        p.setPen(QtGui.QPen(QtGui.QColor("#2a1c06"), 1))
        p.setBrush(QtGui.QColor("#ffd27a"))
        p.drawEllipse(home, 5, 5)
        p.setPen(QtGui.QColor("#ffd27a"))
        p.setFont(QtGui.QFont("DejaVu Sans", 9, QtGui.QFont.Bold))
        p.drawText(home + QtCore.QPointF(8, 14), self.home_call)
        # compteur
        p.setFont(QtGui.QFont("DejaVu Sans", 11, QtGui.QFont.Bold))
        p.setPen(QtGui.QColor(200, 220, 255, 200))
        p.drawText(QtCore.QRectF(0, self.height() - 34, self.width() - 20, 24),
                   QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                   f"FT8 · {active} stations en émission maintenant · {len(self.stations)} entendues en 30 min")
        p.end()


if __name__ == "__main__":
    import random
    import sys
    app = QtWidgets.QApplication(sys.argv)
    m = Ft8Map(background=False)
    m.resize(1400, 760)
    for text in ("CQ K1ABC FN42", "F4TXR DL1XYZ JO62", "CQ DX JA1ABC PM95", "CQ VK2DEF QF56",
                 "EA4ZZ PY2ABC GG66", "CQ ZS6XX KG33", "G4ABC W5XYZ R-07", "CQ 9A3AA",
                 "CQ LU1AA GF05", "CQ UA9ABC", "RK3AA 4X4ZZ -12"):
        m.add_decode(text)
    for s in list(m.stations.values())[::3]:
        s["t"] -= random.choice((300, 1300))
    m.add_decode("F4TXR EA4ZZ IN80")
    m.set_status("JA1ABC", True)
    m.start()
    m.show()
    if "--shot" in sys.argv:
        QtCore.QTimer.singleShot(800, lambda: (m.grab().save(sys.argv[-1]), app.quit()))
    app.exec_()
