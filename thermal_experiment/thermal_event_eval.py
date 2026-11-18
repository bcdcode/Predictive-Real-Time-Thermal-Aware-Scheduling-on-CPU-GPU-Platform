#!/usr/bin/env python3
"""Offline event-based early-warning evaluation."""

import csv
import glob
import os
import math
from collections import defaultdict

RISE_C = 0.5
BASELINE_WINDOW_S = 10.0
MIN_LEAD_S = 2.0
HORIZONS = (5, 10)
DATA_GLOB = "rt_tas_controlled_*.csv"


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def bit(x):
    return int(str(x or "").strip().upper() in ("ON", "1", "TRUE", "YES"))


def load_runs():
    required = {
        "elapsed_s", "phase", "gpu_edge_C", "cpu_tctl_C",
        "gpu_freq_MHz", "gpu_activity_proxy", "cpu_active", "gpu_enabled"
    }
    runs = []
    for path in sorted(glob.glob(DATA_GLOB)):
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            if not required.issubset(set(reader.fieldnames or [])):
                print("Skipping incompatible CSV:", os.path.basename(path))
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
                    "cpu": bit(r["cpu_active"]), "gpu": bit(r["gpu_enabled"]),
                })
        rows.sort(key=lambda x: x["t"])
        if rows:
            runs.append(rows)
            print("Loaded", rows[0]["run"], len(rows), "rows")
    if len(runs) < 2:
        raise SystemExit("Need at least two compatible runs.")
    return runs


def past_row(rows, i, target):
    for j in range(i - 1, -1, -1):
        if rows[j]["t"] <= target:
            return rows[j]
    return None


def build_run(rows):
    """Create past-only scores and event times for one run."""
    scored = []
    events = []
    was_above = False

    for i, r in enumerate(rows):
        prior = [
            x for x in rows
            if r["t"] - BASELINE_WINDOW_S <= x["t"] < r["t"]
        ]
        if not prior:
            continue

        local_min = min(x["gt"] for x in prior)
        above = (r["gt"] - local_min) >= RISE_C

        # Event begins on the first crossing above the preceding 10s minimum.
        if above and not was_above:
            events.append({
                "run": r["run"], "event_t": r["t"],
                "phase": r["phase"], "temperature": r["gt"],
            })
        was_above = above

        old = past_row(rows, i, r["t"] - 4.0)
        if old is None or r["t"] <= old["t"]:
            continue
        dt = r["t"] - old["t"]

        gpu_delta = r["gt"] - old["gt"]
        cpu_slope = (
            (r["ct"] - old["ct"]) / dt
            if r["ct"] is not None and old["ct"] is not None else None
        )
        freq_delta = (
            r["gf"] - old["gf"]
            if r["gf"] is not None and old["gf"] is not None else None
        )
        activity_delta = (
            r["ga"] - old["ga"]
            if r["ga"] is not None and old["ga"] is not None else None
        )

        transition = 0
        old5 = past_row(rows, i, r["t"] - 5.0)
        if old5:
            transition = int(
                r["phase"] != old5["phase"]
                or r["gpu"] != old5["gpu"]
                or r["cpu"] != old5["cpu"]
            )

        features = {
            "gpu_temp_rising": int(gpu_delta >= 0.15),
            "gpu_freq_increasing": int(freq_delta is not None and freq_delta >= 25),
            "gpu_activity_increasing": int(
                activity_delta is not None and activity_delta >= 0.05
            ),
            "cpu_temp_rising": int(cpu_slope is not None and cpu_slope >= 0.05),
            "cpu_active": r["cpu"],
            "recent_transition": transition,
        }
        dynamic_score = (
            2 * features["gpu_temp_rising"]
            + features["gpu_freq_increasing"]
            + features["gpu_activity_increasing"]
            + features["cpu_temp_rising"]
            + features["cpu_active"]
            + features["recent_transition"]
        )
        scored.append({
            **r, "gpu_score": r["gpu"], "dynamic_score": dynamic_score,
            "features": features,
        })

    return scored, events


def label_sample(sample, events, horizon):
    """Positive if an event is 2..horizon seconds ahead in the same phase."""
    for ev in events:
        lead = ev["event_t"] - sample["t"]
        if (MIN_LEAD_S <= lead <= horizon
                and ev["phase"] == sample["phase"]):
            return 1
    return 0


def f1_stats(items, preds):
    tp = fp = fn = tn = 0
    for x, p in zip(items, preds):
        y = x["label"]
        if p and y:
            tp += 1
        elif p:
            fp += 1
        elif y:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "N": len(items), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "F1": f1,
    }


