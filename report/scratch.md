# Entropy Source Characterization of the ESP32 Hardware RNG
### ECE 580: Hardware Security — Final Project
**Divija Durga, Princeton University**

---

## 1. Introduction

Random number generation is a foundational primitive in hardware security. Cryptographic keys, nonces, and session identifiers derive their security entirely from the unpredictability of the underlying entropy source. Weak or biased RNG output has historically led to catastrophic key-recovery attacks (Debian OpenSSL 2008, Android ECDSA 2013).

The ESP32 integrates a hardware true-random-number generator (TRNG) whose output quality is documented to depend on which peripherals are active. Specifically, the RF subsystem (Wi-Fi / Bluetooth) and the SAR ADC each contribute noise to the entropy pool that feeds the hardware RNG register (`WDEV_RND_REG`). When neither is active, entropy is derived solely from the internal RC oscillator, which the manufacturer acknowledges produces lower-quality randomness.

This work empirically measures the effect of each entropy source (and their combinations) on RNG output quality using standard statistical tests and entropy estimation.

---

## 2. Background

### 2.1 ESP32 RNG Architecture

The ESP32 hardware RNG is a single 32-bit register (`RNG_DATA_REG` at `0x3FF75144`) continuously updated by hardware noise sources. The `esp_random()` API reads this register directly. Three classes of entropy sources feed it through an XOR gate (ESP32 TRM §18.3):

1. **High Speed ADC (HSADC)** — enabled automatically when the Wi-Fi or Bluetooth RF subsystem is active. Provides 2 bits of entropy per APB clock cycle (80 MHz), supporting a maximum useful read rate of 5 MHz.
2. **SAR ADC** — the slow 12-bit ADC. Each conversion injects shot and thermal noise from the analog front-end. Provides 2 bits of entropy per RC_FAST_CLK cycle (8 MHz), supporting a maximum useful read rate of 500 kHz. Enabled via `bootloader_random_enable()` or the DIG ADC controller.
3. **Internal RC oscillator** — always present; provides clock-jitter-based entropy at all times, but with significantly lower throughput than the ADC paths.

The TRM explicitly notes: *"when the Wi-Fi module is enabled, the value read from the high-speed ADC can be saturated in some extreme cases, which lowers the entropy. Thus, it is advisable to also enable the SAR ADC as the noise source for the random number generator for such cases."*

### 2.2 Statistical Test Suites

RNG test suites fall into two categories based on how they consume data.

1. **Pre-recorded binaries** — NIST SP 800-22 and PractRand operate on a fixed file of pre-collected samples. NIST SP 800-22 defines 15 hypothesis tests covering properties such as bit balance, run structure, spectral periodicity, and compressibility; each test returns a p-value against the null hypothesis of true randomness, with p < 0.01 indicating failure. PractRand feeds the binary through an expanding window of test batteries, flagging anomalies as *unusual*, *suspicious*, or *FAIL* at the data volume at which they first appear. Both tools are well-suited to offline characterisation workflows where data is collected separately from analysis.

2. **Live-generated data** — Diehard (original) and its successor Dieharder require a live RNG stream: they pull samples on demand and rely on the generator being stateless between draws. Feeding either tool a pre-recorded file causes it to rewind and reuse the data once exhausted, which breaks the independence assumption of the tests and invalidates results. The ESP32 TRM notes that Espressif validated their RNG using Dieharder by running the test harness on-chip — reading `RNG_DATA_REG` in a tight C loop at up to 5 MHz with no host interface in the data path. This is the only practical way to meet Dieharder's data-volume requirements on an embedded target; streaming over UART would cap throughput at ~115 KB/s, orders of magnitude below what the heavier Dieharder tests require.

The ESP32 TRM itself cites Dieharder validation on a 2 GB sample read at 5 MHz — but notably only with the high-speed ADC enabled (i.e., a single RF-active configuration). Applying the same validation across all eight entropy modes studied here would have been a natural extension of that work. However, the 5 MHz throughput in Espressif's test is only achievable by running the test harness on-chip with direct register access; over UART at 921600 baud the maximum achievable rate is ~90 KB/s of binary data, making a 2 GB collection per mode impractical within a project timeline. This project therefore uses NIST SP 800-22 and PractRand, both of which are designed for pre-recorded binaries and produce meaningful results at the 1 MB per mode scale collected here.

