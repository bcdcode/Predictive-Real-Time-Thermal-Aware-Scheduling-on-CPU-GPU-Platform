import csv
import math
from collections import defaultdict

FILES = [
    "rt_tas_v3_3_BASELINE_20261111_151301_live_predictions.csv",
    "rt_tas_v3_3_BASELINE_20261111_160419_live_predictions.csv",
    "rt_tas_v3_3_BASELINE_20261111_162636_live_predictions.csv",
]

METHODS = {
    "CPU": {
        "V8": "cpu_v8_predicted_1s_C",
        "Persistence": "cpu_persistence_predicted_1s_C",
        "Trend": "cpu_trend_predicted_1s_C",
        "Hybrid": "cpu_hybrid_predicted_1s_C",
    },
    "GPU": {
        "V8": "gpu_v8_predicted_1s_C",
        "Persistence": "gpu_persistence_predicted_1s_C",
        "Trend": "gpu_trend_predicted_1s_C",
        "Hybrid": "gpu_hybrid_predicted_1s_C",
    },
}

ACTUAL = {
    "CPU": "cpu_actual_C",
    "GPU": "gpu_actual_C",
}

overall = {
    target: defaultdict(list)
    for target in METHODS
}

by_phase = {
    target: defaultdict(lambda: defaultdict(list))
    for target in METHODS
}

def num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None

for filename in FILES:
    with open(filename, newline="") as f:
        rows = list(csv.DictReader(f))

    run_valid = 0

    for i in range(len(rows) - 1):
        current = rows[i]
        nxt = rows[i + 1]

        if current["prediction_status"] != "FORECAST_ONLY":
            continue

        if current["phase"] != nxt["phase"]:
            continue

        t0 = num(current["elapsed_s"])
        t1 = num(nxt["elapsed_s"])

        if t0 is None or t1 is None:
            continue

        if abs((t1 - t0) - 1.0) > 0.10:
            continue

        run_valid += 1
        phase = current["phase"]

        for target, methods in METHODS.items():
            actual = num(nxt[ACTUAL[target]])

            if actual is None:
                continue

            for method, key in methods.items():
                predicted = num(current[key])

                if predicted is None:
                    continue

                error = actual - predicted
                overall[target][method].append(error)
                by_phase[target][phase][method].append(error)

    print(f"{filename}: {run_valid} valid forecast transitions")

def print_table(title, data):
    print("\n" + title)
    print("-" * 72)
    print(f"{'Method':<15}{'N':>6}{'MAE':>12}{'RMSE':>12}{'Bias':>12}")

    for method in METHODS[target]:
        errors = data.get(method, [])
        if not errors:
            continue

        n = len(errors)
        mae = sum(abs(e) for e in errors) / n
        rmse = math.sqrt(sum(e*e for e in errors) / n)
        bias = sum(errors) / n

        print(
            f"{method:<15}{n:>6}"
            f"{mae:>12.4f}{rmse:>12.4f}{bias:>12.4f}"
        )

print("\nV3.3 POOLED EVALUATION: RUN 1 + RUN 2")
print("Error = actual at t+1 minus prediction at t")
print("Positive bias = underprediction")

for target in ("CPU", "GPU"):
    print_table(target + " OVERALL", overall[target])

    for phase in ("IDLE_BASELINE1", "TA_GPU", "COOLDOWN2"):
        if phase in by_phase[target]:
            print_table(
                target + " - " + phase,
                by_phase[target][phase]
            )

print("\nPooled evaluation completed.")
