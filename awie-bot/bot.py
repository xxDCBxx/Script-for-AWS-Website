"""Build With Awie! - Discord bot for AWS Student Builder Group - UPHSL."""
from __future__ import annotations

import io
import json
import logging
import os
import random
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=False)

import db  # noqa: E402  (after load_dotenv so the Supabase settings from .env are available)
from game_logic import (  # noqa: E402
    POINTS,
    RAFFLE_STEP,
    STREAK_TO_START,
    check_code,
    challenge_index_for,
    raffle_boosts,
    score_wordle,
)

log = logging.getLogger("awie")

# ----------------------------------------------------------------------------- config
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # your server ID -> slash commands appear instantly
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Manila"))
LAUNCH_DATE = date.fromisoformat(os.getenv("LAUNCH_DATE")) if os.getenv("LAUNCH_DATE") else None
STREAK_REQUIRES_WEEKLY = os.getenv("STREAK_REQUIRES_WEEKLY", "false").lower() == "true"
SESSION_MINUTES = int(os.getenv("SESSION_MINUTES", "10"))  # time allowed to answer once started

ORANGE, GREEN, RED = 0xFF9900, 0x2ECC71, 0xE74C3C
TYPE_LABEL = {
    "multiple_choice": "Multiple Choice",
    "connect_the_dots": "Connect the Dots",
    "wordle": "Wordle",
    "coding": "Coding Proper",
}

CHALLENGES: list[dict] = json.loads(
    (Path(__file__).parent / "challenges.json").read_text(encoding="utf-8")
)


# ----------------------------------------------------------------------------- helpers
def today_local() -> date:
    return datetime.now(TZ).date()


def challenge_for(d: date) -> dict:
    """Return the shared challenge for the calendar week containing d."""
    return CHALLENGES[challenge_index_for(d, len(CHALLENGES))]


