import csv
from pathlib import Path

FILES = sorted(Path(".").glob("thermal_predictor_shadow_*.csv"))
weights = (1, 2, 3)
stats = {
    w: {
        "active_n": 0, "active_hit": 0,
        "rising_n": 0, "rising_hit": 0,
        "outside_n": 0, "outside_hit": 0,
    }
    for w in weights
}

for path in FILES:
    with path.open(newline="") as f:
        rows = csv.DictReader(f)
        for r in rows:
            try:
                base = (
                    2 * int(r["gpu_temp_rising"])
                    + int(r["gpu_freq_increasing"])
                    + int(r["gpu_activity_increasing"])
                    + int(r["cpu_active"])
                    + int(r["recent_transition"])
                )
                cpu_rising = int(r["cpu_temp_rising"])
                active = r["phase"] == "CPU_ACTIVE"
                rising = cpu_rising == 1

                for w in weights:
                    score = base + w * cpu_rising
                    hit = score >= 4
                    s = stats[w]

                    if active:
                        s["active_n"] += 1
                        s["active_hit"] += hit

                    if rising:
                        s["rising_n"] += 1
                        s["rising_hit"] += hit

                    if not active:
                        s["outside_n"] += 1
                        s["outside_hit"] += hit

            except (KeyError, ValueError):
                continue

print("Offline CPU-temperature weight comparison")
print("Threshold: score >= 4")
print("Weight | CPU-active hits | Rising-temp hits | Outside-active hits")

for w in weights:
    s = stats[w]

    def fmt(hit, n):
        return f"{hit}/{n} ({100*hit/n:.1f}%)" if n else "N/A"

    print(
        f"{w} | "
        f"{fmt(s['active_hit'], s['active_n'])} | "
        f"{fmt(s['rising_hit'], s['rising_n'])} | "
        f"{fmt(s['outside_hit'], s['outside_n'])}"
    )

print("No live predictor or scheduler settings changed.")
