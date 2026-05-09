#!/usr/bin/env bash
# run_practrand.sh
#
# Run PractRand's RNG_test on every collected data file in data/.
# Results are saved to results/practrand_<MODE>.txt and a summary
# table is printed at the end.
#
# Prerequisites:
#   Build PractRand once from source:
#       curl -LO https://pracrand.sourceforge.net/PractRand.0.95.zip
#       unzip PractRand.0.95.zip && cd PractRand
#       g++ -std=c++14 -O3 -o RNG_test tools/RNG_test.cpp src/*.cpp -Iinclude
#       # copy or symlink the binary somewhere on your PATH, e.g.:
#       cp RNG_test /usr/local/bin/RNG_test
#
# Usage:
#   ./scripts/run_practrand.sh
#   ./scripts/run_practrand.sh --data-dir data --results-dir results

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"
RESULTS_DIR="$PROJECT_DIR/results"

# Parse optional overrides
while [[ $# -gt 0 ]]; do
    case $1 in
        --data-dir)    DATA_DIR="$2";    shift 2 ;;
        --results-dir) RESULTS_DIR="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Locate RNG_test binary
RNG_TEST=""
for candidate in RNG_test "$PROJECT_DIR/PractRand/RNG_test" /usr/local/bin/RNG_test; do
    if command -v "$candidate" &>/dev/null || [[ -x "$candidate" ]]; then
        RNG_TEST="$candidate"
        break
    fi
done

if [[ -z "$RNG_TEST" ]]; then
    echo "ERROR: RNG_test not found." >&2
    echo "" >&2
    echo "Build PractRand first:" >&2
    echo "  curl -LO https://pracrand.sourceforge.net/PractRand.0.95.zip" >&2
    echo "  unzip PractRand.0.95.zip && cd PractRand" >&2
    echo "  g++ -std=c++14 -O3 -o RNG_test tools/RNG_test.cpp src/*.cpp -Iinclude" >&2
    echo "  cp RNG_test /usr/local/bin/RNG_test   # or add to PATH" >&2
    exit 1
fi

mkdir -p "$RESULTS_DIR"

BIN_FILES=("$DATA_DIR"/mode_*.bin)
if [[ ${#BIN_FILES[@]} -eq 0 ]] || [[ ! -f "${BIN_FILES[0]}" ]]; then
    echo "ERROR: no mode_*.bin files found in $DATA_DIR" >&2
    echo "Run build_all.sh first to collect data." >&2
    exit 1
fi

echo "=================================================="
echo " PractRand RNG_test — ESP32 entropy mode sweep"
echo " Binary  : $RNG_TEST"
echo " Data    : $DATA_DIR"
echo " Results : $RESULTS_DIR"
echo "=================================================="
echo ""

SUMMARY_FILE="$RESULTS_DIR/practrand_summary.txt"
echo "PractRand summary — $(date)" > "$SUMMARY_FILE"
echo "========================================" >> "$SUMMARY_FILE"
printf "%-18s  %10s  %s\n" "Mode" "Data" "Verdict" >> "$SUMMARY_FILE"
echo "----------------------------------------" >> "$SUMMARY_FILE"

for BIN in "${BIN_FILES[@]}"; do
    STEM="$(basename "$BIN" .bin)"        # mode_00_BARE
    PARTS=(${STEM//_/ })
    # Name is everything after "mode_NN_"
    MODE_NAME="${STEM#mode_??_}"
    OUT="$RESULTS_DIR/practrand_${MODE_NAME}.txt"

    BYTES="$(wc -c < "$BIN" | tr -d ' ')"
    # Format bytes as KiB / MiB for display
    if   (( BYTES >= 1048576 )); then
        SIZE_STR="$(( BYTES / 1048576 )) MiB"
    elif (( BYTES >= 1024 )); then
        SIZE_STR="$(( BYTES / 1024 )) KiB"
    else
        SIZE_STR="${BYTES} B"
    fi

    echo "---------- $MODE_NAME ($SIZE_STR) ----------"
    echo "Output → $OUT"

    # stdin32 tells PractRand the data is a stream of 32-bit little-endian words,
    # which matches the uint32-LE format written by collect.py.
    "$RNG_TEST" stdin32 < "$BIN" 2>&1 | tee "$OUT"

    # Extract the final verdict line for the summary
    VERDICT=$(grep -E "^(PASS|FAIL|no anomalies)" "$OUT" | tail -1 || echo "(see file)")
    printf "%-18s  %10s  %s\n" "$MODE_NAME" "$SIZE_STR" "$VERDICT" >> "$SUMMARY_FILE"
    echo ""
done

echo "=================================================="
echo " Summary"
echo "=================================================="
cat "$SUMMARY_FILE"
echo ""
echo "Full per-mode reports saved to $RESULTS_DIR/practrand_<MODE>.txt"
