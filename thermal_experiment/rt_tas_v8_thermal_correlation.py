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

                if math.isfinite(cpu) and math.isfinite(gpu):
                    groups[(run, r["phase"])].append((cpu, gpu))
            except (ValueError, TypeError, KeyError):
                pass


def correlation(data):
    n = len(data)
    if n < 3:
        return float("nan")

    xs = [x for x, y in data]
    ys = [y for x, y in data]

    mx = sum(xs) / n
    my = sum(ys) / n

    numerator = sum((x-mx)*(y-my) for x, y in data)
    dx = sum((x-mx)**2 for x in xs)
    dy = sum((y-my)**2 for y in ys)

    if dx == 0 or dy == 0:
        return float("nan")

    return numerator / math.sqrt(dx * dy)


print("\nCPU-GPU THERMAL CORRELATION")
print("=" * 90)
print(f"{'RUN':<10} {'PHASE':<20} {'N':>5} {'CPU AVG':>10} {'GPU AVG':>10} {'CORRELATION':>13}")

for (run, phase), data in sorted(groups.items()):
    n = len(data)
    cpu_avg = sum(x for x, y in data) / n
    gpu_avg = sum(y for x, y in data) / n
    corr = correlation(data)

    print(
        f"{run:<10} {phase:<20} {n:>5} "
        f"{cpu_avg:>10.3f} {gpu_avg:>10.3f} {corr:>13.4f}"
    )
