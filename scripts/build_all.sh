#!/usr/bin/env bash
# build_all.sh
#
# Builds the ESP32 RNG firmware for each of the 8 entropy modes,
# flashes it to the connected board, and collects the UART samples.
#
# Prerequisites:
#   • ESP-IDF environment is sourced  (. $IDF_PATH/export.sh)
#   • pyserial is installed            (pip install pyserial)
#   • ESP32 is connected via USB
#
# Override the serial port via the ESP_PORT environment variable:
#   ESP_PORT=/dev/cu.usbserial-0001 ./scripts/build_all.sh
#
# The script only processes modes listed in MODES_TO_RUN.
# Comment out any modes you want to skip.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ANALYSIS_DIR="$PROJECT_DIR/analysis"
DATA_DIR="$PROJECT_DIR/data"
RESULTS_DIR="$PROJECT_DIR/results"

MODE_NAMES=(BARE WIFI BT WIFI_BT ADC ADC_WIFI ADC_BT ADC_WIFI_BT)

# --- Set to the modes you want to run (0-7) ---
MODES_TO_RUN=(0 1 2 3 4 5 6 7)

# Serial port — auto-detected from common macOS/Linux patterns if not set
# might need to change to COM* on Windows, but I haven't tested there
if [[ -z "${ESP_PORT:-}" ]]; then
    for pat in /dev/cu.usbserial* /dev/cu.SLAB* /dev/cu.wchusbserial* /dev/ttyUSB* /dev/ttyACM*; do
        if ls $pat 2>/dev/null | head -1 | grep -q .; then
            ESP_PORT=$(ls $pat 2>/dev/null | head -1)
            break
        fi
    done
fi

if [[ -z "${ESP_PORT:-}" ]]; then
    echo "ERROR: No serial port found.  Set ESP_PORT=/dev/... and retry." >&2
    exit 1
fi

echo "=================================================="
echo " ESP32 RNG Analysis — full mode sweep"
echo " Project : $PROJECT_DIR"
echo " Port    : $ESP_PORT"
echo " Modes   : ${MODES_TO_RUN[*]}"
echo "=================================================="
echo ""

mkdir -p "$DATA_DIR" "$RESULTS_DIR"

cd "$PROJECT_DIR"

for MODE in "${MODES_TO_RUN[@]}"; do
    NAME="${MODE_NAMES[$MODE]}"
    echo "---------- Mode $MODE : $NAME ----------"

    # --- Generate a merged sdkconfig.defaults for this mode ---
    MERGED_DEFAULTS="$PROJECT_DIR/.sdkconfig_mode${MODE}_tmp"
    cat "$PROJECT_DIR/sdkconfig.defaults" \
        "$PROJECT_DIR/sdkconfig.defaults.mode${MODE}" > "$MERGED_DEFAULTS"

    # --- Force regeneration of sdkconfig from new defaults ---
    rm -f "$PROJECT_DIR/sdkconfig"
    SDKCONFIG_DEFAULTS="$MERGED_DEFAULTS" idf.py reconfigure

    # --- Build ---
    echo "[build] Building mode $MODE ($NAME) …"
    SDKCONFIG_DEFAULTS="$MERGED_DEFAULTS" idf.py build

    # --- Flash ---
    echo "[flash] Flashing mode $MODE ($NAME) …"
    idf.py -p "$ESP_PORT" flash

    # --- Collect samples ---
    # The firmware starts automatically after reset.
    echo "[collect] Collecting samples …"
    python3 "$ANALYSIS_DIR/collect.py" \
        --port "$ESP_PORT" \
        --output-dir "$DATA_DIR" \
        --timeout 180

    rm -f "$MERGED_DEFAULTS"
    echo "[done] Mode $MODE ($NAME) complete."
    echo ""

    # Brief pause between modes to let the serial port settle
    sleep 2
done

# --- Run full analysis ---
echo "=================================================="
echo " All modes collected.  Running statistical analysis …"
echo "=================================================="
python3 "$ANALYSIS_DIR/analyze.py" \
    --data-dir    "$DATA_DIR" \
    --output-dir  "$RESULTS_DIR"

echo ""
echo "Done.  Results are in $RESULTS_DIR/"
