#!/bin/bash

set -u

cd "$HOME/thermal_experiment"

CPU=6
INTERVAL=1

HWCPU="/sys/class/hwmon/hwmon2"
HWGPU="/sys/class/hwmon/hwmon1"

OUT="rt_tas_next_$(date +%Y%m%d_%H%M%S).csv"

echo "timestamp,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,gpu_activity,cpu6_freq_MHz" > "$OUT"

sample()
{
    PHASE="$1"

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

    CPU_FREQ=$(awk '{printf "%.1f",$1/1000}' \
        /sys/devices/system/cpu/cpu6/cpufreq/scaling_cur_freq 2>/dev/null)

    echo "$(date +%s),$PHASE,$CPU_TEMP,$GPU_TEMP,$GPU_FREQ,$GPU_ACTIVITY,$CPU_FREQ" >> "$OUT"
}

set_gpu()
{
    echo "$1" > control.txt
}

run_off()
{
    PHASE="$1"
    SECONDS="$2"

    set_gpu GPU_OFF

    for ((i=0;i<SECONDS;i++))
    do
        sample "$PHASE"
        sleep 1
    done
}

run_both()
{
    PHASE="$1"
    SECONDS="$2"

    set_gpu GPU_ON

    taskset -c "$CPU" ./cpu_burn "$SECONDS" >/dev/null 2>&1 &
    CPU_PID=$!

    for ((i=0;i<SECONDS;i++))
    do
        sample "$PHASE"
        sleep 1
    done

    wait "$CPU_PID" 2>/dev/null
    set_gpu GPU_OFF
}

run_gpu()
{
    PHASE="$1"
    SECONDS="$2"

    set_gpu GPU_ON

    for ((i=0;i<SECONDS;i++))
    do
        sample "$PHASE"
        sleep 1
    done

    set_gpu GPU_OFF
}

run_cpu()
{
    PHASE="$1"
    SECONDS="$2"

    set_gpu GPU_OFF

    taskset -c "$CPU" ./cpu_burn "$SECONDS" >/dev/null 2>&1 &
    CPU_PID=$!

    for ((i=0;i<SECONDS;i++))
    do
        sample "$PHASE"
        sleep 1
    done

    wait "$CPU_PID" 2>/dev/null
}

echo "Starting local HTTP server..."

python3 -m http.server 8765 >/tmp/rt_tas_http.log 2>&1 &
HTTP_PID=$!

sleep 2

echo "Starting persistent GPU workload..."

chromium-browser \
    --user-data-dir=/tmp/chromium-rt-tas-next \
    --use-gl=angle \
    --use-angle=gles \
    --ignore-gpu-blocklist \
    --enable-gpu-rasterization \
    --no-first-run \
    --no-default-browser-check \
    "http://127.0.0.1:8765/gpu_scheduler.html" \
    >/tmp/rt_tas_chromium.log 2>&1 &

BROWSER_PID=$!

sleep 8

echo
echo "========================================"
echo "RT-TAS NEXT EXPERIMENT"
echo "========================================"
echo "CPU core       : $CPU"
echo "Output         : $OUT"
echo
echo "Workload:"
echo "  CPU required : 30 seconds"
echo "  GPU required : 30 seconds"
echo "  Deadline     : 60 seconds"
echo
echo "Baseline       : CPU + GPU simultaneously"
echo "Thermal-aware  : 5s GPU / 5s CPU"
echo "========================================"
echo

echo "BASELINE: idle 20s"
run_off BASELINE 20

echo "BASELINE: CPU + GPU 30s"
run_both BASELINE_BOTH 30

echo "BASELINE: cooldown 20s"
run_off BASELINE_COOLDOWN 20

echo "THERMAL-AWARE: idle 20s"
run_off TA_BASELINE 20

echo "THERMAL-AWARE: alternating 5s GPU / 5s CPU"

for WINDOW in {1..6}
do
    echo "Window $WINDOW: GPU"
    run_gpu TA_GPU 5

    echo "Window $WINDOW: CPU"
    run_cpu TA_CPU 5
done

echo "THERMAL-AWARE: cooldown 20s"
run_off TA_COOLDOWN 20

set_gpu GPU_OFF

kill "$BROWSER_PID" 2>/dev/null
kill "$HTTP_PID" 2>/dev/null

echo
echo "========================================"
echo "EXPERIMENT COMPLETE"
echo "========================================"
echo "CSV: $HOME/thermal_experiment/$OUT"
echo
