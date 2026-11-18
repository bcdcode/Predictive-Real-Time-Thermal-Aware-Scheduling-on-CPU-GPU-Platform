#!/usr/bin/env python3
"""Offline thermal-detector evaluation. Standard library only."""

import csv
import glob
import math
import os
from collections import defaultdict

DATA_GLOB = "rt_tas_controlled_*.csv"
HORIZONS = (5, 10)
RISE_C = 0.5
TREND_WINDOW_S = 4.0
TRANSITION_WINDOW_S = 5.0
MIN_FREQ_DELTA = 25.0
MIN_ACTIVITY_DELTA = 0.05
MIN_CPU_SLOPE = 0.05
MIN_GPU_TEMP_DELTA = 0.15


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def on(v):
    return int(str(v or "").strip().upper() in ("ON", "1", "TRUE", "YES"))


def load_data():
    required = {
        "elapsed_s", "phase", "cpu_tctl_C", "gpu_edge_C",
        "gpu_freq_MHz", "gpu_activity_proxy", "cpu_active", "gpu_enabled"
    }
    runs = []
    for path in sorted(glob.glob(DATA_GLOB)):
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            if not required.issubset(set(reader.fieldnames or [])):
                print("Skipping incompatible CSV:", path)
                continue
            rows = []
            for r in reader:
                t, gt = num(r["elapsed_s"]), num(r["gpu_edge_C"])
                if t is None or gt is None:
                    continue
                rows.append({
                    "run": os.path.basename(path), "t": t,
                    "phase": (r["phase"] or "").strip(),
                    "gt": gt, "ct": num(r["cpu_tctl_C"]),
                    "gf": num(r["gpu_freq_MHz"]),
                    "ga": num(r["gpu_activity_proxy"]),
                    "cpu": on(r["cpu_active"]),
                    "gpu": on(r["gpu_enabled"]),
                })
        rows.sort(key=lambda r: r["t"])
        if rows:
            runs.append(rows)
            print("Loaded", os.path.basename(path), len(rows), "rows")
    if len(runs) < 2:
        raise SystemExit("Need at least two compatible CSV runs.")
    return runs


def past_row(rows, i, target):
    for j in range(i - 1, -1, -1):
        if rows[j]["t"] <= target:
            return rows[j]
    return None


def build_examples(runs):
    examples = []
    for rows in runs:
        for i, r in enumerate(rows):
            old = past_row(rows, i, r["t"] - TREND_WINDOW_S)
            trans_old = past_row(rows, i, r["t"] - TRANSITION_WINDOW_S)
            if old is None or r["t"] <= old["t"]:
                continue
            dt = r["t"] - old["t"]
            gd = r["gt"] - old["gt"]
            cs = (
                (r["ct"] - old["ct"]) / dt
                if r["ct"] is not None and old["ct"] is not None else None
            )
            fd = (
                r["gf"] - old["gf"]
                if r["gf"] is not None and old["gf"] is not None else None
            )
            ad = (
                r["ga"] - old["ga"]
                if r["ga"] is not None and old["ga"] is not None else None
            )

            transition = 0
            if trans_old is not None:
                prev = trans_old
                for rr in rows:
                    if not (trans_old["t"] < rr["t"] <= r["t"]):
                        continue
                    if (rr["phase"] != prev["phase"] or
                        rr["gpu"] != prev["gpu"] or rr["cpu"] != prev["cpu"]):
                        transition = 1
                    prev = rr

            feats = {
                "gpu_temp_rising": int(gd >= MIN_GPU_TEMP_DELTA),
                "gpu_freq_increasing": int(fd is not None and fd >= MIN_FREQ_DELTA),
                "gpu_activity_increasing": int(ad is not None and ad >= MIN_ACTIVITY_DELTA),
                "cpu_temp_rising": int(cs is not None and cs >= MIN_CPU_SLOPE),
                "cpu_active": r["cpu"],
                "recent_transition": transition,
            }
            dyn = (
                2 * feats["gpu_temp_rising"] +
                feats["gpu_freq_increasing"] +
                feats["gpu_activity_increasing"] +
                feats["cpu_temp_rising"] +
                feats["cpu_active"] +
                feats["recent_transition"]
            )

            for h in HORIZONS:
                future = next(
                    (rr for rr in rows if rr["t"] >= r["t"] + h), None
                )
                if future is None or future["phase"] != r["phase"]:
                    continue
                if future["t"] > r["t"] + h + 2:
                    continue

                # Find the first observed threshold crossing in the future.
                crossing = None
                for rr in rows:
                    if rr["t"] <= r["t"]:
                        continue
                    if rr["t"] > r["t"] + h:
                        break
                    if rr["gt"] >= r["gt"] + RISE_C:
                        crossing = rr["t"] - r["t"]
                        break

                examples.append({
                    "run": r["run"], "t": r["t"], "phase": r["phase"],
                    "h": h, "actual": int(future["gt"] - r["gt"] >= RISE_C),
                    "gpu_score": r["gpu"], "dyn_score": dyn,
                    "features": feats, "gpu_delta": gd, "cpu_slope": cs,
                    "freq_delta": fd, "activity_delta": ad,
                    "crossing_s": crossing,
                })
    return examples


