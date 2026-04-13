#!/usr/bin/env python3
"""
Raibis Voice Assistant — Jarvis edition v0.0.7

Workflow:
  1. Script starts (asks headphone mode once, persists choice)
  2. Two claps → opens YouTube in Chrome + speaks greeting in current language
  3. Voice commands (say 'Raibis' to wake):
     - 'change language'       → toggle ES / EN greeting (persisted)
     - 'tasks today'           → list today's tasks from Notion
     - 'tasks this week'       → list this week's tasks
     - 'tasks this month'      → list this month's tasks
     - 'projects'              → list active projects
     - 'play music'            → asks what to play, opens YouTube search in Chrome
     - 'goodbye'               → exit
  4. Say 'raibis stop' anytime → interrupt speech and return to listening

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
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model

# ──────────────────────────────────────────────────────────────────────────────
#  Threshold profiles
# ──────────────────────────────────────────────────────────────────────────────
THRESHOLD_HEADPHONES    = 0.08
THRESHOLD_NO_HEADPHONES = 0.18

SAMPLE_RATE   = 16000
BLOCK_SIZE    = int(SAMPLE_RATE * 0.05)
COOLDOWN      = 0.5
DOUBLE_WINDOW = 2.0

YOUTUBE_SEARCH = "https://www.youtube.com/results?search_query="
YOUTUBE_URL    = "https://youtu.be/pAgnJDJN4VA?si=wcRu25cvV6OqouRY&t=5"

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
VOSK_MODEL  = os.path.join(SCRIPT_DIR, "vosk-model-small-en-us-0.15")
LANG_FILE   = os.path.join(SCRIPT_DIR, ".lang")
MODE_FILE   = os.path.join(SCRIPT_DIR, ".audiomode")

# Notion MCP — Docker container name and binary
NOTION_CONTAINER = "jolly_blackburn"
NOTION_BIN       = "/usr/local/bin/notion-mcp-server"
TASKS_DB_ID      = "1a896b7f-dd8f-81dc-8db0-daea76555b64"
PROJECTS_DB_ID   = "1a896b7f-dd8f-8122-929f-fb8d53ff7e5c"

PRIORITY_ORDER = {"🔥 UltraHigh": 0, "High": 1, "Medium": 2, "Low": 3, "": 4}

# ──────────────────────────────────────────────────────────────────────────────
#  Voices
# ──────────────────────────────────────────────────────────────────────────────
JARVIS_VOICE  = "Daniel"
JARVIS_RATE   = 170
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

# Wake-word responses — called after detecting "Raibis"
WAKE_RESPONSES_EN = [
    "How can I help you, sir?",
    "Yes boss, you are the best. What do you need?",
    "At your service, sir.",
    "Ready and listening, boss.",
    "What can I do for you today, sir?",
]

WAKE_RESPONSES_ES = [
    "¿En qué le puedo ayudar, señor?",
    "Sí jefe, usted es el mejor. ¿Qué necesita?",
    "A sus órdenes, señor.",
    "Listo y escuchando, jefe.",
    "¿Qué puedo hacer por usted hoy, señor?",
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


def load_audiomode() -> Optional[str]:
    if os.path.isfile(MODE_FILE):
        val = open(MODE_FILE).read().strip()
        if val in ("headphones", "speakers"):
            return val
    return None


def save_audiomode(value: str):
    with open(MODE_FILE, "w") as f:
        f.write(value)


def ask_audiomode() -> str:
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
clap_times = []
clap_lock         = threading.Lock()
_clap_triggered   = False
_clap_trigger_lock = threading.Lock()

lang       = load_lang()
lang_lock  = threading.Lock()

voice_queue    = queue.Queue()
voice_paused   = False
shutdown_event = threading.Event()
stop_speaking  = threading.Event()   # set by "raibis stop"

THRESHOLD = THRESHOLD_NO_HEADPHONES


def is_triggered() -> bool:
    with _clap_trigger_lock:
        return _clap_triggered


def set_triggered(val: bool):
    global _clap_triggered
    with _clap_trigger_lock:
        _clap_triggered = val


# ──────────────────────────────────────────────────────────────────────────────
#  TTS
# ──────────────────────────────────────────────────────────────────────────────
def hablar_jarvis(texto: str):
    if stop_speaking.is_set():
        return
    print(f"  [Jarvis] '{texto}'")
    proc = subprocess.Popen(
        ["say", "-v", JARVIS_VOICE, "-r", str(JARVIS_RATE), texto]
    )
    # Poll so we can interrupt on stop_speaking
    while proc.poll() is None:
        if stop_speaking.is_set():
            proc.terminate()
            return
        time.sleep(0.05)


def hablar_espanol(texto: str):
    if stop_speaking.is_set():
        return
    print(f"  [Español] '{texto}'")
    proc = subprocess.Popen(["say", "-v", SPANISH_VOICE, texto])
    while proc.poll() is None:
        if stop_speaking.is_set():
            proc.terminate()
            return
        time.sleep(0.05)


def hablar(texto: str):
    """Speak in the current language."""
    with lang_lock:
        current = lang
    if current == "es":
        hablar_espanol(texto)
    else:
        hablar_jarvis(texto)


def hablar_bienvenida():
    with lang_lock:
        current = lang
    if current == "es":
        hablar_espanol(random.choice(MENSAJES_ES))
    else:
        hablar_jarvis(random.choice(MENSAJES_EN))


def wake_response():
    """Random acknowledgement when wake word is detected."""
    with lang_lock:
        current = lang
    if current == "es":
        hablar_espanol(random.choice(WAKE_RESPONSES_ES))
    else:
        hablar_jarvis(random.choice(WAKE_RESPONSES_EN))


# ──────────────────────────────────────────────────────────────────────────────
#  Notion MCP helper
# ──────────────────────────────────────────────────────────────────────────────
_notion_id = 0
_notion_lock = threading.Lock()


def _next_id() -> int:
    global _notion_id
    with _notion_lock:
        _notion_id += 1
        return _notion_id


def notion_call(method: str, params: dict) -> Optional[dict]:
    """Send one JSON-RPC call to the Notion MCP container via docker exec stdin."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": method,
        "params": params
    })
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", NOTION_CONTAINER, NOTION_BIN],
            input=payload.encode(),
            capture_output=True,
            timeout=15
        )
        if result.returncode != 0:
            print(f"  [Notion] Error: {result.stderr.decode()[:200]}")
            return None
        raw = result.stdout.decode().strip()
        # stdout may have multiple lines; find the JSON-RPC response line
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                if "result" in data:
                    return data["result"]
        return None
    except Exception as e:
        print(f"  [Notion] Exception: {e}")
        return None


