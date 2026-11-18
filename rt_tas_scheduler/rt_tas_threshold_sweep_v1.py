#!/usr/bin/env python3

import csv
import glob
import os
import argparse
from collections import defaultdict

CPU_MARGIN = 0.75
GPU_MARGIN = 1.00

CONFIGS = [
    {"name": "A_RELAXED",      "cpu_limit": 70.0, "gpu_limit": 65.0},
    {"name": "B_MODERATE",     "cpu_limit": 50.0, "gpu_limit": 40.0},
    {"name": "C_CONSERVATIVE","cpu_limit": 45.0, "gpu_limit": 35.0},
    {"name": "D_STRICT",       "cpu_limit": 40.0, "gpu_limit": 32.0},
]

DECISION_FIELDS = [
    "timestamp", "elapsed_s", "monotonic_elapsed_s", "phase",
    "prediction_status",
    "cpu_predicted_C", "cpu_margin_C", "cpu_safe_C",
    "cpu_limit_C", "cpu_gate", "cpu_decision",
    "gpu_predicted_C", "gpu_margin_C", "gpu_safe_C",
    "gpu_limit_C", "gpu_gate", "gpu_decision",
    "decision_reason",
]


def number(value):
    try:
        if value is None or value.strip() in ("", "NA", "NaN", "None"):
            return None
        return float(value)
    except (ValueError, AttributeError):
        return None


def evaluate_sensor(prediction, margin, limit, valid_status):
    if not valid_status or prediction is None:
        return {
            "predicted": "",
            "safe": "",
            "gate": "INVALID",
            "decision": "DEFER_INVALID",
        }

    safe = prediction + margin

    if safe < limit:
        gate = "PASS"
        decision = "ADVISORY_ADMIT"
    else:
        gate = "THERMAL"
        decision = "DEFER_THERMAL"

    return {
        "predicted": f"{prediction:.4f}",
        "safe": f"{safe:.4f}",
        "gate": gate,
        "decision": decision,
    }


def increment_counts(counts, prefix, decision):
    if decision == "ADVISORY_ADMIT":
        counts[prefix + "_admit"] += 1
    elif decision == "DEFER_THERMAL":
        counts[prefix + "_thermal"] += 1
    else:
        counts[prefix + "_invalid"] += 1


