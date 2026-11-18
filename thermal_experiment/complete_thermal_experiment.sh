#!/bin/bash

# ============================================================
# COMPLETE CPU-GPU THERMAL EXPERIMENT
# Platform: Oracle Linux 8.x
# GPU: AMD integrated GPU (amdgpu)
#
# Phases:
# 1. Idle
# 2. CPU only
# 3. GPU only (WebGL)
# 4. CPU + GPU
# 5. Recovery
#
# Automatically:
# - Detects thermal sensors
# - Creates WebGL workload page
# - Starts local HTTP server
# - Opens Chromium
# - Controls CPU and GPU workloads
# - Logs measurements to CSV
# - Closes Chromium and HTTP server
# ============================================================

set -u

BASE_DIR="$HOME/thermal_experiment"
cd "$BASE_DIR" || exit 1

RUN_ID=$(date +%Y%m%d_%H%M%S)
RUN_DIR="$BASE_DIR/complete_run_$RUN_ID"

mkdir -p "$RUN_DIR"
cd "$RUN_DIR" || exit 1

# ---------------- CONFIGURATION ----------------

IDLE_TIME=20
CPU_TIME=30
GPU_TIME=30
MIXED_TIME=30
RECOVERY_TIME=30

CPU_WORKERS=2
INTERVAL=1
PORT=8765

CSV_FILE="$RUN_DIR/thermal_data.csv"
HTML_FILE="$RUN_DIR/webgl_workload.html"

GPU_CONTROL="$RUN_DIR/gpu_control.txt"
CPU_CONTROL="$RUN_DIR/cpu_control.txt"
PHASE_FILE="$RUN_DIR/phase.txt"

SERVER_LOG="$RUN_DIR/server.log"
CHROME_LOG="$RUN_DIR/chromium.log"

SERVER_PID=""
CHROME_PID=""
LOGGER_PID=""

CPU_PIDS=()
CLEANING=0

# ---------------- SENSOR DETECTION ----------------

