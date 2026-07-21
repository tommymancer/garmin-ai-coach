# Running it continuously

Two processes:

| Process | What it does | How to run it |
|---|---|---|
| `coach.feedback` | Checks Garmin for a new activity; messages you if there is one | every ~15 min |
| `coach.chat` | Answers your Telegram messages | always on |

Replace `/path/to/garmin-ai-coach` in the unit files with your actual path.

## Linux (systemd, user services)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now garmin-ai-coach-feedback.timer
systemctl --user enable --now garmin-ai-coach-chat.service
# keep them running when you're not logged in:
sudo loginctl enable-linger "$USER"

journalctl --user -u garmin-ai-coach-chat -f
```

## macOS (launchd)

```bash
cp deploy/launchd/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.garminaicoach.feedback.plist
launchctl load ~/Library/LaunchAgents/com.garminaicoach.chat.plist
tail -f /tmp/garmin-ai-coach-chat.log
```

**macOS gotcha:** launchd cannot execute anything inside `~/Documents`,
`~/Desktop` or `~/Downloads` — those are TCC-protected and you'll get
`Operation not permitted`. Keep the repo somewhere else (e.g. `~/src/`).

## Anything with cron

```
*/15 * * * * cd /path/to/garmin-ai-coach && ./.venv/bin/python -m coach.feedback >> /tmp/coach.log 2>&1
```

The chat daemon needs a supervisor that restarts it, so cron alone isn't enough
for that one — use systemd, launchd, tmux, or a `while true` wrapper.
