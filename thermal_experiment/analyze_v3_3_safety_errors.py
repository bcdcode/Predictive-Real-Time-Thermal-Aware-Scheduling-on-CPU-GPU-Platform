import csv
import math
from collections import defaultdict

FILES = [
    "rt_tas_v3_3_BASELINE_20261111_151301_live_predictions.csv",
    "rt_tas_v3_3_BASELINE_20261111_160419_live_predictions.csv",
    "rt_tas_v3_3_BASELINE_20261111_162636_live_predictions.csv",
]

CONFIG = {
    "CPU": ("cpu_actual_C", "cpu_hybrid_predicted_1s_C"),
    "GPU": ("gpu_actual_C", "gpu_hybrid_predicted_1s_C"),
}

errors = defaultdict(list)

def val(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (ValueError, TypeError):
        return None

def percentile(values, p):
    values = sorted(values)
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * p / 100
    lo = math.floor(position)
    hi = math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)

for filename in FILES:
    with open(filename, newline="") as f:
        rows = list(csv.DictReader(f))

    valid = 0

    for i in range(len(rows) - 1):
        current = rows[i]
        nxt = rows[i + 1]

        if current["prediction_status"] != "FORECAST_ONLY":
            continue

        if current["phase"] != nxt["phase"]:
            continue

        t0 = val(current["elapsed_s"])
        t1 = val(nxt["elapsed_s"])

        if t0 is None or t1 is None:
            continue

        if abs((t1 - t0) - 1.0) > 0.10:
            continue

        valid += 1
        phase = current["phase"]

        for target, (actual_key, pred_key) in CONFIG.items():
            actual = val(nxt[actual_key])
            predicted = val(current[pred_key])

            if actual is None or predicted is None:
                continue

            # Positive residual means the predictor underpredicted.
            residual = actual - predicted

            errors[(target, "OVERALL")].append(residual)
            errors[(target, phase)].append(residual)

    print(f"{filename}: {valid} valid transitions")

print("\nV3.3 HYBRID SAFETY-ERROR ANALYSIS")
print("Residual = actual(t+1) - hybrid_prediction(t)")
print("Positive residual = dangerous underprediction")

print("\n{:<8} {:<18} {:>5} {:>10} {:>10} {:>10} {:>10} {:>10}".format(
    "Target", "Phase", "N", "Under%", "P95", "MaxUnder",
    "P95Abs", "MaxOver"
))

for target in ("CPU", "GPU"):
    for phase in (
        "OVERALL",
        "IDLE_BASELINE1",
        "TA_GPU",
        "COOLDOWN2"
    ):
        e = errors[(target, phase)]

        if not e:
            continue

        positive = [x for x in e if x > 0]
        negative = [x for x in e if x < 0]

        under_pct = 100 * len(positive) / len(e)
        p95 = percentile(e, 95)
        max_under = max(positive) if positive else 0.0
        p95_abs = percentile([abs(x) for x in e], 95)
        max_over = abs(min(negative)) if negative else 0.0

        print(
            f"{target:<8} {phase:<18} {len(e):>5} "
            f"{under_pct:>9.1f}% {p95:>10.4f} "
            f"{max_under:>10.4f} {p95_abs:>10.4f} "
            f"{max_over:>10.4f}"
        )

print("\nInterpretation:")
print("P95      = 95th percentile of signed residuals.")
print("MaxUnder = largest observed positive residual.")
print("P95Abs   = 95th percentile of absolute residuals.")
print("MaxOver  = largest observed overprediction magnitude.")
print("\nThese are empirical error statistics, not guaranteed safety bounds.")
