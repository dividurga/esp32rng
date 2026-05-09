# ESP32 Hardware RNG Entropy Source Characterization
### ECE 580: Hardware Security — Final Project
**Divija Durga, Princeton University**

---

## Overview

This project empirically characterizes the ESP32 hardware TRNG under eight entropy source configurations. The ESP32's `WDEV_RND_REG` register is continuously updated by noise from three sources: the RF subsystem (Wi-Fi / Bluetooth), the SAR ADC, and the internal RC oscillator. This work measures how each source — and their combinations — affects RNG output quality using entropy estimation, all 15 NIST SP 800-22 statistical tests, Berlekamp-Massey linear complexity, and PractRand.

---

## Repository Structure

```
esp32rng/
├── main/
│   ├── rng_analysis_main.c      # ESP32 firmware (all 8 modes)
│   ├── CMakeLists.txt
│   └── Kconfig.projbuild        # CONFIG_RNG_ENTROPY_MODE, CONFIG_RNG_NUM_SAMPLES
├── analysis/
│   ├── collect.py               # UART sample collector → .bin files
│   ├── collect_bare_128mb.py    # Long-run collector for BARE mode (128 MB)
│   ├── analyze.py               # Entropy + NIST + linear complexity + plots
│   ├── nist_tests.py            # Ground-up NIST SP 800-22 implementation (replaces nistrng)
│   ├── cache_viewer.py          # Regenerate plots from cached JSON without rerunning tests
│   ├── run_practrand.sh         # PractRand sweep over all .bin files
│   └── requirements.txt
├── scripts/
│   ├── run_all.py               # Semi-automated 8-mode sweep
│   └── collect_32mb.py          # Collect ~4 MB per mode (~15 min/mode at 115200 baud)
├── PractRand/                   # PractRand v0.96 (patched for Apple Silicon / ARM64)
├── data/                        # 1 MB .bin files (one per mode) — not committed
├── data_32mb/                   # 4 MB .bin files (one per mode) — not committed
├── data_bare_128mb/             # Long BARE run — not committed
├── results_4mb/                 # Analysis outputs for 4 MB dataset
├── report/
│   └── report.tex               # LaTeX report
├── partitions.csv               # Custom partition table (1.94 MB factory slot)
├── sdkconfig.defaults           # Base ESP-IDF config
└── sdkconfig.defaults.mode0-7   # Per-mode config overrides
```

---

## Entropy Source Modes

| ID | Name | Wi-Fi | BT | ADC |
|----|------|-------|----|-----|
| 0 | BARE | — | — | — |
| 1 | WIFI | ✓ | — | — |
| 2 | BT | — | ✓ | — |
| 3 | WIFI\_BT | ✓ | ✓ | — |
| 4 | ADC | — | — | ✓ |
| 5 | ADC\_WIFI | ✓ | — | ✓ |
| 6 | ADC\_BT | — | ✓ | ✓ |
| 7 | ADC\_WIFI\_BT | ✓ | ✓ | ✓ |

Primary dataset: **~1,048,000 × 32-bit samples per mode (~4 MB, ~33.5 Mbit)**.

---

## Hardware

- **Board:** ESP32-WROOM-32 (4 MB flash)
- **Framework:** ESP-IDF v5.2
- **ADC pin:** GPIO 36 (SENSOR\_VP) left floating
- **Connection:** USB-UART at 115200 baud
- **Host:** MacBook Pro, macOS Sonoma 14.6.1

---

## Firmware Design

`main/rng_analysis_main.c` implements all 8 modes in a single binary.
`CONFIG_RNG_ENTROPY_MODE` (set at build time) selects which sources are initialized:

- **WiFi:** STA mode, RF active, no network association
- **BT:** BLE-only via Bluedroid; Classic-BT memory released when unused
- **ADC:** `bootloader_random_enable()` activates the internal SAR ADC entropy path
- **Sampling:** 100 µs delay before each `esp_random()` call to allow pool refresh

---

## Data Collection

```bash
conda activate esp

# Normal 4 MB collection (all 8 modes, ~15 min/mode)
python scripts/collect_32mb.py

# Single-mode long run (BARE only, ~8 hrs for 128 MB)
python analysis/collect_bare_128mb.py
```

For each mode: update sdkconfig → Build (`Ctrl+E B`) → Flash (`Ctrl+E F`) → press Enter → collects automatically.

---

## Analysis

```bash
# Full analysis (entropy + NIST + linear complexity + plots)
conda run -n esp python analysis/analyze.py --data-dir data_32mb --output-dir results_4mb

# Regenerate plots from cached results (no rerunning tests)
conda run -n esp python analysis/cache_viewer.py --cache results_4mb/summary/analysis_cache.json

# PractRand
bash analysis/run_practrand.sh --data-dir data_32mb
```

---

## NIST SP 800-22 Implementation

The `nistrng` third-party library was found to contain implementation bugs during this project (incorrect chi-squared parameters in Linear Complexity, wrong normalisation in Overlapping Template Matching, integer overflow in Cumulative Sums, and z-score returned instead of erfc in Random Excursions Variant). All 15 tests were reimplemented from scratch in `analysis/nist_tests.py` against the NIST SP 800-22 Rev 1a specification.

---

## PractRand

PractRand v0.96 was ported to Apple Silicon (ARM64 / macOS). Three files were patched:

- `src/platform_specifics.cpp` — x86 intrinsic guard
- `src/tests_other.cpp` — shift overflow fix for `BITS_PER_BLOCK=64`
- `tools/dummy_rng.h` — x86 intrinsic guard

Build:
```bash
cd PractRand
g++ -c src/*.cpp src/RNGs/*.cpp src/RNGs/other/*.cpp -O3 -Iinclude -pthread
ar rcs libPractRand.a *.o
g++ -o RNG_test tools/RNG_test.cpp libPractRand.a -O3 -Iinclude -pthread
```

**Credit:** PractRand is written by Chris Doty-Humphrey and is released into the public domain.
Source: https://pracrand.sourceforge.net

---

## Python Setup

```bash
pip install numpy scipy matplotlib pyserial
```

(`nistrng` is no longer used.)

---

## Key Design Decisions

**Why always link WiFi + BT?** `CONFIG_ESP_WIFI_ENABLED` is set by ESP-IDF when the component is included — it cannot be set in `sdkconfig.defaults` to cause inclusion. Unconditional linking with runtime mode guards is the correct approach.

**Why a custom partition table?** WiFi + BT together compile to ~1.25 MB, exceeding the default 1 MB factory slot. `partitions.csv` expands the factory partition to 1.94 MB.

**Why binary `.bin` files?** 4 bytes/sample vs. 9 bytes as hex — 2.25× smaller. NumPy loads them in one call; PractRand `stdin32` reads them directly.
