"""Reconnaît la langue parlée (Whisper « base », hors ligne) pour la recherche
de QSO. Lancé avec le Python de ~/claude/whisper/venv. Reçoit sur l'entrée un
chemin de fichier son brut (s16le, 48 kHz, mono) par ligne ; répond une ligne
JSON : {"lang": "fr", "prob": 0.93, "text": "…"}."""

import json
import os
import sys

import numpy as np
from faster_whisper import WhisperModel

MODEL_DIR = os.path.expanduser("~/claude/whisper/models")


def main():
    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4,
                         download_root=os.path.join(MODEL_DIR, "whisper"))
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        path = line.strip()
        try:
            x = np.fromfile(path, "<i2").astype(np.float32) / 32768
            audio = x[::3].copy()                      # 48 kHz → 16 kHz
            peak = np.abs(audio).max()
            if peak > 0:
                audio *= 0.5 / peak
            segs, info = model.transcribe(audio, beam_size=1, vad_filter=True,
                                          condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segs
                            if s.no_speech_prob < 0.7 and s.avg_logprob > -1.2)
            out = {"lang": info.language, "prob": round(info.language_probability, 2),
                   "text": text}
        except Exception as e:                         # on répond toujours
            out = {"lang": None, "prob": 0.0, "text": "", "error": str(e)}
        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
