#!/usr/bin/env python3
"""
analyze.py — Statistical characterization of ESP32 hardware RNG output.

Loads all  data/mode_XX_<NAME>.bin  files produced by collect.py and runs:

  Entropy metrics
    • Shannon entropy      (bits / byte)
    • Min-entropy  H∞      (bits / byte)
    • Collision entropy H₂ (bits / byte)

  NIST SP 800-22 — all 15 tests via the nistrng library
    (p ≥ 0.01 = PASS; ineligible tests reported as N/A)

  Linear Complexity / LFSR analysis (Berlekamp-Massey)
    • Runs BM on 500 non-overlapping 500-bit blocks per mode
    • Reports mean L, std L, ideal L = 250 (M/2)
    • Low L → predictable / reverse-engineerable sequence

  Visualisations saved to results/
    byte_histograms.png, entropy_comparison.png, nist_pvalues.png,
    nist_heatmap.png, bit_frequency.png, autocorrelation.png,
    scatter_pairs.png, bit_matrix.png, linear_complexity.png

Usage:
    python analyze.py                           # data/ → results/
    python analyze.py --data-dir d --output-dir r

Requirements:
    pip install numpy scipy matplotlib pyserial nistrng
"""

import argparse
import csv
import glob
import json
import math
import os
import sys
import time
from pathlib import Path

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

import nist_tests
import test_plots




# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_bin(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        return np.frombuffer(f.read(), dtype="<u4")

def to_bytes_u8(samples: np.ndarray) -> np.ndarray:
    return samples.view(np.uint8)

def to_bits(samples: np.ndarray) -> np.ndarray:
    """Return bit array as int8 (0/1) — format nistrng expects."""
    return np.unpackbits(samples.view(np.uint8)).astype(np.int8)


# ---------------------------------------------------------------------------
# Entropy metrics
# ---------------------------------------------------------------------------

def shannon_entropy(data: np.ndarray) -> float:
    counts = np.bincount(data, minlength=256).astype(np.float64)
    probs  = counts[counts > 0] / len(data)
    return float(-np.sum(probs * np.log2(probs)))

def min_entropy(data: np.ndarray) -> float:
    counts = np.bincount(data, minlength=256).astype(np.float64)
    p_max  = counts.max() / len(data)
    return float(-math.log2(p_max)) if p_max > 0 else 8.0

def collision_entropy(data: np.ndarray) -> float:
    counts = np.bincount(data, minlength=256).astype(np.float64)
    probs  = counts / len(data)
    return float(-math.log2(np.sum(probs ** 2)))


# ---------------------------------------------------------------------------
# Berlekamp-Massey linear complexity analysis
# ---------------------------------------------------------------------------

def berlekamp_massey(seq) -> int:
    """
    Return the shortest LFSR length L that generates binary sequence seq.
    Implements the standard BM algorithm over GF(2).
    For a truly random sequence of length M, L concentrates around M/2.
    A persistently low L (e.g. < M/4) means the sequence is predictable.
    """
    n = len(seq)
    C = [1]; B = [1]   # connection polynomials
    L = 0; x = 1       # x = steps since last length change
    for N in range(n):
        d = int(seq[N])
        for i in range(1, L + 1):
            d ^= int(C[i]) * int(seq[N - i])
        d &= 1
        if d == 0:
            x += 1
        elif 2 * L <= N:
            T  = C[:]
            Bx = [0] * x + B          # z^x * B(z)
            sz = max(len(C), len(Bx))
            C  = (C  + [0] * sz)[:sz]
            Bx = (Bx + [0] * sz)[:sz]
            C  = [(C[i] ^ Bx[i]) & 1 for i in range(sz)]
            L  = N + 1 - L
            B  = T; x = 1
        else:
            Bx = [0] * x + B
            sz = max(len(C), len(Bx))
            C  = (C  + [0] * sz)[:sz]
            Bx = (Bx + [0] * sz)[:sz]
            C  = [(C[i] ^ Bx[i]) & 1 for i in range(sz)]
            x += 1
    return L


