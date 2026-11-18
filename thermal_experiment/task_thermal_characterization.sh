#!/bin/bash

OUT="task_thermal_characterization.csv"

echo "timestamp,phase,intensity,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,cpu0_freq_MHz" > "$OUT"

log_sample()
{
    timestamp=$(date '+%Y-%m-%d %H:%M:%S.%3N')

    cpu_temp=$(awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon2/temp1_input)

    gpu_temp=$(awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon1/temp1_input)

    gpu_freq=$(awk '{printf "%.1f", $1/1000000}' \
        /sys/class/hwmon/hwmon1/freq1_input)

    cpu_freq=$(awk '{printf "%.1f", $1/1000}' \
        /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)

    echo "$timestamp,$PHASE,$INTENSITY,$cpu_temp,$gpu_temp,$gpu_freq,$cpu_freq" >> "$OUT"
}

run_phase()
{
    PHASE="$1"
    INTENSITY="$2"
    DURATION="$3"

    END=$((SECONDS + DURATION))

    while [ "$SECONDS" -lt "$END" ]; do
        log_sample
        sleep 1
    done
}

echo "=== CPU task thermal characterization ==="
echo "Output: $OUT"

echo "Baseline: 20 seconds"
run_phase baseline 0 20

for INTENSITY in 1 2 3
do
    echo "Starting intensity $INTENSITY"

    ./cpu_task 0 10 "$INTENSITY" &
    PID=$!

    PHASE="active"
    END=$((SECONDS + 10))

    while [ "$SECONDS" -lt "$END" ]; do
        log_sample
        sleep 1
    done

    wait "$PID"

    echo "Cooldown: 30 seconds"

    run_phase cooldown "$INTENSITY" 30
done

echo "Experiment complete"