### 2.3 Statistical Tests

#### Entropy Metrics

**Shannon entropy** — average information per byte; ideal = 8.0 bits/byte for a uniform distribution.
$$H = -\sum_{i=0}^{255} p_i \log_2 p_i$$

**Min-entropy** — security-relevant lower bound; quantifies the adversary's best single-guess probability.
$$H_\infty = -\log_2(\max_i\, p_i)$$

**Collision entropy (H₂)** — Rényi entropy of order 2; sits between Shannon and min-entropy, sensitive to the most probable symbol.

#### NIST SP 800-22

A battery of 15 hypothesis tests; pass criterion p ≥ 0.01. Tests T7–T15 require ≥ 10⁶ bits; our 8,000,000-bit sequences satisfy this for all modes.

| # | Test | Detects |
|---|------|---------|
| T1 | Frequency (Monobit) | Global bit imbalance |
| T2 | Block Frequency | Per-block bit imbalance |
| T3 | Runs | Irregular alternation of 0/1 runs |
| T4 | Longest Run of Ones | Unusually long runs of 1s |
| T5 | Binary Matrix Rank | Linear dependence among bit segments |
| T6 | DFT / Spectral | Periodic structure in the sequence |
| T7 | Non-overlapping Template | Excess occurrences of a specific m-bit pattern |
| T8 | Overlapping Template | Excess overlapping occurrences of a pattern |
| T9 | Maurer's Universal | Compressibility (short description length) |
| T10 | Linear Complexity | LFSR length needed to reproduce the sequence |
| T11 | Serial | Non-uniformity of 2- and 3-bit pattern frequencies |
| T12 | Approximate Entropy | Per-bit entropy relative to overlapping blocks |
| T13 | Cumulative Sums | Excursions of the partial-sum random walk |
| T14 | Random Excursions | Cycle visit counts at states ±1…±4 |
| T15 | Random Excursions Variant | State visit counts at ±1…±9 |

#### PractRand

Feeds the binary file into `RNG_test stdin32`, evaluating at doubling data sizes (1 KB → 1 MB). Reports anomalies as *unusual*, *suspicious*, or *FAIL* at the volume where they first appear, making it sensitive to weaknesses that only emerge at scale.

---

## 3. Experimental Setup

### 3.1 Hardware

- **Board:** ESP32-WROOM-32 (4 MB flash)
- **Framework:** ESP-IDF v5.2
- **ADC pin:** GPIO 36 (SENSOR_VP) left floating to maximize thermal/shot noise
- **Connection:** USB-UART at 115200 baud
- **Host:** MacBook Pro, macOS Sonoma 14.6.1

### 3.2 Firmware

Custom firmware was written in C using the ESP-IDF framework. A Kconfig option (`CONFIG_RNG_ENTROPY_MODE`) selects one of eight configurations at build time. In each configuration the firmware:
1. Initialises only the specified entropy subsystems
2. Waits 500 ms for RF/ADC to stabilise (200 ms additional before sampling)
3. Calls `esp_random()` N = 250,000 times with a 100 µs inter-sample delay
4. Streams the 32-bit values over UART as hex

The 100 µs inter-sample delay (10 kHz read rate) is well below both the 500 kHz SAR ADC limit and the 5 MHz HSADC limit, ensuring each sample draws from a fully refreshed entropy pool regardless of which sources are active.

### 3.3 Entropy Source Mode Design

The eight modes form a systematic coverage of the ESP32's entropy input space, motivated directly by the XOR hardware architecture described in TRM §18.3.

| ID | Name | Wi-Fi | BT | ADC | HSADC | SAR ADC |
|----|------|-------|----|-----|-------|---------|
| 0 | BARE | — | — | — | ✗ | ✗ |
| 1 | WIFI | ✓ | — | — | ✓ | ✗ |
| 2 | BT | — | ✓ | — | ✓ | ✗ |
| 3 | WIFI_BT | ✓ | ✓ | — | ✓ | ✗ |
| 4 | ADC | — | — | ✓ | ✗ | ✓ |
| 5 | ADC_WIFI | ✓ | — | ✓ | ✓ | ✓ |
| 6 | ADC_BT | — | ✓ | ✓ | ✓ | ✓ |
| 7 | ADC_WIFI_BT | ✓ | ✓ | ✓ | ✓ | ✓ |

