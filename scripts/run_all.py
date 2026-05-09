#!/usr/bin/env python3
"""
run_all.py — Semi-automated ESP32 RNG data collection.

For each of the 8 entropy modes this script:
  1. Writes the correct sdkconfig.defaults for that mode
  2. Waits for you to Build + Flash in VS Code (press Enter when done)
  3. Runs collect.py to capture UART samples
  4. After all 8 modes, runs analyze.py

Usage:
    python scripts/run_all.py
    python scripts/run_all.py --port /dev/cu.usbserial-2110
    python scripts/run_all.py --modes 0 1 2   # run only specific modes
"""

import argparse
import glob
import os
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.join(PROJECT_DIR, "analysis")
DATA_DIR     = os.path.join(PROJECT_DIR, "data")
RESULTS_DIR  = os.path.join(PROJECT_DIR, "results")

MODE_NAMES = ["BARE", "WIFI", "BT", "WIFI_BT", "ADC", "ADC_WIFI", "ADC_BT", "ADC_WIFI_BT"]


def find_port():
    patterns = [
        "/dev/cu.usbserial*", "/dev/cu.SLAB*",
        "/dev/cu.wchusbserial*", "/dev/ttyUSB*", "/dev/ttyACM*",
    ]
    for pat in patterns:
        hits = glob.glob(pat)
        if hits:
            return sorted(hits)[0]
    return None


def write_sdkconfig(mode: int) -> None:
    base = os.path.join(PROJECT_DIR, "sdkconfig.defaults")
    mode_override = os.path.join(PROJECT_DIR, f"sdkconfig.defaults.mode{mode}")

    with open(base) as f:
        base_content = f.read()
    with open(mode_override) as f:
        override_content = f.read()

    merged_path = os.path.join(PROJECT_DIR, "sdkconfig.defaults")

    # Build a merged content: start from base, apply mode override lines
    lines = base_content.splitlines()
    override_lines = override_content.splitlines()

    # Collect keys from override
    overrides = {}
    for line in override_lines:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key = line.split("=", 1)[0]
            overrides[key] = line

    # Replace matching keys in base, append any new ones
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0]
            if key in overrides:
                new_lines.append(overrides.pop(key))
                continue
        new_lines.append(line)
    # Append any keys that weren't in base
    for line in overrides.values():
        new_lines.append(line)

    # Write a temporary merged file that idf.py / VS Code will pick up
    merged = os.path.join(PROJECT_DIR, "sdkconfig.defaults.current")
    with open(merged, "w") as f:
        f.write("\n".join(new_lines) + "\n")

    # Also overwrite sdkconfig.defaults so VS Code sees the right mode
    with open(merged_path, "w") as f:
        f.write("\n".join(new_lines) + "\n")

    # Remove stale sdkconfig so it's regenerated from scratch
    stale = os.path.join(PROJECT_DIR, "sdkconfig")
    if os.path.exists(stale):
        os.remove(stale)

    # Remove CMake cache so component dependencies are re-evaluated
    # (needed when switching between WiFi/BT modes)
    import shutil
    cmake_cache = os.path.join(PROJECT_DIR, "build", "CMakeCache.txt")
    if os.path.exists(cmake_cache):
        os.remove(cmake_cache)
    cmake_files = os.path.join(PROJECT_DIR, "build", "CMakeFiles")
    if os.path.exists(cmake_files):
        shutil.rmtree(cmake_files)


def restore_sdkconfig_defaults() -> None:
    """Restore sdkconfig.defaults to mode 0 (BARE) after the sweep."""
    write_sdkconfig(0)


def collect(port: str, mode: int) -> bool:
    name = MODE_NAMES[mode]
    print(f"\n[collect] Starting collection for mode {mode} ({name}) …")
    result = subprocess.run(
        [sys.executable,
         os.path.join(ANALYSIS_DIR, "collect.py"),
         "--port", port,
         "--output-dir", DATA_DIR,
         "--timeout", "600"],
        cwd=PROJECT_DIR,
    )
    return result.returncode == 0


def analyze() -> None:
    print("\n" + "="*50)
    print(" All modes collected — running analysis …")
    print("="*50)
    subprocess.run(
        [sys.executable,
         os.path.join(ANALYSIS_DIR, "analyze.py"),
         "--data-dir", DATA_DIR,
         "--output-dir", RESULTS_DIR],
        cwd=PROJECT_DIR,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect ESP32 RNG data for all modes.")
    parser.add_argument("--port",  default=None, help="Serial port (auto-detected if omitted)")
    parser.add_argument("--modes", type=int, nargs="+", default=list(range(8)),
                        help="Which modes to run (default: 0-7)")
    args = parser.parse_args()

    port = args.port or find_port()
    if port is None:
        print("ERROR: no serial port found. Use --port /dev/...", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("="*55)
    print(" ESP32 RNG — semi-automated collection")
    print(f" Port  : {port}")
    print(f" Modes : {args.modes}")
    print("="*55)
    print()
    print("For each mode you will need to:")
    print("  1. VS Code → ESP-IDF: set SDKCONFIG_DEFAULTS if needed, then Build + Flash")
    print("  2. Press Enter here when the board is flashed and running")
    print()

    failed = []
    for mode in args.modes:
        name = MODE_NAMES[mode]
        print(f"{'─'*55}")
        print(f" Mode {mode} : {name}")
        print(f"{'─'*55}")

        write_sdkconfig(mode)
        print(f"✓ sdkconfig.defaults updated for mode {mode} ({name})")
        print(f"  CONFIG_RNG_ENTROPY_MODE={mode}")
        print()
        print("  → In VS Code: Build  (Ctrl+E B)  then Flash  (Ctrl+E F)")
        input("  → Press Enter once the board is flashed and running … ")

        ok = collect(port, mode)
        if not ok:
            print(f"[!] Collection failed for mode {mode} — skipping.")
            failed.append(mode)

        print()

    restore_sdkconfig_defaults()

    if failed:
        print(f"WARNING: modes {failed} failed collection and have no data.")

    bin_files = glob.glob(os.path.join(DATA_DIR, "mode_*.bin"))
    if bin_files:
        analyze()
    else:
        print("No data files found — skipping analysis.")

    print("\nDone.")


if __name__ == "__main__":
    main()
