#!/bin/bash

set -u

DIR="$HOME/thermal_experiment"
BURN="$DIR/cpu_burn"
OUT="$DIR/cpu_characterization.csv"

CORES=(0 1 2 3 4 5 6 7)

WORK_SECONDS=60
COOLDOWN_SECONDS=30
SAMPLE_INTERVAL=1

echo "Starting CPU thermal characterization"
echo "Output: $OUT"
echo

# CSV header
echo -n "timestamp,phase,test_core,cpu_temp_C,gpu_temp_C,gpu_power_W,gpu_freq_MHz,vddgfx_V,vddnb_V" > "$OUT"

for i in $(seq 0 15); do
    echo -n ",cpu${i}_freq_MHz" >> "$OUT"
done

echo >> "$OUT"

cleanup()
{
    echo
    echo "Stopping experiment..."

    pkill -TERM -f "$BURN" 2>/dev/null || true

    echo "Done."
}

trap cleanup INT TERM EXIT


log_sample()
{
    local phase="$1"
    local test_core="$2"

    timestamp=$(date '+%Y-%m-%d %H:%M:%S.%3N')

    cpu_temp=$(awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon2/temp1_input 2>/dev/null)

    gpu_temp=$(awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon1/temp1_input 2>/dev/null)

    gpu_power=$(awk '{printf "%.6f", $1/1000000}' \
        /sys/class/hwmon/hwmon1/power1_average 2>/dev/null)

    gpu_freq=$(awk '{printf "%.1f", $1/1000000}' \
        /sys/class/hwmon/hwmon1/freq1_input 2>/dev/null)

    vddgfx=$(awk '{printf "%.4f", $1/1000}' \
        /sys/class/hwmon/hwmon1/in0_input 2>/dev/null)

    vddnb=$(awk '{printf "%.4f", $1/1000}' \
        /sys/class/hwmon/hwmon1/in1_input 2>/dev/null)

    echo -n "$timestamp,$phase,$test_core,$cpu_temp,$gpu_temp,$gpu_power,$gpu_freq,$vddgfx,$vddnb" >> "$OUT"

    for i in $(seq 0 15); do

        f="/sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq"

        if [ -r "$f" ]; then
            awk '{printf ",%.1f", $1/1000}' "$f" >> "$OUT"
        else
            echo -n ",NA" >> "$OUT"
        fi

    done

    echo >> "$OUT"
}


run_phase()
{
    local phase="$1"
    local core="$2"
    local duration="$3"

    start=$(date +%s)

    while true; do

        now=$(date +%s)
        elapsed=$((now - start))

        if [ "$elapsed" -ge "$duration" ]; then
            break
        fi

        log_sample "$phase" "$core"

        sleep "$SAMPLE_INTERVAL"
    done
}


for core in "${CORES[@]}"; do

    echo
    echo "============================================"
    echo "Testing physical core: $core"
    echo "Logical CPU: $core"
    echo "Duration: ${WORK_SECONDS}s"
    echo "============================================"

    echo "Starting workload..."

    "$BURN" "$core" "$WORK_SECONDS" &
    BURN_PID=$!

    start=$(date +%s)

    while kill -0 "$BURN_PID" 2>/dev/null; do

        log_sample "LOAD" "$core"

        sleep "$SAMPLE_INTERVAL"

    done

    wait "$BURN_PID" 2>/dev/null || true

    echo "Core $core workload finished."

    if [ "$core" -ne 7 ]; then

        echo "Cooling down for ${COOLDOWN_SECONDS}s..."

        run_phase "COOLDOWN" "$core" "$COOLDOWN_SECONDS"

    fi

done

echo
echo "============================================"
echo "Experiment complete"
echo "============================================"
echo "Results:"
echo "$OUT"
echo