# Build With Awie! — Discord bot

A Discord bot for the **AWS Student Builder Group – UPHSL** server. Members play a weekly AWS challenge
(**Play of the Week**), earn points and streaks, check **Stats**, and turn points into **raffle boosts**.
Data is stored in **Supabase** (hosted Postgres).

## What it does (mapped to the concept paper)

| Concept paper | In the bot |
|---|---|
| Main menu: Play of the Week / Stats | Persistent menu with two buttons (`/setup_menu`, or `/awie` for a private copy) |
| Multiple Choice (+1) | A–D buttons |
| Connect the Dots (+3) | One dropdown per item + "Lock in" button |
| Wordle (+3) | 6 guesses via a pop-up box, 🟩🟨⬛ board |
| Coding Proper (+5) | Pop-up code box, checked against accepted answers |
| Trivia after every answer | Shown whether right or wrong |
| Streak system | 3 wins in a row = Streak 1, then +1 per win; a loss resets it; highest streak is saved |
| Stats (name, score, current & highest streak) | `Stats` button or `/stats` |
| Raffle boost: every 20 points = +1 slot | Shown in Stats; admins export with `/raffle_export` |
| Database of user records | Supabase tables `awie_users` and `awie_plays` |
| Launch: Oct 25, 2026, 12:00 AM | `LAUNCH_DATE=2026-10-25` locks Play of the Week for members until then |

## Setup

### 1. Supabase (database)
1. Go to <https://supabase.com> → **New project** (pick a region close to you, e.g. Singapore). Save the database password.
2. Open **SQL Editor** → **New query**, paste the entire contents of `schema.sql`, and press **Run**. You should see "Success". (It creates the tables and locks them so only the bot can use them. Safe to run again.)
3. Open **Project Settings → API Keys** (labelled *Data API* / *API Keys* depending on the dashboard version) and note:
   - the **Project URL** (`https://xxxx.supabase.co`)
   - the **secret key** (starts with `sb_secret_...`) — or on older projects the **service_role** key.
   **Do not use the anon/publishable key** — the bot would be blocked, and the secret key must never be shared or put in a public repo.

**Using a project your club already has?** That works. Run `schema.sql` in that project instead of a new one.
It only creates tables and functions starting with `awie_` and never touches your existing tables (such as an
attendance table), so nothing there changes. Two things to know: the secret key gives full access to
*everything* in the project, so keep it private; and if another bot or app already uses this project, give this bot
its own copy of the key in its own `.env`.

### 2. Discord (bot account)
1. Go to <https://discord.com/developers/applications> → **New Application** → name it *Build With Awie!* (upload Awie's picture as the app icon).
2. Open the **Bot** tab → **Reset Token** → copy the token (keep it secret). No privileged intents are needed; Awie listens for voice-state updates for stage attendance.
3. Copy the **Application ID** from the *General Information* tab.
4. Invite it to your server with this link (replace `YOUR_CLIENT_ID`):
   `https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=52224&scope=bot%20applications.commands`
   (permissions = View Channels, Send Messages, Embed Links, Attach Files)
5. In Discord: **User Settings → Advanced → Developer Mode ON**, then right-click your server icon → **Copy Server ID**.

### 3. Run the bot
Requires **Python 3.10+**.
```bash
cd awie-bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
# edit .env: DISCORD_TOKEN, GUILD_ID, DISCORD_SUPABASE_URL', SUPABASE_KEY
python test_logic.py             # optional self-check
python validate_challenges.py    # optional content check
python bot.py
```
You should see `Awie is online`. If it stops with a Supabase error, re-check the URL/key and that `schema.sql` was run.

### 4. Put it in your server
In the channel where members will play, run **`/setup_menu`** (needs the *Manage Server* permission).
That posts the permanent menu. Members' answers and stats are private (only they see them).
To announce the new challenge automatically each Sunday at 12:00 AM, set `WEEKLY_ANNOUNCEMENT_CHANNEL_ID` to the announcement channel's ID in the bot's environment (Railway → service → **Variables**). Enable Developer Mode in Discord, right-click the channel, and choose **Copy Channel ID**. The bot needs permission to view and send messages in that channel. Announcements do not ping everyone.
To use the stage attendance tracker with this same bot connection, add `STAGE_CHANNEL_ID` in Railway Variables and set it to your Discord Stage Channel's ID (Developer Mode → right-click the stage channel → **Copy Channel ID**). Ensure Awie's role can view that stage channel. Railway will redeploy the service after the variable is added.

An admin can run `/attendance_start meeting_name` to begin tracking and `/attendance_stop` to stop and save durations to the existing Supabase `attendance` table. Provide the meeting name without quotes. The table must have `display_name`, `username`, `duration`, and `meeting_name` columns, and Awie's existing Supabase credentials must have permission to read and write it. The tracker stores live join times in memory, so do not restart or redeploy the Railway service during a meeting; intervals that have not yet been saved could be lost.

