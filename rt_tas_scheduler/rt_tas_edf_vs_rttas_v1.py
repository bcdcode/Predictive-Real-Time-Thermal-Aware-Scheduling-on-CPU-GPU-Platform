#!/usr/bin/env python3

import csv
import argparse
from collections import Counter


def load_results(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def metrics(rows):
    counts = Counter(row["status"] for row in rows)

    met = counts.get("DEADLINE_MET", 0)
    missed = counts.get("DEADLINE_MISSED_AFTER_EXECUTION", 0)
    expired = counts.get("EXPIRED_WITHOUT_ADMISSION", 0)
    pending = counts.get("PENDING", 0)

    admitted = sum(
        1 for row in rows
        if row.get("start_s", "").strip().lower()
        not in ("", "none", "null")
    )

    return {
        "total": len(rows),
        "admitted": admitted,
        "met": met,
        "missed": missed,
        "expired": expired,
        "pending": pending,
        "deadline_rate": 100.0 * met / len(rows) if rows else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edf", required=True)
    parser.add_argument("--rttas", required=True)
    parser.add_argument(
        "--output",
        default="rt_tas_edf_vs_rttas_v1.csv"
    )
    args = parser.parse_args()

    edf = load_results(args.edf)
    rttas = load_results(args.rttas)

    edf_by_id = {r["task_id"]: r for r in edf}
    rttas_by_id = {r["task_id"]: r for r in rttas}

    if set(edf_by_id) != set(rttas_by_id):
        raise SystemExit("ERROR: Task sets do not match.")

    for task_id in edf_by_id:
        if edf_by_id[task_id]["resource"] != rttas_by_id[task_id]["resource"]:
            raise SystemExit(f"ERROR: Resource mismatch for {task_id}.")

        if edf_by_id[task_id]["deadline_s"] != rttas_by_id[task_id]["deadline_s"]:
            raise SystemExit(f"ERROR: Deadline mismatch for {task_id}.")

    em = metrics(edf)
    rm = metrics(rttas)

    print("\nEDF vs PREDICTIVE RT-TAS")
    print("=" * 65)
    print(f"{'Metric':<30}{'EDF':>15}{'RT-TAS':>15}")
    print("-" * 65)

    fields = [
        ("Total tasks", "total"),
        ("Admitted / dispatched", "admitted"),
        ("Deadlines met", "met"),
        ("Missed after execution", "missed"),
        ("Expired without admission", "expired"),
        ("Pending", "pending"),
    ]

    for label, key in fields:
        print(f"{label:<30}{em[key]:>15}{rm[key]:>15}")

    print("-" * 65)
    print(
        f"{'Deadline success rate (%)':<30}"
        f"{em['deadline_rate']:>14.2f}%"
        f"{rm['deadline_rate']:>14.2f}%"
    )

    output_rows = []
    for task_id in sorted(edf_by_id):
        e = edf_by_id[task_id]
        r = rttas_by_id[task_id]

        output_rows.append({
            "task_id": task_id,
            "resource": e["resource"],
            "edf_start_s": e["start_s"],
            "edf_finish_s": e["finish_s"],
            "edf_status": e["status"],
            "rttas_start_s": r["start_s"],
            "rttas_finish_s": r["finish_s"],
            "rttas_status": r["status"],
        })

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0].keys()))
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nDetailed comparison saved to: {args.output}")


if __name__ == "__main__":
    main()