find_sensor() {

    local expected_chip="$1"
    local expected_label="$2"

    for hwmon in /sys/class/hwmon/hwmon*; do

        [ -r "$hwmon/name" ] || continue

        chip=$(cat "$hwmon/name" 2>/dev/null)

        [ "$chip" = "$expected_chip" ] || continue

        for label_file in "$hwmon"/*_label; do

            [ -r "$label_file" ] || continue

            label=$(cat "$label_file" 2>/dev/null)

            [ "$label" = "$expected_label" ] || continue

            base="${label_file%_label}"

            if [ -r "${base}_input" ]; then
                echo "${base}_input"
                return
            fi

            if [ -r "${base}_average" ]; then
                echo "${base}_average"
                return
            fi

        done
    done

    echo ""
}

CPU_TEMP=$(find_sensor k10temp Tctl)
GPU_TEMP=$(find_sensor amdgpu edge)
GPU_FREQ=$(find_sensor amdgpu sclk)
GPU_VDDGFX=$(find_sensor amdgpu vddgfx)
GPU_VDDNB=$(find_sensor amdgpu vddnb)
GPU_POWER=$(find_sensor amdgpu slowPPT)

read_sensor() {

    file="$1"
    divisor="$2"

    if [ -n "$file" ] && [ -r "$file" ]; then
        awk -v d="$divisor" '{printf "%.3f", $1/d}' "$file" 2>/dev/null
    else
        echo ""
    fi
}

# ---------------- CONTROL FILES ----------------

echo OFF > "$GPU_CONTROL"
echo OFF > "$CPU_CONTROL"
echo IDLE > "$PHASE_FILE"

# ---------------- WEBGL HTML PAGE ----------------

cat > "$HTML_FILE" <<'HTML'
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">

<title>Controlled WebGL Workload</title>

<style>
body {
    background: #101820;
    color: white;
    font-family: Arial;
    text-align: center;
}

canvas {
    width: 90%;
    max-width: 960px;
    border: 2px solid white;
}

#status {
    font-size: 24px;
    color: lightgreen;
}
</style>

</head>

<body>

<h1>GPU WebGL Thermal Workload</h1>

<div id="status">INITIALIZING</div>

<p id="renderer"></p>

<canvas id="glcanvas" width="960" height="540"></canvas>

<script>

const canvas = document.getElementById("glcanvas");
const status = document.getElementById("status");
const rendererText = document.getElementById("renderer");

const gl =
    canvas.getContext("webgl2", {
        powerPreference: "high-performance",
        antialias: false
    }) ||
    canvas.getContext("webgl", {
        powerPreference: "high-performance",
        antialias: false
    });

if (!gl) {

    status.innerText = "WEBGL NOT AVAILABLE";

} else {

    rendererText.innerText =
        "Renderer: " + gl.getParameter(gl.RENDERER);

    const webgl2 =
        typeof WebGL2RenderingContext !== "undefined" &&
        gl instanceof WebGL2RenderingContext;

    const vertexSource = webgl2 ? `#version 300 es
        in vec2 position;
        out vec2 uv;

        void main() {
            uv = position * 0.5 + 0.5;
            gl_Position = vec4(position, 0.0, 1.0);
        }`
        :
        `attribute vec2 position;
         varying vec2 uv;

         void main() {
             uv = position * 0.5 + 0.5;
             gl_Position = vec4(position, 0.0, 1.0);
         }`;

    const fragmentSource = webgl2 ? `#version 300 es
        precision highp float;

        in vec2 uv;
        out vec4 outColor;
        uniform float t;

        void main() {

            vec2 p = (uv - 0.5) * 2.4;
            float v = 0.0;

            for (int i = 0; i < 90; i++) {

                float fi = float(i);

                p = vec2(
                    p.x*p.x - p.y*p.y,
                    2.0*p.x*p.y
                ) + vec2(
                    0.21*sin(t*0.7 + fi*0.03),
                    0.17*cos(t*0.5 + fi*0.02)
                );

                v += 0.0007 /
                     (0.015 + abs(length(p)-0.7));

                p = mod(p+2.0,4.0)-2.0;
            }

            outColor = vec4(
                0.15 + 0.75*abs(sin(v+t*0.2)),
                0.12 + 0.65*abs(cos(v*0.7)),
                0.25 + 0.7*abs(sin(v*0.4)),
                1.0
            );
        }`
        :
        `precision highp float;

         varying vec2 uv;
         uniform float t;

         void main() {

             vec2 p = (uv - 0.5) * 2.4;
             float v = 0.0;

             for (int i = 0; i < 90; i++) {

                 float fi = float(i);

                 p = vec2(
                     p.x*p.x - p.y*p.y,
                     2.0*p.x*p.y
                 ) + vec2(
                     0.21*sin(t*0.7 + fi*0.03),
                     0.17*cos(t*0.5 + fi*0.02)
                 );

                 v += 0.0007 /
                      (0.015 + abs(length(p)-0.7));

                 p = mod(p+2.0,4.0)-2.0;
             }

             gl_FragColor = vec4(
                 0.15 + 0.75*abs(sin(v+t*0.2)),
                 0.12 + 0.65*abs(cos(v*0.7)),
                 0.25 + 0.7*abs(sin(v*0.4)),
                 1.0
             );
         }`;

    function compile(type, source) {

        const shader = gl.createShader(type);

        gl.shaderSource(shader, source);
        gl.compileShader(shader);

        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            throw new Error(gl.getShaderInfoLog(shader));
        }

        return shader;
    }

    try {

        const program = gl.createProgram();

        gl.attachShader(
            program,
            compile(gl.VERTEX_SHADER, vertexSource)
        );

        gl.attachShader(
            program,
            compile(gl.FRAGMENT_SHADER, fragmentSource)
        );

        gl.linkProgram(program);

        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
            throw new Error(gl.getProgramInfoLog(program));
        }

        gl.useProgram(program);

        const buffer = gl.createBuffer();

        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);

        gl.bufferData(
            gl.ARRAY_BUFFER,
            new Float32Array([
                -1,-1,
                 1,-1,
                -1, 1,
                 1, 1
            ]),
            gl.STATIC_DRAW
        );

        const position =
            gl.getAttribLocation(program, "position");

        gl.enableVertexAttribArray(position);

        gl.vertexAttribPointer(
            position, 2, gl.FLOAT, false, 0, 0
        );

        const timeLocation =
            gl.getUniformLocation(program, "t");

        let enabled = false;
        let frames = 0;
        let lastPoll = 0;

        async function pollControl() {

            try {

                const response = await fetch(
                    "/gpu_control.txt?t=" + Date.now(),
                    { cache: "no-store" }
                );

                const value =
                    (await response.text()).trim().toUpperCase();

                enabled = value === "ON";

            } catch (error) {

                enabled = false;

            }

            status.innerText = enabled
                ? "GPU WORKLOAD: ON"
                : "GPU WORKLOAD: OFF";
        }

        async function render(now) {

            if (enabled) {

                gl.viewport(
                    0, 0, canvas.width, canvas.height
                );

                gl.uniform1f(
                    timeLocation,
                    now * 0.001
                );

                gl.drawArrays(
                    gl.TRIANGLE_STRIP, 0, 4
                );

                frames++;
            }

            if (now - lastPoll > 1000) {
                await pollControl();
                lastPoll = now;
            }

            requestAnimationFrame(render);
        }

        pollControl();
        requestAnimationFrame(render);

    } catch (error) {

        status.innerText = "SHADER ERROR";
        rendererText.innerText = String(error);

    }
}

</script>

</body>
</html>
HTML

# ---------------- CSV HEADER ----------------

{
    printf "timestamp,elapsed_s,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,vddgfx_V,vddnb_V,gpu_power_W,gpu_control,cpu_active"

    CPU_COUNT=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)

    for ((i=0; i<CPU_COUNT; i++)); do
        printf ",cpu%d_freq_MHz" "$i"
    done

    printf "\n"

} > "$CSV_FILE"

# ---------------- CPU WORKLOAD ----------------

start_cpu() {

    for ((i=0; i<CPU_WORKERS; i++)); do
        yes > /dev/null &
        CPU_PIDS+=("$!")
    done

    echo ON > "$CPU_CONTROL"
}

stop_cpu() {

    for pid in "${CPU_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done

    CPU_PIDS=()

    echo OFF > "$CPU_CONTROL"
}

# ---------------- CLEANUP ----------------

cleanup() {

    if [ "$CLEANING" -eq 1 ]; then
        return
    fi

    CLEANING=1

    echo
    echo "[CLEANUP] Stopping experiment..."

    echo OFF > "$GPU_CONTROL"
    stop_cpu

    if [ -n "$LOGGER_PID" ]; then
        kill "$LOGGER_PID" 2>/dev/null || true
    fi

    if [ -n "$CHROME_PID" ]; then
        kill "$CHROME_PID" 2>/dev/null || true
    fi

    # Close only Chromium processes using this run's profile.
    if command -v pgrep >/dev/null 2>&1; then

        pgrep -f -- "$CHROME_PROFILE" 2>/dev/null |
        while read -r pid; do
            kill "$pid" 2>/dev/null || true
        done

    fi

    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi

    echo FINISHED > "$PHASE_FILE"

    echo "[CLEANUP] Experiment stopped."
    echo "[CLEANUP] CSV: $CSV_FILE"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------------- LOGGER ----------------

log_loop() {

    START_TIME=$(date +%s)

    NEXT_SAMPLE=$START_TIME

    while true; do

        NOW=$(date +%s)

        if [ "$NOW" -lt "$NEXT_SAMPLE" ]; then
            sleep 0.05
            continue
        fi

        ELAPSED=$((NOW-START_TIME))

        PHASE=$(cat "$PHASE_FILE" 2>/dev/null)
        GPU_STATE=$(cat "$GPU_CONTROL" 2>/dev/null)
        CPU_STATE=$(cat "$CPU_CONTROL" 2>/dev/null)

        CPU_ACTIVE=0
        [ "$CPU_STATE" = "ON" ] && CPU_ACTIVE=1

        printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s' \
            "$(date '+%Y-%m-%d %H:%M:%S')" \
            "$ELAPSED" \
            "$PHASE" \
            "$(read_sensor "$CPU_TEMP" 1000)" \
            "$(read_sensor "$GPU_TEMP" 1000)" \
            "$(read_sensor "$GPU_FREQ" 1000000)" \
            "$(read_sensor "$GPU_VDDGFX" 1000)" \
            "$(read_sensor "$GPU_VDDNB" 1000)" \
            "$(read_sensor "$GPU_POWER" 1000000)" \
            "$GPU_STATE" \
            "$CPU_ACTIVE" >> "$CSV_FILE"

        CPU_COUNT=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)

        for ((i=0; i<CPU_COUNT; i++)); do

            FREQ_FILE="/sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq"

            printf ',%s' \
                "$(read_sensor "$FREQ_FILE" 1000)" \
                >> "$CSV_FILE"

        done

        printf '\n' >> "$CSV_FILE"

        NEXT_SAMPLE=$((NEXT_SAMPLE+INTERVAL))

    done
}
# ---------------- PHASE CONTROL ----------------

run_phase() {

    PHASE="$1"
    DURATION="$2"
    GPU_STATE="$3"
    CPU_STATE="$4"

    echo
    echo "======================================"
    echo " PHASE: $PHASE"
    echo " DURATION: $DURATION seconds"
    echo "======================================"

    echo "$PHASE" > "$PHASE_FILE"

    echo OFF > "$GPU_CONTROL"
    stop_cpu

    if [ "$CPU_STATE" = "ON" ]; then
        start_cpu
    fi

    echo "$GPU_STATE" > "$GPU_CONTROL"

    sleep "$DURATION"

    echo OFF > "$GPU_CONTROL"
    stop_cpu
}

# ---------------- CHECK DEPENDENCIES ----------------

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required."
    exit 1
fi

CHROME_BIN=""

for candidate in chromium-browser chromium google-chrome google-chrome-stable; do

    if command -v "$candidate" >/dev/null 2>&1; then
        CHROME_BIN=$(command -v "$candidate")
        break
    fi

done

if [ -z "$CHROME_BIN" ]; then
    echo "ERROR: Chromium/Chrome not found in PATH."
    exit 1
fi

CHROME_PROFILE="$RUN_DIR/chromium_profile"

# ---------------- START HTTP SERVER ----------------

echo
echo "[START] Starting local HTTP server..."

python3 -m http.server "$PORT" \
    --bind 127.0.0.1 \
    > "$SERVER_LOG" 2>&1 &

SERVER_PID=$!

READY=0

for i in {1..30}; do

    if python3 -c "
import urllib.request
urllib.request.urlopen(
    'http://127.0.0.1:$PORT/webgl_workload.html',
    timeout=1
)" >/dev/null 2>&1; then

        READY=1
        break

    fi

    sleep 1

done

if [ "$READY" -eq 0 ]; then
    echo "ERROR: HTTP server did not start."
    exit 1
fi

# ---------------- OPEN CHROMIUM ----------------

echo
echo "[START] Opening WebGL page in Chromium..."

"$CHROME_BIN" \
    --user-data-dir="$CHROME_PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    --no-sandbox \
    --ignore-gpu-blocklist \
    --enable-webgl \
    --autoplay-policy=no-user-gesture-required \
    "http://127.0.0.1:$PORT/webgl_workload.html" \
    > "$CHROME_LOG" 2>&1 &

CHROME_PID=$!

sleep 5

# ---------------- START LOGGER ----------------

log_loop &
LOGGER_PID=$!

# ---------------- RUN EXPERIMENT ----------------

echo
echo "======================================"
echo " STARTING COMPLETE EXPERIMENT"
echo "======================================"

echo "CPU sensor: ${CPU_TEMP:-NOT FOUND}"
echo "GPU sensor: ${GPU_TEMP:-NOT FOUND}"
echo "GPU clock:  ${GPU_FREQ:-NOT FOUND}"

run_phase "IDLE_PRE" "$IDLE_TIME" OFF OFF

run_phase "CPU_ONLY" "$CPU_TIME" OFF ON

run_phase "GPU_ONLY" "$GPU_TIME" ON OFF

run_phase "CPU_GPU_MIXED" "$MIXED_TIME" ON ON

run_phase "RECOVERY" "$RECOVERY_TIME" OFF OFF

echo
echo "======================================"
echo " EXPERIMENT COMPLETED"
echo "======================================"

echo "CSV file: $CSV_FILE"
echo "Run directory: $RUN_DIR"

exit 0

