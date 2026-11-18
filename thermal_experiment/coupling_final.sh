#!/bin/bash

OUT="coupling_final_$(date +%Y%m%d_%H%M%S).csv"
INTERVAL=1
BASELINE=30
ACTIVE=60
COOLDOWN=30
CPU=6

HWCPU="/sys/class/hwmon/hwmon2"
HWGPU="/sys/class/hwmon/hwmon1"

echo "timestamp,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,gpu_activity,cpu_freq_MHz" > "$OUT"

log_phase() {
    local PHASE="$1"
    local SECONDS="$2"

    for ((i=0; i<SECONDS; i++)); do
        TS=$(date +%s)

        CPU_TEMP=$(awk '{printf "%.3f", $1/1000}' "$HWCPU/temp1_input")
        GPU_TEMP=$(awk '{printf "%.3f", $1/1000}' "$HWGPU/temp1_input")
        GPU_FREQ=$(awk '{printf "%.1f", $1/1000}' "$HWGPU/freq1_input")

        GPU_ACTIVITY=$(awk -v f="$GPU_FREQ" \
            'BEGIN {
                u=(f-400)/(2000-400);
                if(u<0)u=0;
                if(u>1)u=1;
                printf "%.3f",u
            }')

        CPU_FREQ=$(awk '{printf "%.1f", $1/1000}' \
            "/sys/devices/system/cpu/cpu${CPU}/cpufreq/scaling_cur_freq" 2>/dev/null)

        echo "$TS,$PHASE,$CPU_TEMP,$GPU_TEMP,$GPU_FREQ,$GPU_ACTIVITY,$CPU_FREQ" >> "$OUT"

        sleep "$INTERVAL"
    done
}

start_gpu() {
    PROFILE="/tmp/chromium-gpu-rt-tas-final"

    rm -rf "$PROFILE"

    chromium-browser \
        --user-data-dir="$PROFILE" \
        --use-gl=angle \
        --use-angle=gles \
        --ignore-gpu-blocklist \
        --enable-gpu-rasterization \
        --no-first-run \
        --no-default-browser-check \
        "file://$HOME/thermal_experiment/gpu_stress_safe.html" \
        >/tmp/chromium-gpu-rt-tas-final.log 2>&1 &

    CHROME_PID=$!

    echo "Waiting for GPU workload..."

    ACTIVE_COUNT=0

    for ((i=0; i<60; i++)); do
        sleep 1

        GPU_FREQ=$(awk '{printf "%.0f", $1/1000}' "$HWGPU/freq1_input")

        echo "GPU frequency: ${GPU_FREQ} MHz"

        if [ "$GPU_FREQ" -ge 1900 ]; then
            ACTIVE_COUNT=$((ACTIVE_COUNT+1))
        else
            ACTIVE_COUNT=0
        fi

        if [ "$ACTIVE_COUNT" -ge 3 ]; then
            echo "GPU workload confirmed active."
            return 0
        fi
    done

    echo "ERROR: GPU workload did not reach 1900 MHz."
    return 1
}

stop_gpu() {
    if [ -n "$CHROME_PID" ]; then
        kill "$CHROME_PID" 2>/dev/null
        sleep 2
        CHROME_PID=""
    fi
}

echo
echo "=========================================="
echo " CPU-GPU THERMAL COUPLING EXPERIMENT"
echo "=========================================="
echo
echo "Output: $OUT"
echo

echo "PHASE 1: Baseline — no GPU workload"
log_phase BASELINE1 "$BASELINE"

echo
echo "PHASE 2: GPU-only"
start_gpu || exit 1
log_phase GPU_ONLY "$ACTIVE"

echo
echo "Stopping GPU workload..."
stop_gpu

echo
echo "PHASE 3: Cooldown"
log_phase COOLDOWN1 "$COOLDOWN"

echo
echo "PHASE 4: Second baseline — no workload"
log_phase BASELINE2 "$BASELINE"

echo
echo "PHASE 5: CPU + GPU"
start_gpu || exit 1

echo "Starting CPU workload on CPU $CPU..."
taskset -c "$CPU" ./cpu_burn "$ACTIVE" >/tmp/cpu_burn_coupling.log 2>&1 &
CPU_PID=$!

log_phase CPU_GPU "$ACTIVE"

wait "$CPU_PID" 2>/dev/null
stop_gpu

echo
echo "PHASE 6: Final cooldown"
log_phase COOLDOWN2 "$COOLDOWN"

echo
echo "=========================================="
echo "Experiment completed"
echo "=========================================="
echo
echo "CSV file:"
echo "$OUT"
echo