def query_tasks(start_date: str, end_date: str) -> list:
    """Query Tasks V1.0 filtered by due date range, sorted by priority."""
    result = notion_call("tools/call", {
        "name": "API-query-data-source",
        "arguments": {
            "database_id": TASKS_DB_ID,
            "filter": {
                "and": [
                    {"property": "Due", "date": {"on_or_after": start_date}},
                    {"property": "Due", "date": {"on_or_before": end_date}},
                    {"property": "Status", "status": {"does_not_equal": "Done"}},
                    {"property": "Status", "status": {"does_not_equal": "Canceled"}}
                ]
            },
            "sorts": [
                {"property": "Due", "direction": "ascending"}
            ]
        }
    })
    if not result:
        return []
    try:
        content = result.get("content", [])
        if content and isinstance(content[0], dict):
            raw = content[0].get("text", "")
            data = json.loads(raw)
            return data.get("results", [])
    except Exception as e:
        print(f"  [Notion] Parse error: {e}")
    return []


def query_projects() -> list:
    """Query Projects V1.0 — active projects (Doing status)."""
    result = notion_call("tools/call", {
        "name": "API-query-data-source",
        "arguments": {
            "database_id": PROJECTS_DB_ID,
            "filter": {
                "property": "Status",
                "status": {"equals": "Doing"}
            },
            "sorts": [{"property": "Edited", "direction": "descending"}]
        }
    })
    if not result:
        return []
    try:
        content = result.get("content", [])
        if content and isinstance(content[0], dict):
            raw = content[0].get("text", "")
            data = json.loads(raw)
            return data.get("results", [])
    except Exception as e:
        print(f"  [Notion] Parse error: {e}")
    return []


def extract_task_info(task: dict) -> dict:
    props = task.get("properties", {})
    name = ""
    try:
        name = props["Name"]["title"][0]["plain_text"]
    except Exception:
        pass
    priority = ""
    try:
        priority = props["Priority"]["status"]["name"]
    except Exception:
        pass
    due = ""
    try:
        due = props["Due"]["date"]["start"]
    except Exception:
        pass
    status = ""
    try:
        status = props["Status"]["status"]["name"]
    except Exception:
        pass
    return {"name": name, "priority": priority, "due": due, "status": status}


