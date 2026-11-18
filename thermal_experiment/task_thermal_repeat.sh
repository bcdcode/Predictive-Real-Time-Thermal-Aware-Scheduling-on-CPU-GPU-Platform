#!/bin/bash

OUT="task_thermal_repeat.csv"

echo "timestamp,phase,intensity,run,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,cpu0_freq_MHz" > "$OUT"

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

    echo "$timestamp,$PHASE,$INTENSITY,$RUN,$cpu_temp,$gpu_temp,$gpu_freq,$cpu_freq" >> "$OUT"
}

run_phase()
{
    PHASE="$1"
    INTENSITY="$2"
    RUN="$3"
    DURATION="$4"

    END=$((SECONDS + DURATION))

    while [ "$SECONDS" -lt "$END" ]; do
        log_sample
        sleep 1
    done
}

echo "=========================================="
echo "Task Thermal Repeat Experiment"
echo "=========================================="
echo "Output: $OUT"
echo

for RUN in 1 2 3
do
    echo "=========================================="
    echo "RUN $RUN"
    echo "=========================================="

    for INTENSITY in 1 2 3
    do
        echo
        echo "Intensity $INTENSITY"
        echo "  Baseline: 20 seconds"

        run_phase baseline "$INTENSITY" "$RUN" 20

        echo "  Starting workload..."

        ./cpu_task 0 10 "$INTENSITY" &
        PID=$!

        PHASE="active"
        END=$((SECONDS + 10))

        while [ "$SECONDS" -lt "$END" ]; do
            log_sample
            sleep 1
        done

        wait "$PID"

        echo "  Workload finished"
        echo "  Cooldown: 30 seconds"

        run_phase cooldown "$INTENSITY" "$RUN" 30

        echo "  Intensity $INTENSITY complete"
    done

    echo
    echo "RUN $RUN complete"
done

echo
echo "=========================================="
echo "Experiment complete"
echo "=========================================="
echo "Results: $OUT"
