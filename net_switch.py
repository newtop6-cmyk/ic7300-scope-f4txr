"""Commutateur réseau INT / EXT : par où passe Internet.
INT = la box de la maison (Wi-Fi, ou prise Ethernet s'il y en a une) ;
EXT = le téléphone GSM branché en USB (partage de connexion).
On change seulement la priorité des routes (métrique) à chaud, avec nmcli :
rien n'est modifié dans les réglages enregistrés du PC. Tailscale (Pi,
radio) suit tout seul la nouvelle route."""

import subprocess

GOOD, BAD = 50, 700         # métriques : petite = route choisie


def _devices():
    """(interfaces de la maison, interfaces du téléphone) connectées."""
    out = subprocess.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"],
                         capture_output=True, text=True).stdout
    home, phone = [], []
    for line in out.splitlines():
        dev, typ, state = (line.split(":") + ["", "", ""])[:3]
        if not state.startswith("connect") or "externally" in state:
            continue
        if typ == "wifi":
            home.append(dev)
        elif typ == "ethernet":
            # le téléphone en USB : enx… / usb… (pilote rndis / cdc) ; sinon vraie prise
            (phone if dev.startswith(("enx", "usb")) else home).append(dev)
        elif typ in ("gsm", "wwan"):
            phone.append(dev)
    return home, phone


def _metric(dev):
    out = subprocess.run(["ip", "route", "show", "default", "dev", dev],
                         capture_output=True, text=True).stdout
    for word, value in zip(out.split(), out.split()[1:]):
        if word == "metric":
            return int(value)
    return None


def current():
    """« INT », « EXT », ou None si une seule voie (ou aucune) est là."""
    home, phone = _devices()
    best = None
    for dev in home + phone:
        m = _metric(dev)
        if m is not None and (best is None or m < best[0]):
            best = (m, dev)
    if best is None:
        return None
    return "EXT" if best[1] in phone else "INT"


def available():
    home, phone = _devices()
    return bool(home), bool(phone)


def set_mode(mode):
    """Bascule Internet sur INT ou EXT. Renvoie (ok, message)."""
    home, phone = _devices()
    want, other = (home, phone) if mode == "INT" else (phone, home)
    if not want:
        return False, ("pas de réseau de la maison" if mode == "INT"
                       else "téléphone GSM non branché en USB")
    for devs, metric in ((want, GOOD), (other, BAD)):
        for dev in devs:
            r = subprocess.run(["nmcli", "device", "modify", dev,
                                "ipv4.route-metric", str(metric),
                                "ipv6.route-metric", str(metric)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                return False, r.stderr.strip() or r.stdout.strip()
    return True, f"Internet par {'la maison' if mode == 'INT' else 'le GSM (USB)'}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(set_mode(sys.argv[1].upper()))
    print("actuel :", current(), "| disponibles (maison, GSM) :", available())