def extract_project_info(proj: dict) -> dict:
    props = proj.get("properties", {})
    name = ""
    try:
        name = props["Name"]["title"][0]["plain_text"]
    except Exception:
        pass
    status = ""
    try:
        status = props["Status"]["status"]["name"]
    except Exception:
        pass
    macro = ""
    try:
        macro = props["MacroArea"]["select"]["name"]
    except Exception:
        pass
    kanban = ""
    try:
        kanban = props["Kanban"]["select"]["name"]
    except Exception:
        pass
    return {"name": name, "status": status, "macro": macro, "kanban": kanban}


# ──────────────────────────────────────────────────────────────────────────────
#  Clap detection
# ──────────────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    global voice_paused, clap_times

    raw = bytes(indata)
    if not voice_paused:
        voice_queue.put(raw)

    if is_triggered():
        return

    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(pcm ** 2)))
    now = time.time()

    if rms > THRESHOLD:
        with clap_lock:
            if clap_times and (now - clap_times[-1]) < COOLDOWN:
                return
            clap_times.append(now)
            clap_times[:] = [t for t in clap_times if now - t <= DOUBLE_WINDOW]
            count = len(clap_times)
            print(f"  Aplauso {count}/2  (RMS={rms:.3f})")
            if count >= 2:
                with _clap_trigger_lock:
                    global _clap_triggered
                    if _clap_triggered:
                        return
                    _clap_triggered = True
                clap_times.clear()
                threading.Thread(target=secuencia_bienvenida, daemon=True).start()


# ──────────────────────────────────────────────────────────────────────────────
#  Welcome sequence
# ──────────────────────────────────────────────────────────────────────────────
def secuencia_bienvenida():
    global voice_paused
    print("\n  Iniciando secuencia de bienvenida...\n")
    voice_paused = True
    while not voice_queue.empty():
        try:
            voice_queue.get_nowait()
        except queue.Empty:
            break
    abrir_youtube()
    hablar_bienvenida()
    print("\n  Secuencia completada.\n")
    time.sleep(1.0)
    voice_paused = False


def abrir_youtube():
    print("  Opening YouTube in Chrome...")
    subprocess.Popen(["open", "-a", "Google Chrome", YOUTUBE_URL])
    time.sleep(1.0)


# ──────────────────────────────────────────────────────────────────────────────
#  Command handlers
# ──────────────────────────────────────────────────────────────────────────────
def handle_change_language():
    global lang
    with lang_lock:
        lang = "en" if lang == "es" else "es"
        new_lang = lang
    save_lang(new_lang)
    label = "English" if new_lang == "en" else "Spanish"
    print(f"  [Voice] Language → {label}")
    hablar_jarvis(f"Switching greetings to {label}, sir.")


def handle_tasks(timeframe: str):
    """Fetch and speak tasks for a given timeframe: today / week / month."""
    today = datetime.now().date()
    if timeframe == "today":
        start = today.isoformat()
        end   = today.isoformat()
        label_en = "today"
        label_es = "hoy"
    elif timeframe == "week":
        start = today.isoformat()
        end   = (today + timedelta(days=7)).isoformat()
        label_en = "this week"
        label_es = "esta semana"
    else:  # month
        start = today.isoformat()
        end   = (today + timedelta(days=30)).isoformat()
        label_en = "this month"
        label_es = "este mes"

    with lang_lock:
        current = lang

    if current == "es":
        hablar_espanol(f"Consultando tareas para {label_es}, un momento.")
    else:
        hablar_jarvis(f"Fetching tasks for {label_en}, one moment.")

    tasks = query_tasks(start, end)
    if not tasks:
        if current == "es":
            hablar_espanol(f"No encontré tareas pendientes para {label_es}, señor.")
        else:
            hablar_jarvis(f"No pending tasks found for {label_en}, sir.")
        return

    # Sort by priority
    infos = [extract_task_info(t) for t in tasks]
    infos.sort(key=lambda x: PRIORITY_ORDER.get(x["priority"], 4))

    total = len(infos)
    if current == "es":
        hablar_espanol(f"Encontré {total} tareas para {label_es}. ¿Cuántas quiere que le liste?")
    else:
        hablar_jarvis(f"I found {total} tasks for {label_en}. How many would you like me to list?")

    # Listen for a number
    count_str = listen_for_short_answer()
    count = parse_number(count_str, default=min(5, total))
    count = min(count, total)

    # Speak the tasks
    for i, info in enumerate(infos[:count], 1):
        pri = info["priority"] or "No priority"
        due = info["due"] or "no due date"
        name = info["name"] or "Unnamed task"
        if current == "es":
            hablar_espanol(f"Tarea {i}: {name}. Prioridad: {pri}. Fecha: {due}.")
        else:
            hablar_jarvis(f"Task {i}: {name}. Priority: {pri}. Due: {due}.")
        if stop_speaking.is_set():
            break


