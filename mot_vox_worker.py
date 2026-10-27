"""Reconnaît un mot court dit au micro (Whisper « base », hors ligne).
Lancé avec le Python de ~/claude/whisper/venv. Reçoit sur l'entrée un chemin
de fichier son brut (s16le, 16 kHz, mono) par ligne ; répond une ligne JSON :
{"text": "Vox"}."""

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
            audio = np.fromfile(path, "<i2").astype(np.float32) / 32768
            peak = np.abs(audio).max()
            if peak > 0:
                audio *= 0.5 / peak
            pad = np.zeros(8000, np.float32)                # 0,5 s de silence autour
            audio = np.concatenate([pad, audio, pad])
            segs, _ = model.transcribe(audio, language="fr", beam_size=3,
                                       condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segs if s.no_speech_prob < 0.6)
            out = {"text": text}
        except Exception as e:                              # on répond toujours
            out = {"text": "", "error": str(e)}
        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
