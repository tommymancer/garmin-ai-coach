# Setup guide for AI assistants

You are helping a non-expert install **garmin-ai-coach** on their own computer.
This file is your instruction set. Work through it with the user step by step.

## The most important rule: never touch their secrets

The user will need a Garmin password, a Telegram bot token, and a Claude API
key. **Do NOT ask them to paste any of these into this chat.** They belong only
in a file on the user's machine, and the setup script prompts for them there
(hidden input). If a user pastes a secret anyway, tell them to treat it as
compromised: change the Garmin password, revoke the API key at
console.anthropic.com, and regenerate the bot token via @BotFather.

## How to behave

- You are a guide, not an installer. You cannot run commands on their machine —
  give exact commands, one step at a time, and wait for them to report back.
- Ask which operating system they're on first (macOS, Linux, or Windows) and
  give commands for that one only.
- Confirm each step worked before moving to the next. Ask them to paste any
  error message and help them fix it.
- Prefer the automated `setup.py` path below — it does almost everything.

## What they need first (help them get each)

1. **Python 3.10+** — check with `python3 --version` (macOS/Linux) or
   `python --version` (Windows). If missing, point them to python.org.
2. **A Garmin account** with a watch that reports Training Load (most
   Forerunner / Fenix / Venu / Epix models do; entry-level ones may not — if it
   doesn't, the cross-sport feature won't work and they should know before
   investing time).
3. **A Telegram account.**
4. **A Claude API key** — https://console.anthropic.com → API keys → Create.
   This is pay-as-you-go, roughly $1–6/month depending on the model.

## Step 1 — get the code

macOS / Linux:
```bash
git clone https://github.com/tommymancer/garmin-ai-coach.git
cd garmin-ai-coach
```
Windows (PowerShell): same commands.

If they don't have `git`, they can download the ZIP from the GitHub page
("Code" → "Download ZIP"), unzip it, and `cd` into the folder.

**macOS note:** do NOT put this folder in `~/Documents`, `~/Desktop`, or
`~/Downloads`. macOS protects those folders and the background scheduler
(launchd) can't run from them — they'll get "Operation not permitted". A folder
like `~/projects/` or the home directory is fine.

## Step 2 — create the Telegram bot (do this before setup.py)

Tell the user to, in the Telegram app:
1. Search for **@BotFather** and open the chat.
2. Send `/newbot`.
3. Choose a display name (anything) and a username ending in `bot`.
4. BotFather replies with a **token** — they'll paste it into the setup script
   in the next step (not here).

## Step 3 — run the installer

macOS / Linux:
```bash
python3 setup.py
```
Windows:
```powershell
python setup.py
```

The script will:
- create a virtual environment and install dependencies,
- prompt for the Garmin login, bot token, and Claude API key (typed on their
  machine, hidden),
- validate the bot token and help find their Telegram chat ID (it will ask them
  to message their new bot, then detect it),
- write everything to a local `.env` file,
- record a baseline (so they don't get messaged about old workouts).

Walk them through any prompts. If token validation keeps failing, the usual
causes are: an extra space pasted in, or they copied BotFather's message instead
of just the token.

## Step 4 — try it

Start the chat daemon:

macOS / Linux:
```bash
./.venv/bin/python -m coach.chat
```
Windows:
```powershell
.\.venv\Scripts\python -m coach.chat
```

While that's running, have them message their bot on Telegram, e.g.
"how am I doing?" or "what should I do tomorrow?". They can also send a photo of
a meal to get a calorie estimate.

To generate a feedback message immediately (instead of waiting for their next
real workout), they can re-run the baseline logic — but normally feedback fires
by itself when they upload an activity to Garmin.

## Step 5 — keep it running automatically

The chat daemon and the 15-minute feedback check should run in the background.
Point them to `deploy/README.md` in the repo, which has ready-made setups for:
- **Linux**: systemd user services (`systemctl --user`)
- **macOS**: launchd agents (remember the Documents-folder caveat above)
- **anything**: cron for the feedback check

Help them edit the placeholder path in those files to their actual repo path.

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| `Missing required setting: ...` | `.env` is incomplete — re-run `python3 setup.py`. |
| Telegram token "didn't work" | Extra whitespace, or they pasted BotFather's whole message. Just the `123456:AA...` part. |
| Bot never replies in chat | `TELEGRAM_CHAT_ID` doesn't match them. Re-run `python3 -m tools.whoami` after messaging the bot, put the printed ID in `.env`. |
| `429` / "rate limited" from Garmin | Too many logins in a short time (often from repeated testing). Wait ~30–60 min; normal use logs in rarely thanks to token caching. |
| No `ACWR` / no cross-sport load | Their watch doesn't report `activityTrainingLoad`. This is a device limitation, not a bug. |
| macOS "Operation not permitted" from the scheduler | The repo is in `~/Documents`/`~/Desktop`/`~/Downloads`. Move it elsewhere. |
| Swim load looks off | Wrist heart rate in water is unreliable on most watches. Expected. |

## What to tell them at the end

- Their Garmin password and API key are in `.env`, which is git-ignored and
  never uploaded anywhere. The coach runs entirely on their machine.
- The coach reads an optional `coach_plan.md` and `coach_profile.md` in their
  data folder (`~/.garmin-ai-coach` by default). Copy the files from `examples/`
  to give it a training plan and standing instructions. See the main README.
- It is a hobby project, not medical advice.
