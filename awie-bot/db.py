"""Supabase (Postgres) storage for Build With Awie! (users, scores, streaks, daily plays).

All writes that must be consistent (starting a play, scoring it, updating streaks) happen inside the
database functions defined in schema.sql, so they are atomic. Every function here is async.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx
from supabase import AsyncClient, acreate_client

log = logging.getLogger("awie.db")

_client: AsyncClient | None = None
_PAGE = 1000  # Supabase returns at most 1000 rows per request


async def init() -> None:
    """Connect to Supabase and make sure schema.sql has been run."""
    global _client
    url, key = os.getenv("DISCORD_SUPABASE_URL"), os.getenv("DISCORD_SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("DISCORD_SUPABASE_URL and DISCORD_SUPABASE_KEY must be set in .env")
    _client = await acreate_client(url, key)
    try:
        await _client.rpc("awie_get_user", {"p_user_id": 0}).execute()
        await _client.rpc("awie_get_play", {"p_user_id": 0, "p_play_date": "2000-01-01"}).execute()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Could not read the Supabase tables. Check DISCORD_SUPABASE_URL / DISCORD_SUPABASE_KEY (use the secret or "
            "service_role key, not the anon key) and make sure you ran schema.sql in the SQL Editor. "
            f"Details: {exc}"
        ) from exc


async def _retry(make_request):
    """Run a Supabase request, retrying a couple of times on network hiccups."""
    for attempt in range(3):
        try:
            return await make_request()
        except httpx.TransportError:
            if attempt == 2:
                raise
            log.warning("Supabase network error, retrying (%d/2)", attempt + 1)
            await asyncio.sleep(0.5 * (attempt + 1))


def _db() -> AsyncClient:
    assert _client is not None, "db.init() has not been called"
    return _client


async def get_user(user_id: int) -> dict | None:
    res = await _retry(lambda: _db().rpc("awie_get_user", {"p_user_id": user_id}).execute())
    return res.data or None


async def get_play(user_id: int, play_date: str) -> dict | None:
    """Returns {'status', 'points', 'challenge_id', 'age_seconds'} or None."""
    res = await _retry(
        lambda: _db().rpc("awie_get_play", {"p_user_id": user_id, "p_play_date": play_date}).execute()
    )
    return res.data or None


async def start_play(user_id: int, name: str, play_date: str, challenge_id: str) -> bool:
    """Reserve today's Play of the Day. False if the member already has one for that date."""
    res = await _retry(
        lambda: _db()
        .rpc(
            "awie_start_play",
            {"p_user_id": user_id, "p_name": name, "p_play_date": play_date, "p_challenge_id": challenge_id},
        )
        .execute()
    )
    return bool(res.data)


async def finish_play(
    user_id: int, play_date: str, correct: bool, points: int, daily: bool = False
) -> dict | None:
    """Resolve a pending play and update score/streaks atomically. None if it wasn't pending.

    daily=True means a skipped calendar day also breaks the streak (STREAK_REQUIRES_DAILY).
    """
    res = await _retry(
        lambda: _db()
        .rpc(
            "awie_finish_play",
            {
                "p_user_id": user_id,
                "p_play_date": play_date,
                "p_correct": correct,
                "p_points": points,
                "p_daily": daily,
            },
        )
        .execute()
    )
    return res.data or None


async def top_users(limit: int = 10) -> list[dict]:
    res = await _retry(lambda: _db().rpc("awie_top_users", {"p_limit": limit}).execute())
    return res.data or []


async def all_users() -> list[dict]:
    res = await _retry(lambda: _db().rpc("awie_all_users", {}).execute())
    return res.data or []


async def delete_play(user_id: int, play_date: str) -> bool:
    """Admin tool: remove a member's play for a date so they can replay. Score is NOT reverted."""
    res = await _retry(
        lambda: _db().table("awie_plays").delete().eq("user_id", user_id).eq("play_date", play_date).execute()
    )
    return bool(res.data)
