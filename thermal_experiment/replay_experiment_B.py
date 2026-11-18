import csv
from pathlib import Path

FILE = Path("thermal_predictor_shadow_20261029_232747.csv")
ENTER = 4
EXIT = 2
HOLD = 3

with FILE.open(newline="") as f:
    rows = list(csv.DictReader(f))

rows.sort(key=lambda r: float(r["elapsed_s"]))

def candidate_score(r, weight):
    return (
        2 * int(r["gpu_temp_rising"])
        + int(r["gpu_freq_increasing"])
        + int(r["gpu_activity_increasing"])
        + weight * int(r["cpu_temp_rising"])
        + int(r["cpu_active"])
        + int(r["recent_transition"])
    )

def replay(weight):
    state = "KEEP"
    high = low = 0
    states = []
    scores = []
    events = []

    for i, r in enumerate(rows):
        s = candidate_score(r, weight)
        scores.append(s)

        if s >= ENTER:
            high += 1
            low = 0
        elif s <= EXIT:
            low += 1
            high = 0
        else:
            high = low = 0

        old = state
        if state == "KEEP" and high >= HOLD:
            state = "REVIEW"
            high = low = 0
        elif state == "REVIEW" and low >= HOLD:
            state = "KEEP"
            high = low = 0

        states.append(state)
        if old != state:
            events.append((r, state, s))

    return states, scores, events

print("Experiment B: offline replay")
print("File:", FILE)
print("Entry >= 4; exit <= 2; hold = 3 consecutive samples")
print()

for weight in (1, 2, 3):
    states, scores, events = replay(weight)

    active_idx = [
        i for i, r in enumerate(rows)
        if r["phase"] == "CPU_ACTIVE"
    ]
    rising_idx = [
        i for i, r in enumerate(rows)
        if r["cpu_temp_rising"] == "1"
    ]
    outside_idx = [
        i for i, r in enumerate(rows)
        if r["phase"] != "CPU_ACTIVE"
    ]

    def coverage(indices):
        if not indices:
            return "N/A"
        n = sum(states[i] == "REVIEW" for i in indices)
        return f"{n}/{len(indices)} ({100*n/len(indices):.1f}%)"

    active_start = active_idx[0] if active_idx else None
    first_review = next(
        (i for i in active_idx if states[i] == "REVIEW"), None
    )

    delay = (
        float(rows[first_review]["elapsed_s"])
        - float(rows[active_start]["elapsed_s"])
        if first_review is not None and active_start is not None
        else None
    )

    print(f"CPU temperature weight = {weight}")
    print("  State changes:", len(events))
    print("  REVIEW samples:", states.count("REVIEW"))
    print("  CPU-active REVIEW:", coverage(active_idx))
    print("  Rising-temperature REVIEW:", coverage(rising_idx))
    print("  Outside-active REVIEW:", coverage(outside_idx))
    print(
        "  First REVIEW delay from CPU-active start:",
        f"{delay:.1f}s" if delay is not None else "not reached"
    )

    print("  Transitions:")
    for r, state, s in events:
        print(
            f"    t={float(r['elapsed_s']):.1f}s "
            f"phase={r['phase']} "
            f"CPU={float(r['cpu_tctl_C']):.2f}C "
            f"score={s} -> {state}"
        )
    print()

print("Offline only; no live settings changed.")
