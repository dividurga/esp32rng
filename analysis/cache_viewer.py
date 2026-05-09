#!/usr/bin/env python3
"""
cache_viewer.py — Regenerate all summary plots from the JSON analysis cache.

Reads results/summary/analysis_cache.json produced by analyze.py and
regenerates every plot without rerunning any NIST tests.  Fast: seconds
instead of hours.

Usage:
    python cache_viewer.py                          # default paths
    python cache_viewer.py --cache path/to/cache.json --output-dir results/
    python cache_viewer.py --plot pvalue_heatmap    # single plot only

Available --plot names:
    heatmap           binary PASS/FAIL heatmap
    pvalue_heatmap    continuous RdYlGn p-value heatmap + pass-count bar
    pvalues           per-test p-value bar chart (all modes)
    entropy           entropy metrics comparison
    linear_complexity BM linear complexity per mode
    summary_table     print ASCII table of all p-values to stdout
    all               (default) everything above
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR   = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_DEFAULT_CACHE = _PROJECT_ROOT / "results" / "summary" / "analysis_cache.json"
_DEFAULT_OUT   = _PROJECT_ROOT / "results" / "summary"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_cache(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _nist_matrix(all_results):
    """Return (modes, test_names, pvalue_matrix[n_tests, n_modes])."""
    modes      = list(all_results.keys())
    test_names = list(next(iter(all_results.values()))["nist"].keys())
    n_tests, n_modes = len(test_names), len(modes)
    matrix = np.full((n_tests, n_modes), np.nan)
    for j, r in enumerate(all_results.values()):
        for i, tname in enumerate(test_names):
            tr = r["nist"].get(tname)
            if tr and tr.get("eligible", False):
                matrix[i, j] = tr["score"]
    return modes, test_names, matrix


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
def plot_heatmap(all_results, out_dir: Path):
    """Binary green/red PASS/FAIL heatmap."""
    modes, test_names, pmatrix = _nist_matrix(all_results)
    n_tests, n_modes = pmatrix.shape

    bmatrix = np.where(np.isnan(pmatrix), -1.0, np.where(pmatrix >= 0.01, 1.0, 0.0))
    masked  = np.ma.masked_where(bmatrix < 0, bmatrix)
    cmap    = matplotlib.colors.ListedColormap(["#F44336", "#4CAF50"])
    cmap.set_bad(color="#BDBDBD")

    fig, ax = plt.subplots(figsize=(max(10, n_modes * 1.4), max(6, n_tests * 0.55)))
    ax.imshow(masked, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(n_modes));      ax.set_xticklabels(modes, rotation=35, ha="right", fontsize=9)
    ax.set_yticks(range(n_tests));      ax.set_yticklabels(test_names, fontsize=9)
    ax.set_title("NIST SP 800-22 — Pass / Fail  (green=PASS, red=FAIL, grey=N/A)",
                 fontsize=10, fontweight="bold")

    for i in range(n_tests):
        for j in range(n_modes):
            v = bmatrix[i, j]
            label = "N/A" if v < 0 else ("PASS" if v == 1.0 else "FAIL")
            ax.text(j, i, label, ha="center", va="center", fontsize=7,
                    color="white", fontweight="bold")

    fig.tight_layout()
    out = out_dir / "nist_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


def plot_pvalue_heatmap(all_results, out_dir: Path):
    """Continuous RdYlGn p-value heatmap with per-test pass-count bar."""
    modes, test_names, matrix = _nist_matrix(all_results)
    n_tests, n_modes = matrix.shape

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

    out = out_dir / "nist_pvalue_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


def plot_pvalues(all_results, out_dir: Path):
    """Grouped bar chart: p-value per test, one group per mode."""
    modes, test_names, matrix = _nist_matrix(all_results)
    n_tests, n_modes = matrix.shape

    x   = np.arange(n_tests)
    w   = 0.8 / n_modes
    fig, ax = plt.subplots(figsize=(max(14, n_tests * 0.9), 5))

    for j, mode in enumerate(modes):
        vals = matrix[:, j]
        bars = ax.bar(x + j * w - 0.4 + w / 2, vals, width=w * 0.9, label=mode)
        for bar, v in zip(bars, vals):
            if np.isnan(v):
                bar.set_color("#BDBDBD")

    ax.axhline(0.01, color="red", linestyle="--", lw=1.2, label="α=0.01")
    ax.set_xticks(x)
    ax.set_xticklabels(test_names, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("p-value")
    ax.set_ylim(0, 1.05)
    ax.set_title("NIST SP 800-22 — p-values by test and mode")
    ax.legend(fontsize=8, ncol=min(n_modes, 4))
    fig.tight_layout()

    out = out_dir / "nist_pvalues.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


def plot_entropy(all_results, out_dir: Path):
    """Bar chart: Shannon / H∞ / H₂ per mode."""
    modes = list(all_results.keys())
    shannon = [r["shannon_bpb"]       for r in all_results.values()]
    hmin    = [r["min_entropy"]       for r in all_results.values()]
    h2      = [r["collision_entropy"] for r in all_results.values()]

    x  = np.arange(len(modes))
    w  = 0.25
    fig, ax = plt.subplots(figsize=(max(8, len(modes) * 1.2), 5))
    ax.bar(x - w, shannon, w, label="Shannon")
    ax.bar(x,     hmin,    w, label="H∞ (min-entropy)")
    ax.bar(x + w, h2,      w, label="H₂ (collision)")
    ax.set_xticks(x)
    ax.set_xticklabels(modes, rotation=35, ha="right")
    ax.set_ylabel("bits / byte")
    ax.set_ylim(0, 8.5)
    ax.axhline(8.0, color="green", linestyle="--", lw=1.2, label="ideal = 8")
    ax.set_title("Entropy metrics per mode")
    ax.legend()
    fig.tight_layout()

    out = out_dir / "entropy_comparison.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


def plot_linear_complexity(all_results, out_dir: Path):
    """Scatter: mean BM linear complexity per mode."""
    modes = list(all_results.keys())
    means = [r["lc"].get("mean_L", float("nan")) for r in all_results.values()]
    stds  = [r["lc"].get("std_L",  float("nan")) for r in all_results.values()]

    fig, ax = plt.subplots(figsize=(max(7, len(modes) * 1.1), 4))
    x = np.arange(len(modes))
    ax.bar(x, means, yerr=stds, capsize=4, color="#1976D2", alpha=0.8)
    ax.axhline(250, color="red", linestyle="--", lw=1.2, label="ideal = 250 (M/2)")
    ax.set_xticks(x)
    ax.set_xticklabels(modes, rotation=35, ha="right")
    ax.set_ylabel("Mean linear complexity (bits)")
    ax.set_title("Berlekamp-Massey linear complexity per mode")
    ax.legend()
    fig.tight_layout()

    out = out_dir / "linear_complexity.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


def plot_per_test_pvalues(all_results, out_dir: Path):
    """One bar chart per NIST test: p-value per mode, saved to out_dir/per_test/."""
    modes, test_names, matrix = _nist_matrix(all_results)
    n_modes = len(modes)
    per_test_dir = out_dir / "per_test"
    per_test_dir.mkdir(exist_ok=True)

    colors = ["#4CAF50" if v >= 0.01 else "#F44336" for v in [1.0] * n_modes]  # template
    x = np.arange(n_modes)

    for i, tname in enumerate(test_names):
        vals = matrix[i, :]
        bar_colors = []
        for v in vals:
            if np.isnan(v):
                bar_colors.append("#BDBDBD")
            elif v >= 0.01:
                bar_colors.append("#4CAF50")
            else:
                bar_colors.append("#F44336")

        fig, ax = plt.subplots(figsize=(max(6, n_modes * 0.9), 4))
        bars = ax.bar(x, np.where(np.isnan(vals), 0, vals), color=bar_colors,
                      edgecolor="white", linewidth=0.8)

        # annotate bars with p-value text
        for bar, v in zip(bars, vals):
            if np.isnan(v):
                ax.text(bar.get_x() + bar.get_width() / 2, 0.02, "N/A",
                        ha="center", va="bottom", fontsize=8, color="#555555")
            else:
                ax.text(bar.get_x() + bar.get_width() / 2, v + 0.015,
                        f"{v:.4f}", ha="center", va="bottom", fontsize=8)

        ax.axhline(0.01, color="red", linestyle="--", lw=1.5, label="α = 0.01")
        ax.set_xlim(-0.5, n_modes - 0.5)
        ax.set_ylim(0, 1.12)
        ax.set_xticks(x)
        ax.set_xticklabels(modes, rotation=35, ha="right", fontsize=9)
        ax.set_ylabel("p-value")
        ax.set_title(f"NIST T{i+1:02d}: {tname}\np-value per mode  (green ≥ 0.01 = PASS, red = FAIL)",
                     fontsize=10)
        ax.legend(fontsize=9)
        fig.tight_layout()

        safe_name = tname.replace(" ", "_")
        out = per_test_dir / f"t{i+1:02d}_{safe_name}.png"
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {out.relative_to(out_dir.parent)}")


def print_summary_table(all_results):
    """Print ASCII table: modes × tests with p-values."""
    modes, test_names, matrix = _nist_matrix(all_results)
    col_w = max(len(m) for m in modes) + 2
    row_w = max(len(t) for t in test_names) + 2

    header = f"{'Test':<{row_w}}" + "".join(f"{m:>{col_w}}" for m in modes)
    print(header)
    print("-" * len(header))
    for i, tname in enumerate(test_names):
        row = f"{tname:<{row_w}}"
        for j in range(len(modes)):
            v = matrix[i, j]
            if np.isnan(v):
                cell = "N/A"
            else:
                marker = "*" if v < 0.01 else " "
                cell = f"{v:.4f}{marker}"
            row += f"{cell:>{col_w}}"
        print(row)
    print("\n* = FAIL (p < 0.01)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
_ALL_PLOTS = ["heatmap", "pvalue_heatmap", "pvalues", "per_test_pvalues",
              "entropy", "linear_complexity", "summary_table"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache",      default=str(_DEFAULT_CACHE),
                    help="Path to analysis_cache.json")
    ap.add_argument("--output-dir", default=str(_DEFAULT_OUT),
                    help="Directory to write PNG files into")
    ap.add_argument("--plot",       default="all",
                    choices=_ALL_PLOTS + ["all"],
                    help="Which plot(s) to generate")
    args = ap.parse_args()

    cache_path = Path(args.cache)
    out_dir    = Path(args.output_dir)

    if not cache_path.exists():
        print(f"ERROR: cache not found at {cache_path}", file=sys.stderr)
        print("Run analyze.py first to generate the cache.", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading cache from {cache_path} …")
    all_results = _load_cache(cache_path)
    modes = list(all_results.keys())
    print(f"  Found {len(modes)} mode(s): {', '.join(modes)}\n")

    plots = _ALL_PLOTS if args.plot == "all" else [args.plot]

    dispatch = {
        "heatmap":           plot_heatmap,
        "pvalue_heatmap":    plot_pvalue_heatmap,
        "pvalues":           plot_pvalues,
        "per_test_pvalues":  plot_per_test_pvalues,
        "entropy":           plot_entropy,
        "linear_complexity": plot_linear_complexity,
    }

    for name in plots:
        if name == "summary_table":
            print_summary_table(all_results)
        else:
            dispatch[name](all_results, out_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