def linear_complexity_profile(bits: np.ndarray,
                               block_size: int = 500,
                               max_blocks: int = 500) -> dict:
    """
    Run Berlekamp-Massey on up to max_blocks non-overlapping block_size-bit blocks.
    Returns dict with L statistics and the polynomial from the last block.
    Ideal for random data: mean(L) ≈ block_size/2, low std.
    """
    total_blocks = len(bits) // block_size
    n_blocks     = min(max_blocks, total_blocks)
    ideal_L      = block_size / 2.0

    L_values: list[int] = []
    last_C: list[int]   = []

    print(f"      Running BM on {n_blocks} × {block_size}-bit blocks …", flush=True)
    for b in range(n_blocks):
        block = bits[b * block_size : (b + 1) * block_size].tolist()
        L_val = berlekamp_massey(block)
        L_values.append(L_val)
        if b == n_blocks - 1:
            # Rebuild final polynomial for display
            from copy import copy
            C = [1]; B = [1]; Lc = 0; x = 1
            for N in range(block_size):
                d = block[N]
                for i in range(1, Lc + 1):
                    d ^= C[i] * block[N - i]
                d &= 1
                if d == 0:
                    x += 1
                elif 2 * Lc <= N:
                    T  = C[:]
                    Bx = [0] * x + B
                    sz = max(len(C), len(Bx))
                    C  = (C  + [0] * sz)[:sz]
                    Bx = (Bx + [0] * sz)[:sz]
                    C  = [(C[i] ^ Bx[i]) & 1 for i in range(sz)]
                    Lc = N + 1 - Lc; B = T; x = 1
                else:
                    Bx = [0] * x + B
                    sz = max(len(C), len(Bx))
                    C  = (C  + [0] * sz)[:sz]
                    Bx = (Bx + [0] * sz)[:sz]
                    C  = [(C[i] ^ Bx[i]) & 1 for i in range(sz)]
                    x += 1
            last_C = C

    arr       = np.array(L_values)
    mean_L    = float(np.mean(arr))
    std_L     = float(np.std(arr))
    min_L     = int(np.min(arr))
    max_L     = int(np.max(arr))
    frac_low  = float(np.mean(arr < ideal_L * 0.75))   # fraction with L < 3/8 * M

    # Summarise the feedback polynomial as a hex string (first 8 coefficients max)
    poly_preview = "".join(str(c) for c in last_C[:min(len(last_C), 64)])

    return {
        "L_values":     L_values,
        "n_blocks":     n_blocks,
        "block_size":   block_size,
        "ideal_L":      ideal_L,
        "mean_L":       mean_L,
        "std_L":        std_L,
        "min_L":        min_L,
        "max_L":        max_L,
        "frac_low":     frac_low,
        "poly_preview": poly_preview,
    }


# ---------------------------------------------------------------------------
# NIST SP 800-22 — our own implementations, no nistrng dependency
# ---------------------------------------------------------------------------

def run_nist(bits: np.ndarray) -> dict:
    return nist_tests.run_all(bits, verbose=True)


# ---------------------------------------------------------------------------
# Per-mode analysis
# ---------------------------------------------------------------------------

