import csv

FILES = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv"
}

required = {
    "timestamp",
    "elapsed_s",
    "phase",
    "cpu_tctl_C",
    "gpu_edge_C",
    "gpu_freq_MHz",
    "cpu6_freq_MHz",
    "cpu_active",
    "gpu_enabled",
    "gpu_busy_percent"
}

for name, filename in FILES.items():
    print("\n====", name, "====")

    with open(filename, newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        rows = list(reader)

    missing = required - fields

    print("File:", filename)
    print("Samples:", len(rows))
    print("Columns:", len(fields))
    print("Required columns missing:", missing)

    if missing:
        print("STATUS: INCOMPATIBLE")
    else:
        print("STATUS: REQUIRED COLUMNS PRESENT")

    for col in ["cpu_tctl_C", "gpu_edge_C", "gpu_busy_percent"]:
        try:
            values = [float(r[col]) for r in rows]
            print(
                col,
                "min =", min(values),
                "max =", max(values)
            )
        except (ValueError, KeyError, TypeError):
            print("ERROR: Invalid values in", col)
