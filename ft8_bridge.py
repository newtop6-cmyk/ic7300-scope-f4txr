"""Pont FT8 : WSJT-X pilote la radio à travers le Scope.

Le Scope garde sa liaison unique avec la radio (port 7300 du Pi). Ce module
ouvre un petit serveur sur 127.0.0.1:4532 qui parle comme « rigctld »
(Hamlib) : dans WSJT-X, Radio = « Hamlib NET rigctl », serveur
127.0.0.1:4532, PTT par CAT. Fréquence, mode et émission passent donc par
le Scope, qui coupe le micro et l'écoute pendant les émissions FT8.

`rig` doit fournir : get_freq(), set_freq(hz), get_mode() -> nom Hamlib,
set_mode(nom Hamlib), get_ptt() -> bool, set_ptt(bool).
"""

import os
import string
import struct

from PyQt5 import QtCore, QtNetwork

PORT = 4532

# réponse à « \dump_state » (protocole 0) : plages 30 kHz–74,8 MHz, 100 W
_MODES = 0x1FF          # AM CW USB LSB RTTY FM ... (masque large, peu importe)
DUMP_STATE = "\n".join([
    "0", "2", "2",
    f"30000.000000 74800000.000000 0x{_MODES:x} -1 -1 0x3 0x1",
    "0 0 0 0 0 0 0",
    f"1800000.000000 74800000.000000 0x{_MODES:x} 2000 100000 0x3 0x1",
    "0 0 0 0 0 0 0",
    f"0x{_MODES:x} 1", f"0x{_MODES:x} 10", "0 0",
    f"0x{_MODES:x} 3000", f"0x{_MODES:x} 2400", "0 0",
    "9999", "9999", "0", "0", "", "",
    "0x0", "0x0", "0x0", "0x0", "0x0", "0x0",
]) + "\n"

# fréquences FT8 normalisées (région 1), en Hz
FT8_FREQS = (1_840_000, 3_573_000, 5_357_000, 7_074_000, 10_136_000, 14_074_000,
             18_100_000, 21_074_000, 24_915_000, 28_074_000, 50_313_000, 70_154_000)


def ft8_freq_for(hz):
    """Fréquence FT8 de la bande où se trouve hz (la plus proche en rapport)."""
    if not hz:
        return 14_074_000
    return min(FT8_FREQS, key=lambda f: abs(f / hz - 1))


RPRT_OK = "RPRT 0\n"
RPRT_ERR = "RPRT -1\n"
RPRT_NA = "RPRT -11\n"

# commandes longues « \get_freq » → lettre courte
_LONG = {"get_freq": "f", "set_freq": "F", "get_mode": "m", "set_mode": "M",
         "get_vfo": "v", "set_vfo": "V", "get_ptt": "t", "set_ptt": "T",
         "get_split_vfo": "s", "set_split_vfo": "S"}


class RigctlServer(QtCore.QObject):
    status = QtCore.pyqtSignal(str)

    def __init__(self, rig, parent=None):
        super().__init__(parent)
        self.rig = rig
        self.server = QtNetwork.QTcpServer(self)
        self.server.newConnection.connect(self._new)
        self.clients = []

    def start(self):
        if self.server.isListening():
            return True
        ok = self.server.listen(QtNetwork.QHostAddress.LocalHost, PORT)
        if not ok:
            self.status.emit(f"FT8 : port {PORT} occupé ({self.server.errorString()})")
        return ok

    def stop(self):
        for sock in self.clients:
            sock.disconnectFromHost()
        self.clients = []
        self.server.close()

    def _new(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.buf = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._gone(s))
            self.clients.append(sock)
            self.status.emit("FT8 : WSJT-X connecté au Scope")

    def _gone(self, sock):
        if sock in self.clients:
            self.clients.remove(sock)
        sock.deleteLater()
        if self.rig.get_ptt():              # sécurité : jamais d'émission orpheline
            self.rig.set_ptt(False)

    def _read(self, sock):
        sock.buf += bytes(sock.readAll())
        while b"\n" in sock.buf:
            line, sock.buf = sock.buf.split(b"\n", 1)
            reply = self.handle(line.decode("ascii", "replace").strip())
            if reply is None:
                sock.disconnectFromHost()
                return
            sock.write(reply.encode())

    def handle(self, line):
        """Une commande rigctl → la réponse texte (None = fin de connexion)."""
        if not line:
            return ""
        parts = line.split()
        cmd, args = parts[0], parts[1:]
        if cmd.startswith("\\"):
            name = cmd[1:]
            if name == "chk_vfo":
                return "CHKVFO 0\n"
            if name == "dump_state":
                return DUMP_STATE
            if name == "get_powerstat":
                return "1\n"
            cmd = _LONG.get(name, cmd)
        try:
            if cmd in ("q", "Q"):
                return None
            if cmd == "f":
                return f"{int(self.rig.get_freq() or 0)}\n"
            if cmd == "F":
                self.rig.set_freq(int(float(args[0])))
                return RPRT_OK
            if cmd == "m":
                return f"{self.rig.get_mode()}\n3000\n"
            if cmd == "M":
                self.rig.set_mode(args[0])
                return RPRT_OK
            if cmd == "t":
                return f"{1 if self.rig.get_ptt() else 0}\n"
            if cmd == "T":
                self.rig.set_ptt(args[0] != "0")
                return RPRT_OK
            if cmd == "v":
                return "VFOA\n"
            if cmd == "V":
                return RPRT_OK
            if cmd == "s":
                return "0\nVFOA\n"
            if cmd == "S":
                return RPRT_OK if args[:1] == ["0"] else RPRT_NA
        except (IndexError, ValueError):
            return RPRT_ERR
        return RPRT_NA