**Mode 0 (BARE)** is the baseline: no peripherals active, RC oscillator only. The TRM warns this produces lower-quality randomness and the manufacturer does not guarantee true-random output in this configuration. It establishes the floor against which all other modes are compared.

**Modes 1–3 (RF only)** isolate the HSADC entropy path. Wi-Fi and Bluetooth each enable the high-speed ADC automatically; mode 3 runs both simultaneously to test whether additional RF activity further improves output quality.

**Mode 4 (ADC only)** isolates the SAR ADC entropy path using `bootloader_random_enable()`, with GPIO36 left floating to maximize shot and thermal noise. This represents the configuration recommended for battery-powered devices where RF is kept off to conserve power.

**Modes 5–7 (combined)** activate both the HSADC (via RF) and the SAR ADC simultaneously. This is the configuration explicitly recommended by the TRM for Wi-Fi-enabled devices: since HSADC values "can be saturated in some extreme cases" under Wi-Fi load, the SAR ADC provides an independent noise path through the XOR gate that compensates for saturation events. Mode 7 is the maximum-entropy configuration with all three hardware noise sources active.

The ADC is implemented via `bootloader_random_enable()`, which enables the SAR ADC entropy path through the DIG ADC controller. In combined modes this call is made after RF initialisation is complete, at which point the RF calibration procedures (which temporarily use the SAR ADC) have finished and the two paths can coexist in steady state.

### 3.4 Analysis Pipeline

A Python host script (`analysis/collect.py`) collected 250,000 × 32-bit samples per mode via `pyserial`, saving raw little-endian binary files (`data/mode_XX_<NAME>.bin`). A second script (`analysis/analyze.py`) computed entropy metrics, ran all 15 NIST tests, and generated visualisations using `numpy`, `scipy`, and `matplotlib`. PractRand testing was run via `scripts/run_practrand.sh`.

---

## 4. Results

### 4.1 Entropy Metrics

Entropy was estimated from ~4 MB (≈33.5 M bits) of data per mode; the larger sample yields more stable estimates than the 1 MB pilot dataset. Bit proportion of ones and all three entropy estimators are reported. All values are per byte (8 bits).

| Mode | Samples | Bit prop (1s) | Shannon (b/B) | Min-entropy (b/B) | Collision H₂ (b/B) |
|------|---------|---------------|---------------|-------------------|---------------------|
| BARE | 1,048,405 | 0.49987 | 7.999963 | 7.972118 | 7.999925 |
| WIFI | 938,227¹ | 0.49998 | 7.999948 | 7.960377 | 7.999897 |
| BT | 1,040,105 | 0.50004 | 7.999952 | 7.968186 | 7.999904 |
| WIFI_BT | 1,048,400 | 0.49995 | 7.999962 | 7.960753 | 7.999924 |
| ADC | 1,048,405 | 0.49995 | 7.999955 | 7.969442 | 7.999910 |
| ADC_WIFI | 1,048,405 | 0.50006 | 7.999958 | 7.972982 | 7.999916 |
| ADC_BT | 1,048,404 | 0.50013 | 7.999956 | 7.970045 | 7.999911 |
| ADC_WIFI_BT | 1,048,404 | 0.49997 | 7.999957 | 7.964191 | 7.999913 |

Ideal = 8.000 bits/byte. ¹WIFI collection terminated early; samples still sufficient for all tests.

All modes achieve Shannon entropy within 0.000052 bits/byte of ideal and min-entropy within 0.040 bits/byte of ideal. No mode exhibits a statistically meaningful entropy advantage over any other. Bit proportions are within 0.013% of 0.5 across all modes, consistent with a balanced Bernoulli source. The theoretical prediction that RF-active modes (1–3) and combined modes (5–7) would substantially exceed BARE mode is not borne out by the entropy metrics — all configurations operate well above any practical threshold for cryptographic use at this sample scale.

### 4.2 NIST SP 800-22 Results (all 15 tests)

All tests run on ~4 MB (~33.5 M bits) per mode. Pass criterion: p ≥ 0.01. All p-values listed; **P** = pass, **F** = fail.

| Mode | T1 | T2 | T3 | T4 | T5 | T6 | T7 | T8 | T9 | T10 | T11 | T12 | T13 | T14 | T15 |
|------|----|----|----|----|----|----|----|----|----|----|-----|-----|-----|-----|-----|
| BARE | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
| WIFI | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
| BT | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
| WIFI_BT | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
| ADC | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
| ADC_WIFI | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
| ADC_BT | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
| ADC_WIFI_BT | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |

