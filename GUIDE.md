# raibis-voice-welcome

Double-clap home automation — two claps trigger a random greeting, open YouTube in Chrome. Voice-activated via wake word "Raibis" to change greeting language.

## What it does

**Clap mode:**
1. Listens on the microphone for 2 claps
2. Speaks a random greeting in the current language (Spanish by default)
3. Opens YouTube in Google Chrome

**Voice command mode:**
1. Say **"Raibis"** — Jarvis replies *"How can I help you, sir?"*
2. Say **"Change language"** — toggles greetings between Spanish and English
3. After switching to English, greetings shuffle between:
   - *"Welcome back, sir."*
   - *"It is good to be back, sir."*
   - *"Welcome back, boss."*

**Voices:**
- English (Jarvis mode): `Daniel` — British male, en_GB, 165 wpm
- Spanish: `Mónica` — Castilian Spanish, es_ES

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

**3. Create a virtual environment and install dependencies**
```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

**4. Download the Vosk speech recognition model** (~40 MB, offline, no API key)
```bash
curl -L -o model.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip model.zip
rm model.zip
```

**5. Run**
```bash
venv/bin/python3 bienvenido_jarvis.py
# or if using system Python:
python3 bienvenido_jarvis.py
```

**6. Grant microphone access**
macOS will prompt for microphone permissions on first run. Accept, then restart the script.

---

### Option B — Run with Docker (Linux / non-macOS)

> Note: on macOS the container cannot access the system microphone or call AppleScript/`say`, so Docker is primarily for Linux hosts.

**1. Install Docker** — https://docs.docker.com/get-docker/

**2. Clone and build**
```bash
git clone <your-repo-url>
cd raibis-voice-welcome
docker compose up --build
```

---

## Auto-start on macOS login (LaunchAgent)

**1. Edit the plist** — replace `PATH_TO_REPO` with your absolute clone path:
```bash
sed -i '' 's|PATH_TO_REPO|/Users/yourname/raibis-voice-welcome|g' \
    com.raibis.voice.welcome.plist
```

**2. Load it**
```bash
cp com.raibis.voice.welcome.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.raibis.voice.welcome.plist
```

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

Open `bienvenido_jarvis.py` and edit either list near the top:

```python
MENSAJES_ES = [
    "Bienvenido a casa, señor Rubix.",
    "Bienvenido a casa, Patronzote.",
    # Add more Spanish greetings here
]

MENSAJES_EN = [
    "Welcome back, sir.",
    "It is good to be back, sir.",
    "Welcome back, boss.",
    # Add more English greetings here
]
```

---

## Changing the YouTube link

Edit `YOUTUBE_URL` near the top of `bienvenido_jarvis.py`:

```python
YOUTUBE_URL = "https://youtu.be/YOUR_VIDEO_ID"
```

---

## Changing the Jarvis voice

Edit `JARVIS_VOICE` near the top of `bienvenido_jarvis.py`:

```python
JARVIS_VOICE = "Daniel"   # British male — best Jarvis match
```

See all available voices:
```bash
say -v '?' | grep en_GB    # British English options
say -v '?' | grep en_US    # American English options
say -v '?' | grep es_      # Spanish options
```

To change the Spanish voice, edit `SPANISH_VOICE`:
```python
SPANISH_VOICE = "Paulina"   # Mexican Spanish
```

---

## Adjusting clap sensitivity

Edit `THRESHOLD` in `bienvenido_jarvis.py`:

```python
THRESHOLD = 0.10   # raise if background noise triggers it; lower if claps aren't detected
```

---

## Requirements

- Python 3.9+
- Microphone
- macOS (for `say` TTS, `open -a "Google Chrome"`)
- Google Chrome installed
- Vosk model downloaded (see setup step 4 above)
