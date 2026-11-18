import csv
import math
import os

TRAIN_FILES = [
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261011_172905.csv",
]
TEST_FILE = "rt_tas_controlled_20261021_163039.csv"

HORIZONS = (1, 5, 10)
WINDOW = 5
TOLERANCE = 0.75
RIDGE = 1.0

SENSORS = {"CPU": "cpu_tctl_C", "GPU": "gpu_edge_C"}

# Fixed before evaluating the held-out run.
# A = temperature history; B = temperature history + workload state.
SELECTED = {
    ("CPU", 1): ("A_temp", [0, 1, 2, 3, 4, 10]),
    ("CPU", 5): ("B_state", [0, 1, 2, 3, 4, 10, 5, 6]),
    ("CPU", 10): ("B_state", [0, 1, 2, 3, 4, 10, 5, 6]),
    ("GPU", 1): ("persistence", None),
    ("GPU", 5): ("persistence", None),
    ("GPU", 10): ("B_state", [0, 1, 2, 3, 4, 10, 5, 6]),
}


def load_rows(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        r["elapsed_s"] = float(r["elapsed_s"])
        for k in (
            "cpu_tctl_C", "gpu_edge_C", "gpu_freq_MHz",
            "gpu_activity_proxy", "cpu6_freq_MHz"
        ):
            r[k] = float(r[k])

        r["cpu_active"] = float(r["cpu_active"].strip().upper() == "ON")
        r["gpu_enabled"] = float(r["gpu_enabled"].strip().upper() == "ON")
        r["phase"] = r["phase"].strip()

    return sorted(rows, key=lambda r: r["elapsed_s"])


def nearest_target(rows, i, horizon):
    desired = rows[i]["elapsed_s"] + horizon
    best, best_error = None, float("inf")

    for j in range(i + 1, len(rows)):
        err = abs(rows[j]["elapsed_s"] - desired)
        if rows[j]["elapsed_s"] > desired + TOLERANCE:
            break
        if err < best_error:
            best, best_error = j, err

    return best if best is not None and best_error <= TOLERANCE else None


def segment_start(rows, i):
    phase = rows[i]["phase"]
    start = i
    while start > 0 and rows[start - 1]["phase"] == phase:
        start -= 1
    return start


def slope(rows, i, start, sensor):
    hist = rows[max(start, i - WINDOW + 1):i + 1]
    if len(hist) < 3:
        return 0.0

    ts = [r["elapsed_s"] for r in hist]
    ys = [r[sensor] for r in hist]
    mt, my = sum(ts) / len(ts), sum(ys) / len(ys)
    den = sum((t - mt) ** 2 for t in ts)
    if den == 0:
        return 0.0
    return sum((t - mt) * (y - my)
               for t, y in zip(ts, ys)) / den


def make_features(rows, i, start, horizon):
    r = rows[i]
    return [
        1.0,
        r["cpu_tctl_C"],
        r["gpu_edge_C"],
        slope(rows, i, start, "cpu_tctl_C"),
        slope(rows, i, start, "gpu_edge_C"),
        r["cpu_active"],
        r["gpu_enabled"],
        r["cpu6_freq_MHz"] / 1000.0,
        r["gpu_freq_MHz"] / 1000.0,
        r["gpu_activity_proxy"],
        float(horizon),
        r["cpu_active"] * horizon,
        r["gpu_enabled"] * horizon,
    ]


def build_examples(rows, horizon, sensor):
    result = []
    for i in range(len(rows) - 1):
        j = nearest_target(rows, i, horizon)
        if j is None:
            continue

        phase = rows[i]["phase"]
        if any(rows[k]["phase"] != phase for k in range(i, j + 1)):
            continue

        start = segment_start(rows, i)
        if i - start + 1 < 3:
            continue

        current, actual = rows[i][sensor], rows[j][sensor]
        dt = rows[j]["elapsed_s"] - rows[i]["elapsed_s"]

        result.append({
            "x": make_features(rows, i, start, horizon),
            "current": current,
            "actual": actual,
            "delta": actual - current,
            "trend": current + slope(rows, i, start, sensor) * dt,
            "phase": phase,
            "start": rows[i]["elapsed_s"],
            "target": rows[j]["elapsed_s"],
        })
    return result


def solve(a, b):
    n = len(b)
    aug = [a[i][:] + [b[i]] for i in range(n)]

    for col in range(n):
        p = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[p][col]) < 1e-12:
            raise ArithmeticError("Singular regression system")
        aug[col], aug[p] = aug[p], aug[col]

        d = aug[col][col]
        for k in range(col, n + 1):
            aug[col][k] /= d

        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            for k in range(col, n + 1):
                aug[r][k] -= factor * aug[col][k]

    return [aug[i][n] for i in range(n)]


