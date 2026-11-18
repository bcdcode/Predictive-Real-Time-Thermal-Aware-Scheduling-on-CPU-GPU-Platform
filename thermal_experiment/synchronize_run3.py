import csv
from collections import defaultdict

RT_FILE = "rt_tas_controlled_20261105_222247.csv"
GPU_FILE = "gpu_busy_experiment_20261105_222245.csv"
OUTPUT = "rt_tas_gpu_busy_20261105_run3.csv"

gpu_data = {}

with open(GPU_FILE, newline="") as f:
    for row in csv.DictReader(f):
        gpu_data[row["timestamp"].strip()] = float(
            row["gpu_busy_percent"]
        )

merged = []
unmatched = []

with open(RT_FILE, newline="") as f:
    for row in csv.DictReader(f):
        timestamp = row["timestamp"].strip()

        if timestamp not in gpu_data:
            unmatched.append(timestamp)
            continue

        row["gpu_busy_percent"] = gpu_data[timestamp]
        merged.append(row)

if not merged:
    raise SystemExit("ERROR: No matching timestamps.")

with open(OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
    writer.writeheader()
    writer.writerows(merged)

print("\n===== RUN 3 SYNCHRONIZATION =====")
print("RT-TAS samples:", len(merged) + len(unmatched))
print("GPU busy samples:", len(gpu_data))
print("Matched samples:", len(merged))
print("Unmatched RT samples:", len(unmatched))
print("Match rate: %.2f%%" %
      (100 * len(merged) / (len(merged) + len(unmatched))))
print("Output:", OUTPUT)

phase_data = defaultdict(list)

for row in merged:
    phase_data[row["phase"]].append(
        float(row["gpu_busy_percent"])
    )

print("\n===== GPU BUSY BY PHASE =====")
print("%-20s %8s %12s %12s" %
      ("PHASE", "SAMPLES", "AVERAGE %", "MAXIMUM %"))

for phase, values in sorted(phase_data.items()):
    print("%-20s %8d %12.2f %12.2f" %
          (phase, len(values), sum(values)/len(values), max(values)))
