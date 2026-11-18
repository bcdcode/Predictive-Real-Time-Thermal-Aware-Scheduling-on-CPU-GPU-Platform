import csv
from collections import defaultdict

INPUT = "gpu_busy_model_predictions_v8.csv"

phases = {"COOLDOWN1", "COOLDOWN2"}

# Group errors by held-out run and phase
groups = defaultdict(lambda: {
    "e": [], "f": [], "records": []
})

with open(INPUT, newline="") as f:
    reader = csv.DictReader(f)

    for row in reader:
        if (
            row["target"] != "CPU"
            or int(row["horizon_s"]) != 1
            or row["phase"] not in phases
        ):
            continue

        e = float(row["model_e_absolute_error_C"])
        fm = float(row["model_f_absolute_error_C"])

        key = (row["heldout_run"], row["phase"])

        groups[key]["e"].append(e)
        groups[key]["f"].append(fm)
        groups[key]["records"].append(row)

print("\n==============================================")
print("COOLDOWN MODEL E vs MODEL F DIAGNOSTICS")
print("CPU | 1-second horizon")
print("==============================================")

print(
    f"{'RUN':<16} {'PHASE':<12} {'E MAE':>9} "
    f"{'F MAE':>9} {'GAIN':>9} {'SAMPLES':>8}"
)
print("-" * 70)

for key in sorted(groups):
    data = groups[key]

    e_mae = sum(data["e"]) / len(data["e"])
    f_mae = sum(data["f"]) / len(data["f"])

    gain = (e_mae - f_mae) / e_mae * 100

    print(
        f"{key[0]:<16} {key[1]:<12} "
        f"{e_mae:9.4f} {f_mae:9.4f} "
        f"{gain:8.2f}% {len(data['e']):8d}"
    )

print("\n==============================================")
print("WORST MODEL F SAMPLES")
print("==============================================")

all_records = []

for data in groups.values():
    all_records.extend(data["records"])

all_records.sort(
    key=lambda r: float(r["model_f_absolute_error_C"]),
    reverse=True
)

print(
    f"{'RUN':<16} {'PHASE':<12} {'AGE':>6} "
    f"{'ACTUAL':>9} {'E PRED':>9} {'F PRED':>9} "
    f"{'E ERR':>9} {'F ERR':>9}"
)
print("-" * 100)

for row in all_records[:20]:
    print(
        f"{row['heldout_run']:<16} "
        f"{row['phase']:<12} "
        f"{float(row['phase_age_s']):6.1f} "
        f"{float(row['actual_temperature_C']):9.3f} "
        f"{float(row['model_e_prediction_C']):9.3f} "
        f"{float(row['model_f_prediction_C']):9.3f} "
        f"{float(row['model_e_absolute_error_C']):9.3f} "
        f"{float(row['model_f_absolute_error_C']):9.3f}"
    )

print("\n==============================================")
print("SIGNED ERROR ANALYSIS")
print("Positive = overprediction; Negative = underprediction")
print("==============================================")

for phase in sorted(phases):
    records = [
        r for r in all_records if r["phase"] == phase
    ]

    if not records:
        continue

    e_bias = sum(
        float(r["model_e_prediction_C"]) -
        float(r["actual_temperature_C"])
        for r in records
    ) / len(records)

    f_bias = sum(
        float(r["model_f_prediction_C"]) -
        float(r["actual_temperature_C"])
        for r in records
    ) / len(records)

    print(
        f"{phase:<12} "
        f"Model E signed error: {e_bias:+.4f} C | "
        f"Model F signed error: {f_bias:+.4f} C"
    )

print("\nDiagnostic completed.")
