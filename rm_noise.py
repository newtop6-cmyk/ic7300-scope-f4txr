"""Filtre RM Noise (programme Windows, sous Wine) sur le son de la radio.

Marche : lance RM Noise s'il ne tourne pas, branche son entrée sur le son de la
radio et sa sortie sur les haut-parleurs, puis pousse son curseur
« filtered / original » tout en haut (100 % filtré).
Arrêt : ferme RM Noise."""

import ctypes
import os
import re
import subprocess
import time

WINEPREFIX = os.path.expanduser("~/.wine")
RMNOISE_DIR = r"C:\users\marco\AppData\Local\Programs\RM Noise"
TITLE = "RM Noise client"
ENV = {**os.environ, "WINEPREFIX": WINEPREFIX, "LC_ALL": "C"}
WHEEL_UP = 4                    # bouton X de la molette vers le haut
WHEEL_CLICKS = 60               # assez pour aller en butée


def running():
    out = subprocess.run(["pgrep", "-f", r"RM Noise\\rmnoise.exe"],
                         capture_output=True, text=True).stdout
    return bool(out.strip())


def launch():
    # « wine start » : RM Noise a besoin d'une vraie console Windows
    subprocess.Popen(["wine-stable", "start", "/d", RMNOISE_DIR, "rmnoise.exe"],
                     env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def stop():
    subprocess.run(["pkill", "-f", r"RM Noise\\rmnoise.exe"], capture_output=True)


def _streams(kind):
    """Indices des flux PulseAudio de RM Noise (source-outputs ou sink-inputs)."""
    out = subprocess.run(["pactl", "list", kind], capture_output=True, text=True,
                         env=ENV).stdout
    ids, current = [], None
    for line in out.splitlines():
        m = re.match(r"^\S.*#(\d+)", line)
        if m:
            current = m.group(1)
        elif "application.name" in line and "rmnoise" in line.lower() and current:
            ids.append(current)
    return ids


def route(source, sink):
    """Entrée de RM Noise = son de la radio ; sortie = haut-parleurs."""
    ins, outs = _streams("source-outputs"), _streams("sink-inputs")
    for i in ins:
        subprocess.run(["pactl", "move-source-output", i, source], capture_output=True)
    for i in outs:
        subprocess.run(["pactl", "move-sink-input", i, sink], capture_output=True)
    return bool(ins), bool(outs)


def set_levels(in_percent=None, out_percent=None, out_mute=None):
    """Volume d'entrée (son de la radio vers RM Noise), volume et coupure de
    sa sortie (vers les haut-parleurs). Renvoie True si RM Noise est branché."""
    ins, outs = _streams("source-outputs"), _streams("sink-inputs")
    if in_percent is not None:
        for i in ins:
            subprocess.run(["pactl", "set-source-output-volume", i, f"{round(in_percent)}%"],
                           capture_output=True)
    for i in outs:
        if out_percent is not None:
            subprocess.run(["pactl", "set-sink-input-volume", i, f"{round(out_percent)}%"],
                           capture_output=True)
        if out_mute is not None:
            subprocess.run(["pactl", "set-sink-input-mute", i, "1" if out_mute else "0"],
                           capture_output=True)
    return bool(ins and outs)


def window_geometry():
    """Identifiant X, position (x, y) et taille de la fenêtre RM Noise, ou None."""
    out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True,
                         text=True).stdout
    for line in out.splitlines():
        if TITLE in line:
            m = re.search(r"(0x[0-9a-f]+) .*?(\d+)x(\d+)\+-?\d+\+-?\d+\s+\+(-?\d+)\+(-?\d+)",
                          line)
            if m:
                wid = int(m.group(1), 16)
                w, h, x, y = map(int, m.groups()[1:])
                return wid, x, y, w, h
    return None


class _XClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5),
                ("pad", ctypes.c_long * 12)]


def _activate(xlib, dpy, wid):
    """Met la fenêtre au premier plan (demande au gestionnaire de fenêtres)."""
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XDefaultRootWindow.restype = ctypes.c_ulong
    root = xlib.XDefaultRootWindow(dpy)
    ev = _XClientMessage()
    ev.type = 33                                    # ClientMessage
    ev.send_event = 1
    ev.window = wid
    ev.message_type = xlib.XInternAtom(dpy, b"_NET_ACTIVE_WINDOW", 0)
    ev.format = 32
    ev.data[0] = 2                                  # demande d'un outil utilisateur
    ev.data[1] = 0
    mask = (1 << 19) | (1 << 20)                    # SubstructureNotify | Redirect
    xlib.XSendEvent(dpy, ctypes.c_ulong(root), 0, ctypes.c_long(mask), ctypes.byref(ev))
    xlib.XRaiseWindow(dpy, ctypes.c_ulong(wid))
    xlib.XFlush(dpy)
    time.sleep(0.4)


def slider_full():
    """Pousse le curseur « filtered / original » tout en haut (souris simulée)."""
    geo = window_geometry()
    if not geo:
        return False
    wid, x, y, w, h = geo
    try:
        xlib = ctypes.cdll.LoadLibrary("libX11.so.6")
        xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
    except OSError:
        return False
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    dpy = xlib.XOpenDisplay(None)
    if not dpy:
        return False
    dpy = ctypes.c_void_p(dpy)
    _activate(xlib, dpy, wid)

    def move(px, py):
        xtst.XTestFakeMotionEvent(dpy, -1, int(px), int(py), 0)
        xlib.XFlush(dpy)
        time.sleep(0.05)

    def button(down):
        xtst.XTestFakeButtonEvent(dpy, 1, down, 0)
        xlib.XFlush(dpy)
        time.sleep(0.05)

    # curseur vertical « filtered / original » à gauche du graphique
    # (~49 px du bord) : RM Noise le règle à la molette ; on tourne vers
    # « filtered » jusqu'en butée
    move(x + 49, y + int(h * 0.53))
    for _ in range(WHEEL_CLICKS):
        xtst.XTestFakeButtonEvent(dpy, WHEEL_UP, 1, 0)
        xtst.XTestFakeButtonEvent(dpy, WHEEL_UP, 0, 0)
        xlib.XFlush(dpy)
        time.sleep(0.02)
    xlib.XCloseDisplay(dpy)
    return True
