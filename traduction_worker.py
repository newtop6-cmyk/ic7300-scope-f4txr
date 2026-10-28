"""Traduction en direct pour le bouton TRADUCTION du Scope (hors ligne).
Lancé avec le Python de ~/claude/whisper/venv ; réutilise le moteur de
~/claude/whisper/traducteur.py (Whisper + modèles Argos xx → en → fr).
Entrée : un chemin de son brut (float32, 16 kHz, mono) par ligne.
Sortie : une ligne JSON {"lang", "prob", "text", "fr"} (ou {} si rien)."""

import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/claude/whisper"))

import numpy as np                                  # noqa: E402
from traducteur import NOMS, Traducteur            # noqa: E402


def main():
    tr = Traducteur()
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        path = line.strip()
        try:
            audio = np.fromfile(path, dtype=np.float32)
            res = tr.traiter(audio, None)
            if res:
                lang, prob, text, fr = res
                out = {"lang": lang, "name": NOMS.get(lang, lang), "prob": round(prob, 2),
                       "text": text, "fr": fr}
            else:
                out = {}
        except Exception as e:                       # on répond toujours
            out = {"error": str(e)}
        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
