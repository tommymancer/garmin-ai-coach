# garmin-ai-coach — one container runs both the feedback loop and the chat daemon.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coach ./coach
COPY examples ./examples

# Persistent data (Garmin tokens, state, profile, plan) lives here — mount a
# volume so it survives restarts. Config comes from environment variables.
ENV COACH_DATA_DIR=/data
VOLUME /data

CMD ["python", "-m", "coach.run"]
