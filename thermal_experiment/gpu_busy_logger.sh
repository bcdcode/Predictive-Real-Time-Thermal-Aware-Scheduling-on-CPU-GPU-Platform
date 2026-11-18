#!/bin/bash
set -u

OUT="$1"

GPU_BUSY="/sys/class/drm/card0/device/gpu_busy_percent"

if [ ! -r "$GPU_BUSY" ]; then
    echo "ERROR: GPU busy sensor unavailable."
    exit 1
fi

echo "timestamp,gpu_busy_percent" > "$OUT"

echo "GPU busy logger started."
echo "Output: $OUT"

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    BUSY=$(cat "$GPU_BUSY" 2>/dev/null)

    if [[ "$BUSY" =~ ^[0-9]+$ ]]; then
        printf '%s,%s\n' "$TIMESTAMP" "$BUSY" >> "$OUT"
    fi

    sleep 1
done