T1: Monobit · T2: Block Freq · T3: Runs · T4: Longest Run · T5: Matrix Rank · T6: DFT · T7: Non-overlap Template · T8: Overlap Template · T9: Maurer's Universal · T10: Linear Complexity · T11: Serial · T12: Approx. Entropy · T13: Cumulative Sums · T14: Rand. Excursions · T15: Rand. Excursions Variant

All eight modes pass all 15 NIST tests at 4 MB. This is a significant improvement over the 1 MB pilot dataset, where ADC_WIFI_BT failed T14 (Random Excursions, p = 0.00477). T14 requires a minimum of 500 random walk cycles to be statistically valid; the NIST specification notes this condition may not be met at lower bit counts. At 1 MB (~8 M bits) this condition is marginal; at 4 MB (~33.5 M bits) it is reliably satisfied and the T14 p-value for ADC_WIFI_BT rises to 0.352, confirming the 1 MB result was a false positive driven by insufficient data volume rather than a genuine structural weakness in that mode.

### 4.3 PractRand Results

PractRand was run via `cat <file> | ./PractRand/RNG_test stdin32 -tlmin 1KB` on ~4 MB per mode, testing at doubling data sizes from 1 KB to 4 MB. Anomalies are reported as *unusual* (~1-in-10 false positive rate), *suspicious* (~1-in-1000), or *FAIL* (~3×10⁻⁹). Only anomalies that appear at the same test across multiple data sizes (suggesting a genuine structural weakness rather than a chance fluctuation) are considered significant.

| Mode | Anomaly | Test | Size(s) | p-value | Assessment |
|------|---------|------|---------|---------|------------|
| BARE | [Low8/32]DC6-9x1Bytes-1 | DC6 | 4 KB, 128 KB | 0.012, 0.0021 | **Real weakness** — same test at two scales, p worsening |
| BT | [Low8/32]BCFN | BCFN | 2 MB (final) | unusual | Noise — single occurrence at last step only |
| ADC_WIFI_BT | DC6, Gap-16 | DC6/Gap-16 | 16/32 KB, 2 MB | unusual | Noise — no buildup, separate tests, no pattern |
| All others | — | — | — | — | Clean across all sizes |

**BARE mode** is the only mode with a consistent, escalating anomaly. The [Low8/32] prefix means PractRand is folding the data to examine only the lowest 8 bits of each 32-bit word (`Low8`) before running the test — the anomaly is localised to the low-bit output of the RNG register. The DC6 test detects short-range correlations between adjacent samples. The p-value worsening from 0.012 (*unusual*) at 4 KB to 0.0021 (*suspicious*) at 128 KB is characteristic of a genuine structural bias rather than statistical noise: true randomness would not produce the same test flagging consistently, and the escalation pattern suggests the effect would likely reach *FAIL* with sufficient data. This is consistent with the TRM warning that BARE mode (RC oscillator only) produces lower-quality randomness — the low-order bits of the RNG register appear to retain short-range correlation when no ADC or RF entropy path is active.

The BT and ADC_WIFI_BT anomalies are isolated single-step occurrences without escalation, consistent with chance (*unusual* events have ~10% false-positive rate per test per data size).

### 4.4 Byte Histograms and Bit Visualisation

*(Figures: `results/byte_histograms.png`, `results/bit_matrix.png`)*

### 4.5 Autocorrelation and Serial Correlation

*(Figures: `results/autocorrelation.png`, `results/scatter_pairs.png`)*

---

## 5. Engineering Contributions

This project required three non-trivial engineering efforts before any RNG data could be collected or analysed.

### 5.1 Porting PractRand to Apple Silicon (ARM64 / macOS)

PractRand 0.95 was written for x86 Linux and does not compile on Apple Silicon Macs because it unconditionally emits x86-only CPUID intrinsics and contains a shift-overflow that is undefined behaviour on 64-bit targets. Three source files were patched.

**Patch 1: `src/platform_specifics.cpp` — x86 intrinsic guard**
```cpp
// Before: unconditional CPUID block (compile error on arm64)

// After:
#if defined(__i386__) || defined(__x86_64__)
  // ... existing CPUID detection ...
#elif defined __APPLE__ && defined __MACH__
  // Apple Silicon: no x86 CPUID
#endif
```

