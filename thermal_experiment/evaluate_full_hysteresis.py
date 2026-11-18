import csv
from pathlib import Path
from collections import Counter

FILE = Path("thermal_predictor_shadow_20261029_222853.csv")
ENTER_SCORE = 4
EXIT_SCORE = 2

with FILE.open(newline="") as f:
    rows = list(csv.DictReader(f))

if not rows:
    raise SystemExit("ERROR: CSV has no samples")

rows.sort(key=lambda r: float(r["elapsed_s"]))

def raw_state(row):
    # Use the actual predictor's action label.
    action = row["recommended_action"]
    if "KEEP_TWFD_UNCHANGED" in action:
        return "KEEP"
    if "REVIEW_TWFD_PLACEMENT" in action:
        return "REVIEW"
    return "OTHER"

def replay(hold_count):
    state = "KEEP"
    high = low = 0
    states = []
    events = []

    for i, row in enumerate(rows):
        score = float(row["dynamic_score"])

        if score >= ENTER_SCORE:
            high += 1
            low = 0
        elif score <= EXIT_SCORE:
            low += 1
            high = 0
        else:
            high = low = 0

        previous = state

        if state == "KEEP" and high >= hold_count:
            state = "REVIEW"
            high = low = 0
        elif state == "REVIEW" and low >= hold_count:
            state = "KEEP"
            high = low = 0

        states.append(state)

        if state != previous:
            events.append((i, row, state))

    return states, events

def count_changes(states):
    return sum(a != b for a, b in zip(states, states[1:]))

actual = [raw_state(r) for r in rows]

print("FULL-TIMELINE OFFLINE HYSTERESIS TEST")
print("File:", FILE)
print("Samples:", len(rows))
print("Actual action labels:", dict(Counter(actual)))
print("Actual action changes:", count_changes(actual))
print()

for count in (2, 3, 4):
    states, events = replay(count)
    print(
        f"HOLD={count}: changes={len(events)}, "
        f"review_samples={states.count('REVIEW')}, "
        f"keep_samples={states.count('KEEP')}"
    )

    for i, row, state in events:
        print(
            f"  t={float(row['elapsed_s']):.1f}s "
            f"{row['timestamp']} phase={row['phase']} "
            f"CPU={row['cpu_tctl_C']}C "
            f"score={row['dynamic_score']} -> {state}"
        )

    print()

print("Per-phase candidate-state counts:")
for phase in sorted(set(r["phase"] for r in rows)):
    indices = [i for i, r in enumerate(rows) if r["phase"] == phase]
    print(f"  {phase}: samples={len(indices)}")
    for count in (2, 3, 4):
        states, _ = replay(count)
        counts = Counter(states[i] for i in indices)
        print(
            f"    hold={count}: "
            f"KEEP={counts['KEEP']}, REVIEW={counts['REVIEW']}"
        )

print()
print("Offline only: no live files or scheduler settings changed.")
print("Note: candidate thresholds (enter >=4, exit <=2) are experimental.")