def analyze_mode(samples: np.ndarray, mode_name: str, mode_num: int, total: int,
                 mode_out_dir: str = None) -> dict:
    data_u8 = to_bytes_u8(samples)
    bits    = to_bits(samples)

    sh  = shannon_entropy(data_u8)
    minh = min_entropy(data_u8)
    colh = collision_entropy(data_u8)
    bp   = float(np.mean(bits))
    print(f"    Entropy  Shannon={sh:.2e}  H∞={minh:.2e}  H₂={colh:.2e}  1-bits={bp*100:.3f}%")

    print(f"    NIST SP 800-22  ({len(bits):,} bits):")
    t0 = time.time()
    nist = run_nist(bits)
    print(f"    NIST done in {time.time()-t0:.1f}s")

    print(f"    Linear Complexity (Berlekamp-Massey):")
    t0 = time.time()
    lc = linear_complexity_profile(bits)
    elapsed = time.time() - t0
    predictable = lc["frac_low"] > 0.5
    print(f"      mean L={lc['mean_L']:.1f}  std={lc['std_L']:.1f}  "
          f"ideal={lc['ideal_L']:.0f}  "
          f"frac<75%ideal={lc['frac_low']*100:.1f}%  "
          f"{'⚠ PREDICTABLE' if predictable else 'OK'}  ({elapsed:.1f}s)")

    if mode_out_dir:
        print(f"    Per-test plots → {mode_out_dir}/")
        test_plots.plot_all_tests(bits, nist, mode_name, mode_out_dir, lc_data=lc)

    return {
        "mode":              mode_name,
        "n_samples_32bit":   len(samples),
        "n_bits":            len(bits),
        "shannon_bpb":       sh,
        "min_entropy":       minh,
        "collision_entropy": colh,
        "bit_prop_ones":     bp,
        "nist":              nist,
        "lc":                lc,
    }


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def print_summary(all_results: dict) -> None:
    # Collect all test names that appeared
    all_test_names = []
    for r in all_results.values():
        for name in r["nist"]:
            if name not in all_test_names:
                all_test_names.append(name)

    sep = "─" * 100
    print()
    print(sep)
    print("  ESP32 RNG — NIST SP 800-22 (nistrng)  |  ✗ = FAIL  |  N/A = ineligible")
    print(sep)

    # Entropy header
    print(f"  {'Mode':<14} {'Shannon':>8} {'H_inf':>7} {'H_2':>7}  {'1-bit%':>7}")
    print(sep)
    for r in all_results.values():
        print(f"  {r['mode']:<14} "
              f"{r['shannon_bpb']:8.4f} "
              f"{r['min_entropy']:7.4f} "
              f"{r['collision_entropy']:7.4f}  "
              f"{r['bit_prop_ones']*100:7.4f}%")

    print()
    print("  NIST p-values (score = mean p-value across sub-tests):")
    print(sep)
    name_w = max(len(n) for n in all_test_names) + 2
    header  = f"  {'Test':<{name_w}}"
    for mode in all_results:
        header += f" {mode:>12}"
    print(header)
    print(sep)

    for tname in all_test_names:
        row = f"  {tname:<{name_w}}"
        for r in all_results.values():
            tr = r["nist"].get(tname)
            if tr is None or not tr["eligible"]:
                row += f"{'N/A':>13}"
            else:
                flag = " " if tr["passed"] else "✗"
                row += f"  {tr['score']:>8.5f}{flag}  "
        print(row)

    print(sep)
    print()

    # --- Linear complexity summary ---
    print("  Linear Complexity (Berlekamp-Massey, 500 blocks × 500 bits, ideal L=250):")
    print(sep)
    print(f"  {'Mode':<14} {'mean L':>8} {'std L':>7} {'min L':>7} {'max L':>7}  {'%<187':>6}  {'Verdict':>12}")
    print(sep)
    for r in all_results.values():
        lc = r.get("lc", {})
        if not lc:
            print(f"  {r['mode']:<14}  (no LC data)")
            continue
        verdict = "PREDICTABLE" if lc["frac_low"] > 0.5 else "random-like"
        print(f"  {r['mode']:<14} "
              f"{lc['mean_L']:8.1f} "
              f"{lc['std_L']:7.1f} "
              f"{lc['min_L']:7d} "
              f"{lc['max_L']:7d}  "
              f"{lc['frac_low']*100:6.1f}%  "
              f"{verdict:>12}")
    print(sep)
    print()


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

_CMAP = plt.cm.tab10

def _mode_color(i):
    return _CMAP(i % 10)

def _subplots_grid(n, col_max=4):
    cols = min(n, col_max)
    rows = math.ceil(n / cols)
    return rows, cols


