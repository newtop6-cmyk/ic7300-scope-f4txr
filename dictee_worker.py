"""Transcription des dictées (Whisper « small », hors ligne), guidée par le
vocabulaire radio de l'utilisateur. Lancé avec le Python de ~/claude/whisper/venv.
Entrée : une ligne JSON {"path": son brut s16le 16 kHz mono, "prompt": texte}.
Sortie : une ligne JSON {"text": "..."}. S'arrête seul après 5 min sans travail."""

import json
import os
import select
import sys

import numpy as np
from faster_whisper import WhisperModel

MODEL_DIR = os.path.expanduser("~/claude/whisper/models/whisper")
IDLE_S = 300


def main():
    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=6,
                         download_root=MODEL_DIR)
    print(json.dumps({"ready": True}), flush=True)
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], IDLE_S)
        if not ready:
            return                                  # libère la mémoire
        line = sys.stdin.readline()
        if not line:
            return
        try:
            job = json.loads(line)
            audio = np.fromfile(job["path"], "<i2").astype(np.float32) / 32768
            peak = np.abs(audio).max()
            if peak > 0:
                audio *= 0.6 / peak
            segs, _ = model.transcribe(audio, language="fr", beam_size=5,
                                       initial_prompt=job.get("prompt") or None,
                                       condition_on_previous_text=False,
                                       vad_filter=True)
            text = " ".join(s.text.strip() for s in segs if s.no_speech_prob < 0.7)
            out = {"text": text}
        except Exception as e:                      # on répond toujours
            out = {"text": "", "error": str(e)}
        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