def metrics(examples, preds, step):
    tp = fp = fn = tn = 0
    for e, p in zip(examples, preds):
        if p and e["actual"]:
            tp += 1
        elif p:
            fp += 1
        elif e["actual"]:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0

    # Approximate monitored duration: one interval per evaluated sample.
    duration_min = len(examples) * step / 60
    fpm = fp / duration_min if duration_min else 0

    lead = [
        e["crossing_s"] for e, p in zip(examples, preds)
        if p and e["actual"] and e.get("crossing_s") is not None
    ]
    return {
        "N": len(examples), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "F1": f1,
        "false_alarms_per_min": fpm,
        "lead_count": len(lead),
        "mean_lead_s": sum(lead) / len(lead) if lead else "",
        "median_lead_s": sorted(lead)[len(lead)//2] if lead else "",
    }


def choose_threshold(train, score_fn):
    """Maximize training F1; ties favor higher precision then higher threshold."""
    if not train:
        return 0
    values = sorted(set(score_fn(e) for e in train))
    candidates = [values[0] - 1] + values + [values[-1] + 1]
    best = None
    for threshold in candidates:
        preds = [int(score_fn(e) >= threshold) for e in train]
        m = metrics(train, preds, 1)
        key = (m["F1"], m["precision"], threshold)
        if best is None or key > best[0]:
            best = (key, threshold)
    return best[1]


def phase_score_maps(train):
    counts, positives = defaultdict(int), defaultdict(int)
    for e in train:
        counts[e["phase"]] += 1
        positives[e["phase"]] += e["actual"]
    total = len(train)
    fallback = sum(e["actual"] for e in train) / total if total else 0
    return {
        p: positives[p] / counts[p] for p in counts
    }, fallback


def run_eval(examples):
    prediction_rows, summary_rows, per_run_rows = [], [], []
    run_names = sorted({e["run"] for e in examples})

    for h in HORIZONS:
        all_h = [e for e in examples if e["h"] == h]
        for sampling in ("1s_overlapping", "nonoverlap"):
            step = 1 if sampling == "1s_overlapping" else h

            def selected(rows):
                # Experiments use second-based timestamps; anchor grid at t=0.
                return [
                    e for e in rows
                    if abs(e["t"] / step - round(e["t"] / step)) < 1e-6
                ]

            sampled = selected(all_h)
            for held in run_names:
                test = [e for e in sampled if e["run"] == held]
                train = [e for e in sampled if e["run"] != held]
                if not test or not train:
                    continue

                gpu_th = choose_threshold(train, lambda e: e["gpu_score"])
                dyn_th = choose_threshold(train, lambda e: e["dyn_score"])

                rates, fallback = phase_score_maps(train)
                phase_score = lambda e: rates.get(e["phase"], fallback)
                phase_th = choose_threshold(train, phase_score)

                pred_map = {
                    "gpu_state_only": [int(e["gpu_score"] >= gpu_th) for e in test],
                    "dynamic_detector": [int(e["dyn_score"] >= dyn_th) for e in test],
                    "phase_only": [int(phase_score(e) >= phase_th) for e in test],
                }
                thresholds = {
                    "gpu_state_only": gpu_th,
                    "dynamic_detector": dyn_th,
                    "phase_only": phase_th,
                }

                for detector, preds in pred_map.items():
                    m = metrics(test, preds, step)
                    per_run_rows.append({
                        "horizon_s": h, "sampling": sampling,
                        "held_out_run": held, "detector": detector,
                        **m, "threshold": thresholds[detector],
                    })
                    for e, pred in zip(test, preds):
                        row = {
                            "run": e["run"], "held_out_run": held,
                            "t": e["t"], "phase": e["phase"],
                            "horizon_s": h, "sampling": sampling,
                            "detector": detector, "actual": e["actual"],
                            "prediction": pred, "threshold": thresholds[detector],
                            "gpu_score": e["gpu_score"], "dynamic_score": e["dyn_score"],
                            "gpu_temp_delta_C": e["gpu_delta"],
                            "cpu_temp_slope_C_s": e["cpu_slope"],
                            "gpu_freq_delta_MHz": e["freq_delta"],
                            "gpu_activity_delta": e["activity_delta"],
                            "crossing_lead_s": e["crossing_s"] if e["actual"] else "",
                        }
                        row.update(e["features"])
                        prediction_rows.append(row)

            # Pooled out-of-fold predictions. Every row is predicted by a model
            # that did not train on its run.
            for detector in ("gpu_state_only", "dynamic_detector", "phase_only"):
                records = [
                    r for r in prediction_rows
                    if r["horizon_s"] == h and r["sampling"] == sampling
                    and r["detector"] == detector
                ]
                # Each run is held out exactly once; pooled rows are out-of-fold.
                fake = [
                    {
                        "actual": int(r["actual"]),
                        "phase": r["phase"],
                        "crossing_s": (
                            float(r["crossing_lead_s"])
                            if r["crossing_lead_s"] not in ("", None)
                            else None
                        ),
                    }
                    for r in records
                ]
                preds = [int(r["prediction"]) for r in records]
                m = metrics(fake, preds, step)
                summary_rows.append({
                    "horizon_s": h, "sampling": sampling,
                    "detector": detector, **m,
                })

    return prediction_rows, summary_rows, per_run_rows


def write(path, rows, fields):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    runs = load_data()
    examples = build_examples(runs)
    if not examples:
        raise SystemExit("No labeled examples; check timestamps/phases.")

    print("\nTarget: GPU edge temperature rises >= 0.5 C within the horizon.")
    print("Phase baseline now tunes its threshold on training runs.")
    print("All detector thresholds are selected without the held-out run.")
    print("Non-overlap mode samples every 5s or 10s on a run-anchored grid.\n")

    predictions, summaries, per_run = run_eval(examples)

    print("POOLED OUT-OF-FOLD RESULTS")
    for r in summaries:
        print(
            f"{r['horizon_s']:2}s {r['sampling']:<16} {r['detector']:<20}"
            f"N={r['N']:4d} P={r['precision']:.3f} R={r['recall']:.3f}"
            f" F1={r['F1']:.3f} FP/min={r['false_alarms_per_min']:.2f}"
            f" lead_n={r['lead_count']}"
            + (f" mean_lead={r['mean_lead_s']:.2f}s" if r["mean_lead_s"] != "" else "")
        )

    print("\nPER HELD-OUT RUN")
    for r in per_run:
        print(
            f"{r['horizon_s']:2}s {r['sampling']:<16} {r['held_out_run']:<40}"
            f" {r['detector']:<19} F1={r['F1']:.3f}"
            f" P={r['precision']:.3f} R={r['recall']:.3f}"
            f" FP/min={r['false_alarms_per_min']:.2f}"
        )

    pred_fields = [
        "run", "held_out_run", "t", "phase", "horizon_s", "sampling",
        "detector", "actual", "prediction", "threshold", "gpu_score",
        "dynamic_score", "gpu_temp_delta_C", "cpu_temp_slope_C_s",
        "gpu_freq_delta_MHz", "gpu_activity_delta", "crossing_lead_s",
        "gpu_temp_rising", "gpu_freq_increasing", "gpu_activity_increasing",
        "cpu_temp_rising", "cpu_active", "recent_transition",
    ]
    write("thermal_dynamic_v2_predictions.csv", predictions, pred_fields)
    write("thermal_dynamic_v2_summary.csv", summaries, [
        "horizon_s", "sampling", "detector", "N", "TP", "FP", "FN", "TN",
        "precision", "recall", "F1", "false_alarms_per_min",
        "lead_count", "mean_lead_s", "median_lead_s",
    ])
    write("thermal_dynamic_v2_per_run.csv", per_run, [
        "horizon_s", "sampling", "held_out_run", "detector",
        "N", "TP", "FP", "FN", "TN", "precision", "recall", "F1",
        "false_alarms_per_min", "lead_count", "mean_lead_s",
        "median_lead_s", "threshold",
    ])

    print("\nFiles created:")
    print("  thermal_dynamic_v2_predictions.csv")
    print("  thermal_dynamic_v2_summary.csv")
    print("  thermal_dynamic_v2_per_run.csv")
    print("\nCaution: overlapping labels are correlated; lead time is conditional on")
    print("a true positive and a sampled threshold crossing, not a guarantee of warning time.")


if __name__ == "__main__":
    main()