def is_admin(interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild


def menu_embed() -> discord.Embed:
    e = discord.Embed(
        title="🤖 Build With Awie!",
        description=(
            "Hi, I'm **Awie**! I'm building a system on AWS and I need your help.\n\n"
            "🎮 **Play of the Week** - solve this week's AWS challenge, earn points and build a streak.\n"
            "📊 **Stats** - see your score, streak and raffle boosts."
        ),
        color=ORANGE,
    )
    e.set_footer(text="AWS Student Builder Group - UPHSL")
    return e


async def stats_embed(user: discord.abc.User) -> discord.Embed:
    row = await db.get_user(user.id)
    score = row["score"] if row else 0
    cur = row["current_streak"] if row else 0
    best = row["highest_streak"] if row else 0
    boosts = raffle_boosts(score)
    to_next = RAFFLE_STEP - (score % RAFFLE_STEP)
    e = discord.Embed(
        title="🤖 Awie's Stats",
        description=(
            f"👤 **Name:** {user.display_name}\n"
            f"⭐ **Score:** {score} points\n"
            f"🔥 **Current Streak:** {cur}\n"
            f"🏆 **Highest Streak:** {best}\n"
            f"🎟️ **Raffle Boosts:** +{boosts}"
        ),
        color=ORANGE,
    )
    e.set_footer(text=f"{to_next} more point(s) until your next raffle boost")
    return e


def result_embed(ch: dict, correct: bool, points: int, result: dict | None, detail: str | None, recorded: bool):
    e = discord.Embed(
        title="✅ Nice work!" if correct else "❌ Not this time",
        color=GREEN if correct else RED,
    )
    lines = [f"You earned **+{points} point{'s' if points != 1 else ''}**."] if correct else [
        "No points this round - but every attempt teaches something!"
    ]
    if detail:
        lines.append(detail)
    e.description = "\n\n".join(lines)
    e.add_field(name="💡 Awie's Trivia", value=ch["trivia"], inline=False)

    if result:
        if result["streak_lost"]:
            streak_line = f"💔 Your streak of **{result['previous_streak']}** was reset."
        elif correct and result["current_streak"] > 0:
            prefix = "🔥 Streak unlocked! " if result["streak_started"] else "🔥 "
            streak_line = f"{prefix}Current streak: **{result['current_streak']}**"
        elif correct:
            streak_line = (
                f"Streak progress: **{result['consecutive_wins']}/{STREAK_TO_START}** wins in a row"
            )
        else:
            streak_line = "Streak progress reset - win again to rebuild it."
        e.add_field(
            name="📊 Your totals",
            value=(
                f"⭐ Score: **{result['score']}**  ·  🎟️ Raffle boosts: **+{raffle_boosts(result['score'])}**\n"
                f"{streak_line}"
            ),
            inline=False,
        )
    if not recorded:
        e.set_footer(text="Preview mode - nothing was saved.")
    return e


# ----------------------------------------------------------------------------- challenge views
class ChallengeView(discord.ui.View):
    """Base class: one view per Play of the Week session (only the player can use it)."""

    def __init__(self, challenge: dict, user_id: int, play_date: str, record: bool):
        super().__init__(timeout=SESSION_MINUTES * 60)
        self.challenge = challenge
        self.user_id = user_id
        self.play_date = play_date
        self.record = record
        self.finished = False
        self.origin: discord.Interaction | None = None

    # subclasses return the challenge-specific part of the message
    def body(self) -> str:
        raise NotImplementedError

    def intro_embed(self) -> discord.Embed:
        ch = self.challenge
        e = discord.Embed(
            title="🤖 Awie needs your help!",
            description=f"{ch['scenario']}\n\n{self.body()}",
            color=ORANGE,
        )
        pts = POINTS[ch["type"]]
        e.set_footer(
            text=f"{TYPE_LABEL[ch['type']]} · +{pts} point{'s' if pts != 1 else ''} · "
            f"answer within {SESSION_MINUTES} minutes"
        )
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This challenge belongs to someone else.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction: discord.Interaction, correct: bool, detail: str | None = None):
        if self.finished:
            return
        self.finished = True
        self.stop()
        # Saving to the database can take a moment; acknowledge now (Discord allows only 3 seconds).
        await interaction.response.defer()
        points = POINTS[self.challenge["type"]] if correct else 0
        result = None
        if self.record:
            try:
                result = await db.finish_play(
                    self.user_id, self.play_date, correct, points, daily=STREAK_REQUIRES_WEEKLY
                )
            except Exception:  # noqa: BLE001
                log.exception("Could not save result for user %s", self.user_id)
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="⚠️ Awie couldn't save your result",
                        description="There was a connection problem, so your answer wasn't recorded. "
                        "Please tell an officer - they can reset your Play of the Week so you can try again.",
                        color=RED,
                    ),
                    view=None,
                )
                return
        embed = result_embed(self.challenge, correct, points, result, detail, self.record)
        await interaction.edit_original_response(embed=embed, view=None)

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        if self.record:
            try:
                await db.finish_play(self.user_id, self.play_date, False, 0, daily=STREAK_REQUIRES_WEEKLY)
            except Exception:  # noqa: BLE001
                log.exception("Could not record timeout for user %s", self.user_id)
        if self.origin:
            e = discord.Embed(
                title="⏰ Time's up!",
                description="This Play of the Week session expired and counted as a loss. Try again next week!",
                color=RED,
            )
            e.add_field(name="💡 Awie's Trivia", value=self.challenge["trivia"], inline=False)
            try:
                await self.origin.edit_original_response(embed=e, view=None)
            except discord.HTTPException:
                pass


