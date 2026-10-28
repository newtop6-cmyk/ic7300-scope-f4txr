"""Surveille le fil principal du Scope (celui des boutons et du clavier).

blocages.log : si l'interface reste figée plus de 0,5 s, Python y écrit où en
était chaque fil (faulthandler, en C : ne garde aucune référence aux objets en
cours de dessin, contrairement à un échantillonneur en Python)."""

import faulthandler
import os
import time

from PyQt5 import QtCore

HERE = os.path.dirname(os.path.abspath(__file__))
STALL_S = 0.5


def start(parent):
    try:
        log = open(os.path.join(HERE, "blocages.log"), "a", buffering=1)
    except OSError:
        return
    log.write(time.strftime("=== %Y-%m-%d %H:%M:%S lancement du Scope\n"))
    parent._veille_log = log

    def beat():
        # réarmé toutes les 0,1 s ; s'il n'est pas réarmé à temps, le fil
        # principal est bloqué et la pile est écrite dans blocages.log
        faulthandler.dump_traceback_later(STALL_S, repeat=False, file=log)

    timer = QtCore.QTimer(parent)
    timer.timeout.connect(beat)
    timer.start(100)
    parent._veille_beat = timer


def profile(seconds=20):
    """Mesure de 20 s : où le fil principal passe son temps → profil.txt.
    Les piles sont lues par faulthandler (en C), sans risque pour les dessins."""
    import collections
    import tempfile
    import threading

    main_id = threading.main_thread().ident

    def run():
        own, leaf = collections.Counter(), collections.Counter()
        n = 0
        end = time.monotonic() + seconds
        with tempfile.TemporaryFile("w+") as tmp:
            while time.monotonic() < end:
                time.sleep(0.02)
                tmp.seek(0)
                tmp.truncate()
                faulthandler.dump_traceback(tmp, all_threads=True)
                tmp.seek(0)
                text = tmp.read()
                block = None
                for part in text.split("\n\n"):
                    if f"0x{main_id:016x}" in part:
                        block = part
                lines = [ln.strip() for ln in (block or "").splitlines()[1:]]
                if not lines:
                    continue
                n += 1
                leaf[lines[0]] += 1
                for ln in lines:
                    if HERE in ln and "in main" not in ln and "<module>" not in ln:
                        own[ln.replace(HERE + "/", "")] += 1
                        break
                else:
                    own["(attente / Qt)"] += 1
        out = [time.strftime("%H:%M:%S") + f"  {n} échantillons"]
        out += [f"{100 * c / n:5.1f} %  {k}" for k, c in own.most_common(30)]
        out.append("--- ligne en cours")
        out += [f"{100 * c / n:5.1f} %  {k}" for k, c in leaf.most_common(15)]
        try:
            with open(os.path.join(HERE, "profil.txt"), "w") as fh:
                fh.write("\n".join(out) + "\n")
        except OSError:
            pass

    threading.Thread(target=run, name="Profil", daemon=True).start()


try:
    from PyQt5 import QtWidgets

    class TimedApp(QtWidgets.QApplication):
        """Mesure (SCOPE_MESURE=1) : temps passé par type d'objet et d'événement,
        écrit dans mesure.txt toutes les 20 s."""

        def __init__(self, argv):
            super().__init__(argv)
            import collections
            self._t = collections.Counter()
            self._n = collections.Counter()
            self._start = time.monotonic()

        def notify(self, obj, ev):
            t = time.perf_counter()
            try:
                return super().notify(obj, ev)
            finally:
                key = f"{type(obj).__name__} / {int(ev.type())}"
                self._t[key] += time.perf_counter() - t
                self._n[key] += 1
                if time.monotonic() - self._start > 20:
                    span = time.monotonic() - self._start
                    lines = [f"{100 * v / span:5.1f} %  {self._n[k]:6d}×  {k}"
                             for k, v in self._t.most_common(30)]
                    with open(os.path.join(HERE, "mesure.txt"), "w") as fh:
                        fh.write("\n".join(lines) + "\n")
                    self._t.clear()
                    self._n.clear()
                    self._start = time.monotonic()
except ImportError:
    pass
