#!/bin/bash

OUT="gpu_thermal_short_$(date +%Y%m%d_%H%M%S).csv"

BASELINE=20
ACTIVE=30
COOLDOWN=20
INTERVAL=1

HWCPU="/sys/class/hwmon/hwmon2"
HWGPU="/sys/class/hwmon/hwmon1"
HTML="$HOME/thermal_experiment/gpu_workload.html"

echo "timestamp,phase,gpu_level,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,gpu_activity" > "$OUT"

log_sample() {

    phase="$1"
    level="$2"

    CPU_TEMP=$(awk '{printf "%.3f",$1/1000}' "$HWCPU/temp1_input")
    GPU_TEMP=$(awk '{printf "%.3f",$1/1000}' "$HWGPU/temp1_input")
    GPU_FREQ=$(awk '{printf "%.1f",$1/1000000}' "$HWGPU/freq1_input")

    GPU_ACTIVITY=$(awk -v f="$GPU_FREQ" '
    BEGIN {
        a=(f-400)/(2000-400)
        if(a<0) a=0
        if(a>1) a=1
        printf "%.3f",a
    }')

    echo "$(date +%H:%M:%S),$phase,$level,$CPU_TEMP,$GPU_TEMP,$GPU_FREQ,$GPU_ACTIVITY" >> "$OUT"
}

collect() {

    phase="$1"
    level="$2"
    duration="$3"

    echo
    echo "----------------------------------------"
    echo "$phase  (${level}%)"
    echo "----------------------------------------"

    for ((i=0; i<duration; i++)); do
        log_sample "$phase" "$level"
        sleep "$INTERVAL"
    done
}

run_gpu() {

    level="$1"
    duration="$2"

    PROFILE="/tmp/chromium-gpu-short-${level}-$$"

    echo
    echo "Starting GPU workload: ${level}%"

    chromium-browser \
        --user-data-dir="$PROFILE" \
        --use-gl=angle \
        --use-angle=gles \
        --ignore-gpu-blocklist \
        --enable-gpu-rasterization \
        --no-first-run \
        --no-default-browser-check \
        "file://$HTML?duty=$level" \
        >/tmp/gpu-short-${level}-$$.log 2>&1 &

    BROWSER_PID=$!

    # Allow GPU process to initialize.
    sleep 4

    collect "GPU_${level}" "$level" "$duration"

    echo "Stopping GPU workload..."

    kill "$BROWSER_PID" 2>/dev/null
    sleep 2
    pkill -f "$PROFILE" 2>/dev/null
    rm -rf "$PROFILE" 2>/dev/null
}

echo
echo "========================================"
echo "GPU THERMAL CHARACTERIZATION"
echo "========================================"
echo "Output: $OUT"
echo

# -----------------------------------------
# BASELINE
# -----------------------------------------

collect "BASELINE" 0 "$BASELINE"

# -----------------------------------------
# 25%
# -----------------------------------------

run_gpu 25 "$ACTIVE"

collect "COOLDOWN" 0 "$COOLDOWN"

# -----------------------------------------
# 50%
# -----------------------------------------

run_gpu 50 "$ACTIVE"

collect "COOLDOWN" 0 "$COOLDOWN"

# -----------------------------------------
# 75%
# -----------------------------------------

run_gpu 75 "$ACTIVE"

collect "COOLDOWN" 0 "$COOLDOWN"

# -----------------------------------------
# 100%
# -----------------------------------------

run_gpu 100 "$ACTIVE"

collect "COOLDOWN" 0 "$COOLDOWN"

echo
echo "========================================"
echo "COMPLETE"
echo "========================================"
echo
echo "CSV: $OUT"
