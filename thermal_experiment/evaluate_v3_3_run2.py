import csv
import math
from collections import defaultdict

FILE = "rt_tas_v3_3_BASELINE_20261111_160419_live_predictions.csv"

with open(FILE, newline="") as f:
    rows = list(csv.DictReader(f))

cpu_methods = {
    "V8": "cpu_v8_predicted_1s_C",
    "Persistence": "cpu_persistence_predicted_1s_C",
    "Trend": "cpu_trend_predicted_1s_C",
    "Hybrid": "cpu_hybrid_predicted_1s_C",
}

gpu_methods = {
    "V8": "gpu_v8_predicted_1s_C",
    "Persistence": "gpu_persistence_predicted_1s_C",
    "Trend": "gpu_trend_predicted_1s_C",
    "Hybrid": "gpu_hybrid_predicted_1s_C",
}

def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None

results = {
    "CPU": defaultdict(list),
    "GPU": defaultdict(list)
}

phase_results = {
    "CPU": defaultdict(lambda: defaultdict(list)),
    "GPU": defaultdict(lambda: defaultdict(list))
}

for i in range(len(rows) - 1):
    current = rows[i]
    nxt = rows[i + 1]

    if current["prediction_status"] != "FORECAST_ONLY":
        continue

    if current["phase"] != nxt["phase"]:
        continue

    t0 = number(current["elapsed_s"])
    t1 = number(nxt["elapsed_s"])

    if t0 is None or t1 is None or abs((t1-t0)-1.0) > 0.10:
        continue

    phase = current["phase"]

    for target, methods, actual_key in [
        ("CPU", cpu_methods, "cpu_actual_C"),
        ("GPU", gpu_methods, "gpu_actual_C")
    ]:
        actual = number(nxt[actual_key])

        if actual is None:
            continue

        for method, pred_key in methods.items():
            predicted = number(current[pred_key])

            if predicted is None:
                continue

            error = actual - predicted
            results[target][method].append(error)
            phase_results[target][phase][method].append(error)

def report(title, data):
    print("\n" + title)
    print("-" * 75)
    print(f"{'Method':<15}{'N':>6}{'MAE':>12}{'RMSE':>12}{'Bias':>12}")

    for method, errors in data.items():
        n = len(errors)
        if not n:
            continue

        mae = sum(abs(e) for e in errors) / n
        rmse = math.sqrt(sum(e*e for e in errors) / n)
        bias = sum(errors) / n

        print(f"{method:<15}{n:>6}{mae:>12.4f}{rmse:>12.4f}{bias:>12.4f}")

print("V3.3 RUN1: ONE-STEP-AHEAD EVALUATION")
print("Actual at t+1 compared with prediction made at t")
print("Positive bias = underprediction")
print("Negative bias = overprediction")

for target in ("CPU", "GPU"):
    report(target + " OVERALL", results[target])

    for phase, methods in phase_results[target].items():
        report(target + " - " + phase, methods)

print("\nEvaluation completed.")