def plot_byte_histograms(all_data, out_dir):
    n = len(all_data)
    rows, cols = _subplots_grid(n)
    fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 4*rows), squeeze=False)
    ax_flat = [ax for row in axes for ax in row]
    for i, (mode, samples) in enumerate(all_data.items()):
        data_u8 = to_bytes_u8(samples)
        counts  = np.bincount(data_u8, minlength=256)
        exp     = len(data_u8) / 256.0
        ax = ax_flat[i]
        ax.bar(range(256), counts, width=1.0, color=_mode_color(i), alpha=0.75, linewidth=0)
        ax.axhline(exp, color="red", lw=1.2, ls="--", label="Uniform")
        ax.set_title(mode, fontsize=10, fontweight="bold")
        ax.set_xlabel("Byte value"); ax.set_ylabel("Count")
        h = shannon_entropy(data_u8)
        ax.text(0.97, 0.95, f"H={h:.2e}b", transform=ax.transAxes,
                ha="right", va="top", fontsize=8,
                bbox=dict(boxstyle="round", fc="wheat", alpha=0.5))
        ax.legend(fontsize=7)
    for j in range(n, len(ax_flat)):
        ax_flat[j].set_visible(False)
    fig.suptitle("Byte-value distributions by entropy source mode", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "byte_histograms.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_entropy_comparison(all_results, out_dir):
    modes   = list(all_results.keys())
    shannon = [r["shannon_bpb"]       for r in all_results.values()]
    minH    = [r["min_entropy"]        for r in all_results.values()]
    colH    = [r["collision_entropy"]  for r in all_results.values()]
    x = np.arange(len(modes))
    w = 0.25
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.bar(x-w, shannon, w, label="Shannon",              color="#2196F3", alpha=0.85, ec="black", lw=0.4)
    ax.bar(x,   minH,    w, label="Min-entropy H∞",       color="#F44336", alpha=0.85, ec="black", lw=0.4)
    ax.bar(x+w, colH,    w, label="Collision entropy H₂", color="#4CAF50", alpha=0.85, ec="black", lw=0.4)
    ax.axhline(8.0, color="black", ls="--", lw=1.5, label="Ideal (8 bits/byte)")
    ax.set_xticks(x); ax.set_xticklabels(modes, rotation=30, ha="right")
    ax.set_ylim(0, 8.6); ax.set_xlabel("Mode"); ax.set_ylabel("Entropy (bits/byte)")
    ax.set_title("Entropy metrics by entropy source mode", fontsize=13, fontweight="bold")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "entropy_comparison.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_nist_pvalues(all_results, out_dir):
    modes = list(all_results.keys())
    all_test_names = list(next(iter(all_results.values()))["nist"].keys())

    fig, axes = plt.subplots(2, 1, figsize=(16, 12))
    colors = plt.cm.Set3(np.linspace(0, 1, 8))
    mid = len(all_test_names) // 2
    groups = [all_test_names[:mid], all_test_names[mid:]]

    for ax, test_names in zip(axes, groups):
        x = np.arange(len(modes))
        w = 0.9 / max(len(test_names), 1)
        for ti, tname in enumerate(test_names):
            pvals = []
            for r in all_results.values():
                tr = r["nist"].get(tname)
                pvals.append(tr["score"] if (tr and tr["eligible"]) else 0.0)
            ax.bar(x + ti*w, pvals, w, label=tname,
                   color=colors[ti % len(colors)], alpha=0.85, ec="black", lw=0.3)
        ax.axhline(0.01, color="red", ls="--", lw=2, label="α=0.01")
        ax.set_xticks(x + len(test_names)*w/2)
        ax.set_xticklabels(modes, rotation=20, ha="right")
        ax.set_ylim(0, 1.05); ax.set_ylabel("p-value")
        ax.set_title("NIST SP 800-22 p-values", fontsize=11, fontweight="bold")
        ax.legend(fontsize=8, ncol=4); ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "nist_pvalues.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_nist_heatmap(all_results, out_dir):
    """Binary PASS/FAIL heatmap: green=PASS, red=FAIL, grey=N/A."""
    modes      = list(all_results.keys())
    test_names = list(next(iter(all_results.values()))["nist"].keys())
    n_tests, n_modes = len(test_names), len(modes)

    # build integer matrix: 1=PASS, 0=FAIL, -1=N/A
    matrix = np.full((n_tests, n_modes), -1, dtype=float)
    for j, r in enumerate(all_results.values()):
        for i, tname in enumerate(test_names):
            tr = r["nist"].get(tname)
            if tr and tr["eligible"]:
                matrix[i, j] = 1.0 if tr["passed"] else 0.0

    masked = np.ma.masked_where(matrix < 0, matrix)
    cmap = matplotlib.colors.ListedColormap(["#F44336", "#4CAF50"])
    cmap.set_bad(color="#BDBDBD")

    fig, ax = plt.subplots(figsize=(max(10, n_modes * 1.4), max(6, n_tests * 0.55)))
    ax.imshow(masked, cmap=cmap, vmin=0, vmax=1, aspect="auto")

    ax.set_xticks(range(n_modes))
    ax.set_xticklabels(modes, rotation=35, ha="right", fontsize=9)
    ax.set_yticks(range(n_tests))
    ax.set_yticklabels(test_names, fontsize=9)
    ax.set_title("NIST SP 800-22 — Pass / Fail per mode  (green=PASS, red=FAIL, grey=N/A)",
                 fontsize=10, fontweight="bold")

    for i in range(n_tests):
        for j in range(n_modes):
            v = matrix[i, j]
            label = "N/A" if v < 0 else ("PASS" if v == 1.0 else "FAIL")
            ax.text(j, i, label, ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")

    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "nist_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_nist_pvalue_heatmap(all_results, out_dir):
    """Continuous RdYlGn p-value heatmap with pass-count bar chart."""
    modes      = list(all_results.keys())
    test_names = list(next(iter(all_results.values()))["nist"].keys())
    n_tests, n_modes = len(test_names), len(modes)

    matrix = np.full((n_tests, n_modes), np.nan)
    for j, r in enumerate(all_results.values()):
        for i, tname in enumerate(test_names):
            tr = r["nist"].get(tname)
            if tr and tr["eligible"]:
                matrix[i, j] = tr["score"]

    fig, (ax_p, ax_pf) = plt.subplots(
        1, 2,
        figsize=(max(14, n_modes * 1.6 + 6), max(7, n_tests * 0.58)),
        gridspec_kw={"width_ratios": [3, 1], "wspace": 0.08},
    )

    cmap_pval = plt.cm.RdYlGn.copy()
    cmap_pval.set_bad(color="#BDBDBD")
    masked = np.ma.masked_invalid(matrix)
    im = ax_p.imshow(masked, cmap=cmap_pval, vmin=0, vmax=1, aspect="auto")

    ax_p.set_xticks(range(n_modes))
    ax_p.set_xticklabels(modes, rotation=35, ha="right", fontsize=9)
    ax_p.set_yticks(range(n_tests))
    ax_p.set_yticklabels(test_names, fontsize=9)
    ax_p.set_title("NIST SP 800-22 — p-values per test per mode\n"
                   "(green=high p, red=low p, grey=N/A, dashed=α=0.01)",
                   fontsize=10, fontweight="bold")

    for i in range(n_tests):
        for j in range(n_modes):
            v = matrix[i, j]
            if np.isnan(v):
                ax_p.text(j, i, "N/A", ha="center", va="center", fontsize=7, color="#555555")
            else:
                color  = "black" if 0.15 < v < 0.85 else "white"
                weight = "bold"  if v < 0.01 else "normal"
                ax_p.text(j, i, f"{v:.3f}", ha="center", va="center",
                          fontsize=7, color=color, fontweight=weight)

    cb = fig.colorbar(im, ax=ax_p, fraction=0.025, pad=0.02)
    cb.set_label("p-value", fontsize=9)
    cb.ax.axhline(0.01, color="red", lw=1.5, linestyle="--")
    cb.ax.text(1.6, 0.01, "α=0.01", va="center", fontsize=7,
               color="red", transform=cb.ax.transData)

    pass_counts = np.sum(~np.isnan(matrix) & (matrix >= 0.01), axis=1)
    elig_counts = np.sum(~np.isnan(matrix), axis=1)
    fail_counts = elig_counts - pass_counts

    ypos = np.arange(n_tests)
    ax_pf.barh(ypos, pass_counts,  color="#4CAF50", label="PASS", height=0.6)
    ax_pf.barh(ypos, fail_counts, left=pass_counts, color="#F44336", label="FAIL", height=0.6)
    ax_pf.set_xlim(0, n_modes)
    ax_pf.set_xticks(range(n_modes + 1))
    ax_pf.set_xlabel("# modes", fontsize=9)
    ax_pf.set_yticks(ypos)
    ax_pf.set_yticklabels([""] * n_tests)
    ax_pf.set_title("Pass\ncount", fontsize=9, fontweight="bold")
    ax_pf.legend(fontsize=7, loc="lower right")
    ax_pf.axvline(n_modes, color="gray", lw=0.5, linestyle=":")

    fig.savefig(os.path.join(out_dir, "nist_pvalue_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_bit_frequency(all_results, out_dir):
    modes = list(all_results.keys())
    props = [r["bit_prop_ones"] for r in all_results.values()]
    colors = [_mode_color(i) for i in range(len(modes))]
    fig, ax = plt.subplots(figsize=(12, 5))
    bars = ax.bar(modes, props, color=colors, alpha=0.85, ec="black", lw=0.5)
    ax.axhline(0.50,        color="green",  ls="--", lw=2,   label="Ideal (0.5)")
    ax.axhline(0.50 + 0.01, color="orange", ls=":",  lw=1.5, label="±1% bound")
    ax.axhline(0.50 - 0.01, color="orange", ls=":",  lw=1.5)
    for bar, val in zip(bars, props):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height()+0.0003,
                f"{val:.5f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticklabels(modes, rotation=30, ha="right")
    ax.set_ylim(0.45, 0.55); ax.set_ylabel("Proportion of 1-bits")
    ax.set_title("Bit frequency (proportion of 1-bits) per mode", fontsize=13, fontweight="bold")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "bit_frequency.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_autocorrelation(all_data, out_dir, max_lag=50):
    n = len(all_data)
    rows, cols = _subplots_grid(n)
    fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 3*rows), squeeze=False)
    ax_flat = [ax for row in axes for ax in row]
    for i, (mode, samples) in enumerate(all_data.items()):
        b = samples.view(np.uint8).astype(np.float64)
        b -= b.mean()
        var = np.var(b)
        nb = len(b)
        corrs = (np.array([np.mean(b[:nb-l] * b[l:]) for l in range(1, max_lag+1)])
                 / var if var > 1e-12 else np.zeros(max_lag))
        ax = ax_flat[i]
        ax.bar(range(1, max_lag+1), corrs, width=0.8, color=_mode_color(i), alpha=0.7)
        ax.axhline(0, color="black", lw=0.8)
        sig = 2.0 / math.sqrt(len(samples)*4)
        ax.axhline( sig, color="red", ls="--", lw=1, alpha=0.8)
        ax.axhline(-sig, color="red", ls="--", lw=1, alpha=0.8)
        ax.set_title(mode, fontsize=9, fontweight="bold")
        ax.set_xlabel("Lag"); ax.set_ylabel("Correlation")
        ax.set_ylim(-0.08, 0.08)
    for j in range(n, len(ax_flat)):
        ax_flat[j].set_visible(False)
    fig.suptitle("Byte-level autocorrelation (red = ≈2σ threshold)", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "autocorrelation.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_scatter_pairs(all_data, out_dir, n_pts=5000):
    n = len(all_data)
    rows, cols = _subplots_grid(n)
    fig, axes = plt.subplots(rows, cols, figsize=(4*cols, 4*rows), squeeze=False)
    ax_flat = [ax for row in axes for ax in row]
    for i, (mode, samples) in enumerate(all_data.items()):
        pts = min(n_pts, len(samples)-1)
        x   = samples[:pts].astype(np.float64) / 2**32
        y   = samples[1:pts+1].astype(np.float64) / 2**32
        ax  = ax_flat[i]
        ax.scatter(x, y, s=0.4, alpha=0.3, color=_mode_color(i), linewidths=0)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.set_title(mode, fontsize=9, fontweight="bold")
        ax.set_xlabel("xᵢ (normalised)"); ax.set_ylabel("xᵢ₊₁")
        ax.set_aspect("equal")
    for j in range(n, len(ax_flat)):
        ax_flat[j].set_visible(False)
    fig.suptitle("Consecutive-sample scatter (uniform fill = no serial correlation)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "scatter_pairs.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_bit_matrix(all_data, out_dir, n_bits=65536):
    side = int(math.sqrt(n_bits))
    n = len(all_data)
    rows, cols = _subplots_grid(n)
    fig, axes = plt.subplots(rows, cols, figsize=(4*cols, 4*rows), squeeze=False)
    ax_flat = [ax for row in axes for ax in row]
    for i, (mode, samples) in enumerate(all_data.items()):
        bits = np.unpackbits(samples.view(np.uint8))[:side*side].reshape(side, side)
        ax   = ax_flat[i]
        ax.imshow(bits, cmap="gray", interpolation="none", vmin=0, vmax=1)
        ax.set_title(mode, fontsize=9, fontweight="bold")
        ax.axis("off")
    for j in range(n, len(ax_flat)):
        ax_flat[j].set_visible(False)
    fig.suptitle(f"Raw bit visualisation ({side}×{side} = {side*side:,} bits)\n"
                 "Ideal: uniform grey noise — visible structure = weak entropy",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "bit_matrix.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_linear_complexity(all_results, out_dir):
    """
    Histogram of L values per mode.
    Random source → bell centred on M/2=250.
    PRNG/LFSR  → spike at a much smaller value.
    """
    n = len(all_results)
    rows, cols = _subplots_grid(n)
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows), squeeze=False)
    ax_flat = [ax for row in axes for ax in row]

    for i, (mode, r) in enumerate(all_results.items()):
        lc = r.get("lc", {})
        ax = ax_flat[i]
        if not lc or not lc.get("L_values"):
            ax.set_title(f"{mode}\n(no LC data)"); ax.axis("off"); continue

        L_arr     = np.array(lc["L_values"])
        ideal     = lc["ideal_L"]
        block_sz  = lc["block_size"]

        ax.hist(L_arr, bins=30, color=_mode_color(i), alpha=0.8, edgecolor="black", lw=0.4)
        ax.axvline(ideal,       color="green", lw=2,   ls="--", label=f"Ideal M/2={ideal:.0f}")
        ax.axvline(lc["mean_L"],color="red",   lw=1.5, ls="-",  label=f"Mean={lc['mean_L']:.1f}")
        ax.set_title(f"{mode}", fontsize=9, fontweight="bold")
        ax.set_xlabel("LFSR length L"); ax.set_ylabel("Block count")
        ax.legend(fontsize=7)

        verdict = "PREDICTABLE" if lc["frac_low"] > 0.5 else "random-like"
        ax.text(0.97, 0.95, verdict,
                transform=ax.transAxes, ha="right", va="top", fontsize=8,
                color="red" if lc["frac_low"] > 0.5 else "green",
                fontweight="bold",
                bbox=dict(boxstyle="round", fc="white", alpha=0.7))

    for j in range(n, len(ax_flat)):
        ax_flat[j].set_visible(False)

    fig.suptitle(
        "Berlekamp-Massey: distribution of shortest LFSR length L\n"
        "(500 blocks × 500 bits | green dashed = ideal M/2 = 250 | "
        "left spike → predictable / reversible)",
        fontsize=11, fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "linear_complexity.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Cache — save / load all_results as JSON so plots can be regenerated
# without re-running NIST + BM
# ---------------------------------------------------------------------------

_CACHE_FILE = "analysis_cache.json"


def save_cache(all_results: dict, out_dir: str) -> None:
    path = os.path.join(out_dir, _CACHE_FILE)
    with open(path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"  Cache saved → {path}")


def load_cache(out_dir: str) -> dict:
    path = os.path.join(out_dir, _CACHE_FILE)
    with open(path) as f:
        data = json.load(f)
    print(f"[cache] Loaded {len(data)} modes from {path}")
    return data


def save_csv(all_results: dict, out_dir: str) -> None:
    """Write one CSV row per mode with entropy metrics + all NIST p-values."""
    path = os.path.join(out_dir, "results_summary.csv")

    # Collect all test names across all modes (preserves order)
    test_names: list[str] = []
    for r in all_results.values():
        for k in r["nist"]:
            if k not in test_names:
                test_names.append(k)

    header = (["mode", "n_samples", "n_bits",
                "shannon_bpb", "min_entropy", "collision_entropy", "bit_prop_ones",
                "lc_mean_L", "lc_std_L", "lc_frac_low"]
              + [f"p_{t}" for t in test_names]
              + [f"pass_{t}" for t in test_names])

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in all_results.values():
            lc = r.get("lc", {})
            row = [
                r["mode"], r["n_samples_32bit"], r["n_bits"],
                r["shannon_bpb"], r["min_entropy"], r["collision_entropy"], r["bit_prop_ones"],
                lc.get("mean_L", ""), lc.get("std_L", ""), lc.get("frac_low", ""),
            ]
            for t in test_names:
                tr = r["nist"].get(t, {})
                row.append(tr.get("score", "") if tr.get("eligible") else "N/A")
            for t in test_names:
                tr = r["nist"].get(t, {})
                if not tr.get("eligible"):
                    row.append("N/A")
                else:
                    row.append("PASS" if tr.get("passed") else "FAIL")
            w.writerow(row)

    print(f"  CSV saved → {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Statistical analysis of ESP32 RNG samples.")
    parser.add_argument("--data-dir",   default=os.path.join(_PROJECT_ROOT, "data"),
                        help="Directory with mode_XX_*.bin files (default: <project>/data/)")
    parser.add_argument("--output-dir", default=os.path.join(_PROJECT_ROOT, "results"),
                        help="Directory for plots and reports (default: <project>/results/)")
    parser.add_argument("--from-cache", action="store_true",
                        help="Skip analysis; reload results from analysis_cache.json and regenerate plots")
    args = parser.parse_args()

    # results/
    #   summary/          ← cross-mode overview plots + cache + CSV
    #   mode_00_BARE/     ← per-test diagnostic PNGs for each mode
    #   mode_01_WIFI/
    #   …
    summary_dir = os.path.join(args.output_dir, "summary")
    os.makedirs(summary_dir, exist_ok=True)

    all_data:    dict[str, np.ndarray] = {}
    all_results: dict[str, dict]       = {}

    # ------------------------------------------------------------------
    # Fast path: reload from cache and skip all computation
    # ------------------------------------------------------------------
    if args.from_cache:
        all_results = load_cache(summary_dir)
        # Still need raw samples for plots that use all_data (byte histo, autocorr, etc.)
        bin_files = sorted(glob.glob(os.path.join(args.data_dir, "mode_*.bin")))
        for fp in bin_files:
            stem  = Path(fp).stem
            parts = stem.split("_", 2)
            name  = parts[2] if len(parts) >= 3 else stem
            all_data[name] = load_bin(fp)
            # Regenerate per-test plots from cached results
            mode_out_dir = os.path.join(args.output_dir, stem)
            bits = to_bits(all_data[name])
            lc   = all_results[name].get("lc")
            print(f"  Regenerating plots for {name} …")
            test_plots.plot_all_tests(bits, all_results[name]["nist"], name,
                                      mode_out_dir, lc_data=lc)
    else:
        # ------------------------------------------------------------------
        # Full analysis path
        # ------------------------------------------------------------------
        bin_files = sorted(glob.glob(os.path.join(args.data_dir, "mode_*.bin")))
        if not bin_files:
            print(f"ERROR: no sample files found in '{args.data_dir}/'.\n"
                  f"Run  python collect.py  first.", file=sys.stderr)
            sys.exit(1)

        total = len(bin_files)
        print(f"Found {total} mode file(s). Starting analysis …\n")

        t_start = time.time()
        for i, fp in enumerate(bin_files, 1):
            stem  = Path(fp).stem
            parts = stem.split("_", 2)
            name  = parts[2] if len(parts) >= 3 else stem

            mode_out_dir = os.path.join(args.output_dir, stem)
            os.makedirs(mode_out_dir, exist_ok=True)

            samples = load_bin(fp)
            n_bits  = len(samples) * 32
            print(f"── Mode {i}/{total}: {name}  ({len(samples):,} samples, {n_bits:,} bits) ──")
            t_mode = time.time()

            all_data[name]    = samples
            all_results[name] = analyze_mode(samples, name, i, total,
                                             mode_out_dir=mode_out_dir)

            print(f"    Mode {name} done in {time.time()-t_mode:.1f}s  "
                  f"(total elapsed {time.time()-t_start:.1f}s)\n")

        print_summary(all_results)

        print("Saving cache and CSV …")
        # Strip L_values list before caching (large — recoverable from .bin)
        cache = {}
        for mode, r in all_results.items():
            cr = {k: v for k, v in r.items() if k != "lc"}
            lc = r.get("lc", {})
            cr["lc"] = {k: v for k, v in lc.items() if k != "L_values"}
            cache[mode] = cr
        save_cache(cache, summary_dir)
        save_csv(all_results, summary_dir)

    print("Generating summary plots …")
    plot_byte_histograms(all_data,       summary_dir); print("  summary/byte_histograms.png")
    plot_entropy_comparison(all_results, summary_dir); print("  summary/entropy_comparison.png")
    plot_nist_pvalues(all_results,       summary_dir); print("  summary/nist_pvalues.png")
    plot_nist_heatmap(all_results,       summary_dir); print("  summary/nist_heatmap.png")
    plot_nist_pvalue_heatmap(all_results, summary_dir); print("  summary/nist_pvalue_heatmap.png")
    plot_bit_frequency(all_results,      summary_dir); print("  summary/bit_frequency.png")
    plot_autocorrelation(all_data,       summary_dir); print("  summary/autocorrelation.png")
    plot_scatter_pairs(all_data,         summary_dir); print("  summary/scatter_pairs.png")
    plot_bit_matrix(all_data,            summary_dir); print("  summary/bit_matrix.png")
    plot_linear_complexity(all_results,  summary_dir); print("  summary/linear_complexity.png")

    print(f"\nAll outputs saved to  {args.output_dir}/")
    print(f"  Cross-mode summaries → {summary_dir}/")
    print(f"  Per-test diagnostics → {args.output_dir}/mode_XX_NAME/")
    print(f"  Cache (fast reload)  → {summary_dir}/{_CACHE_FILE}")
    print(f"  CSV summary          → {summary_dir}/results_summary.csv")


if __name__ == "__main__":
    main()
