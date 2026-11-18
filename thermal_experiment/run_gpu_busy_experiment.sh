#!/bin/bash
set -u

cd "$HOME/thermal_experiment" || exit 1

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

GPU_LOG="gpu_busy_experiment_${TIMESTAMP}.csv"
RT_LOG="rt_tas_controlled_${TIMESTAMP}.csv"

LOGGER_PID=""

cleanup() {
    echo
    echo "Stopping GPU busy logger..."

    if [ -n "$LOGGER_PID" ]; then
        kill "$LOGGER_PID" 2>/dev/null || true
        wait "$LOGGER_PID" 2>/dev/null || true
        LOGGER_PID=""
    fi

    echo "GPU busy logger stopped."
    echo "GPU data: $HOME/thermal_experiment/$GPU_LOG"
    echo "RT-TAS data: latest rt_tas_controlled_*.csv"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "======================================"
echo " GPU-ACTIVITY-AWARE RT-TAS EXPERIMENT"
echo "======================================"

echo "GPU logger output: $GPU_LOG"

./gpu_busy_logger.sh "$GPU_LOG" &
LOGGER_PID=$!

sleep 2

if ! kill -0 "$LOGGER_PID" 2>/dev/null; then
    echo "ERROR: GPU logger failed to start."
    exit 1
fi

echo
echo "GPU busy logger is running."
echo "Starting RT-TAS controlled experiment..."
echo

./rt_tas_controlled.sh

STATUS=$?

echo
echo "RT-TAS experiment exit status: $STATUS"

exit "$STATUS"
