import csv
from pathlib import Path

FILE = Path("thermal_predictor_shadow_20261029_002346.csv")
ENTER_SCORE = 4
EXIT_SCORE = 2
HOLD_COUNT = 3

with FILE.open(newline="") as f:
    rows = list(csv.DictReader(f))

if not rows:
    raise SystemExit("ERROR: CSV has no data rows.")

def number(row, key):
    try:
        return float(row[key])
    except (KeyError, ValueError, TypeError):
        return float("nan")

# Reconstruct the offline three-sample hold rule.
# Scores 3 and other intermediate scores reset both counters.
held = False
high_count = low_count = 0
events = []

for i, r in enumerate(rows):
    score = number(r, "dynamic_score")
    old_state = held

    if score >= ENTER_SCORE:
        high_count += 1
        low_count = 0
    elif score <= EXIT_SCORE:
        low_count += 1
        high_count = 0
    else:
        high_count = low_count = 0

    if not held and high_count >= HOLD_COUNT:
        held = True
        high_count = low_count = 0
        events.append((i, "ENTER"))

    elif held and low_count >= HOLD_COUNT:
        held = False
        high_count = low_count = 0
        events.append((i, "EXIT"))

def temp_delta(i, seconds):
    target = number(rows[i], "elapsed_s") - seconds
    candidates = [
        j for j in range(i)
        if number(rows[j], "elapsed_s") <= target
    ]
    if not candidates:
        return None
    j = candidates[-1]
    dt = number(rows[i], "elapsed_s") - number(rows[j], "elapsed_s")
    if dt <= 0:
        return None
    return (
        number(rows[i], "cpu_tctl_C")
        - number(rows[j], "cpu_tctl_C"),
        dt,
        rows[j]["timestamp"]
    )

print(f"File: {FILE}")
print(f"Rows: {len(rows)}")
print(f"Reconstructed hold transitions: {len(events)}")
print("\nTRANSITIONS")
print("TYPE  TIME                 PHASE          CPU_C  SCORE  DELTA_3S  DELTA_5S")

for i, kind in events:
    r = rows[i]
    d3 = temp_delta(i, 3)
    d5 = temp_delta(i, 5)
    fmt = lambda d: "N/A" if d is None else f"{d[0]:+5.2f}C"
    print(
        f"{kind:5} {r['timestamp']:19} "
        f"{r['phase']:14} {number(r, 'cpu_tctl_C'):6.2f} "
        f"{number(r, 'dynamic_score'):5.0f} "
        f"{fmt(d3):>8} {fmt(d5):>8}"
    )

print("\nTEMPERATURE TREND WHILE HELD")
print("TIME                 CPU_C  SCORE  DELTA_3S  DELTA_5S")

held = False
high_count = low_count = 0
for i, r in enumerate(rows):
    score = number(r, "dynamic_score")
    if score >= ENTER_SCORE:
        high_count += 1
        low_count = 0
    elif score <= EXIT_SCORE:
        low_count += 1
        high_count = 0
    else:
        high_count = low_count = 0

    if not held and high_count >= HOLD_COUNT:
        held = True
        high_count = low_count = 0
    elif held and low_count >= HOLD_COUNT:
        held = False
        high_count = low_count = 0

    if held:
        d3 = temp_delta(i, 3)
        d5 = temp_delta(i, 5)
        fmt = lambda d: "N/A" if d is None else f"{d[0]:+5.2f}C"
        print(
            f"{r['timestamp']:19} {number(r, 'cpu_tctl_C'):6.2f} "
            f"{score:5.0f} {fmt(d3):>8} {fmt(d5):>8}"
        )

print("\nNOTE: Deltas are observed temperature changes, not predictions.")
print("This analysis does not change the live scheduler or predictor.")
