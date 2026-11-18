import csv
from collections import defaultdict

groups = defaultdict(list)

with open("rt_tas_v8_loro_predictions.csv", newline="") as f:
    for r in csv.DictReader(f):
        if r["sensor"] != "GPU":
            continue

        groups[(r["test_run"], r["phase"])].append({
            "elapsed": int(float(r["elapsed_s"])),
            "error": float(r["predicted"]) - float(r["actual"])
        })

print("\nGPU RIDGE ERROR: FIRST HALF VS SECOND HALF")
print("=" * 100)
print(
    f"{'RUN':<15} {'PHASE':<20} {'PERIOD':<12} "
    f"{'N':>5} {'MAE':>10} {'BIAS':>10}"
)

for (run, phase), rows in sorted(groups.items()):
    rows.sort(key=lambda x: x["elapsed"])
    midpoint = len(rows) // 2

    for period, subset in [
        ("FIRST_HALF", rows[:midpoint]),
        ("SECOND_HALF", rows[midpoint:])
    ]:
        errors = [x["error"] for x in subset]
        n = len(errors)

        mae = sum(abs(e) for e in errors) / n
        bias = sum(errors) / n

        print(
            f"{run:<15} {phase:<20} {period:<12} "
            f"{n:>5} {mae:>10.4f} {bias:>+10.4f}"
        )
