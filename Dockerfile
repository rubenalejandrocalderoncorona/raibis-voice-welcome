FROM python:3.11-slim

# Install system dependencies for sounddevice / PortAudio
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    libportaudio2 \
    libportaudiocpp0 \
    ffmpeg \
    espeak \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bienvenido_jarvis.py .

CMD ["python", "bienvenido_jarvis.py"]