def threshold_for(train, score):
    """Choose a training-only threshold using balanced accuracy.

    Prefer a non-degenerate classifier when one is available.
    Balanced accuracy gives equal weight to positive and negative labels.
    """
    values = sorted(set(score(x) for x in train))
    if not values:
        return 0

    candidates = [values[0] - 1] + values + [values[-1] + 1]
    evaluated = []

    for th in candidates:
        preds = [int(score(x) >= th) for x in train]
        tp = sum(p == 1 and x["label"] == 1
                 for x, p in zip(train, preds))
        fp = sum(p == 1 and x["label"] == 0
                 for x, p in zip(train, preds))
        fn = sum(p == 0 and x["label"] == 1
                 for x, p in zip(train, preds))
        tn = sum(p == 0 and x["label"] == 0
                 for x, p in zip(train, preds))

        tpr = tp / (tp + fn) if tp + fn else 0.0
        tnr = tn / (tn + fp) if tn + fp else 0.0
        balanced_accuracy = (tpr + tnr) / 2

        precision = tp / (tp + fp) if tp + fp else 0.0
        f1 = (2 * precision * tpr / (precision + tpr)
              if precision + tpr else 0.0)

        positive_count = sum(preds)
        non_degenerate = int(0 < positive_count < len(preds))

        evaluated.append((
            balanced_accuracy, non_degenerate, f1, precision, th
        ))

    # Prioritize balanced accuracy, then avoid trivial predictions,
    # then use F1, precision, and threshold as tie-breakers.
    return max(evaluated)[-1]


def phase_rates(train):
    totals, positives = defaultdict(int), defaultdict(int)
    for x in train:
        totals[x["phase"]] += 1
        positives[x["phase"]] += x["label"]
    rates = {p: positives[p] / totals[p] for p in totals}
    fallback = sum(x["label"] for x in train) / len(train) if train else 0
    return rates, fallback


def collapse_episodes(rows, max_gap=2.0):
    """Group repeated warnings from the same detector into episodes."""
    if not rows:
        return []
    rows = sorted(rows, key=lambda x: x["t"])
    episodes = []
    start = last = rows[0]["t"]
    count = 1
    for r in rows[1:]:
        if r["t"] - last <= max_gap:
            last = r["t"]
            count += 1
        else:
            episodes.append({"start": start, "end": last, "samples": count})
            start = last = r["t"]
            count = 1
    episodes.append({"start": start, "end": last, "samples": count})
    return episodes