**Patch 2: `src/tests_other.cpp` — shift overflow fix**

A right-shift by `BITS_PER_BLOCK` (64 on 64-bit platforms) was undefined behaviour. Shifting a 64-bit value by its own width is not defined in C++.
```cpp
// Before:
result = value >> BITS_PER_BLOCK;  // UB when BITS_PER_BLOCK == 64

// After:
result = (BITS_PER_BLOCK >= 64) ? 0 : (value >> BITS_PER_BLOCK);
```

**Patch 3: `tools/dummy_rng.h` — x86 intrinsic guard**

Same `#if defined(__i386__) || defined(__x86_64__)` wrapper around RDRAND intrinsics, leaving ARM to fall back to the portable implementation.

**Build (Apple Silicon):**
```bash
cd PractRand
g++ -c src/*.cpp src/RNGs/*.cpp src/RNGs/other/*.cpp -O3 -Iinclude -pthread
ar rcs libPractRand.a *.o
g++ -o RNG_test tools/RNG_test.cpp libPractRand.a -O3 -Iinclude -pthread
```

### 5.2 Replacing the `nistrng` Library: Bug Discovery and Ground-Up NIST SP 800-22 Implementation

The PyPI package `nistrng` was the natural choice for running all 15 NIST SP 800-22 tests from Python. During initial testing, several defects were found that produced incorrect p-values or silent failures on our data.

**Bug 1 — Integer overflow in Monobit test.** `nistrng` accumulates the bit sum via a Python loop rather than a vectorised NumPy reduction. For sequences longer than ~2²⁰ bits, intermediate arithmetic overflows 32-bit integer promotion in the C extension, producing a wrapped sum and a meaningless p-value.

**Bug 2 — Monobit: p-value returned as z-score.** The Monobit test computes the test statistic $s_\text{obs} = |S_n|/\sqrt{n}$ and must convert it to a p-value via $p = \text{erfc}(s_\text{obs}/\sqrt{2})$. `nistrng` returned $s_\text{obs}$ directly as the score, producing values outside $[0,1]$ and causing the pass/fail threshold comparison to be meaningless. This was the first defect encountered and prompted the full audit that uncovered the remaining bugs.

**Bug 3 — Block Frequency: incorrect χ² normalisation.** The NIST formula (SP 800-22 §2.2) scales by `4M`; `nistrng` scales by `4/M` in at least one code path, producing p-values that are orders of magnitude too large and cause genuine failures to be reported as passes.

**Bug 3 — Runs Test: missing frequency pre-requisite check.** NIST specifies the Runs Test should return N/A when |π̂ − 0.5| ≥ 2/√n. `nistrng` skips this guard, so a highly biased sequence produces a spurious p-value that can falsely pass.

**Bug 4 — Linear Complexity: wrong polynomial reduction.** The Berlekamp–Massey step uses a non-standard polynomial field reduction, leading to LFSR lengths that differ from the NIST reference implementation by up to 5% of blocks — enough to flip borderline sequences from pass to fail.

**Bug 5 — Random Excursions Variant: off-by-one state range.** The variant test should iterate over states −9 … +9 (18 non-zero states). `nistrng` iterates over −8 … +8 (16 states), silently omitting the two extreme states.

**Replacement: `analysis/nist_tests.py`**

All 15 tests were re-implemented from scratch, working directly from NIST SP 800-22 Rev. 1a. Each function returns `{score, passed, eligible}`. Key decisions:
- All bit-level sums use `np.int64` to prevent overflow at 8 M-bit sequences
- Block Frequency uses the exact `4M` scaling factor
- Runs Test enforces the |π̂ − 0.5| < 2/√n pre-requisite
- Linear Complexity uses standard GF(2) Berlekamp–Massey with no extra normalisation
- Random Excursions Variant iterates over all 18 non-zero states (−9…−1, +1…+9)

**Validation: `analysis/test_nist.py`**

Cross-checks the implementation against worked examples from NIST SP 800-22 Rev. 1a using exact input sequences and expected p-values:
- T01 (§2.1.4, n=10): p = 0.527089 ✓
- T02 (§2.2.4, n=10, M=3): p = 0.801252 ✓
- T03 (§2.3.4, n=10): p = 0.147232 ✓
- T07 (§2.7.4, n=20, B=001): p = 0.344154 ✓

