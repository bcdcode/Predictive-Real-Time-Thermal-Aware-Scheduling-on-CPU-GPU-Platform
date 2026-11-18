import csv
import math
from collections import defaultdict

FILES = [
    ("RUN1_NOV03", "rt_tas_gpu_busy_aligned.csv"),
    ("RUN2_NOV05", "rt_tas_gpu_busy_20261105.csv"),
    ("RUN3_NOV05", "rt_tas_gpu_busy_20261105_run3.csv"),
    ("RUN4_NOV07", "rt_tas_gpu_busy_20261107_run4.csv"),
    ("RUN5_NOV07", "rt_tas_gpu_busy_20261107_run5.csv"),
    ("RUN6_NOV07", "rt_tas_gpu_busy_20261107_run6.csv"),
]

FEATURES = [
    "gpu_edge_C",
    "gpu_freq_MHz",
    "gpu_activity_proxy",
    "gpu_busy_percent",
    "cpu_tctl_C",
    "cpu6_freq_MHz",
]

groups = defaultdict(list)

for run, filename in FILES:
    with open(filename, newline="") as f:
        for row in csv.DictReader(f):
            phase = row["phase"]
            values = {}

            for feature in FEATURES:
                try:
                    value = float(row[feature])
                    if math.isfinite(value):
                        values[feature] = value
                except (ValueError, TypeError):
                    pass

            groups[(run, phase)].append(values)


def stats(values):
    if not values:
        return None

    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n

    return mean, math.sqrt(variance), min(values), max(values)


print("\nV8 TRAINING DATA — FEATURE COMPARISON")
print("=" * 145)

for feature in FEATURES:
    print(f"\nFEATURE: {feature}")
    print("-" * 125)
    print(
        f"{'RUN':<15} {'PHASE':<20} {'N':>4} "
        f"{'MEAN':>11} {'STD':>10} {'MIN':>11} {'MAX':>11}"
    )

    for (run, phase), rows in sorted(groups.items()):
        values = [
            row[feature] for row in rows
            if feature in row
        ]

        result = stats(values)
        if result is None:
            continue

        mean, std, minimum, maximum = result

        print(
            f"{run:<15} {phase:<20} {len(values):>4} "
            f"{mean:>11.3f} {std:>10.3f} "
            f"{minimum:>11.3f} {maximum:>11.3f}"
        )

print("\nCOMPARISON COMPLETE")
