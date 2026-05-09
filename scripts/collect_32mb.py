#!/usr/bin/env python3
"""
collect_32mb.py — Collect 4 MB (1,048,576 samples) per entropy mode.

Differences from the normal collect.py flow:
  - Sets CONFIG_RNG_NUM_SAMPLES=1048576  (4× larger than the default 1MB run)
  - Saves to data_32mb/ so original 1MB data is untouched
  - ~15 min per mode at 115200 baud (~2 hrs total for all 8 modes)

Usage:
    cd esp32rng
    python scripts/collect_32mb.py
    python scripts/collect_32mb.py --port /dev/cu.usbserial-2110
    python scripts/collect_32mb.py --modes 0 1 2   # specific modes only
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

PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR     = os.path.join(PROJECT_DIR, "data_32mb")
ANALYSIS_DIR = os.path.join(PROJECT_DIR, "analysis")

MODES = {
    0: "BARE",
    1: "WIFI",
    2: "BT",
    3: "WIFI_BT",
    4: "ADC",
    5: "ADC_WIFI",
    6: "ADC_BT",
    7: "ADC_WIFI_BT",
}

N_SAMPLES = 33_554_432  # 128 MB at 4 bytes/sample (~8 hrs at 115200 baud hex)
BAUD      = 115200
TIMEOUT_S = 32400       # 9 hr ceiling

HEX32 = re.compile(r"^[0-9A-Fa-f]{8}$")


# ---------------------------------------------------------------------------
# sdkconfig patching
# ---------------------------------------------------------------------------

def _patch_sdkconfig(mode_id: int) -> None:
    """Write sdkconfig.defaults for this mode with 32MB sample count + fast baud."""
    base_path     = os.path.join(PROJECT_DIR, "sdkconfig.defaults")
    override_path = os.path.join(PROJECT_DIR, f"sdkconfig.defaults.mode{mode_id}")

    with open(base_path) as f:
        lines = f.read().splitlines()
    with open(override_path) as f:
        override_lines = f.read().splitlines()

    # collect per-mode overrides
    overrides: dict[str, str] = {}
    for line in override_lines:
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            overrides[s.split("=", 1)[0]] = s

    # 32MB-specific overrides (applied on top of everything)
    large_overrides = {
        "CONFIG_RNG_NUM_SAMPLES": f"CONFIG_RNG_NUM_SAMPLES={N_SAMPLES}",
    }
    overrides.update(large_overrides)

    merged: list[str] = []
    for line in lines:
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
        with open(os.path.join(PROJECT_DIR, target), "w") as f:
            f.write(content)

    # remove stale sdkconfig and cmake cache so they regenerate cleanly
    stale = os.path.join(PROJECT_DIR, "sdkconfig")
    if os.path.exists(stale):
        os.remove(stale)
    for p in (os.path.join(PROJECT_DIR, "build", "CMakeCache.txt"),):
        if os.path.exists(p):
            os.remove(p)
    cmake_files = os.path.join(PROJECT_DIR, "build", "CMakeFiles")
    if os.path.exists(cmake_files):
        shutil.rmtree(cmake_files)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _find_port() -> str | None:
    for pat in ["/dev/cu.usbserial*", "/dev/cu.SLAB*",
                "/dev/cu.wchusbserial*", "/dev/ttyUSB*", "/dev/ttyACM*"]:
        hits = glob.glob(pat)
        if hits:
            return sorted(hits)[0]
    return None


def _collect(port: str, mode_id: int) -> str | None:
    os.makedirs(DATA_DIR, exist_ok=True)
    name = MODES[mode_id]
    out_path = os.path.join(DATA_DIR, f"mode_{mode_id:02d}_{name}.bin")

    print(f"[collect] Opening {port} @ {BAUD} baud …")
    ser = serial.Serial(port, BAUD, timeout=2)

    samples: list[int] = []
    in_data  = False
    deadline = time.monotonic() + TIMEOUT_S
    t_start  = None

    print(f"[collect] Waiting for firmware — reset (EN button) if needed.")
    print(f"[collect] Target: {N_SAMPLES:,} samples = 4 MB  (ETA ~15 min)")

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        if line.startswith("MODE_ID: "):
            fid = int(line.split(": ", 1)[1])
            if fid != mode_id:
                print(f"[collect] WARNING: firmware is mode {fid}, expected {mode_id}",
                      file=sys.stderr)

        elif line == "BEGIN_DATA":
            in_data = True
            t_start = time.monotonic()
            print(f"[collect] ▶  collecting mode {mode_id} ({name}) …")

        elif line == "END_DATA":
            in_data = False

        elif line == "=== COLLECTION COMPLETE ===":
            break

        elif in_data and HEX32.match(line):
            samples.append(int(line, 16))
            n = len(samples)
            if n % 50_000 == 0:
                elapsed = time.monotonic() - t_start
                rate    = n / elapsed if elapsed > 0 else 0
                eta     = (N_SAMPLES - n) / rate if rate > 0 else 0
                pct     = 100 * n / N_SAMPLES
                print(f"[collect]  {n:>9,} / {N_SAMPLES:,}  ({pct:.1f}%)  "
                      f"{rate:.0f} samp/s  ETA {eta/60:.1f} min", end="\r", flush=True)

    ser.close()
    print()  # newline after \r progress

    if not samples:
        print("[collect] ERROR: no samples received.", file=sys.stderr)
        return None

    elapsed = time.monotonic() - (t_start or time.monotonic())
    print(f"[collect] ✓  {len(samples):,} samples in {elapsed/60:.1f} min")

    with open(out_path, "wb") as f:
        for v in samples:
            f.write(struct.pack("<I", v))

    size_mb = os.path.getsize(out_path) / 1_048_576
    print(f"[collect] Saved → {out_path}  ({size_mb:.1f} MB)")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port",  default=None)
    ap.add_argument("--modes", type=int, nargs="+", default=list(range(8)),
                    help="Which modes to collect (default: 0-7)")
    args = ap.parse_args()

    port = args.port or _find_port()
    if port is None:
        print("ERROR: no serial port found. Use --port /dev/...", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 60)
    print("  ESP32 RNG — 32 MB collection")
    print(f"  Port   : {port}")
    print(f"  Baud   : {BAUD}")
    print(f"  Samples: {N_SAMPLES:,} per mode  (4 MB)")
    print(f"  Output : {DATA_DIR}/")
    print(f"  Modes  : {args.modes}")
    print(f"  ETA    : ~{len(args.modes) * 15} min total")
    print("=" * 60)
    print()
    print("For each mode you will:")
    print("  1. Build + Flash in VS Code  (Ctrl+E B  then  Ctrl+E F)")
    print("  2. Press Enter here — collection starts immediately")
    print()

    failed = []
    for mode_id in args.modes:
        name = MODES[mode_id]
        print(f"{'─'*60}")
        print(f"  Mode {mode_id} : {name}")
        print(f"{'─'*60}")

        _patch_sdkconfig(mode_id)
        print(f"✓  sdkconfig.defaults → mode {mode_id}, {N_SAMPLES:,} samples, {BAUD} baud")
        print()
        print("  → VS Code: Build  (Ctrl+E B)  then Flash  (Ctrl+E F)")
        input("  → Press Enter once the board is flashed and running … ")

        out = _collect(port, mode_id)
        if out is None:
            print(f"[!] Collection failed for mode {mode_id} — skipping.")
            failed.append(mode_id)
        print()

    if failed:
        print(f"WARNING: modes {failed} failed and have no 32MB data.", file=sys.stderr)

    collected = glob.glob(os.path.join(DATA_DIR, "mode_*.bin"))
    print(f"\n{'='*60}")
    print(f"  Collected {len(collected)} mode file(s) in {DATA_DIR}/")
    for f in sorted(collected):
        mb = os.path.getsize(f) / 1_048_576
        print(f"    {os.path.basename(f):35s}  {mb:.1f} MB")
    print()
    print("  To run PractRand on the 4MB data:")
    print(f"    bash analysis/run_practrand.sh --data-dir data_32mb")
    print()
    print("  To run full NIST analysis:")
    print(f"    conda run -n esp python3 analysis/analyze.py --data-dir data_32mb --output-dir results_32mb")


if __name__ == "__main__":
    main()
