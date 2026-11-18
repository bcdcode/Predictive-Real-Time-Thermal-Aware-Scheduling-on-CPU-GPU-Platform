#!/usr/bin/env python3
import csv
from collections import defaultdict
from statistics import mean

FILE = "rt_tas_controlled_20261026_221300.csv"

groups = defaultdict(list)

with open(FILE, newline="") as f:
    reader = csv.DictReader(f)

    required = {
        "phase", "cpu_tctl_C", "gpu_edge_C",
        "cpu6_freq_MHz", "gpu_freq_MHz",
        "cpu_active", "gpu_enabled"
    }
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise SystemExit(f"Missing columns: {sorted(missing)}")

    for row in reader:
        try:
            row["cpu_tctl_C"] = float(row["cpu_tctl_C"])
            row["gpu_edge_C"] = float(row["gpu_edge_C"])
            row["cpu6_freq_MHz"] = float(row["cpu6_freq_MHz"])
            row["gpu_freq_MHz"] = float(row["gpu_freq_MHz"])
        except (ValueError, TypeError):
            continue

        groups[row["phase"]].append(row)

print(f"Baseline dataset: {FILE}")
print(f"{'Phase':<20} {'N':>4} "
      f"{'CPU avg':>8} {'CPU max':>8} "
      f"{'GPU avg':>8} {'GPU max':>8} "
      f"{'CPU MHz':>9} {'GPU MHz':>9}")

for phase, rows in groups.items():
    cpu = [r["cpu_tctl_C"] for r in rows]
    gpu = [r["gpu_edge_C"] for r in rows]
    cf = [r["cpu6_freq_MHz"] for r in rows]
    gf = [r["gpu_freq_MHz"] for r in rows]

    print(f"{phase:<20} {len(rows):>4} "
          f"{mean(cpu):>8.2f} {max(cpu):>8.2f} "
          f"{mean(gpu):>8.2f} {max(gpu):>8.2f} "
          f"{mean(cf):>9.1f} {mean(gf):>9.1f}")

print("\nWorkload-state counts:")
for phase, rows in groups.items():
    states = sorted({
        (r["cpu_active"], r["gpu_enabled"]) for r in rows
    })
    print(f"{phase}: {states}")

print("\nBaseline analysis complete. No workload controls were changed.")
