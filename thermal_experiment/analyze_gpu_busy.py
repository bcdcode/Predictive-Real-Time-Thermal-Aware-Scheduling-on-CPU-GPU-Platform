import csv
import math
from collections import defaultdict

FILE = "rt_tas_gpu_busy_aligned.csv"

rows = []

with open(FILE, newline="") as f:
    for r in csv.DictReader(f):
        rows.append({
            "phase": r["phase"],
            "busy": float(r["gpu_busy_percent"]),
            "cpu": float(r["cpu_tctl_C"]),
            "gpu": float(r["gpu_edge_C"]),
            "freq": float(r["gpu_freq_MHz"])
        })

def correlation(x, y):
    n = len(x)
    if n < 3:
        return float("nan")

    mx = sum(x) / n
    my = sum(y) / n

    numerator = sum((a-mx)*(b-my) for a,b in zip(x,y))
    dx = sum((a-mx)**2 for a in x)
    dy = sum((b-my)**2 for b in y)

    denominator = math.sqrt(dx*dy)

    return numerator / denominator if denominator else float("nan")

print("Samples:", len(rows))

busy = [r["busy"] for r in rows]
gpu_temp = [r["gpu"] for r in rows]
cpu_temp = [r["cpu"] for r in rows]
gpu_freq = [r["freq"] for r in rows]

print("\n===== OVERALL CORRELATION =====")
print("GPU busy vs GPU temperature:",
      round(correlation(busy, gpu_temp), 4))
print("GPU busy vs CPU temperature:",
      round(correlation(busy, cpu_temp), 4))
print("GPU busy vs GPU frequency:",
      round(correlation(busy, gpu_freq), 4))

print("\n===== GPU BUSY DISTRIBUTION =====")

buckets = defaultdict(list)

for r in rows:
    if r["busy"] < 1:
        label = "0%"
    elif r["busy"] < 5:
        label = "1-4%"
    elif r["busy"] < 10:
        label = "5-9%"
    elif r["busy"] < 15:
        label = "10-14%"
    else:
        label = "15%+"

    buckets[label].append(r["gpu"])

for label, values in buckets.items():
    print("%-10s N=%3d Avg_GPU_Temp=%.2f C" %
          (label, len(values), sum(values)/len(values)))

print("\n===== TEMPERATURE CHANGE VS GPU BUSY =====")

for i in range(1, len(rows)):
    if rows[i]["phase"] != rows[i-1]["phase"]:
        continue

    dt = 1.0
    dgpu = (rows[i]["gpu"] - rows[i-1]["gpu"]) / dt
    dcpu = (rows[i]["cpu"] - rows[i-1]["cpu"]) / dt

    print("%-16s busy=%5.1f%% GPU_dT=%7.3f CPU_dT=%7.3f" %
          (rows[i]["phase"], rows[i]["busy"], dgpu, dcpu))
