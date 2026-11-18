import csv
from collections import defaultdict

RT_FILE = "rt_tas_controlled_20261103_135006.csv"
GPU_FILE = "gpu_busy_test_20261103_135010.csv"
OUTPUT = "rt_tas_gpu_busy_aligned.csv"

# Read GPU busy measurements
gpu_data = {}

with open(GPU_FILE, newline="") as f:
    for row in csv.DictReader(f):
        timestamp = row["timestamp"].strip()

        if timestamp in gpu_data:
            raise ValueError("Duplicate GPU timestamp: " + timestamp)

        gpu_data[timestamp] = float(row["gpu_busy_percent"])

# Read and synchronize RT-TAS measurements
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

# Save aligned dataset
if merged:
    fields = list(merged[0].keys())

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(merged)

print("\n===== SYNCHRONIZATION REPORT =====")
print("RT-TAS samples       :", len(merged) + len(unmatched))
print("GPU busy samples     :", len(gpu_data))
print("Matched samples      :", len(merged))
print("Unmatched RT samples :", len(unmatched))
print("Output               :", OUTPUT)

# Per-phase GPU utilization statistics
phase_values = defaultdict(list)

for row in merged:
    phase_values[row["phase"]].append(
        float(row["gpu_busy_percent"])
    )

print("\n===== GPU BUSY BY PHASE =====")
print("%-20s %8s %12s %12s" %
      ("PHASE", "SAMPLES", "AVERAGE %", "MAXIMUM %"))

for phase, values in sorted(phase_values.items()):
    print("%-20s %8d %12.2f %12.2f" %
          (phase, len(values),
           sum(values) / len(values), max(values)))

print("\n===== FIRST 5 ALIGNED ROWS =====")

for row in merged[:5]:
    print(row["timestamp"],
          row["phase"],
          "CPU:", row["cpu_tctl_C"],
          "GPU:", row["gpu_edge_C"],
          "GPU busy:", row["gpu_busy_percent"], "%")
