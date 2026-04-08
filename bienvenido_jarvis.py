#!/usr/bin/env python3
"""
Double-clap welcome script for Señor Rubix / Patronzote / Señor Rubius.

Detects 2 claps → AI voice says welcome (random) → opens YouTube → Claude + Cursor side by side.

Dependencies:
    pip install sounddevice numpy pyttsx3

Usage:
    python bienvenido_jarvis.py
"""

import os
import sys
import time
import random
import threading
import subprocess
import webbrowser

import numpy as np
import sounddevice as sd
import pyttsx3

# ──────────────────────────────────────────────────────────────────────────────
#  Configuración
# ──────────────────────────────────────────────────────────────────────────────
SAMPLE_RATE    = 44100
BLOCK_SIZE     = int(SAMPLE_RATE * 0.05)   # 50 ms per block
THRESHOLD      = 0.20     # Minimum RMS to count as a clap  ← adjust if failing
COOLDOWN       = 0.1      # Minimum seconds between claps
DOUBLE_WINDOW  = 2.0      # Time window to detect second clap

YOUTUBE_URL    = "https://www.youtube.com/watch?v=hEIexwwiKKU"
NEW_PROJECT    = os.path.expanduser("~/Desktop/nuevo_proyecto")

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
    abrir_apps_lado_a_lado()

    print("\n  Secuencia completada.\n")


def hablar(texto: str):
    """Local TTS with pyttsx3 (uses system voices, no API key needed)."""
    print(f"  Diciendo: '{texto}'")

    # macOS: try 'say' command first (best quality, Spanish voice)
    resultado = subprocess.run(
        ["say", "-v", "Monica", texto],
        capture_output=True
    )
    if resultado.returncode == 0:
        return  # success with Monica (macOS Spanish voice)

    # Fallback: pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")

    # Look for Spanish voice
    esp = [v for v in voices if "es" in v.id.lower() or "spanish" in v.name.lower()]
    if esp:
        engine.setProperty("voice", esp[0].id)
        print(f"     Voice selected: {esp[0].name}")
    else:
        print("     Using default voice (no Spanish voice found)")

    engine.setProperty("rate", 148)
    engine.say(texto)
    engine.runAndWait()


def abrir_youtube():
    print(f"  Opening YouTube...")
    webbrowser.open(YOUTUBE_URL)
    time.sleep(1.2)


def abrir_apps_lado_a_lado():
    sw, sh = obtener_resolucion_pantalla()
    mitad = sw // 2

    os.makedirs(NEW_PROJECT, exist_ok=True)

    # Open Claude
    print("  Opening Claude...")
    subprocess.Popen(["open", "-a", "Claude"])
    time.sleep(1.8)

    # Open Cursor
    print("  Opening Cursor...")
    cursor_cmd = encontrar_cursor()
    if cursor_cmd:
        subprocess.Popen([cursor_cmd, NEW_PROJECT])
    else:
        subprocess.Popen(["open", "-a", "Cursor", NEW_PROJECT])
    time.sleep(1.8)

    # Side-by-side layout with AppleScript
    print("  Organizing windows...")
    applescript = f"""
    tell application "System Events"
        try
            tell process "Claude"
                set frontmost to true
                set position of window 1 to {{0, 0}}
                set size of window 1 to {{{mitad}, {sh}}}
            end tell
        end try
        try
            tell process "Cursor"
                set frontmost to true
                set position of window 1 to {{{mitad}, 0}}
                set size of window 1 to {{{mitad}, {sh}}}
            end tell
        end try
    end tell
    """
    subprocess.run(["osascript", "-e", applescript], capture_output=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Utilities
# ──────────────────────────────────────────────────────────────────────────────
def obtener_resolucion_pantalla() -> tuple[int, int]:
    try:
        out = subprocess.run(
            ["osascript", "-e",
             "tell application \"Finder\" to get bounds of window of desktop"],
            capture_output=True, text=True
        ).stdout.strip()
        parts = [int(x.strip()) for x in out.split(",")]
        return parts[2], parts[3]
    except Exception:
        return 1920, 1080


def encontrar_cursor():
    """Returns the Cursor CLI path if available."""
    candidatos = [
        "/usr/local/bin/cursor",
        "/opt/homebrew/bin/cursor",
        os.path.expanduser("~/.cursor/bin/cursor"),
    ]
    for path in candidatos:
        if os.path.isfile(path):
            return path
    result = subprocess.run(["which", "cursor"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


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
