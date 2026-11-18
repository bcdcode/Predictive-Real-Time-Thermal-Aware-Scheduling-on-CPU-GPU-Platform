import csv
from collections import defaultdict

RT_FILE = "rt_tas_controlled_20261107_152329.csv"
GPU_FILE = "gpu_busy_experiment_20261107_152327.csv"
OUTPUT = "rt_tas_gpu_busy_20261107_run4.csv"

# Read GPU busy measurements
gpu_data = {}

with open(GPU_FILE, newline="") as f:
    for row in csv.DictReader(f):
        timestamp = row["timestamp"].strip()
        gpu_data[timestamp] = float(row["gpu_busy_percent"])

# Synchronize with RT-TAS timestamps
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

# Write a separate output file
with open(OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
    writer.writeheader()
    writer.writerows(merged)

print("\n===== RUN 4 SYNCHRONIZATION REPORT =====")
print("RT-TAS samples:", len(merged) + len(unmatched))
print("GPU busy samples:", len(gpu_data))
print("Matched samples:", len(merged))
print("Unmatched RT samples:", len(unmatched))
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
          (phase, len(values),
           sum(values) / len(values), max(values)))

print("\n===== FIRST FIVE SAMPLES =====")

for row in merged[:5]:
    print(row["timestamp"], row["phase"],
          "GPU busy:", row["gpu_busy_percent"])

print("\n===== OUTPUT VALIDATION =====")
with open(OUTPUT, newline="") as f:
    result = list(csv.DictReader(f))

print("Output rows:", len(result))
print("Output columns:", len(result[0]))
print("Last sample:", result[-1]["timestamp"])
