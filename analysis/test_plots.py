#!/usr/bin/env python3
"""
test_plots.py — One diagnostic plot per NIST SP 800-22 test.

Each plot shows the actual test statistic (DFT spectrum, random walk,
run-length histogram, …) so a FAIL is immediately visually interpretable.
Red title = FAIL, green = PASS, grey = N/A.
"""

import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PASS_COLOR = "#4CAF50"
FAIL_COLOR = "#F44336"
NA_COLOR   = "#9E9E9E"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _status(result: dict):
    if not result.get("eligible", True):
        return NA_COLOR, "N/A"
    ok = result.get("passed", False)
    return (PASS_COLOR if ok else FAIL_COLOR), f"{'PASS' if ok else 'FAIL'}  p={result['score']:.2e}"


def _suptitle(fig, mode: str, label: str, result: dict):
    color, status = _status(result)
    fig.suptitle(f"{mode}  |  {label}  |  {status}",
                 fontsize=10, fontweight="bold", color="white",
                 bbox=dict(facecolor=color, boxstyle="round,pad=0.4"))


def _border(ax, result: dict):
    color, _ = _status(result)
    for sp in ax.spines.values():
        sp.set_edgecolor(color); sp.set_linewidth(3)


def _finish(fig, out_path):
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _na(mode, label, result, out_path):
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.text(0.5, 0.5, "N/A — test not eligible", ha="center", va="center",
            transform=ax.transAxes, fontsize=13, color="gray", fontweight="bold")
    ax.axis("off")
    _suptitle(fig, mode, label, result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T01 — Monobit (Frequency)
# Shows: proportion of 0s vs 1s vs ideal 0.5
# ---------------------------------------------------------------------------

def plot_t01(bits, result, out_path, mode):
    n = len(bits); n1 = int(np.sum(bits)); p1 = n1 / n; p0 = 1 - p1
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(["0-bits", "1-bits"], [p0, p1],
                  color=["#2196F3", "#FF9800"], edgecolor="black", lw=0.5, width=0.45)
    ax.axhline(0.5, color="green", ls="--", lw=2, label="Ideal 0.5")
    ax.axhline(0.505, color="orange", ls=":", lw=1)
    ax.axhline(0.495, color="orange", ls=":", lw=1, label="±0.5 % band")
    for bar, v in zip(bars, [p0, p1]):
        ax.text(bar.get_x() + bar.get_width()/2, v + 3e-4, f"{v:.6f}",
                ha="center", va="bottom", fontsize=10)
    ax.set_ylim(0.47, 0.53); ax.set_ylabel("Proportion"); ax.legend(fontsize=8)
    _border(ax, result); _suptitle(fig, mode, "T01 Monobit — bit proportion", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T02 — Frequency within Block
# Shows: histogram of per-block 1-bit proportions; should bell around 0.5
# ---------------------------------------------------------------------------

def plot_t02(bits, result, out_path, mode, M=128):
    n_b = len(bits) // M; use = min(n_b, 8000)
    props = np.array([np.mean(bits[i*M:(i+1)*M]) for i in range(use)])
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.hist(props, bins=60, color="#2196F3", edgecolor="black", lw=0.2, alpha=0.85)
    ax.axvline(0.5, color="green", ls="--", lw=2, label="Ideal 0.5")
    ax.set_xlabel(f"Proportion of 1-bits per {M}-bit block  ({use:,} blocks)")
    ax.set_ylabel("Block count"); ax.legend(fontsize=8)
    _border(ax, result)
    _suptitle(fig, mode, f"T02 Block Frequency (M={M}) — block proportion histogram", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T03 — Runs
# Shows: observed vs expected run-length counts
# ---------------------------------------------------------------------------

def plot_t03(bits, result, out_path, mode):
    b = bits.astype(np.int8)
    d = np.diff(np.concatenate(([b[0]^1], b, [b[-1]^1])))
    starts = np.where(d == 1)[0]; ends = np.where(d == -1)[0]
    rl = ends - starts
    n = len(bits); mx = min(int(rl.max()), 25)
    obs = np.array([np.sum(rl == k) for k in range(1, mx+1)])
    exp = np.array([(n-k+3) / 2**(k+2) for k in range(1, mx+1)])
    x = np.arange(1, mx+1)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(x-0.2, obs, 0.38, label="Observed", color="#2196F3",  edgecolor="black", lw=0.3, alpha=0.85)
    ax.bar(x+0.2, exp, 0.38, label="Expected (random)",  color="#FF9800", edgecolor="black", lw=0.3, alpha=0.85)
    ax.set_xlabel("Run length"); ax.set_ylabel("Count")
    ax.set_xlim(0.5, mx+0.5); ax.legend(fontsize=8)
    ax.text(0.98, 0.95, f"Total runs: {len(rl):,}\nExpected ≈ {n//2:,}",
            transform=ax.transAxes, ha="right", va="top", fontsize=8,
            bbox=dict(boxstyle="round", fc="wheat", alpha=0.8))
    _border(ax, result)
    _suptitle(fig, mode, "T03 Runs — run-length distribution vs expected", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T04 — Longest Run of Ones in a Block
# Shows: histogram of longest-run lengths per block
# ---------------------------------------------------------------------------

def plot_t04(bits, result, out_path, mode, block_sz=10_000):
    n_b = len(bits) // block_sz; use = min(n_b, 800)
    longest = []
    for i in range(use):
        blk = bits[i*block_sz:(i+1)*block_sz].astype(np.int8)
        d   = np.diff(np.concatenate(([0], blk, [0])))
        s   = np.where(d == 1)[0]; e = np.where(d == -1)[0]
        longest.append(int(np.max(e - s)) if len(s) else 0)
    arr = np.array(longest)
    fig, ax = plt.subplots(figsize=(9, 4))
    lo, hi = int(arr.min()), int(arr.max())
    ax.hist(arr, bins=range(lo, hi+2), color="#9C27B0", edgecolor="black", lw=0.3, alpha=0.85)
    ax.axvline(np.mean(arr), color="red",   ls="-",  lw=2, label=f"Mean = {np.mean(arr):.1f}")
    ax.axvline(math.log2(block_sz), color="green", ls="--", lw=2,
               label=f"log₂({block_sz//1000}K) ≈ {math.log2(block_sz):.1f}")
    ax.set_xlabel(f"Longest run of 1s per {block_sz//1000}K-bit block  ({use} blocks)")
    ax.set_ylabel("Block count"); ax.legend(fontsize=8)
    _border(ax, result)
    _suptitle(fig, mode, "T04 Longest Run — distribution of max run per block", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T05 — Binary Matrix Rank
# Shows: observed rank distribution vs NIST expected proportions
# ---------------------------------------------------------------------------

def _gf2_rank(mat):
    m = mat.copy(); R, rows, cols = 0, *m.shape
    for c in range(cols):
        piv = next((r for r in range(R, rows) if m[r, c]), None)
        if piv is None: continue
        m[[R, piv]] = m[[piv, R]]
        for r in range(rows):
            if r != R and m[r, c]: m[r] ^= m[R]
        R += 1
    return R

def plot_t05(bits, result, out_path, mode, M=32, Q=32):
    bk = M*Q; n_m = len(bits)//bk; use = min(n_m, 300)
    ranks = [_gf2_rank(bits[i*bk:(i+1)*bk].reshape(M, Q)) for i in range(use)]
    ranks = np.array(ranks); tot = len(ranks)
    exp = {M: 0.2888*tot, M-1: 0.5776*tot, M-2: 0.1336*tot}
    vals = sorted(set(ranks.tolist()) | set(exp))
    obs_c = [int(np.sum(ranks == v)) for v in vals]
    exp_c = [exp.get(v, 0) for v in vals]
    x = np.arange(len(vals))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(x-0.2, obs_c, 0.38, label="Observed", color="#2196F3", edgecolor="black", lw=0.3)
    ax.bar(x+0.2, exp_c, 0.38, label="Expected",  color="#FF9800", edgecolor="black", lw=0.3)
    ax.set_xticks(x); ax.set_xticklabels([str(v) for v in vals])
    ax.set_xlabel(f"GF(2) matrix rank  ({use} × {M}×{Q} matrices)")
    ax.set_ylabel("Count"); ax.legend(fontsize=8)
    _border(ax, result)
    _suptitle(fig, mode, f"T05 Binary Matrix Rank ({M}×{Q}) — rank distribution", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T06 — DFT / Spectral
# Shows: |DFT| magnitude spectrum with 95 % threshold; peaks above = red fill
# ---------------------------------------------------------------------------

def plot_t06(bits, result, out_path, mode):
    N = min(len(bits), 1_000_000)
    if N % 2: N -= 1
    x   = bits[:N].astype(np.float64) * 2 - 1          # {-1, +1}
    X   = np.abs(np.fft.rfft(x))[1:N//2]               # skip DC
    thr = math.sqrt(math.log(1/0.05) * N)
    n_exc = int(np.sum(X > thr)); n_exp = int(0.05 * len(X))

    show = min(len(X), 20_000)
    freqs = np.arange(1, show+1) / N
    exc_mask = X[:show] > thr

    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(freqs, X[:show], lw=0.3, alpha=0.6, color="#2196F3", label="|DFT(f)|")
    ax.axhline(thr, color="red", lw=1.5, ls="--", label=f"95 % threshold = {thr:.1f}")
    if np.any(exc_mask):
        ax.fill_between(freqs, thr, np.where(exc_mask, X[:show], thr),
                        color="red", alpha=0.55,
                        label=f"{n_exc} peaks > threshold  (expected ≤ {n_exp})")
    ax.set_xlabel(f"Frequency (cycles per bit) — first {show:,} of {len(X):,} components  [N={N:,} bits]")
    ax.set_ylabel("|DFT coefficient|"); ax.legend(fontsize=8)
    ax.text(0.98, 0.95,
            f"Peaks above threshold: {n_exc}\nExpected (5 %): ~{n_exp}",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            bbox=dict(boxstyle="round", fc="wheat", alpha=0.85))
    _border(ax, result)
    _suptitle(fig, mode, "T06 DFT / Spectral — frequency-domain magnitude spectrum", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T07 — Non-overlapping Template Matching
# Shows: per-block template hit count vs expected μ ± 2σ
# ---------------------------------------------------------------------------

def plot_t07(bits, result, out_path, mode, N_blocks=8):
    tmpl = np.array([1,1,1,1,1,1,1,1], dtype=np.int8); m = len(tmpl)
    bsz  = len(bits) // N_blocks
    counts = []
    for i in range(N_blocks):
        blk = bits[i*bsz:(i+1)*bsz]
        wins = np.lib.stride_tricks.sliding_window_view(blk, m)
        counts.append(int(np.sum(np.all(wins == tmpl, axis=1))))
    mu    = (bsz - m + 1) / 2**m
    sigma = math.sqrt(bsz * (1/2**m - (2*m-1)/2**(2*m)))
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(range(N_blocks), counts, color="#2196F3", edgecolor="black", lw=0.4, alpha=0.85, label="Observed Wⱼ")
    ax.axhline(mu,           color="green",  ls="--", lw=2,   label=f"Expected μ = {mu:.1f}")
    ax.axhline(mu + 2*sigma, color="orange", ls=":",  lw=1.5, label="μ ± 2σ")
    ax.axhline(mu - 2*sigma, color="orange", ls=":",  lw=1.5)
    ax.set_xlabel("Block index j"); ax.set_ylabel("Template hit count Wⱼ"); ax.legend(fontsize=8)
    _border(ax, result)
    _suptitle(fig, mode, f"T07 Non-overlapping Template [{list(tmpl)}]", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T08 — Overlapping Template Matching
# Shows: histogram of per-block hit counts
# ---------------------------------------------------------------------------

def plot_t08(bits, result, out_path, mode, M=1032, K=5):
    tmpl = np.array([1]*9, dtype=np.int8); m = len(tmpl)
    n_b  = min(len(bits) // M, 968)
    counts = []
    for i in range(n_b):
        blk  = bits[i*M:(i+1)*M]
        wins = np.lib.stride_tricks.sliding_window_view(blk, m)
        counts.append(min(int(np.sum(np.all(wins == tmpl, axis=1))), K))
    vals, cnts = np.unique(counts, return_counts=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(vals, cnts, color="#9C27B0", edgecolor="black", lw=0.3, alpha=0.85)
    ax.set_xlabel(f"Overlapping template hits per {M}-bit block (capped at {K})  [{n_b:,} blocks]")
    ax.set_ylabel("Block count")
    _border(ax, result)
    _suptitle(fig, mode, f"T08 Overlapping Template [{'1'*9}]", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T09 — Maurer's Universal Statistical
# Shows: fn = log₂(gap) time series vs expected value
# ---------------------------------------------------------------------------

def plot_t09(bits, result, out_path, mode, L=7, Q=1280):
    n_b = len(bits) // L
    if n_b < Q + 500:
        return _na(mode, "T09 Maurer's Universal", result, out_path)
    mat  = bits[:n_b*L].reshape(n_b, L).astype(np.uint8)
    vals = mat.dot(1 << np.arange(L-1, -1, -1, dtype=np.uint8))
    last = np.full(2**L, -1, dtype=np.int64)
    fn   = []
    for i in range(n_b):
        v = int(vals[i])
        if i >= Q and last[v] >= 0:
            fn.append(math.log2(i - last[v]))
        last[v] = i
    if not fn:
        return _na(mode, "T09 Maurer's Universal", result, out_path)
    fn_arr  = np.array(fn); mean_fn = float(np.mean(fn_arr))
    exp_tbl = {7: 6.1962, 6: 5.2177, 5: 4.2534, 8: 7.1836}
    exp     = exp_tbl.get(L, L - 1.0)
    show    = min(len(fn), 8000)
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(fn[:show], lw=0.4, alpha=0.7, color="#2196F3")
    ax.axhline(mean_fn, color="red",   ls="--", lw=1.5, label=f"fn mean = {mean_fn:.4f}")
    ax.axhline(exp,     color="green", ls="--", lw=1.5, label=f"Expected = {exp:.4f}")
    ax.set_xlabel(f"Block index (after Q={Q} init period)  [first {show:,} shown]")
    ax.set_ylabel(f"log₂(gap to last {L}-bit pattern)"); ax.legend(fontsize=8)
    _border(ax, result)
    _suptitle(fig, mode, f"T09 Maurer's Universal (L={L}) — fn time series", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T10 — Linear Complexity  (BM data passed in from analyze.py)
# Shows: L histogram; ideal L = M/2 = 250
# ---------------------------------------------------------------------------

def plot_t10(bits, result, out_path, mode, lc_data=None):
    if not lc_data or not lc_data.get("L_values"):
        return _na(mode, "T10 Linear Complexity (no BM data)", result, out_path)
    L_arr  = np.array(lc_data["L_values"])
    ideal  = lc_data["ideal_L"]; mean_L = lc_data["mean_L"]; frac = lc_data["frac_low"]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(L_arr, bins=30, color="#FF5722", edgecolor="black", lw=0.3, alpha=0.85)
    ax.axvline(ideal,  color="green", lw=2, ls="--", label=f"Ideal M/2 = {ideal:.0f}")
    ax.axvline(mean_L, color="red",   lw=2, ls="-",  label=f"Observed mean = {mean_L:.1f}")
    ax.set_xlabel("Shortest LFSR length L per 500-bit block"); ax.set_ylabel("Block count")
    ax.legend(fontsize=8)
    verdict = f"{'PREDICTABLE' if frac > 0.5 else 'random-like'}  ({frac*100:.1f} % blocks L < {ideal*0.75:.0f})"
    ax.text(0.02, 0.95, verdict, transform=ax.transAxes, va="top", fontsize=9,
            color="red" if frac > 0.5 else "green", fontweight="bold",
            bbox=dict(boxstyle="round", fc="white", alpha=0.8))
    _border(ax, result)
    _suptitle(fig, mode, "T10 Linear Complexity (BM) — LFSR length distribution", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T11 — Serial
# Shows: 2-bit and 3-bit overlapping pattern counts vs expected uniform
# ---------------------------------------------------------------------------

def plot_t11(bits, result, out_path, mode):
    n  = len(bits)
    p2 = bits[:-1].astype(np.int32)*2 + bits[1:].astype(np.int32)
    p3 = bits[:-2].astype(np.int32)*4 + bits[1:-1].astype(np.int32)*2 + bits[2:].astype(np.int32)
    c2 = np.array([np.sum(p2 == v) for v in range(4)]); e2 = (n-1)/4
    c3 = np.array([np.sum(p3 == v) for v in range(8)]); e3 = (n-2)/8
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4))
    x2 = np.arange(4)
    ax1.bar(x2-0.2, c2,    0.38, label="Observed", color="#2196F3", edgecolor="black", lw=0.3)
    ax1.bar(x2+0.2, [e2]*4, 0.38, label="Expected", color="#FF9800", edgecolor="black", lw=0.3)
    ax1.set_xticks(x2); ax1.set_xticklabels(["00","01","10","11"])
    ax1.set_xlabel("2-bit pattern"); ax1.set_ylabel("Count"); ax1.set_title("2-bit patterns"); ax1.legend(fontsize=8)
    x3 = np.arange(8)
    ax2.bar(x3-0.2, c3,    0.38, label="Observed", color="#9C27B0", edgecolor="black", lw=0.3)
    ax2.bar(x3+0.2, [e3]*8, 0.38, label="Expected", color="#FF9800", edgecolor="black", lw=0.3)
    ax2.set_xticks(x3); ax2.set_xticklabels(["000","001","010","011","100","101","110","111"], rotation=30)
    ax2.set_xlabel("3-bit pattern"); ax2.set_ylabel("Count"); ax2.set_title("3-bit patterns"); ax2.legend(fontsize=8)
    color, status = _status(result)
    fig.suptitle(f"{mode}  |  T11 Serial  |  {status}", fontsize=10, fontweight="bold",
                 color="white", bbox=dict(facecolor=color, boxstyle="round,pad=0.4"))
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------------
# T12 — Approximate Entropy
# Shows: computed ApEn vs ideal ln(2); bit-entropy per 1000-bit chunk
# ---------------------------------------------------------------------------

def plot_t12(bits, result, out_path, mode, m=10):
    sub = bits[:min(len(bits), 100_000)]; n = len(sub)
    def phi(ml):
        w   = np.lib.stride_tricks.sliding_window_view(sub, ml)
        k   = w.dot(1 << np.arange(ml-1, -1, -1))
        _, c = np.unique(k, return_counts=True)
        p   = c / (n - ml + 1)
        return float(np.sum(p * np.log(p)))
    apen  = phi(m) - phi(m+1)
    ideal = math.log(2)

    # Chunk entropy: proportion of 1s per 1000-bit window
    ck = 1000; n_ck = len(bits) // ck
    use = min(n_ck, 8000)
    chunk_ent = np.array([float(np.mean(bits[i*ck:(i+1)*ck])) for i in range(use)])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    ax1.bar(["ApEn (observed)", "ln(2) ideal"], [apen, ideal],
            color=["#2196F3", "#4CAF50"], edgecolor="black", lw=0.5, width=0.45)
    for i, v in enumerate([apen, ideal]):
        ax1.text(i, v + 0.001, f"{v:.5f}", ha="center", va="bottom", fontsize=10)
    ax1.set_ylabel(f"Approximate Entropy (m={m})"); ax1.set_title(f"ApEn vs ideal  [n={n:,}]")

    ax2.hist(chunk_ent, bins=60, color="#FF9800", edgecolor="black", lw=0.2, alpha=0.85)
    ax2.axvline(0.5, color="green", ls="--", lw=2, label="Ideal 0.5")
    ax2.set_xlabel(f"Proportion of 1s per {ck}-bit chunk  ({use:,} chunks)")
    ax2.set_ylabel("Count"); ax2.set_title("Per-chunk bit proportion"); ax2.legend(fontsize=8)

    color, status = _status(result)
    fig.suptitle(f"{mode}  |  T12 Approximate Entropy  |  {status}", fontsize=10,
                 fontweight="bold", color="white",
                 bbox=dict(facecolor=color, boxstyle="round,pad=0.4"))
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------------
# T13 — Cumulative Sums
# Shows: forward and backward random walk with max excursion lines
# ---------------------------------------------------------------------------

def plot_t13(bits, result, out_path, mode):
    w      = bits.astype(np.int64) * 2 - 1
    fwd    = np.cumsum(w); bwd = np.cumsum(w[::-1])
    z_fwd  = int(np.max(np.abs(fwd))); z_bwd = int(np.max(np.abs(bwd)))
    N_show = min(len(bits), 100_000)
    exp    = math.sqrt(N_show)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    for ax, data, z, col, lab in [(ax1, fwd[:N_show], z_fwd, "#2196F3", "Forward"),
                                   (ax2, bwd[:N_show], z_bwd, "#FF5722", "Backward")]:
        ax.plot(data, lw=0.4, color=col, alpha=0.8)
        ax.axhline(0,    color="black",  lw=0.8)
        ax.axhline( z,   color="red",    ls="--", lw=1.5, label=f"Max |S| = {z}  (full sequence)")
        ax.axhline(-z,   color="red",    ls="--", lw=1.5)
        ax.axhline( exp, color="green",  ls=":",  lw=1,   label=f"√n = {exp:.0f}")
        ax.axhline(-exp, color="green",  ls=":",  lw=1)
        ax.set_ylabel("Cumulative sum S"); ax.set_title(f"{lab} walk"); ax.legend(fontsize=7)
    ax2.set_xlabel(f"Step  (first {N_show:,} of {len(bits):,} bits shown)")
    color, status = _status(result)
    fig.suptitle(f"{mode}  |  T13 Cumulative Sums  |  {status}", fontsize=10,
                 fontweight="bold", color="white",
                 bbox=dict(facecolor=color, boxstyle="round,pad=0.4"))
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------------
# T14 — Random Excursions
# Shows: visit counts ξ(x) per state ±1..±4 vs J (cycle count)
# ---------------------------------------------------------------------------

def plot_t14(bits, result, out_path, mode):
    w = bits.astype(np.int64) * 2 - 1
    s = np.concatenate(([0], np.cumsum(w), [0]))
    J = int(np.count_nonzero(s[1:] == 0))
    if J < 500:
        return _na(mode, f"T14 Random Excursions  (J={J} < 500)", result, out_path)
    states = [-4,-3,-2,-1,1,2,3,4]
    obs    = [int(np.sum(s == x)) for x in states]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(range(len(states)), obs, color="#2196F3", edgecolor="black", lw=0.4, alpha=0.85,
           label="Observed ξ(x)")
    ax.axhline(J, color="green", ls="--", lw=2, label=f"J (cycles) = {J:,}")
    ax.set_xticks(range(len(states))); ax.set_xticklabels([str(x) for x in states])
    ax.set_xlabel("State x"); ax.set_ylabel("Cycle visit count ξ(x)"); ax.legend(fontsize=8)
    ax.text(0.98, 0.95, f"J = {J:,} zero-crossing cycles",
            transform=ax.transAxes, ha="right", va="top", fontsize=8,
            bbox=dict(boxstyle="round", fc="wheat", alpha=0.8))
    _border(ax, result)
    _suptitle(fig, mode, "T14 Random Excursions — state visit counts vs J", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# T15 — Random Excursion Variant
# Shows: total visit count ξ(x) for ±1..±9 with ±2σ bands; red = outlier
# ---------------------------------------------------------------------------

def plot_t15(bits, result, out_path, mode):
    w = bits.astype(np.int64) * 2 - 1
    s = np.concatenate(([0], np.cumsum(w), [0]))
    J = int(np.count_nonzero(s[1:] == 0))
    if J < 500:
        return _na(mode, f"T15 Random Excursion Variant  (J={J} < 500)", result, out_path)
    states = [x for x in range(-9, 10) if x != 0]
    counts = [int(np.sum(s == x)) for x in states]
    sigmas = [math.sqrt(2*J*(4*abs(x)-2)) for x in states]
    zs     = [abs(c - J) / sig for c, sig in zip(counts, sigmas)]
    colors = ["#F44336" if z > 1.96 else "#2196F3" for z in zs]
    x_idx  = np.arange(len(states))
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(x_idx, counts, color=colors, edgecolor="black", lw=0.3, alpha=0.85,
           label="Observed ξ(x)  (red = |z| > 1.96)")
    ax.axhline(J, color="green", ls="--", lw=2, label=f"Expected ≈ J = {J:,}")
    for i, (sig, _) in enumerate(zip(sigmas, states)):
        ax.plot([i-0.4, i+0.4], [J+2*sig, J+2*sig], color="orange", lw=1.5)
        ax.plot([i-0.4, i+0.4], [J-2*sig, J-2*sig], color="orange", lw=1.5)
    ax.set_xticks(x_idx); ax.set_xticklabels([str(x) for x in states])
    ax.set_xlabel("State x  (red bars: |z-score| > 1.96, orange = ±2σ per state)")
    ax.set_ylabel("Total visit count ξ(x)"); ax.legend(fontsize=8)
    ax.text(0.98, 0.95, f"J = {J:,}", transform=ax.transAxes, ha="right", va="top",
            fontsize=9, bbox=dict(boxstyle="round", fc="wheat", alpha=0.8))
    _border(ax, result)
    _suptitle(fig, mode, "T15 Random Excursion Variant — state visit counts", result)
    _finish(fig, out_path)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_MAP = {
    "monobit":                           ("T01_frequency.png",                    plot_t01),
    "frequency_within_block":            ("T02_block_frequency.png",              plot_t02),
    "runs":                              ("T03_runs.png",                         plot_t03),
    "longest_run_ones_in_a_block":       ("T04_longest_run.png",                  plot_t04),
    "binary_matrix_rank":                ("T05_matrix_rank.png",                  plot_t05),
    "dft":                               ("T06_dft.png",                          plot_t06),
    "non_overlapping_template_matching": ("T07_nonoverlapping_template.png",      plot_t07),
    "overlapping_template_matching":     ("T08_overlapping_template.png",         plot_t08),
    "maurers_universal":                 ("T09_maurers_universal.png",            plot_t09),
    "linear_complexity":                 ("T10_linear_complexity.png",            plot_t10),
    "serial":                            ("T11_serial.png",                       plot_t11),
    "approximate_entropy":               ("T12_approx_entropy.png",              plot_t12),
    "cumulative sums":                   ("T13_cumulative_sums.png",             plot_t13),
    "random_excursion":                  ("T14_random_excursions.png",           plot_t14),
    "random_excursion_variant":          ("T15_random_excursion_variant.png",    plot_t15),
}


def plot_all_tests(bits: np.ndarray, nist_results: dict, mode_name: str,
                   out_dir: str, lc_data: dict = None) -> None:
    """
    Generate one diagnostic PNG per NIST test into out_dir.

    Parameters
    ----------
    bits         : int8 array of 0/1 bits
    nist_results : dict keyed by nistrng battery key → {score, passed, eligible}
    mode_name    : display name e.g. "BARE"
    out_dir      : output directory (created if absent)
    lc_data      : output of analyze.linear_complexity_profile() for T10
    """
    os.makedirs(out_dir, exist_ok=True)
    for key, (fname, fn) in _MAP.items():
        r        = nist_results.get(key, {"score": -1.0, "passed": False, "eligible": False})
        out_path = os.path.join(out_dir, fname)
        try:
            if key == "linear_complexity":
                fn(bits, r, out_path, mode_name, lc_data=lc_data)
            else:
                fn(bits, r, out_path, mode_name)
        except Exception as exc:
            print(f"      [warn] {fname}: {exc}")