class MultipleChoiceView(ChallengeView):
    def __init__(self, *args):
        super().__init__(*args)
        for i in range(len(self.challenge["options"])):
            btn = discord.ui.Button(label="ABCDE"[i], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def body(self) -> str:
        opts = "\n".join(f"**{'ABCDE'[i]}.** {o}" for i, o in enumerate(self.challenge["options"]))
        return f"**{self.challenge['question']}**\n\n{opts}"

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            ch = self.challenge
            correct = index == ch["answer"]
            detail = None
            if not correct:
                detail = f"The answer was **{'ABCDE'[ch['answer']]}. {ch['options'][ch['answer']]}**."
            await self.finish(interaction, correct, detail)

        return callback


class ConnectTheDotsView(ChallengeView):
    def __init__(self, *args):
        super().__init__(*args)
        pairs = self.challenge["pairs"]
        self.shuffled = [p[1] for p in pairs]
        random.shuffle(self.shuffled)
        self.choice: list[int | None] = [None] * len(pairs)

        for i, (left, _right) in enumerate(pairs):
            select = discord.ui.Select(
                placeholder=f"{i + 1}. {left} →"[:150],
                options=[discord.SelectOption(label=r[:100], value=str(j)) for j, r in enumerate(self.shuffled)],
                row=i,
            )
            select.callback = self._make_callback(i, select)
            self.add_item(select)

    def body(self) -> str:
        lines = []
        for i, (left, _r) in enumerate(self.challenge["pairs"]):
            picked = self.choice[i]
            target = f"**{self.shuffled[picked]}**" if picked is not None else "*(not selected yet)*"
            lines.append(f"{i + 1}. **{left}** → {target}")
        remaining = self.choice.count(None)
        footer = f"\n\n*{remaining} selection{'s' if remaining != 1 else ''} remaining — answers lock in automatically when all are chosen.*"
        return f"{self.challenge['instructions']}\n\n" + "\n".join(lines) + footer

    def _make_callback(self, i: int, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            j = int(select.values[0])
            self.choice[i] = j
            for opt in select.options:
                opt.default = opt.value == str(j)
            # Auto-submit once every dropdown has been answered
            if all(c is not None for c in self.choice):
                await self._submit(interaction)
            else:
                await interaction.response.edit_message(embed=self.intro_embed(), view=self)

        return callback

    async def _submit(self, interaction: discord.Interaction):
        pairs = self.challenge["pairs"]
        marks, wrong = [], 0
        for i, (left, right) in enumerate(pairs):
            ok = self.shuffled[self.choice[i]] == right
            wrong += 0 if ok else 1
            marks.append(f"{'✅' if ok else '❌'} **{left}** → {right}")
        detail = "**Correct connections:**\n" + "\n".join(marks)
        await self.finish(interaction, wrong == 0, detail)


class GuessModal(discord.ui.Modal):
    def __init__(self, view: "WordleView"):
        super().__init__(title="Wordle: guess the AWS term")
        self.wordle = view
        n = len(view.secret)
        self.guess = discord.ui.TextInput(
            label=f"Your {n}-letter guess", min_length=n, max_length=n, placeholder="Type your guess"
        )
        self.add_item(self.guess)

    async def on_submit(self, interaction: discord.Interaction):
        guess = self.guess.value.strip().upper()
        if not guess.isalpha() or len(guess) != len(self.wordle.secret):
            await interaction.response.send_message(
                f"Guesses must be {len(self.wordle.secret)} letters (A-Z only).", ephemeral=True
            )
            return
        await self.wordle.handle_guess(interaction, guess)


class WordleView(ChallengeView):
    MAX_ATTEMPTS = 6
    EMOJI = {"G": "🟩", "Y": "🟨", "X": "⬛"}

    def __init__(self, *args):
        super().__init__(*args)
        self.secret = self.challenge["word"].upper()
        self.guesses: list[str] = []

    def board(self) -> str:
        rows = [
            "".join(self.EMOJI[c] for c in score_wordle(g, self.secret)) + f"  `{g}`"
            for g in self.guesses
        ]
        rows += ["⬜" * len(self.secret)] * (self.MAX_ATTEMPTS - len(self.guesses))
        return "\n".join(rows)

    def body(self) -> str:
        return (
            f"**Clue:** {self.challenge['clue']}\n"
            f"Guess the AWS term in **{self.MAX_ATTEMPTS} tries**. "
            "🟩 right spot · 🟨 wrong spot · ⬛ not in the word\n\n" + self.board()
        )

    @discord.ui.button(label="Make a guess", emoji="⌨️", style=discord.ButtonStyle.primary)
    async def guess_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GuessModal(self))

    async def handle_guess(self, interaction: discord.Interaction, guess: str):
        if self.finished:
            return
        self.guesses.append(guess)
        if guess == self.secret:
            await self.finish(
                interaction, True, f"{self.board()}\n\nSolved in **{len(self.guesses)}/{self.MAX_ATTEMPTS}**!"
            )
        elif len(self.guesses) >= self.MAX_ATTEMPTS:
            await self.finish(interaction, False, f"{self.board()}\n\nThe word was **{self.secret}**.")
        else:
            await interaction.response.edit_message(embed=self.intro_embed(), view=self)


class CodeModal(discord.ui.Modal):
    def __init__(self, view: "CodingView"):
        super().__init__(title="Coding Proper")
        self.coding = view
        self.code = discord.ui.TextInput(
            label="Your line of code", style=discord.TextStyle.paragraph, max_length=500,
            placeholder="Type only the missing line(s)",
        )
        self.add_item(self.code)

    async def on_submit(self, interaction: discord.Interaction):
        ch = self.coding.challenge
        correct = check_code(ch["accepted_patterns"], self.code.value)
        detail = f"**Reference solution:**\n```python\n{ch['example_answer']}\n```"
        await self.coding.finish(interaction, correct, detail)


class CodingView(ChallengeView):
    def body(self) -> str:
        return self.challenge["prompt"]

    @discord.ui.button(label="Write my code", emoji="💻", style=discord.ButtonStyle.primary)
    async def code_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CodeModal(self))


