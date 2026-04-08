#!/usr/bin/env python3
"""
Double-clap welcome script for Señor Rubix / Patronzote / Señor Rubius.

Detects 2 claps → Spanish voice says welcome (random) → opens YouTube in Chrome.

Dependencies:
    pip install sounddevice numpy

Usage:
    python bienvenido_jarvis.py
"""

import sys
import time
import random
import threading
import subprocess

import numpy as np
import sounddevice as sd

# ──────────────────────────────────────────────────────────────────────────────
#  Configuración
# ──────────────────────────────────────────────────────────────────────────────
SAMPLE_RATE    = 44100
BLOCK_SIZE     = int(SAMPLE_RATE * 0.05)   # 50 ms per block
THRESHOLD      = 0.10     # Minimum RMS to count as a clap  ← adjust if failing
COOLDOWN       = 0.4      # Minimum seconds between claps (single clap burst ~200-300ms)
DOUBLE_WINDOW  = 2.0      # Time window to detect second clap

YOUTUBE_URL    = "https://www.youtube.com/watch?v=pAgnJDJN4VA&list=RDpAgnJDJN4VA&start_radio=1"

# macOS Spanish voices — ranked by preference (native speakers, no API needed)
# Change SPANISH_VOICE to any voice from: say -v '?' | grep es_
SPANISH_VOICE  = "Mónica"   # es_ES — clear Castilian Spanish

# Shuffle greetings — add or change these freely
MENSAJES = [
    "Bienvenido a casa, señor Rubix.",
    "Bienvenido a casa, Patronzote.",
    "Bienvenido a casa, señor Rubius.",
]

# ──────────────────────────────────────────────────────────────────────────────
#  Global state
# ──────────────────────────────────────────────────────────────────────────────
clap_times: list[float] = []
triggered = False
lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────────
#  Clap detection
# ──────────────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    global triggered, clap_times

    if triggered:
        return

    rms = float(np.sqrt(np.mean(indata ** 2)))
    now = time.time()

    if rms > THRESHOLD:
        with lock:
            # Ignore if within cooldown of previous clap
            if clap_times and (now - clap_times[-1]) < COOLDOWN:
                return

            clap_times.append(now)
            # Clean up claps outside the detection window
            clap_times = [t for t in clap_times if now - t <= DOUBLE_WINDOW]

            count = len(clap_times)
            print(f"  Aplauso {count}/2  (RMS={rms:.3f})")

            if count >= 2:
                triggered = True
                clap_times = []
                threading.Thread(target=secuencia_bienvenida, daemon=True).start()


# ──────────────────────────────────────────────────────────────────────────────
#  Welcome sequence
# ──────────────────────────────────────────────────────────────────────────────
def secuencia_bienvenida():
    print("\n  Iniciando secuencia de bienvenida...\n")

    mensaje = random.choice(MENSAJES)
    hablar(mensaje)
    abrir_youtube()

    print("\n  Secuencia completada.\n")


def hablar(texto: str):
    """TTS using macOS native Spanish voices via the 'say' command."""
    print(f"  Diciendo: '{texto}'")

    # Try preferred Spanish voice first
    resultado = subprocess.run(["say", "-v", SPANISH_VOICE, texto], capture_output=True)
    if resultado.returncode == 0:
        return

    # Fallback: any available Spanish voice
    fallbacks = ["Paulina", "Rocko (Spanish (Spain))", "Reed (Spanish (Spain))"]
    for voz in fallbacks:
        r = subprocess.run(["say", "-v", voz, texto], capture_output=True)
        if r.returncode == 0:
            print(f"     Fallback voice used: {voz}")
            return

    # Last resort: default system voice
    print("     Warning: no Spanish voice found, using system default")
    subprocess.run(["say", texto], capture_output=True)


def abrir_youtube():
    print("  Opening YouTube in Chrome...")
    subprocess.Popen(["open", "-a", "Google Chrome", YOUTUBE_URL])
    time.sleep(1.2)


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    global triggered

    print("=" * 55)
    print("  Escuchando aplausos... (Ctrl+C to exit)")
    print(f"  Current threshold: {THRESHOLD}  (adjust THRESHOLD if failing)")
    print("=" * 55)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        ):
            while True:
                time.sleep(0.1)
                if triggered:
                    time.sleep(8)
                    triggered = False
                    print("\n  Escuchando de nuevo...\n")
    except KeyboardInterrupt:
        print("\n\nHasta luego!")
        sys.exit(0)


if __name__ == "__main__":
    main()