# --- réglages de WSJT-X ---------------------------------------------------
WSJTX_INI = os.path.expanduser("~/.config/WSJT-X.ini")


def _enum_variant(type_name, key):
    """Valeur d'énumération WSJT-X telle que QSettings l'écrit (@Variant(...))."""
    t, k = type_name.encode(), key.encode()
    raw = (struct.pack(">I", 127) + struct.pack(">I", len(t) + 1) + t + b"\0"
           + struct.pack(">I", len(k) + 1) + k + b"\0")
    out, escape_next = [], False
    for b in raw:
        c = chr(b)
        if b == 0:
            out.append("\\0")
            escape_next = True
        elif b < 0x20 or b >= 0x7F or (escape_next and c in string.hexdigits):
            out.append(f"\\x{b:x}")
            escape_next = True
        else:
            out.append(c)
            escape_next = False
    return "@Variant(" + "".join(out) + ")"


def _set_keys(lines, name, forced, if_missing=None):
    """Dans la section [name] : impose `forced`, ajoute `if_missing` s'il manque."""
    header = f"[{name}]"
    if header not in lines:
        lines += ["", header] if lines else [header]
    start = lines.index(header) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    while end > start and not lines[end - 1].strip():
        end -= 1                        # les ajouts vont avant la ligne vide
    section = lines[start:end]
    present = {line.split("=", 1)[0]: i for i, line in enumerate(section) if "=" in line}
    for key, value in {**(if_missing or {}), **forced}.items():
        if key in present:
            if key in forced:
                section[present[key]] = f"{key}={value}"
        else:
            section.append(f"{key}={value}")
    lines[start:end] = section


def ensure_wsjtx_config(sound_in, sound_out, call="F4TXR", grid="JN33ps"):
    """Règle WSJT-X sur le pont du Scope (radio, émission, son) ; l'indicatif,
    le locator et le mode FT8 ne sont écrits que s'ils manquent."""
    try:
        with open(WSJTX_INI, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    first_ft8 = "FT8_ready=true" not in lines
    _set_keys(lines, "Configuration", {
        "Rig": "Hamlib NET rigctl",
        "CATNetworkPort": f"127.0.0.1:{PORT}",
        "PTTMethod": _enum_variant("TransceiverFactory::PTTMethod", "PTT_method_CAT"),
        "DataMode": _enum_variant("Configuration::DataMode", "data_mode_data"),
        "SplitMode": _enum_variant("TransceiverFactory::SplitMode", "split_mode_none"),
        "SoundInName": sound_in,
        "SoundOutName": sound_out,
    }, {"MyCall": call, "MyGrid": grid})
    if first_ft8:                       # une seule fois : ensuite, le choix de l'opérateur
        _set_keys(lines, "Common", {"Mode": "FT8"})
        _set_keys(lines, "Scope", {"FT8_ready": "true"})
    with open(WSJTX_INI, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