VIEW_FOR_TYPE = {
    "multiple_choice": MultipleChoiceView,
    "connect_the_dots": ConnectTheDotsView,
    "wordle": WordleView,
    "coding": CodingView,
}


# ----------------------------------------------------------------------------- main menu actions
async def start_play_of_the_week(interaction: discord.Interaction, preview_index: int | None = None):
    user = interaction.user
    today = today_local()
    iso = today.isoformat()

    # Database calls can take a moment; acknowledge right away (Discord allows only 3 seconds).
    await interaction.response.defer(ephemeral=True, thinking=True)

    if preview_index is None:
        if LAUNCH_DATE and today < LAUNCH_DATE and not is_admin(interaction):
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="🚀 Awie is almost ready!",
                    description=f"Play of the Week opens on **{LAUNCH_DATE:%B %d, %Y}**. See you then!",
                    color=ORANGE,
                )
            )
            return

        play = await db.get_play(user.id, iso)
        if play:
            await interaction.edit_original_response(content=await _existing_play_message(user.id, iso, play))
            return
        challenge = challenge_for(today)
        if not await db.start_play(user.id, user.display_name, iso, challenge["id"]):
            await interaction.edit_original_response(
                content="You already have this week's Play of the Week. Check **Stats** to see your progress!"
            )
            return
        record = True
    else:
        challenge = CHALLENGES[preview_index - 1]
        record = False

    view = VIEW_FOR_TYPE[challenge["type"]](challenge, user.id, iso, record)
    await interaction.edit_original_response(embed=view.intro_embed(), view=view)
    view.origin = interaction


async def _existing_play_message(user_id: int, iso: str, play: dict) -> str:
    if play["status"] == "pending":
        if play["age_seconds"] > (SESSION_MINUTES + 1) * 60:
            await db.finish_play(user_id, iso, False, 0, daily=STREAK_REQUIRES_WEEKLY)
            return "Your earlier session expired and counted as a loss. Come back next week for a new Play of the Week!"
        return (
            "You already have an active Play of the Week - finish it first! "
            f"(It expires {SESSION_MINUTES} minutes after you started.)"
        )
    icon = "✅" if play["status"] == "correct" else "❌"
    return (
        f"{icon} You've already played this week's Play of the Week. "
        f"A new one unlocks at midnight ({TZ.key}). Check **Stats** to see your progress!"
    )


