import csv
from pathlib import Path

FILE = Path("thermal_predictor_shadow_20261029_222853.csv")
ENTER_SCORE = 4
EXIT_SCORE = 2
HOLD_COUNT = 3

with FILE.open(newline="") as f:
    rows = list(csv.DictReader(f))

if not rows:
    raise SystemExit("ERROR: No samples found.")

def score(row):
    return float(row["dynamic_score"])

def replay(selected, hold_count):
    state = "KEEP"
    high = low = 0
    changes = []
    states = []

    for i, row in enumerate(selected):
        s = score(row)

        if s >= ENTER_SCORE:
            high += 1
            low = 0
        elif s <= EXIT_SCORE:
            low += 1
            high = 0
        else:
            high = low = 0

        old = state

        if state == "KEEP" and high >= hold_count:
            state = "REVIEW"
            high = low = 0
        elif state == "REVIEW" and low >= hold_count:
            state = "KEEP"
            high = low = 0

        states.append(state)

        if state != old:
            changes.append({
                "index": i,
                "timestamp": row["timestamp"],
                "elapsed": float(row["elapsed_s"]),
                "phase": row["phase"],
                "temp": row["cpu_tctl_C"],
                "score": s,
                "state": state,
            })

    return states, changes

print("Offline recommendation-hysteresis comparison")
print("Input:", FILE)
print("KEEP = keep TWFD unchanged; REVIEW = review placement")
print()

for phase in ("CPU_ACTIVE", "IDLE_OR_OTHER"):
    selected = [r for r in rows if r["phase"] == phase]
    if not selected:
        continue

    print(f"\nPHASE: {phase}, samples={len(selected)}")

    # Baseline: raw score threshold, no consecutive-sample requirement.
    baseline = [
        "REVIEW" if score(r) >= ENTER_SCORE else "KEEP"
        for r in selected
    ]
    baseline_changes = sum(
        baseline[i] != baseline[i - 1]
        for i in range(1, len(baseline))
    )

    print(f"Raw threshold changes: {baseline_changes}")

    for count in (2, 3, 4):
        states, changes = replay(selected, count)
        print(
            f"Hold={count}: changes={len(changes)}, "
            f"review_samples={states.count('REVIEW')}, "
            f"keep_samples={states.count('KEEP')}"
        )

        for event in changes:
            print(
                f"  {event['timestamp']} "
                f"t={event['elapsed']:.1f}s "
                f"CPU={event['temp']}C score={event['score']:.0f} "
                f"-> {event['state']}"
            )

print("\nOffline replay only; live predictor and scheduler unchanged.")
