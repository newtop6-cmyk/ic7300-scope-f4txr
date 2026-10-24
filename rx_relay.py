#!/usr/bin/env python3
"""Son reçu de la radio (Pi) → PC par SSH, à retard borné.

    rx_relay.py HÔTE SOURCE_PI SORTIE_PC

pw-record lit la carte son de la radio sur le Pi, le flux arrive par SSH et
part dans pacat vers une sortie locale du PC. Si du retard s'accumule dans le
tuyau (réseau en rafales, horloges du Pi et du PC légèrement différentes), le
surplus est jeté : le son reste à environ 0,1 s de la radio au lieu de dériver
de plusieurs secondes comme l'ancien tunnel PipeWire.
"""

import fcntl
import os
import struct
import subprocess
import sys
import termios

RATE = 16000
BYTES_PER_S = RATE * 2              # s16 mono
CHUNK = BYTES_PER_S // 100          # 10 ms
MAX_BACKLOG = BYTES_PER_S * 15 // 100   # au-delà de 150 ms en attente…
KEEP = BYTES_PER_S * 5 // 100           # …on ne garde que les 50 dernières ms


def queued(fd):
    """Octets déjà arrivés dans le tuyau et pas encore lus."""
    buf = fcntl.ioctl(fd, termios.FIONREAD, b"\0\0\0\0")
    return struct.unpack("i", buf)[0]


def main():
    host, pi_source, pc_sink = sys.argv[1:4]
    ssh = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
         "-o", "ServerAliveInterval=5", f"marco@{host}",
         f"exec stdbuf -o0 pw-record --raw --target {pi_source} --rate {RATE} --channels 1 "
         f"--format s16 --latency 20ms -"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pacat = subprocess.Popen(
        ["pacat", "--playback", f"--device={pc_sink}", "--raw", "--format=s16le",
         f"--rate={RATE}", "--channels=1", "--latency-msec=60",
         "--client-name=IC-7300 reception", "--stream-name=IC-7300 reception"],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fd = ssh.stdout.fileno()
    carry = b""                     # octet seul en attente : jamais couper un échantillon
    try:
        while True:
            backlog = queued(fd)
            if backlog > MAX_BACKLOG:
                drop = (backlog - KEEP) // 2 * 2        # échantillons entiers
                while drop > 0:
                    got = os.read(fd, min(drop, 65536))
                    if not got:
                        return
                    drop -= len(got)
            data = os.read(fd, CHUNK)
            if not data:
                return                                  # SSH fermé
            data = carry + data
            if len(data) % 2:
                carry, data = data[-1:], data[:-1]
            else:
                carry = b""
            pacat.stdin.write(data)
            pacat.stdin.flush()
    except (BrokenPipeError, OSError, KeyboardInterrupt):
        pass
    finally:
        for proc in (ssh, pacat):
            try:
                proc.terminate()
            except OSError:
                pass


if __name__ == "__main__":
    main()
