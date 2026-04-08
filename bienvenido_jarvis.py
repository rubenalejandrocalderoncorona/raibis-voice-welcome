#!/usr/bin/env python3
"""
Double-clap welcome script — Jarvis edition.

Modes:
  - Clap mode:   2 claps → Jarvis voice greeting → opens YouTube in Chrome
  - Voice mode:  say "Raibis" → "How can I help you, sir?" → say "change language"
                 → toggles greeting language between Spanish and English

Dependencies:
    pip install sounddevice numpy vosk
    Download model: https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    Unzip next to this script as: vosk-model-small-en-us-0.15/

Usage:
    python bienvenido_jarvis.py
"""

import json
import os
import queue
import random
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model

# ──────────────────────────────────────────────────────────────────────────────
#  Configuración
# ──────────────────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 16000         # vosk works best at 16 kHz
BLOCK_SIZE    = int(SAMPLE_RATE * 0.05)
THRESHOLD     = 0.10          # RMS clap threshold — lower = more sensitive
COOLDOWN      = 0.4           # seconds between accepted claps
DOUBLE_WINDOW = 2.0           # window to catch the second clap

YOUTUBE_URL   = "https://youtu.be/pAgnJDJN4VA?si=wcRu25cvV6OqouRY&t=5"

VOSK_MODEL    = os.path.join(os.path.dirname(__file__), "vosk-model-small-en-us-0.15")

# Jarvis voice — British male via macOS 'say'
JARVIS_VOICE  = "Daniel"      # en_GB — change to "Reed (English (UK))" etc. if preferred
JARVIS_RATE   = 165           # words per minute (Jarvis-style: measured, not rushed)

SPANISH_VOICE = "Mónica"      # es_ES

# ──────────────────────────────────────────────────────────────────────────────
#  Greetings (both languages)
# ──────────────────────────────────────────────────────────────────────────────
MENSAJES_ES = [
    "Bienvenido a casa, señor Rubix.",
    "Bienvenido a casa, Patronzote.",
    "Bienvenido a casa, señor Rubius.",
]

MENSAJES_EN = [
    "Welcome back, sir.",
    "It is good to be back, sir.",
    "Welcome back, boss.",
]

# ──────────────────────────────────────────────────────────────────────────────
#  State
# ──────────────────────────────────────────────────────────────────────────────
clap_times: list[float] = []
clap_triggered  = False
clap_lock       = threading.Lock()

lang            = "es"        # current greeting language: "es" or "en"
lang_lock       = threading.Lock()

voice_queue: queue.Queue = queue.Queue()   # raw audio chunks → vosk thread
listening_for_command = False              # True while waiting for "change language"


# ──────────────────────────────────────────────────────────────────────────────
#  TTS helpers
# ──────────────────────────────────────────────────────────────────────────────
def hablar_jarvis(texto: str):
    """British male Jarvis voice."""
    print(f"  [Jarvis] '{texto}'")
    r = subprocess.run(["say", "-v", JARVIS_VOICE, "-r", str(JARVIS_RATE), texto],
                       capture_output=True)
    if r.returncode != 0:
        subprocess.run(["say", "-r", str(JARVIS_RATE), texto], capture_output=True)


def hablar_espanol(texto: str):
    """Native Spanish voice."""
    print(f"  [Español] '{texto}'")
    fallbacks = ["Paulina", "Rocko (Spanish (Spain))", "Reed (Spanish (Spain))"]
    r = subprocess.run(["say", "-v", SPANISH_VOICE, texto], capture_output=True)
    if r.returncode == 0:
        return
    for voz in fallbacks:
        r = subprocess.run(["say", "-v", voz, texto], capture_output=True)
        if r.returncode == 0:
            return
    subprocess.run(["say", texto], capture_output=True)


def hablar_bienvenida():
    """Speak greeting in the current language."""
    with lang_lock:
        current = lang
    if current == "es":
        hablar_espanol(random.choice(MENSAJES_ES))
    else:
        hablar_jarvis(random.choice(MENSAJES_EN))


# ──────────────────────────────────────────────────────────────────────────────
#  Clap detection
# ──────────────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    global clap_triggered, clap_times

    # Feed raw audio to vosk regardless of clap state
    voice_queue.put(bytes(indata))

    if clap_triggered:
        return

    # Upsample check: vosk uses 16kHz mono int16; indata is float32 — use RMS only
    rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
    now = time.time()

    if rms > THRESHOLD:
        with clap_lock:
            if clap_times and (now - clap_times[-1]) < COOLDOWN:
                return
            clap_times.append(now)
            clap_times = [t for t in clap_times if now - t <= DOUBLE_WINDOW]
            count = len(clap_times)
            print(f"  Aplauso {count}/2  (RMS={rms:.3f})")
            if count >= 2:
                clap_triggered = True
                clap_times = []
                threading.Thread(target=secuencia_bienvenida, daemon=True).start()


