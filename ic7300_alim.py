#!/usr/bin/env python3
"""Allume ou éteint l'IC-7300 branché sur le Raspberry Pi (via cat_server.py).

Usage : ic7300_alim.py marche|arret [hôte]
Le Pi n'accepte qu'une connexion à la fois : fermer IC-7300 Scope avant.
"""
import socket
import subprocess
import sys
import time

HOTE = "100.76.125.118"         # Raspberry Pi (Tailscale)
PORT = 7300
ADR = 0x94                      # adresse CI-V de l'IC-7300


def commande(sub):
    return bytes([0xFE, 0xFE, ADR, 0xE0, 0x18, sub, 0xFD])


def lire_frequence(s):
    """Renvoie la fréquence en Hz, ou None si la radio ne répond pas."""
    s.sendall(bytes([0xFE, 0xFE, ADR, 0xE0, 0x03, 0xFD]))
    fin = time.time() + 1.5
    data = b""
    while time.time() < fin:
        try:
            data += s.recv(512)
        except socket.timeout:
            pass
        i = data.find(bytes([0xFE, 0xFE, 0xE0, ADR, 0x03]))
        if i >= 0 and len(data) >= i + 11:
            f = 0
            for k, x in enumerate(data[i + 5:i + 10]):
                f += ((x >> 4) * 10 + (x & 15)) * 10 ** (2 * k)
            return f
    return None


def message(texte):
    print(texte)
    subprocess.run(["notify-send", "IC-7300", texte], check=False)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("marche", "arret"):
        sys.exit(__doc__)
    hote = sys.argv[2] if len(sys.argv) > 2 else HOTE
    try:
        s = socket.create_connection((hote, PORT), timeout=5)
    except OSError as e:
        message(f"Pi injoignable ({e}). Tailscale est-il connecté ?")
        sys.exit(1)
    s.settimeout(0.3)
    with s:
        # Ne rien faire si IC-7300 Scope occupe déjà la connexion
        try:
            s.sendall(bytes([0xFE, 0xFE, ADR, 0xE0, 0x03, 0xFD]))
        except OSError:
            pass
        if sys.argv[1] == "marche":
            # Réveil : une suite de FE (environ 150 à 115200 bauds), puis la commande
            s.sendall(bytes([0xFE] * 150) + commande(0x01))
            message("Allumage envoyé, patiente quelques secondes…")
            for _ in range(8):
                time.sleep(1.5)
                f = lire_frequence(s)
                if f:
                    message(f"IC-7300 allumé : {f / 1e6:.4f} MHz")
                    return
            message("L'IC-7300 ne répond pas encore. Réessaie dans un instant.")
        else:
            s.sendall(commande(0x00))
            time.sleep(4)
            try:                    # vider ce que la radio a envoyé avant l'arrêt
                while s.recv(4096):
                    pass
            except OSError:
                pass
            if lire_frequence(s) is None:
                message("IC-7300 éteint.")
            else:
                message("L'IC-7300 répond encore : extinction non confirmée.")


if __name__ == "__main__":
    main()
