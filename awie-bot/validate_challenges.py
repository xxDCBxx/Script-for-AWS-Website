"""Checks challenges.json for mistakes. Run this after adding or editing challenges:  python validate_challenges.py"""
import json
import re
import sys
from pathlib import Path

from game_logic import POINTS, check_code

data = json.loads((Path(__file__).parent / "challenges.json").read_text(encoding="utf-8"))
errors: list[str] = []
seen: set[str] = set()


def err(ch, msg):
    errors.append(f"[{ch.get('id', '?')}] {msg}")


for ch in data:
    if ch.get("id") in seen:
        err(ch, "duplicate id")
    seen.add(ch.get("id"))

    t = ch.get("type")
    if t not in POINTS:
        err(ch, f"unknown type {t!r}")
        continue
    for key in ("scenario", "trivia"):
        if not ch.get(key):
            err(ch, f"missing {key}")
    if len(ch.get("trivia", "")) > 1024:
        err(ch, "trivia is longer than 1024 characters (Discord limit)")

    if t == "multiple_choice":
        opts = ch.get("options", [])
        if not 2 <= len(opts) <= 5:
            err(ch, "needs 2-5 options")
        if not isinstance(ch.get("answer"), int) or not 0 <= ch["answer"] < len(opts):
            err(ch, "answer must be a valid option index (0-based)")
        if not ch.get("question"):
            err(ch, "missing question")

    elif t == "connect_the_dots":
        pairs = ch.get("pairs", [])
        if not 2 <= len(pairs) <= 5:
            err(ch, "needs 2-5 pairs (Discord allows 5 rows, one per pair, auto-submits on last selection)")
        rights = [p[1] for p in pairs]
        if len(set(rights)) != len(rights):
            err(ch, "right-hand items must be unique")
        if any(len(r) > 100 for r in rights):
            err(ch, "right-hand items must be 100 characters or fewer")
        if not ch.get("instructions"):
            err(ch, "missing instructions")

    elif t == "wordle":
        word = ch.get("word", "")
        if not word.isalpha() or not 4 <= len(word) <= 10:
            err(ch, "word must be 4-10 letters (A-Z only)")
        if not ch.get("clue"):
            err(ch, "missing clue")

    elif t == "coding":
        patterns = ch.get("accepted_patterns", [])
        if not patterns or not ch.get("prompt") or not ch.get("example_answer"):
            err(ch, "needs prompt, accepted_patterns and example_answer")
        for p in patterns:
            try:
                re.compile(p)
            except re.error as e:
                err(ch, f"bad regex {p!r}: {e}")
        if patterns and not check_code(patterns, ch.get("example_answer", "")):
            err(ch, "example_answer does not match its own accepted_patterns")

if errors:
    print("Problems found:")
    print("\n".join(" - " + e for e in errors))
    sys.exit(1)

counts: dict[str, int] = {}
for ch in data:
    counts[ch["type"]] = counts.get(ch["type"], 0) + 1
print(f"OK: {len(data)} challenges valid -> {counts}")