def main():
    runs = load_runs()
    run_data = {}
    for rows in runs:
        scored, events = build_run(rows)
        run_data[rows[0]["run"]] = {"samples": scored, "events": events}

    all_predictions = []
    summary = []
    event_results = []
    per_run_results = []

    for horizon in HORIZONS:
        # Training and testing samples: positive means an event is 2..H seconds ahead.
        examples = []
        for run, data in run_data.items():
            for s in data["samples"]:
                # Evaluate at 1-second timestamps; timestamps are rounded to seconds.
                if abs(s["t"] - round(s["t"])) > 1e-6:
                    continue
                x = dict(s)
                x["label"] = label_sample(s, data["events"], horizon)
                x["horizon"] = horizon
                examples.append(x)

        run_names = sorted(run_data)
        oof = defaultdict(list)

        for held in run_names:
            train = [x for x in examples if x["run"] != held]
            test = [x for x in examples if x["run"] == held]
            if not train or not test:
                continue

            gpu_th = threshold_for(train, lambda x: x["gpu_score"])
            dyn_th = threshold_for(train, lambda x: x["dynamic_score"])
            rates, fallback = phase_rates(train)
            phase_score = lambda x: rates.get(x["phase"], fallback)
            phase_th = threshold_for(train, phase_score)

            specs = {
                "gpu_state_only": (lambda x: x["gpu_score"], gpu_th),
                "dynamic_detector": (lambda x: x["dynamic_score"], dyn_th),
                "phase_only": (phase_score, phase_th),
            }

            for detector, (score_fn, th) in specs.items():
                for x in test:
                    pred = int(score_fn(x) >= th)
                    rec = {
                        "run": x["run"], "held_out_run": held,
                        "t": x["t"], "phase": x["phase"], "horizon_s": horizon,
                        "detector": detector, "label": x["label"],
                        "prediction": pred, "threshold": th,
                        "gpu_score": x["gpu_score"], "dynamic_score": x["dynamic_score"],
                    }
                    all_predictions.append(rec)
                    oof[detector].append((x, pred))

        for detector in ("gpu_state_only", "dynamic_detector", "phase_only"):
            pairs = oof[detector]
            items = [dict(x, label=x["label"]) for x, _ in pairs]
            preds = [p for _, p in pairs]
            m = f1_stats(items, preds)

            # Event-level match: a warning must be at least 2s early and no
            # farther away than the prediction horizon. Each event matched once.
            matched_events = set()
            warnings = [r for r in all_predictions
                        if r["horizon_s"] == horizon and r["detector"] == detector
                        and r["prediction"] == 1]
            event_total = 0
            for run, data in run_data.items():
                evs = data["events"]
                for ei, ev in enumerate(evs):
                    event_total += 1
                    eligible = [
                        w for w in warnings
                        if w["run"] == run
                        and MIN_LEAD_S <= ev["event_t"] - w["t"] <= horizon
                        and w["phase"] == ev["phase"]
                    ]
                    if eligible:
                        chosen = max(eligible, key=lambda w: w["t"])
                        matched_events.add((run, ei))
                        event_results.append({
                            "horizon_s": horizon, "detector": detector,
                            "run": run, "event_t": ev["event_t"],
                            "warning_t": chosen["t"],
                            "lead_s": ev["event_t"] - chosen["t"],
                            "matched": 1,
                        })
                    else:
                        event_results.append({
                            "horizon_s": horizon, "detector": detector,
                            "run": run, "event_t": ev["event_t"],
                            "warning_t": "", "lead_s": "", "matched": 0,
                        })

            event_recall = len(matched_events) / event_total if event_total else 0.0
            # Warning episodes not matched to any event are false-warning episodes.
            false_episodes = 0
            total_episodes = 0
            for run in run_names:
                run_warnings = [w for w in warnings if w["run"] == run]
                episodes = collapse_episodes(run_warnings)
                total_episodes += len(episodes)
                evs = run_data[run]["events"]
                for ep in episodes:
                    # An episode is useful if its first warning is in the valid
                    # early-warning interval for at least one event.
                    useful = any(
                        MIN_LEAD_S <= ev["event_t"] - ep["start"] <= horizon
                        and ev["phase"] == next(
                            (w["phase"] for w in run_warnings if w["t"] == ep["start"]), ""
                        )
                        for ev in evs
                    )
                    if not useful:
                        false_episodes += 1

            summary.append({
                "horizon_s": horizon, "detector": detector,
                **m, "event_count": event_total,
                "events_warned": len(matched_events),
                "event_recall": event_recall,
                "warning_episodes": total_episodes,
                "false_warning_episodes": false_episodes,
            })

    # Save predictions and event-level outcomes.
    def write_csv(path, rows, fields):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    write_csv("thermal_event_predictions.csv", all_predictions, [
        "run", "held_out_run", "t", "phase", "horizon_s", "detector",
        "label", "prediction", "threshold", "gpu_score", "dynamic_score",
    ])
    write_csv("thermal_event_summary.csv", summary, [
        "horizon_s", "detector", "N", "TP", "FP", "FN", "TN",
        "precision", "recall", "F1", "event_count", "events_warned",
        "event_recall", "warning_episodes", "false_warning_episodes",
    ])
    write_csv("thermal_event_results.csv", event_results, [
        "horizon_s", "detector", "run", "event_t", "warning_t", "lead_s", "matched",
    ])

    print("\nEVENT-BASED RESULTS")
    print("Event definition: first sample >=0.5 C above preceding 10-second minimum.")
    print(f"Valid warning window: {MIN_LEAD_S:.0f} seconds to {max(HORIZONS)} seconds before event.")
    print("Thresholds selected using training runs only.\n")
    for r in summary:
        print(
            f"{r['horizon_s']:2}s {r['detector']:<19} "
            f"sample-F1={r['F1']:.3f} sample-P={r['precision']:.3f} "
            f"sample-R={r['recall']:.3f} "
            f"event-recall={r['event_recall']:.3f} "
            f"events={r['events_warned']}/{r['event_count']} "
            f"warning-episodes={r['warning_episodes']} "
            f"false-episodes={r['false_warning_episodes']}"
        )

    print("\nFiles created:")
    print("  thermal_event_predictions.csv")
    print("  thermal_event_summary.csv")
    print("  thermal_event_results.csv")
    print("\nResearch caution: event definition is a heuristic, not a physical thermal limit.")


if __name__ == "__main__":
    main()
