#!/usr/bin/env python3
"""Envoie une commande au Scope qui tourne : python3 scope_cmd.py egaliseur
(egaliseur, proprete, mobile, fixe, console)."""
import glob
import socket
import sys

paths = glob.glob("/tmp/ic7300-scope-commandes") + glob.glob("/tmp/*/ic7300-scope-commandes")
if not paths:
    sys.exit("Scope pas lancé (pas de porte de commande)")
s = socket.socket(socket.AF_UNIX)
s.settimeout(3)
s.connect(paths[0])
s.sendall((" ".join(sys.argv[1:]) + "\n").encode())
print(s.recv(100).decode().strip())
