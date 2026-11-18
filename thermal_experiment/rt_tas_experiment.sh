#!/bin/bash

OUT="rt_tas_experiment_$(date +%Y%m%d_%H%M%S).csv"

HWCPU="/sys/class/hwmon/hwmon2"
HWGPU="/sys/class/hwmon/hwmon1"

CPU=6

BASELINE=20
ACTIVE=60
COOLDOWN=30

INTERVAL=1

GPU_HTML="$HOME/thermal_experiment/gpu_workload.html"

echo "timestamp,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,gpu_activity,cpu_freq_MHz" > "$OUT"

log_sample()
{
    phase="$1"

    CPU_TEMP=$(awk '{printf "%.3f",$1/1000}' \
        "$HWCPU/temp1_input")

    GPU_TEMP=$(awk '{printf "%.3f",$1/1000}' \
        "$HWGPU/temp1_input")

    GPU_FREQ=$(awk '{printf "%.1f",$1/1000000}' \
        "$HWGPU/freq1_input")

    GPU_ACTIVITY=$(awk -v f="$GPU_FREQ" '
    BEGIN {
        a=(f-400)/(2000-400)
        if(a<0)a=0
        if(a>1)a=1
        printf "%.3f",a
    }')

    CPU_FREQ=$(awk '{printf "%.1f",$1/1000000}' \
        "/sys/devices/system/cpu/cpu${CPU}/cpufreq/scaling_cur_freq" 2>/dev/null)

    echo "$(date +%H:%M:%S),$phase,$CPU_TEMP,$GPU_TEMP,$GPU_FREQ,$GPU_ACTIVITY,$CPU_FREQ" >> "$OUT"
}

collect()
{
    phase="$1"
    duration="$2"

    for ((i=0;i<duration;i++)); do
        log_sample "$phase"
        sleep "$INTERVAL"
    done
}

start_gpu()
{
    PROFILE="/tmp/chromium-rt-tas-$$"

    chromium-browser \
        --user-data-dir="$PROFILE" \
        --use-gl=angle \
        --use-angle=gles \
        --ignore-gpu-blocklist \
        --enable-gpu-rasterization \
        --no-first-run \
        --no-default-browser-check \
        "file://$GPU_HTML?duty=100" \
        >/tmp/rt-tas-gpu-$$.log 2>&1 &

    GPU_PID=$!

    sleep 5
}

stop_gpu()
{
    kill "$GPU_PID" 2>/dev/null
    sleep 2
    pkill -f "$PROFILE" 2>/dev/null
    rm -rf "$PROFILE" 2>/dev/null
}

start_cpu()
{
    taskset -c "$CPU" ./cpu_burn "$CPU" 60 >/dev/null 2>&1 &
    CPU_PID=$!
}

stop_cpu()
{
    kill "$CPU_PID" 2>/dev/null
    wait "$CPU_PID" 2>/dev/null
}

echo
echo "=============================================="
echo " RT-TAS CPU-GPU THERMAL EXPERIMENT"
echo "=============================================="
echo "Output: $OUT"
echo

# ==========================================================
# BASELINE
# ==========================================================

echo "BASELINE: 20 s"

collect "BASELINE" "$BASELINE"

echo
echo "BASELINE: CPU + GPU simultaneously"

start_gpu
start_cpu

collect "BASELINE_ACTIVE" "$ACTIVE"

stop_cpu
stop_gpu

echo
echo "BASELINE COOLDOWN"

collect "BASELINE_COOLDOWN" "$COOLDOWN"

# ==========================================================
# THERMAL-AWARE
# ==========================================================

echo
echo "THERMAL-AWARE: 20 s baseline"

collect "TA_BASELINE" "$BASELINE"

echo
echo "THERMAL-AWARE SCHEDULING"
echo "CPU and GPU alternate in 5-second windows."

TA_END=$((SECONDS + ACTIVE))

while [ "$SECONDS" -lt "$TA_END" ]; do

    # ------------------------------------------
    # GPU window
    # ------------------------------------------

    echo "GPU window"

    start_gpu

    for ((i=0;i<5;i++)); do
        log_sample "TA_GPU"
        sleep 1
    done

    stop_gpu

    # ------------------------------------------
    # CPU window
    # ------------------------------------------

    echo "CPU window"

    start_cpu

    for ((i=0;i<5;i++)); do
        log_sample "TA_CPU"
        sleep 1
    done

    stop_cpu

done

echo
echo "THERMAL-AWARE COOLDOWN"

collect "TA_COOLDOWN" "$COOLDOWN"

echo
echo "=============================================="
echo " EXPERIMENT COMPLETE"
echo "=============================================="
echo
echo "CSV: $OUT"