### 5. Keep it running 24/7
The bot only works while `python bot.py` is running. Options:
- **AWS (fits the theme!)**: a small EC2 or Lightsail instance. Check current pricing/credits for your account.
- Any always-on PC, Raspberry Pi, or a bot-hosting service.

Because the data lives in Supabase, you can move or rebuild the bot machine any time without losing scores
(just copy `.env` to the new machine).

Example `systemd` service on Linux (`/etc/systemd/system/awie.service`):
```ini
[Unit]
Description=Build With Awie bot
After=network-online.target

[Service]
WorkingDirectory=/home/ubuntu/awie-bot
ExecStart=/home/ubuntu/awie-bot/.venv/bin/python bot.py
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```
Then `sudo systemctl enable --now awie`.

> **Supabase free-plan note:** projects on the free plan can be paused after a period of inactivity. Once members are
> playing weekly this isn't an issue, but check your project's status before launch and during any quiet period.

## Commands

| Command | Who | What |
|---|---|---|
| `/awie` | everyone | Private copy of the menu |
| `/stats` | everyone | Your stats |
| `/leaderboard` | everyone | Top 10 by score |
| `/setup_menu` | admin | Post the permanent menu in this channel |
| `/attendance_start <meeting_name>` | admin | Start tracking participants in the configured stage channel |
| `/attendance_stop` | admin | Stop tracking and save attendance durations |
| `/preview_challenge <1-18>` | admin | Try any challenge without saving results |
| `/raffle_export` | admin | `.txt` with each member's name repeated once per boost, ready to paste into the raffle wheel |
| `/reset_today @member` | admin | Let a member replay today (their score/streak are not reverted) |

"Admin" = anyone with the **Manage Server** permission.

## Viewing the data in Supabase
**Table Editor → `awie_users`** shows every member's score, current streak and highest streak (sortable, exportable to CSV).
**`awie_plays`** shows each daily attempt (`correct` / `incorrect` / `pending`).

## Before launch checklist
1. `/preview_challenge 1` … `18` to try every challenge (nothing is saved).
2. Have a couple of officers test a real Play of the Day, then clear the test data in Supabase → SQL Editor:
   ```sql
   truncate table public.awie_plays, public.awie_users;
   ```
3. Keep `LAUNCH_DATE=2026-10-25` — members see "Awie is almost ready!" until midnight Oct 25 (Manila time), exactly matching the planned launch.
4. Post the menu with `/setup_menu` at your launch event (Oct 24, 9–10 PM).

## Editing the questions
All content is in `challenges.json`. Four formats: `multiple_choice`, `connect_the_dots` (2–4 pairs), `wordle` (4–10 letter word), `coding` (answers checked by pattern). Copy an existing entry, change it, then run `python validate_challenges.py`.
The Play of the Week rotates at Sunday 12:00 AM, starting a Sunday–Saturday calendar week in the configured `TIMEZONE` (Asia/Manila by default), so everyone gets the same challenge all week. Each challenge appears once per 18-week cycle; add more before the cycle repeats.

## Editing the rules
The streak rules live in two places that must match: `game_logic.py` (`apply_result`, used by the self-tests) and the `awie_finish_play` function in `schema.sql` (what the live bot uses, so the score and streak update together in one step). The 20-points-per-boost rule is `RAFFLE_STEP` in `game_logic.py`.

## Rules the bot follows (please confirm these match your intent)
- **One Play of the Day per member per day**, resetting at midnight Manila time. Points are given only for correct answers.
- **Abandoning counts as a loss.** Once someone starts, they have `SESSION_MINUTES` (default 10) to answer; otherwise it counts as a loss. This stops people from peeking at the question and retrying.
- **Streak**: the paper says "3 correct answers across 3 consecutive Plays of the Day = Streak 1". The bot counts consecutive *plays* (missing a day doesn't break it). To also require daily play, set `STREAK_REQUIRES_DAILY=true`.
- **Wordle** gives 6 guesses; the result only counts once the word is solved or all guesses are used.
- **Coding Proper** checks for specific accepted answers (ignoring spacing and quote style), so it's a "fill in the line" format rather than free-form code.
- **Raffle boosts** are the *extra* slots (score ÷ 20, rounded down). Members' regular raffle entry is unchanged.

## Security
- Never post your Discord bot token or your Supabase secret key. If either leaks, reset it (Discord: **Reset Token**; Supabase: rotate the key) and update `.env`.
- The tables have Row Level Security turned on with no public access, so the public API key cannot read or change anything.
