
#!/bin/bash

set -u

cd "$HOME/thermal_experiment" || exit 1

RT_TAS="./rt_tas_controlled.sh"
PREDICTOR="./thermal_predictor_shadow.py"

PREDICTOR_PID=""
CLEANING=0

cleanup() {
    [ "$CLEANING" -eq 1 ] && return
    CLEANING=1

    echo
    echo "Stopping predictor integration..."

    if [ -n "$PREDICTOR_PID" ]; then
        kill -TERM "$PREDICTOR_PID" 2>/dev/null || true
        wait "$PREDICTOR_PID" 2>/dev/null || true
    fi

    echo "Predictor stopped."
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Validate required files.
for f in "$RT_TAS" "$PREDICTOR" \
         "./gpu_workload_controlled.html" "./cpu_burn"; do
    if [ ! -e "$f" ]; then
        echo "ERROR: Missing required file: $f"
        exit 1
    fi
done

if [ ! -x "$RT_TAS" ]; then
    echo "Making RT_TAS executable..."
    chmod +x "$RT_TAS"
fi

echo "=========================================="
echo " RT_TAS + THERMAL PREDICTOR INTEGRATION"
echo "=========================================="
echo "Mode: SHADOW (no scheduling intervention)"
echo

# Start predictor first so it observes the complete experiment.
echo "Starting thermal predictor..."

python3 -u "$PREDICTOR" &
PREDICTOR_PID=$!

sleep 2

if ! kill -0 "$PREDICTOR_PID" 2>/dev/null; then
    echo "ERROR: Predictor failed to start."
    exit 1
fi

echo "Predictor is running."
echo

# Start controlled RT_TAS experiment.
echo "Starting controlled RT_TAS experiment..."
echo

"$RT_TAS"
RT_STATUS=$?

echo
echo "RT_TAS experiment finished with status: $RT_STATUS"

cleanup
trap - EXIT INT TERM

echo
echo "=========================================="
echo " INTEGRATION RUN FINISHED"
echo "=========================================="
echo "Inspect the RT_TAS CSV and predictor CSV."
echo "Compare their timestamps and workload phases."

exit "$RT_STATUS"

