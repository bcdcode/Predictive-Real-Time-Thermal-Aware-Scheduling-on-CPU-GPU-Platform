import csv
from pathlib import Path

FILE = Path("thermal_predictor_shadow_20261029_002346.csv")
ENTER_SCORE = 4
EXIT_SCORE = 2
HOLD_COUNT = 3
LIMITS = [None, 0.125, 0.25, 0.50, 1.00]

with FILE.open(newline="") as f:
    rows = list(csv.DictReader(f))

if not rows:
    raise SystemExit("ERROR: CSV contains no rows.")

def val(i, key):
    return float(rows[i][key])

def delta3(i):
    now = val(i, "elapsed_s")
    candidates = [
        j for j in range(i)
        if 2.5 <= now - val(j, "elapsed_s") <= 3.5
    ]
    if not candidates:
        return None
    j = min(candidates, key=lambda k:
            abs((now - val(k, "elapsed_s")) - 3.0))
    return val(i, "cpu_tctl_C") - val(j, "cpu_tctl_C")

def simulate(limit, policy):
    held = False
    high = low = 0
    events = []
    held_samples = 0
    blocked = missing = 0

    for i, row in enumerate(rows):
        score = val(i, "dynamic_score")

        if score >= ENTER_SCORE:
            high += 1
            low = 0
        elif score <= EXIT_SCORE:
            low += 1
            high = 0
        else:
            high = low = 0

        if not held:
            if high >= HOLD_COUNT:
                held = True
                events.append((i, "ENTER"))
                high = low = 0
            continue

        held_samples += 1

        if low < HOLD_COUNT:
            continue

        d = delta3(i)
        allowed = (
            limit is None or
            (d is not None and d <= limit)
        )

        if allowed:
            held = False
            events.append((i, "EXIT"))
            high = low = 0
        else:
            blocked += 1
            if d is None:
                missing += 1
            if policy == "fresh":
                low = 0

    return events, held_samples, held, blocked, missing

print("Offline replay for", FILE)
print("Policy: persistent = keep checking; fresh = reconfirm 3 low samples")
print()
print(f"{'LIMIT':10} {'POLICY':11} {'TRANS':>5} {'ENTER':>5} "
      f"{'EXIT':>5} {'HELD':>6} {'BLOCKED':>8} {'NO_DELTA':>8} {'END_HELD':>9}")
print("-" * 85)

for limit in LIMITS:
    for policy in ("persistent", "fresh"):
        events, held_n, end_held, blocked, missing = simulate(limit, policy)
        enters = sum(kind == "ENTER" for _, kind in events)
        exits = sum(kind == "EXIT" for _, kind in events)
        label = "BASELINE" if limit is None else f"{limit:.3f} C"
        print(f"{label:10} {policy:11} {len(events):5} {enters:5} "
              f"{exits:5} {held_n:6} {blocked:8} {missing:8} "
              f"{str(end_held):>9}")

print("\nNo source CSV or live scheduler files were changed.")