# ──────────────────────────────────────────────────────────────────────────────
#  Welcome sequence (clap trigger)
# ──────────────────────────────────────────────────────────────────────────────
def secuencia_bienvenida():
    global clap_triggered
    print("\n  Iniciando secuencia de bienvenida...\n")
    hablar_bienvenida()
    abrir_youtube()
    print("\n  Secuencia completada.\n")


def abrir_youtube():
    print("  Opening YouTube in Chrome...")
    subprocess.Popen(["open", "-a", "Google Chrome", YOUTUBE_URL])
    time.sleep(1.2)


# ──────────────────────────────────────────────────────────────────────────────
#  Voice command thread (vosk wake-word + dialog)
# ──────────────────────────────────────────────────────────────────────────────
def voice_thread(model: Model):
    """
    Listens continuously. Wake word: 'raibis'.
    After wake: asks how to help, waits for 'change language'.
    """
    global listening_for_command, lang

    rec = KaldiRecognizer(model, SAMPLE_RATE)
    # Restrict vocabulary to speed up detection and reduce false positives
    rec_wake = KaldiRecognizer(model, SAMPLE_RATE,
                               '["raibis", "ray bis", "rabis", "[unk]"]')
    rec_cmd  = KaldiRecognizer(model, SAMPLE_RATE,
                               '["change language", "change", "language", "[unk]"]')

    state = "wake"   # "wake" | "command"

    print("  [Voice] Listening for 'Raibis'...")

    while True:
        try:
            chunk = voice_queue.get(timeout=1)
        except queue.Empty:
            continue

        if state == "wake":
            if rec_wake.AcceptWaveform(chunk):
                result = json.loads(rec_wake.Result())
                text = result.get("text", "").lower()
                if any(w in text for w in ["raibis", "ray bis", "rabis"]):
                    print(f"  [Voice] Wake word detected: '{text}'")
                    threading.Thread(
                        target=lambda: hablar_jarvis("How can I help you, sir?"),
                        daemon=True
                    ).start()
                    state = "command"
                    # drain stale audio
                    while not voice_queue.empty():
                        voice_queue.get_nowait()
                    rec_cmd = KaldiRecognizer(model, SAMPLE_RATE,
                                             '["change language", "change", "language", "[unk]"]')

        elif state == "command":
            if rec_cmd.AcceptWaveform(chunk):
                result = json.loads(rec_cmd.Result())
                text = result.get("text", "").lower()
                print(f"  [Voice] Heard: '{text}'")
                if "change" in text or "language" in text:
                    threading.Thread(target=handle_change_language, daemon=True).start()
                else:
                    hablar_jarvis("I did not catch that, sir.")
                state = "wake"
                # reset wake recognizer
                rec_wake = KaldiRecognizer(model, SAMPLE_RATE,
                                           '["raibis", "ray bis", "rabis", "[unk]"]')


def handle_change_language():
    global lang
    with lang_lock:
        lang = "en" if lang == "es" else "es"
        new_lang = lang
    label = "English" if new_lang == "en" else "Spanish"
    print(f"  [Voice] Language switched to: {label}")
    hablar_jarvis(f"Switching greetings to {label}, sir.")


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    global clap_triggered

    # Load vosk model
    if not os.path.isdir(VOSK_MODEL):
        print(f"\n  ERROR: Vosk model not found at: {VOSK_MODEL}")
        print("  Download it with:")
        print("    curl -L -o model.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip")
        print("    unzip model.zip")
        sys.exit(1)

    import vosk
    vosk.SetLogLevel(-1)   # silence vosk logs
    model = Model(VOSK_MODEL)

    # Start voice thread
    t = threading.Thread(target=voice_thread, args=(model,), daemon=True)
    t.start()

    print("=" * 55)
    print("  Escuchando aplausos y comandos de voz...")
    print(f"  Wake word: 'Raibis'  |  Threshold: {THRESHOLD}")
    print(f"  Greeting language: {'Spanish' if lang == 'es' else 'English'}")
    print("  Ctrl+C to exit")
    print("=" * 55)

    try:
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="int16",
            callback=audio_callback,
        ):
            while True:
                time.sleep(0.1)
                if clap_triggered:
                    time.sleep(8)
                    clap_triggered = False
                    print("\n  Escuchando de nuevo...\n")
    except KeyboardInterrupt:
        print("\n\nHasta luego!")
        sys.exit(0)


if __name__ == "__main__":
    main()
