import csv
import math

prefix = "rt_tas_v3_1_BASELINE_20261109_211245"

with open(prefix + ".csv", newline="") as f:
    telemetry = list(csv.DictReader(f))

with open(prefix + "_live_predictions.csv", newline="") as f:
    predictions = list(csv.DictReader(f))

# Actual telemetry indexed by elapsed second
actual = {
    int(float(r["elapsed_s"])): r
    for r in telemetry
}

print("\nV3.1 BASELINE: ONE-SECOND FORECAST VALIDATION")
print("=" * 70)

models = [
    ("CPU", "cpu_predicted_1s_C", "cpu_tctl_C"),
    ("GPU", "gpu_predicted_1s_C", "gpu_edge_C")
]

for target, predicted_col, telemetry_col in models:

    errors = []

    print(f"\n{target} PREDICTIONS")
    print("-" * 70)

    for p in predictions:

        if p["phase"] != "TA_GPU":
            continue

        if p["prediction_status"] != "FORECAST_ONLY":
            continue

        t = int(float(p["elapsed_s"]))

        # One-second-ahead actual temperature
        future = actual.get(t + 1)

        if future is None:
            continue

        if future["phase"] != "TA_GPU":
            continue

        pred = float(p[predicted_col])
        measured = float(future[telemetry_col])

        error = pred - measured
        errors.append(error)

        print(
            f"t={t:2d} | predicted={pred:7.3f} "
            f"| actual(t+1)={measured:7.3f} "
            f"| error={error:+7.3f}"
        )

    if not errors:
        print("No valid aligned samples.")
        continue

    mae = sum(abs(e) for e in errors) / len(errors)
    bias = sum(errors) / len(errors)
    rmse = math.sqrt(sum(e*e for e in errors) / len(errors))

    print("\nSamples:", len(errors))
    print("MAE:  ", round(mae, 4), "C")
    print("RMSE: ", round(rmse, 4), "C")
    print("Bias: ", round(bias, 4), "C")

print("\nValidation completed.")