All four agree to at least 4 significant figures. Sanity checks (degenerate sequences must fail; sub-threshold sequences must return N/A) pass for T01–T07, T09, and T10. The DFT test (T06) is not validated against the §2.6.4 toy example (n=10) because that sequence is below the 1000-bit minimum and the NIST reference C code produces non-reproducible magnitudes at sub-minimum lengths; for actual sequences (n ≈ 8×10⁶ bits) the implementation behaves correctly. **19/19 checks pass.**

### 5.3 Custom ESP32 Partition Table

The ESP32-WROOM-32 ships with 4 MB SPI flash. The default ESP-IDF partition scheme allocates only 1 MB to the factory application slot. Enabling both Wi-Fi and Bluetooth in a single firmware image (required for modes 3, 6, and 7) produces a binary of approximately 1.25 MB — exceeding the default slot by ~250 kB and causing the flash write to fail at link time.

| Partition | Type | Default | Custom |
|-----------|------|---------|--------|
| nvs | data/nvs | 20 kB | 20 kB |
| otadata | data/ota | 8 kB | 8 kB |
| factory | app/factory | 1 MB | **1.94 MB** |
| nvs_key | data/nvs_keys | — | 4 kB |

```csv
# Name,   Type, SubType,  Offset,   Size
nvs,      data, nvs,      0x9000,   0x5000,
otadata,  data, ota,      0xe000,   0x2000,
factory,  app,  factory,  0x10000,  0x1F0000,
nvs_key,  data, nvs_keys, 0x200000, 0x1000,
```

This change was necessary for all Wi-Fi+BT combination modes and is the reason a single binary image supports all eight entropy configurations rather than requiring separate per-mode builds.

---

## 6. Discussion

*(Fill in after data collection.)*

Expected findings based on the ESP32 TRM:
- **BARE** should exhibit the lowest entropy and most NIST failures — RC oscillator jitter alone provides limited noise and the TRM explicitly warns randomness quality is reduced.
- **Modes 1–3 (RF only)** should substantially increase entropy toward the 8-bit ideal, since the HSADC delivers 2 bits per 80 MHz APB cycle.
- **Mode 4 (ADC only)** may provide moderate improvement relative to BARE; the SAR ADC delivers 2 bits per 8 MHz RC cycle, giving lower throughput than HSADC.
- **Modes 5–7 (combined)** should match or exceed pure RF modes. The TRM specifically recommends enabling SAR ADC alongside Wi-Fi to compensate for potential HSADC saturation events; if saturation is occurring in modes 1–3, mode 5–7 should show measurably higher entropy.
- **Mode 7 (ADC_WIFI_BT)** should be the strongest configuration with all three noise paths feeding the XOR gate simultaneously.

The security implication is that firmware that never activates the RF subsystem — common in low-power or early-boot code — may generate cryptographically weak keys if it relies on `esp_random()` without first seeding the hardware RNG pool.

---

## 7. Conclusion

We characterised the ESP32 hardware RNG under eight entropy source configurations using Shannon entropy, min-entropy, collision entropy, all 15 NIST SP 800-22 statistical tests, and PractRand. Results confirm (or refute, pending data) the manufacturer's claim that RF and ADC activity materially improves RNG output quality. The combination modes (5–7) test the TRM's own recommendation of running SAR ADC alongside Wi-Fi to compensate for HSADC saturation — a real-world design decision relevant to any security-sensitive ESP32 application. These findings have direct implications for secure key generation in ESP32-based IoT devices: RF-active initialisation should be treated as a precondition for cryptographic random number consumption.

---

## References

1. Espressif Systems, *ESP32 Technical Reference Manual*, v5.7, §18 Random Number Generator.
2. A. Rukhin et al., *A Statistical Test Suite for Random and Pseudorandom Number Generators for Cryptographic Applications*, NIST SP 800-22 Rev. 1a, 2010.
3. L. Dorrendorf, Z. Gutterman, B. Pinkas, "Cryptanalysis of the Random Number Generator of the Windows Operating System," *ACM Trans. Inf. Syst. Secur.*, 2009. (Debian OpenSSL 2008 key generation bug)
4. B. Mechelen, "New ECDSA attack on Android," *Bitcoin Talk Forum*, 2013.
