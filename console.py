"""Console (terminal) gardée visible par-dessus Scope en plein écran.

Les terminaux GNOME passent en « toujours au-dessus » (X11, _NET_WM_STATE_ABOVE) :
ils restent visibles même quand on clique dans Scope. S'il n'y en a aucun,
on en ouvre un.
"""
import ctypes
import re
import subprocess

TERMINAL_CLASS = '("gnome-terminal-server" "Gnome-terminal")'


class _XClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5),
                ("pad", ctypes.c_long * 12)]


def terminal_windows():
    """Identifiants X des vraies fenêtres de terminal GNOME."""
    try:
        out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    wids = []
    for line in out.splitlines():
        if TERMINAL_CLASS in line:
            m = re.search(r"(0x[0-9a-f]+) .*?(\d+)x(\d+)\+", line)
            if m and int(m.group(2)) > 50 and int(m.group(3)) > 50:
                wids.append(int(m.group(1), 16))
    return wids


def claude_terminal():
    """Le terminal où tourne Claude (titre avec « Claude »), sinon le premier."""
    try:
        out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    wids = terminal_windows()
    for line in out.splitlines():
        if TERMINAL_CLASS in line and "claude" in line.lower():
            m = re.search(r"(0x[0-9a-f]+) ", line)
            if m and int(m.group(1), 16) in wids:
                return int(m.group(1), 16)
    return wids[0] if wids else None


def _send(wids, atom_name, data_fn):
    try:
        xlib = ctypes.cdll.LoadLibrary("libX11.so.6")
    except OSError:
        return False
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XDefaultRootWindow.restype = ctypes.c_ulong
    dpy = xlib.XOpenDisplay(None)
    if not dpy:
        return False
    dpy = ctypes.c_void_p(dpy)
    root = xlib.XDefaultRootWindow(dpy)
    mask = (1 << 19) | (1 << 20)                    # SubstructureNotify | Redirect
    for wid in wids:
        ev = _XClientMessage()
        ev.type = 33                                # ClientMessage
        ev.send_event = 1
        ev.window = wid
        ev.message_type = xlib.XInternAtom(dpy, atom_name, 0)
        ev.format = 32
        for i, v in enumerate(data_fn(xlib, dpy)):
            ev.data[i] = v
        xlib.XSendEvent(dpy, ctypes.c_ulong(root), 0, ctypes.c_long(mask),
                        ctypes.byref(ev))
    xlib.XFlush(dpy)
    xlib.XCloseDisplay(dpy)
    return True


def set_above(wids, above=True):
    """Met (ou enlève) les fenêtres en « toujours au-dessus »."""
    return _send(wids, b"_NET_WM_STATE", lambda x, d: (
        1 if above else 0, x.XInternAtom(d, b"_NET_WM_STATE_ABOVE", 0), 0, 1))


def activate(wid):
    return _send([wid], b"_NET_ACTIVE_WINDOW", lambda x, d: (2, 0))


# place de la console, en fraction de l'écran : en bas à droite du waterfall,
# sans cacher les mesures, le bouton VFO ni les rangées de boutons
PLACE = (0.60, 0.30, 0.39, 0.32)            # x, y, largeur, hauteur


def place(wid, screen_w, screen_h):
    """Déplace et redimensionne la fenêtre (demande au gestionnaire de fenêtres)."""
    x, y, w, h = (round(f * n) for f, n in zip(PLACE, (screen_w, screen_h,
                                                        screen_w, screen_h)))
    flags = 10 | (0xF << 8) | (2 << 12)     # gravité statique, x y l h, outil utilisateur
    return _send([wid], b"_NET_MOVERESIZE_WINDOW", lambda xl, d: (flags, x, y, w, h))


def show_console(screen=None):
    """Terminaux visibles par-dessus Scope ; en ouvre un si besoin.
    screen = (largeur, hauteur) : place aussi le terminal en bas à droite.
    Renvoie True si un terminal existait déjà."""
    wids = terminal_windows()
    if not wids:
        subprocess.Popen(["gnome-terminal"], start_new_session=True)
        return False
    set_above(wids, True)
    if screen:
        place(wids[0], *screen)
    activate(wids[0])
    return True


def hide_console():
    """Les terminaux repassent derrière Scope."""
    set_above(terminal_windows(), False)


# hauteur gardée fixe pour la console (pixels), retenue d'une session à l'autre
import json
import os
import time
HEIGHT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "console_hauteur.json")
DEFAULT_HEIGHT = 494


def fixed_height():
    try:
        with open(HEIGHT_FILE) as f:
            return int(json.load(f)["hauteur"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_HEIGHT


def _geometry(wid):
    """(largeur, hauteur, maximisée) de la fenêtre, ou None."""
    try:
        info = subprocess.run(["xwininfo", "-id", hex(wid)], capture_output=True,
                              text=True, timeout=2).stdout
        state = subprocess.run(["xprop", "-id", hex(wid), "_NET_WM_STATE"],
                               capture_output=True, text=True, timeout=2).stdout
        w = int(re.search(r"Width: (\d+)", info).group(1))
        h = int(re.search(r"Height: (\d+)", info).group(1))
    except (OSError, subprocess.TimeoutExpired, AttributeError):
        return None
    return w, h, "MAXIMIZED" in state


def keep_height():
    """Remet la console à sa hauteur fixe si elle a changé (ou a été agrandie)."""
    wids = terminal_windows()
    if not wids:
        return
    wid = wids[0]
    geo = _geometry(wid)
    if geo is None:
        return
    w, h, maxi = geo
    target = fixed_height()
    if not maxi and abs(h - target) <= 8:
        return
    if maxi:                                # sortir du plein écran d'abord
        _send([wid], b"_NET_WM_STATE", lambda x, d: (
            0, x.XInternAtom(d, b"_NET_WM_STATE_MAXIMIZED_VERT", 0),
            x.XInternAtom(d, b"_NET_WM_STATE_MAXIMIZED_HORZ", 0), 1))
        w = 520
    flags = 10 | (1 << 10) | (1 << 11) | (2 << 12)   # largeur + hauteur seulement
    asked = target
    for _ in range(3):              # la barre de titre décale un peu : on rattrape
        _send([wid], b"_NET_MOVERESIZE_WINDOW",
              lambda xl, d, a=asked: (flags, 0, 0, w, a))
        time.sleep(0.8)
        geo = _geometry(wid)
        if geo is None or abs(geo[1] - target) <= 4:
            return
        asked += target - geo[1]
