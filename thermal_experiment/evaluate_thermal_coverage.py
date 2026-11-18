import csv
from pathlib import Path

FILES = sorted(Path(".").glob("thermal_predictor_shadow_*.csv"))

def replay(rows, hold):
    state = "KEEP"
    high = low = 0
    states = []

    for row in rows:
        score = float(row["dynamic_score"])

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

totals = {
    h: {
        "active": [0, 0],
        "rising": [0, 0],
        "idle": [0, 0],
        "review_rising": 0,
    }
    for h in (2, 3, 4)
}

used = 0

for path in FILES:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        continue

    required = {
        "elapsed_s", "phase", "dynamic_score",
        "cpu_temp_rising", "recommended_action"
    }
    if not required.issubset(rows[0]):
        continue

    rows.sort(key=lambda r: float(r["elapsed_s"]))
    used += 1

    for h in (2, 3, 4):
        states = replay(rows, h)

        for row, state in zip(rows, states):
            review = state == "REVIEW"
            phase = row["phase"]
            rising = row["cpu_temp_rising"] == "1"

            if phase == "CPU_ACTIVE":
                totals[h]["active"][0] += 1
                totals[h]["active"][1] += review

            if rising:
                totals[h]["rising"][0] += 1
                totals[h]["rising"][1] += review
                if review:
                    totals[h]["review_rising"] += 1

            if phase != "CPU_ACTIVE":
                totals[h]["idle"][0] += 1
                totals[h]["idle"][1] += review

print(f"Recordings analysed: {used}")
print("Thresholds: enter >=4, exit <=2")
print("Coverage = REVIEW samples / samples in category")
print()

for h in (2, 3, 4):
    t = totals[h]
    print(f"HOLD {h}")
    for name, label in (
        ("active", "CPU_ACTIVE"),
        ("rising", "CPU_TEMP_RISING"),
        ("idle", "NOT_CPU_ACTIVE"),
    ):
        n, review = t[name]
        pct = 100 * review / n if n else 0
        print(
            f"  {label}: REVIEW {review}/{n} "
            f"({pct:.1f}%)"
        )
    print()

print("Offline only; no live settings changed.")
print("Coverage is descriptive, not proof of thermal danger or benefit.")
