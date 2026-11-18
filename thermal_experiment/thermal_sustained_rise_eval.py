#!/usr/bin/env python3

import csv
import os
from collections import defaultdict

INPUT = "rt_tas_controlled_20261026_221300.csv"
OUTPUT = "thermal_sustained_rise_results_20261026.csv"

# Existing one-step alert threshold and exploratory sustained-rise criterion.
ONE_STEP_THRESHOLD_C = 0.5
SUSTAINED_NET_RISE_C = 1.0
FUTURE_HORIZONS = (5, 10)


def to_float(row, key):
    try:
        value = row.get(key, "")
        if value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def main():
    if not os.path.isfile(INPUT):
        print("ERROR: Cannot find input file:", INPUT)
        print("Check the filename with: ls rt_tas_controlled_*.csv")
        return

    rows = []

    with open(INPUT, newline="") as f:
        reader = csv.DictReader(f)
        required = ["elapsed_s", "phase", "gpu_edge_C"]

        missing = [
            col for col in required
            if col not in (reader.fieldnames or [])
        ]
        if missing:
            print("ERROR: Missing columns:", ", ".join(missing))
            print("CSV columns:", reader.fieldnames)
            return

        for row in reader:
            elapsed = to_float(row, "elapsed_s")
            temp = to_float(row, "gpu_edge_C")

            if elapsed is None or temp is None:
                continue

            rows.append({
                "elapsed_s": elapsed,
                "phase": row["phase"],
                "gpu_temp_C": temp,
                "one_step_alert": False,
                "sustained_alert": False,
            })

    rows.sort(key=lambda r: r["elapsed_s"])

    # Index observations by phase and elapsed time.
    by_phase_time = {}
    by_phase = defaultdict(list)

    for r in rows:
        key = (r["phase"], round(r["elapsed_s"], 3))
        by_phase_time[key] = r
        by_phase[r["phase"]].append(r)

    # Detect alerts only within the same phase and at consecutive seconds.
    for phase, samples in by_phase.items():
        samples.sort(key=lambda r: r["elapsed_s"])

        for i, current in enumerate(samples):
            if i >= 1:
                previous = samples[i - 1]
                consecutive = abs(
                    current["elapsed_s"] - previous["elapsed_s"] - 1.0
                ) < 0.01

                if consecutive:
                    delta = current["gpu_temp_C"] - previous["gpu_temp_C"]
                    current["one_step_alert"] = (
                        delta >= ONE_STEP_THRESHOLD_C
                    )

            if i >= 2:
                first = samples[i - 2]
                middle = samples[i - 1]

                consecutive = (
                    abs(middle["elapsed_s"] - first["elapsed_s"] - 1.0)
                    < 0.01
                    and abs(
                        current["elapsed_s"] - middle["elapsed_s"] - 1.0
                    ) < 0.01
                )

                strictly_increasing = (
                    first["gpu_temp_C"] < middle["gpu_temp_C"]
                    and middle["gpu_temp_C"] < current["gpu_temp_C"]
                )

                net_rise = current["gpu_temp_C"] - first["gpu_temp_C"]

                current["sustained_alert"] = (
                    consecutive
                    and strictly_increasing
                    and net_rise >= SUSTAINED_NET_RISE_C
                )

    # Save per-sample detector results and same-phase follow-up changes.
    output_fields = [
        "elapsed_s", "phase", "gpu_temp_C",
        "one_step_alert", "sustained_alert",
        "gpu_change_5s_C", "gpu_change_10s_C",
        "applied",
    ]

    output_rows = []

    for r in rows:
        out = {
            "elapsed_s": r["elapsed_s"],
            "phase": r["phase"],
            "gpu_temp_C": r["gpu_temp_C"],
            "one_step_alert": "YES" if r["one_step_alert"] else "NO",
            "sustained_alert": "YES" if r["sustained_alert"] else "NO",
            "gpu_change_5s_C": "",
            "gpu_change_10s_C": "",
            "applied": "NO",
        }

        for horizon in FUTURE_HORIZONS:
            target = round(r["elapsed_s"] + horizon, 3)
            future = by_phase_time.get((r["phase"], target))

            if future is not None:
                change = future["gpu_temp_C"] - r["gpu_temp_C"]
                out["gpu_change_" + str(horizon) + "s_C"] = round(
                    change, 3
                )

        output_rows.append(out)

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(output_rows)

    print("GPU sustained-rise detector evaluation")
    print("Input:", INPUT)
    print("Output:", OUTPUT)
    print("All actions remain unapplied.")
    print()
    print(
        "{:<20} {:>8} {:>10} {:>12} {:>12} {:>12}".format(
            "Phase", "Samples", "One-step", "Sustained",
            "5s follow-up", "10s follow-up"
        )
    )

    phases = sorted(set(r["phase"] for r in rows))
    phases.append("ALL_PHASES")

    for phase in phases:
        subset = rows if phase == "ALL_PHASES" else [
            r for r in rows if r["phase"] == phase
        ]

        one_step_count = sum(r["one_step_alert"] for r in subset)
        sustained_count = sum(r["sustained_alert"] for r in subset)

        # Mean future temperature change after sustained alerts.
        followup_text = []

        for horizon in FUTURE_HORIZONS:
            changes = []

            for r in subset:
                if not r["sustained_alert"]:
                    continue

                target = round(r["elapsed_s"] + horizon, 3)
                future = by_phase_time.get((r["phase"], target))

                if future is not None:
                    changes.append(
                        future["gpu_temp_C"] - r["gpu_temp_C"]
                    )

            if changes:
                mean_change = sum(changes) / len(changes)
                followup_text.append(
                    "{:.3f}C (n={})".format(mean_change, len(changes))
                )
            else:
                followup_text.append("n/a (n=0)")

        print(
            "{:<20} {:>8} {:>10} {:>12} {:>12} {:>12}".format(
                phase, len(subset), one_step_count, sustained_count,
                followup_text[0], followup_text[1]
            )
        )

    print()
    print("Detector definitions:")
    print(
        "One-step: GPU temperature rises by at least {:.1f}C in one second."
        .format(ONE_STEP_THRESHOLD_C)
    )
    print(
        "Sustained: three consecutive readings strictly increase, "
        "with net rise >= {:.1f}C.".format(SUSTAINED_NET_RISE_C)
    )
    print("Follow-up changes use the same phase, when a matching sample exists.")
    print("These are exploratory criteria, not hardware safety limits.")


if __name__ == "__main__":
    main()
