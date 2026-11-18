import csv
import math
from collections import defaultdict

INPUT = "rt_tas_v8_loro_predictions.csv"

methods = {
    "V8_RIDGE": "predicted",
    "PERSISTENCE": "current",
    "LINEAR_TREND": "trend"
}

# Group by sensor, run and phase
groups = defaultdict(list)

with open(INPUT, newline="") as f:
    reader = csv.DictReader(f)

    for row in reader:
        sensor = row["sensor"]
        run = row["test_run"]
        phase = row["phase"]
        actual = float(row["actual"])

        for method, column in methods.items():
            predicted = float(row[column])
            error = predicted - actual

            groups[(sensor, run, phase, method)].append(error)


def metrics(errors):
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    bias = sum(errors) / n
    return n, mae, rmse, bias


# Detailed run-wise phase results
run_results = []

for key in sorted(groups):
    sensor, run, phase, method = key
    n, mae, rmse, bias = metrics(groups[key])

    run_results.append({
        "sensor": sensor,
        "test_run": run,
        "phase": phase,
        "method": method,
        "samples": n,
        "mae": mae,
        "rmse": rmse,
        "bias": bias
    })

with open("rt_tas_v8_run_phase_metrics.csv", "w", newline="") as f:
    fields = [
        "sensor", "test_run", "phase", "method",
        "samples", "mae", "rmse", "bias"
    ]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(run_results)


# Pool predictions across all six runs for each phase
pooled = defaultdict(list)

for (sensor, run, phase, method), errors in groups.items():
    pooled[(sensor, phase, method)].extend(errors)

print("\nV8 PHASE-WISE VALIDATION")
print("=" * 105)
print(
    f"{'SENSOR':<7} {'PHASE':<20} {'METHOD':<15} "
    f"{'N':>5} {'MAE':>10} {'RMSE':>10} {'BIAS':>10}"
)

phase_results = []

for key in sorted(pooled):
    sensor, phase, method = key
    n, mae, rmse, bias = metrics(pooled[key])

    print(
        f"{sensor:<7} {phase:<20} {method:<15} "
        f"{n:>5} {mae:>10.4f} {rmse:>10.4f} {bias:>+10.4f}"
    )

    phase_results.append({
        "sensor": sensor,
        "phase": phase,
        "method": method,
        "samples": n,
        "mae": mae,
        "rmse": rmse,
        "bias": bias
    })

with open("rt_tas_v8_phase_metrics.csv", "w", newline="") as f:
    fields = [
        "sensor", "phase", "method",
        "samples", "mae", "rmse", "bias"
    ]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(phase_results)

print("\n" + "=" * 105)
print("VALIDATION COMPLETE")
print("Pooled phase results: rt_tas_v8_phase_metrics.csv")
print("Run-wise phase results: rt_tas_v8_run_phase_metrics.csv")
