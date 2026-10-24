"""Pure game rules for Build With Awie! (no Discord or database code here, so it is easy to test)."""
from __future__ import annotations

import random
import re
from datetime import date, timedelta
from typing import Iterable

# Points for a CORRECT answer, per challenge format (from the concept paper).
POINTS = {
    "multiple_choice": 1,
    "connect_the_dots": 3,
    "wordle": 3,
    "coding": 5,
}

RAFFLE_STEP = 20        # every 20 points = +1 raffle boost
STREAK_TO_START = 3     # 3 correct Plays of the Day in a row = Streak 1


def week_start_for(d: date) -> date:
    """Return the Sunday date that identifies the Sunday-Saturday week containing d."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def skipped_week(last_play_date: date | None, current_week_start: date) -> bool:
    """Whether at least one Sunday-Saturday week passed without a completed play."""
    return last_play_date is not None and (current_week_start - last_play_date).days > 7


def challenge_index_for(d: date, count: int) -> int:
    """Return a stable, shuffled challenge index for the Sunday-Saturday week containing d."""
    if count <= 0:
        raise ValueError("count must be positive")

    epoch_sunday = date(2025, 1, 5)
    week_start = week_start_for(d)
    week_number = (week_start - epoch_sunday).days // 7
    cycle, week_in_cycle = divmod(week_number, count)

    indices = list(range(count))
    random.Random(cycle).shuffle(indices)
    return indices[week_in_cycle]


def raffle_boosts(score: int) -> int:
    """Every 20 points = +1 raffle boost (extra name slot on the raffle wheel)."""
    return max(0, score) // RAFFLE_STEP


def apply_result(consecutive_wins: int, current_streak: int, highest_streak: int, correct: bool):
    """Update streak state after one Play of the Week.

    - 3 correct Plays in a row  -> Streak = 1
    - every further correct Play -> Streak + 1
    - a loss                     -> streak AND the 3-in-a-row progress reset to 0
    - the highest streak is never lowered
    Returns (consecutive_wins, current_streak, highest_streak).
    """
    if not correct:
        return 0, 0, highest_streak
    consecutive_wins += 1
    if consecutive_wins >= STREAK_TO_START:
        current_streak = consecutive_wins - STREAK_TO_START + 1
    return consecutive_wins, current_streak, max(highest_streak, current_streak)


def score_wordle(guess: str, secret: str) -> list[str]:
    """Standard Wordle scoring. Returns a list of 'G' (right spot), 'Y' (wrong spot), 'X' (absent)."""
    guess, secret = guess.upper(), secret.upper()
    result = ["X"] * len(secret)
    unmatched: dict[str, int] = {}
    for i, (g, s) in enumerate(zip(guess, secret)):
        if g == s:
            result[i] = "G"
        else:
            unmatched[s] = unmatched.get(s, 0) + 1
    for i, g in enumerate(guess):
        if result[i] == "G":
            continue
        if unmatched.get(g, 0) > 0:
            result[i] = "Y"
            unmatched[g] -= 1
    return result


def normalize_code(text: str) -> str:
    """Strip code fences, unify quotes and remove all whitespace so answers can be pattern-matched."""
    text = re.sub(r"```[a-zA-Z]*", "", text).replace("`", "")
    text = text.replace('"', "'")
    return re.sub(r"\s+", "", text)


def check_code(patterns: Iterable[str], text: str) -> bool:
    """True if the normalized answer fully matches any accepted pattern."""
    normalized = normalize_code(text)
    return any(re.fullmatch(p, normalized) for p in patterns)
