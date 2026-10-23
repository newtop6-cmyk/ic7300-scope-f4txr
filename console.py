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
