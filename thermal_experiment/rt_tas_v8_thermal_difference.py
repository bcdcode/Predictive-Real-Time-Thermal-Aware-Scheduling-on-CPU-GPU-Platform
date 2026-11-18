import csv
import math
from collections import defaultdict

FILES = [
    ("RUN1", "rt_tas_gpu_busy_aligned.csv"),
    ("RUN2", "rt_tas_gpu_busy_20261105.csv"),
    ("RUN3", "rt_tas_gpu_busy_20261105_run3.csv"),
    ("RUN4", "rt_tas_gpu_busy_20261107_run4.csv"),
    ("RUN5", "rt_tas_gpu_busy_20261107_run5.csv"),
    ("RUN6", "rt_tas_gpu_busy_20261107_run6.csv"),
]

groups = defaultdict(list)

for run, filename in FILES:
    with open(filename, newline="") as f:
        for r in csv.DictReader(f):
            try:
                cpu = float(r["cpu_tctl_C"])
                gpu = float(r["gpu_edge_C"])
                delta = gpu - cpu

                if math.isfinite(delta):
                    groups[(run, r["phase"])].append(delta)
            except (ValueError, TypeError, KeyError):
                pass

print("\nGPU-CPU TEMPERATURE DIFFERENCE")
print("=" * 100)
print(
    f"{'RUN':<10} {'PHASE':<20} {'N':>5} "
    f"{'MEAN DELTA':>13} {'STD':>10} {'MIN':>10} {'MAX':>10}"
)

for (run, phase), values in sorted(groups.items()):
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean)**2 for x in values) / n
    std = math.sqrt(variance)

    print(
        f"{run:<10} {phase:<20} {n:>5} "
        f"{mean:>13.3f} {std:>10.3f} "
        f"{min(values):>10.3f} {max(values):>10.3f}"
    )