def handle_projects():
    with lang_lock:
        current = lang

    if current == "es":
        hablar_espanol("Consultando proyectos activos, un momento.")
    else:
        hablar_jarvis("Fetching active projects, one moment.")

    projects = query_projects()
    if not projects:
        if current == "es":
            hablar_espanol("No encontré proyectos activos, señor.")
        else:
            hablar_jarvis("No active projects found, sir.")
        return

    infos = [extract_project_info(p) for p in projects]
    total = len(infos)

    if current == "es":
        hablar_espanol(f"Tiene {total} proyectos activos.")
    else:
        hablar_jarvis(f"You have {total} active projects.")

    for i, info in enumerate(infos, 1):
        name  = info["name"] or "Unnamed"
        macro = info["macro"] or ""
        if current == "es":
            hablar_espanol(f"Proyecto {i}: {name}. Área: {macro}.")
        else:
            hablar_jarvis(f"Project {i}: {name}. Area: {macro}.")
        if stop_speaking.is_set():
            break

    if stop_speaking.is_set():
        return

    if current == "es":
        hablar_espanol("¿Quiere que le muestre las propiedades de algún proyecto en especial?")
    else:
        hablar_jarvis("Would you like me to show the properties of a specific project?")

    answer = listen_for_short_answer()
    if answer and any(w in answer for w in ["yes", "yeah", "sure", "sí", "si", "claro"]):
        if current == "es":
            hablar_espanol("¿Cuál proyecto?")
        else:
            hablar_jarvis("Which project, sir?")
        project_name = listen_for_short_answer()
        # Find best match
        match = next((p for p in infos if project_name.lower() in p["name"].lower()), None)
        if match:
            if current == "es":
                hablar_espanol(
                    f"Proyecto: {match['name']}. "
                    f"Estado: {match['status']}. "
                    f"Área: {match['macro']}. "
                    f"Kanban: {match['kanban']}."
                )
            else:
                hablar_jarvis(
                    f"Project: {match['name']}. "
                    f"Status: {match['status']}. "
                    f"Area: {match['macro']}. "
                    f"Kanban: {match['kanban']}."
                )
        else:
            if current == "es":
                hablar_espanol("No encontré ese proyecto, señor.")
            else:
                hablar_jarvis("I could not find that project, sir.")


def handle_play_music():
    with lang_lock:
        current = lang

    if current == "es":
        hablar_espanol("¿Qué música quiere escuchar, señor?")
    else:
        hablar_jarvis("What music would you like to play, sir?")

    query = listen_for_short_answer(timeout=8)
    if not query:
        if current == "es":
            hablar_espanol("No escuché nada, señor.")
        else:
            hablar_jarvis("I did not catch that, sir.")
        return

    print(f"  [Music] Searching YouTube for: '{query}'")
    encoded = query.replace(" ", "+")
    url = YOUTUBE_SEARCH + encoded
    subprocess.Popen(["open", "-a", "Google Chrome", url])

    if current == "es":
        hablar_espanol(f"Buscando {query} en YouTube, señor.")
    else:
        hablar_jarvis(f"Searching YouTube for {query}, sir.")


def handle_goodbye():
    with lang_lock:
        current = lang
    if current == "es":
        hablar_espanol("Hasta luego, señor. Que tenga un excelente día.")
    else:
        hablar_jarvis("Goodbye, sir. Have a great day.")
    time.sleep(0.5)
    shutdown_event.set()


# ──────────────────────────────────────────────────────────────────────────────
#  Short answer listener (used after asking a question)
# ──────────────────────────────────────────────────────────────────────────────
def listen_for_short_answer(timeout: float = 6.0) -> str:
    """
    Drain voice_queue for `timeout` seconds and return the best transcription.
    Uses a fresh full-vocab recognizer so any word can be understood.
    """
    import vosk as vosk_mod
    vosk_mod.SetLogLevel(-1)
    model_path = VOSK_MODEL
    if not os.path.isdir(model_path):
        return ""
    model = Model(model_path)
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    deadline = time.time() + timeout
    best = ""
    while time.time() < deadline:
        try:
            chunk = voice_queue.get(timeout=0.3)
        except queue.Empty:
            continue
        if rec.AcceptWaveform(chunk):
            text = json.loads(rec.Result()).get("text", "").lower().strip()
            if text:
                best = text
                break
    # Also check partial
    partial = json.loads(rec.PartialResult()).get("partial", "").lower().strip()
    return best or partial


