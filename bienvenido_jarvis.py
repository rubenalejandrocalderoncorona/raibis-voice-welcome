#!/usr/bin/env python3
"""
Double-clap welcome script — Jarvis edition.

Workflow:
  1. Script starts (asks headphone mode once, persists choice)
  2. Two claps → opens YouTube in Chrome + speaks greeting in current language
  3. Say "Raibis" anytime → Jarvis replies "How can I help you, sir?"
     - Say "change language" → toggles greeting language (persisted to disk)
     - Say "goodbye"         → Jarvis says goodbye and exits

Dependencies:
    pip install sounddevice numpy vosk

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
#  Threshold profiles
#  Headphones: mic picks up less ambient sound → lower threshold needed
#  No headphones: more ambient noise → higher threshold to avoid false triggers
# ──────────────────────────────────────────────────────────────────────────────
THRESHOLD_HEADPHONES    = 0.08
THRESHOLD_NO_HEADPHONES = 0.18

SAMPLE_RATE   = 16000
BLOCK_SIZE    = int(SAMPLE_RATE * 0.05)   # 50ms blocks
COOLDOWN      = 0.5    # min seconds between two accepted claps
DOUBLE_WINDOW = 2.0    # max seconds between clap 1 and clap 2

YOUTUBE_URL   = "https://youtu.be/pAgnJDJN4VA?si=wcRu25cvV6OqouRY&t=5"

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
VOSK_MODEL    = os.path.join(SCRIPT_DIR, "vosk-model-small-en-us-0.15")
LANG_FILE     = os.path.join(SCRIPT_DIR, ".lang")
MODE_FILE     = os.path.join(SCRIPT_DIR, ".audiomode")  # persists headphone choice

# English voice — Daniel (en_GB), deep calm British male
JARVIS_VOICE  = "Daniel"
JARVIS_RATE   = 170

# Spanish voice — Rocko (Mexican Spanish), lighter male tone
SPANISH_VOICE = "Rocko (Spanish (Mexico))"

# ──────────────────────────────────────────────────────────────────────────────
#  Greetings
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
#  Persistent settings
# ──────────────────────────────────────────────────────────────────────────────
def load_lang() -> str:
    if os.path.isfile(LANG_FILE):
        val = open(LANG_FILE).read().strip()
        if val in ("es", "en"):
            return val
    return "es"


def save_lang(value: str):
    with open(LANG_FILE, "w") as f:
        f.write(value)


def load_audiomode() -> str | None:
    """Returns 'headphones' | 'speakers' | None if not set yet."""
    if os.path.isfile(MODE_FILE):
        val = open(MODE_FILE).read().strip()
        if val in ("headphones", "speakers"):
            return val
    return None


def save_audiomode(value: str):
    with open(MODE_FILE, "w") as f:
        f.write(value)


def ask_audiomode() -> str:
    """Ask once on first run. Persists the answer."""
    print("\n" + "=" * 55)
    print("  First-time setup: audio mode")
    print("  Are you using headphones or speakers?")
    print("  [1] Headphones")
    print("  [2] Speakers / no headphones")
    print("=" * 55)
    while True:
        choice = input("  Enter 1 or 2: ").strip()
        if choice == "1":
            save_audiomode("headphones")
            return "headphones"
        elif choice == "2":
            save_audiomode("speakers")
            return "speakers"
        print("  Please enter 1 or 2.")


# ──────────────────────────────────────────────────────────────────────────────
#  State
# ──────────────────────────────────────────────────────────────────────────────
clap_times: list[float] = []
clap_lock       = threading.Lock()
# Use a lock-protected flag instead of a plain bool to prevent race conditions
_clap_triggered = False
_clap_trigger_lock = threading.Lock()

lang      = load_lang()
lang_lock = threading.Lock()

voice_queue: queue.Queue = queue.Queue()
voice_paused   = False          # True while clap sequence is running
shutdown_event = threading.Event()

THRESHOLD = THRESHOLD_NO_HEADPHONES  # set properly in main()


def is_triggered() -> bool:
    with _clap_trigger_lock:
        return _clap_triggered


def set_triggered(val: bool):
    global _clap_triggered
    with _clap_trigger_lock:
        _clap_triggered = val


# ──────────────────────────────────────────────────────────────────────────────
#  TTS helpers
# ──────────────────────────────────────────────────────────────────────────────
def hablar_jarvis(texto: str):
    print(f"  [Jarvis] '{texto}'")
    r = subprocess.run(["say", "-v", JARVIS_VOICE, "-r", str(JARVIS_RATE), texto],
                       capture_output=True)
    if r.returncode != 0:
        subprocess.run(["say", "-r", str(JARVIS_RATE), texto], capture_output=True)


def hablar_espanol(texto: str):
    print(f"  [Español] '{texto}'")
    r = subprocess.run(["say", "-v", SPANISH_VOICE, texto], capture_output=True)
    if r.returncode == 0:
        return
    for voz in ["Reed (Spanish (Spain))", "Eddy (Spanish (Spain))"]:
        r = subprocess.run(["say", "-v", voz, texto], capture_output=True)
        if r.returncode == 0:
            return
    subprocess.run(["say", texto], capture_output=True)


def hablar_bienvenida():
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
    global voice_paused, clap_times

    raw = bytes(indata)

    # Only feed audio to vosk when not in a clap sequence
    if not voice_paused:
        voice_queue.put(raw)

    if is_triggered():
        return

    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(pcm ** 2)))
    now = time.time()

    if rms > THRESHOLD:
        with clap_lock:
            # Ignore if within cooldown of previous clap
            if clap_times and (now - clap_times[-1]) < COOLDOWN:
                return
            clap_times.append(now)
            # Drop claps outside the detection window
            clap_times = [t for t in clap_times if now - t <= DOUBLE_WINDOW]
            count = len(clap_times)
            print(f"  Aplauso {count}/2  (RMS={rms:.3f})")

            if count >= 2:
                # Atomically claim the trigger — prevents double-fire
                with _clap_trigger_lock:
                    global _clap_triggered
                    if _clap_triggered:
                        return   # already claimed by another callback
                    _clap_triggered = True
                clap_times = []
                threading.Thread(target=secuencia_bienvenida, daemon=True).start()


# ──────────────────────────────────────────────────────────────────────────────
#  Welcome sequence
# ──────────────────────────────────────────────────────────────────────────────
def secuencia_bienvenida():
    global voice_paused
    print("\n  Iniciando secuencia de bienvenida...\n")

    # Pause voice recognition so clap audio doesn't confuse vosk
    voice_paused = True
    # Drain any queued audio from the clap burst
    while not voice_queue.empty():
        try:
            voice_queue.get_nowait()
        except queue.Empty:
            break

    abrir_youtube()
    hablar_bienvenida()

    print("\n  Secuencia completada.\n")

    # Re-enable voice recognition after a short buffer
    time.sleep(1.0)
    voice_paused = False


def abrir_youtube():
    print("  Opening YouTube in Chrome...")
    subprocess.Popen(["open", "-a", "Google Chrome", YOUTUBE_URL])
    time.sleep(1.0)


# ──────────────────────────────────────────────────────────────────────────────
#  Voice command thread
# ──────────────────────────────────────────────────────────────────────────────
def voice_thread(model: Model):
    global lang

    WAKE_VOCAB    = '["ray bus", "rubies", "ray b", "[unk]"]'
    WAKE_TRIGGERS = ["ray bus", "rubies", "ray b"]
    CMD_VOCAB     = '["change language", "change", "language", "goodbye", "good bye", "[unk]"]'

    rec_wake = KaldiRecognizer(model, SAMPLE_RATE, WAKE_VOCAB)
    rec_cmd  = KaldiRecognizer(model, SAMPLE_RATE, CMD_VOCAB)

    state = "wake"
    print("  [Voice] Listening for 'Raibis'...")

    while not shutdown_event.is_set():
        try:
            chunk = voice_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if state == "wake":
            if rec_wake.AcceptWaveform(chunk):
                text = json.loads(rec_wake.Result()).get("text", "").lower()
                if any(w in text for w in WAKE_TRIGGERS):
                    print(f"  [Voice] Wake word: '{text}'")
                    threading.Thread(
                        target=lambda: hablar_jarvis("How can I help you, sir?"),
                        daemon=True
                    ).start()
                    while not voice_queue.empty():
                        voice_queue.get_nowait()
                    rec_cmd = KaldiRecognizer(model, SAMPLE_RATE, CMD_VOCAB)
                    state = "command"

        elif state == "command":
            if rec_cmd.AcceptWaveform(chunk):
                text = json.loads(rec_cmd.Result()).get("text", "").lower()
                print(f"  [Voice] Command: '{text}'")

                if "change" in text or "language" in text:
                    threading.Thread(target=handle_change_language, daemon=True).start()
                elif "goodbye" in text or "good bye" in text:
                    threading.Thread(target=handle_goodbye, daemon=True).start()
                    return
                else:
                    hablar_jarvis("I did not catch that, sir.")

                while not voice_queue.empty():
                    voice_queue.get_nowait()
                rec_wake = KaldiRecognizer(model, SAMPLE_RATE, WAKE_VOCAB)
                state = "wake"


def handle_change_language():
    global lang
    with lang_lock:
        lang = "en" if lang == "es" else "es"
        new_lang = lang
    save_lang(new_lang)
    label = "English" if new_lang == "en" else "Spanish"
    print(f"  [Voice] Language → {label}")
    hablar_jarvis(f"Switching greetings to {label}, sir.")


def handle_goodbye():
    hablar_jarvis("Goodbye, sir. Have a great day.")
    time.sleep(0.5)
    shutdown_event.set()


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    global THRESHOLD

    if not os.path.isdir(VOSK_MODEL):
        print(f"\n  ERROR: Vosk model not found at: {VOSK_MODEL}")
        print("  Run:")
        print("    curl -L -o model.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip")
        print("    unzip model.zip")
        sys.exit(1)

    # Ask audio mode once; remember it for future runs
    audiomode = load_audiomode()
    if audiomode is None:
        audiomode = ask_audiomode()

    THRESHOLD = THRESHOLD_HEADPHONES if audiomode == "headphones" else THRESHOLD_NO_HEADPHONES

    import vosk
    vosk.SetLogLevel(-1)
    model = Model(VOSK_MODEL)

    threading.Thread(target=voice_thread, args=(model,), daemon=True).start()

    with lang_lock:
        current_lang = lang

    print("=" * 55)
    print("  Raibis Voice — ready")
    print(f"  Greeting language : {'Spanish' if current_lang == 'es' else 'English'}")
    print(f"  Audio mode        : {audiomode}  (threshold: {THRESHOLD})")
    print("  Commands (say 'Raibis' first):")
    print("    'Change language' — toggle ES / EN")
    print("    'Goodbye'         — exit")
    print("  Ctrl+C to force exit")
    print("=" * 55)

    try:
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="int16",
            callback=audio_callback,
        ):
            while not shutdown_event.is_set():
                time.sleep(0.1)
                if is_triggered():
                    time.sleep(6)
                    set_triggered(False)
                    print("\n  Escuchando de nuevo...\n")
    except KeyboardInterrupt:
        print("\n\nHasta luego!")
    sys.exit(0)


if __name__ == "__main__":
    main()
