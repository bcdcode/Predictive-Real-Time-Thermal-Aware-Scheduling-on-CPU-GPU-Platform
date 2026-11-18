#!/bin/bash

OUT="gpu_thermal_characterization_$(date +%Y%m%d_%H%M%S).csv"

BASELINE=30
ACTIVE=60
COOLDOWN=30
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

run_phase() {

    LEVEL="$1"
    SECONDS="$2"

    PROFILE="/tmp/chromium-gpu-characterization-${LEVEL}-$$"

    echo
    echo "========================================"
    echo "GPU LEVEL: ${LEVEL}%"
    echo "========================================"

    chromium-browser \
        --user-data-dir="$PROFILE" \
        --use-gl=angle \
        --use-angle=gles \
        --ignore-gpu-blocklist \
        --enable-gpu-rasterization \
        --no-first-run \
        --no-default-browser-check \
        "file://$HTML?duty=$LEVEL" \
        >/tmp/gpu-browser-${LEVEL}-$$.log 2>&1 &

    BROWSER_PID=$!

    echo "Browser PID: $BROWSER_PID"

    # Give Chromium/GPU process time to initialize.
    sleep 5

    echo "Collecting ${SECONDS}s..."

    for ((i=0; i<SECONDS; i++)); do

        log_sample "GPU_${LEVEL}" "$LEVEL"

        sleep "$INTERVAL"

    done

    echo "Stopping GPU workload..."

    kill "$BROWSER_PID" 2>/dev/null

    sleep 3

    pkill -f "$PROFILE" 2>/dev/null

    rm -rf "$PROFILE" 2>/dev/null
}

echo
echo "GPU THERMAL CHARACTERIZATION"
echo "Output: $OUT"
echo

echo "=== BASELINE ==="

for ((i=0; i<BASELINE; i++)); do

    log_sample "BASELINE" "0"

    sleep "$INTERVAL"

done

echo
echo "=== LOW GPU WORKLOAD ==="

run_phase 25 "$ACTIVE"

echo
echo "=== COOLDOWN ==="

for ((i=0; i<COOLDOWN; i++)); do

    log_sample "COOLDOWN" "0"

    sleep "$INTERVAL"

done

echo
echo "=== MEDIUM GPU WORKLOAD ==="

run_phase 50 "$ACTIVE"

echo
echo "=== COOLDOWN ==="

for ((i=0; i<COOLDOWN; i++)); do

    log_sample "COOLDOWN" "0"

    sleep "$INTERVAL"

done

echo
echo "=== HIGH GPU WORKLOAD ==="

run_phase 75 "$ACTIVE"

echo
echo "=== COOLDOWN ==="

for ((i=0; i<COOLDOWN; i++)); do

    log_sample "COOLDOWN" "0"

    sleep "$INTERVAL"

done

echo
echo "=== MAX GPU WORKLOAD ==="

run_phase 100 "$ACTIVE"

echo
echo "=== FINAL COOLDOWN ==="

for ((i=0; i<COOLDOWN; i++)); do

    log_sample "COOLDOWN" "0"

    sleep "$INTERVAL"

done

echo
echo "========================================"
echo "CHARACTERIZATION COMPLETE"
echo "========================================"
echo
echo "CSV: $OUT"
