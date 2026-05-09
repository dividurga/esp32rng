#!/usr/bin/env bash
# run_practrand.sh — Run PractRand on each mode's .bin file (no data looping).
#
# Usage:
#   cd esp32rng
#   bash analysis/run_practrand.sh
#
# Output: results/practrand/<mode>.txt  + results/practrand/summary.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RNG_TEST="$PROJECT_DIR/PractRand/RNG_test"

# allow --data-dir override
DATA_DIR="$PROJECT_DIR/data"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# derive output dir from data dir name
DATA_NAME="$(basename "$DATA_DIR")"
OUT_DIR="$PROJECT_DIR/results/practrand_${DATA_NAME}"

mkdir -p "$OUT_DIR"

if [[ ! -x "$RNG_TEST" ]]; then
    echo "ERROR: RNG_test not found at $RNG_TEST" >&2
    exit 1
fi

SUMMARY="$OUT_DIR/summary.txt"
> "$SUMMARY"

for bin_file in "$DATA_DIR"/mode_*.bin; do
    mode=$(basename "$bin_file" .bin)
    out_file="$OUT_DIR/${mode}.txt"

    echo "=== $mode ===" | tee -a "$SUMMARY"
    printf "  Input: %s  (%s)\n" "$bin_file" "$(du -h "$bin_file" | cut -f1)"

    # set tlmax to 90% of the file size so PractRand tests all available data
    file_bytes=$(wc -c < "$bin_file")
    file_mb=$(( file_bytes / 1048576 ))
    tlmax="${file_mb}MB"
    [[ "$file_mb" -lt 1 ]] && tlmax="512KB"

    cat "$bin_file" | "$RNG_TEST" stdin32 -tlmin 256KB -tlmax "$tlmax" 2>&1 | tee "$out_file"

    # extract final verdict line into summary
    grep -E "FAIL|no anomalies|bytes|length=" "$out_file" | tail -5 >> "$SUMMARY"
    echo "" >> "$SUMMARY"

    echo "  → Saved $out_file"
    echo ""
done

echo "========================================"
echo "Summary written to $SUMMARY"
echo ""
cat "$SUMMARY"