class MainMenu(discord.ui.View):
    """Persistent menu: keeps working after the bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Play of the Week", emoji="🎮", style=discord.ButtonStyle.primary, custom_id="awie:play")
    async def play(self, interaction: discord.Interaction, button: discord.ui.Button):
        await start_play_of_the_week(interaction)

    @discord.ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="awie:stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.edit_original_response(embed=await stats_embed(interaction.user))


# ----------------------------------------------------------------------------- bot + commands
class AwieBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())

    async def setup_hook(self):
        await db.init()
        self.add_view(MainMenu())
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        log.info("Awie is online as %s (%d challenges loaded)", self.user, len(CHALLENGES))


bot = AwieBot()
admin_only = app_commands.checks.has_permissions(manage_guild=True)


@bot.tree.command(name="awie", description="Open the Build With Awie! menu")
@app_commands.guild_only()
async def awie_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=menu_embed(), view=MainMenu(), ephemeral=True)


@bot.tree.command(name="stats", description="See your Build With Awie! score, streaks and raffle boosts")
@app_commands.guild_only()
async def stats_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=await stats_embed(interaction.user), ephemeral=True)


@bot.tree.command(name="leaderboard", description="Top 10 builders by score")
@app_commands.guild_only()
async def leaderboard_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    rows = await db.top_users(10)
    if not rows:
        await interaction.followup.send("No scores yet - be the first to play!")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i] if i < 3 else f'**{i + 1}.**'} {r['name']} - {r['score']} pts "
        f"(🏆 best streak {r['highest_streak']})"
        for i, r in enumerate(rows)
    ]
    await interaction.followup.send(
        embed=discord.Embed(title="🏆 Awie's Leaderboard", description="\n".join(lines), color=ORANGE)
    )


@bot.tree.command(name="setup_menu", description="(Admin) Post the permanent Build With Awie! menu in this channel")
@app_commands.guild_only()
@admin_only
async def setup_menu_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=menu_embed(), view=MainMenu())


@bot.tree.command(name="preview_challenge", description="(Admin) Try any challenge without saving results")
@app_commands.describe(number=f"Challenge number, 1-{len(CHALLENGES)}")
@app_commands.guild_only()
@admin_only
async def preview_cmd(interaction: discord.Interaction, number: app_commands.Range[int, 1, len(CHALLENGES)]):
    await start_play_of_the_week(interaction, preview_index=number)


@bot.tree.command(name="raffle_export", description="(Admin) Export raffle boost entries (one name per extra slot)")
@app_commands.guild_only()
@admin_only
async def raffle_export_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    rows = [(r, raffle_boosts(r["score"])) for r in await db.all_users()]
    rows = [(r, b) for r, b in rows if b > 0]
    if not rows:
        await interaction.followup.send("Nobody has a raffle boost yet.", ephemeral=True)
        return
    names: list[str] = []
    for r, b in rows:
        names.extend([r["name"]] * b)
    summary = "\n".join(f"**{r['name']}** - {r['score']} pts → +{b} slot(s)" for r, b in rows[:25])
    if len(rows) > 25:
        summary += f"\n...and {len(rows) - 25} more (see the file)"
    file = discord.File(io.BytesIO("\n".join(names).encode("utf-8")), filename="raffle_boost_entries.txt")
    embed = discord.Embed(
        title="🎟️ Raffle Boost Entries",
        description=f"{summary}\n\n**{len(names)}** extra slots total. Paste the file's names into the raffle "
        "wheel on top of the regular entries.",
        color=ORANGE,
    )
    await interaction.followup.send(embed=embed, file=file, ephemeral=True)


@bot.tree.command(name="reset_this_week", description="(Admin) Let a member replay this week's Play of the Week")
@app_commands.describe(member="Member to reset (their score and streak are NOT reverted)")
@app_commands.guild_only()
@admin_only
async def reset_this_week_cmd(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    ok = await db.delete_play(member.id, today_local().isoformat())
    await interaction.followup.send(
        f"Reset this week's play for {member.display_name}." if ok else f"{member.display_name} has no play this week.",
        ephemeral=True,
    )


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the **Manage Server** permission to use this command."
    else:
        log.exception("Command error", exc_info=error)
        msg = "Oops, Awie hit a snag. Please try again."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and fill it in.")
    bot.run(TOKEN, log_handler=None)
