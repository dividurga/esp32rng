#!/usr/bin/env python3
"""
collect_bare_128mb.py — Collect 128 MB (33,554,432 samples) from BARE mode (mode 0).

Before running:
  1. Edit sdkconfig.defaults.mode0 and set:
       CONFIG_RNG_NUM_SAMPLES=33554432
  2. In VS Code: Build (Ctrl+E B) then Flash (Ctrl+E F)
  3. Run this script:
       conda run -n esp python analysis/collect_bare_128mb.py

Output: data_bare_128mb/mode_00_BARE.bin  (~128 MB)
Then run PractRand:
  cat data_bare_128mb/mode_00_BARE.bin | ./PractRand/RNG_test stdin32 -tlmin 1KB
"""

from __future__ import annotations

import glob
import os
import re
import struct
import sys
import time

import serial

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR   = os.path.join(PROJECT_ROOT, "data_bare_128mb")
OUTPUT_PATH  = os.path.join(OUTPUT_DIR, "mode_00_BARE.bin")
PORT_PATTERNS = [
    "/dev/cu.usbserial*",
    "/dev/cu.SLAB_USBtoUART*",
    "/dev/cu.wchusbserial*",
    "/dev/ttyUSB*",
    "/dev/ttyACM*",
]
BAUD         = 115200
TIMEOUT_S    = 36000   # 10 hours — 128 MB at 115200 baud takes ~8 hours
TARGET_MB    = 128
TARGET_BYTES = TARGET_MB * 1024 * 1024
HEX32        = re.compile(r"^[0-9A-Fa-f]{8}$")


def find_port() -> str | None:
    for pat in PORT_PATTERNS:
        hits = glob.glob(pat)
        if hits:
            return sorted(hits)[0]
    return None


def main() -> None:
    port = find_port()
    if port is None:
        print("ERROR: no serial port found. Connect the ESP32 and try again.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"ESP32 BARE mode — 128 MB collection")
    print(f"Port    : {port} @ {BAUD} baud")
    print(f"Output  : {OUTPUT_PATH}")
    print(f"Timeout : {TIMEOUT_S // 3600} hours")
    print()
    print("Make sure firmware was built with CONFIG_RNG_NUM_SAMPLES=33554432")
    print("and flashed before running this script.")
    print()
    input("Press Enter to start collecting (reset the board now if needed) … ")

    print(f"[collect] Opening {port} …")
    ser = serial.Serial(port, BAUD, timeout=1)

    samples_written = 0
    in_data = False
    deadline = time.monotonic() + TIMEOUT_S
    t_start  = time.monotonic()

    with open(OUTPUT_PATH, "wb") as out:
        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            if line == "BEGIN_DATA":
                in_data = True
                print("[collect] ▶  BEGIN_DATA received — collecting …")
            elif line == "END_DATA":
                in_data = False
            elif line == "=== COLLECTION COMPLETE ===":
                print("\n[collect] ✓  COLLECTION COMPLETE received.")
                break
            elif in_data and HEX32.match(line):
                out.write(struct.pack("<I", int(line, 16)))
                samples_written += 1
                if samples_written % 50000 == 0:
                    elapsed   = time.monotonic() - t_start
                    mb_done   = samples_written * 4 / (1024 * 1024)
                    mb_remain = TARGET_MB - mb_done
                    rate      = mb_done / elapsed if elapsed > 0 else 0
                    eta_s     = mb_remain / rate if rate > 0 else 0
                    eta_h     = eta_s / 3600
                    print(f"[collect]   {mb_done:.1f} / {TARGET_MB} MB"
                          f"  |  {rate*1024:.0f} KB/s"
                          f"  |  ETA {eta_h:.1f} h",
                          end="\r", flush=True)

    ser.close()

    actual_bytes = samples_written * 4
    actual_mb    = actual_bytes / (1024 * 1024)
    elapsed      = time.monotonic() - t_start

    print(f"\n[collect] Collected {samples_written:,} samples"
          f" = {actual_mb:.1f} MB in {elapsed/3600:.2f} h")
    print(f"[collect] Saved → {OUTPUT_PATH}  ({actual_bytes:,} bytes)")

    if actual_bytes < 1024 * 1024:
        print("\nWARNING: less than 1 MB collected — check firmware config.", file=sys.stderr)
        sys.exit(1)

    print()
    print("Run PractRand:")
    print(f"  cat {OUTPUT_PATH} | ./PractRand/RNG_test stdin32 -tlmin 1KB")


if __name__ == "__main__":
    main()
