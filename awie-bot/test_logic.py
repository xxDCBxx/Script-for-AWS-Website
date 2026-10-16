"""Quick self-checks for the game rules. Run:  python test_logic.py

(The streak rules also exist inside schema.sql so the database can update them atomically; keep the two
in sync. See README -> "Editing the rules".)
"""
from game_logic import apply_result, check_code, raffle_boosts, score_wordle

# --- streaks: 3 wins in a row = Streak 1, then +1 per win; a loss resets; highest is kept
state = (0, 0, 0)
for correct, expect_streak in [(True, 0), (True, 0), (True, 1), (True, 2), (True, 3), (False, 0), (True, 0)]:
    state = apply_result(*state, correct)
    assert state[1] == expect_streak, (correct, state)
assert state[2] == 3, "highest streak must survive a reset"

# --- raffle boosts: every 20 points = +1
for score, boosts in [(0, 0), (19, 0), (20, 1), (42, 2), (59, 2), (60, 3)]:
    assert raffle_boosts(score) == boosts, score

# --- wordle scoring (incl. repeated letters)
assert "".join(score_wordle("BUCKET", "BUCKET")) == "GGGGGG"
assert "".join(score_wordle("BUTTER", "BUCKET")) == "GGYXGX"
assert "".join(score_wordle("zzzzzz", "BUCKET")) == "XXXXXX"

# --- code checking
pats = [r"table\.put_item\(Item=\{'id':'001'\}\)"]
assert check_code(pats, "table.put_item(Item={'id': '001'})")
assert check_code(pats, '```python\ntable.put_item(Item={"id": "001"})\n```')
assert not check_code(pats, "table.put_item(Item={'id': '002'})")

print("All logic tests passed.")
