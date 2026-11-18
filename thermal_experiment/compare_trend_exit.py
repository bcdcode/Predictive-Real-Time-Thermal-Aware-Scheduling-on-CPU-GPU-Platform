import csv
from pathlib import Path

FILE = Path("thermal_predictor_shadow_20261029_002346.csv")
ENTER_SCORE = 4
EXIT_SCORE = 2
HOLD_COUNT = 3
TREND_LIMITS = [None, 0.125, 0.25, 0.50, 1.00]

with FILE.open(newline="") as f:
    rows = list(csv.DictReader(f))

if not rows:
    raise SystemExit("ERROR: No CSV data found.")

def val(row, key):
    return float(row[key])

def delta_over_3s(i):
    now = val(rows[i], "elapsed_s")
    candidates = [
        j for j in range(i)
        if now - val(rows[j], "elapsed_s") >= 2.5
        and now - val(rows[j], "elapsed_s") <= 3.5
    ]
    if not candidates:
        return None
    j = min(candidates, key=lambda k: abs(
        (now - val(rows[k], "elapsed_s")) - 3.0
    ))
    return val(rows[i], "cpu_tctl_C") - val(rows[j], "cpu_tctl_C")

def simulate(limit):
    held = False
    high = low = 0
    events = []
    held_samples = 0
    blocked_exits = 0

    for i, row in enumerate(rows):
        score = val(row, "dynamic_score")

        if score >= ENTER_SCORE:
            high += 1
            low = 0
        elif score <= EXIT_SCORE:
            low += 1
            high = 0
        else:
            high = low = 0

        if not held and high >= HOLD_COUNT:
            held = True
            events.append((i, "ENTER"))
            high = low = 0

        elif held:
            held_samples += 1
            if low >= HOLD_COUNT:
                d3 = delta_over_3s(i)
                trend_ok = (
                    limit is None or
                    (d3 is not None and d3 <= limit)
                )
                if trend_ok:
                    held = False
                    events.append((i, "EXIT"))
                    high = low = 0
                else:
                    blocked_exits += 1

    return events, held_samples, held, blocked_exits

print("Offline comparison; trend = CPU temperature delta over ~3 seconds")
print("Limit(C)  Transitions  Entries  Exits  HeldSamples  EndHeld  BlockedChecks")

for limit in TREND_LIMITS:
    events, samples, end_held, blocked = simulate(limit)
    entries = sum(kind == "ENTER" for _, kind in events)
    exits = sum(kind == "EXIT" for _, kind in events)
    label = "BASELINE" if limit is None else f"{limit:.3f}"
    print(
        f"{label:9} {len(events):11} {entries:8} {exits:6} "
        f"{samples:12} {str(end_held):8} {blocked:13}"
    )

print("\nEVENTS for each variant")
for limit in TREND_LIMITS:
    events, _, end_held, _ = simulate(limit)
    label = "BASELINE" if limit is None else f"{limit:.3f} C"
    print(f"\n{label}")
    for i, kind in events:
        r = rows[i]
        d3 = delta_over_3s(i)
        dtext = "N/A" if d3 is None else f"{d3:+.3f} C"
        print(
            f"  {kind:5} {r['timestamp']} "
            f"CPU={val(r, 'cpu_tctl_C'):.2f} C "
            f"score={val(r, 'dynamic_score'):.0f} "
            f"delta3s={dtext}"
        )
    if end_held:
        print("  NOTE: review remained active at end of recording.")

print("\nNo source CSV or live scheduler files were changed.")