def parse_number(text: str, default: int) -> int:
    """Extract first number word or digit from text."""
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
        "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
        "all": 999, "todos": 999, "todas": 999,
    }
    for token in text.lower().split():
        if token in words:
            return words[token]
        if token.isdigit():
            return int(token)
    return default


# ──────────────────────────────────────────────────────────────────────────────
#  Voice command thread
# ──────────────────────────────────────────────────────────────────────────────
def voice_thread(model: Model):
    global lang

    WAKE_VOCAB    = '["ray bus", "rubies", "ray b", "raybis stop", "ray bis stop", "[unk]"]'
    WAKE_TRIGGERS = ["ray bus", "rubies", "ray b"]
    STOP_TRIGGERS = ["stop", "raybis stop", "ray bis stop", "ray bus stop"]

    CMD_VOCAB = (
        '["change language", "change", "language", '
        '"tasks today", "tasks this week", "tasks week", "tasks this month", "tasks month", '
        '"tasks", "today", "week", "month", '
        '"projects", "play music", "music", '
        '"goodbye", "good bye", "[unk]"]'
    )

    rec_wake = KaldiRecognizer(model, SAMPLE_RATE, WAKE_VOCAB)
    rec_cmd  = KaldiRecognizer(model, SAMPLE_RATE, CMD_VOCAB)
    # Full vocab recognizer for stop detection (always running)
    rec_stop = KaldiRecognizer(model, SAMPLE_RATE)

    state = "wake"
    print("  [Voice] Listening for 'Raibis'...")

    while not shutdown_event.is_set():
        try:
            chunk = voice_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        # Always check for "raibis stop" regardless of state
        if rec_stop.AcceptWaveform(chunk):
            stop_text = json.loads(rec_stop.Result()).get("text", "").lower()
            if any(t in stop_text for t in STOP_TRIGGERS):
                print("  [Voice] Stop detected — interrupting.")
                stop_speaking.set()
                time.sleep(0.3)
                stop_speaking.clear()
                # drain and reset
                while not voice_queue.empty():
                    voice_queue.get_nowait()
                rec_wake = KaldiRecognizer(model, SAMPLE_RATE, WAKE_VOCAB)
                state = "wake"
                continue

        if state == "wake":
            if rec_wake.AcceptWaveform(chunk):
                text = json.loads(rec_wake.Result()).get("text", "").lower()
                if any(w in text for w in WAKE_TRIGGERS):
                    print(f"  [Voice] Wake: '{text}'")
                    threading.Thread(target=wake_response, daemon=True).start()
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
                elif "task" in text or "today" in text:
                    if "week" in text:
                        threading.Thread(target=handle_tasks, args=("week",), daemon=True).start()
                    elif "month" in text:
                        threading.Thread(target=handle_tasks, args=("month",), daemon=True).start()
                    else:
                        threading.Thread(target=handle_tasks, args=("today",), daemon=True).start()
                elif "project" in text:
                    threading.Thread(target=handle_projects, daemon=True).start()
                elif "music" in text or "play" in text:
                    threading.Thread(target=handle_play_music, daemon=True).start()
                elif "goodbye" in text or "good bye" in text:
                    threading.Thread(target=handle_goodbye, daemon=True).start()
                    return
                else:
                    with lang_lock:
                        current = lang
                    if current == "es":
                        hablar_espanol("No entendí ese comando, señor.")
                    else:
                        hablar_jarvis("I did not catch that command, sir.")

                while not voice_queue.empty():
                    voice_queue.get_nowait()
                rec_wake = KaldiRecognizer(model, SAMPLE_RATE, WAKE_VOCAB)
                state = "wake"


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

    audiomode = load_audiomode()
    if audiomode is None:
        audiomode = ask_audiomode()

    THRESHOLD = THRESHOLD_HEADPHONES if audiomode == "headphones" else THRESHOLD_NO_HEADPHONES

    import vosk as vosk_mod
    vosk_mod.SetLogLevel(-1)
    model = Model(VOSK_MODEL)

    threading.Thread(target=voice_thread, args=(model,), daemon=True).start()

    with lang_lock:
        current_lang = lang

    print("=" * 55)
    print("  Raibis Voice — ready  (v0.0.7)")
    print(f"  Greeting language : {'Spanish' if current_lang == 'es' else 'English'}")
    print(f"  Audio mode        : {audiomode}  (threshold: {THRESHOLD})")
    print("  Wake word: 'Raibis' — then say:")
    print("    'tasks today / this week / this month'")
    print("    'projects'")
    print("    'play music'")
    print("    'change language'")
    print("    'goodbye'")
    print("  Say 'raibis stop' anytime to interrupt")
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