def fit_ridge(examples, indices):
    xs = [[e["x"][k] for k in indices] for e in examples]
    ys = [e["delta"] for e in examples]
    width, n = len(indices), len(examples)
    means, scales = [0.0] * width, [1.0] * width

    for k, original in enumerate(indices):
        if original == 0:
            continue
        means[k] = sum(x[k] for x in xs) / n
        var = sum((x[k] - means[k]) ** 2 for x in xs) / n
        scales[k] = math.sqrt(var) if var > 1e-12 else 1.0

    def transform(x):
        return [
            1.0 if indices[k] == 0 else (x[k] - means[k]) / scales[k]
            for k in range(width)
        ]

    tx = [transform(x) for x in xs]
    a = [[0.0] * width for _ in range(width)]
    b = [0.0] * width

    for x, y in zip(tx, ys):
        for p in range(width):
            b[p] += x[p] * y
            for q in range(width):
                a[p][q] += x[p] * x[q]

    for k in range(width):
        if indices[k] != 0:
            a[k][k] += RIDGE

    return solve(a, b), means, scales, indices


def predict_delta(x, model):
    coeff, means, scales, indices = model
    total = 0.0
    for k, idx in enumerate(indices):
        value = 1.0 if idx == 0 else (x[idx] - means[k]) / scales[k]
        total += coeff[k] * value
    return total


def metrics(errors):
    if not errors:
        return float("nan"), float("nan")
    return (
        sum(abs(e) for e in errors) / len(errors),
        math.sqrt(sum(e * e for e in errors) / len(errors)),
    )


def fmt(x):
    return "%.3f" % x if math.isfinite(x) else "N/A"


def main():
    for path in TRAIN_FILES + [TEST_FILE]:
        if not os.path.isfile(path):
            raise SystemExit("Missing file: " + path)

    train_runs = [load_rows(p) for p in TRAIN_FILES]
    test_rows = load_rows(TEST_FILE)
    predictions = []

    print("TRAIN FILES:", ", ".join(TRAIN_FILES))
    print("HELD-OUT TEST:", TEST_FILE)
    print("No model fitting or feature selection uses the held-out run.")

    for label, sensor in SENSORS.items():
        for horizon in HORIZONS:
            train = []
            for run in train_runs:
                train.extend(build_examples(run, horizon, sensor))
            test = build_examples(test_rows, horizon, sensor)

            if not train or not test:
                print("\n%s %ds: insufficient examples" % (label, horizon))
                continue

            method, indices = SELECTED[(label, horizon)]
            model = fit_ridge(train, indices) if indices else None

            errors = {"persistence": [], "trend": [], "selected": []}
            for e in test:
                selected = (
                    e["current"] if method == "persistence"
                    else e["current"] + predict_delta(e["x"], model)
                )

                for name, pred in (
                    ("persistence", e["current"]),
                    ("trend", e["trend"]),
                    ("selected", selected),
                ):
                    errors[name].append(pred - e["actual"])

                predictions.append({
                    "sensor": label,
                    "horizon_s": horizon,
                    "method": method,
                    "phase": e["phase"],
                    "start_elapsed_s": e["start"],
                    "target_elapsed_s": e["target"],
                    "actual_C": e["actual"],
                    "selected_prediction_C": selected,
                    "error_C": selected - e["actual"],
                })

            print("\n%s %ds | train=%d test=%d | selected=%s" %
                  (label, horizon, len(train), len(test), method))
            for name in ("persistence", "trend", "selected"):
                ma, rm = metrics(errors[name])
                print("  %-12s MAE=%s RMSE=%s" % (name, fmt(ma), fmt(rm)))

    output = "thermal_heldout_20261021_predictions.csv"
    fields = [
        "sensor", "horizon_s", "method", "phase",
        "start_elapsed_s", "target_elapsed_s", "actual_C",
        "selected_prediction_C", "error_C",
    ]
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(predictions)

    print("\nSaved per-sample results to:", output)


if __name__ == "__main__":
    main()
