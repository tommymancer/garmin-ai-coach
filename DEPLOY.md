# Deploy

Pick one. All of them run **both** halves (activity feedback + chat) in a single
process, so there's nothing to keep alive by hand.

Every option needs the same 4-5 settings. Grab them first:

- `GARMIN_EMAIL`, `GARMIN_PASSWORD`
- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather) (`/newbot`)
- `TELEGRAM_CHAT_ID` — message your bot, then run `python3 -m tools.whoami`,
  or read it from the first reply the bot logs
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com)

---

## Docker on your own machine (simplest)

No Python install, no launchd/systemd, no macOS Documents-folder gotcha.

```bash
git clone https://github.com/tommymancer/garmin-ai-coach.git
cd garmin-ai-coach
cp .env.example .env      # then edit .env with the values above
docker compose up -d
```

That's it. Check it's alive and watch the logs:

```bash
docker compose logs -f
```

Update later:

```bash
git pull && docker compose up -d --build
```

Your Garmin tokens and state persist in a Docker volume (`coach-data`), so
restarts don't re-trigger old workouts.

---

## Fly.io (no machine of your own, ~free)

Runs 24/7 in the cloud on the free-ish tier. Secrets are stored by Fly, never
committed.

```bash
# one-time
curl -L https://fly.io/install.sh | sh
fly auth signup            # or: fly auth login

# from the repo folder
fly launch --copy-config --no-deploy      # accept the app name / region
fly volumes create coach_data --size 1    # persistent storage for tokens/state

# set your secrets (repeat --stage-secret style as needed)
fly secrets set \
  GARMIN_EMAIL="you@example.com" \
  GARMIN_PASSWORD="..." \
  TELEGRAM_BOT_TOKEN="..." \
  TELEGRAM_CHAT_ID="..." \
  ANTHROPIC_API_KEY="sk-ant-..."

fly deploy
fly logs        # watch it come up
```

---

## Railway / Render (git-based, click to deploy)

Both auto-detect the `Dockerfile` — no config files needed.

1. Push your fork to GitHub (or use this repo).
2. On [Railway](https://railway.app) or [Render](https://render.com): **New →
   Deploy from GitHub repo** → pick the repo.
3. Add the 4-5 environment variables above in the service's **Variables** /
   **Environment** tab.
4. Add a persistent disk/volume mounted at `/data` (so tokens survive restarts).
5. Deploy. Open the logs to confirm it started.

> On Render, choose a **Background Worker** (not a Web Service) — there's no web
> port to expose.

---

## A note on your credentials

Wherever you run this, your Garmin email/password and API key are stored **in
plain text** — in your `.env` file (Docker) or in the host's secret store
(Fly/Railway/Render). That's normal for a self-hosted tool: it's your data on
infrastructure you control, and nothing is sent to the project author or anyone
else. But if you deploy to a shared or throwaway host, delete the app when
you're done, and rotate the Garmin password / API key if you ever suspect the
host was compromised.