def main():
    parser = argparse.ArgumentParser(
        description="Offline CPU/GPU thermal threshold sweep"
    )
    parser.add_argument(
        "--input-dir",
        default=os.path.expanduser("~/thermal_experiment")
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.expanduser("~/thermal_experiment/threshold_sweep_v1")
    )
    args = parser.parse_args()

    pattern = os.path.join(
        args.input_dir,
        "rt_tas_v3_3_BASELINE_*_live_predictions.csv"
    )

    files = sorted(glob.glob(pattern))

    if not files:
        raise SystemExit("ERROR: No prediction CSV files found.")

    os.makedirs(args.output_dir, exist_ok=True)

    summary_rows = []
    phase_rows = []

    print("\nRT-TAS THRESHOLD SWEEP V1")
    print("=" * 65)
    print(f"Input files: {len(files)}")
    print(f"CPU margin:  {CPU_MARGIN:.2f} C")
    print(f"GPU margin:  {GPU_MARGIN:.2f} C")
    print(f"Output directory: {args.output_dir}")

    for input_file in files:
        run_name = os.path.basename(input_file)
        run_name = run_name.replace(
            "rt_tas_v3_3_BASELINE_", ""
        ).replace("_live_predictions.csv", "")

        with open(input_file, newline="") as f:
            rows = list(csv.DictReader(f))

        required = {
            "timestamp", "elapsed_s", "monotonic_elapsed_s",
            "phase", "prediction_status",
            "cpu_hybrid_predicted_1s_C",
            "gpu_hybrid_predicted_1s_C",
        }

        if not rows:
            print(f"Skipping empty file: {input_file}")
            continue

        missing = required - set(rows[0].keys())
        if missing:
            raise SystemExit(
                f"ERROR: Missing columns in {input_file}: {sorted(missing)}"
            )

        for config in CONFIGS:
            name = config["name"]

            output_file = os.path.join(
                args.output_dir,
                f"{run_name}_{name}_decisions.csv"
            )

            counts = defaultdict(int)
            phase_counts = defaultdict(lambda: defaultdict(int))

            with open(output_file, "w", newline="") as out:
                writer = csv.DictWriter(
                    out, fieldnames=DECISION_FIELDS
                )
                writer.writeheader()

                for row in rows:
                    status = row["prediction_status"]
                    valid_status = status == "FORECAST_ONLY"

                    cpu_prediction = number(
                        row["cpu_hybrid_predicted_1s_C"]
                    )
                    gpu_prediction = number(
                        row["gpu_hybrid_predicted_1s_C"]
                    )

                    cpu = evaluate_sensor(
                        cpu_prediction,
                        CPU_MARGIN,
                        config["cpu_limit"],
                        valid_status
                    )

                    gpu = evaluate_sensor(
                        gpu_prediction,
                        GPU_MARGIN,
                        config["gpu_limit"],
                        valid_status
                    )

                    # A missing sensor forecast is invalid independently.
                    counts["records"] += 1
                    if valid_status:
                        counts["valid_status_records"] += 1
                    else:
                        counts["invalid_status_records"] += 1

                    increment_counts(counts, "cpu", cpu["decision"])
                    increment_counts(counts, "gpu", gpu["decision"])

                    phase = row["phase"]
                    pc = phase_counts[phase]
                    pc["records"] += 1
                    increment_counts(pc, "cpu", cpu["decision"])
                    increment_counts(pc, "gpu", gpu["decision"])

                    reasons = []
                    if cpu["decision"] == "DEFER_INVALID":
                        reasons.append("CPU_INVALID")
                    elif cpu["decision"] == "DEFER_THERMAL":
                        reasons.append("CPU_LIMIT")

                    if gpu["decision"] == "DEFER_INVALID":
                        reasons.append("GPU_INVALID")
                    elif gpu["decision"] == "DEFER_THERMAL":
                        reasons.append("GPU_LIMIT")

                    if not reasons:
                        reasons.append("BOTH_GATES_PASS")

                    writer.writerow({
                        "timestamp": row["timestamp"],
                        "elapsed_s": row["elapsed_s"],
                        "monotonic_elapsed_s": row["monotonic_elapsed_s"],
                        "phase": phase,
                        "prediction_status": status,

                        "cpu_predicted_C": cpu["predicted"],
                        "cpu_margin_C": CPU_MARGIN,
                        "cpu_safe_C": cpu["safe"],
                        "cpu_limit_C": config["cpu_limit"],
                        "cpu_gate": cpu["gate"],
                        "cpu_decision": cpu["decision"],

                        "gpu_predicted_C": gpu["predicted"],
                        "gpu_margin_C": GPU_MARGIN,
                        "gpu_safe_C": gpu["safe"],
                        "gpu_limit_C": config["gpu_limit"],
                        "gpu_gate": gpu["gate"],
                        "gpu_decision": gpu["decision"],

                        "decision_reason": ";".join(reasons),
                    })

            def rate(admit, thermal):
                total = admit + thermal
                return 100.0 * admit / total if total else 0.0

            summary_rows.append({
                "run": run_name,
                "configuration": name,
                "cpu_limit_C": config["cpu_limit"],
                "gpu_limit_C": config["gpu_limit"],
                "records": counts["records"],
                "valid_status_records": counts["valid_status_records"],
                "invalid_status_records": counts["invalid_status_records"],
                "cpu_admit": counts["cpu_admit"],
                "cpu_thermal_defer": counts["cpu_thermal"],
                "cpu_invalid": counts["cpu_invalid"],
                "cpu_admission_rate_percent": round(
                    rate(counts["cpu_admit"], counts["cpu_thermal"]), 2
                ),
                "gpu_admit": counts["gpu_admit"],
                "gpu_thermal_defer": counts["gpu_thermal"],
                "gpu_invalid": counts["gpu_invalid"],
                "gpu_admission_rate_percent": round(
                    rate(counts["gpu_admit"], counts["gpu_thermal"]), 2
                ),
                "decision_csv": output_file,
            })

            for phase, pc in sorted(phase_counts.items()):
                phase_rows.append({
                    "run": run_name,
                    "configuration": name,
                    "phase": phase,
                    "records": pc["records"],
                    "cpu_admit": pc["cpu_admit"],
                    "cpu_thermal_defer": pc["cpu_thermal"],
                    "cpu_invalid": pc["cpu_invalid"],
                    "gpu_admit": pc["gpu_admit"],
                    "gpu_thermal_defer": pc["gpu_thermal"],
                    "gpu_invalid": pc["gpu_invalid"],
                })

            print(
                f"{run_name} | {name}: "
                f"CPU {counts['cpu_admit']} admit / "
                f"{counts['cpu_thermal']} thermal defer; "
                f"GPU {counts['gpu_admit']} admit / "
                f"{counts['gpu_thermal']} thermal defer"
            )

    summary_file = os.path.join(
        args.output_dir, "threshold_sweep_summary.csv"
    )
    phase_file = os.path.join(
        args.output_dir, "threshold_sweep_phase_summary.csv"
    )

    if summary_rows:
        with open(summary_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=list(summary_rows[0].keys())
            )
            writer.writeheader()
            writer.writerows(summary_rows)

    if phase_rows:
        with open(phase_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=list(phase_rows[0].keys())
            )
            writer.writeheader()
            writer.writerows(phase_rows)

    print("\n" + "=" * 65)
    print("THRESHOLD SWEEP COMPLETED")
    print(f"Configurations per input: {len(CONFIGS)}")
    print(f"Decision CSV files: {len(summary_rows)}")
    print(f"Summary: {summary_file}")
    print(f"Phase summary: {phase_file}")


if __name__ == "__main__":
    main()
