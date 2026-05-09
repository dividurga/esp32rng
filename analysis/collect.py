#!/usr/bin/env python3
"""
collect.py — Prepare sdkconfig, wait for manual VS Code build+flash, then collect.

Usage:
    python collect.py --mode 3          # prepare config, prompt to build+flash, collect
    python collect.py --mode all        # repeat for all 8 modes
    python collect.py --mode 3 --no-flash   # skip prepare+prompt, just collect
    python collect.py --mode 1 --port /dev/cu.usbserial-0001
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import struct
import sys
import time

import serial

# ---------------------------------------------------------------------------
# Mode registry — mirrors sdkconfig.defaults.modeN comments
# ---------------------------------------------------------------------------

MODES: dict[int, str] = {
    0: "BARE",
    1: "WIFI",
    2: "BT",
    3: "WIFI_BT",
    4: "ADC",
    5: "ADC_WIFI",
    6: "ADC_BT",
    7: "ADC_WIFI_BT",
}

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_esp_port() -> str | None:
    patterns = [
        "/dev/cu.usbserial*",
        "/dev/cu.SLAB_USBtoUART*",
        "/dev/cu.wchusbserial*",
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
    ]
    for pat in patterns:
        hits = glob.glob(pat)
        if hits:
            return sorted(hits)[0]
    return None


HEX32 = re.compile(r"^[0-9A-Fa-f]{8}$")


# ---------------------------------------------------------------------------
# Config preparation
# ---------------------------------------------------------------------------

def prepare_mode(mode_id: int) -> None:
    """Merge sdkconfig.defaults + modeN overrides, delete stale sdkconfig + cmake cache."""
    base_path     = os.path.join(PROJECT_ROOT, "sdkconfig.defaults")
    override_path = os.path.join(PROJECT_ROOT, f"sdkconfig.defaults.mode{mode_id}")

    with open(base_path) as f:
        base_lines = f.read().splitlines()
    with open(override_path) as f:
        override_lines = f.read().splitlines()

    overrides: dict[str, str] = {}
    for line in override_lines:
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            overrides[s.split("=", 1)[0]] = s

    merged: list[str] = []
    for line in base_lines:
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            key = s.split("=", 1)[0]
            if key in overrides:
                merged.append(overrides.pop(key))
                continue
        merged.append(line)
    merged.extend(overrides.values())

    content = "\n".join(merged) + "\n"
    for target in ("sdkconfig.defaults", "sdkconfig.defaults.current"):
        with open(os.path.join(PROJECT_ROOT, target), "w") as f:
            f.write(content)

    stale = os.path.join(PROJECT_ROOT, "sdkconfig")
    if os.path.exists(stale):
        os.remove(stale)

    cmake_cache = os.path.join(PROJECT_ROOT, "build", "CMakeCache.txt")
    if os.path.exists(cmake_cache):
        os.remove(cmake_cache)
    cmake_files = os.path.join(PROJECT_ROOT, "build", "CMakeFiles")
    if os.path.exists(cmake_files):
        shutil.rmtree(cmake_files)


# ---------------------------------------------------------------------------
# Core collection
# ---------------------------------------------------------------------------

def collect_one_run(port: str, expected_mode_id: int, baud: int = 115200,
                    timeout_s: int = 180, output_dir: str = "data") -> str | None:
    os.makedirs(output_dir, exist_ok=True)

    print(f"[collect] Opening {port} @ {baud} baud …")
    ser = serial.Serial(port, baud, timeout=1)

    mode_name: str | None = None
    mode_id:   int | None = None
    samples: list[int] = []
    in_data = False
    deadline = time.monotonic() + timeout_s

    print("[collect] Waiting for firmware output — reset (EN) the board if needed.")

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        if line.startswith("MODE: "):
            mode_name = line.split(": ", 1)[1]
        elif line.startswith("MODE_ID: "):
            mode_id = int(line.split(": ", 1)[1])
            if mode_id != expected_mode_id:
                print(f"[collect] WARNING: firmware reports mode {mode_id}, expected {expected_mode_id}",
                      file=sys.stderr)
        elif line == "BEGIN_DATA":
            in_data = True
            print(f"[collect] ▶  mode {mode_id} ({mode_name}) — collecting …")
        elif line == "END_DATA":
            in_data = False
        elif line == "=== COLLECTION COMPLETE ===":
            break
        elif in_data and HEX32.match(line):
            samples.append(int(line, 16))
            if len(samples) % 2000 == 0:
                print(f"[collect]    {len(samples)} samples …", end="\r", flush=True)

    ser.close()

    if not samples:
        print("[collect] ERROR: no samples received.", file=sys.stderr)
        return None

    print(f"\n[collect] ✓  {len(samples)} samples for mode {mode_id} ({mode_name})")

    out_path = os.path.join(output_dir, f"mode_{mode_id:02d}_{mode_name}.bin")
    with open(out_path, "wb") as f:
        for v in samples:
            f.write(struct.pack("<I", v))

    print(f"[collect] Saved → {out_path}  ({os.path.getsize(out_path):,} bytes)")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_modes(value: str) -> list[int]:
    if value.lower() == "all":
        return list(MODES.keys())
    try:
        m = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"mode must be 0-7 or 'all', got {value!r}")
    if m not in MODES:
        raise argparse.ArgumentTypeError(f"mode must be 0-7 or 'all', got {m}")
    return [m]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build, flash, and collect ESP32 RNG samples per entropy mode."
    )
    parser.add_argument("--mode", required=True, type=parse_modes,
                        metavar="N|all",
                        help="Entropy mode 0-7, or 'all' to run all modes sequentially")
    parser.add_argument("--port",       default=None,
                        help="Serial port (auto-detected if omitted)")
    parser.add_argument("--baud",       type=int, default=115200)
    parser.add_argument("--output-dir", default=os.path.join(PROJECT_ROOT, "data"),
                        help="Directory for .bin output files (default: <project>/data/)")
    parser.add_argument("--timeout",    type=int, default=360,
                        help="Max seconds to wait for a complete run (default: 360)")
    parser.add_argument("--no-flash", action="store_true",
                        help="Skip config prep + build prompt; collect from already-running firmware")
    args = parser.parse_args()

    port = args.port or find_esp_port()
    if port is None:
        print("ERROR: no serial port found. Use --port /dev/... to specify one.",
              file=sys.stderr)
        sys.exit(1)

    print(f"[collect] Using port: {port}")

    failed: list[int] = []
    for mode_id in args.mode:
        print(f"\n{'='*60}")
        print(f"  Mode {mode_id}: {MODES[mode_id]}")
        print(f"{'='*60}")

        if not args.no_flash:
            prepare_mode(mode_id)
            print(f"✓ sdkconfig.defaults written for mode {mode_id} ({MODES[mode_id]})")
            print(f"  CONFIG_RNG_ENTROPY_MODE={mode_id}")
            print()
            print("  → In VS Code: Build  (Ctrl+E B)  then Flash  (Ctrl+E F)")
            input("  → Press Enter once the board is flashed and running … ")

        result = collect_one_run(port, mode_id, args.baud, args.timeout, args.output_dir)
        if result is None:
            print(f"[!] Collection failed for mode {mode_id} — skipping.")
            failed.append(mode_id)

    if failed:
        print(f"\n[!] Failed modes: {failed}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
