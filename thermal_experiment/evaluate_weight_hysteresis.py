import csv
from pathlib import Path

FILES = sorted(Path(".").glob("thermal_predictor_shadow_*.csv"))
WEIGHTS = (1, 2, 3)
HOLDS = (2, 3, 4)

def candidate_scores(row, weight):
    return (
        2 * int(row["gpu_temp_rising"])
        + int(row["gpu_freq_increasing"])
        + int(row["gpu_activity_increasing"])
        + weight * int(row["cpu_temp_rising"])
        + int(row["cpu_active"])
        + int(row["recent_transition"])
    )

def replay(rows, weight, hold):
    state = "KEEP"
    high = low = 0
    states = []

    for row in rows:
        score = candidate_scores(row, weight)

        if score >= 4:
            high += 1
            low = 0
        elif score <= 2:
            low += 1
            high = 0
        else:
            high = low = 0

        if state == "KEEP" and high >= hold:
            state = "REVIEW"
            high = low = 0
        elif state == "REVIEW" and low >= hold:
            state = "KEEP"
            high = low = 0

        states.append(state)

    return states

stats = {
    (w, h): {
        "changes": 0,
        "review": 0,
        "active_n": 0,
        "active_review": 0,
        "rising_n": 0,
        "rising_review": 0,
        "outside_n": 0,
        "outside_review": 0,
    }
    for w in WEIGHTS for h in HOLDS
}

for path in FILES:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        continue

    required = {
        "elapsed_s", "phase", "dynamic_score",
        "cpu_active", "cpu_temp_rising",
        "gpu_temp_rising", "gpu_freq_increasing",
        "gpu_activity_increasing", "recent_transition",
    }
    if not required.issubset(rows[0]):
        continue

    rows.sort(key=lambda r: float(r["elapsed_s"]))

    for w in WEIGHTS:
        for h in HOLDS:
            states = replay(rows, w, h)
            s = stats[(w, h)]
            s["changes"] += sum(
                a != b for a, b in zip(states, states[1:])
            )
            s["review"] += states.count("REVIEW")

            for row, state in zip(rows, states):
                review = state == "REVIEW"
                active = row["phase"] == "CPU_ACTIVE"
                rising = row["cpu_temp_rising"] == "1"

                if active:
                    s["active_n"] += 1
                    s["active_review"] += review

                if rising:
                    s["rising_n"] += 1
                    s["rising_review"] += review

                if not active:
                    s["outside_n"] += 1
                    s["outside_review"] += review

def percent(hit, n):
    return f"{100 * hit / n:.1f}%" if n else "N/A"

print("WEIGHT x HYSTERESIS OFFLINE REPLAY")
print("Thresholds: enter >=4, exit <=2")
print("weight hold changes review_samples "
      "active_coverage rising_temp_coverage outside_coverage")

for w in WEIGHTS:
    for h in HOLDS:
        s = stats[(w, h)]
        print(
            w, h, s["changes"], s["review"],
            percent(s["active_review"], s["active_n"]),
            percent(s["rising_review"], s["rising_n"]),
            percent(s["outside_review"], s["outside_n"]),
        )

print("Offline only. No live settings changed.")
