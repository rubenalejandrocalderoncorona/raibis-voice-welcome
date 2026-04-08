# raibis-voice-welcome

Double-clap home automation — two claps trigger a random Spanish greeting, open YouTube, and launch Claude + Cursor side by side.

## What it does

1. Listens on the microphone for 2 claps
2. Randomly says one of:
   - "Bienvenido a casa, señor Rubix."
   - "Bienvenido a casa, Patronzote."
   - "Bienvenido a casa, señor Rubius."
3. Opens YouTube with your song
4. Opens Claude and Cursor side by side

---

## Running on a new computer

### Option A — Run natively (macOS, recommended)

**1. Install Python 3.9+**
```bash
brew install python
```

**2. Clone the repo**
```bash
git clone <your-repo-url>
cd raibis-voice-welcome
```

**3. Install dependencies**
```bash
pip3 install -r requirements.txt
```

**4. Run**
```bash
python3 bienvenido_jarvis.py
```

**5. Grant microphone access**
macOS will prompt for microphone permissions. Accept, then restart the script.

---

### Option B — Run with Docker (Linux / non-macOS)

> Note: on macOS the container cannot access the system microphone or call AppleScript/`say`, so Docker is primarily for Linux hosts.

**1. Install Docker**
See https://docs.docker.com/get-docker/

**2. Clone the repo**
```bash
git clone <your-repo-url>
cd raibis-voice-welcome
```

**3. Build & run**
```bash
docker compose up --build
```

---

## Auto-start on macOS login (LaunchAgent)

**1. Edit the plist** — replace `PATH_TO_REPO` with the absolute path where you cloned:

```bash
# Example (adjust to your actual path):
sed -i '' 's|PATH_TO_REPO|/Users/yourname/raibis-voice-welcome|g' \
    com.raibis.voice.welcome.plist
```

**2. Copy to LaunchAgents and load**
```bash
cp com.raibis.voice.welcome.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.raibis.voice.welcome.plist
```

The script now starts automatically every time you log in.

**Stop it:**
```bash
launchctl unload ~/Library/LaunchAgents/com.raibis.voice.welcome.plist
```

**View logs:**
```bash
tail -f /tmp/raibis-voice-welcome.log
tail -f /tmp/raibis-voice-welcome.error.log
```

---

## Customizing greetings

Open `bienvenido_jarvis.py` and edit the `MENSAJES` list near the top:

```python
MENSAJES = [
    "Bienvenido a casa, señor Rubix.",
    "Bienvenido a casa, Patronzote.",
    "Bienvenido a casa, señor Rubius.",
    # Add as many as you like ↓
    "Hola de nuevo, máquina.",
]
```

Save and restart the script (or reload the LaunchAgent) — no other changes needed.

---

## Changing the YouTube link

Edit the `YOUTUBE_URL` variable near the top of `bienvenido_jarvis.py`:

```python
YOUTUBE_URL = "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

---

## Adjusting clap sensitivity

If claps are not detected or there are false positives, adjust `THRESHOLD` in `bienvenido_jarvis.py`:

```python
THRESHOLD = 0.20   # raise if background noise triggers it; lower if claps aren't detected
```

---

## Requirements

- Python 3.9+
- Microphone
- macOS (for `say` TTS, AppleScript window layout, and LaunchAgent auto-start)
- Claude and Cursor apps installed (for the side-by-side launch)
