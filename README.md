# Overworld Event Bot

A Raid-Helper-style Discord bot for scheduling Overworld group events: post an event, people click **Accept** to sign up, the embed shows a live countdown and the current roster.

## Layout
- `bot.py` — slash commands + the countdown refresh loop
- `views.py` — the persistent Accept/Leave button view
- `database.py` — SQLite storage (events + signups)
- `utils.py` — embed builder + time formatting
- `events.db` — created automatically on first run (don't commit this)

## Setup
1. Create a bot at https://discord.com/developers/applications → **Bot** tab → copy the token.
2. Under **OAuth2 → URL Generator**, tick `bot` + `applications.commands`, permissions: Send Messages, Embed Links, Read Message History. Use the generated URL to invite it to your server.
3. Locally:
   ```
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env          # then paste your token into .env
   python bot.py
   ```

Slash commands can take up to an hour to appear globally the first time; per-server it's usually instant.

## Commands
- `/event create title description date time` — date as `YYYY-MM-DD`, time as `HH:MM` (24h), interpreted in the `TIMEZONE` env var (defaults to `Europe/Stockholm`).
- `/event list` — active events in the server, with IDs.
- `/event close event_id` — freezes the countdown, keeps the roster visible. Creator or a Manage Server admin only.
- `/event delete event_id` — deletes the event and its message. Same permission rule.

## Notes on the design
- **Buttons survive restarts.** The Accept/Leave view uses fixed `custom_id`s and looks up which event a click belongs to via the message ID, rather than baking the event ID into the button. That means one `bot.add_view(...)` call at startup covers every event message ever posted, including ones from before the last restart — no per-event re-registration needed.
- **Countdown refresh** runs on a 1-minute loop and edits every active event's message. If you have a lot of concurrent events, you may want to widen this to every 2–5 minutes to stay well under Discord's rate limits.
- **Storage** is a single SQLite file. Fine for one bot instance; if you ever need multiple processes hitting the same data, swap `aiosqlite` for `asyncpg` + Postgres — the query shapes in `database.py` would carry over almost directly.

## Running it 24/7
Running `python bot.py` on your own PC only keeps the bot online while that PC is on. To keep it running always, host it somewhere that stays up continuously. A few options, cheapest first:

- **A small VPS** (Hetzner CX22, ~€4/mo; or a DigitalOcean/Linode droplet) — most control, run it with `systemd` or inside `tmux`/`screen`, or Docker if you prefer.
- **Railway / Fly.io** — deploy straight from a GitHub repo, free tiers exist but are limited (Railway needs a card on file now; Fly's free allowance is small). Good if you don't want to touch Linux at all.
- **A Raspberry Pi at home** — works, but depends on your home internet/power staying up.

For a VPS with systemd, a minimal service file looks like:
```ini
[Unit]
Description=Overworld Event Bot
After=network.target

[Service]
WorkingDirectory=/home/youruser/raidhelper-bot
ExecStart=/home/youruser/raidhelper-bot/venv/bin/python bot.py
Restart=always
EnvironmentFile=/home/youruser/raidhelper-bot/.env

[Install]
WantedBy=multi-user.target
```
Then `sudo systemctl enable --now overworld-bot`. It'll restart automatically on crash or reboot.

## Extending it
Since Overworld doesn't have a WoW-style fixed role split, this bot is intentionally headcount-based (Accept/Leave, one list). If you later want sub-categories — say separate lists for "Main Group" vs "Backup", or a max roster size — that's a moderate change to `views.py` (add buttons) and `utils.py` (split the signups list into groups), and I'm happy to build that when you know what you want there.
